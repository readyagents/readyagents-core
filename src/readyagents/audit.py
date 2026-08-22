"""Append-only audit trail for runs and decisions.

Resume snapshots still overwrite ``$READYAGENTS_HOME/runs/<id>.json``.
Audit events are a separate JSONL file that is never rewritten.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from readyagents.workflow.state import utc_now


def audit_dir_for(home: Path) -> Path:
    return Path(home) / "audit"


def append_audit_event(audit_dir: Path, event: Mapping[str, Any]) -> Path:
    """Append one JSON object as a line. Never truncates an existing file."""
    payload = dict(event)
    payload.setdefault("ts", utc_now())
    run_id = str(payload.get("run_id") or "unknown")
    audit_dir = Path(audit_dir)
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / f"{run_id}.jsonl"
    line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    fd = os.open(path, flags, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    return path


def read_audit_events(audit_dir: Path, run_id: str) -> list[dict[str, Any]]:
    path = Path(audit_dir) / f"{run_id}.jsonl"
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            events.append(row)
    return events


def make_auditor(audit_dir: Path, redactor: Any | None = None):
    """Return ``auditor(event, **fields)`` that appends a redacted JSONL line."""

    def _audit(event: str, **fields: Any) -> None:
        payload: dict[str, Any] = {"event": event, **fields}
        if redactor is not None:
            payload = redactor.redact(payload)
        append_audit_event(audit_dir, payload)

    return _audit
