"""Safe `{{dotted.path}}` interpolation against run state."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from readyagents.errors import TemplateError

_VAR = re.compile(
    r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_\.]*)"
    r"(?:\s*\|\s*(default|len|join)(?:\s+([^}]+?))?)?"
    r"\s*\}\}"
)
_FILTERS = frozenset({"default", "len", "join"})


def resolve_path(data: Any, path: str) -> Any:
    """Resolve a dotted path (`a.b.0.c`) against dicts/lists."""
    current = data
    for part in path.split("."):
        current = _step(current, part, path)
    return current


def _step(current: Any, part: str, full: str) -> Any:
    if current is None:
        raise TemplateError(f"Missing template variable: {full}")
    if isinstance(current, Mapping):
        if part in current:
            return current[part]
        raise TemplateError(f"Missing template variable: {full}")
    if isinstance(current, (list, tuple)):
        try:
            idx = int(part)
        except ValueError as exc:
            raise TemplateError(f"Missing template variable: {full}") from exc
        try:
            return current[idx]
        except IndexError as exc:
            raise TemplateError(f"Missing template variable: {full}") from exc
    raise TemplateError(f"Missing template variable: {full}")


def lookup(mapping: Mapping[str, Any], path: str) -> Any:
    if path in mapping and "." not in path:
        return mapping[path]
    head, _, rest = path.partition(".")
    if head not in mapping:
        raise TemplateError(f"Missing template variable: {path}")
    if not rest:
        return mapping[head]
    return resolve_path(mapping[head], rest)


def interpolate(template: str, mapping: Mapping[str, Any]) -> str:
    """Replace `{{var}}` tokens. Missing names raise TemplateError unless `| default`."""

    def repl(match: re.Match[str]) -> str:
        path = match.group(1)
        filt = match.group(2)
        arg = (match.group(3) or "").strip()
        try:
            value = lookup(mapping, path)
        except TemplateError:
            if filt == "default":
                return _unquote(arg)
            raise
        if filt:
            value = _apply_filter(filt, value, arg)
        return _stringify(value)

    return _VAR.sub(repl, template)


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def _apply_filter(name: str, value: Any, arg: str) -> Any:
    if name == "default":
        if value is None or value == "":
            return _unquote(arg)
        return value
    if name == "len":
        try:
            return len(value)
        except TypeError as exc:
            raise TemplateError("filter len requires a sized value") from exc
    if name == "join":
        sep = _unquote(arg) if arg else ""
        if isinstance(value, str):
            return sep.join(value)
        try:
            return sep.join(_stringify(item) for item in value)
        except TypeError as exc:
            raise TemplateError("filter join requires an iterable") from exc
    raise TemplateError(f"unknown filter '{name}'")


def interpolate_value(value: Any, mapping: Mapping[str, Any]) -> Any:
    """Recursively interpolate strings inside dicts/lists."""
    if isinstance(value, str):
        return interpolate(value, mapping)
    if isinstance(value, Mapping):
        return {k: interpolate_value(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate_value(v, mapping) for v in value]
    if isinstance(value, tuple):
        return tuple(interpolate_value(v, mapping) for v in value)
    return value


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple, bool)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
