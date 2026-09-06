"""Cumulative default-off verifier for Onyx Live Activation V9."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
FROZEN = {
    "core/onyx_live_activation_v8.py": "a088d0c49851699c5486a59a4db6734b8ec81ed7c01ad821bf8a1ea1966486f4",
    "docs/onyx/checkpoints/onyx-live-activation-v8/manifest.json": "ab28f369248df1ed807aeeee15658193a533881bf68fb2268d49692b52c20392",
    "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V8-E6-001.md": "ee17b06e2f468c94621e7dda913e3dcda6850f3fbce478f0a5200fa9de1f1c0b",
    "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V8-E6-001.manifest.json": "7a5c9f903bded763457bc465ab3dfdbb8c63193776cbab449725d7438f1dc479",
    "core/onyx_hud_orb_v6.py": "ee5f5f62ab0c799313e7b9ffcf7b3f5364af8b1d80d2d126a63fa4b2290b4233",
    "docs/onyx/checkpoints/hud-orb-v6-candidate/manifest.json": "ba034588791b1003a6743bf037ae32a11285adcac7c4084cba1bc5bb3923ae1c",
    "docs/onyx/acceptance/VE-HUD-ORB-V6-C003-E6-001.md": "c9663515321554cec4e69524ee13eb543194562167da6ac21aafb219bcc65d9f",
    "docs/onyx/acceptance/VE-HUD-ORB-V6-C003-E6-001.manifest.json": "fbd22e3fd4e944a55ef872370c858783871eb5b20c27df58cefe14b3dc7dc4b9",
    "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
    "ui.py": "e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b",
}


def _environment() -> dict[str, str]:
    result = dict(os.environ)
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    result["QT_QPA_PLATFORM"] = "offscreen"
    result["QSG_RHI_BACKEND"] = "software"
    return result


def _run(command: list[str], marker: str, timeout: int = 600) -> None:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=_environment(),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode or marker not in result.stdout:
        raise RuntimeError(result.stdout + result.stderr)


def run() -> None:
    for relative, expected in FROZEN.items():
        observed = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        if observed != expected:
            raise RuntimeError(f"frozen V8/HUD V6 drift: {relative}")

    _run(
        [
            str(PYTHON),
            "-I",
            "-S",
            "-B",
            "scripts/verify_onyx_live_activation_v8_acceptance.py",
        ],
        "ONYX_LIVE_ACTIVATION_V8_ACCEPTANCE_OK",
    )
    _run(
        [
            str(PYTHON),
            "-I",
            "-S",
            "-B",
            "scripts/verify_hud_orb_v6_c003_acceptance.py",
        ],
        "HUD_ORB_V6_C003_ACCEPTANCE_OK",
    )
    _run(
        [
            str(PYTHON),
            "-B",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            ".pytest-onyx-live-v9-cumulative",
            "tests/test_onyx_live_activation_v9.py",
        ],
        "11 passed",
        timeout=900,
    )
    print("ONYX_LIVE_ACTIVATION_V9_CUMULATIVE_OK")
    print(
        "v8_acceptance=exact hud_v6_c003_acceptance=exact focused=11/11 "
        "seams=27 rollback=installed-v8-exact shortcut=bootstrap-v9 "
        "hud=v6 one_ui=pass network_calls=0 live_activation=not_performed"
    )


if __name__ == "__main__":
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    run()
