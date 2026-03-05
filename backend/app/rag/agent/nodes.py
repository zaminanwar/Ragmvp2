"""Agent node functions for the agentic RAG pipeline.

Each node is an async function: (state, **bound_deps) -> partial state update dict.
Dependencies (llm, retriever, reranker) are bound via functools.partial at graph build time.
"""

import asyncio
import time
from uuid import UUID

import structlog

from app.rag.agent.output_parser import parse_json_response, parse_json_array
from app.rag.agent.prompts import (
    DECOMPOSE_PROMPT,
    GRADER_PROMPT,
    GENERATOR_PROMPT,
    HALLUCINATION_PROMPT,
    HYDE_PROMPT,
    REWRITE_PROMPT,
    ROUTER_PROMPT,
)
from app.rag.llm.base import BaseLLM
from app.rag.retrieval.base import BaseRetriever, RetrievalResult

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Node: Route Query
# ---------------------------------------------------------------------------

async def route_query(state: dict, *, llm: BaseLLM) -> dict:
    """Classify query intent and select optimal retrieval strategy."""
    question = state["question"]
    start = time.monotonic()

    response = await llm.generate(
        prompt=ROUTER_PROMPT.format(question=question),
        temperature=0.0,
        max_tokens=150,
    )

    parsed = parse_json_response(response.content, default={"search_mode": "hybrid"})
    search_mode = parsed.get("search_mode", "hybrid")
    if search_mode not in ("vector", "fulltext", "hybrid"):
        search_mode = "hybrid"

    duration = time.monotonic() - start
    logger.info("agent.route_query", mode=search_mode, duration_ms=round(duration * 1000))

    return {
        "query_type": search_mode,
        "search_mode_used": search_mode,
        "agent_trace": [f"route_query -> {search_mode}"],
        "total_input_tokens": state.get("total_input_tokens", 0) + response.input_tokens,
        "total_output_tokens": state.get("total_output_tokens", 0) + response.output_tokens,
    }


# ---------------------------------------------------------------------------
# Node: Retrieve
# ---------------------------------------------------------------------------

async def retrieve(state: dict, *, retriever: BaseRetriever) -> dict:
    """Fetch documents using the selected retrieval strategy."""
    query = state.get("rewritten_question") or state["question"]
    workspace_id = UUID(state["workspace_id"])
    top_k = state.get("top_k", 5)
    start = time.monotonic()

    results = await retriever.retrieve(query, workspace_id, top_k=top_k)

    # Convert RetrievalResult objects to serializable dicts for state
    documents = [
        {
            "chunk_id": str(r.chunk_id),
            "document_id": str(r.document_id),
            "content": r.content,
            "score": r.score,
            "metadata": r.metadata,
            "source": r.source,
        }
        for r in results
    ]

    attempts = state.get("retrieval_attempts", 0) + 1
    duration = time.monotonic() - start
    logger.info("agent.retrieve", count=len(documents), attempts=attempts, duration_ms=round(duration * 1000))

    return {
        "documents": documents,
        "retrieval_attempts": attempts,
        "agent_trace": [f"retrieve -> {len(documents)} docs (attempt {attempts})"],
    }


# ---------------------------------------------------------------------------
# Node: HyDE Retrieve (Hypothetical Document Embeddings)
# ---------------------------------------------------------------------------

