"""Tool registry — singleton that maps tool names to BaseTool instances."""

from __future__ import annotations

import structlog

from app.workflows.tools.base import BaseTool

logger = structlog.get_logger(__name__)


class ToolRegistry:
    """Global registry of workflow tools, keyed by name (e.g. 'rag.query')."""

    _tools: dict[str, BaseTool] = {}

    @classmethod
    def register(cls, tool: BaseTool) -> None:
        if tool.name in cls._tools:
            logger.warning("tool_overwritten", tool=tool.name)
        cls._tools[tool.name] = tool
        logger.info("tool_registered", tool=tool.name)

    @classmethod
    def get(cls, name: str) -> BaseTool:
        try:
            return cls._tools[name]
        except KeyError:
            raise KeyError(f"Tool '{name}' not found. Registered: {list(cls._tools.keys())}")

    @classmethod
    def has(cls, name: str) -> bool:
        return name in cls._tools

    @classmethod
    def list_tools(cls) -> list[dict]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
                "output_schema": t.output_schema,
            }
            for t in cls._tools.values()
        ]

    @classmethod
    def clear(cls) -> None:
        """Reset registry — useful in tests."""
        cls._tools = {}


def register_all_tools() -> None:
    """Called at app startup to register every built-in tool.

    Adapter tools (e.g. alm.*) are registered here too, conditional on config.
    """
    from app.workflows.tools.rag_tools import RagQueryTool, RagBatchQueryTool, RagIngestTool
    from app.workflows.tools.llm_tools import LlmClassifyTool, LlmExtractTool, LlmGenerateTool
    from app.workflows.tools.document_tools import DocumentParseTool, DocumentExtractTool
    from app.workflows.tools.transform_tools import TransformMapTool, TransformMergeTool
    from app.workflows.tools.export_tools import ExportExcelTool
    from app.workflows.tools.notify_tools import NotifyWebhookTool, NotifyEmailTool

    for tool_cls in [
        RagQueryTool, RagBatchQueryTool, RagIngestTool,
        LlmClassifyTool, LlmExtractTool, LlmGenerateTool,
        DocumentParseTool, DocumentExtractTool,
        TransformMapTool, TransformMergeTool,
        ExportExcelTool,
        NotifyWebhookTool, NotifyEmailTool,
    ]:
        ToolRegistry.register(tool_cls())

    logger.info("register_all_tools", count=len(ToolRegistry._tools))
