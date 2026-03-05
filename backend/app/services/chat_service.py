"""Chat service - manages conversations and message history."""

import uuid
from typing import AsyncIterator

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.core.exceptions import NotFoundError
from app.models.chat import Citation, Conversation, Message
from app.models.workspace import Workspace
from app.rag.embeddings.providers import get_embedding_provider
from app.rag.engine import RAGEngine, RAGResponse
from app.rag.llm.factory import get_llm_provider
from app.rag.retrieval.hybrid_search import HybridRetriever
from app.rag.retrieval.reranker import CohereReranker, LLMReranker

logger = structlog.get_logger()


class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._semantic_cache = None

    async def _get_semantic_cache(self, workspace: Workspace):
        """Lazily initialize semantic cache if enabled."""
        if not getattr(workspace, "enable_semantic_cache", False):
            return None
        if self._semantic_cache is None:
            try:
                import redis.asyncio as aioredis
                from app.rag.cache import SemanticCache
                settings = get_settings()
                redis_client = aioredis.from_url(settings.redis_url)
                embedding = get_embedding_provider(provider=workspace.embedding_provider)
                self._semantic_cache = SemanticCache(redis_client, embedding)
            except Exception as e:
                logger.warning("semantic_cache_init_failed", error=str(e))
                return None
        return self._semantic_cache

    def _build_engine(self, workspace: Workspace) -> RAGEngine:
        """Build a RAG engine configured for the workspace."""
        llm = get_llm_provider(
            provider=workspace.llm_provider,
            model=workspace.llm_model,
        )
        embedding = get_embedding_provider(provider=workspace.embedding_provider)

        enable_graph = getattr(workspace, "enable_knowledge_graph", False)
        retriever = HybridRetriever(self.db, embedding, enable_graph=enable_graph)

        # Use Cohere reranker if API key is available, otherwise LLM-based
        reranker = None
        if workspace.enable_reranking:
            settings = get_settings()
            cohere_key = getattr(settings, "cohere_api_key", None)
            if cohere_key:
                reranker = CohereReranker(api_key=cohere_key)
            else:
                reranker = LLMReranker(llm)

        return RAGEngine(
            llm=llm,
            retriever=retriever,
            reranker=reranker,
            embedding_provider=embedding,
            enable_corrective_rag=True,
            enable_reranking=workspace.enable_reranking,
            enable_hyde=getattr(workspace, "enable_hyde", False),
            enable_query_decomposition=getattr(workspace, "enable_query_decomposition", False),
            enable_adaptive_routing=getattr(workspace, "enable_adaptive_routing", True),
            enable_self_reflection=getattr(workspace, "enable_self_reflection", True),
        )

    async def create_conversation(
        self,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        title: str = "New Conversation",
    ) -> Conversation:
        conv = Conversation(
            workspace_id=workspace_id,
            user_id=user_id,
            title=title,
        )
        self.db.add(conv)
        await self.db.flush()
        return conv

    async def get_conversation(self, conversation_id: uuid.UUID) -> Conversation:
        result = await self.db.execute(
            select(Conversation)
            .options(selectinload(Conversation.messages).selectinload(Message.citations))
            .where(Conversation.id == conversation_id)
        )
        conv = result.scalar_one_or_none()
        if not conv:
            raise NotFoundError("Conversation not found")
        return conv

    async def list_conversations(
        self, workspace_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[Conversation]:
        result = await self.db.execute(
            select(Conversation)
            .where(
                Conversation.workspace_id == workspace_id,
                Conversation.user_id == user_id,
                Conversation.is_active == True,
            )
            .order_by(Conversation.updated_at.desc())
        )
        return list(result.scalars().all())

    async def send_message(
        self,
        conversation_id: uuid.UUID,
        workspace: Workspace,
        user_message: str,
    ) -> tuple[Message, Message]:
        """Send a message and get RAG-powered response."""
        conv = await self.get_conversation(conversation_id)

        # Save user message
        user_msg = Message(
            conversation_id=conversation_id,
            role="user",
            content=user_message,
        )
        self.db.add(user_msg)
        await self.db.flush()

        # Build chat history
        chat_history = [
            {"role": m.role, "content": m.content}
            for m in conv.messages[-10:]
        ]

        # Check semantic cache first
        cache = await self._get_semantic_cache(workspace)
        cached_response = None
        if cache:
            cached_response = await cache.get(user_message, str(workspace.id))

        if cached_response:
            rag_response = RAGResponse(
                content=cached_response["content"],
                citations=cached_response.get("citations", []),
                context=None,
                model=cached_response.get("model", "cached"),
                input_tokens=0,
                output_tokens=0,
            )
            logger.info("semantic_cache_hit", query=user_message[:60])
        else:
            # Run RAG pipeline
            engine = self._build_engine(workspace)
            rag_response = await engine.query(
                query=user_message,
                workspace_id=workspace.id,
                system_prompt=workspace.system_prompt,
                chat_history=chat_history,
                top_k=workspace.similarity_top_k,
                temperature=workspace.temperature,
            )

            # Store in semantic cache
            if cache:
                try:
                    ttl = getattr(workspace, "cache_ttl_seconds", 3600)
                    await cache.set(
                        user_message,
                        str(workspace.id),
                        {
                            "content": rag_response.content,
                            "citations": rag_response.citations,
                            "model": rag_response.model,
                        },
                        ttl=ttl,
                    )
                except Exception as cache_err:
                    logger.warning("semantic_cache_store_failed", error=str(cache_err))

        # Save assistant message
        assistant_msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=rag_response.content,
            model_used=rag_response.model,
            input_tokens=rag_response.input_tokens,
            output_tokens=rag_response.output_tokens,
            was_corrective_rag=rag_response.context.was_corrective if rag_response.context else False,
            agent_trace={"trace": rag_response.context.agent_trace} if rag_response.context else None,
            search_mode_used=rag_response.context.search_mode_used if rag_response.context else None,
        )
        self.db.add(assistant_msg)
        await self.db.flush()

        # Save citations (skip any with invalid chunk references)
        from sqlalchemy import select as sa_select
        from app.models.document import DocumentChunk
        for cite in rag_response.citations:
            try:
                chunk_id = uuid.UUID(str(cite["chunk_id"]))
                # Verify chunk exists
                exists = await self.db.execute(
                    sa_select(DocumentChunk.id).where(DocumentChunk.id == chunk_id)
                )
                if exists.scalar_one_or_none() is None:
                    continue
                citation = Citation(
                    message_id=assistant_msg.id,
                    chunk_id=chunk_id,
                    relevance_score=cite["score"],
                    excerpt=cite["content"][:500],
                    position=cite["index"],
                )
                self.db.add(citation)
            except (ValueError, KeyError):
                continue
        await self.db.flush()

        # Auto-title on first message
        if len(conv.messages) <= 2:
            conv.title = user_message[:100]
            await self.db.flush()

        return user_msg, assistant_msg

    async def stream_message(
        self,
        conversation_id: uuid.UUID,
        workspace: Workspace,
        user_message: str,
    ) -> AsyncIterator[dict]:
        """Stream a RAG response."""
        conv = await self.get_conversation(conversation_id)

        # Save user message
        user_msg = Message(
            conversation_id=conversation_id,
            role="user",
            content=user_message,
        )
        self.db.add(user_msg)
        await self.db.flush()

        chat_history = [
            {"role": m.role, "content": m.content}
            for m in conv.messages[-10:]
        ]

        engine = self._build_engine(workspace)
        full_content = ""

        async for chunk in engine.query_stream(
            query=user_message,
            workspace_id=workspace.id,
            system_prompt=workspace.system_prompt,
            chat_history=chat_history,
            top_k=workspace.similarity_top_k,
            temperature=workspace.temperature,
        ):
            if chunk["type"] == "token":
                full_content += chunk["content"]
            yield chunk

        # Save completed message
        assistant_msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=full_content,
        )
        self.db.add(assistant_msg)
        await self.db.flush()

    async def delete_conversation(self, conversation_id: uuid.UUID):
        conv = await self.get_conversation(conversation_id)
        conv.is_active = False
        await self.db.flush()
