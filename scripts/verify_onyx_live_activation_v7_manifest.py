"""Verify every V7 candidate binding, then rerun the cumulative gate."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
MANIFEST = (
    ROOT
    / "docs"
    / "onyx"
    / "checkpoints"
    / "onyx-live-activation-v7"
    / "manifest.json"
)


def run() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema"] == "onyx.live-activation.v7"
    assert data["status"] == "candidate-ready-for-independent-gate"
    assert data["default_off"] is True
    assert data["live_activated"] is False
    assert data["provider_calls_performed"] is False
    assert data["network_calls"] == 0
    assert data["activation"]["independent_gate_required"] is True
    assert data["host_contract"]["v6_transactional_writes"] == 22
    assert data["host_contract"]["v7_transactional_writes"] == 1
    assert data["host_contract"]["total_transactional_writes"] == 23
    assert data["phase5_identity"] == {
        "principal_id": "onyx-owner",
        "workspace_id": "onyx-local-workspace",
        "account_id": "cyryx-local-account",
        "profile_id": "onyx-owner-profile",
    }
    assert data["local_catalog"]["public_arguments_coerced"] is False
    assert data["local_catalog"]["full_main_broker"] is True
    assert data["local_catalog"]["completed_reads"] == 1
    assert data["local_catalog"]["same_call_id_reexecution"] == 0
    seen: set[str] = set()
    for entry in data["files"]:
        relative = entry["path"]
        assert relative not in seen
        seen.add(relative)
        observed = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert observed == entry["sha256"], relative
    result = subprocess.run(
        [
            str(PYTHON),
            "-B",
            str(ROOT / "scripts" / "verify_onyx_live_activation_v7.py"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=1200,
        check=False,
    )
    if result.returncode or "ONYX_LIVE_ACTIVATION_V7_CUMULATIVE_OK" not in result.stdout:
        raise RuntimeError(result.stdout + result.stderr)
    print("ONYX_LIVE_ACTIVATION_V7_MANIFEST_OK")
    print(
        f"bindings={len(seen)} cumulative=pass status=candidate "
        "phase5=ready local_catalog_reads=1 live_activation=not_performed"
    )


if __name__ == "__main__":
    run()
