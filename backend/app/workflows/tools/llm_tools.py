"""LLM workflow tools — classify, extract, generate via existing LLM providers."""

from __future__ import annotations

import json

import structlog

from app.rag.llm.factory import get_llm_provider
from app.workflows.tools.base import BaseTool, ToolInput, ToolOutput

logger = structlog.get_logger(__name__)


class LlmClassifyTool(BaseTool):
    name = "llm.classify"
    description = "Use an LLM to classify items against a schema (e.g. Polarion work-item types)."
    input_schema = {
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "File path or content to classify"},
            "schema": {"description": "Target classification schema (e.g. ALM work-item types)"},
            "instructions": {"type": "string"},
            "provider": {"type": "string"},
            "model": {"type": "string"},
        },
        "required": ["instructions"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "workitems": {"type": "array"},
        },
    }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        params = tool_input.params
        try:
            llm = get_llm_provider(
                provider=params.get("provider"),
                model=params.get("model"),
            )
            prompt = params["instructions"]
            if params.get("schema"):
                prompt += f"\n\nTarget schema:\n{json.dumps(params['schema'], indent=2)}"
            if params.get("file"):
                prompt += f"\n\nContent to classify:\n{params['file']}"

            response = await llm.generate(
                prompt=prompt,
                system="You are an expert document classifier. Return valid JSON.",
                max_tokens=8192,
            )

            # Try to parse JSON from response
            try:
                data = json.loads(response.content)
            except json.JSONDecodeError:
                # Try to extract JSON from markdown code blocks
                content = response.content
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                data = json.loads(content.strip())

            return ToolOutput(
                success=True,
                data=data if isinstance(data, dict) else {"workitems": data},
                metadata={
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "model": response.model,
                },
            )
        except Exception as e:
            logger.exception("llm_classify_failed", error=str(e))
            return ToolOutput(success=False, error=str(e))


class LlmExtractTool(BaseTool):
    name = "llm.extract"
    description = "Use an LLM to extract structured data from text."
    input_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "schema": {"description": "Expected output schema"},
            "instructions": {"type": "string"},
        },
        "required": ["text", "instructions"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "extracted": {"description": "Extracted structured data"},
        },
    }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        params = tool_input.params
        try:
            llm = get_llm_provider(
                provider=params.get("provider"),
                model=params.get("model"),
            )
            prompt = f"{params['instructions']}\n\nText:\n{params['text']}"
            if params.get("schema"):
                prompt += f"\n\nExpected output schema:\n{json.dumps(params['schema'], indent=2)}"

            response = await llm.generate(
                prompt=prompt,
                system="You are an expert data extractor. Return valid JSON.",
                max_tokens=8192,
            )

            try:
                data = json.loads(response.content)
            except json.JSONDecodeError:
                content = response.content
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                data = json.loads(content.strip())

            return ToolOutput(
                success=True,
                data={"extracted": data},
                metadata={
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "model": response.model,
                },
            )
        except Exception as e:
            logger.exception("llm_extract_failed", error=str(e))
            return ToolOutput(success=False, error=str(e))


class LlmGenerateTool(BaseTool):
    name = "llm.generate"
    description = "General-purpose LLM text generation."
    input_schema = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "system_prompt": {"type": "string"},
            "temperature": {"type": "number", "default": 0.1},
            "max_tokens": {"type": "integer", "default": 4096},
            "provider": {"type": "string"},
            "model": {"type": "string"},
        },
        "required": ["prompt"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
        },
    }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        params = tool_input.params
        try:
            llm = get_llm_provider(
                provider=params.get("provider"),
                model=params.get("model"),
            )
            response = await llm.generate(
                prompt=params["prompt"],
                system=params.get("system_prompt"),
                temperature=params.get("temperature", 0.1),
                max_tokens=params.get("max_tokens", 4096),
            )
            return ToolOutput(
                success=True,
                data={"content": response.content},
                metadata={
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "model": response.model,
                },
            )
        except Exception as e:
            logger.exception("llm_generate_failed", error=str(e))
            return ToolOutput(success=False, error=str(e))
