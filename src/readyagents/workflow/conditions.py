"""Boolean conditions over existing comparison atoms. No Python eval()."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from readyagents.errors import TemplateError, WorkflowError
from readyagents.workflow.templates import interpolate, lookup

_COMPARE = re.compile(
    r"^\s*(.+?)\s*(==|!=|>=|<=|>|<|contains|startswith|endswith)\s*(.+?)\s*$",
    re.DOTALL,
)
_BOOL_OPS = re.compile(r"\b(and|or|not)\b", re.IGNORECASE)


def evaluate_condition(expr: str, mapping: Mapping[str, Any]) -> bool:
    """Evaluate a small boolean of comparisons / truthy paths. No `eval()`."""
    text = (expr or "").strip()
    if not text:
        return False
    try:
        return _eval_or(text, mapping)
    except WorkflowError:
        raise
    except TemplateError:
        raise


def _split_top(expr: str, op: str) -> list[str] | None:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    quote: str | None = None
    i = 0
    token = f" {op} "
    lower = expr
    while i < len(lower):
        ch = expr[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in {'"', "'"}:
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch == "(":
            depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ")":
            depth -= 1
            if depth < 0:
                raise WorkflowError("Unbalanced ')' in condition")
            buf.append(ch)
            i += 1
            continue
        if depth == 0 and expr[i : i + len(token)].lower() == token:
            piece = "".join(buf).strip()
            if not piece:
                raise WorkflowError(f"Empty operand for '{op}'")
            parts.append(piece)
            buf = []
            i += len(token)
            continue
        buf.append(ch)
        i += 1
    if quote:
        raise WorkflowError("Unterminated quote in condition")
    if depth != 0:
        raise WorkflowError("Unbalanced '(' in condition")
    tail = "".join(buf).strip()
    if parts:
        if not tail:
            raise WorkflowError(f"Empty operand for '{op}'")
        parts.append(tail)
        return parts
    return None


def _eval_or(expr: str, mapping: Mapping[str, Any]) -> bool:
    parts = _split_top(expr, "or")
    if parts is None:
        return _eval_and(expr, mapping)
    return any(_eval_and(part, mapping) for part in parts)


def _eval_and(expr: str, mapping: Mapping[str, Any]) -> bool:
    parts = _split_top(expr, "and")
    if parts is None:
        return _eval_not(expr, mapping)
    return all(_eval_not(part, mapping) for part in parts)


def _eval_not(expr: str, mapping: Mapping[str, Any]) -> bool:
    text = expr.strip()
    if text.lower().startswith("not ") or text.lower() == "not":
        rest = text[3:].strip()
        if not rest:
            raise WorkflowError("Empty operand for 'not'")
        return not _eval_not(rest, mapping)
    if text.startswith("(") and text.endswith(")"):
        inner = text[1:-1].strip()
        if _balanced_outer_parens(text):
            return _eval_or(inner, mapping)
    return _eval_atom(text, mapping)


def _balanced_outer_parens(text: str) -> bool:
    if not (text.startswith("(") and text.endswith(")")):
        return False
    depth = 0
    quote: str | None = None
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in {'"', "'"}:
            quote = ch
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and i != len(text) - 1:
                return False
    return depth == 0


def _eval_atom(expr: str, mapping: Mapping[str, Any]) -> bool:
    text = expr.strip()
    if _BOOL_OPS.search(text) and not _quoted_only_ops(text):
        raise WorkflowError(f"Could not parse condition '{expr}'")
    match = _COMPARE.match(text)
    if match:
        left_raw, op, right_raw = match.group(1), match.group(2), match.group(3)
        if not _is_single_operand(left_raw) or not _is_single_operand(right_raw):
            raise WorkflowError(f"Could not parse condition '{expr}'")
        if _BOOL_OPS.search(left_raw) or _BOOL_OPS.search(right_raw):
            if not (_quoted_only_ops(left_raw) and _quoted_only_ops(right_raw)):
                raise WorkflowError(f"Could not parse condition '{expr}'")
        left = _atom(left_raw, mapping)
        right = _atom(right_raw, mapping)
        return _compare(left, op, right)
    interpolated = interpolate(text, mapping) if "{{" in text else text
    try:
        value: Any = (
            lookup(mapping, interpolated)
            if interpolated.isidentifier() or "." in interpolated
            else interpolated
        )
    except TemplateError:
        value = interpolated
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0", ""}:
            return False
    return bool(value)


def _is_single_operand(raw: str) -> bool:
    text = raw.strip()
    if not text:
        return False
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        return True
    if "{{" in text:
        return text.count("{{") == 1 and text.count("}}") == 1
    if text.lower() in {"true", "false", "null", "none"}:
        return True
    if text.replace("_", "").replace(".", "").replace("-", "").isalnum():
        return True
    try:
        float(text)
        return True
    except ValueError:
        return False


def _quoted_only_ops(text: str) -> bool:
    """True if any and/or/not tokens sit only inside quotes."""
    quote: str | None = None
    i = 0
    lower = text.lower()
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in {'"', "'"}:
            quote = ch
            i += 1
            continue
        for word in ("and", "or", "not"):
            n = len(word)
            if lower[i : i + n] == word:
                before = text[i - 1] if i else " "
                after = text[i + n] if i + n < len(text) else " "
                if not before.isalnum() and before != "_" and not after.isalnum() and after != "_":
                    return False
        i += 1
    return True


def _atom(raw: str, mapping: Mapping[str, Any]) -> Any:
    text = raw.strip()
    quoted = (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    )
    if quoted:
        return interpolate(text[1:-1], mapping)
    if "{{" in text:
        return interpolate(text, mapping)
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    try:
        if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
            return int(text)
        return float(text)
    except ValueError:
        pass
    try:
        return lookup(mapping, text)
    except TemplateError:
        return interpolate(text, mapping) if "{{" in text else text


def _compare(left: Any, op: str, right: Any) -> bool:
    if op == "==":
        return _norm(left) == _norm(right)
    if op == "!=":
        return _norm(left) != _norm(right)
    if op in {">", "<", ">=", "<="}:
        try:
            lf, rf = float(left), float(right)
        except (TypeError, ValueError):
            lf, rf = str(left), str(right)
        if op == ">":
            return lf > rf
        if op == "<":
            return lf < rf
        if op == ">=":
            return lf >= rf
        return lf <= rf
    left_s, right_s = str(left), str(right)
    if op == "contains":
        return right_s in left_s
    if op == "startswith":
        return left_s.startswith(right_s)
    if op == "endswith":
        return left_s.endswith(right_s)
    return False


def _norm(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip()
    return value
