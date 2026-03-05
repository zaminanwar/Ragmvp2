"""Evaluation runner — executes RAG pipeline against test datasets and computes metrics."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import structlog

from app.evaluation.metrics import run_all_metrics
from app.rag.engine import RAGEngine
from app.rag.llm.base import BaseLLM

logger = structlog.get_logger()


@dataclass
class EvalSample:
    """A single evaluation test case."""
    question: str
    ground_truth_answer: str
    ground_truth_contexts: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    """Result for a single evaluation sample."""
    question: str
    generated_answer: str
    ground_truth: str
    contexts_used: list[str]
    metrics: dict[str, float]


@dataclass
class EvalRunResult:
    """Aggregated result for a full evaluation run."""
    run_id: str
    workspace_id: str
    sample_count: int
    aggregate_metrics: dict[str, float]
    per_sample_results: list[EvalResult]
    config_snapshot: dict
    started_at: datetime
    completed_at: datetime


async def run_evaluation(
    engine: RAGEngine,
    eval_llm: BaseLLM,
    workspace_id: uuid.UUID,
    dataset: list[EvalSample],
    config_snapshot: dict | None = None,
) -> EvalRunResult:
    """Run the RAG pipeline on each sample and compute evaluation metrics.

    Args:
        engine: Configured RAG engine for the workspace
        eval_llm: LLM to use for evaluation metrics (can be different from generation LLM)
        workspace_id: Workspace to evaluate
        dataset: List of test samples with ground truth
        config_snapshot: Optional dict of RAG config at time of run
    """
    run_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    per_sample_results: list[EvalResult] = []
    all_metrics: dict[str, list[float]] = {}

    logger.info("eval_run_started", run_id=run_id, samples=len(dataset))

    for i, sample in enumerate(dataset):
        try:
            # Run RAG pipeline
            rag_response = await engine.query(
                query=sample.question,
                workspace_id=workspace_id,
            )

            # Extract contexts from citations
            contexts_used = [c.get("content", "") for c in rag_response.citations]

            # Compute metrics
            metrics = await run_all_metrics(
                question=sample.question,
                answer=rag_response.content,
                contexts=contexts_used,
                ground_truth=sample.ground_truth_answer,
                llm=eval_llm,
            )

            result = EvalResult(
                question=sample.question,
                generated_answer=rag_response.content,
                ground_truth=sample.ground_truth_answer,
                contexts_used=contexts_used,
                metrics=metrics,
            )
            per_sample_results.append(result)

            # Accumulate for aggregation
            for metric_name, score in metrics.items():
                if metric_name not in all_metrics:
                    all_metrics[metric_name] = []
                all_metrics[metric_name].append(score)

            logger.info(
                "eval_sample_complete",
                run_id=run_id,
                sample=i + 1,
                aggregate=round(metrics.get("aggregate", 0), 3),
            )

        except Exception as e:
            logger.error("eval_sample_failed", run_id=run_id, sample=i + 1, error=str(e))
            per_sample_results.append(EvalResult(
                question=sample.question,
                generated_answer="",
                ground_truth=sample.ground_truth_answer,
                contexts_used=[],
                metrics={"error": str(e)},
            ))

    # Compute aggregate metrics
    aggregate_metrics = {}
    for metric_name, scores in all_metrics.items():
        if scores:
            aggregate_metrics[metric_name] = sum(scores) / len(scores)

    completed_at = datetime.now(timezone.utc)

    logger.info(
        "eval_run_complete",
        run_id=run_id,
        samples=len(dataset),
        aggregate=aggregate_metrics,
        duration_s=(completed_at - started_at).total_seconds(),
    )

    return EvalRunResult(
        run_id=run_id,
        workspace_id=str(workspace_id),
        sample_count=len(dataset),
        aggregate_metrics=aggregate_metrics,
        per_sample_results=per_sample_results,
        config_snapshot=config_snapshot or {},
        started_at=started_at,
        completed_at=completed_at,
    )
