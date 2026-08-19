"""Immutable-ish run state and persisted run records."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from readyagents.errors import ConfigError, WorkflowError


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
    pending_node: str | None = None
    usage: dict[str, int] = field(default_factory=dict)
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

    def add_usage(self, **amounts: Any) -> None:
        for key, raw in amounts.items():
            if raw is None:
                continue
            try:
                n = int(raw)
            except (TypeError, ValueError):
                continue
            self.usage[key] = int(self.usage.get(key, 0)) + n

    def to_record(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow": self.workflow_name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "pending_node": self.pending_node,
            "inputs": _jsonable(self.inputs),
            "outputs": _jsonable(self.output_keys or self.node_outputs),
            "output_keys": _jsonable(self.output_keys),
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
            "usage": dict(self.usage),
        }

    @classmethod
    def from_record(cls, data: Mapping[str, Any]) -> RunState:
        results = [
            NodeResult(
                node_id=str(row.get("node_id", "")),
                type=str(row.get("type", "")),
                status=str(row.get("status", "")),
                output=row.get("output"),
                error=row.get("error"),
                attempts=int(row.get("attempts") or 1),
                started_at=str(row.get("started_at") or ""),
                finished_at=str(row.get("finished_at") or ""),
            )
            for row in data.get("node_results") or []
            if isinstance(row, Mapping)
        ]
        return cls(
            run_id=str(data.get("run_id") or ""),
            workflow_name=str(data.get("workflow") or data.get("workflow_name") or ""),
            inputs=dict(data.get("inputs") or {}),
            node_outputs=dict(data.get("node_outputs") or {}),
            output_keys=dict(data.get("output_keys") or data.get("outputs") or {}),
            results=results,
            metadata=dict(data.get("metadata") or {}),
            errors=list(data.get("errors") or []),
            status=str(data.get("status") or "running"),
            pending_node=data.get("pending_node"),
            usage={str(k): int(v) for k, v in dict(data.get("usage") or {}).items()},
            started_at=str(data.get("started_at") or utc_now()),
            finished_at=data.get("finished_at"),
        )


def persist_run(state: RunState, runs_dir: Path) -> Path:
    """Atomically write `<run_id>.json` (temp file + os.replace)."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    path = runs_dir / f"{state.run_id}.json"
    tmp = runs_dir / f".{state.run_id}.{uuid4().hex}.json.tmp"
    record = json.dumps(state.to_record(), indent=2, ensure_ascii=False) + "\n"
    try:
        tmp.write_text(record, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return path


def load_run(runs_dir: Path, run_id: str) -> RunState:
    """Load a persisted run. `run_id` may be a unique prefix."""
    runs_dir = Path(runs_dir)
    exact = runs_dir / f"{run_id}.json"
    if exact.is_file():
        return _read_run(exact)
    matches = sorted(runs_dir.glob(f"{run_id}*.json")) if runs_dir.is_dir() else []
    if len(matches) == 1:
        return _read_run(matches[0])
    if len(matches) > 1:
        ids = ", ".join(p.stem for p in matches[:8])
        raise ConfigError(f"Run id '{run_id}' is ambiguous. Matches: {ids}")
    raise ConfigError(f"Run not found: {run_id}")


def list_runs(
    runs_dir: Path,
    *,
    status: str | None = None,
    workflow: str | None = None,
    limit: int = 0,
) -> list[RunState]:
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        return []
    states: list[RunState] = []
    for path in runs_dir.glob("*.json"):
        if path.name.startswith("."):
            continue
        try:
            states.append(_read_run(path))
        except (OSError, json.JSONDecodeError, ConfigError, TypeError, ValueError):
            continue
    states.sort(key=lambda s: s.started_at, reverse=True)
    if status:
        wanted = status.strip().lower()
        states = [s for s in states if s.status == wanted]
    if workflow:
        wanted_wf = workflow.strip()
        states = [s for s in states if s.workflow_name == wanted_wf]
    if limit and limit > 0:
        states = states[:limit]
    return states


def _read_run(path: Path) -> RunState:
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Corrupt run record {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Cannot read run record {path}: {exc}") from exc
    if not isinstance(data, dict) or not data.get("run_id"):
        raise ConfigError(f"Invalid run record: {path}")
    return RunState.from_record(data)


def build_decisions(approve: list[str], reject: list[str]) -> dict[str, str]:
    decisions: dict[str, str] = {}
    for node_id in approve:
        decisions[node_id] = "approve"
    for node_id in reject:
        decisions[node_id] = "reject"
    return decisions


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
