"""Verify the default-off Activation V11 C001 composition candidate."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv/Scripts/python.exe"
MANIFEST = ROOT / "docs/onyx/checkpoints/onyx-live-activation-v11/manifest.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_gate(
    arguments: list[str],
    *,
    prefix: str,
    expected: str,
    timeout: int = 300,
) -> str:
    base_temp = Path(tempfile.mkdtemp(prefix=prefix, dir=ROOT))
    command = list(arguments)
    if "--basetemp" in command:
        command[command.index("--basetemp") + 1] = str(base_temp)
    try:
        result = subprocess.run(
            [str(PYTHON), "-B", *command],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    finally:
        shutil.rmtree(base_temp, ignore_errors=True)
    if result.returncode or expected not in result.stdout:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout


def verify() -> dict[str, object]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema"] == "onyx.live-activation.v11"
    assert data["candidate"] == "onyx-live-activation-v11-c001"
    assert data["status"] == "candidate-ready-external-gate"
    assert data["default_off"] is True
    assert data["live_activated"] is False
    assert data["shortcut_write_performed"] is False
    assert data["network_calls"] == 0
    rows = sorted(data["files"], key=lambda item: item["path"])
    assert len(rows) == 19
    for item in rows:
        assert digest(ROOT / item["path"]) == item["sha256"]
    material = "".join(
        f"{item['path']}\0{item['sha256']}\n" for item in rows
    ).encode()
    root = hashlib.sha256(material).hexdigest()
    assert root == data["artifact_root_sha256"]
    assert data["planned_composition"] == {
        "predecessor": "accepted-v10-c003-e6-exact",
        "hud": "accepted-hud-orb-v8-c001-e6-exact",
        "new_transactional_seams": 2,
        "total_transactional_seams": 37,
        "rollback_state": "exact-installed-v10",
        "macos_linux": "delegate-exact-v10",
    }

    run_gate(
        [
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            "unused",
            "tests/test_onyx_live_activation_v11.py",
        ],
        prefix=".pytest-onyx-live-v11-verifier-",
        expected="18 passed",
    )
    run_gate(
        [
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            "unused",
            "tests/test_onyx_live_activation_v10.py",
        ],
        prefix=".pytest-onyx-live-v11-v10-",
        expected="33 passed",
    )
    run_gate(
        [
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            "unused",
            "tests/test_onyx_hud_orb_v8_candidate.py",
        ],
        prefix=".pytest-onyx-live-v11-hud-",
        expected="7 passed",
    )
    smoke = subprocess.run(
        [
            str(PYTHON),
            "-I",
            "-S",
            "-B",
            "scripts/verify_onyx_live_activation_v11_c001_physical_smoke.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    if (
        smoke.returncode
        or "ONYX_LIVE_ACTIVATION_V11_C001_PHYSICAL_SMOKE_OK"
        not in smoke.stdout
    ):
        raise RuntimeError(smoke.stdout + smoke.stderr)
    preflight = subprocess.run(
        [
            str(PYTHON),
            "-B",
            "scripts/bootstrap_onyx_live_v11.pyw",
            "--preflight-only",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if preflight.returncode or "ONYX_LIVE_V11_HOST_PREFLIGHT_OK" not in (
        preflight.stdout
    ):
        raise RuntimeError(preflight.stdout + preflight.stderr)
    return {
        "files": len(rows),
        "root": root,
        "focused": 18,
        "v10_regression": 33,
        "hud_v8": 7,
        "physical_smoke": True,
        "live": False,
    }


if __name__ == "__main__":
    print(
        "ONYX_LIVE_ACTIVATION_V11_C001_CANDIDATE_OK",
        json.dumps(verify(), sort_keys=True),
    )