async def hyde_retrieve(state: dict, *, llm: BaseLLM, retriever: BaseRetriever, embedding_provider) -> dict:
    """Generate hypothetical answer, embed it, retrieve similar docs."""
    question = state["question"]
    workspace_id = UUID(state["workspace_id"])
    top_k = state.get("top_k", 5)
    start = time.monotonic()

    # Generate hypothetical document
    response = await llm.generate(
        prompt=HYDE_PROMPT.format(question=question),
        temperature=0.3,
        max_tokens=500,
    )
    hypothetical_doc = response.content.strip()

    # Embed the hypothetical document
    hyde_embedding = await embedding_provider.embed_text(hypothetical_doc)

    # Retrieve using hypothetical embedding
    # We need to call vector retriever directly with pre-computed embedding
    from app.rag.retrieval.vector_search import VectorRetriever
    if hasattr(retriever, 'vector_retriever') and isinstance(retriever.vector_retriever, VectorRetriever):
        results = await retriever.vector_retriever.retrieve_by_embedding(
            embedding=hyde_embedding, workspace_id=workspace_id, top_k=top_k
        )
    else:
        # Fallback to standard retrieval
        results = await retriever.retrieve(question, workspace_id, top_k=top_k)

    documents = [
        {
            "chunk_id": str(r.chunk_id),
            "document_id": str(r.document_id),
            "content": r.content,
            "score": r.score,
            "metadata": {**r.metadata, "hyde_used": True},
            "source": r.source,
        }
        for r in results
    ]

    attempts = state.get("retrieval_attempts", 0) + 1
    duration = time.monotonic() - start
    logger.info("agent.hyde_retrieve", count=len(documents), duration_ms=round(duration * 1000))

    return {
        "documents": documents,
        "retrieval_attempts": attempts,
        "agent_trace": [f"hyde_retrieve -> {len(documents)} docs"],
        "total_input_tokens": state.get("total_input_tokens", 0) + response.input_tokens,
        "total_output_tokens": state.get("total_output_tokens", 0) + response.output_tokens,
    }


# ---------------------------------------------------------------------------
# Node: Decompose Query
# ---------------------------------------------------------------------------

async def decompose_query(state: dict, *, llm: BaseLLM, retriever: BaseRetriever) -> dict:
    """Decompose complex query into sub-queries, retrieve for each, merge results."""
    question = state["question"]
    workspace_id = UUID(state["workspace_id"])
    top_k = state.get("top_k", 5)
    start = time.monotonic()

    # Ask LLM to decompose
    response = await llm.generate(
        prompt=DECOMPOSE_PROMPT.format(question=question),
        temperature=0.0,
        max_tokens=300,
    )

    sub_questions = parse_json_array(response.content)
    if len(sub_questions) <= 1:
        # Not worth decomposing — just use original question
        sub_questions = [question]

    # Retrieve for each sub-question in parallel
    retrieve_tasks = [
        retriever.retrieve(sq, workspace_id, top_k=top_k)
        for sq in sub_questions
    ]
    all_results = await asyncio.gather(*retrieve_tasks)

    # Merge via simple RRF across sub-query result sets
    rrf_scores: dict[str, float] = {}
    doc_map: dict[str, dict] = {}
    rrf_k = 60

    for sq_idx, results in enumerate(all_results):
        weight = 1.0
        for rank, r in enumerate(results):
            key = str(r.chunk_id)
            score = weight / (rrf_k + rank + 1)
            rrf_scores[key] = rrf_scores.get(key, 0.0) + score
            if key not in doc_map:
                doc_map[key] = {
                    "chunk_id": str(r.chunk_id),
                    "document_id": str(r.document_id),
                    "content": r.content,
                    "score": 0.0,
                    "metadata": {**r.metadata, "decomposed": True, "sub_query": sub_questions[sq_idx]},
                    "source": r.source,
                }

    # Sort by fused score and take top_k
    sorted_keys = sorted(rrf_scores.keys(), key=lambda k: rrf_scores[k], reverse=True)
    documents = []
    for key in sorted_keys[:top_k]:
        doc = doc_map[key]
        doc["score"] = rrf_scores[key]
        documents.append(doc)

    attempts = state.get("retrieval_attempts", 0) + 1
    duration = time.monotonic() - start
    logger.info("agent.decompose_query", sub_questions=len(sub_questions), results=len(documents), duration_ms=round(duration * 1000))

    return {
        "documents": documents,
        "retrieval_attempts": attempts,
        "agent_trace": [f"decompose_query -> {len(sub_questions)} sub-Qs -> {len(documents)} docs"],
        "total_input_tokens": state.get("total_input_tokens", 0) + response.input_tokens,
        "total_output_tokens": state.get("total_output_tokens", 0) + response.output_tokens,
    }


# ---------------------------------------------------------------------------
# Node: Rerank
# ---------------------------------------------------------------------------

