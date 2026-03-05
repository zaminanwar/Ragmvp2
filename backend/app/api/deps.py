"""FastAPI dependency injection."""

import uuid
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.exceptions import ForbiddenError, NotFoundError, UnauthorizedError
from app.core.security import decode_access_token
from app.models.base import get_db
from app.models.user import User, UserRole
from app.models.workspace import Workspace, WorkspaceMember


async def get_current_user(
    authorization: str = Header(..., alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate the current user from JWT token."""
    if not authorization.startswith("Bearer "):
        raise UnauthorizedError("Invalid authorization header")

    token = authorization.removeprefix("Bearer ")
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if user_id is None:
            raise UnauthorizedError("Invalid token payload")
    except Exception:
        raise UnauthorizedError("Could not validate credentials")

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise UnauthorizedError("User not found or inactive")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Require admin role."""
    if user.role != UserRole.ADMIN.value:
        raise ForbiddenError("Admin access required")
    return user


async def require_manager(user: User = Depends(get_current_user)) -> User:
    """Require manager or admin role."""
    if user.role not in (UserRole.ADMIN.value, UserRole.MANAGER.value):
        raise ForbiddenError("Manager access required")
    return user


async def get_workspace(
    workspace_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Workspace:
    """Get workspace with membership validation."""
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()

    if workspace is None:
        raise NotFoundError("Workspace not found")

    # Admins can access all workspaces
    if user.role == UserRole.ADMIN.value:
        return workspace

    # Check membership
    result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    member = result.scalar_one_or_none()

    if member is None:
        raise ForbiddenError("Not a member of this workspace")

    return workspace


# Type aliases for cleaner route signatures
CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_admin)]
ManagerUser = Annotated[User, Depends(require_manager)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
