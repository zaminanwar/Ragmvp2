"""Unit tests for VariableResolver."""

import pytest

from app.workflows.engine.resolver import VariableResolver


# ── Helpers ──────────────────────────────────────────────────────────────────

def _resolver(*, state=None, inputs=None, context=None):
    return VariableResolver(
        state=state or {},
        inputs=inputs or {},
        context=context or {},
    )


# ── $inputs resolution ──────────────────────────────────────────────────────


class TestInputsResolution:
    def test_simple_input(self):
        r = _resolver(inputs={"name": "Alice"})
        assert r.resolve("$inputs.name") == "Alice"

    def test_nested_input(self):
        r = _resolver(inputs={"config": {"timeout": 30}})
        assert r.resolve("$inputs.config.timeout") == 30

    def test_input_preserves_dict(self):
        data = {"a": 1, "b": [2, 3]}
        r = _resolver(inputs={"payload": data})
        result = r.resolve("$inputs.payload")
        assert result == data
        assert isinstance(result, dict)

    def test_input_preserves_list(self):
        items = [1, 2, 3]
        r = _resolver(inputs={"items": items})
        result = r.resolve("$inputs.items")
        assert result == items
        assert isinstance(result, list)

    def test_input_preserves_int(self):
        r = _resolver(inputs={"count": 42})
        assert r.resolve("$inputs.count") == 42
        assert isinstance(r.resolve("$inputs.count"), int)

    def test_missing_input_raises(self):
        r = _resolver(inputs={})
        with pytest.raises(KeyError):
            r.resolve("$inputs.missing")


# ── $steps resolution ───────────────────────────────────────────────────────


class TestStepsResolution:
    def test_step_output_field(self):
        state = {"fetch_schema": {"output": {"schema": {"types": ["req"]}}}}
        r = _resolver(state=state)
        assert r.resolve("$steps.fetch_schema.output.schema") == {"types": ["req"]}

    def test_deep_step_output(self):
        state = {"step1": {"output": {"result": {"items": [1, 2]}}}}
        r = _resolver(state=state)
        assert r.resolve("$steps.step1.output.result.items") == [1, 2]

    def test_missing_step_raises(self):
        r = _resolver(state={})
        with pytest.raises(KeyError):
            r.resolve("$steps.nonexistent.output.data")


# ── $context resolution ─────────────────────────────────────────────────────


class TestContextResolution:
    def test_context_field(self):
        r = _resolver(context={"workspace_id": "ws-123", "user_id": "u-456"})
        assert r.resolve("$context.workspace_id") == "ws-123"
        assert r.resolve("$context.user_id") == "u-456"

    def test_missing_context_raises(self):
        r = _resolver(context={})
        with pytest.raises(KeyError):
            r.resolve("$context.unknown")


# ── $item (loop variable) resolution ────────────────────────────────────────


class TestLoopVariables:
    def test_loop_var(self):
        r = _resolver()
        r.set_loop_var("item", {"id": "REQ-1", "text": "shall do X"})
        assert r.resolve("$item.id") == "REQ-1"
        assert r.resolve("$item.text") == "shall do X"

    def test_clear_loop_vars(self):
        r = _resolver()
        r.set_loop_var("item", {"id": "REQ-1"})
        r.clear_loop_vars()
        # After clear, $item should resolve to None, and accessing .id fails
        with pytest.raises((TypeError, ValueError, AttributeError)):
            r.resolve("$item.id")


# ── Inline substitution (string interpolation) ──────────────────────────────


class TestInlineSubstitution:
    def test_inline_var_in_string(self):
        r = _resolver(inputs={"name": "Alice"})
        result = r.resolve("Hello $inputs.name!")
        assert result == "Hello Alice!"

    def test_multiple_vars_in_string(self):
        r = _resolver(inputs={"first": "A", "last": "B"})
        result = r.resolve("$inputs.first-$inputs.last")
        assert result == "A-B"

    def test_inline_coerces_to_string(self):
        r = _resolver(inputs={"count": 42})
        result = r.resolve("Count is $inputs.count")
        assert result == "Count is 42"
        assert isinstance(result, str)


# ── Jinja2 templates ────────────────────────────────────────────────────────


class TestJinja2:
    def test_jinja_template(self):
        r = _resolver(inputs={"name": "world"})
        result = r.resolve("{{ inputs.name | upper }}")
        assert result == "WORLD"

    def test_jinja_with_steps(self):
        state = {"s1": {"output": {"count": 5}}}
        r = _resolver(state=state)
        result = r.resolve("Found {{ steps.s1.output.count }} items")
        assert result == "Found 5 items"


# ── Recursive resolution (dicts and lists) ──────────────────────────────────


class TestRecursiveResolution:
    def test_resolve_dict(self):
        r = _resolver(inputs={"project": "P1", "timeout": 30})
        value = {
            "project_id": "$inputs.project",
            "options": {"timeout": "$inputs.timeout"},
        }
        result = r.resolve(value)
        assert result == {"project_id": "P1", "options": {"timeout": 30}}

    def test_resolve_list(self):
        r = _resolver(inputs={"a": "X", "b": "Y"})
        result = r.resolve(["$inputs.a", "$inputs.b", "literal"])
        assert result == ["X", "Y", "literal"]

    def test_non_string_passthrough(self):
        r = _resolver()
        assert r.resolve(42) == 42
        assert r.resolve(True) is True
        assert r.resolve(None) is None

    def test_deepcopy_no_mutation(self):
        """Resolving should not mutate the original value."""
        r = _resolver(inputs={"x": "hello"})
        original = {"key": "$inputs.x"}
        r.resolve(original)
        assert original["key"] == "$inputs.x"  # unchanged


# ── Array projection [*] ────────────────────────────────────────────────────


class TestArrayProjection:
    def test_array_projection(self):
        state = {
            "step1": {
                "output": {
                    "items": [
                        {"name": "a", "val": 1},
                        {"name": "b", "val": 2},
                    ]
                }
            }
        }
        r = _resolver(state=state)
        result = r.resolve("$steps.step1.output.items[*].name")
        assert result == ["a", "b"]


# ── Unknown namespace ───────────────────────────────────────────────────────


class TestUnknownNamespace:
    def test_unknown_namespace_raises(self):
        r = _resolver()
        with pytest.raises(ValueError, match="Unknown variable namespace"):
            r.resolve("$unknown.field")
