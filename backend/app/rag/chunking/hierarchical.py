"""Hierarchical (parent-child) chunking strategy.

Index small chunks for precise matching, but return parent chunks
for richer context during generation. This bridges the
precision-vs-context tradeoff.
"""

from app.rag.chunking.base import BaseChunker, Chunk
from app.rag.chunking.text_splitter import RecursiveChunker


class HierarchicalChunker(BaseChunker):
    """Two-level chunking: parent chunks (large) containing child chunks (small).

    - Child chunks (256 tokens): Used for embedding + retrieval matching
    - Parent chunks (1024 tokens): Returned for generation context

    Each child stores its parent_chunk_index in metadata for lookup.
    """

    def __init__(
        self,
        parent_size: int = 1024,
        child_size: int = 256,
        parent_overlap: int = 100,
        child_overlap: int = 25,
    ):
        self.parent_chunker = RecursiveChunker(
            chunk_size=parent_size, chunk_overlap=parent_overlap,
        )
        self.child_chunker = RecursiveChunker(
            chunk_size=child_size, chunk_overlap=child_overlap,
        )

    def chunk(self, text: str, metadata: dict | None = None) -> list[Chunk]:
        """Return child chunks with parent references in metadata.

        The returned chunks are the CHILD chunks (for indexing/embedding).
        Parent content is stored in each child's metadata for retrieval-time expansion.
        """
        metadata = metadata or {}
        parents = self.parent_chunker.chunk(text, metadata)

        all_children = []
        child_idx = 0

        for parent_idx, parent in enumerate(parents):
            child_chunks = self.child_chunker.chunk(parent.content, {})

            for child in child_chunks:
                child.chunk_index = child_idx
                child.metadata = {
                    **metadata,
                    "chunk_strategy": "hierarchical_child",
                    "parent_chunk_index": parent_idx,
                    "parent_content": parent.content,
                    "parent_token_count": parent.token_count,
                }
                all_children.append(child)
                child_idx += 1

        return all_children

    def chunk_with_parents(self, text: str, metadata: dict | None = None) -> tuple[list[Chunk], list[Chunk]]:
        """Return both parent and child chunk lists separately.

        Useful when you want to store parents as separate DB records
        and link via foreign key rather than embedding parent content in metadata.
        """
        metadata = metadata or {}
        parents = self.parent_chunker.chunk(text, metadata)
        for p in parents:
            p.metadata["chunk_strategy"] = "hierarchical_parent"

        all_children = []
        child_idx = 0
        for parent_idx, parent in enumerate(parents):
            child_chunks = self.child_chunker.chunk(parent.content, {})
            for child in child_chunks:
                child.chunk_index = child_idx
                child.metadata = {
                    **metadata,
                    "chunk_strategy": "hierarchical_child",
                    "parent_chunk_index": parent_idx,
                }
                all_children.append(child)
                child_idx += 1

        return parents, all_children
