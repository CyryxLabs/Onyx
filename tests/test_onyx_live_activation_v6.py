from __future__ import annotations

import hashlib
import os
import runpy
import subprocess
from pathlib import Path

from core import onyx_live_activation_v6 as live


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v6.pyw"
HOST_GATE = ROOT / "scripts" / "verify_onyx_live_activation_v6_host.py"
PROVIDER_GATE = ROOT / "scripts" / "verify_onyx_live_activation_v6_provider.py"
QT_GATE = ROOT / "scripts" / "verify_onyx_live_activation_v6_qt.py"


def clean_environment():
    result = dict(os.environ)
    for version in range(4, 7):
        result.pop(f"ONYX_LIVE_ACTIVATION_V{version}", None)
        result.pop(f"ONYX_LIVE_ROLLBACK_V{version}", None)
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    result["QT_QPA_PLATFORM"] = "offscreen"
    result["QSG_RHI_BACKEND"] = "software"
    return result


def active_environment():
    result = clean_environment()
    result.update(live.exact_activation_environment())
    return result


def test_v6_launcher_truth_table_and_clean_preimport_refusal():
    mode = runpy.run_path(str(LAUNCHER), run_name="v6_launcher_test")["_launch_mode"]
    assert mode({}) == "legacy"
    assert mode(live.exact_activation_environment()) == "active"
    assert mode(live.exact_rollback_environment()) == "rollback"
    for name in (live.LIVE_MASTER_FLAG, *live.CHILD_FLAGS):
        partial = live.exact_activation_environment()
        partial.pop(name)
        assert mode(partial) == "refuse"
    env = clean_environment()
    env[live.LIVE_MASTER_FLAG] = "true"
    result = subprocess.run(
        [str(PYTHON), "-B", str(LAUNCHER), "--preflight-only"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )
    assert result.returncode != 0
    assert "ONYX_LIVE_V6_PREIMPORT_REFUSAL CLEAN" in result.stderr


def test_v6_actual_host_preflight_without_provisioning():
    result = subprocess.run(
        [str(PYTHON), "-B", str(LAUNCHER), "--preflight-only"],
        cwd=ROOT,
        env=active_environment(),
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ONYX_LIVE_V6_HOST_PREFLIGHT_OK" in result.stdout


def run_gate(path: Path, marker: str, detail: str):
    result = subprocess.run(
        [str(PYTHON), "-B", str(path)],
        cwd=ROOT,
        env=active_environment(),
        text=True,
        capture_output=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert marker in result.stdout
    assert detail in result.stdout


def test_v6_host_identity_window_numeric_threading_and_rollback():
    run_gate(
        HOST_GATE,
        "ONYX_LIVE_ACTIVATION_V6_REAL_HOST_OK",
        "ids_tested=1000",
    )


def test_v6_fake_provider_1007_1011_recovery_and_stability():
    run_gate(
        PROVIDER_GATE,
        "ONYX_LIVE_ACTIVATION_V6_FAKE_PROVIDER_OK",
        "simulated_seconds=601",
    )


def test_v6_real_qt_retains_one_setup_surface():
    run_gate(QT_GATE, "ONYX_LIVE_ACTIVATION_V6_QT_OK", "setup_surfaces=1")


def test_v5_and_frozen_host_bytes_are_unchanged():
    expected = {
        "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
        "ui.py": "e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b",
        "core/onyx_live_activation_v4.py": "2521b5dcf53172e73e23219e9266037f7312a233ef135281a1a2ac3660aec05b",
        "core/onyx_live_activation_v5.py": "5c110ae3af5172ba5de5f1f6711a214f24bbaee30b9ea33b863272a83a36bba6",
        "scripts/launch_onyx_live_v5.pyw": "1b468782ad6d1784eaaad5e188a63a84ff00e52505ef1602cca01c6b320c98a1",
        "scripts/launch_onyx_live_v5_active.cmd": "b0b897aa345e7776ac48f2a7adf81c5f6fd98597ff3f6e1faeccfa658c2ca1a1",
        "scripts/launch_onyx_live_v5_rollback.cmd": "51e332ba23c55248c3992b8e516abb6d36207a58e98fd5a0585be2b745ed522d",
        "scripts/verify_onyx_live_activation_v5.py": "84031b50fc16779b9c7690d1080e56cb16f8d327f83ac8c4a0368bbd772d25a3",
        "scripts/verify_onyx_live_activation_v5_manifest.py": "0fa5eac369b1acf3f3f12d4b1fe8aab4e7180331c2d898daf6cf1341a5d53602",
        "scripts/verify_onyx_live_activation_v5_host.py": "13abfbc24771d551f37c6a30276823854bbf2ccdcb262fa8294c5f9100a660e6",
        "scripts/verify_onyx_live_activation_v5_provider.py": "9385dc07fb2b4dc8df2898a9efa1f32de9969e9172b8f2edfc77d662c85cfa65",
        "scripts/verify_onyx_live_activation_v5_qt.py": "f816e1c90fcae9295191bc02e99e52770e2b874947232dd6d8fc987ac9410105",
        "tests/test_onyx_live_activation_v5.py": "7fdf6b5dcdf122b351bf5f77c25bfa3784fd8de38876c6790e31719316f2bf64",
        "docs/onyx/checkpoints/onyx-live-activation-v5/ONYX_LIVE_ACTIVATION_V5_CHECKPOINT.md": "e5873466d08df0c27d81768188bf04853abc063c39aae4ed2845a34f9ef9b929",
        "docs/onyx/checkpoints/onyx-live-activation-v5/manifest.json": "c303807772bad3bab16ff6b86c5ab9ec74caa55aa2c33669866cb9a93e898015",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest

