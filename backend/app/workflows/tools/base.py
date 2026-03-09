"""Base tool interface — all workflow tools implement this contract."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolInput:
    """Input passed to every tool execution."""

    params: dict[str, Any]
    context: dict[str, Any] = field(default_factory=dict)
    # context includes: workspace_id, user_id, run_id


@dataclass
class ToolOutput:
    """Standardised output returned by every tool."""

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # metadata includes: duration_ms, token_usage, prompt_version


class BaseTool(ABC):
    """Abstract base for all workflow tools.

    Tools are stateless — all state flows through ToolInput/ToolOutput.
    """

    name: str
    description: str
    input_schema: dict  # JSON Schema describing expected params
    output_schema: dict  # JSON Schema describing data shape

    @abstractmethod
    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        """Run the tool. Must be idempotent where possible."""
        ...

    async def validate_input(self, params: dict) -> list[str]:
        """Optional pre-execution validation. Returns list of error messages."""
        return []

    def __repr__(self) -> str:
        return f"<Tool {self.name}>"
