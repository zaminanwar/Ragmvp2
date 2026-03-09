"""Unit tests for ToolRegistry."""

import pytest

from app.workflows.tools.base import BaseTool, ToolInput, ToolOutput
from app.workflows.tools.registry import ToolRegistry
from tests.conftest import EchoTool


class TestToolRegistry:
    def test_register_and_get(self):
        tool = EchoTool()
        ToolRegistry.register(tool)
        assert ToolRegistry.get("test.echo") is tool

    def test_get_missing_raises(self):
        with pytest.raises(KeyError, match="not found"):
            ToolRegistry.get("nonexistent.tool")

    def test_has(self):
        assert not ToolRegistry.has("test.echo")
        ToolRegistry.register(EchoTool())
        assert ToolRegistry.has("test.echo")

    def test_list_tools(self):
        ToolRegistry.register(EchoTool())
        tools = ToolRegistry.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "test.echo"
        assert "description" in tools[0]
        assert "input_schema" in tools[0]
        assert "output_schema" in tools[0]

    def test_clear(self):
        ToolRegistry.register(EchoTool())
        assert ToolRegistry.has("test.echo")
        ToolRegistry.clear()
        assert not ToolRegistry.has("test.echo")

    def test_overwrite_warning(self):
        """Registering a tool with the same name overwrites the previous one."""
        tool1 = EchoTool()
        tool2 = EchoTool()
        ToolRegistry.register(tool1)
        ToolRegistry.register(tool2)
        assert ToolRegistry.get("test.echo") is tool2

    def test_list_tools_multiple(self):
        from tests.conftest import FailTool

        ToolRegistry.register(EchoTool())
        ToolRegistry.register(FailTool())
        tools = ToolRegistry.list_tools()
        names = {t["name"] for t in tools}
        assert names == {"test.echo", "test.fail"}
