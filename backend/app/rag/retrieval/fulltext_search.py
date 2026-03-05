"""Full-text search using Elasticsearch (inspired by RAGFlow's dual search)."""

from uuid import UUID

from elasticsearch import AsyncElasticsearch

from app.config import get_settings
from app.rag.retrieval.base import BaseRetriever, RetrievalResult


class FullTextRetriever(BaseRetriever):
    """BM25 full-text search via Elasticsearch."""

    def __init__(self):
        settings = get_settings()
        self.es = AsyncElasticsearch(settings.elasticsearch_url)
        self.index_prefix = "rag_chunks"

    def _index_name(self, workspace_id: UUID) -> str:
        return f"{self.index_prefix}_{str(workspace_id).replace('-', '')}"

    async def ensure_index(self, workspace_id: UUID):
        """Create index if it doesn't exist."""
        index = self._index_name(workspace_id)
        if not await self.es.indices.exists(index=index):
            await self.es.indices.create(
                index=index,
                body={
                    "settings": {
                        "number_of_shards": 1,
                        "number_of_replicas": 0,
                        "analysis": {
                            "analyzer": {
                                "rag_analyzer": {
                                    "type": "custom",
                                    "tokenizer": "standard",
                                    "filter": ["lowercase", "stop", "snowball"],
                                }
                            }
                        },
                    },
                    "mappings": {
                        "properties": {
                            "chunk_id": {"type": "keyword"},
                            "document_id": {"type": "keyword"},
                            "content": {"type": "text", "analyzer": "rag_analyzer"},
                            "metadata": {"type": "object", "enabled": False},
                        }
                    },
                },
            )

    async def index_chunk(
        self,
        workspace_id: UUID,
        chunk_id: UUID,
        document_id: UUID,
        content: str,
        metadata: dict | None = None,
    ):
        """Index a chunk for full-text search."""
        index = self._index_name(workspace_id)
        await self.es.index(
            index=index,
            id=str(chunk_id),
            body={
                "chunk_id": str(chunk_id),
                "document_id": str(document_id),
                "content": content,
                "metadata": metadata or {},
            },
        )

    async def retrieve(
        self,
        query: str,
        workspace_id: UUID,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        index = self._index_name(workspace_id)

        if not await self.es.indices.exists(index=index):
            return []

        body = {
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["content"],
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                }
            },
            "size": top_k,
        }

        response = await self.es.search(index=index, body=body)
        hits = response["hits"]["hits"]

        results = []
        for hit in hits:
            source = hit["_source"]
            results.append(
                RetrievalResult(
                    chunk_id=UUID(source["chunk_id"]),
                    document_id=UUID(source["document_id"]),
                    content=source["content"],
                    score=hit["_score"],
                    metadata=source.get("metadata", {}),
                    source="fulltext",
                )
            )
        return results

    async def delete_document_chunks(self, workspace_id: UUID, document_id: UUID):
        """Delete all chunks for a document from the index."""
        index = self._index_name(workspace_id)
        if await self.es.indices.exists(index=index):
            await self.es.delete_by_query(
                index=index,
                body={"query": {"term": {"document_id": str(document_id)}}},
            )
