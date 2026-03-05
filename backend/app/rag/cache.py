"""Semantic query cache using Redis + embedding similarity.

Caches RAG responses for semantically similar queries to avoid
redundant LLM calls. Uses cosine similarity on query embeddings
to detect near-duplicate questions.
"""

import hashlib
import json
import time

import numpy as np
import structlog

from app.rag.embeddings.base import BaseEmbedding

logger = structlog.get_logger()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a, dtype=np.float32)
    b_arr = np.array(b, dtype=np.float32)
    dot = np.dot(a_arr, b_arr)
    norm = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
    if norm == 0:
        return 0.0
    return float(dot / norm)


class SemanticCache:
    """Cache RAG responses keyed by semantic query similarity.

    Flow:
    1. Embed incoming query
    2. Scan cached query embeddings for this workspace
    3. If any cached embedding has cosine similarity >= threshold, return cached response
    4. Otherwise, miss — caller runs full pipeline and calls set() afterward

    For production scale, replace brute-force scan with Redis Vector Search (RediSearch).
    """

    def __init__(
        self,
        redis_client,
        embedding: BaseEmbedding,
        threshold: float = 0.95,
        max_cache_entries: int = 1000,
    ):
        self.redis = redis_client
        self.embedding = embedding
        self.threshold = threshold
        self.max_cache_entries = max_cache_entries

    def _cache_prefix(self, workspace_id: str) -> str:
        return f"rag_cache:{workspace_id}"

    async def get(self, query: str, workspace_id: str) -> dict | None:
        """Check for a semantically similar cached query.

        Returns the cached response dict, or None on miss.
        """
        try:
            query_embedding = await self.embedding.embed_text(query)
            prefix = self._cache_prefix(workspace_id)

            # Scan cached entries (brute-force for now)
            cursor = 0
            while True:
                cursor, keys = await self.redis.scan(
                    cursor=cursor, match=f"{prefix}:*", count=100,
                )
                for key in keys:
                    cached_data = await self.redis.hgetall(key)
                    if not cached_data:
                        continue

                    # Decode bytes if needed
                    emb_raw = cached_data.get(b"embedding") or cached_data.get("embedding")
                    if not emb_raw:
                        continue
                    if isinstance(emb_raw, bytes):
                        emb_raw = emb_raw.decode()

                    cached_embedding = json.loads(emb_raw)
                    similarity = _cosine_similarity(query_embedding, cached_embedding)

                    if similarity >= self.threshold:
                        resp_raw = cached_data.get(b"response") or cached_data.get("response")
                        if isinstance(resp_raw, bytes):
                            resp_raw = resp_raw.decode()
                        logger.info("semantic_cache_hit", similarity=round(similarity, 4), query=query[:60])
                        return json.loads(resp_raw)

                if cursor == 0:
                    break

            return None

        except Exception as e:
            logger.warning("semantic_cache_get_error", error=str(e))
            return None

    async def set(
        self,
        query: str,
        workspace_id: str,
        response: dict,
        ttl: int = 3600,
    ):
        """Cache a query-response pair."""
        try:
            query_embedding = await self.embedding.embed_text(query)
            query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
            cache_key = f"{self._cache_prefix(workspace_id)}:{query_hash}"

            await self.redis.hset(cache_key, mapping={
                "embedding": json.dumps(query_embedding),
                "response": json.dumps(response),
                "query": query,
                "created_at": str(time.time()),
            })
            await self.redis.expire(cache_key, ttl)

            logger.info("semantic_cache_set", key=cache_key, ttl=ttl)

        except Exception as e:
            logger.warning("semantic_cache_set_error", error=str(e))

    async def invalidate_workspace(self, workspace_id: str):
        """Invalidate all cached entries for a workspace (e.g., when docs change)."""
        try:
            prefix = self._cache_prefix(workspace_id)
            cursor = 0
            deleted = 0
            while True:
                cursor, keys = await self.redis.scan(
                    cursor=cursor, match=f"{prefix}:*", count=100,
                )
                if keys:
                    await self.redis.delete(*keys)
                    deleted += len(keys)
                if cursor == 0:
                    break
            logger.info("semantic_cache_invalidated", workspace_id=workspace_id, deleted=deleted)
        except Exception as e:
            logger.warning("semantic_cache_invalidate_error", error=str(e))
