"""
End-to-end integration test for the workflow engine.

Runs the full lifecycle against a real (in-memory SQLite) database
with no Docker, no Redis, no external services required.

Flow tested:
  1. Create workflow definition (2-step echo workflow)
  2. Publish it
  3. Start a run
  4. Execute the run (directly, bypassing Redis queue)
  5. Verify run completed, step results recorded, audit trail exists
  6. Test checkpoint/approval flow
  7. Test cancel + rerun
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.pool import StaticPool

# ── SQLite compatibility shims ───────────────────────────────────────────────
# Teach SQLAlchemy how to render PostgreSQL types on SQLite.

try:
    from pgvector.sqlalchemy import Vector

    @compiles(Vector, "sqlite")
    def _compile_vector_sqlite(type_, compiler, **kw):
        return "TEXT"
except ImportError:
    pass


@compiles(PG_UUID, "sqlite")
def _compile_uuid_sqlite(type_, compiler, **kw):
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


# ── Imports (after shims are registered) ─────────────────────────────────────

from app.models.base import Base
from app.models.user import User, UserRole
from app.models.workspace import Workspace
from app.models.workflow import (
    RunStatus,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStepResult,
    WorkflowApproval,
    WorkflowAuditEntry,
)
from app.workflows.tools.base import BaseTool, ToolInput, ToolOutput
from app.workflows.tools.registry import ToolRegistry
from app.workflows.engine.executor import WorkflowExecutor
from app.api.routes import workflows as workflows_router
from app.core.security import create_access_token

# ── Test tools ───────────────────────────────────────────────────────────────


class EchoTool(BaseTool):
    name = "test.echo"
    description = "Returns input as output."
    input_schema = {"type": "object"}
    output_schema = {"type": "object"}

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        return ToolOutput(success=True, data=tool_input.params)


class UpperTool(BaseTool):
    name = "test.upper"
    description = "Uppercases the 'text' field."
    input_schema = {"type": "object", "properties": {"text": {"type": "string"}}}
    output_schema = {"type": "object", "properties": {"text": {"type": "string"}}}

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        text = tool_input.params.get("text", "")
        return ToolOutput(success=True, data={"text": text.upper()})


# ── Database setup ───────────────────────────────────────────────────────────

TEST_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestSessionFactory = async_sessionmaker(
    TEST_ENGINE, class_=AsyncSession, expire_on_commit=False
)


@asynccontextmanager
async def _get_test_db():
    async with TestSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_test_db():
    async with _get_test_db() as session:
        yield session


# ── Test app factory ─────────────────────────────────────────────────────────

TEST_USER_ID = uuid.uuid4()
TEST_WORKSPACE_ID = uuid.uuid4()


def _create_test_app() -> FastAPI:
    """Build a minimal FastAPI app with only the workflow router."""
    from app.api.deps import get_current_user, require_manager
    from app.models.base import get_db

    app = FastAPI()
    app.include_router(
        workflows_router.router, prefix="/api/workflows", tags=["Workflows"]
    )

    # Create a fake user object
    fake_user = type("FakeUser", (), {
        "id": TEST_USER_ID,
        "email": "test@test.com",
        "username": "testuser",
        "role": UserRole.MANAGER.value,
        "is_active": True,
    })()

    async def _fake_current_user():
        return fake_user

    async def _fake_manager_user():
        return fake_user

    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_current_user] = _fake_current_user
    app.dependency_overrides[require_manager] = _fake_manager_user

    return app


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
async def setup_db():
    """Create all tables before each test, drop after."""
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture(autouse=True)
def register_tools():
    ToolRegistry.clear()
    ToolRegistry.register(EchoTool())
    ToolRegistry.register(UpperTool())
    yield
    ToolRegistry.clear()


@pytest.fixture
async def seed_data():
    """Insert a test user and workspace so FK constraints are satisfied."""
    async with _get_test_db() as db:
        user = User(
            id=TEST_USER_ID,
            email="test@test.com",
            username="testuser",
            hashed_password="fakehash",
            role=UserRole.MANAGER.value,
        )
        workspace = Workspace(
            id=TEST_WORKSPACE_ID,
            name="Test Workspace",
            slug="test-workspace",
        )
        db.add(user)
        db.add(workspace)
        await db.flush()


@pytest.fixture
def client():
    app = _create_test_app()
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": "Bearer fake-token"},
    )


TWO_STEP_DEFINITION = {
    "version": "1.0",
    "inputs": {
        "greeting": {
            "type": "string",
            "description": "A greeting message",
            "required": True,
        }
    },
    "outputs": {
        "result": {"type": "string", "from": "$steps.upper_step.output.text"},
    },
    "steps": [
        {
            "id": "echo_step",
            "name": "Echo Input",
            "tool": "test.echo",
            "inputs": {"text": "$inputs.greeting"},
            "outputs": ["text"],
        },
        {
            "id": "upper_step",
            "name": "Uppercase It",
            "tool": "test.upper",
            "inputs": {"text": "$steps.echo_step.output.text"},
            "outputs": ["text"],
        },
    ],
}

CHECKPOINT_DEFINITION = {
    "version": "1.0",
    "inputs": {"msg": {"type": "string", "required": True}},
    "steps": [
        {
            "id": "gated_step",
            "name": "Gated",
            "tool": "test.echo",
            "inputs": {"text": "$inputs.msg"},
            "outputs": ["text"],
            "checkpoint": {
                "type": "approval",
                "message": "Please review before continuing",
                "required_role": "manager",
            },
        },
        {
            "id": "after_gate",
            "name": "After Gate",
            "tool": "test.upper",
            "inputs": {"text": "$steps.gated_step.output.text"},
            "outputs": ["text"],
        },
    ],
}


# ── Helper ───────────────────────────────────────────────────────────────────


async def _execute_run(run_id: uuid.UUID):
    """Load a run from DB and execute it directly (no Redis needed)."""
    async with _get_test_db() as db:
        from sqlalchemy import select

        result = await db.execute(
            select(WorkflowRun).where(WorkflowRun.id == run_id)
        )
        run = result.scalar_one()
        executor = WorkflowExecutor(db, run)
        await executor.execute()


# ── Tests ────────────────────────────────────────────────────────────────────


class TestWorkflowE2E:
    """Full lifecycle: create → publish → run → verify."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, client: AsyncClient, seed_data):
        # ── 1. Create definition ─────────────────────────────────────
        resp = await client.post(
            "/api/workflows/definitions",
            json={
                "workspace_id": str(TEST_WORKSPACE_ID),
                "name": "E2E Test Workflow",
                "description": "Two-step echo + uppercase",
                "definition_json": TWO_STEP_DEFINITION,
            },
        )
        assert resp.status_code == 200, resp.text
        defn = resp.json()
        assert defn["name"] == "E2E Test Workflow"
        assert defn["status"] == "draft"
        assert defn["slug"] == "e2e-test-workflow"
        workflow_id = defn["id"]

        # ── 2. List definitions ──────────────────────────────────────
        resp = await client.get(
            f"/api/workflows/definitions?workspace_id={TEST_WORKSPACE_ID}"
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # ── 3. Publish ───────────────────────────────────────────────
        resp = await client.post(
            f"/api/workflows/definitions/{workflow_id}/publish"
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "published"

        # ── 4. Validate ──────────────────────────────────────────────
        resp = await client.post(
            "/api/workflows/definitions/validate",
            json={"definition_json": TWO_STEP_DEFINITION},
        )
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

        # ── 5. List available tools ──────────────────────────────────
        resp = await client.get("/api/workflows/tools")
        assert resp.status_code == 200
        tool_names = {t["name"] for t in resp.json()}
        assert "test.echo" in tool_names
        assert "test.upper" in tool_names

        # ── 6. Start a run ───────────────────────────────────────────
        # (worker disabled — we'll execute manually)
        from app.config import get_settings
        settings = get_settings()
        original_worker = settings.enable_workflow_worker
        settings.enable_workflow_worker = False

        try:
            resp = await client.post(
                "/api/workflows/runs",
                json={
                    "workflow_id": workflow_id,
                    "workspace_id": str(TEST_WORKSPACE_ID),
                    "input_json": {"greeting": "hello world"},
                },
            )
            assert resp.status_code == 200, resp.text
            run = resp.json()
            run_id = run["id"]
            assert run["status"] == "pending"
        finally:
            settings.enable_workflow_worker = original_worker

        # ── 7. Execute the workflow directly ─────────────────────────
        await _execute_run(uuid.UUID(run_id))

        # ── 8. Check run status → completed ──────────────────────────
        resp = await client.get(f"/api/workflows/runs/{run_id}")
        assert resp.status_code == 200
        run = resp.json()
        assert run["status"] == "completed", f"Expected completed, got {run['status']}: {run.get('error_message')}"
        assert run["progress_pct"] == 100
        assert run["output_json"]["result"] == "HELLO WORLD"

        # ── 9. Check progress endpoint ───────────────────────────────
        resp = await client.get(f"/api/workflows/runs/{run_id}/progress")
        assert resp.status_code == 200
        progress = resp.json()
        assert progress["status"] == "completed"
        assert progress["total_steps"] == 2
        assert len(progress["steps"]) == 2

        # ── 10. Check step results ───────────────────────────────────
        resp = await client.get(f"/api/workflows/runs/{run_id}/steps")
        assert resp.status_code == 200
        steps = resp.json()
        assert len(steps) == 2
        assert steps[0]["step_id"] == "echo_step"
        assert steps[0]["status"] == "completed"
        assert steps[0]["output_json"]["text"] == "hello world"
        assert steps[1]["step_id"] == "upper_step"
        assert steps[1]["status"] == "completed"
        assert steps[1]["output_json"]["text"] == "HELLO WORLD"
        assert steps[0]["duration_ms"] is not None
        assert steps[1]["duration_ms"] is not None

        # ── 11. Check audit trail ────────────────────────────────────
        resp = await client.get(f"/api/workflows/runs/{run_id}/audit")
        assert resp.status_code == 200
        audit = resp.json()
        event_types = [e["event_type"] for e in audit]
        assert "run_started" in event_types
        assert "step_started" in event_types
        assert "step_completed" in event_types
        assert "run_completed" in event_types

        # ── 12. List runs ────────────────────────────────────────────
        resp = await client.get(
            f"/api/workflows/runs?workspace_id={TEST_WORKSPACE_ID}"
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["status"] == "completed"

        print("\n✓ Full lifecycle test passed: create → publish → run → complete")

    @pytest.mark.asyncio
    async def test_checkpoint_approval_flow(self, client: AsyncClient, seed_data):
        """Test: run pauses at checkpoint, approval resumes it."""
        from app.config import get_settings
        settings = get_settings()
        original_worker = settings.enable_workflow_worker
        settings.enable_workflow_worker = False

        try:
            # Create + publish a workflow with a checkpoint
            resp = await client.post(
                "/api/workflows/definitions",
                json={
                    "workspace_id": str(TEST_WORKSPACE_ID),
                    "name": "Checkpoint Workflow",
                    "definition_json": CHECKPOINT_DEFINITION,
                },
            )
            assert resp.status_code == 200
            workflow_id = resp.json()["id"]

            resp = await client.post(
                f"/api/workflows/definitions/{workflow_id}/publish"
            )
            assert resp.status_code == 200

            # Start run
            resp = await client.post(
                "/api/workflows/runs",
                json={
                    "workflow_id": workflow_id,
                    "workspace_id": str(TEST_WORKSPACE_ID),
                    "input_json": {"msg": "needs review"},
                },
            )
            assert resp.status_code == 200
            run_id = resp.json()["id"]

            # Execute — should pause at checkpoint
            await _execute_run(uuid.UUID(run_id))

            resp = await client.get(f"/api/workflows/runs/{run_id}")
            assert resp.json()["status"] == "waiting_approval"

            # Check pending approvals
            resp = await client.get(
                f"/api/workflows/approvals/pending?workspace_id={TEST_WORKSPACE_ID}"
            )
            assert resp.status_code == 200
            approvals = resp.json()
            assert len(approvals) == 1
            approval_id = approvals[0]["id"]
            assert approvals[0]["step_id"] == "gated_step"

            # Approve it
            resp = await client.post(
                f"/api/workflows/approvals/{approval_id}/decide",
                json={"approved": True, "comment": "Looks good!"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "approved"

            # Run should now be marked as running again
            resp = await client.get(f"/api/workflows/runs/{run_id}")
            assert resp.json()["status"] == "running"

            # Execute again (resume) — should complete
            await _execute_run(uuid.UUID(run_id))

            resp = await client.get(f"/api/workflows/runs/{run_id}")
            run = resp.json()
            assert run["status"] == "completed"

            # Verify step after gate executed
            resp = await client.get(f"/api/workflows/runs/{run_id}/steps")
            steps = resp.json()
            step_ids = [s["step_id"] for s in steps]
            assert "gated_step" in step_ids
            assert "after_gate" in step_ids

            print("\n✓ Checkpoint approval flow passed: pause → approve → resume → complete")
        finally:
            settings.enable_workflow_worker = original_worker

    @pytest.mark.asyncio
    async def test_cancel_and_rerun(self, client: AsyncClient, seed_data):
        """Test: cancel a run, then rerun from a specific step."""

        # Create + publish
        resp = await client.post(
            "/api/workflows/definitions",
            json={
                "workspace_id": str(TEST_WORKSPACE_ID),
                "name": "Rerun Workflow",
                "definition_json": TWO_STEP_DEFINITION,
            },
        )
        workflow_id = resp.json()["id"]
        await client.post(f"/api/workflows/definitions/{workflow_id}/publish")

        # Start + execute
        from app.config import get_settings
        settings = get_settings()
        original_worker = settings.enable_workflow_worker
        settings.enable_workflow_worker = False

        try:
            resp = await client.post(
                "/api/workflows/runs",
                json={
                    "workflow_id": workflow_id,
                    "workspace_id": str(TEST_WORKSPACE_ID),
                    "input_json": {"greeting": "test rerun"},
                },
            )
            run_id = resp.json()["id"]
        finally:
            settings.enable_workflow_worker = original_worker

        await _execute_run(uuid.UUID(run_id))

        # Verify completed
        resp = await client.get(f"/api/workflows/runs/{run_id}")
        assert resp.json()["status"] == "completed"

        # Cancel it (even though completed — tests the endpoint)
        resp = await client.post(f"/api/workflows/runs/{run_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

        # Rerun from step 2 with overrides
        settings.enable_workflow_worker = False
        try:
            resp = await client.post(
                f"/api/workflows/runs/{run_id}/rerun-from/upper_step",
                json={
                    "step_id": "upper_step",
                    "overrides": {"upper_step": {"inputs": {"text": "override me"}}},
                },
            )
            assert resp.status_code == 200
            new_run = resp.json()
            new_run_id = new_run["id"]
            assert new_run["parent_run_id"] == run_id
        finally:
            settings.enable_workflow_worker = original_worker

        # Execute the rerun
        await _execute_run(uuid.UUID(new_run_id))

        resp = await client.get(f"/api/workflows/runs/{new_run_id}")
        rerun = resp.json()
        assert rerun["status"] == "completed"
        # The override should have been applied
        assert rerun["output_json"]["result"] == "OVERRIDE ME"

        print("\n✓ Cancel + rerun flow passed: complete → cancel → rerun with override → complete")

    @pytest.mark.asyncio
    async def test_validation_catches_bad_definition(self, client: AsyncClient, seed_data):
        """Validate endpoint catches missing steps, unknown tools, bad refs."""

        # Missing steps
        resp = await client.post(
            "/api/workflows/definitions/validate",
            json={"definition_json": {}},
        )
        assert resp.json()["valid"] is False
        assert "Missing 'steps'" in resp.json()["errors"][0]

        # Unknown tool
        resp = await client.post(
            "/api/workflows/definitions/validate",
            json={
                "definition_json": {
                    "steps": [
                        {"id": "s1", "tool": "nonexistent.tool", "inputs": {}}
                    ]
                }
            },
        )
        assert resp.json()["valid"] is False
        assert "not registered" in resp.json()["errors"][0]

        # Forward reference (step references a later step)
        resp = await client.post(
            "/api/workflows/definitions/validate",
            json={
                "definition_json": {
                    "steps": [
                        {
                            "id": "s1",
                            "tool": "test.echo",
                            "inputs": {"x": "$steps.s2.output.y"},
                        },
                        {"id": "s2", "tool": "test.echo", "inputs": {}},
                    ]
                }
            },
        )
        assert resp.json()["valid"] is False
        assert "hasn't executed yet" in resp.json()["errors"][0]

        print("\n✓ Validation tests passed: catches bad definitions correctly")
