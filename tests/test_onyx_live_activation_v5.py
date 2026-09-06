from __future__ import annotations

import hashlib
import os
import runpy
import subprocess
from pathlib import Path

from core import onyx_live_activation_v5 as live


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v5.pyw"
HOST_GATE = ROOT / "scripts" / "verify_onyx_live_activation_v5_host.py"
PROVIDER_GATE = ROOT / "scripts" / "verify_onyx_live_activation_v5_provider.py"
QT_GATE = ROOT / "scripts" / "verify_onyx_live_activation_v5_qt.py"


def clean_environment():
    result = dict(os.environ)
    for name in (*live.CONTROL_FLAGS, "ONYX_LIVE_ACTIVATION_V4", "ONYX_LIVE_ROLLBACK_V4"):
        result.pop(name, None)
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    result["QT_QPA_PLATFORM"] = "offscreen"
    result["QSG_RHI_BACKEND"] = "software"
    return result


def active_environment():
    result = clean_environment()
    result.update(live.exact_activation_environment())
    return result


def test_v5_launcher_truth_table_and_clean_preimport_refusal():
    mode = runpy.run_path(str(LAUNCHER), run_name="v5_launcher_test")["_launch_mode"]
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
    assert "ONYX_LIVE_V5_PREIMPORT_REFUSAL CLEAN" in result.stderr


def test_v5_actual_host_preflight_without_provisioning():
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
    assert "ONYX_LIVE_V5_HOST_PREFLIGHT_OK" in result.stdout


def run_gate(path: Path, marker: str, detail: str):
    result = subprocess.run(
        [str(PYTHON), "-B", str(path)],
        cwd=ROOT,
        env=active_environment(),
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert marker in result.stdout
    assert detail in result.stdout


def test_v5_real_host_failpoints_mime_faults_replay_and_rollback():
    run_gate(HOST_GATE, "ONYX_LIVE_ACTIVATION_V5_REAL_HOST_OK", "seam_failpoints=18")


def test_v5_fake_provider_1007_recovery_and_accelerated_stability():
    run_gate(
        PROVIDER_GATE,
        "ONYX_LIVE_ACTIVATION_V5_FAKE_PROVIDER_OK",
        "simulated_seconds=601",
    )


def test_v5_real_qt_has_one_setup_surface_and_resumes_hud():
    run_gate(QT_GATE, "ONYX_LIVE_ACTIVATION_V5_QT_OK", "setup_surfaces=1")


def test_accepted_v4_and_host_bytes_are_unchanged():
    expected = {
        "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
        "ui.py": "e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b",
        "core/onyx_live_activation_v4.py": "2521b5dcf53172e73e23219e9266037f7312a233ef135281a1a2ac3660aec05b",
        "scripts/launch_onyx_live_v4.pyw": "a7bfc190cb95d49e871fcd312f32badbd1a5a6d18393ca725d214f1f66769af8",
        "scripts/verify_onyx_live_activation_v4.py": "20426a7fd2e592dfa54b2a352928a941e01bd7798314bb3d21363a9c0e6bd597",
        "scripts/verify_onyx_live_activation_v4_host.py": "e1e53cee11d1fbaf460d8690f9131da56c9773e75ffbd286345395c969fe2105",
        "scripts/verify_onyx_live_activation_v4_qt.py": "19015ebf96a32e449709831d86d90465e612ba63f770bea917f01dd21ab3b95b",
        "tests/test_onyx_live_activation_v4.py": "4c776af560a7f3bfd470bef91d205fddbe509c6c767cbaad2b754f3023068783",
        "docs/onyx/checkpoints/onyx-live-activation-v4/ONYX_LIVE_ACTIVATION_V4_CHECKPOINT.md": "3ea17bf227025f7dbe2ce4f91e15801151c6262efc01173657e7c3ce481d638f",
        "docs/onyx/checkpoints/onyx-live-activation-v4/manifest.json": "ebe3b24e641d1148e3ddb3767705b593a0d9df0898ba2654b53cd7820e0d6c09",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest

