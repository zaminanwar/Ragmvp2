"""Contextual chunk embeddings (Anthropic-style Contextual Retrieval).

Prepends document-level context to each chunk before embedding,
so embeddings capture both local and global document meaning.
This is one of the highest-impact retrieval improvements available.
"""

import asyncio

import structlog

from app.rag.chunking.base import Chunk
from app.rag.llm.base import BaseLLM

logger = structlog.get_logger()

SUMMARY_PROMPT = "Summarize this document in 2-3 sentences. Be factual and specific."

CONTEXT_PROMPT = """Document summary: {summary}

Chunk content: {chunk}

In 1-2 sentences, describe what this chunk is about in the context of the whole document. Be factual and specific."""


async def add_contextual_headers(
    chunks: list[Chunk],
    full_text: str,
    llm: BaseLLM,
    batch_size: int = 5,
) -> list[Chunk]:
    """Add contextual headers to chunks for improved embedding quality.

    For each chunk, generates a brief contextual description using
    the document summary + chunk content, then stores it as metadata.
    The embedding content should use the contextualized version.

    Args:
        chunks: List of document chunks
        full_text: Full document text (used for summary generation)
        llm: LLM provider for context generation
        batch_size: How many chunks to process in parallel

    Returns:
        Chunks with added 'contextual_header' and 'embedding_content' metadata
    """
    if not chunks:
        return chunks

    # Generate document summary once
    summary_response = await llm.generate(
        prompt=f"Document text (first 3000 chars):\n{full_text[:3000]}",
        system=SUMMARY_PROMPT,
        temperature=0.0,
        max_tokens=200,
    )
    doc_summary = summary_response.content.strip()

    async def contextualize_one(chunk: Chunk) -> Chunk:
        try:
            response = await llm.generate(
                prompt=CONTEXT_PROMPT.format(
                    summary=doc_summary,
                    chunk=chunk.content[:800],
                ),
                temperature=0.0,
                max_tokens=150,
            )
            contextual_header = response.content.strip()
        except Exception as e:
            logger.warning("contextual_header_failed", error=str(e))
            contextual_header = doc_summary

        chunk.metadata["contextual_header"] = contextual_header
        chunk.metadata["embedding_content"] = f"{contextual_header}\n\n{chunk.content}"
        return chunk

    # Process in batches to avoid overwhelming LLM
    result_chunks = []
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        contextualized = await asyncio.gather(*[contextualize_one(c) for c in batch])
        result_chunks.extend(contextualized)

    logger.info("contextual_headers_added", chunk_count=len(result_chunks))
    return result_chunks
