from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from core import onyx_live_activation_v10 as live


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/onyx/checkpoints/onyx-live-activation-v10/manifest.json"
EXPECTED_MANIFEST = "b22459a5315370f179089cf67d501a687305c2147d2c68ef132575326d47e236"
EXPECTED_ROOT = "5f1b32f01fe7a481f27062b90e5cbbf9816a7b6306547b7a0fe7ddf2a26a56c4"
PYTHON = ROOT / ".venv/Scripts/python.exe"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_p0_c003_manifest_and_26_file_root_are_exact() -> None:
    data = candidate()
    assert digest(MANIFEST) == EXPECTED_MANIFEST
    assert data["candidate"] == "onyx-live-activation-v10-c003"
    assert data["status"] == "candidate-ready-external-gate"
    assert data["default_off"] is True
    assert data["live_activated"] is False
    assert data["live_wiring"] is False
    assert data["shortcut_write_performed"] is False
    assert data["network_calls"] == 0
    assert data["planned_composition"]["total_transactional_seams"] == 35
    assert data["verification"]["focused"] == {"passed": 33, "failed": 0}
    rows = sorted(data["files"], key=lambda record: record["path"])
    assert len(rows) == 26
    for record in rows:
        assert digest(ROOT / record["path"]) == record["sha256"]
    material = "".join(
        f"{record['path']}\0{record['sha256']}\n" for record in rows
    ).encode()
    assert hashlib.sha256(material).hexdigest() == EXPECTED_ROOT


