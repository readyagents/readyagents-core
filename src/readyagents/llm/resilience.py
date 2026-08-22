"""Budget, model fallback, circuit breaker, and token-cost helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, NoReturn

from readyagents.errors import BudgetExceeded, CircuitOpen, LLMError
from readyagents.llm.base import parse_model_ref
from readyagents.logging import get_logger

log = get_logger("llm.resilience")

# USD per million tokens (prompt, completion). Approximate public list prices.
_RATES_PER_MILLION: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-3-5-sonnet": (3.00, 15.00),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "default": (0.15, 0.60),
}


def cost_micros(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    rates: Mapping[str, tuple[float, float]] | None = None,
) -> int:
    """USD cost as integer millionths of a dollar (exact to sum)."""
    table = rates or _RATES_PER_MILLION
    key = (model or "").split(":")[-1].strip() or "default"
    prompt_rate, completion_rate = table.get(key) or table.get("default") or (0.15, 0.60)
    usd = (prompt_tokens / 1_000_000) * prompt_rate + (
        completion_tokens / 1_000_000
    ) * completion_rate
    return int(round(usd * 1_000_000))


def normalize_usage(raw: Mapping[str, Any] | None, *, model: str = "") -> dict[str, int]:
    data = dict(raw or {})
    prompt_raw = data.get("prompt_tokens")
    if prompt_raw is None:
        prompt_raw = data.get("input_tokens")
    prompt = _as_int(prompt_raw)
    completion = _as_int(
        data.get("completion_tokens")
        if data.get("completion_tokens") is not None
        else data.get("output_tokens")
    )
    total = _as_int(data.get("total_tokens")) or (prompt + completion)
    micros = _as_int(data.get("cost_micros"))
    if micros == 0 and (prompt or completion):
        micros = cost_micros(model, prompt, completion)
    out = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cost_micros": micros,
    }
    extra = _as_int(data.get("estimated_tokens"))
    if extra:
        out["estimated_tokens"] = extra
    hits = _as_int(data.get("cache_hits"))
    if hits:
        out["cache_hits"] = hits
    return out


def _as_int(raw: Any) -> int:
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def usage_nonzero(usage: Mapping[str, int]) -> bool:
    return any(int(v) for v in usage.values())


class CircuitBreaker:
    """Process-local breaker keyed by model ref. Not distributed."""

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        import time

        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self._clock = clock or time.monotonic
        self._fail_count: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def allow(self, model: str) -> bool:
        until = self._open_until.get(model)
        if until is None:
            return True
        if self._clock() >= until:
            self._open_until.pop(model, None)
            self._fail_count[model] = 0
            return True
        return False

    def record_success(self, model: str) -> None:
        self._fail_count[model] = 0
        self._open_until.pop(model, None)

    def record_failure(self, model: str) -> None:
        n = self._fail_count.get(model, 0) + 1
        self._fail_count[model] = n
        if n >= self.failure_threshold:
            self._open_until[model] = self._clock() + self.cooldown_seconds

    def is_open(self, model: str) -> bool:
        return not self.allow(model)


def model_candidates(
    primary: str | None,
    *fallback_groups: Sequence[str] | None,
) -> list[str]:
    seen: list[str] = []
    for group in ((primary,) if primary else (), *(fallback_groups or ())):
        if not group:
            continue
        for item in group:
            ref = str(item).strip()
            if ref and ref not in seen:
                seen.append(ref)
    return seen


def model_id_for(ref: str) -> str:
    if not ref:
        return "mock"
    if ":" in ref:
        return parse_model_ref(ref)[1]
    return ref


def check_budget(
    usage: Mapping[str, int],
    *,
    max_tokens: int | None = None,
    max_cost_micros: int | None = None,
) -> None:
    tokens = int(usage.get("total_tokens") or 0) + int(usage.get("estimated_tokens") or 0)
    if max_tokens is not None and tokens >= max_tokens:
        raise BudgetExceeded("tokens", tokens, max_tokens)
    cost = int(usage.get("cost_micros") or 0)
    if max_cost_micros is not None and cost >= max_cost_micros:
        raise BudgetExceeded("cost_micros", cost, max_cost_micros)


def usd_to_micros(value: float | int | None) -> int | None:
    if value is None:
        return None
    return int(round(float(value) * 1_000_000))


def raise_exhausted(
    tried: Sequence[str], skipped: Sequence[str], last: BaseException | None
) -> NoReturn:
    if skipped and not tried:
        raise CircuitOpen(skipped[0])
    if last is not None:
        raise last
    if skipped:
        raise CircuitOpen(skipped[0])
    raise LLMError("No LLM model was available")
