"""Advanced text splitting with multiple strategies (inspired by RAGFlow template-based chunking)."""

import re

import tiktoken
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker, Chunk


class RecursiveChunker(BaseChunker):
    """Standard recursive character text splitter with token counting."""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=self._token_count,
            separators=["\n\n", "\n", ". ", " ", ""],
        )
        self._encoder = tiktoken.get_encoding("cl100k_base")

    def _token_count(self, text: str) -> int:
        return len(self._encoder.encode(text))

    def chunk(self, text: str, metadata: dict | None = None) -> list[Chunk]:
        metadata = metadata or {}
        splits = self._splitter.split_text(text)
        chunks = []
        for i, split in enumerate(splits):
            token_count = self._token_count(split)
            chunks.append(
                Chunk(
                    content=split,
                    chunk_index=i,
                    token_count=token_count,
                    metadata={**metadata, "chunk_strategy": "recursive"},
                )
            )
        return chunks


class SemanticChunker(BaseChunker):
    """Semantic chunking - splits on topic/meaning boundaries rather than fixed sizes.
    Inspired by RAGFlow's deep document understanding approach."""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self._encoder = tiktoken.get_encoding("cl100k_base")

    def _token_count(self, text: str) -> int:
        return len(self._encoder.encode(text))

    def _split_by_headings(self, text: str) -> list[str]:
        """Split by markdown-style headings and structural boundaries."""
        # Match markdown headings, horizontal rules, and significant whitespace
        pattern = r'(?=^#{1,6}\s)|(?=^\-{3,}$)|(?=^\*{3,}$)|(?=\n{3,})'
        sections = re.split(pattern, text, flags=re.MULTILINE)
        return [s.strip() for s in sections if s.strip()]

    def chunk(self, text: str, metadata: dict | None = None) -> list[Chunk]:
        metadata = metadata or {}
        sections = self._split_by_headings(text)

        chunks = []
        current_chunk = ""
        chunk_idx = 0

        for section in sections:
            if self._token_count(current_chunk + "\n\n" + section) > self.chunk_size:
                if current_chunk:
                    chunks.append(
                        Chunk(
                            content=current_chunk.strip(),
                            chunk_index=chunk_idx,
                            token_count=self._token_count(current_chunk),
                            metadata={**metadata, "chunk_strategy": "semantic"},
                        )
                    )
                    chunk_idx += 1

                # Handle oversized sections with recursive fallback
                if self._token_count(section) > self.chunk_size:
                    fallback = RecursiveChunker(self.chunk_size, self.chunk_overlap)
                    sub_chunks = fallback.chunk(section, metadata)
                    for sc in sub_chunks:
                        sc.chunk_index = chunk_idx
                        sc.metadata["chunk_strategy"] = "semantic_recursive_fallback"
                        chunks.append(sc)
                        chunk_idx += 1
                    current_chunk = ""
                else:
                    current_chunk = section
            else:
                current_chunk = (current_chunk + "\n\n" + section).strip()

        if current_chunk.strip():
            chunks.append(
                Chunk(
                    content=current_chunk.strip(),
                    chunk_index=chunk_idx,
                    token_count=self._token_count(current_chunk),
                    metadata={**metadata, "chunk_strategy": "semantic"},
                )
            )

        return chunks


def get_chunker(strategy: str = "recursive", **kwargs) -> BaseChunker:
    """Factory for chunking strategies."""
    strategies = {
        "recursive": RecursiveChunker,
        "semantic": SemanticChunker,
    }
    chunker_cls = strategies.get(strategy, RecursiveChunker)
    return chunker_cls(**kwargs)