async def rerank(state: dict, *, reranker) -> dict:
    """Apply reranker to improve retrieval precision."""
    documents = state.get("documents", [])
    if not documents or not reranker:
        return {"agent_trace": ["rerank -> skipped"]}

    query = state.get("rewritten_question") or state["question"]
    top_k = state.get("top_k", 5)
    start = time.monotonic()

    # Convert dicts back to RetrievalResult for reranker interface
    results = [
        RetrievalResult(
            chunk_id=UUID(d["chunk_id"]),
            document_id=UUID(d["document_id"]),
            content=d["content"],
            score=d["score"],
            metadata=d["metadata"],
            source=d["source"],
        )
        for d in documents
    ]

    reranked = await reranker.rerank(query, results, top_k)

    reranked_docs = [
        {
            "chunk_id": str(r.chunk_id),
            "document_id": str(r.document_id),
            "content": r.content,
            "score": r.score,
            "metadata": r.metadata,
            "source": r.source,
        }
        for r in reranked
    ]

    duration = time.monotonic() - start
    logger.info("agent.rerank", input=len(documents), output=len(reranked_docs), duration_ms=round(duration * 1000))

    return {
        "documents": reranked_docs,
        "agent_trace": [f"rerank -> {len(reranked_docs)} docs"],
    }


# ---------------------------------------------------------------------------
# Node: Grade Documents
# ---------------------------------------------------------------------------

async def grade_documents(state: dict, *, llm: BaseLLM) -> dict:
    """Evaluate relevance of each retrieved chunk using LLM-as-judge."""
    documents = state.get("documents", [])
    question = state.get("rewritten_question") or state["question"]
    start = time.monotonic()

    if not documents:
        return {
            "documents_relevant": False,
            "agent_trace": ["grade_documents -> 0/0 relevant"],
        }

    # Grade each document in parallel
    async def grade_one(doc: dict) -> tuple[dict, bool]:
        content_preview = doc["content"][:1000]
        response = await llm.generate(
            prompt=GRADER_PROMPT.format(question=question, document=content_preview),
            temperature=0.0,
            max_tokens=150,
        )
        parsed = parse_json_response(response.content, default={"relevant": True})
        is_relevant = parsed.get("relevant", True)
        doc["metadata"]["relevance_graded"] = True
        doc["metadata"]["graded_relevant"] = is_relevant
        return doc, is_relevant

    # Process in batches of 5 to avoid overwhelming the LLM
    relevant_docs = []
    all_graded = []
    batch_size = 5
    total_in = 0
    total_out = 0

    for i in range(0, len(documents), batch_size):
        batch = documents[i:i + batch_size]
        results = await asyncio.gather(*[grade_one(doc) for doc in batch])
        for doc, is_relevant in results:
            all_graded.append(doc)
            if is_relevant:
                relevant_docs.append(doc)

    # Build sources from relevant docs
    sources = [
        {
            "index": i + 1,
            "chunk_id": doc["chunk_id"],
            "document_id": doc["document_id"],
            "content": doc["content"][:300],
            "score": doc["score"],
            "source": doc["metadata"].get("filename", "Unknown"),
            "metadata": {
                k: v for k, v in doc["metadata"].items()
                if k in ("page_number", "chunk_strategy", "reranked", "relevance_graded",
                         "hyde_used", "decomposed")
            },
        }
        for i, doc in enumerate(relevant_docs)
    ]

    is_relevant = len(relevant_docs) >= 1
    duration = time.monotonic() - start
    logger.info("agent.grade_documents", relevant=len(relevant_docs), total=len(documents), duration_ms=round(duration * 1000))

    return {
        "documents": relevant_docs if relevant_docs else documents,
        "documents_relevant": is_relevant,
        "sources": sources,
        "agent_trace": [f"grade_documents -> {len(relevant_docs)}/{len(documents)} relevant"],
    }


# ---------------------------------------------------------------------------
# Node: Rewrite Question
# ---------------------------------------------------------------------------

