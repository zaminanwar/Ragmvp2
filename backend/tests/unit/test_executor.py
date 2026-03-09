"""Unit tests for WorkflowExecutor with mocked DB and tools."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.workflow import (
    ApprovalStatus,
    RunStatus,
    StepStatus,
    WorkflowApproval,
    WorkflowAuditEntry,
    WorkflowStepResult,
)
from app.workflows.engine.executor import WorkflowExecutor
from app.workflows.tools.base import ToolInput, ToolOutput
from app.workflows.tools.registry import ToolRegistry
from tests.conftest import EchoTool, ExplodeTool, FailTool, make_run


# ── Helpers ──────────────────────────────────────────────────────────────────


def _two_step_definition(tool1="test.echo", tool2="test.echo"):
    return {
        "steps": [
            {
                "id": "step_a",
                "name": "Step A",
                "tool": tool1,
                "inputs": {"msg": "$inputs.greeting"},
                "outputs": ["msg"],
            },
            {
                "id": "step_b",
                "name": "Step B",
                "tool": tool2,
                "inputs": {"msg": "$steps.step_a.output.msg"},
                "outputs": ["msg"],
            },
        ],
        "outputs": {
            "final": {"from": "$steps.step_b.output.msg"},
        },
    }


# ── Happy path ──────────────────────────────────────────────────────────────


class TestExecutorHappyPath:
    @pytest.mark.asyncio
    async def test_two_step_success(self, mock_db, echo_tool):
        definition = _two_step_definition()
        run = make_run(
            definition_snapshot_json=definition,
            input_json={"greeting": "hello"},
        )

        executor = WorkflowExecutor(mock_db, run)
        await executor.execute()

        assert run.status == RunStatus.COMPLETED.value
        assert run.completed_at is not None
        assert run.progress_pct == 100
        assert run.output_json == {"final": "hello"}

    @pytest.mark.asyncio
    async def test_state_accumulates(self, mock_db, echo_tool):
        definition = _two_step_definition()
        run = make_run(
            definition_snapshot_json=definition,
            input_json={"greeting": "world"},
        )

        executor = WorkflowExecutor(mock_db, run)
        await executor.execute()

        # Both steps should be in state
        assert "step_a" in run.state_json
        assert "step_b" in run.state_json
        assert run.state_json["step_a"]["output"]["msg"] == "world"

    @pytest.mark.asyncio
    async def test_step_results_recorded(self, mock_db, echo_tool):
        definition = _two_step_definition()
        run = make_run(
            definition_snapshot_json=definition,
            input_json={"greeting": "hi"},
        )

        executor = WorkflowExecutor(mock_db, run)
        await executor.execute()

        # Check that WorkflowStepResult objects were added to DB
        step_results = [
            obj for obj in mock_db.added if isinstance(obj, WorkflowStepResult)
        ]
        assert len(step_results) == 2
        assert step_results[0].step_id == "step_a"
        assert step_results[1].step_id == "step_b"
        assert step_results[0].status == StepStatus.COMPLETED.value
        assert step_results[1].status == StepStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_audit_entries_created(self, mock_db, echo_tool):
        definition = _two_step_definition()
        run = make_run(
            definition_snapshot_json=definition,
            input_json={"greeting": "hi"},
        )

        executor = WorkflowExecutor(mock_db, run)
        await executor.execute()

        audit_entries = [
            obj for obj in mock_db.added if isinstance(obj, WorkflowAuditEntry)
        ]
        event_types = [e.event_type for e in audit_entries]
        assert "run_started" in event_types
        assert "run_completed" in event_types
        assert event_types.count("step_started") == 2
        assert event_types.count("step_completed") == 2


# ── Step failure ─────────────────────────────────────────────────────────────


class TestExecutorFailure:
    @pytest.mark.asyncio
    async def test_step_failure_fails_run(self, mock_db, echo_tool, fail_tool):
        definition = _two_step_definition(tool2="test.fail")
        run = make_run(
            definition_snapshot_json=definition,
            input_json={"greeting": "hi"},
        )

        executor = WorkflowExecutor(mock_db, run)
        await executor.execute()

        assert run.status == RunStatus.FAILED.value
        assert run.error_message is not None
        assert "step_b" in run.error_message

    @pytest.mark.asyncio
    async def test_exception_fails_run(self, mock_db, echo_tool, explode_tool):
        definition = _two_step_definition(tool2="test.explode")
        run = make_run(
            definition_snapshot_json=definition,
            input_json={"greeting": "hi"},
        )

        executor = WorkflowExecutor(mock_db, run)
        await executor.execute()

        assert run.status == RunStatus.FAILED.value
        assert "boom" in run.error_message

    @pytest.mark.asyncio
    async def test_resolution_error_fails_step(self, mock_db, echo_tool):
        """If variable resolution fails, the step should fail."""
        definition = {
            "steps": [
                {
                    "id": "bad_step",
                    "name": "Bad",
                    "tool": "test.echo",
                    "inputs": {"data": "$steps.nonexistent.output.x"},
                    "outputs": ["data"],
                }
            ],
        }
        run = make_run(
            definition_snapshot_json=definition,
            input_json={},
        )

        executor = WorkflowExecutor(mock_db, run)
        await executor.execute()

        assert run.status == RunStatus.FAILED.value


# ── Error policy ─────────────────────────────────────────────────────────────


class TestErrorPolicy:
    @pytest.mark.asyncio
    async def test_pause_policy(self, mock_db, fail_tool):
        definition = {
            "steps": [
                {
                    "id": "pausable",
                    "name": "Pausable",
                    "tool": "test.fail",
                    "inputs": {},
                    "outputs": [],
                }
            ],
            "error_policy": {
                "default": "fail",
                "on_step_failure": {"pausable": "pause"},
            },
        }
        run = make_run(
            definition_snapshot_json=definition,
            input_json={},
        )

        executor = WorkflowExecutor(mock_db, run)
        await executor.execute()

        assert run.status == RunStatus.PAUSED.value

    @pytest.mark.asyncio
    async def test_default_fail_policy(self, mock_db, fail_tool):
        definition = {
            "steps": [
                {
                    "id": "s1",
                    "name": "S1",
                    "tool": "test.fail",
                    "inputs": {},
                    "outputs": [],
                }
            ],
            "error_policy": {"default": "fail"},
        }
        run = make_run(
            definition_snapshot_json=definition,
            input_json={},
        )

        executor = WorkflowExecutor(mock_db, run)
        await executor.execute()

        assert run.status == RunStatus.FAILED.value


# ── Retry logic ──────────────────────────────────────────────────────────────


class TestRetry:
    @pytest.mark.asyncio
    async def test_retry_on_failure(self, mock_db):
        """Tool fails twice then succeeds on third attempt."""
        call_count = 0

        class RetryTool(EchoTool):
            name = "test.retry"

            async def execute(self, tool_input: ToolInput) -> ToolOutput:
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    return ToolOutput(success=False, error=f"fail #{call_count}")
                return ToolOutput(success=True, data={"ok": True})

        ToolRegistry.register(RetryTool())

        definition = {
            "steps": [
                {
                    "id": "retryable",
                    "name": "Retryable",
                    "tool": "test.retry",
                    "inputs": {},
                    "outputs": ["ok"],
                    "retry": {"max_attempts": 3, "backoff_seconds": 0},
                }
            ],
        }
        run = make_run(
            definition_snapshot_json=definition,
            input_json={},
        )

        executor = WorkflowExecutor(mock_db, run)
        await executor.execute()

        assert run.status == RunStatus.COMPLETED.value
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhausted(self, mock_db, fail_tool):
        definition = {
            "steps": [
                {
                    "id": "s1",
                    "name": "S1",
                    "tool": "test.fail",
                    "inputs": {},
                    "outputs": [],
                    "retry": {"max_attempts": 2, "backoff_seconds": 0},
                }
            ],
        }
        run = make_run(
            definition_snapshot_json=definition,
            input_json={},
        )

        executor = WorkflowExecutor(mock_db, run)
        await executor.execute()

        assert run.status == RunStatus.FAILED.value


# ── Resumption from step index ──────────────────────────────────────────────


class TestResumption:
    @pytest.mark.asyncio
    async def test_resume_from_step_1(self, mock_db, echo_tool):
        """Simulates resuming after step 0 was already completed."""
        definition = _two_step_definition()
        run = make_run(
            definition_snapshot_json=definition,
            input_json={"greeting": "resumed"},
            state_json={"step_a": {"output": {"msg": "resumed"}}},
            current_step_index=1,
        )

        executor = WorkflowExecutor(mock_db, run)
        await executor.execute()

        assert run.status == RunStatus.COMPLETED.value
        assert "step_b" in run.state_json
        # Only step_b should have been executed
        step_results = [
            obj for obj in mock_db.added if isinstance(obj, WorkflowStepResult)
        ]
        step_ids = [sr.step_id for sr in step_results]
        assert "step_a" not in step_ids
        assert "step_b" in step_ids


# ── Checkpoint / approval ───────────────────────────────────────────────────


class TestCheckpoint:
    @pytest.mark.asyncio
    async def test_checkpoint_pauses_run(self, mock_db, echo_tool):
        definition = {
            "steps": [
                {
                    "id": "gated",
                    "name": "Gated Step",
                    "tool": "test.echo",
                    "inputs": {"msg": "hello"},
                    "outputs": ["msg"],
                    "checkpoint": {
                        "type": "approval",
                        "message": "Please approve",
                        "required_role": "manager",
                    },
                }
            ],
        }
        run = make_run(
            definition_snapshot_json=definition,
            input_json={},
        )

        # Mock DB execute to return no existing approval
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        executor = WorkflowExecutor(mock_db, run)
        await executor.execute()

        assert run.status == RunStatus.WAITING_APPROVAL.value
        # An approval record should have been added
        approvals = [
            obj for obj in mock_db.added if isinstance(obj, WorkflowApproval)
        ]
        assert len(approvals) == 1
        assert approvals[0].step_id == "gated"

    @pytest.mark.asyncio
    async def test_approved_checkpoint_continues(self, mock_db, echo_tool):
        definition = {
            "steps": [
                {
                    "id": "gated",
                    "name": "Gated Step",
                    "tool": "test.echo",
                    "inputs": {"msg": "hello"},
                    "outputs": ["msg"],
                    "checkpoint": {
                        "type": "approval",
                        "message": "Please approve",
                    },
                }
            ],
            "outputs": {"result": {"from": "$steps.gated.output.msg"}},
        }
        run = make_run(
            definition_snapshot_json=definition,
            input_json={},
        )

        # Mock DB execute to return an already-approved approval
        existing_approval = MagicMock()
        existing_approval.status = ApprovalStatus.APPROVED.value
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_approval
        mock_db.execute = AsyncMock(return_value=mock_result)

        executor = WorkflowExecutor(mock_db, run)
        await executor.execute()

        assert run.status == RunStatus.COMPLETED.value

    @pytest.mark.asyncio
    async def test_rejected_checkpoint_fails_run(self, mock_db, echo_tool):
        definition = {
            "steps": [
                {
                    "id": "gated",
                    "name": "Gated",
                    "tool": "test.echo",
                    "inputs": {"msg": "hello"},
                    "outputs": ["msg"],
                    "checkpoint": {"type": "approval", "message": "Approve?"},
                }
            ],
        }
        run = make_run(
            definition_snapshot_json=definition,
            input_json={},
        )

        rejected = MagicMock()
        rejected.status = ApprovalStatus.REJECTED.value
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = rejected
        mock_db.execute = AsyncMock(return_value=mock_result)

        executor = WorkflowExecutor(mock_db, run)
        await executor.execute()

        assert run.status == RunStatus.FAILED.value
        assert "rejected" in run.error_message.lower()


# ── Loop execution ──────────────────────────────────────────────────────────


class TestLoopExecution:
    @pytest.mark.asyncio
    async def test_loop_over_items(self, mock_db, echo_tool):
        definition = {
            "steps": [
                {
                    "id": "loop_step",
                    "name": "Loop",
                    "tool": "test.echo",
                    "inputs": {"msg": "$item.text"},
                    "outputs": ["results"],
                    "loop": {
                        "over": "$inputs.items",
                        "as": "item",
                        "batch_size": 2,
                        "concurrency": 1,
                    },
                }
            ],
        }
        run = make_run(
            definition_snapshot_json=definition,
            input_json={"items": [{"text": "a"}, {"text": "b"}, {"text": "c"}]},
        )

        executor = WorkflowExecutor(mock_db, run)
        await executor.execute()

        assert run.status == RunStatus.COMPLETED.value
        loop_output = run.state_json["loop_step"]["output"]["results"]
        assert len(loop_output) == 3


# ── Overrides ────────────────────────────────────────────────────────────────


class TestOverrides:
    @pytest.mark.asyncio
    async def test_step_input_override(self, mock_db, echo_tool):
        definition = {
            "steps": [
                {
                    "id": "s1",
                    "name": "S1",
                    "tool": "test.echo",
                    "inputs": {"msg": "$inputs.original"},
                    "outputs": ["msg"],
                }
            ],
        }
        run = make_run(
            definition_snapshot_json=definition,
            input_json={"original": "old_value"},
            overrides_json={"s1": {"inputs": {"msg": "overridden"}}},
        )

        executor = WorkflowExecutor(mock_db, run)
        await executor.execute()

        assert run.status == RunStatus.COMPLETED.value
        assert run.state_json["s1"]["output"]["msg"] == "overridden"
