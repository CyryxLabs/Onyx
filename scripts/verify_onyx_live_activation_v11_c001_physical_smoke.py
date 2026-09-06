"""Run the isolated real-host smoke for Activation V11 C001."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv/Scripts/python.exe"


def run() -> None:
    base_temp = Path(
        tempfile.mkdtemp(prefix=".pytest-onyx-live-v11-c001-smoke-", dir=ROOT)
    )
    try:
        result = subprocess.run(
            [
                str(PYTHON),
                "-B",
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                str(base_temp),
                "tests/test_onyx_live_activation_v11.py",
                "-k",
                "test_real_v11_composes_one_v8_renderer_and_rolls_back_exactly",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    finally:
        shutil.rmtree(base_temp, ignore_errors=True)
    if result.returncode or "1 passed" not in result.stdout:
        raise RuntimeError(result.stdout + result.stderr)
    print("ONYX_LIVE_ACTIVATION_V11_C001_PHYSICAL_SMOKE_OK")
    print(
        "real_host=constructed root=onyxLiveShellV8Root "
        "renderer=qml-v8-voice-reactive quick_widgets=1 "
        "speaking_phase=advanced idle_phase=zero "
        "rollback=exact-v10 shortcut_writes=0 provider_calls=0"
    )


if __name__ == "__main__":
    run()
