"""Pipeline middleware framework (inspired by Open WebUI's Pipelines Plugin Framework).

Allows custom processing to be injected at various stages of the RAG pipeline:
- Pre-retrieval: Query transformation, intent classification
- Post-retrieval: Filtering, augmentation
- Pre-generation: Context assembly, prompt engineering
- Post-generation: Output filtering, safety checks
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


class PipelineStage(str, Enum):
    PRE_RETRIEVAL = "pre_retrieval"
    POST_RETRIEVAL = "post_retrieval"
    PRE_GENERATION = "pre_generation"
    POST_GENERATION = "post_generation"


@dataclass
class PipelineContext:
    """Data flowing through the pipeline."""
    query: str
    workspace_id: Any = None
    user_id: Any = None
    retrieval_results: list = None
    generated_text: str = ""
    metadata: dict = None

    def __post_init__(self):
        self.retrieval_results = self.retrieval_results or []
        self.metadata = self.metadata or {}


class PipelineFilter(ABC):
    """Base class for pipeline filters/middleware."""

    stage: PipelineStage = PipelineStage.PRE_RETRIEVAL
    priority: int = 100  # Lower = runs first

    @abstractmethod
    async def process(self, ctx: PipelineContext) -> PipelineContext:
        """Process and return the modified context."""
        ...


class Pipeline:
    """Composable pipeline that runs filters in order."""

    def __init__(self):
        self._filters: list[PipelineFilter] = []

    def add_filter(self, f: PipelineFilter) -> "Pipeline":
        self._filters.append(f)
        self._filters.sort(key=lambda x: (x.stage.value, x.priority))
        return self

    async def run(self, ctx: PipelineContext, stage: PipelineStage) -> PipelineContext:
        for f in self._filters:
            if f.stage == stage:
                ctx = await f.process(ctx)
        return ctx
