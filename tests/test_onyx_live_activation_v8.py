from __future__ import annotations

import hashlib
import os
import runpy
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from core import onyx_live_activation_v8 as live


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v8.pyw"
BOOTSTRAP = ROOT / live.BOOTSTRAP_RELATIVE
HOST_GATE = ROOT / "scripts" / "verify_onyx_live_activation_v8_host.py"
CUMULATIVE_GATE = ROOT / "scripts" / "verify_onyx_live_activation_v8.py"


def clean_environment() -> dict[str, str]:
    result = dict(os.environ)
    for version in range(1, 9):
        result.pop(f"ONYX_LIVE_ACTIVATION_V{version}", None)
        result.pop(f"ONYX_LIVE_ROLLBACK_V{version}", None)
    for name in (*live.PHASE5_IDENTITY_FLAGS, *live.PHASE5_IDENTITY_ALIASES):
        result.pop(name, None)
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    result["QT_QPA_PLATFORM"] = "offscreen"
    result["QSG_RHI_BACKEND"] = "software"
    return result


def active_environment() -> dict[str, str]:
    result = clean_environment()
    result.update(live.exact_activation_environment())
    return result


def test_v8_launcher_truth_table_and_bootstrap_establishes_active_contract():
    mode = runpy.run_path(str(LAUNCHER), run_name="v8_launcher_test")["_launch_mode"]
    active = live.exact_activation_environment()
    assert mode({}) == "legacy"
    assert mode(active) == "active"
    assert mode(live.exact_rollback_environment()) == "rollback"
    for name in (
        live.LIVE_MASTER_FLAG,
        *live.CHILD_FLAGS,
        *live.PHASE5_IDENTITY_FLAGS,
    ):
        partial = dict(active)
        partial.pop(name)
        assert mode(partial) == "refuse"
    bootstrap = runpy.run_path(str(BOOTSTRAP), run_name="v8_bootstrap_contract_test")
    prepared = bootstrap["_bootstrap_environment"](
        {
            "PATH": "preserved",
            "ONYX_LIVE_ACTIVATION_V7": "1",
            "ONYX_LIVE_ROLLBACK_V6": "1",
            "ONYX_PRINCIPAL_ID": "alias",
        }
    )
    assert prepared == {"PATH": "preserved", **active}
    assert mode(prepared) == "active"


def test_v8_partial_environment_refuses_before_host_import():
    environment = clean_environment()
    environment[live.LIVE_MASTER_FLAG] = "1"
    result = subprocess.run(
        [str(PYTHON), "-B", str(LAUNCHER), "--preflight-only"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode != 0
    assert "ONYX_LIVE_V8_PREIMPORT_REFUSAL CLEAN" in result.stderr


def test_shortcut_bootstrap_executes_canonical_active_preflight_with_hud_v5():
    result = subprocess.run(
        [str(PYTHON), "-B", str(BOOTSTRAP), "--preflight-only"],
        cwd=ROOT,
        env=clean_environment(),
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ONYX_LIVE_V8_HOST_PREFLIGHT_OK" in result.stdout
    assert "hud=v5" in result.stdout
    assert "shortcut=bootstrap-v8" in result.stdout
    assert "network_calls=0" in result.stdout


def test_source_shortcut_rejects_missing_pythonw_target(tmp_path: Path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "bootstrap_onyx_live_v8.pyw").touch()
    (scripts / "launch_onyx_live_v8.pyw").touch()
    controller = object.__new__(live.OnyxLiveActivationV8)
    controller.contract = SimpleNamespace(
        ui_module=SimpleNamespace(__file__=str(tmp_path / "ui.py"))
    )
    instance = SimpleNamespace(_desktop_path=lambda _os: tmp_path / "Desktop")

    with pytest.raises(
        live.ActivationV8Error,
        match="canonical V8 shortcut entrypoint is unavailable",
    ):
        controller._source_shortcut_spec(instance)


def _run_gate(path: Path, marker: str, detail: str) -> None:
    result = subprocess.run(
        [str(PYTHON), "-B", str(path)],
        cwd=ROOT,
        env=active_environment(),
        text=True,
        capture_output=True,
        timeout=900,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker in result.stdout
    assert detail in result.stdout


def test_v8_shortcut_com_quoting_idempotency_failpoint_and_post_v7_rollback():
    _run_gate(
        HOST_GATE,
        "ONYX_LIVE_ACTIVATION_V8_SHORTCUT_OK",
        "rollback=post-v7-exact",
    )


def test_v8_cumulative_preserves_default_off_desktop_and_v7_acceptance():
    _run_gate(
        CUMULATIVE_GATE,
        "ONYX_LIVE_ACTIVATION_V8_CUMULATIVE_OK",
        "desktop_legacy=4/4",
    )


def test_v7_candidate_and_acceptance_bytes_are_unchanged():
    expected = {
        "core/onyx_live_activation_v7.py": "906c7c0e31cb5efc28e5357bb158545e903d65ff1f160b3899bc3e2fb3c1dc77",
        "docs/onyx/checkpoints/onyx-live-activation-v7/manifest.json": "312d6654f3423f16f4b36f435638920836994bd56c3e9a8766a086e2c6d647da",
        "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V7-E6-001.md": "8438769b1b597b0d66174db0c73d50a9577702c5957ba6ff24b55315d11aedb5",
        "scripts/verify_onyx_live_activation_v7_acceptance.py": "23fb601ffe783e3283f4ff2d446f21e55f1b049a3b2b50fbefc52f8c4dac06d9",
        "tests/test_onyx_live_activation_v7_acceptance.py": "bad81b091ae09ca41f289f9515f2d630ca1fffbd83f2913426899f4d38d746d9",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
