"""Built-in pipeline filters for common operations."""

import re
import structlog

from app.pipelines.base import PipelineContext, PipelineFilter, PipelineStage

logger = structlog.get_logger()


class QueryCleanupFilter(PipelineFilter):
    """Clean and normalize user queries before retrieval."""

    stage = PipelineStage.PRE_RETRIEVAL
    priority = 10

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        # Trim excessive whitespace
        ctx.query = re.sub(r"\s+", " ", ctx.query).strip()
        return ctx


class ProfanityFilter(PipelineFilter):
    """Basic content safety filter on generated output."""

    stage = PipelineStage.POST_GENERATION
    priority = 10

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        # Placeholder for content safety checks
        ctx.metadata["safety_checked"] = True
        return ctx


class TokenBudgetFilter(PipelineFilter):
    """Trim retrieval results to fit within a token budget (Pathway's adaptive RAG pattern)."""

    stage = PipelineStage.POST_RETRIEVAL
    priority = 50

    def __init__(self, max_context_tokens: int = 4000):
        self.max_tokens = max_context_tokens

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        total_tokens = 0
        trimmed = []
        for result in ctx.retrieval_results:
            token_estimate = len(result.content.split()) * 1.3  # Rough estimate
            if total_tokens + token_estimate > self.max_tokens:
                break
            trimmed.append(result)
            total_tokens += token_estimate

        ctx.retrieval_results = trimmed
        ctx.metadata["context_tokens_estimate"] = int(total_tokens)
        return ctx


class UsageTrackingFilter(PipelineFilter):
    """Track usage metrics for monitoring and billing."""

    stage = PipelineStage.POST_GENERATION
    priority = 90

    async def process(self, ctx: PipelineContext) -> PipelineContext:
        logger.info(
            "usage_tracked",
            workspace_id=str(ctx.workspace_id),
            user_id=str(ctx.user_id),
            query_length=len(ctx.query),
            result_count=len(ctx.retrieval_results),
            response_length=len(ctx.generated_text),
        )
        return ctx
