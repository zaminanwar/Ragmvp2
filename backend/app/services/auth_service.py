"""Authentication service."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, UnauthorizedError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User, UserRole


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def register(
        self,
        email: str,
        username: str,
        password: str,
        full_name: str | None = None,
    ) -> tuple[User, str]:
        """Register a new user and return user + token."""
        # Check uniqueness
        existing = await self.db.execute(
            select(User).where((User.email == email) | (User.username == username))
        )
        if existing.scalar_one_or_none():
            raise ConflictError("User with this email or username already exists")

        user = User(
            email=email,
            username=username,
            hashed_password=hash_password(password),
            full_name=full_name,
            role=UserRole.MEMBER.value,
        )
        self.db.add(user)
        await self.db.flush()

        token = create_access_token({"sub": str(user.id), "role": user.role})
        return user, token

    async def login(self, email: str, password: str) -> tuple[User, str]:
        """Authenticate user and return user + token."""
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if not user or not verify_password(password, user.hashed_password):
            raise UnauthorizedError("Invalid email or password")

        if not user.is_active:
            raise UnauthorizedError("Account is deactivated")

        token = create_access_token({"sub": str(user.id), "role": user.role})
        return user, token
