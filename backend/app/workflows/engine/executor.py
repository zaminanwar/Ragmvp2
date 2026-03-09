"""Workflow executor — walks through steps, resolves variables, calls tools."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import (
    RunStatus,
    StepStatus,
    ApprovalStatus,
    WorkflowApproval,
    WorkflowAuditEntry,
    WorkflowRun,
    WorkflowStepResult,
)
from app.workflows.engine.resolver import VariableResolver
from app.workflows.tools.base import ToolInput, ToolOutput
from app.workflows.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowExecutor:
    """Execute a workflow run from current_step_index to completion (or pause)."""

    def __init__(self, db: AsyncSession, run: WorkflowRun):
        self.db = db
        self.run = run
        self._definition = run.definition_snapshot_json
        self._state: dict = run.state_json or {}
        self._overrides: dict = run.overrides_json or {}
        self._resolver = VariableResolver(
            state=self._state,
            inputs=run.input_json,
            context={
                "workspace_id": str(run.workspace_id),
                "user_id": str(run.triggered_by),
                "run_id": str(run.id),
            },
        )

    # ── Public API ───────────────────────────────────────────────────────

    async def execute(self) -> None:
        """Execute steps starting from current_step_index."""
        steps = self._definition["steps"]

        self.run.status = RunStatus.RUNNING.value
        self.run.started_at = self.run.started_at or _utcnow()
        await self._save_state()
        await self._audit("run_started")

        for i in range(self.run.current_step_index, len(steps)):
            step = steps[i]
            step_id = step["id"]

            # ── Post-step checkpoint gate ────────────────────────────
            if "checkpoint" in step:
                should_pause = await self._handle_checkpoint(step, i)
                if should_pause:
                    return  # paused — scheduler will resume on approval

            # ── Execute step ─────────────────────────────────────────
            if "loop" in step:
                success = await self._execute_loop(step, i)
            else:
                success = await self._execute_step(step, i)

            if not success:
                policy = self._get_error_policy(step_id)
                if policy == "pause":
                    self.run.status = RunStatus.PAUSED.value
                    await self._save_state()
                    return
                # default: fail the whole run
                self.run.status = RunStatus.FAILED.value
                self.run.completed_at = _utcnow()
                await self._save_state()
                await self._audit("run_failed", step_id=step_id)
                return

            # ── Advance ──────────────────────────────────────────────
            self.run.current_step_index = i + 1
            self.run.progress_pct = int(((i + 1) / len(steps)) * 100)
            await self._save_state()

        # ── All steps done ───────────────────────────────────────────
        self.run.status = RunStatus.COMPLETED.value
        self.run.completed_at = _utcnow()
        self.run.output_json = self._resolve_outputs()
        await self._save_state()
        await self._audit("run_completed")

    # ── Step execution ───────────────────────────────────────────────────

    async def _execute_step(self, step_def: dict, index: int) -> bool:
        """Execute a single step. Returns True on success."""
        step_id = step_def["id"]
        tool_name = step_def["tool"]
        max_attempts = step_def.get("retry", {}).get("max_attempts", 1)
        backoff = step_def.get("retry", {}).get("backoff_seconds", 5)

        # Resolve inputs, merging any overrides
        raw_inputs = dict(step_def.get("inputs", {}))
        if step_id in self._overrides:
            override_inputs = self._overrides[step_id].get("inputs", {})
            raw_inputs.update(override_inputs)

        try:
            resolved_inputs = self._resolver.resolve(raw_inputs)
        except Exception as e:
            return await self._record_step_failure(step_id, index, tool_name, {}, str(e))

        tool = ToolRegistry.get(tool_name)

        # Validate
        errors = await tool.validate_input(resolved_inputs)
        if errors:
            return await self._record_step_failure(
                step_id, index, tool_name, resolved_inputs, f"Validation: {'; '.join(errors)}"
            )

        # Execute with retries
        step_result = WorkflowStepResult(
            run_id=self.run.id,
            step_id=step_id,
            step_index=index,
            tool_name=tool_name,
            status=StepStatus.RUNNING.value,
            input_json=resolved_inputs,
            started_at=_utcnow(),
        )
        self.db.add(step_result)
        await self._audit("step_started", step_id=step_id)

        for attempt in range(max_attempts):
            t0 = time.monotonic()
            try:
                tool_input = ToolInput(
                    params=resolved_inputs,
                    context={
                        "workspace_id": str(self.run.workspace_id),
                        "user_id": str(self.run.triggered_by),
                        "run_id": str(self.run.id),
                    },
                )
                output: ToolOutput = await tool.execute(tool_input)
                elapsed_ms = int((time.monotonic() - t0) * 1000)

                if output.success:
                    step_result.status = StepStatus.COMPLETED.value
                    step_result.output_json = output.data
                    step_result.completed_at = _utcnow()
                    step_result.duration_ms = elapsed_ms
                    step_result.retry_count = attempt

                    # Store in state for downstream resolution
                    self._state[step_id] = {"output": output.data}
                    self.run.state_json = self._state
                    await self._audit(
                        "step_completed", step_id=step_id,
                        details_json={"duration_ms": elapsed_ms, "metadata": output.metadata},
                    )
                    return True

                # Tool returned failure
                step_result.retry_count = attempt
                if attempt < max_attempts - 1:
                    logger.warning("step_retry", step_id=step_id, attempt=attempt, error=output.error)
                    await asyncio.sleep(backoff * (attempt + 1))
                    continue

                step_result.status = StepStatus.FAILED.value
                step_result.error_message = output.error
                step_result.completed_at = _utcnow()
                step_result.duration_ms = elapsed_ms
                self.run.error_message = f"Step '{step_id}' failed: {output.error}"
                await self._audit("step_failed", step_id=step_id, details_json={"error": output.error})
                return False

            except Exception as exc:
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                if attempt < max_attempts - 1:
                    logger.warning("step_exception_retry", step_id=step_id, attempt=attempt, error=str(exc))
                    await asyncio.sleep(backoff * (attempt + 1))
                    continue

                step_result.status = StepStatus.FAILED.value
                step_result.error_message = str(exc)
                step_result.completed_at = _utcnow()
                step_result.duration_ms = elapsed_ms
                self.run.error_message = f"Step '{step_id}' exception: {exc}"
                await self._audit("step_failed", step_id=step_id, details_json={"error": str(exc)})
                return False

        return False  # unreachable but satisfies type checker

    async def _record_step_failure(
        self, step_id: str, index: int, tool_name: str, inputs: dict, error: str
    ) -> bool:
        step_result = WorkflowStepResult(
            run_id=self.run.id,
            step_id=step_id,
            step_index=index,
            tool_name=tool_name,
            status=StepStatus.FAILED.value,
            input_json=inputs,
            error_message=error,
            started_at=_utcnow(),
            completed_at=_utcnow(),
        )
        self.db.add(step_result)
        self.run.error_message = f"Step '{step_id}': {error}"
        await self._audit("step_failed", step_id=step_id, details_json={"error": error})
        return False

    # ── Loop execution ───────────────────────────────────────────────────

    async def _execute_loop(self, step_def: dict, index: int) -> bool:
        """Execute a step that loops over a list of items."""
        loop_cfg = step_def["loop"]
        items_ref = loop_cfg["over"]
        batch_size = loop_cfg.get("batch_size", 1)
        concurrency = loop_cfg.get("concurrency", 1)

        items = self._resolver.resolve(items_ref)
        if not isinstance(items, list):
            return await self._record_step_failure(
                step_def["id"], index, step_def["tool"], {},
                f"Loop 'over' resolved to {type(items).__name__}, expected list"
            )

        all_results = []
        sem = asyncio.Semaphore(concurrency)

        async def process_batch(batch: list) -> list[ToolOutput]:
            results = []
            for item in batch:
                async with sem:
                    self._resolver.set_loop_var("item", item)
                    raw_inputs = dict(step_def.get("inputs", {}))
                    if step_def["id"] in self._overrides:
                        raw_inputs.update(self._overrides[step_def["id"]].get("inputs", {}))
                    resolved = self._resolver.resolve(raw_inputs)

                    tool = ToolRegistry.get(step_def["tool"])
                    tool_input = ToolInput(
                        params=resolved,
                        context={
                            "workspace_id": str(self.run.workspace_id),
                            "user_id": str(self.run.triggered_by),
                            "run_id": str(self.run.id),
                        },
                    )
                    output = await tool.execute(tool_input)
                    results.append(output)
            return results

        # Process in batches
        for i in range(0, len(items), batch_size):
            batch = items[i : i + batch_size]
            batch_outputs = await process_batch(batch)
            for out in batch_outputs:
                if out.success:
                    all_results.append(out.data)
                else:
                    logger.warning("loop_item_failed", step_id=step_def["id"], error=out.error)
                    all_results.append({"error": out.error})

        self._resolver.clear_loop_vars()

        # Store aggregated results
        output_keys = step_def.get("outputs", [])
        aggregated = {}
        if output_keys:
            aggregated[output_keys[0]] = all_results
        self._state[step_def["id"]] = {"output": aggregated}
        self.run.state_json = self._state

        # Record step result
        step_result = WorkflowStepResult(
            run_id=self.run.id,
            step_id=step_def["id"],
            step_index=index,
            tool_name=step_def["tool"],
            status=StepStatus.COMPLETED.value,
            input_json={"loop_items_count": len(items)},
            output_json=aggregated,
            started_at=_utcnow(),
            completed_at=_utcnow(),
        )
        self.db.add(step_result)
        await self._audit("step_completed", step_id=step_def["id"],
                          details_json={"loop_items": len(items)})
        return True

    # ── Checkpoint handling ──────────────────────────────────────────────

    async def _handle_checkpoint(self, step_def: dict, index: int) -> bool:
        """Check if this step's checkpoint needs approval. Returns True if pausing."""
        step_id = step_def["id"]
        checkpoint = step_def["checkpoint"]

        # Check if approval already exists and was granted
        from sqlalchemy import select
        result = await self.db.execute(
            select(WorkflowApproval).where(
                WorkflowApproval.run_id == self.run.id,
                WorkflowApproval.step_id == step_id,
            )
        )
        existing = result.scalar_one_or_none()

        if existing and existing.status == ApprovalStatus.APPROVED.value:
            return False  # already approved, continue

        if existing and existing.status == ApprovalStatus.REJECTED.value:
            self.run.status = RunStatus.FAILED.value
            self.run.error_message = f"Approval rejected at step '{step_id}'"
            self.run.completed_at = _utcnow()
            await self._save_state()
            await self._audit("run_failed", step_id=step_id,
                              details_json={"reason": "approval_rejected"})
            return True

        if not existing:
            # Create approval request
            context_data = {}
            if "show_data" in checkpoint:
                try:
                    context_data = self._resolver.resolve(checkpoint["show_data"])
                except Exception:
                    context_data = {"error": "Could not resolve show_data"}

            approval = WorkflowApproval(
                run_id=self.run.id,
                step_id=step_id,
                context_json=context_data if isinstance(context_data, dict) else {"data": context_data},
            )
            self.db.add(approval)
            self.run.status = RunStatus.WAITING_APPROVAL.value
            self.run.current_step_index = index
            await self._save_state()
            await self._audit("approval_requested", step_id=step_id,
                              details_json={"message": checkpoint.get("message", "")})
            return True

        # Pending — still waiting
        return True

    # ── Output resolution ────────────────────────────────────────────────

    def _resolve_outputs(self) -> dict:
        outputs_def = self._definition.get("outputs", {})
        result = {}
        for key, spec in outputs_def.items():
            try:
                result[key] = self._resolver.resolve(spec.get("from", ""))
            except Exception as e:
                result[key] = f"<unresolved: {e}>"
        return result

    # ── Error policy ─────────────────────────────────────────────────────

    def _get_error_policy(self, step_id: str) -> str:
        error_policy = self._definition.get("error_policy", {})
        per_step = error_policy.get("on_step_failure", {})
        return per_step.get(step_id, error_policy.get("default", "fail"))

    # ── Persistence helpers ──────────────────────────────────────────────

    async def _save_state(self) -> None:
        self.run.state_json = self._state
        self.db.add(self.run)
        await self.db.flush()

    async def _audit(
        self,
        event_type: str,
        step_id: str | None = None,
        details_json: dict | None = None,
    ) -> None:
        entry = WorkflowAuditEntry(
            run_id=self.run.id,
            event_type=event_type,
            step_id=step_id,
            user_id=self.run.triggered_by,
            details_json=details_json or {},
        )
        self.db.add(entry)
        await self.db.flush()
        logger.info(
            "workflow_audit",
            run_id=str(self.run.id),
            event=event_type,
            step_id=step_id,
        )
