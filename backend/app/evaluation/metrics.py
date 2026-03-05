"""Core RAGAS-style evaluation metrics implemented with LLM-as-judge.

No external dependency on ragas library — uses our own LLM providers
for full control and provider-agnostic operation.
"""

import structlog

from app.rag.agent.output_parser import parse_json_response
from app.rag.llm.base import BaseLLM

logger = structlog.get_logger()


async def faithfulness(
    answer: str,
    contexts: list[str],
    llm: BaseLLM,
) -> float:
    """Measure whether the answer is grounded in the provided contexts.

    Score 0.0-1.0: What fraction of claims in the answer are supported by the contexts?
    """
    if not answer or not contexts:
        return 0.0

    context_text = "\n\n".join(f"Context {i+1}: {c[:500]}" for i, c in enumerate(contexts))

    response = await llm.generate(
        prompt=f"""Evaluate the faithfulness of this answer to the provided contexts.

Contexts:
{context_text}

Answer: {answer}

For each factual claim in the answer, determine if it is supported by the contexts.
Return a JSON object: {{"supported_claims": <int>, "total_claims": <int>, "score": <float 0.0-1.0>}}""",
        temperature=0.0,
        max_tokens=200,
    )

    parsed = parse_json_response(response.content, default={"score": 0.5})
    return max(0.0, min(1.0, float(parsed.get("score", 0.5))))


async def answer_relevancy(
    answer: str,
    question: str,
    llm: BaseLLM,
) -> float:
    """Measure whether the answer actually addresses the question.

    Score 0.0-1.0: How relevant is the answer to the question asked?
    """
    if not answer or not question:
        return 0.0

    response = await llm.generate(
        prompt=f"""Rate how well this answer addresses the question.

Question: {question}
Answer: {answer}

Consider: Does the answer directly address what was asked? Is it complete? Is it focused?
Return a JSON object: {{"score": <float 0.0-1.0>, "reasoning": "<brief>"}}""",
        temperature=0.0,
        max_tokens=200,
    )

    parsed = parse_json_response(response.content, default={"score": 0.5})
    return max(0.0, min(1.0, float(parsed.get("score", 0.5))))


async def context_precision(
    contexts: list[str],
    ground_truth: str,
    llm: BaseLLM,
) -> float:
    """Measure whether relevant contexts are ranked higher.

    Score 0.0-1.0: Are the most relevant chunks at the top of the retrieved list?
    """
    if not contexts or not ground_truth:
        return 0.0

    context_list = "\n".join(
        f"[Rank {i+1}] {c[:300]}" for i, c in enumerate(contexts)
    )

    response = await llm.generate(
        prompt=f"""Given the ground truth answer, evaluate the precision of the retrieved contexts.

Ground truth: {ground_truth}

Retrieved contexts (in rank order):
{context_list}

For each context, determine if it is relevant to answering with the ground truth.
Return a JSON object: {{"relevant_at_ranks": [<list of 1-indexed ranks that are relevant>], "score": <float 0.0-1.0>}}

Score should reflect whether relevant contexts appear at higher ranks (precision@k style).""",
        temperature=0.0,
        max_tokens=300,
    )

    parsed = parse_json_response(response.content, default={"score": 0.5})
    return max(0.0, min(1.0, float(parsed.get("score", 0.5))))


async def context_recall(
    contexts: list[str],
    ground_truth: str,
    llm: BaseLLM,
) -> float:
    """Measure whether all information needed to answer was retrieved.

    Score 0.0-1.0: What fraction of the ground truth can be attributed to retrieved contexts?
    """
    if not contexts or not ground_truth:
        return 0.0

    context_text = "\n\n".join(f"Context {i+1}: {c[:400]}" for i, c in enumerate(contexts))

    response = await llm.generate(
        prompt=f"""Evaluate context recall: what fraction of the ground truth answer is covered by the retrieved contexts?

Ground truth answer: {ground_truth}

Retrieved contexts:
{context_text}

Break the ground truth into key claims/facts. For each, determine if it is supported by any retrieved context.
Return a JSON object: {{"covered_claims": <int>, "total_claims": <int>, "score": <float 0.0-1.0>}}""",
        temperature=0.0,
        max_tokens=300,
    )

    parsed = parse_json_response(response.content, default={"score": 0.5})
    return max(0.0, min(1.0, float(parsed.get("score", 0.5))))


async def answer_correctness(
    answer: str,
    ground_truth: str,
    llm: BaseLLM,
) -> float:
    """Measure factual correctness of the answer against ground truth.

    Score 0.0-1.0: How factually correct is the answer compared to the ground truth?
    """
    if not answer or not ground_truth:
        return 0.0

    response = await llm.generate(
        prompt=f"""Compare the generated answer against the ground truth for factual correctness.

Ground truth: {ground_truth}
Generated answer: {answer}

Evaluate:
1. Are the facts in the generated answer correct?
2. Are important facts from the ground truth missing?
3. Are there any contradictions?

Return a JSON object: {{"score": <float 0.0-1.0>, "correct_facts": <int>, "incorrect_facts": <int>, "missing_facts": <int>}}""",
        temperature=0.0,
        max_tokens=300,
    )

    parsed = parse_json_response(response.content, default={"score": 0.5})
    return max(0.0, min(1.0, float(parsed.get("score", 0.5))))


async def run_all_metrics(
    question: str,
    answer: str,
    contexts: list[str],
    ground_truth: str,
    llm: BaseLLM,
) -> dict[str, float]:
    """Run all evaluation metrics and return a score dict."""
    import asyncio

    results = await asyncio.gather(
        faithfulness(answer, contexts, llm),
        answer_relevancy(answer, question, llm),
        context_precision(contexts, ground_truth, llm),
        context_recall(contexts, ground_truth, llm),
        answer_correctness(answer, ground_truth, llm),
        return_exceptions=True,
    )

    metric_names = [
        "faithfulness", "answer_relevancy", "context_precision",
        "context_recall", "answer_correctness",
    ]

    scores = {}
    for name, result in zip(metric_names, results):
        if isinstance(result, Exception):
            logger.warning(f"metric_{name}_failed", error=str(result))
            scores[name] = 0.0
        else:
            scores[name] = result

    # Compute aggregate
    valid_scores = [s for s in scores.values() if s > 0]
    scores["aggregate"] = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0

    return scores
