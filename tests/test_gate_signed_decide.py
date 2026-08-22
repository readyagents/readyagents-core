from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from readyagents.errors import ApprovalRequired
from readyagents.workflow.runner import run_workflow_file
from readyagents.workflow.state import load_run

_PACK = Path(__file__).resolve().parents[1] / "examples" / "packs" / "hitl_gate.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("hitl_gate", _PACK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_gate()

_SECRET = "gate-test-secret"


def _pause_approval(tmp_path: Path, tmp_settings):
    wf = tmp_path / "approval_gate.yaml"
    src = Path(__file__).resolve().parents[1] / "examples" / "approval_gate.yaml"
    wf.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ApprovalRequired) as exc:
        run_workflow_file(wf, settings=tmp_settings, persist=True)
    return exc.value.run_id, wf


def _signed_body(run_id: str, *, secret: str = _SECRET) -> tuple[bytes, str]:
    payload = {"run_id": run_id, "node_id": "gate", "decision": "approve"}
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return body, gate.sign_body(secret, body)


def test_signed_payload_resumes_paused_approval(tmp_path: Path, tmp_settings) -> None:
    run_id, _wf = _pause_approval(tmp_path, tmp_settings)
    body, sig = _signed_body(run_id)
    state = gate.apply_signed_decision(body, sig, secret=_SECRET, settings=tmp_settings)
    assert state.status == "succeeded"
    assert "approval_gate ok" in str(state.output_keys.get("summary"))


def test_unsigned_payload_does_not_resume(tmp_path: Path, tmp_settings) -> None:
    run_id, _wf = _pause_approval(tmp_path, tmp_settings)
    body, _sig = _signed_body(run_id)
    with pytest.raises(gate.SignatureError, match="unsigned"):
        gate.apply_signed_decision(body, None, secret=_SECRET, settings=tmp_settings)
    loaded = load_run(tmp_settings.runs_dir(), run_id)
    assert loaded.status == "paused"
    assert loaded.pending_node == "gate"


def test_forged_signature_does_not_resume(tmp_path: Path, tmp_settings) -> None:
    run_id, _wf = _pause_approval(tmp_path, tmp_settings)
    body, _sig = _signed_body(run_id)
    with pytest.raises(gate.SignatureError, match="forged"):
        gate.apply_signed_decision(body, "deadbeef" * 8, secret=_SECRET, settings=tmp_settings)
    loaded = load_run(tmp_settings.runs_dir(), run_id)
    assert loaded.status == "paused"


def test_http_post_signed_uses_resume_path(tmp_path: Path, tmp_settings) -> None:
    run_id, _wf = _pause_approval(tmp_path, tmp_settings)
    body, sig = _signed_body(run_id)
    code, payload = gate.handle_http_post(
        {gate.SIGNATURE_HEADER: sig},
        body,
        secret=_SECRET,
        settings=tmp_settings,
    )
    assert code == 200
    assert payload["ok"] is True
    assert payload["status"] == "succeeded"
    summary = str((payload.get("outputs") or {}).get("summary"))
    assert "approval_gate ok" in summary


def test_http_post_unsigned_stays_paused(tmp_path: Path, tmp_settings) -> None:
    run_id, _wf = _pause_approval(tmp_path, tmp_settings)
    body, _sig = _signed_body(run_id)
    code, payload = gate.handle_http_post(
        {},
        body,
        secret=_SECRET,
        settings=tmp_settings,
    )
    assert code == 401
    assert payload["ok"] is False
    loaded = load_run(tmp_settings.runs_dir(), run_id)
    assert loaded.status == "paused"