async def rewrite_question(state: dict, *, llm: BaseLLM) -> dict:
    """Rewrite the query for better retrieval after poor results."""
    question = state["question"]
    start = time.monotonic()

    response = await llm.generate(
        prompt=REWRITE_PROMPT.format(question=question),
        temperature=0.3,
        max_tokens=200,
    )

    rewritten = response.content.strip().strip('"').strip("'")

    duration = time.monotonic() - start
    logger.info("agent.rewrite_question", original=question[:80], rewritten=rewritten[:80], duration_ms=round(duration * 1000))

    return {
        "rewritten_question": rewritten,
        "documents": [],  # Clear for fresh retrieval
        "agent_trace": [f"rewrite_question -> {rewritten[:60]}..."],
        "total_input_tokens": state.get("total_input_tokens", 0) + response.input_tokens,
        "total_output_tokens": state.get("total_output_tokens", 0) + response.output_tokens,
    }


# ---------------------------------------------------------------------------
# Node: Generate
# ---------------------------------------------------------------------------

async def generate(state: dict, *, llm: BaseLLM) -> dict:
    """Synthesize answer from graded context and chat history."""
    question = state.get("rewritten_question") or state["question"]
    documents = state.get("documents", [])
    chat_history = state.get("chat_history", [])
    system_prompt = state.get("system_prompt", "")
    start = time.monotonic()

    # Build context string
    if documents:
        context_parts = []
        for i, doc in enumerate(documents):
            source_info = doc.get("metadata", {}).get("filename", "Unknown source")
            context_parts.append(f"[Source {i+1}] ({source_info}):\n{doc['content']}")
        context = "\n\n---\n\n".join(context_parts)
    else:
        context = "No relevant documents were found for this question."

    # Build chat history string
    if chat_history:
        history_str = "\n".join(
            f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}"
            for m in chat_history[-10:]
        )
    else:
        history_str = "No prior conversation."

    prompt = GENERATOR_PROMPT.format(
        context=context,
        chat_history=history_str,
        question=question,
    )

    system = system_prompt or (
        "You are a helpful AI assistant with access to a knowledge base. "
        "Answer questions based on the provided context. Be precise and cite your sources."
    )

    response = await llm.generate(prompt, system=system, temperature=0.1)

    duration = time.monotonic() - start
    logger.info("agent.generate", length=len(response.content), duration_ms=round(duration * 1000))

    return {
        "generation": response.content,
        "model_used": response.model,
        "agent_trace": ["generate"],
        "total_input_tokens": state.get("total_input_tokens", 0) + response.input_tokens,
        "total_output_tokens": state.get("total_output_tokens", 0) + response.output_tokens,
    }


# ---------------------------------------------------------------------------
# Node: Check Hallucination
# ---------------------------------------------------------------------------

async def check_hallucination(state: dict, *, llm: BaseLLM) -> dict:
    """Verify the generated answer is grounded in source documents."""
    documents = state.get("documents", [])
    generation = state.get("generation", "")
    start = time.monotonic()

    if not documents or not generation:
        return {
            "answer_grounded": True,
            "agent_trace": ["check_hallucination -> grounded (no docs to check)"],
        }

    # Build sources summary (first 500 chars each)
    sources_text = "\n\n".join(
        f"Source {i+1}: {doc['content'][:500]}"
        for i, doc in enumerate(documents)
    )

    response = await llm.generate(
        prompt=HALLUCINATION_PROMPT.format(sources=sources_text, answer=generation),
        temperature=0.0,
        max_tokens=150,
    )

    parsed = parse_json_response(response.content, default={"grounded": True})
    is_grounded = parsed.get("grounded", True)

    duration = time.monotonic() - start
    logger.info("agent.check_hallucination", grounded=is_grounded, duration_ms=round(duration * 1000))

    return {
        "answer_grounded": is_grounded,
        "agent_trace": [f"check_hallucination -> {'grounded' if is_grounded else 'NOT grounded'}"],
        "total_input_tokens": state.get("total_input_tokens", 0) + response.input_tokens,
        "total_output_tokens": state.get("total_output_tokens", 0) + response.output_tokens,
    }
