"""Variable resolver — resolves $-references and {{Jinja2}} templates in step inputs."""

from __future__ import annotations

import copy
import re
from typing import Any

from jinja2 import BaseLoader, Environment

# Matches $inputs.field, $steps.id.output.field, $context.field, $item.field
_VAR_PATTERN = re.compile(r"\$(\w+(?:\.\w+)*(?:\[\*\]\.\w+)*)")


class VariableResolver:
    """Recursively resolves variable references inside step input dicts.

    Supports:
        $inputs.<field>                       — workflow input provided at run start
        $steps.<step_id>.output.<field>       — output from a previous step
        $context.<field>                      — system context (workspace_id, user_id, run_id)
        $item.<field>                         — current loop iteration item
        {{jinja2 expression}}                 — Jinja2 templates in string values
    """

    def __init__(
        self,
        state: dict[str, Any],
        inputs: dict[str, Any],
        context: dict[str, Any],
    ):
        self._state = state       # {"step_id": {"output": {...}}}
        self._inputs = inputs
        self._context = context
        self._loop_vars: dict[str, Any] = {}
        self._jinja_env = Environment(loader=BaseLoader())

    # ── Public API ───────────────────────────────────────────────────────

    def resolve(self, value: Any) -> Any:
        """Recursively resolve all $-references and {{templates}} in *value*."""
        return self._resolve(copy.deepcopy(value))

    def set_loop_var(self, name: str, value: Any) -> None:
        self._loop_vars[name] = value

    def clear_loop_vars(self) -> None:
        self._loop_vars.clear()

    # ── Internal ─────────────────────────────────────────────────────────

    def _resolve(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._resolve_string(value)
        if isinstance(value, dict):
            return {k: self._resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve(v) for v in value]
        return value

    def _resolve_string(self, s: str) -> Any:
        # If the entire string is a single $variable, return the raw value
        # (preserves type — dict, list, int, etc.)
        match = _VAR_PATTERN.fullmatch(s)
        if match:
            return self._lookup(match.group(1))

        # Otherwise, do inline replacement (result is always a string)
        resolved = _VAR_PATTERN.sub(lambda m: str(self._lookup(m.group(1))), s)

        # Jinja2 templates
        if "{{" in resolved:
            tmpl = self._jinja_env.from_string(resolved)
            resolved = tmpl.render(
                inputs=self._inputs,
                steps=self._state,
                context=self._context,
                item=self._loop_vars.get("item"),
            )

        return resolved

    def _lookup(self, path: str) -> Any:
        """Resolve a dot-separated path like 'steps.fetch_schema.output.schema'."""
        parts = path.split(".")

        # Pick the root namespace
        root_key = parts[0]
        if root_key == "inputs":
            obj: Any = self._inputs
            parts = parts[1:]
        elif root_key == "steps":
            obj = self._state
            parts = parts[1:]
        elif root_key == "context":
            obj = self._context
            parts = parts[1:]
        elif root_key == "item":
            obj = self._loop_vars.get("item")
            parts = parts[1:]
        else:
            raise ValueError(f"Unknown variable namespace: ${root_key}")

        # Walk the remaining path
        for part in parts:
            # Handle [*] array projection
            if part.endswith("[*]"):
                key = part[:-3]
                obj = obj[key] if isinstance(obj, dict) else getattr(obj, key)
                # Remaining parts apply to each element — handled by caller
                # For now, return the list so subsequent . access can map over it
                continue

            if isinstance(obj, dict):
                if part not in obj:
                    raise KeyError(
                        f"Variable resolution failed: '{part}' not found in {list(obj.keys())}"
                    )
                obj = obj[part]
            elif isinstance(obj, list):
                # Apply field access across list items (array projection)
                obj = [item[part] if isinstance(item, dict) else getattr(item, part) for item in obj]
            else:
                raise ValueError(
                    f"Cannot access '{part}' on {type(obj).__name__}"
                )

        return obj
