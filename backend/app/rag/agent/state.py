"""Agent state definition for the agentic RAG pipeline.

Uses TypedDict with Annotated accumulator for trace tracking across nodes.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class RAGAgentState(TypedDict):
    # Input
    question: str
    workspace_id: str
    chat_history: list[dict]
    system_prompt: str
    top_k: int

    # Workspace feature flags
    enable_reranking: bool
    enable_hyde: bool
    enable_query_decomposition: bool

    # Pipeline state
    query_type: str  # vector, fulltext, hybrid
    documents: list[dict]  # retrieved chunks as dicts
    retrieval_attempts: int
    generation: str
    documents_relevant: bool
    answer_grounded: bool
    rewritten_question: str
    sources: list[dict]  # citation metadata
    search_mode_used: str

    # Trace accumulator — appends across nodes automatically
    agent_trace: Annotated[list[str], operator.add]

    # Token tracking
    total_input_tokens: int
    total_output_tokens: int
    model_used: str
