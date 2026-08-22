"""Strict structured output validation for agent nodes (Pydantic)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from readyagents.errors import StructuredOutputError

_JSON_TYPES: dict[str, Any] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def parse_json_payload(text: str) -> Any:
    stripped = (text or "").strip()
    if not stripped:
        raise ValueError("empty LLM output")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            pass
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start != -1 and end != -1 and end > start:
        return json.loads(stripped[start : end + 1])
    raise ValueError("LLM output is not JSON")


def _annotation(spec: Any) -> Any:
    if not isinstance(spec, dict):
        return Any
    raw_type = spec.get("type")
    if isinstance(raw_type, list):
        parts = [_simple(t) for t in raw_type]
        out: Any = parts[0] if parts else Any
        for part in parts[1:]:
            out = out | part
        return out
    return _simple(raw_type or "string")


def _simple(raw: Any) -> Any:
    if not isinstance(raw, str):
        return Any
    return _JSON_TYPES.get(raw, Any)


def model_from_schema(schema: dict[str, Any]) -> type[BaseModel]:
    """Build a one-off Pydantic model from a JSON Schema object."""
    extra_flag = schema.get("additionalProperties", True)
    extra = "allow" if extra_flag else "forbid"

    class _Base(BaseModel):
        model_config = ConfigDict(extra=extra)

    props = schema.get("properties")
    if not isinstance(props, dict):
        # Whole-payload type, e.g. {"type": "object"} with no properties.
        return create_model("AgentStructured", __base__=_Base)

    required = {str(item) for item in (schema.get("required") or []) if item}
    fields: dict[str, Any] = {}
    for name, spec in props.items():
        annotation = _annotation(spec if isinstance(spec, dict) else {})
        if name in required:
            fields[name] = (annotation, Field(...))
        else:
            fields[name] = (annotation | None, None)
    return create_model("AgentStructured", __base__=_Base, **fields)


def validate_structured_output(text: str, schema: dict[str, Any], *, node_id: str) -> Any:
    """Parse JSON and validate against ``schema``. Raises StructuredOutputError."""
    try:
        data = parse_json_payload(text)
    except (ValueError, json.JSONDecodeError) as exc:
        raise StructuredOutputError(node_id, f"structured output is not JSON: {exc}") from exc
    if not isinstance(schema, dict) or not schema:
        raise StructuredOutputError(node_id, "output_schema must be a JSON Schema object")
    model = model_from_schema(schema)
    try:
        parsed = model.model_validate(data)
    except ValidationError as exc:
        raise StructuredOutputError(
            node_id, f"structured output failed schema validation: {exc}"
        ) from exc
    return parsed.model_dump()
