from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import ModuleType
from unittest.mock import patch

import pytest

from core import onyx_live_activation_v11 as live


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/onyx/checkpoints/onyx-live-activation-v11/manifest.json"
EXPECTED_MANIFEST = "95aa2e7430db568abda4835ee88648a47a4848b2170649898be39f35ddd8fe8e"
EXPECTED_ROOT = "3c196ad5a9483675264ae3f04380cd037761c04c77c2fa523fc4867a09d9d935"
PYTHON = ROOT / ".venv/Scripts/python.exe"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_p0_manifest_and_19_file_root_are_exact() -> None:
    data = candidate()
    assert digest(MANIFEST) == EXPECTED_MANIFEST
    assert data["candidate"] == "onyx-live-activation-v11-c001"
    assert data["status"] == "candidate-ready-external-gate"
    assert data["default_off"] is True
    assert data["live_activated"] is False
    assert data["shortcut_write_performed"] is False
    assert data["network_calls"] == 0
    assert data["planned_composition"]["total_transactional_seams"] == 37
    rows = sorted(data["files"], key=lambda record: record["path"])
    assert len(rows) == 19
    for record in rows:
        assert digest(ROOT / record["path"]) == record["sha256"]
    material = "".join(
        f"{record['path']}\0{record['sha256']}\n" for record in rows
    ).encode()
    assert hashlib.sha256(material).hexdigest() == EXPECTED_ROOT


def test_p0_exact_v10_and_hud_v8_acceptance_envelopes_are_bound() -> None:
    paths = {record["path"] for record in candidate()["files"]}
    expected = {
        "core/onyx_live_activation_v10.py",
        "docs/onyx/checkpoints/onyx-live-activation-v10/manifest.json",
        "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V10-C003-E6-001.md",
        "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V10-C003-E6-001.manifest.json",
        "core/onyx_hud_orb_v8.py",
        "docs/onyx/checkpoints/hud-orb-v8-candidate/manifest.json",
        "docs/onyx/acceptance/VE-HUD-ORB-V8-C001-E6-001.md",
        "docs/onyx/acceptance/VE-HUD-ORB-V8-C001-E6-001.manifest.json",
    }
    assert expected <= paths
    for metadata in (
        "docs/onyx/acceptance/"
        "VE-ONYX-LIVE-ACTIVATION-V10-C003-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-HUD-ORB-V8-C001-E6-001.manifest.json",
    ):
        envelope = json.loads((ROOT / metadata).read_text(encoding="utf-8"))
        assert envelope["decision"] == "accepted"
        assert envelope["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}


def test_p1_private_bridge_is_narrow_and_fail_closed() -> None:
    source = (ROOT / "core/onyx_live_activation_v11.py").read_text(
        encoding="utf-8"
    )
    function = source.split("def _install_accepted_hud_v8", 1)[1].split(
        "\ndef ", 1
    )[0]
    assert "record.installed_host is not host" in function
    assert "marker is not accepted_v7_module._INSTALLATION_TOKEN" in function
    assert 'host.__module__ = "core.onyx_hud_orb_v7"' in function
    assert "finally:" in function
    assert "host.__module__ = original_module" in function
    ui_module = ModuleType("ui_spoof")
    private = ModuleType("_onyx_v10_verified_hud_v7")
    private._ACTIVE_INSTALLATIONS = {}
    private._INSTALLATION_TOKEN = object()
    ui_module._ONYX_HUD_V7_INSTALLATION = private._INSTALLATION_TOKEN
    ui_module._CinematicHudV5Host = type("Spoof", (), {})
    with pytest.raises(live.ActivationV11Error, match="bridge authentication"):
        live._install_accepted_hud_v8(ui_module, private, lambda _ui: True)


def test_p1_runtime_and_preimport_order_are_bound() -> None:
    runtime = json.loads(
        (
            ROOT
            / "docs/onyx/checkpoints/onyx-live-activation-v11/"
            "runtime-manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert runtime["candidate"] == "onyx-live-activation-v11-c001"
    assert set(runtime["files"]) == {"pythonw", "bootstrap", "launcher"}
    launcher = (ROOT / "scripts/launch_onyx_live_v11.pyw").read_text(
        encoding="utf-8"
    )
    assert launcher.index("verify_activation_prerequisites") < launcher.index(
        "import main as onyx_main"
    )
    assert 'cd /d "%~dp0.."' in (
        ROOT / "scripts/launch_onyx_live_v11_active.cmd"
    ).read_text(encoding="utf-8")


def test_p2_isolated_real_host_smoke_has_no_shortcut_or_provider_call() -> None:
    result = subprocess.run(
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
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ONYX_LIVE_ACTIVATION_V11_C001_PHYSICAL_SMOKE_OK" in result.stdout
    assert "root=onyxLiveShellV8Root" in result.stdout
    assert "speaking_phase=advanced idle_phase=zero" in result.stdout
    assert "shortcut_writes=0 provider_calls=0" in result.stdout


def test_p2_non_windows_delegates_exact_v10(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = runpy.run_path(
        str(ROOT / "scripts/launch_onyx_live_v11.pyw"),
        run_name="v11_c001_e6_non_windows",
    )
    observed: list[dict[str, str]] = []
    globals_ = launcher["run"].__globals__
    monkeypatch.setitem(globals_, "_run_v10", lambda env: observed.append(dict(env)))
    monkeypatch.setattr(globals_["platform"], "system", lambda: "Linux")
    monkeypatch.setattr(sys, "argv", ["launch_onyx_live_v11.pyw"])
    with patch.dict(os.environ, live.exact_activation_environment(), clear=True):
        launcher["run"]()
    assert observed == [live.v10.exact_activation_environment()]


def test_p3_activation_changes_only_hud_and_shortcut_seams() -> None:
    source = (ROOT / "core/onyx_live_activation_v11.py").read_text(
        encoding="utf-8"
    )
    assert "V11_SEAM_COUNT = 2" in source
    assert "TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V11_SEAM_COUNT" in source
    for forbidden in (
        "_execute_tool =",
        "_run_live_loop =",
        "_send_realtime =",
        "requests.",
        "httpx.",
        "socket.connect",
    ):
        assert forbidden not in source
    assert "rollback_state" not in source


def test_p3_default_off_checkpoint_has_no_completion_overclaim() -> None:
    data = candidate()
    checkpoint = (
        ROOT
        / "docs/onyx/checkpoints/onyx-live-activation-v11/"
        "ONYX_LIVE_ACTIVATION_V11_CHECKPOINT.md"
    ).read_text(encoding="utf-8")
    assert data["default_off"] is True and data["live_activated"] is False
    assert data["shortcut_write_performed"] is False
    assert "live activation, shortcut write and provider calls: none" in checkpoint
    assert "does not claim" in checkpoint

