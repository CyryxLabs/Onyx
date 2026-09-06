"""Cumulative default-off gate for Onyx Live Activation V8."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
FROZEN_V7 = {
    "core/onyx_live_activation_v7.py": "906c7c0e31cb5efc28e5357bb158545e903d65ff1f160b3899bc3e2fb3c1dc77",
    "docs/onyx/checkpoints/onyx-live-activation-v7/manifest.json": "312d6654f3423f16f4b36f435638920836994bd56c3e9a8766a086e2c6d647da",
    "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V7-E6-001.md": "8438769b1b597b0d66174db0c73d50a9577702c5957ba6ff24b55315d11aedb5",
    "scripts/verify_onyx_live_activation_v7_acceptance.py": "23fb601ffe783e3283f4ff2d446f21e55f1b049a3b2b50fbefc52f8c4dac06d9",
    "tests/test_onyx_live_activation_v7_acceptance.py": "bad81b091ae09ca41f289f9515f2d630ca1fffbd83f2913426899f4d38d746d9",
}


def active_environment() -> dict[str, str]:
    from core.onyx_live_activation_v8 import exact_activation_environment

    result = dict(os.environ)
    for version in range(1, 9):
        result.pop(f"ONYX_LIVE_ACTIVATION_V{version}", None)
        result.pop(f"ONYX_LIVE_ROLLBACK_V{version}", None)
    result.update(exact_activation_environment())
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    result["QT_QPA_PLATFORM"] = "offscreen"
    result["QSG_RHI_BACKEND"] = "software"
    return result


def run() -> None:
    for relative, expected in FROZEN_V7.items():
        observed = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        if observed != expected:
            raise RuntimeError(f"frozen V7 drift: {relative}")
    compile_files = (
        "core/onyx_live_activation_v8.py",
        "scripts/launch_onyx_live_v8.pyw",
        "scripts/bootstrap_onyx_live_v8.pyw",
        "scripts/verify_onyx_live_activation_v8_host.py",
        "tests/test_onyx_live_activation_v8.py",
    )
    compiled = subprocess.run(
        [str(PYTHON), "-B", "-m", "py_compile", *compile_files],
        cwd=ROOT,
        env=active_environment(),
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if compiled.returncode:
        raise RuntimeError(compiled.stdout + compiled.stderr)
    gates = (
        (
            [
                str(PYTHON),
                "-I",
                "-S",
                "-B",
                "scripts/verify_onyx_live_activation_v7_acceptance.py",
            ],
            "ONYX_LIVE_ACTIVATION_V7_ACCEPTANCE_OK",
        ),
        (
            [str(PYTHON), "-B", "scripts/verify_onyx_live_activation_v8_host.py"],
            "ONYX_LIVE_ACTIVATION_V8_SHORTCUT_OK",
        ),
        (
            [
                str(PYTHON),
                "-B",
                "scripts/bootstrap_onyx_live_v8.pyw",
                "--preflight-only",
            ],
            "ONYX_LIVE_V8_HOST_PREFLIGHT_OK",
        ),
        (
            [
                str(PYTHON),
                "-B",
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                ".pytest-onyx-v8-desktop-cumulative",
                "tests/test_desktop_shortcut.py",
            ],
            "4 passed",
        ),
    )
    for command, marker in gates:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=active_environment(),
            text=True,
            capture_output=True,
            timeout=600,
            check=False,
        )
        if result.returncode or marker not in result.stdout:
            raise RuntimeError(result.stdout + result.stderr)
    print("ONYX_LIVE_ACTIVATION_V8_CUMULATIVE_OK")
    print(
        "v7_acceptance=exact shortcut_gate=pass desktop_legacy=4/4 "
        "bootstrap_mode=active hud=v5 seams=24 rollback=post-v7-exact "
        "network_calls=0 live_activation=not_performed"
    )


if __name__ == "__main__":
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    run()
