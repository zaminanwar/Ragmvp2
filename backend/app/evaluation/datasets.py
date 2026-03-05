"""Evaluation dataset utilities — load, save, and generate test datasets."""

import json
from dataclasses import asdict
from pathlib import Path

import structlog

from app.evaluation.runner import EvalSample
from app.rag.llm.base import BaseLLM

logger = structlog.get_logger()


def load_dataset(path: str) -> list[EvalSample]:
    """Load an evaluation dataset from a JSON/JSONL file.

    Expected format (JSON array):
    [
        {
            "question": "What is X?",
            "ground_truth_answer": "X is ...",
            "ground_truth_contexts": ["context 1", "context 2"]  // optional
        }
    ]

    Or JSONL (one JSON object per line).
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Dataset file not found: {path}")

    text = file_path.read_text(encoding="utf-8")

    # Try JSONL first
    if file_path.suffix == ".jsonl":
        samples = []
        for line in text.strip().split("\n"):
            if line.strip():
                obj = json.loads(line)
                samples.append(_parse_sample(obj))
        return samples

    # JSON array
    data = json.loads(text)
    if isinstance(data, list):
        return [_parse_sample(obj) for obj in data]

    raise ValueError(f"Expected JSON array or JSONL, got {type(data)}")


def _parse_sample(obj: dict) -> EvalSample:
    return EvalSample(
        question=obj["question"],
        ground_truth_answer=obj.get("ground_truth_answer", obj.get("answer", "")),
        ground_truth_contexts=obj.get("ground_truth_contexts", obj.get("contexts", [])),
    )


def save_dataset(samples: list[EvalSample], path: str):
    """Save an evaluation dataset to JSON."""
    data = [asdict(s) for s in samples]
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


async def generate_synthetic_dataset(
    chunks: list[str],
    llm: BaseLLM,
    num_samples: int = 20,
) -> list[EvalSample]:
    """Generate synthetic QA pairs from document chunks using LLM.

    Takes a sample of chunks and generates question-answer pairs
    that can be used for evaluation.
    """
    import random
    from app.rag.agent.output_parser import parse_json_response

    # Sample chunks (avoid using all for cost reasons)
    selected = random.sample(chunks, min(num_samples, len(chunks)))
    samples: list[EvalSample] = []

    for chunk_text in selected:
        try:
            response = await llm.generate(
                prompt=f"""Generate a question-answer pair from this document chunk.
The question should be something a user would naturally ask.
The answer should be factual and based entirely on the chunk content.

Document chunk:
{chunk_text[:1500]}

Return a JSON object: {{"question": "<question>", "answer": "<detailed answer>"}}""",
                temperature=0.5,
                max_tokens=400,
            )

            parsed = parse_json_response(response.content, default={})
            if parsed.get("question") and parsed.get("answer"):
                samples.append(EvalSample(
                    question=parsed["question"],
                    ground_truth_answer=parsed["answer"],
                    ground_truth_contexts=[chunk_text],
                ))
        except Exception as e:
            logger.warning("synthetic_qa_generation_failed", error=str(e))
            continue

    logger.info("synthetic_dataset_generated", samples=len(samples))
    return samples