def test_p0_c002_integrity_and_exact_accepted_composition_are_preserved() -> None:
    source = (ROOT / "core/onyx_live_activation_v10.py").read_text(encoding="utf-8")
    paths = {record["path"] for record in candidate()["files"]}
    assert {
        "core/onyx_live_activation_v9.py",
        "core/onyx_hud_orb_v7.py",
        "core/phase6_live_wiring_v1.py",
        "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V9-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-HUD-ORB-V7-C003-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-P6-LIVE-WIRING-V1-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-P5-EXIT-CANDIDATE-V2-E6-001.manifest.json",
    } <= paths
    assert "_verify_hud_v7_closure(project)" in source
    assert "runpy.run_path" in source
    assert "_ROLLBACK_AUTHORITIES" in source
    assert 'cd /d "%~dp0.."' in (
        ROOT / "scripts/launch_onyx_live_v10_active.cmd"
    ).read_text(encoding="utf-8")
    for metadata in (
        "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V9-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-HUD-ORB-V7-C003-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-P6-LIVE-WIRING-V1-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-P5-EXIT-CANDIDATE-V2-E6-001.manifest.json",
    ):
        envelope = json.loads((ROOT / metadata).read_text(encoding="utf-8"))
        assert envelope["decision"] == "accepted"
        assert envelope["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}


def test_p1_secure_unknown_owner_matrix_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import credentials

    config = tmp_path / "settings.json"
    ui_module = ModuleType("external_ui_contract")
    ui_module.API_FILE = config
    status = {"configured": True}
    monkeypatch.setattr(credentials, "status", lambda: dict(status))

    def original(_instance: object) -> bool:
        return False

    for owner in ("", "Sir", "Efendim", "unknown"):
        config.write_text(
            json.dumps({"os_system": "windows", "owner_name": owner}),
            encoding="utf-8",
        )
        assert live._secure_onboarding_ready(ui_module, original, object()) is True

    status["configured"] = False
    assert live._secure_onboarding_ready(ui_module, original, object()) is False
    status["configured"] = True
    config.write_text(json.dumps({"owner_name": ""}), encoding="utf-8")
    assert live._secure_onboarding_ready(ui_module, original, object()) is False
    config.write_text(
        json.dumps({"os_system": "invalid", "owner_name": ""}),
        encoding="utf-8",
    )
    assert live._secure_onboarding_ready(ui_module, original, object()) is False
    config.write_text("{", encoding="utf-8")
    assert live._secure_onboarding_ready(ui_module, original, object()) is False


def test_p1_onboarding_rollback_ignores_public_reference_drift() -> None:
    class Window:
        pass

    def original_check(_instance: object) -> bool:
        return False

    def poison_check(_instance: object) -> bool:
        return True

    Window._check_config = poison_check
    controller = object.__new__(live.OnyxLiveActivationV10)
    controller.contract = SimpleNamespace(
        main_window=Window,
        ui_module=ModuleType("ui"),
        module=ModuleType("host"),
    )
    controller._hud_v7_module = None
    controller._wiring = None
    controller._shortcut_v9 = None
    controller._setup_v9 = None
    controller._check_config_v9 = object()
    controller._init_v9 = None
    authority = live._RollbackAuthorityV10(
        controller=controller,
        main_window=Window,
        hud_module=ModuleType("hud"),
        uninstall_hud=lambda _ui: True,
        check_config_v9=original_check,
    )
    live._ROLLBACK_AUTHORITIES[id(controller)] = authority
    with patch.dict(os.environ, live.exact_activation_environment(), clear=True):
        controller.rollback_installation()
    assert Window._check_config is original_check
    assert controller._check_config_v9 is None
    assert live.OnyxLiveActivationV10.TOTAL_SEAM_COUNT == 35


def test_p1_runtime_and_patch_order_are_bound_before_mainwindow() -> None:
    runtime = json.loads(
        (
            ROOT
            / "docs/onyx/checkpoints/onyx-live-activation-v10/runtime-manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert runtime["candidate"] == "onyx-live-activation-v10-c003"
    assert runtime["onboarding"] == {
        "secure_unknown_owner_ready": True,
        "credential_required": True,
        "valid_os_required": True,
        "unreadable_config_denied": True,
        "fallback_address": "Sir",
    }
    source = (ROOT / "core/onyx_live_activation_v10.py").read_text(encoding="utf-8")
    assert source.index("window_type._check_config = check_config") < source.index(
        "window_type.__init__ = initialize"
    )
    launcher = (ROOT / "scripts/launch_onyx_live_v10.pyw").read_text(encoding="utf-8")
    assert launcher.index("verify_activation_prerequisites") < launcher.index(
        "import main as onyx_main"
    )


def test_p2_isolated_real_host_physical_smoke_has_no_shortcut_write() -> None:
    result = subprocess.run(
        [
            str(PYTHON),
            "-I",
            "-S",
            "-B",
            "scripts/verify_onyx_live_activation_v10_c003_physical_smoke.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ONYX_LIVE_ACTIVATION_V10_C003_PHYSICAL_SMOKE_OK" in result.stdout
    assert "address=Sir" in result.stdout
    assert "contact_question=exact" in result.stdout
    assert "shortcut_writes=0" in result.stdout


def test_p2_non_windows_still_delegates_exact_v9(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = runpy.run_path(
        str(ROOT / "scripts/launch_onyx_live_v10.pyw"),
        run_name="v10_c003_e6_non_windows",
    )
    observed: list[dict[str, str]] = []
    globals_ = launcher["run"].__globals__
    monkeypatch.setitem(globals_, "_run_v9", lambda env: observed.append(dict(env)))
    monkeypatch.setattr(globals_["platform"], "system", lambda: "Linux")
    monkeypatch.setattr(sys, "argv", ["launch_onyx_live_v10.pyw"])
    with patch.dict(os.environ, live.exact_activation_environment(), clear=True):
        launcher["run"]()
    assert observed == [live.v9.exact_activation_environment()]


def test_p3_default_off_no_network_write_or_completion_overclaim() -> None:
    data = candidate()
    checkpoint = (
        ROOT / "docs/onyx/checkpoints/onyx-live-activation-v10/"
        "ONYX_LIVE_ACTIVATION_V10_CHECKPOINT.md"
    ).read_text(encoding="utf-8")
    core = (
        (ROOT / "core/onyx_live_activation_v10.py").read_text(encoding="utf-8").lower()
    )
    assert data["default_off"] is True
    assert data["live_activated"] is False
    assert data["shortcut_write_performed"] is False
    assert data["network_calls"] == 0
    for forbidden in ("requests.", "httpx.", "socket.connect", "provider_call"):
        assert forbidden not in core
    assert "physical activation, shortcut write and provider/network calls: none" in (
        checkpoint
    )
    assert "adds no user-facing\nPhase 6 route" in checkpoint
