"""Workspace management routes (AnythingLLM workspace pattern)."""

import uuid
from pydantic import BaseModel
from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.services.workspace_service import WorkspaceService

router = APIRouter()


class CreateWorkspaceRequest(BaseModel):
    name: str
    description: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    temperature: float = 0.1
    system_prompt: str | None = None
    chunk_size: int = 512
    chunk_overlap: int = 50
    similarity_top_k: int = 5
    enable_hybrid_search: bool = True
    enable_reranking: bool = True


class UpdateWorkspaceRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    temperature: float | None = None
    system_prompt: str | None = None
    similarity_top_k: int | None = None
    enable_hybrid_search: bool | None = None
    enable_reranking: bool | None = None


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None
    llm_provider: str | None
    llm_model: str | None
    temperature: float
    similarity_top_k: int
    enable_hybrid_search: bool
    enable_reranking: bool


class AddMemberRequest(BaseModel):
    user_id: str
    role: str = "viewer"


@router.post("", response_model=WorkspaceResponse)
async def create_workspace(body: CreateWorkspaceRequest, user: CurrentUser, db: DbSession):
    service = WorkspaceService(db)
    ws = await service.create(
        name=body.name,
        owner=user,
        description=body.description,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        embedding_provider=body.embedding_provider,
        embedding_model=body.embedding_model,
        temperature=body.temperature,
        system_prompt=body.system_prompt,
        chunk_size=body.chunk_size,
        chunk_overlap=body.chunk_overlap,
        similarity_top_k=body.similarity_top_k,
        enable_hybrid_search=body.enable_hybrid_search,
        enable_reranking=body.enable_reranking,
    )
    return _to_response(ws)


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(user: CurrentUser, db: DbSession):
    service = WorkspaceService(db)
    workspaces = await service.list_for_user(user)
    return [_to_response(ws) for ws in workspaces]


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(workspace_id: uuid.UUID, user: CurrentUser, db: DbSession):
    service = WorkspaceService(db)
    ws = await service.get_by_id(workspace_id)
    return _to_response(ws)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: uuid.UUID, body: UpdateWorkspaceRequest, user: CurrentUser, db: DbSession
):
    service = WorkspaceService(db)
    ws = await service.update(workspace_id, **body.model_dump(exclude_none=True))
    return _to_response(ws)


@router.post("/{workspace_id}/members")
async def add_member(workspace_id: uuid.UUID, body: AddMemberRequest, user: CurrentUser, db: DbSession):
    from app.models.workspace import WorkspaceRole
    service = WorkspaceService(db)
    member = await service.add_member(
        workspace_id, uuid.UUID(body.user_id), WorkspaceRole(body.role)
    )
    return {"status": "ok", "member_id": str(member.id)}


def _to_response(ws) -> WorkspaceResponse:
    return WorkspaceResponse(
        id=str(ws.id),
        name=ws.name,
        slug=ws.slug,
        description=ws.description,
        llm_provider=ws.llm_provider,
        llm_model=ws.llm_model,
        temperature=ws.temperature,
        similarity_top_k=ws.similarity_top_k,
        enable_hybrid_search=ws.enable_hybrid_search,
        enable_reranking=ws.enable_reranking,
    )
