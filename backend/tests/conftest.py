"""Shared test fixtures for the workflow engine test suite."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.workflow import (
    ApprovalStatus,
    RunStatus,
    StepStatus,
    WorkflowApproval,
    WorkflowRun,
)
from app.workflows.tools.base import BaseTool, ToolInput, ToolOutput
from app.workflows.tools.registry import ToolRegistry


# ── Helpers ──────────────────────────────────────────────────────────────────


class EchoTool(BaseTool):
    """Test tool that echoes its params back as output."""

    name = "test.echo"
    description = "Echoes input params."
    input_schema = {"type": "object", "properties": {"msg": {"type": "string"}}}
    output_schema = {"type": "object", "properties": {"msg": {"type": "string"}}}

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        return ToolOutput(success=True, data=tool_input.params)


class FailTool(BaseTool):
    """Test tool that always fails."""

    name = "test.fail"
    description = "Always fails."
    input_schema = {}
    output_schema = {}

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        return ToolOutput(success=False, error="intentional failure")


class ExplodeTool(BaseTool):
    """Test tool that raises an exception."""

    name = "test.explode"
    description = "Raises an exception."
    input_schema = {}
    output_schema = {}

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        raise RuntimeError("boom")


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_registry():
    """Ensure ToolRegistry is clean before/after every test."""
    ToolRegistry.clear()
    yield
    ToolRegistry.clear()


@pytest.fixture
def echo_tool():
    tool = EchoTool()
    ToolRegistry.register(tool)
    return tool


@pytest.fixture
def fail_tool():
    tool = FailTool()
    ToolRegistry.register(tool)
    return tool


@pytest.fixture
def explode_tool():
    tool = ExplodeTool()
    ToolRegistry.register(tool)
    return tool


@pytest.fixture
def user_id():
    return uuid.uuid4()


@pytest.fixture
def workspace_id():
    return uuid.uuid4()


@pytest.fixture
def run_id():
    return uuid.uuid4()


@pytest.fixture
def mock_db():
    """Mock AsyncSession that tracks add() calls and supports flush/execute."""
    db = AsyncMock()
    db.added = []

    def track_add(obj):
        db.added.append(obj)

    db.add = MagicMock(side_effect=track_add)
    db.flush = AsyncMock()
    return db


def make_run(
    *,
    run_id=None,
    workflow_id=None,
    workspace_id=None,
    triggered_by=None,
    definition_snapshot_json,
    input_json=None,
    state_json=None,
    current_step_index=0,
    status=RunStatus.PENDING.value,
    overrides_json=None,
):
    """Helper to create a WorkflowRun-like object for executor tests."""
    run = MagicMock(spec=WorkflowRun)
    run.id = run_id or uuid.uuid4()
    run.workflow_id = workflow_id or uuid.uuid4()
    run.workspace_id = workspace_id or uuid.uuid4()
    run.triggered_by = triggered_by or uuid.uuid4()
    run.status = status
    run.current_step_index = current_step_index
    run.state_json = state_json or {}
    run.input_json = input_json or {}
    run.output_json = None
    run.error_message = None
    run.started_at = None
    run.completed_at = None
    run.progress_pct = 0
    run.definition_snapshot_json = definition_snapshot_json
    run.overrides_json = overrides_json
    return run
