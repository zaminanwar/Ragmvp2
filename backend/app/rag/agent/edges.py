"""Conditional edge functions for the agentic RAG graph.

Each edge function takes the current state and returns a string
identifying the next node to execute.
"""

MAX_RETRIEVAL_ATTEMPTS = 3
MAX_GENERATION_ATTEMPTS = 2


def select_retrieval_strategy(state: dict) -> str:
    """After routing, decide which retrieval node to use."""
    if state.get("enable_hyde", False):
        return "hyde_retrieve"
    if state.get("enable_query_decomposition", False):
        return "decompose_query"
    return "retrieve"


def should_rerank(state: dict) -> str:
    """After retrieval, decide whether to apply reranking."""
    if state.get("enable_reranking", False):
        return "rerank"
    return "grade_documents"


def should_generate_or_rewrite(state: dict) -> str:
    """After grading, decide whether to generate or rewrite the query."""
    if state.get("documents_relevant", False):
        return "generate"
    if state.get("retrieval_attempts", 0) >= MAX_RETRIEVAL_ATTEMPTS:
        # Give up on retrieval, generate with what we have
        return "generate"
    return "rewrite_question"


def should_return_or_regenerate(state: dict) -> str:
    """After hallucination check, decide whether to return or regenerate."""
    if state.get("answer_grounded", False):
        return "end"
    # Count how many times we've generated
    gen_count = sum(1 for t in state.get("agent_trace", []) if t == "generate")
    if gen_count >= MAX_GENERATION_ATTEMPTS:
        return "end"
    return "regenerate"


def route_after_rewrite(state: dict) -> str:
    """After rewriting, decide which retrieval strategy to re-use."""
    # On rewrite, always use standard retrieve (not HyDE/decompose again)
    return "retrieve"
