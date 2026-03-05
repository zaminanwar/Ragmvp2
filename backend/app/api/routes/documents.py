"""Document management routes."""

import uuid

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.config import get_settings
from app.core.exceptions import BadRequestError
from app.services.document_service import DocumentService

router = APIRouter()


class DocumentResponse(BaseModel):
    id: str
    workspace_id: str
    original_filename: str
    file_type: str
    file_size: int
    status: str
    chunk_count: int
    created_at: str
    error_message: str | None = None


@router.post("/upload", response_model=DocumentResponse)
async def upload_document(
    workspace_id: str = Form(...),
    file: UploadFile = File(...),
    chunk_strategy: str = Form("recursive"),
    chunk_size: int = Form(512),
    chunk_overlap: int = Form(50),
    user: CurrentUser = None,
    db: DbSession = None,
):
    settings = get_settings()

    # Validate file type
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename and "." in file.filename else ""
    if ext not in settings.supported_file_type_list:
        raise BadRequestError(f"Unsupported file type: {ext}")

    # Validate file size
    content = await file.read()
    if len(content) > settings.max_upload_size_mb * 1024 * 1024:
        raise BadRequestError(f"File exceeds max size of {settings.max_upload_size_mb}MB")

    service = DocumentService(db)
    doc = await service.upload_and_process(
        file_content=content,
        filename=file.filename or "untitled",
        workspace_id=uuid.UUID(workspace_id),
        content_type=file.content_type or "application/octet-stream",
        chunk_strategy=chunk_strategy,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    return _to_response(doc)


@router.get("/workspace/{workspace_id}", response_model=list[DocumentResponse])
async def list_documents(workspace_id: uuid.UUID, user: CurrentUser, db: DbSession):
    service = DocumentService(db)
    docs = await service.list_documents(workspace_id)
    return [_to_response(d) for d in docs]


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: uuid.UUID, user: CurrentUser, db: DbSession):
    service = DocumentService(db)
    doc = await service.get_document(document_id)
    return _to_response(doc)


@router.delete("/{document_id}")
async def delete_document(document_id: uuid.UUID, user: CurrentUser, db: DbSession):
    service = DocumentService(db)
    await service.delete_document(document_id)
    return {"status": "deleted"}


@router.get("/workspace/{workspace_id}/stats")
async def workspace_stats(workspace_id: uuid.UUID, user: CurrentUser, db: DbSession):
    service = DocumentService(db)
    return await service.get_workspace_stats(workspace_id)


def _to_response(doc) -> DocumentResponse:
    return DocumentResponse(
        id=str(doc.id),
        workspace_id=str(doc.workspace_id),
        original_filename=doc.original_filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        status=doc.status if isinstance(doc.status, str) else doc.status.value,
        chunk_count=doc.chunk_count,
        created_at=doc.created_at.isoformat() if doc.created_at else "",
        error_message=doc.error_message,
    )
