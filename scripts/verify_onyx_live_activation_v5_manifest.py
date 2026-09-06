"""Verify every V5 manifest binding, then rerun the cumulative candidate gate."""

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
    / "onyx-live-activation-v5"
    / "manifest.json"
)


def run():
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema"] == "onyx.live-activation.v5"
    assert data["status"] == "candidate-ready-for-independent-gate"
    assert data["default_off"] is True
    assert data["live_activated"] is False
    assert data["provider_calls_performed"] is False
    assert data["activation"]["independent_gate_required"] is True

    seen = set()
    for entry in data["files"]:
        relative = entry["path"]
        assert relative not in seen
        seen.add(relative)
        observed = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        assert observed == entry["sha256"], relative

    result = subprocess.run(
        [str(PYTHON), "-B", str(ROOT / "scripts" / "verify_onyx_live_activation_v5.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=300,
        check=False,
    )
    if result.returncode or "ONYX_LIVE_ACTIVATION_V5_CUMULATIVE_OK" not in result.stdout:
        raise RuntimeError(result.stdout + result.stderr)
    print("ONYX_LIVE_ACTIVATION_V5_MANIFEST_OK")
    print(
        f"bindings={len(seen)} cumulative=pass status=candidate "
        "live_activation=not_performed"
    )


if __name__ == "__main__":
    run()
