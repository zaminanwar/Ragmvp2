"""Authentication routes."""

from pydantic import BaseModel, EmailStr
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession
from app.services.auth_service import AuthService

router = APIRouter()


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str
    password: str
    full_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    token: str
    user: dict


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    full_name: str | None
    role: str


@router.post("/register", response_model=AuthResponse)
async def register(body: RegisterRequest, db: DbSession):
    service = AuthService(db)
    user, token = await service.register(
        email=body.email,
        username=body.username,
        password=body.password,
        full_name=body.full_name,
    )
    return AuthResponse(
        token=token,
        user={
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role,
        },
    )


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, db: DbSession):
    service = AuthService(db)
    user, token = await service.login(email=body.email, password=body.password)
    return AuthResponse(
        token=token,
        user={
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role,
        },
    )


@router.get("/me", response_model=UserResponse)
async def get_me(user: CurrentUser):
    return UserResponse(
        id=str(user.id),
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
    )
