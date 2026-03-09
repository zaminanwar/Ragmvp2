"""Transform workflow tools — pure data manipulation (map, merge)."""

from __future__ import annotations

import structlog

from app.workflows.tools.base import BaseTool, ToolInput, ToolOutput

logger = structlog.get_logger(__name__)


class TransformMapTool(BaseTool):
    name = "transform.map"
    description = "Apply a field mapping/transformation to each item in a list."
    input_schema = {
        "type": "object",
        "properties": {
            "items": {"type": "array", "description": "List of objects to transform"},
            "mapping": {
                "type": "object",
                "description": "Field mapping: {new_field: old_field_or_expression}",
            },
            "include_original": {"type": "boolean", "default": False},
        },
        "required": ["items", "mapping"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "items": {"type": "array"},
        },
    }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        params = tool_input.params
        try:
            items = params["items"]
            mapping = params["mapping"]
            include_original = params.get("include_original", False)
            result = []

            for item in items:
                if not isinstance(item, dict):
                    result.append(item)
                    continue

                new_item = dict(item) if include_original else {}
                for new_key, source in mapping.items():
                    if isinstance(source, str) and source in item:
                        new_item[new_key] = item[source]
                    else:
                        new_item[new_key] = source  # literal value
                result.append(new_item)

            return ToolOutput(success=True, data={"items": result})
        except Exception as e:
            logger.exception("transform_map_failed", error=str(e))
            return ToolOutput(success=False, error=str(e))


class TransformMergeTool(BaseTool):
    name = "transform.merge"
    description = "Merge two lists of objects by a common key."
    input_schema = {
        "type": "object",
        "properties": {
            "left": {"type": "array"},
            "right": {"type": "array"},
            "on": {"type": "string", "description": "Key to join on"},
        },
        "required": ["left", "right", "on"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "items": {"type": "array"},
        },
    }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        params = tool_input.params
        try:
            left = params["left"]
            right = params["right"]
            key = params["on"]

            # Index right side by key
            right_index = {}
            for item in right:
                if isinstance(item, dict) and key in item:
                    right_index[item[key]] = item

            merged = []
            for item in left:
                if not isinstance(item, dict):
                    merged.append(item)
                    continue
                result = dict(item)
                k = item.get(key)
                if k and k in right_index:
                    result.update(right_index[k])
                merged.append(result)

            return ToolOutput(success=True, data={"items": merged})
        except Exception as e:
            logger.exception("transform_merge_failed", error=str(e))
            return ToolOutput(success=False, error=str(e))
