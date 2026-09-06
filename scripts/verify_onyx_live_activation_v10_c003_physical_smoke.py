"""Run the isolated real-host smoke for Activation V10 C003 onboarding."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv/Scripts/python.exe"


def run() -> None:
    base_temp = Path(
        tempfile.mkdtemp(prefix=".pytest-onyx-live-v10-c003-smoke-", dir=ROOT)
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
                "tests/test_onyx_live_activation_v10.py",
                "-k",
                "test_real_host_unknown_owner_ready_and_denials_show_setup",
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
    print("ONYX_LIVE_ACTIVATION_V10_C003_PHYSICAL_SMOKE_OK")
    print(
        "real_host=constructed unknown_owner=ready address=Sir "
        "contact_question=exact missing_credential=setup missing_os=setup "
        "unreadable_config=setup shortcut_writes=0 live_activation=not_performed"
    )


if __name__ == "__main__":
    run()
