"""Verify every V8 candidate binding, then rerun its cumulative gate."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
MANIFEST = (
    ROOT / "docs" / "onyx" / "checkpoints" / "onyx-live-activation-v8" / "manifest.json"
)


def run() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert payload["schema"] == "onyx.live-activation.v8"
    assert payload["status"] == "candidate-ready-for-independent-gate"
    assert payload["default_off"] is True
    assert payload["live_activated"] is False
    assert payload["network_calls"] == 0
    assert payload["host_contract"]["v7_transactional_writes"] == 23
    assert payload["host_contract"]["v8_transactional_writes"] == 1
    assert payload["host_contract"]["total_transactional_writes"] == 24
    assert payload["shortcut"]["source_argument"] == (
        "scripts/bootstrap_onyx_live_v8.pyw"
    )
    assert payload["shortcut"]["source_target_required_file"] is True
    assert payload["shortcut"]["legacy_launcher_forbidden"] is True
    assert payload["shortcut"]["bootstrap_empty_environment_mode"] == "active"
    assert payload["shortcut"]["hud"] == "v5"
    assert payload["shortcut"]["frozen_behavior"] == "delegated-unchanged"
    seen: set[str] = set()
    for entry in payload["files"]:
        relative = entry["path"]
        assert relative not in seen
        seen.add(relative)
        observed = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert observed == entry["sha256"], relative
    result = subprocess.run(
        [str(PYTHON), "-B", "scripts/verify_onyx_live_activation_v8.py"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=1200,
        check=False,
    )
    if (
        result.returncode
        or "ONYX_LIVE_ACTIVATION_V8_CUMULATIVE_OK" not in result.stdout
    ):
        raise RuntimeError(result.stdout + result.stderr)
    print("ONYX_LIVE_ACTIVATION_V8_MANIFEST_OK")
    print(
        f"bindings={len(seen)} cumulative=pass shortcut=bootstrap-v8 "
        "mode=active hud=v5 live_activation=not_performed"
    )


if __name__ == "__main__":
    run()
