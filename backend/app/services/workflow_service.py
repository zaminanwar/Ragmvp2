"""Workflow service — business logic for definitions, runs, approvals."""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError
from app.models.workflow import (
    ApprovalStatus,
    DefinitionStatus,
    RunStatus,
    WorkflowApproval,
    WorkflowAuditEntry,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStepResult,
)
from app.workflows.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Definitions ──────────────────────────────────────────────────────

    async def create_definition(
        self,
        workspace_id: uuid.UUID,
        name: str,
        definition_json: dict,
        created_by: uuid.UUID,
        description: str | None = None,
        is_template: bool = False,
        required_role: str = "member",
    ) -> WorkflowDefinition:
        slug = name.lower().replace(" ", "-").replace("_", "-")
        defn = WorkflowDefinition(
            workspace_id=workspace_id,
            name=name,
            slug=slug,
            description=description,
            definition_json=definition_json,
            created_by=created_by,
            is_template=is_template,
            required_role=required_role,
        )
        self.db.add(defn)
        await self.db.flush()
        await self.db.refresh(defn)
        return defn

    async def get_definition(self, workflow_id: uuid.UUID) -> WorkflowDefinition:
        result = await self.db.execute(
            select(WorkflowDefinition).where(WorkflowDefinition.id == workflow_id)
        )
        defn = result.scalar_one_or_none()
        if not defn:
            raise NotFoundError("Workflow definition not found")
        return defn

    async def list_definitions(
        self, workspace_id: uuid.UUID, status: str | None = None
    ) -> list[WorkflowDefinition]:
        q = select(WorkflowDefinition).where(
            WorkflowDefinition.workspace_id == workspace_id
        )
        if status:
            q = q.where(WorkflowDefinition.status == status)
        q = q.order_by(WorkflowDefinition.created_at.desc())
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def update_definition(
        self, workflow_id: uuid.UUID, **kwargs
    ) -> WorkflowDefinition:
        defn = await self.get_definition(workflow_id)
        for key, value in kwargs.items():
            if hasattr(defn, key):
                setattr(defn, key, value)
        await self.db.flush()
        return defn

    async def publish_definition(self, workflow_id: uuid.UUID) -> WorkflowDefinition:
        defn = await self.get_definition(workflow_id)
        defn.status = DefinitionStatus.PUBLISHED.value
        await self.db.flush()
        await self.db.refresh(defn)
        return defn

    async def validate_definition(self, definition_json: dict) -> list[str]:
        """Validate a workflow definition schema. Returns list of error messages."""
        errors = []
        if "steps" not in definition_json:
            errors.append("Missing 'steps' array")
            return errors

        steps = definition_json["steps"]
        step_ids = set()

        for i, step in enumerate(steps):
            if "id" not in step:
                errors.append(f"Step {i}: missing 'id'")
            elif step["id"] in step_ids:
                errors.append(f"Step {i}: duplicate id '{step['id']}'")
            else:
                step_ids.add(step["id"])

            if "tool" not in step:
                errors.append(f"Step {i}: missing 'tool'")
            elif not ToolRegistry.has(step["tool"]):
                errors.append(f"Step {i}: tool '{step['tool']}' not registered")

            # Validate variable references point to earlier steps
            inputs = step.get("inputs", {})
            for key, val in inputs.items():
                if isinstance(val, str) and val.startswith("$steps."):
                    ref_step = val.split(".")[1]
                    if ref_step not in step_ids:
                        errors.append(
                            f"Step {i} ({step.get('id', '?')}): input '{key}' references "
                            f"step '{ref_step}' which hasn't executed yet"
                        )

        return errors

    # ── Runs ─────────────────────────────────────────────────────────────

    async def start_run(
        self,
        workflow_id: uuid.UUID,
        workspace_id: uuid.UUID,
        triggered_by: uuid.UUID,
        input_json: dict,
    ) -> WorkflowRun:
        defn = await self.get_definition(workflow_id)
        run = WorkflowRun(
            workflow_id=workflow_id,
            workspace_id=workspace_id,
            triggered_by=triggered_by,
            input_json=input_json,
            definition_snapshot_json=copy.deepcopy(defn.definition_json),
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def rerun_from_step(
        self,
        original_run_id: uuid.UUID,
        step_id: str,
        overrides: dict | None = None,
        triggered_by: uuid.UUID | None = None,
    ) -> WorkflowRun:
        """Create a new run that copies state up to step_id from an existing run."""
        original = await self.get_run(original_run_id)
        definition = original.definition_snapshot_json
        steps = definition.get("steps", [])

        # Find the step index
        target_index = None
        for i, s in enumerate(steps):
            if s["id"] == step_id:
                target_index = i
                break
        if target_index is None:
            raise NotFoundError(f"Step '{step_id}' not found in workflow definition")

        # Copy state from steps before target_index
        copied_state = {}
        for i in range(target_index):
            sid = steps[i]["id"]
            if sid in (original.state_json or {}):
                copied_state[sid] = copy.deepcopy(original.state_json[sid])

        new_run = WorkflowRun(
            workflow_id=original.workflow_id,
            workspace_id=original.workspace_id,
            triggered_by=triggered_by or original.triggered_by,
            input_json=copy.deepcopy(original.input_json),
            definition_snapshot_json=copy.deepcopy(definition),
            state_json=copied_state,
            current_step_index=target_index,
            parent_run_id=original.id,
            overrides_json=overrides,
        )
        self.db.add(new_run)
        await self.db.flush()
        await self.db.refresh(new_run)
        return new_run

    async def get_run(self, run_id: uuid.UUID) -> WorkflowRun:
        result = await self.db.execute(
            select(WorkflowRun).where(WorkflowRun.id == run_id)
        )
        run = result.scalar_one_or_none()
        if not run:
            raise NotFoundError("Workflow run not found")
        return run

    async def list_runs(
        self,
        workspace_id: uuid.UUID,
        workflow_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> list[WorkflowRun]:
        q = select(WorkflowRun).where(WorkflowRun.workspace_id == workspace_id)
        if workflow_id:
            q = q.where(WorkflowRun.workflow_id == workflow_id)
        if status:
            q = q.where(WorkflowRun.status == status)
        q = q.order_by(WorkflowRun.created_at.desc())
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def cancel_run(self, run_id: uuid.UUID) -> WorkflowRun:
        run = await self.get_run(run_id)
        run.status = RunStatus.CANCELLED.value
        run.completed_at = _utcnow()
        await self.db.flush()
        return run

    async def get_run_steps(self, run_id: uuid.UUID) -> list[WorkflowStepResult]:
        result = await self.db.execute(
            select(WorkflowStepResult)
            .where(WorkflowStepResult.run_id == run_id)
            .order_by(WorkflowStepResult.step_index)
        )
        return list(result.scalars().all())

    async def get_run_progress(self, run_id: uuid.UUID) -> dict:
        run = await self.get_run(run_id)
        steps = await self.get_run_steps(run_id)
        total = len(run.definition_snapshot_json.get("steps", []))
        return {
            "run_id": str(run.id),
            "status": run.status,
            "current_step_index": run.current_step_index,
            "total_steps": total,
            "progress_pct": run.progress_pct,
            "steps": [
                {
                    "step_id": s.step_id,
                    "status": s.status,
                    "tool_name": s.tool_name,
                    "duration_ms": s.duration_ms,
                    "error_message": s.error_message,
                }
                for s in steps
            ],
        }

    # ── Approvals ────────────────────────────────────────────────────────

    async def submit_approval(
        self,
        approval_id: uuid.UUID,
        user_id: uuid.UUID,
        approved: bool,
        comment: str | None = None,
    ) -> WorkflowApproval:
        result = await self.db.execute(
            select(WorkflowApproval).where(WorkflowApproval.id == approval_id)
        )
        approval = result.scalar_one_or_none()
        if not approval:
            raise NotFoundError("Approval not found")

        approval.status = ApprovalStatus.APPROVED.value if approved else ApprovalStatus.REJECTED.value
        approval.decided_by = user_id
        approval.decided_at = _utcnow()
        approval.comment = comment
        await self.db.flush()

        # Update run status
        run = await self.get_run(approval.run_id)
        if approved:
            run.status = RunStatus.RUNNING.value
        else:
            run.status = RunStatus.FAILED.value
            run.error_message = f"Approval rejected at step '{approval.step_id}'"
            run.completed_at = _utcnow()

        # Audit
        entry = WorkflowAuditEntry(
            run_id=approval.run_id,
            event_type="approval_granted" if approved else "approval_rejected",
            step_id=approval.step_id,
            user_id=user_id,
            details_json={"comment": comment or ""},
        )
        self.db.add(entry)
        await self.db.flush()

        return approval

    async def list_pending_approvals(
        self, workspace_id: uuid.UUID
    ) -> list[WorkflowApproval]:
        result = await self.db.execute(
            select(WorkflowApproval)
            .join(WorkflowRun, WorkflowApproval.run_id == WorkflowRun.id)
            .where(
                WorkflowRun.workspace_id == workspace_id,
                WorkflowApproval.status == ApprovalStatus.PENDING.value,
            )
            .order_by(WorkflowApproval.requested_at.desc())
        )
        return list(result.scalars().all())

    # ── Audit ────────────────────────────────────────────────────────────

    async def get_audit_trail(self, run_id: uuid.UUID) -> list[WorkflowAuditEntry]:
        result = await self.db.execute(
            select(WorkflowAuditEntry)
            .where(WorkflowAuditEntry.run_id == run_id)
            .order_by(WorkflowAuditEntry.timestamp)
        )
        return list(result.scalars().all())
