"""Workspace management service (AnythingLLM workspace pattern)."""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError, NotFoundError
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceRole


class WorkspaceService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _slugify(self, name: str) -> str:
        slug = re.sub(r"[^\w\s-]", "", name.lower())
        slug = re.sub(r"[\s_]+", "-", slug).strip("-")
        return slug

    async def create(
        self,
        name: str,
        owner: User,
        description: str | None = None,
        **config_kwargs,
    ) -> Workspace:
        slug = self._slugify(name)
        # Ensure unique slug
        existing = await self.db.execute(select(Workspace).where(Workspace.slug == slug))
        if existing.scalar_one_or_none():
            slug = f"{slug}-{uuid.uuid4().hex[:6]}"

        workspace = Workspace(
            name=name,
            slug=slug,
            description=description,
            **config_kwargs,
        )
        self.db.add(workspace)
        await self.db.flush()

        # Add creator as owner
        member = WorkspaceMember(
            workspace_id=workspace.id,
            user_id=owner.id,
            role=WorkspaceRole.OWNER.value,
        )
        self.db.add(member)
        await self.db.flush()

        return workspace

    async def list_for_user(self, user: User) -> list[Workspace]:
        """List workspaces the user has access to."""
        from app.models.user import UserRole
        if user.role == UserRole.ADMIN.value:
            result = await self.db.execute(select(Workspace).where(Workspace.is_active == True))
            return list(result.scalars().all())

        result = await self.db.execute(
            select(Workspace)
            .join(WorkspaceMember)
            .where(WorkspaceMember.user_id == user.id, Workspace.is_active == True)
        )
        return list(result.scalars().all())

    async def get_by_id(self, workspace_id: uuid.UUID) -> Workspace:
        result = await self.db.execute(
            select(Workspace)
            .options(selectinload(Workspace.members))
            .where(Workspace.id == workspace_id)
        )
        workspace = result.scalar_one_or_none()
        if not workspace:
            raise NotFoundError("Workspace not found")
        return workspace

    async def update(self, workspace_id: uuid.UUID, **kwargs) -> Workspace:
        workspace = await self.get_by_id(workspace_id)
        for key, value in kwargs.items():
            if hasattr(workspace, key) and value is not None:
                setattr(workspace, key, value)
        await self.db.flush()
        return workspace

    async def add_member(
        self,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID,
        role: str = WorkspaceRole.VIEWER.value,
    ) -> WorkspaceMember:
        existing = await self.db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        if existing.scalar_one_or_none():
            raise ConflictError("User is already a member")

        member = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=user_id,
            role=role,
        )
        self.db.add(member)
        await self.db.flush()
        return member
