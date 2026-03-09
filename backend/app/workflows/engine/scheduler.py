"""Workflow scheduler — Redis blpop job queue + background worker loop."""

from __future__ import annotations

import asyncio
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.workflow import RunStatus, WorkflowRun
from app.workflows.engine.executor import WorkflowExecutor

logger = structlog.get_logger(__name__)


class WorkflowScheduler:
    """Lightweight job queue backed by Redis BLPOP.

    Usage (in app lifespan):
        scheduler = WorkflowScheduler(redis_client, session_factory)
        asyncio.create_task(scheduler.start_worker())
    """

    QUEUE_KEY = "workflow:job_queue"

    def __init__(self, redis_client, session_factory: async_sessionmaker):
        self._redis = redis_client
        self._session_factory = session_factory
        self._running = True
        self._active_tasks: set[asyncio.Task] = set()
        self._max_concurrent = 10

    # ── Queue operations ─────────────────────────────────────────────────

    async def enqueue(self, run_id: uuid.UUID) -> None:
        """Push a new run onto the queue."""
        await self._redis.rpush(self.QUEUE_KEY, str(run_id))
        logger.info("workflow_enqueued", run_id=str(run_id))

    async def resume(self, run_id: uuid.UUID) -> None:
        """Re-enqueue a paused/waiting run (e.g. after approval)."""
        await self._redis.rpush(self.QUEUE_KEY, str(run_id))
        logger.info("workflow_resumed", run_id=str(run_id))

    # ── Worker loop ──────────────────────────────────────────────────────

    async def start_worker(self) -> None:
        """Background loop — pull jobs from Redis and process them."""
        logger.info("workflow_worker_started")
        while self._running:
            # Limit concurrency
            if len(self._active_tasks) >= self._max_concurrent:
                await asyncio.sleep(0.5)
                continue

            try:
                job = await self._redis.blpop(self.QUEUE_KEY, timeout=5)
            except Exception as e:
                logger.error("redis_blpop_error", error=str(e))
                await asyncio.sleep(2)
                continue

            if job:
                run_id = uuid.UUID(job[1].decode())
                task = asyncio.create_task(self._process(run_id))
                self._active_tasks.add(task)
                task.add_done_callback(self._active_tasks.discard)

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._active_tasks:
            logger.info("workflow_worker_draining", count=len(self._active_tasks))
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
        logger.info("workflow_worker_stopped")

    # ── Job processing ───────────────────────────────────────────────────

    async def _process(self, run_id: uuid.UUID) -> None:
        """Load a run from DB and execute it."""
        logger.info("workflow_processing", run_id=str(run_id))

        async with self._session_factory() as db:
            try:
                # Retry lookup in case the creating transaction hasn't committed yet
                run = None
                for attempt in range(3):
                    result = await db.execute(
                        select(WorkflowRun).where(WorkflowRun.id == run_id)
                    )
                    run = result.scalar_one_or_none()
                    if run:
                        break
                    logger.warning("workflow_run_not_yet_visible", run_id=str(run_id), attempt=attempt)
                    await asyncio.sleep(0.5)

                if not run:
                    logger.error("workflow_run_not_found", run_id=str(run_id))
                    return

                # Only process runs that are pending, running, or waiting_approval
                # (waiting_approval means an approval was just granted)
                if run.status not in (
                    RunStatus.PENDING.value,
                    RunStatus.RUNNING.value,
                    RunStatus.WAITING_APPROVAL.value,
                ):
                    logger.warning(
                        "workflow_skip_invalid_status",
                        run_id=str(run_id),
                        status=run.status,
                    )
                    return

                executor = WorkflowExecutor(db, run)
                await executor.execute()
                await db.commit()

                logger.info(
                    "workflow_processed",
                    run_id=str(run_id),
                    status=run.status,
                )

            except Exception as exc:
                await db.rollback()
                logger.exception("workflow_execution_error", run_id=str(run_id), error=str(exc))

                # Try to mark the run as failed
                try:
                    result = await db.execute(
                        select(WorkflowRun).where(WorkflowRun.id == run_id)
                    )
                    run = result.scalar_one_or_none()
                    if run and run.status != RunStatus.FAILED.value:
                        run.status = RunStatus.FAILED.value
                        run.error_message = f"Unhandled error: {exc}"
                        await db.commit()
                except Exception:
                    logger.exception("workflow_fail_mark_error", run_id=str(run_id))
