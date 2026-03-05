"""Re-ranking module for improving retrieval precision (RAGFlow fused re-ranking pattern).

Supports both API-based (Cohere) and LLM-based re-ranking.
"""

import httpx
import structlog

from app.config import get_settings
from app.rag.retrieval.base import RetrievalResult

logger = structlog.get_logger()


class LLMReranker:
    """Re-rank results using the LLM itself to score relevance.
    This is a fallback when no dedicated reranker API is available."""

    def __init__(self, llm_provider=None):
        self._llm = llm_provider

    async def rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        if not results or not self._llm:
            return results[:top_k]

        prompt = self._build_rerank_prompt(query, results)

        try:
            response = await self._llm.generate(
                prompt,
                system="You are a relevance scoring assistant. Score each passage's relevance to the query from 0.0 to 1.0. Return ONLY a JSON array of scores.",
                temperature=0.0,
                max_tokens=200,
            )
            import json
            scores = json.loads(response.content)

            for i, result in enumerate(results):
                if i < len(scores):
                    result.score = float(scores[i])
                    result.metadata["reranked"] = True

            results.sort(key=lambda r: r.score, reverse=True)
        except Exception as e:
            logger.warning("LLM reranking failed, using original scores", error=str(e))

        return results[:top_k]

    def _build_rerank_prompt(self, query: str, results: list[RetrievalResult]) -> str:
        passages = "\n\n".join(
            f"Passage {i+1}: {r.content[:500]}" for i, r in enumerate(results)
        )
        return f"""Query: {query}

{passages}

Score each passage's relevance to the query from 0.0 to 1.0. Return ONLY a JSON array of numbers, e.g. [0.9, 0.3, 0.7, ...]"""


class CohereReranker:
    """Re-rank using Cohere's rerank API for production-grade relevance scoring."""

    def __init__(self, api_key: str | None = None, model: str = "rerank-v3.5"):
        self.model = model
        self._api_key = api_key

    async def rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        if not results or not self._api_key:
            return results[:top_k]

        documents = [r.content[:4096] for r in results]

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.cohere.ai/v1/rerank",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "query": query,
                        "documents": documents,
                        "top_n": top_k,
                    },
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()

            reranked = []
            for item in data["results"]:
                idx = item["index"]
                result = results[idx]
                result.score = item["relevance_score"]
                result.metadata["reranked"] = True
                result.metadata["reranker"] = "cohere"
                reranked.append(result)

            return reranked
        except Exception as e:
            logger.warning("Cohere reranking failed", error=str(e))
            return results[:top_k]
