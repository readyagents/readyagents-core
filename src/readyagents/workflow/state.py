"""Immutable-ish run state and persisted run records."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from readyagents.errors import WorkflowError


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class NodeResult:
    node_id: str
    type: str
    status: str
    output: Any = None
    error: str | None = None
    attempts: int = 1
    started_at: str = ""
    finished_at: str = ""


@dataclass
class RunState:
    """Inputs + per-node outputs. Treat as append-only during a run."""

    run_id: str
    workflow_name: str
    inputs: dict[str, Any]
    node_outputs: dict[str, Any] = field(default_factory=dict)
    output_keys: dict[str, Any] = field(default_factory=dict)
    results: list[NodeResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    status: str = "running"
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None

    @classmethod
    def start(
        cls,
        workflow_name: str,
        inputs: Mapping[str, Any],
        *,
        metadata: Mapping[str, Any] | None = None,
        run_id: str | None = None,
    ) -> RunState:
        return cls(
            run_id=run_id or uuid4().hex,
            workflow_name=workflow_name,
            inputs=dict(inputs),
            metadata=dict(metadata or {}),
        )

    def mapping(self) -> dict[str, Any]:
        """Template namespace: inputs, node ids, output keys, metadata."""
        ns: dict[str, Any] = {}
        ns.update(self.metadata)
        ns.update(self.inputs)
        ns.update(self.node_outputs)
        ns.update(self.output_keys)
        ns["inputs"] = self.inputs
        ns["outputs"] = self.node_outputs
        ns["run_id"] = self.run_id
        return ns

    def record(
        self,
        node_id: str,
        output: Any,
        *,
        node_type: str,
        output_key: str | None = None,
        attempts: int = 1,
        started_at: str = "",
        finished_at: str = "",
    ) -> None:
        self.node_outputs[node_id] = output
        if output_key:
            self.output_keys[output_key] = output
        self.results.append(
            NodeResult(
                node_id=node_id,
                type=node_type,
                status="ok",
                output=_jsonable(output),
                attempts=attempts,
                started_at=started_at,
                finished_at=finished_at,
            )
        )

    def record_error(
        self, node_id: str, node_type: str, message: str, *, attempts: int = 1
    ) -> None:
        self.errors.append(message)
        self.results.append(
            NodeResult(
                node_id=node_id,
                type=node_type,
                status="error",
                error=message,
                attempts=attempts,
                finished_at=utc_now(),
            )
        )

    def finish(self, status: str) -> None:
        self.status = status
        self.finished_at = utc_now()

    def to_record(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow": self.workflow_name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "inputs": _jsonable(self.inputs),
            "outputs": _jsonable(self.output_keys or self.node_outputs),
            "node_outputs": _jsonable(self.node_outputs),
            "node_results": [
                {
                    "node_id": r.node_id,
                    "type": r.type,
                    "status": r.status,
                    "output": r.output,
                    "error": r.error,
                    "attempts": r.attempts,
                    "started_at": r.started_at,
                    "finished_at": r.finished_at,
                }
                for r in self.results
            ],
            "metadata": _jsonable(self.metadata),
            "errors": list(self.errors),
        }


def persist_run(state: RunState, runs_dir: Path) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{state.run_id}.json"
    record = json.dumps(state.to_record(), indent=2, ensure_ascii=False) + "\n"
    path.write_text(record, encoding="utf-8")
    return path


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def parse_input_pairs(pairs: list[str]) -> dict[str, Any]:
    """Parse CLI `--input KEY=VALUE` pairs."""
    result: dict[str, Any] = {}
    for raw in pairs:
        if "=" not in raw:
            raise WorkflowError(f"Invalid --input '{raw}' (expected KEY=VALUE)")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise WorkflowError(f"Invalid --input '{raw}' (empty key)")
        result[key] = _coerce_scalar(value)
    return result


def _coerce_scalar(value: str) -> Any:
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null" or lowered == "none":
        return None
    try:
        if value.strip().isdigit() or (
            value.strip().startswith("-") and value.strip()[1:].isdigit()
        ):
            return int(value.strip())
        return float(value) if "." in value.strip() else value
    except ValueError:
        return value
