"""Evaluation API routes — run and compare RAG quality evaluations."""

import json
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.evaluation.datasets import load_dataset, generate_synthetic_dataset
from app.evaluation.runner import EvalSample, run_evaluation
from app.models.user import User
from app.models.workspace import Workspace
from app.rag.embeddings.providers import get_embedding_provider
from app.rag.engine import RAGEngine
from app.rag.llm.factory import get_llm_provider
from app.rag.retrieval.hybrid_search import HybridRetriever
from app.rag.retrieval.reranker import LLMReranker
from app.services.workspace_service import WorkspaceService

logger = structlog.get_logger()

router = APIRouter()


class EvalRunRequest(BaseModel):
    workspace_id: str
    dataset: list[dict]  # List of {question, ground_truth_answer, ground_truth_contexts?}


class EvalRunResponse(BaseModel):
    run_id: str
    sample_count: int
    aggregate_metrics: dict
    per_sample_results: list[dict]


@router.post("/run", response_model=EvalRunResponse)
async def run_eval(
    body: EvalRunRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run an evaluation on a workspace with the provided dataset."""
    import uuid

    workspace_service = WorkspaceService(db)
    workspace = await workspace_service.get_by_id(uuid.UUID(body.workspace_id))
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Build evaluation dataset
    samples = [
        EvalSample(
            question=d["question"],
            ground_truth_answer=d.get("ground_truth_answer", d.get("answer", "")),
            ground_truth_contexts=d.get("ground_truth_contexts", []),
        )
        for d in body.dataset
    ]

    # Build RAG engine
    llm = get_llm_provider(provider=workspace.llm_provider, model=workspace.llm_model)
    embedding = get_embedding_provider(provider=workspace.embedding_provider)
    retriever = HybridRetriever(db, embedding)
    reranker = LLMReranker(llm) if workspace.enable_reranking else None

    engine = RAGEngine(
        llm=llm,
        retriever=retriever,
        reranker=reranker,
        embedding_provider=embedding,
        enable_reranking=workspace.enable_reranking,
        enable_hyde=getattr(workspace, "enable_hyde", False),
        enable_query_decomposition=getattr(workspace, "enable_query_decomposition", False),
    )

    # Use same LLM for evaluation metrics
    eval_llm = llm

    # Run evaluation
    config_snapshot = {
        "llm_provider": workspace.llm_provider,
        "llm_model": workspace.llm_model,
        "enable_reranking": workspace.enable_reranking,
        "enable_hyde": getattr(workspace, "enable_hyde", False),
        "enable_query_decomposition": getattr(workspace, "enable_query_decomposition", False),
        "similarity_top_k": workspace.similarity_top_k,
    }

    result = await run_evaluation(
        engine=engine,
        eval_llm=eval_llm,
        workspace_id=workspace.id,
        dataset=samples,
        config_snapshot=config_snapshot,
    )

    return EvalRunResponse(
        run_id=result.run_id,
        sample_count=result.sample_count,
        aggregate_metrics=result.aggregate_metrics,
        per_sample_results=[
            {
                "question": r.question,
                "generated_answer": r.generated_answer[:500],
                "ground_truth": r.ground_truth[:500],
                "metrics": r.metrics,
            }
            for r in result.per_sample_results
        ],
    )


class SyntheticDatasetRequest(BaseModel):
    workspace_id: str
    num_samples: int = 20


@router.post("/generate-dataset")
async def generate_eval_dataset(
    body: SyntheticDatasetRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a synthetic evaluation dataset from workspace documents."""
    import uuid
    from sqlalchemy import select
    from app.models.document import DocumentChunk

    workspace_id = uuid.UUID(body.workspace_id)

    # Fetch chunks from workspace
    result = await db.execute(
        select(DocumentChunk.content)
        .where(DocumentChunk.workspace_id == workspace_id)
        .limit(100)
    )
    chunks = [row[0] for row in result.all()]

    if not chunks:
        raise HTTPException(status_code=400, detail="No documents in workspace")

    llm = get_llm_provider()
    samples = await generate_synthetic_dataset(chunks, llm, num_samples=body.num_samples)

    return {
        "samples": [
            {
                "question": s.question,
                "ground_truth_answer": s.ground_truth_answer,
                "ground_truth_contexts": s.ground_truth_contexts,
            }
            for s in samples
        ],
        "count": len(samples),
    }
