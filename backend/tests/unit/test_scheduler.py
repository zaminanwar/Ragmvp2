"""Unit tests for WorkflowScheduler."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.workflow import RunStatus, WorkflowRun
from app.workflows.engine.scheduler import WorkflowScheduler


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.rpush = AsyncMock()
    redis.blpop = AsyncMock(return_value=None)
    return redis


@pytest.fixture
def mock_session_factory():
    factory = MagicMock()
    return factory


@pytest.fixture
def scheduler(mock_redis, mock_session_factory):
    return WorkflowScheduler(mock_redis, mock_session_factory)


# ── Queue operations ────────────────────────────────────────────────────────


class TestQueueOperations:
    @pytest.mark.asyncio
    async def test_enqueue(self, scheduler, mock_redis):
        run_id = uuid.uuid4()
        await scheduler.enqueue(run_id)
        mock_redis.rpush.assert_called_once_with(
            WorkflowScheduler.QUEUE_KEY, str(run_id)
        )

    @pytest.mark.asyncio
    async def test_resume(self, scheduler, mock_redis):
        run_id = uuid.uuid4()
        await scheduler.resume(run_id)
        mock_redis.rpush.assert_called_once_with(
            WorkflowScheduler.QUEUE_KEY, str(run_id)
        )


# ── Worker lifecycle ────────────────────────────────────────────────────────


class TestWorkerLifecycle:
    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, scheduler):
        assert scheduler._running is True
        await scheduler.stop()
        assert scheduler._running is False

    @pytest.mark.asyncio
    async def test_worker_respects_stop(self, scheduler, mock_redis):
        """Worker loop should exit when _running becomes False."""
        call_count = 0

        async def fake_blpop(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                scheduler._running = False
            return None

        mock_redis.blpop = fake_blpop

        await scheduler.start_worker()
        assert call_count >= 2
        assert scheduler._running is False


# ── Job processing ──────────────────────────────────────────────────────────


class TestJobProcessing:
    @pytest.mark.asyncio
    async def test_process_valid_run(self, scheduler, mock_session_factory):
        """_process should load the run, create executor, and call execute."""
        run_id = uuid.uuid4()

        mock_run = MagicMock(spec=WorkflowRun)
        mock_run.id = run_id
        mock_run.status = RunStatus.PENDING.value
        mock_run.definition_snapshot_json = {"steps": []}
        mock_run.state_json = {}
        mock_run.input_json = {}
        mock_run.overrides_json = None
        mock_run.workspace_id = uuid.uuid4()
        mock_run.triggered_by = uuid.uuid4()
        mock_run.started_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_run

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        # Make session_factory return context manager yielding mock_db
        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.workflows.engine.scheduler.WorkflowExecutor"
        ) as MockExecutor:
            mock_executor = AsyncMock()
            MockExecutor.return_value = mock_executor

            await scheduler._process(run_id)

            MockExecutor.assert_called_once_with(mock_db, mock_run)
            mock_executor.execute.assert_called_once()
            mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_skips_cancelled_run(self, scheduler, mock_session_factory):
        """Runs with invalid status should be skipped."""
        run_id = uuid.uuid4()

        mock_run = MagicMock(spec=WorkflowRun)
        mock_run.id = run_id
        mock_run.status = RunStatus.CANCELLED.value

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_run

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.workflows.engine.scheduler.WorkflowExecutor"
        ) as MockExecutor:
            await scheduler._process(run_id)
            MockExecutor.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_not_found(self, scheduler, mock_session_factory):
        """Missing run should not crash."""
        run_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        # Should not raise
        await scheduler._process(run_id)


# ── Concurrency limit ───────────────────────────────────────────────────────


class TestConcurrency:
    def test_max_concurrent_default(self, scheduler):
        assert scheduler._max_concurrent == 10

    @pytest.mark.asyncio
    async def test_queue_key(self, scheduler):
        assert scheduler.QUEUE_KEY == "workflow:job_queue"
