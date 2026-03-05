"""Robust JSON extraction from LLM responses.

Handles markdown code blocks, extra text, and malformed JSON
across all providers (OpenAI, Anthropic, Ollama).
"""

import json
import re


def parse_json_response(text: str, default: dict | list | None = None) -> dict | list:
    """Extract JSON from LLM response text.

    Tries multiple strategies:
    1. Direct JSON parse
    2. Extract from ```json ... ``` blocks
    3. Find first { ... } or [ ... ] in text
    4. Return default if all fail
    """
    text = text.strip()

    # Strategy 1: Direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 2: Markdown code blocks
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if code_block:
        try:
            return json.loads(code_block.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 3: Find JSON object or array
    for pattern in [r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", r"\[.*?\]"]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except (json.JSONDecodeError, ValueError):
                pass

    # Strategy 4: Default
    if default is not None:
        return default

    return {"error": "Failed to parse JSON", "raw": text[:200]}


def parse_json_array(text: str) -> list[str]:
    """Extract a JSON array of strings from LLM response."""
    result = parse_json_response(text, default=[])
    if isinstance(result, list):
        return [str(item) for item in result]
    return []
