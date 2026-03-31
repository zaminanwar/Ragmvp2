"""Chat service - manages conversations and message history."""

import uuid
from typing import AsyncIterator

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models.chat import Citation, Conversation, Message
from app.models.workspace import Workspace
from app.rag.embeddings.providers import get_embedding_provider
from app.rag.engine import RAGEngine, RAGResponse
from app.rag.llm.factory import get_llm_provider
from app.rag.retrieval.hybrid_search import HybridRetriever
from app.rag.retrieval.reranker import LLMReranker

logger = structlog.get_logger()


class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _build_engine(self, workspace: Workspace) -> RAGEngine:
        """Build a RAG engine configured for the workspace."""
        llm = get_llm_provider(
            provider=workspace.llm_provider,
            model=workspace.llm_model,
        )
        embedding = get_embedding_provider(provider=workspace.embedding_provider)
        retriever = HybridRetriever(self.db, embedding)
        reranker = LLMReranker(llm) if workspace.enable_reranking else None

        return RAGEngine(
            llm=llm,
            retriever=retriever,
            reranker=reranker,
            enable_corrective_rag=True,
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

        # Save assistant message
        assistant_msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=rag_response.content,
            model_used=rag_response.model,
            token_count=rag_response.input_tokens + rag_response.output_tokens,
            metadata_json={"input_tokens": rag_response.input_tokens, "output_tokens": rag_response.output_tokens},
            was_corrective_rag=rag_response.context.was_corrective if rag_response.context else False,
        )
        self.db.add(assistant_msg)
        await self.db.flush()

        # Save citations
        for cite in rag_response.citations:
            citation = Citation(
                message_id=assistant_msg.id,
                chunk_id=uuid.UUID(cite["chunk_id"]),
                relevance_score=cite["score"],
                excerpt=cite["content"],
                position=cite["index"],
            )
            self.db.add(citation)
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
