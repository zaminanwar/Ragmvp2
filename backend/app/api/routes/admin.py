"""Admin routes for user management and system monitoring."""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, DbSession
from app.models.chat import Conversation, Message
from app.models.document import Document, DocumentChunk
from app.models.user import User, UserRole
from app.models.workspace import Workspace

router = APIRouter()


class UpdateUserRoleRequest(BaseModel):
    role: str


@router.get("/users")
async def list_users(admin: AdminUser, db: DbSession):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "username": u.username,
            "full_name": u.full_name,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: uuid.UUID, body: UpdateUserRoleRequest, admin: AdminUser, db: DbSession
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("User not found")
    user.role = UserRole(body.role)
    await db.flush()
    return {"status": "updated", "user_id": str(user_id), "role": body.role}


@router.patch("/users/{user_id}/deactivate")
async def deactivate_user(user_id: uuid.UUID, admin: AdminUser, db: DbSession):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("User not found")
    user.is_active = False
    await db.flush()
    return {"status": "deactivated"}


@router.get("/stats")
async def system_stats(admin: AdminUser, db: DbSession):
    """System-wide statistics dashboard."""
    user_count = await db.scalar(select(func.count(User.id)))
    workspace_count = await db.scalar(select(func.count(Workspace.id)))
    doc_count = await db.scalar(select(func.count(Document.id)))
    chunk_count = await db.scalar(select(func.count(DocumentChunk.id)))
    conversation_count = await db.scalar(select(func.count(Conversation.id)))
    message_count = await db.scalar(select(func.count(Message.id)))

    return {
        "users": user_count or 0,
        "workspaces": workspace_count or 0,
        "documents": doc_count or 0,
        "chunks": chunk_count or 0,
        "conversations": conversation_count or 0,
        "messages": message_count or 0,
    }
