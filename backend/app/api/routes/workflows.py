"""Workflow API endpoints — definitions, runs, approvals, tools."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession, ManagerUser
from app.services.workflow_service import WorkflowService
from app.workflows.tools.registry import ToolRegistry

router = APIRouter()


# ── Request/Response schemas ─────────────────────────────────────────────────


class CreateDefinitionRequest(BaseModel):
    workspace_id: uuid.UUID
    name: str
    description: str | None = None
    definition_json: dict
    is_template: bool = False
    required_role: str = "member"


class UpdateDefinitionRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    definition_json: dict | None = None
    required_role: str | None = None


class StartRunRequest(BaseModel):
    workflow_id: uuid.UUID
    workspace_id: uuid.UUID
    input_json: dict = {}


class RerunFromStepRequest(BaseModel):
    step_id: str
    overrides: dict | None = None


class ApprovalDecisionRequest(BaseModel):
    approved: bool
    comment: str | None = None


class ValidateDefinitionRequest(BaseModel):
    definition_json: dict


# ── Definitions ──────────────────────────────────────────────────────────────


@router.post("/definitions")
async def create_definition(
    req: CreateDefinitionRequest,
    user: ManagerUser,
    db: DbSession,
):
    service = WorkflowService(db)
    defn = await service.create_definition(
        workspace_id=req.workspace_id,
        name=req.name,
        definition_json=req.definition_json,
        created_by=user.id,
        description=req.description,
        is_template=req.is_template,
        required_role=req.required_role,
    )
    return _serialize_definition(defn)


@router.get("/definitions")
async def list_definitions(
    workspace_id: uuid.UUID = Query(...),
    status: str | None = Query(None),
    user: CurrentUser = Depends(),
    db: DbSession = Depends(),
):
    service = WorkflowService(db)
    defs = await service.list_definitions(workspace_id, status=status)
    return [_serialize_definition(d) for d in defs]


@router.get("/definitions/{workflow_id}")
async def get_definition(
    workflow_id: uuid.UUID,
    user: CurrentUser = Depends(),
    db: DbSession = Depends(),
):
    service = WorkflowService(db)
    defn = await service.get_definition(workflow_id)
    return _serialize_definition(defn)


@router.patch("/definitions/{workflow_id}")
async def update_definition(
    workflow_id: uuid.UUID,
    req: UpdateDefinitionRequest,
    user: ManagerUser,
    db: DbSession,
):
    service = WorkflowService(db)
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    defn = await service.update_definition(workflow_id, **kwargs)
    return _serialize_definition(defn)


@router.post("/definitions/{workflow_id}/publish")
async def publish_definition(
    workflow_id: uuid.UUID,
    user: ManagerUser,
    db: DbSession,
):
    service = WorkflowService(db)
    defn = await service.publish_definition(workflow_id)
    return _serialize_definition(defn)


@router.post("/definitions/validate")
async def validate_definition(
    req: ValidateDefinitionRequest,
    user: CurrentUser = Depends(),
    db: DbSession = Depends(),
):
    service = WorkflowService(db)
    errors = await service.validate_definition(req.definition_json)
    return {"valid": len(errors) == 0, "errors": errors}


# ── Runs ─────────────────────────────────────────────────────────────────────


@router.post("/runs")
async def start_run(
    req: StartRunRequest,
    user: CurrentUser = Depends(),
    db: DbSession = Depends(),
):
    service = WorkflowService(db)
    run = await service.start_run(
        workflow_id=req.workflow_id,
        workspace_id=req.workspace_id,
        triggered_by=user.id,
        input_json=req.input_json,
    )

    # Enqueue for execution
    from app.config import get_settings
    settings = get_settings()
    if settings.enable_workflow_worker:
        import redis.asyncio as aioredis
        from app.workflows.engine.scheduler import WorkflowScheduler
        redis_client = aioredis.from_url(settings.redis_url)
        scheduler = WorkflowScheduler(redis_client, None)
        await scheduler.enqueue(run.id)

    return _serialize_run(run)


@router.get("/runs")
async def list_runs(
    workspace_id: uuid.UUID = Query(...),
    workflow_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
    user: CurrentUser = Depends(),
    db: DbSession = Depends(),
):
    service = WorkflowService(db)
    runs = await service.list_runs(workspace_id, workflow_id=workflow_id, status=status)
    return [_serialize_run(r) for r in runs]


@router.get("/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    user: CurrentUser = Depends(),
    db: DbSession = Depends(),
):
    service = WorkflowService(db)
    run = await service.get_run(run_id)
    return _serialize_run(run)


@router.get("/runs/{run_id}/progress")
async def get_run_progress(
    run_id: uuid.UUID,
    user: CurrentUser = Depends(),
    db: DbSession = Depends(),
):
    service = WorkflowService(db)
    return await service.get_run_progress(run_id)


@router.get("/runs/{run_id}/steps")
async def get_run_steps(
    run_id: uuid.UUID,
    user: CurrentUser = Depends(),
    db: DbSession = Depends(),
):
    service = WorkflowService(db)
    steps = await service.get_run_steps(run_id)
    return [
        {
            "id": str(s.id),
            "step_id": s.step_id,
            "step_index": s.step_index,
            "tool_name": s.tool_name,
            "status": s.status,
            "input_json": s.input_json,
            "output_json": s.output_json,
            "error_message": s.error_message,
            "duration_ms": s.duration_ms,
            "retry_count": s.retry_count,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "completed_at": s.completed_at.isoformat() if s.completed_at else None,
        }
        for s in steps
    ]


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: uuid.UUID,
    user: CurrentUser = Depends(),
    db: DbSession = Depends(),
):
    service = WorkflowService(db)
    run = await service.cancel_run(run_id)
    return _serialize_run(run)


@router.post("/runs/{run_id}/rerun-from/{step_id}")
async def rerun_from_step(
    run_id: uuid.UUID,
    step_id: str,
    req: RerunFromStepRequest | None = None,
    user: CurrentUser = Depends(),
    db: DbSession = Depends(),
):
    service = WorkflowService(db)
    overrides = req.overrides if req else None
    new_run = await service.rerun_from_step(
        original_run_id=run_id,
        step_id=step_id,
        overrides=overrides,
        triggered_by=user.id,
    )

    # Enqueue
    from app.config import get_settings
    settings = get_settings()
    if settings.enable_workflow_worker:
        import redis.asyncio as aioredis
        from app.workflows.engine.scheduler import WorkflowScheduler
        redis_client = aioredis.from_url(settings.redis_url)
        scheduler = WorkflowScheduler(redis_client, None)
        await scheduler.enqueue(new_run.id)

    return _serialize_run(new_run)


@router.get("/runs/{run_id}/audit")
async def get_audit_trail(
    run_id: uuid.UUID,
    user: ManagerUser,
    db: DbSession,
):
    service = WorkflowService(db)
    entries = await service.get_audit_trail(run_id)
    return [
        {
            "id": str(e.id),
            "event_type": e.event_type,
            "step_id": e.step_id,
            "user_id": str(e.user_id) if e.user_id else None,
            "details_json": e.details_json,
            "timestamp": e.timestamp.isoformat(),
        }
        for e in entries
    ]


# ── Approvals ────────────────────────────────────────────────────────────────


@router.get("/approvals/pending")
async def list_pending_approvals(
    workspace_id: uuid.UUID = Query(...),
    user: ManagerUser = Depends(),
    db: DbSession = Depends(),
):
    service = WorkflowService(db)
    approvals = await service.list_pending_approvals(workspace_id)
    return [
        {
            "id": str(a.id),
            "run_id": str(a.run_id),
            "step_id": a.step_id,
            "status": a.status,
            "context_json": a.context_json,
            "requested_at": a.requested_at.isoformat(),
        }
        for a in approvals
    ]


@router.post("/approvals/{approval_id}/decide")
async def decide_approval(
    approval_id: uuid.UUID,
    req: ApprovalDecisionRequest,
    user: ManagerUser,
    db: DbSession,
):
    service = WorkflowService(db)
    approval = await service.submit_approval(
        approval_id=approval_id,
        user_id=user.id,
        approved=req.approved,
        comment=req.comment,
    )

    # If approved, resume the run
    if req.approved:
        from app.config import get_settings
        settings = get_settings()
        if settings.enable_workflow_worker:
            import redis.asyncio as aioredis
            from app.workflows.engine.scheduler import WorkflowScheduler
            redis_client = aioredis.from_url(settings.redis_url)
            scheduler = WorkflowScheduler(redis_client, None)
            await scheduler.resume(approval.run_id)

    return {"id": str(approval.id), "status": approval.status}


# ── Tools ────────────────────────────────────────────────────────────────────


@router.get("/tools")
async def list_tools(user: CurrentUser = Depends()):
    return ToolRegistry.list_tools()


# ── Serializers ──────────────────────────────────────────────────────────────


def _serialize_definition(d: "WorkflowDefinition") -> dict:
    return {
        "id": str(d.id),
        "workspace_id": str(d.workspace_id),
        "name": d.name,
        "slug": d.slug,
        "description": d.description,
        "version": d.version,
        "status": d.status,
        "definition_json": d.definition_json,
        "is_template": d.is_template,
        "required_role": d.required_role,
        "created_by": str(d.created_by),
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _serialize_run(r: "WorkflowRun") -> dict:
    return {
        "id": str(r.id),
        "workflow_id": str(r.workflow_id),
        "workspace_id": str(r.workspace_id),
        "triggered_by": str(r.triggered_by),
        "status": r.status,
        "current_step_index": r.current_step_index,
        "progress_pct": r.progress_pct,
        "input_json": r.input_json,
        "output_json": r.output_json,
        "error_message": r.error_message,
        "parent_run_id": str(r.parent_run_id) if r.parent_run_id else None,
        "overrides_json": r.overrides_json,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
