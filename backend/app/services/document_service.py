"""Document ingestion and management service.

Implements the dedicated collector pattern from AnythingLLM with
deep document understanding from RAGFlow and real-time sync from Pathway.
"""

import uuid

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.rag.chunking.document_parser import DocumentParser
from app.rag.chunking.text_splitter import get_chunker
from app.rag.embeddings.providers import get_embedding_provider
from app.rag.retrieval.fulltext_search import FullTextRetriever
from app.services.storage_service import StorageService

logger = structlog.get_logger()


class DocumentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.parser = DocumentParser()
        self.storage = StorageService()
        self.fulltext = FullTextRetriever()

    async def upload_and_process(
        self,
        file_content: bytes,
        filename: str,
        workspace_id: uuid.UUID,
        content_type: str = "application/octet-stream",
        chunk_strategy: str = "recursive",
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> Document:
        """Upload, parse, chunk, embed, and index a document."""
        settings = get_settings()
        chunk_size = chunk_size or settings.chunk_size
        chunk_overlap = chunk_overlap or settings.chunk_overlap

        # 1. Upload to storage
        storage_path = self.storage.upload_file(
            file_content, filename, workspace_id, content_type
        )

        # 2. Create document record
        file_ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "txt"
        doc = Document(
            workspace_id=workspace_id,
            filename=f"{uuid.uuid4().hex}.{file_ext}",
            original_filename=filename,
            file_type=file_ext,
            file_size=len(file_content),
            storage_path=storage_path,
            status=DocumentStatus.PROCESSING,
        )
        self.db.add(doc)
        await self.db.flush()

        try:
            # 3. Parse document
            text = self.parser.parse(file_content, filename)
            logger.info("document_parsed", doc_id=str(doc.id), chars=len(text))

            # 4. Chunk
            chunker = get_chunker(chunk_strategy, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            chunks = chunker.chunk(text, metadata={"filename": filename, "file_type": file_ext})
            logger.info("document_chunked", doc_id=str(doc.id), chunk_count=len(chunks))

            # 5. Embed
            embedding_provider = get_embedding_provider()
            texts = [c.content for c in chunks]
            embeddings = await embedding_provider.embed_batch(texts)

            # 6. Store chunks with embeddings
            await self.fulltext.ensure_index(workspace_id)

            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                db_chunk = DocumentChunk(
                    document_id=doc.id,
                    workspace_id=workspace_id,
                    chunk_index=i,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    embedding=embedding,
                    metadata_json=chunk.metadata,
                    bm25_content=chunk.content,
                )
                self.db.add(db_chunk)
                await self.db.flush()

                # Index in Elasticsearch for full-text search
                await self.fulltext.index_chunk(
                    workspace_id=workspace_id,
                    chunk_id=db_chunk.id,
                    document_id=doc.id,
                    content=chunk.content,
                    metadata=chunk.metadata,
                )

            doc.status = DocumentStatus.INDEXED
            doc.chunk_count = len(chunks)
            await self.db.flush()

            logger.info("document_indexed", doc_id=str(doc.id), chunks=len(chunks))

        except Exception as e:
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(e)
            await self.db.flush()
            logger.error("document_processing_failed", doc_id=str(doc.id), error=str(e))
            raise

        return doc

    async def list_documents(self, workspace_id: uuid.UUID) -> list[Document]:
        result = await self.db.execute(
            select(Document)
            .where(Document.workspace_id == workspace_id)
            .order_by(Document.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_document(self, document_id: uuid.UUID) -> Document:
        result = await self.db.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()
        if not doc:
            from app.core.exceptions import NotFoundError
            raise NotFoundError("Document not found")
        return doc

    async def delete_document(self, document_id: uuid.UUID):
        doc = await self.get_document(document_id)

        # Delete from Elasticsearch
        await self.fulltext.delete_document_chunks(doc.workspace_id, doc.id)

        # Delete from storage
        try:
            self.storage.delete_file(doc.storage_path)
        except Exception:
            pass

        # Delete from DB (cascades to chunks)
        await self.db.delete(doc)
        await self.db.flush()

    async def get_workspace_stats(self, workspace_id: uuid.UUID) -> dict:
        doc_count = await self.db.scalar(
            select(func.count(Document.id)).where(Document.workspace_id == workspace_id)
        )
        chunk_count = await self.db.scalar(
            select(func.count(DocumentChunk.id)).where(DocumentChunk.workspace_id == workspace_id)
        )
        return {"document_count": doc_count or 0, "chunk_count": chunk_count or 0}
