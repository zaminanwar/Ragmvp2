"""Chat routes with streaming support via WebSocket and SSE."""

import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.core.security import decode_access_token
from app.models.base import get_db, get_session_factory
from app.models.user import User
from app.services.chat_service import ChatService
from app.services.workspace_service import WorkspaceService

router = APIRouter()


class SendMessageRequest(BaseModel):
    conversation_id: str | None = None
    workspace_id: str
    message: str


class ConversationResponse(BaseModel):
    id: str
    workspace_id: str
    title: str
    created_at: str


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    model_used: str | None = None
    was_corrective_rag: bool = False
    citations: list[dict] = []
    created_at: str


@router.post("/send")
async def send_message(body: SendMessageRequest, user: CurrentUser, db: DbSession):
    """Send a message and get a complete (non-streaming) response."""
    chat_service = ChatService(db)
    ws_service = WorkspaceService(db)
    workspace = await ws_service.get_by_id(uuid.UUID(body.workspace_id))

    # Create conversation if needed
    if body.conversation_id:
        conv_id = uuid.UUID(body.conversation_id)
    else:
        conv = await chat_service.create_conversation(workspace.id, user.id)
        conv_id = conv.id

    user_msg, assistant_msg = await chat_service.send_message(conv_id, workspace, body.message)

    return {
        "conversation_id": str(conv_id),
        "user_message": {
            "id": str(user_msg.id),
            "role": "user",
            "content": user_msg.content,
        },
        "assistant_message": {
            "id": str(assistant_msg.id),
            "role": "assistant",
            "content": assistant_msg.content,
            "model_used": assistant_msg.model_used,
            "was_corrective_rag": assistant_msg.was_corrective_rag,
        },
    }


@router.post("/stream")
async def stream_message(body: SendMessageRequest, user: CurrentUser, db: DbSession):
    """Stream a response via Server-Sent Events (SSE)."""
    chat_service = ChatService(db)
    ws_service = WorkspaceService(db)
    workspace = await ws_service.get_by_id(uuid.UUID(body.workspace_id))

    if body.conversation_id:
        conv_id = uuid.UUID(body.conversation_id)
    else:
        conv = await chat_service.create_conversation(workspace.id, user.id)
        conv_id = conv.id

    async def event_generator():
        yield f"data: {json.dumps({'type': 'start', 'conversation_id': str(conv_id)})}\n\n"
        async for chunk in chat_service.stream_message(conv_id, workspace, body.message):
            yield f"data: {json.dumps(chunk)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/conversations/{workspace_id}", response_model=list[ConversationResponse])
async def list_conversations(workspace_id: uuid.UUID, user: CurrentUser, db: DbSession):
    chat_service = ChatService(db)
    convs = await chat_service.list_conversations(workspace_id, user.id)
    return [
        ConversationResponse(
            id=str(c.id),
            workspace_id=str(c.workspace_id),
            title=c.title,
            created_at=c.created_at.isoformat() if c.created_at else "",
        )
        for c in convs
    ]


@router.get("/conversation/{conversation_id}/messages")
async def get_messages(conversation_id: uuid.UUID, user: CurrentUser, db: DbSession):
    chat_service = ChatService(db)
    conv = await chat_service.get_conversation(conversation_id)
    return {
        "conversation_id": str(conv.id),
        "title": conv.title,
        "messages": [
            {
                "id": str(m.id),
                "role": m.role,
                "content": m.content,
                "model_used": m.model_used,
                "was_corrective_rag": m.was_corrective_rag,
                "citations": [
                    {
                        "chunk_id": str(c.chunk_id),
                        "excerpt": c.excerpt,
                        "relevance_score": c.relevance_score,
                        "position": c.position,
                    }
                    for c in m.citations
                ],
                "created_at": m.created_at.isoformat() if m.created_at else "",
            }
            for m in conv.messages
        ],
    }


@router.delete("/conversation/{conversation_id}")
async def delete_conversation(conversation_id: uuid.UUID, user: CurrentUser, db: DbSession):
    chat_service = ChatService(db)
    await chat_service.delete_conversation(conversation_id)
    return {"status": "deleted"}


@router.websocket("/ws/{workspace_id}")
async def websocket_chat(websocket: WebSocket, workspace_id: uuid.UUID):
    """WebSocket endpoint for real-time chat streaming."""
    await websocket.accept()

    try:
        # Authenticate via first message
        auth_data = await websocket.receive_json()
        token = auth_data.get("token", "")
        try:
            payload = decode_access_token(token)
            user_id = uuid.UUID(payload["sub"])
        except Exception:
            await websocket.send_json({"type": "error", "message": "Authentication failed"})
            await websocket.close()
            return

        session_factory = get_session_factory()

        while True:
            data = await websocket.receive_json()
            message = data.get("message", "")
            conversation_id = data.get("conversation_id")

            async with session_factory() as db:
                chat_service = ChatService(db)
                ws_service = WorkspaceService(db)
                workspace = await ws_service.get_by_id(workspace_id)

                if conversation_id:
                    conv_id = uuid.UUID(conversation_id)
                else:
                    conv = await chat_service.create_conversation(workspace_id, user_id)
                    conv_id = conv.id
                    await websocket.send_json({
                        "type": "conversation_created",
                        "conversation_id": str(conv_id),
                    })

                async for chunk in chat_service.stream_message(conv_id, workspace, message):
                    await websocket.send_json(chunk)

                await db.commit()

    except WebSocketDisconnect:
        pass
