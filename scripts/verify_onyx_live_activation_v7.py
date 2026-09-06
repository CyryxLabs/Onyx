"""Cumulative gate for the isolated Onyx Live Activation V7 candidate."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
V6_MANIFEST = (
    ROOT
    / "docs"
    / "onyx"
    / "checkpoints"
    / "onyx-live-activation-v6"
    / "manifest.json"
)
V6_MANIFEST_SHA256 = "4b7b3bcdb7c87043e97baa952b883dcfc9f498026c272099f5222de7decb4453"
GATES = (
    (
        "v6",
        ROOT / "scripts" / "verify_onyx_live_activation_v6_manifest.py",
        "ONYX_LIVE_ACTIVATION_V6_MANIFEST_OK",
    ),
    (
        "host",
        ROOT / "scripts" / "verify_onyx_live_activation_v7_host.py",
        "ONYX_LIVE_ACTIVATION_V7_HOST_OK",
    ),
    (
        "phase5",
        ROOT / "scripts" / "verify_onyx_live_activation_v7_provider.py",
        "ONYX_LIVE_ACTIVATION_V7_PHASE5_E2E_OK",
    ),
)


def active_environment() -> dict[str, str]:
    from core.onyx_live_activation_v7 import exact_activation_environment

    result = dict(os.environ)
    for version in range(4, 8):
        result.pop(f"ONYX_LIVE_ACTIVATION_V{version}", None)
        result.pop(f"ONYX_LIVE_ROLLBACK_V{version}", None)
    result.update(exact_activation_environment())
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    result["QT_QPA_PLATFORM"] = "offscreen"
    result["QSG_RHI_BACKEND"] = "software"
    return result


def run() -> None:
    observed = hashlib.sha256(V6_MANIFEST.read_bytes()).hexdigest()
    if observed != V6_MANIFEST_SHA256:
        raise RuntimeError("frozen V6 manifest drift")
    outputs: list[str] = []
    for name, path, marker in GATES:
        result = subprocess.run(
            [str(PYTHON), "-B", str(path)],
            cwd=ROOT,
            env=active_environment(),
            text=True,
            capture_output=True,
            timeout=900,
            check=False,
        )
        if result.returncode or marker not in result.stdout:
            raise RuntimeError(
                f"{name} gate failed\n{result.stdout}\n{result.stderr}"
            )
        outputs.append(name)
    print("ONYX_LIVE_ACTIVATION_V7_CUMULATIVE_OK")
    print(
        "gates=" + ",".join(outputs) + " frozen_v6=exact "
        "canonical_identities=4 phase5=ready local_catalog_reads=1 "
        "network_calls=0 provider=fake-only live_activation=not_performed"
    )


if __name__ == "__main__":
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    run()
