from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import FunctionType, ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from core import onyx_live_activation_v10 as live


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/onyx/checkpoints/onyx-live-activation-v10/manifest.json"
EXPECTED_MANIFEST = "208897c07a24d6fe9e22636cfa42ce5772b17e95fac18e86d9fdbc993b34720e"
EXPECTED_ROOT = "f42994deaea77f64f4a8870fb397f09790effbb24195ee8dcd7b074ac8e7dcc1"
PYTHON = ROOT / ".venv/Scripts/python.exe"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate() -> dict[str, object]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_p0_candidate_manifest_and_25_file_root_are_exact() -> None:
    data = candidate()
    assert digest(MANIFEST) == EXPECTED_MANIFEST
    assert data["candidate"] == "onyx-live-activation-v10-c002"
    assert data["status"] == "candidate-ready-external-gate"
    assert data["default_off"] is True
    assert data["live_activated"] is False
    assert data["live_wiring"] is False
    assert data["shortcut_write_performed"] is False
    assert data["network_calls"] == 0
    assert data["planned_composition"]["total_transactional_seams"] == 34
    assert data["verification"]["focused"] == {"passed": 29, "failed": 0}
    rows = sorted(data["files"], key=lambda record: record["path"])
    assert len(rows) == 25
    for record in rows:
        assert digest(ROOT / record["path"]) == record["sha256"]
    material = "".join(
        f"{record['path']}\0{record['sha256']}\n" for record in rows
    ).encode()
    assert hashlib.sha256(material).hexdigest() == EXPECTED_ROOT


def test_p0_exact_v9_hud_wiring_and_phase5_e6_membership() -> None:
    paths = {record["path"] for record in candidate()["files"]}
    closures = {
        "v9": {
            "core/onyx_live_activation_v9.py",
            "docs/onyx/checkpoints/onyx-live-activation-v9/manifest.json",
            "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V9-E6-001.md",
            "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V9-E6-001.manifest.json",
        },
        "hud": {
            "core/onyx_hud_orb_v7.py",
            "docs/onyx/checkpoints/hud-orb-v7-candidate/manifest.json",
            "docs/onyx/acceptance/VE-HUD-ORB-V7-C003-E6-001.md",
            "docs/onyx/acceptance/VE-HUD-ORB-V7-C003-E6-001.manifest.json",
        },
        "wiring": {
            "core/phase6_live_wiring_v1.py",
            "docs/onyx/checkpoints/phase6-live-wiring-v1/manifest.json",
            "docs/onyx/acceptance/VE-P6-LIVE-WIRING-V1-E6-001.md",
            "docs/onyx/acceptance/VE-P6-LIVE-WIRING-V1-E6-001.manifest.json",
        },
        "phase5": {
            "docs/onyx/checkpoints/phase5-exit-candidate-v2/manifest.json",
            "docs/onyx/acceptance/VE-P5-EXIT-CANDIDATE-V2-E6-001.md",
            "docs/onyx/acceptance/VE-P5-EXIT-CANDIDATE-V2-E6-001.manifest.json",
        },
    }
    assert all(values <= paths for values in closures.values())
    for metadata in (
        "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V9-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-HUD-ORB-V7-C003-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-P6-LIVE-WIRING-V1-E6-001.manifest.json",
        "docs/onyx/acceptance/VE-P5-EXIT-CANDIDATE-V2-E6-001.manifest.json",
    ):
        envelope = json.loads((ROOT / metadata).read_text(encoding="utf-8"))
        assert envelope["decision"] == "accepted"
        assert envelope["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}


def test_p1_real_fresh_hud_api_installs_and_rolls_back() -> None:
    script = """
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QSG_RHI_BACKEND"] = "software"
os.environ["ONYX_HUD_V6_CANDIDATE"] = "1"
os.environ["ONYX_HUD_V7_LIVE"] = "1"
import ui
from pathlib import Path
from core.onyx_hud_orb_v6 import install_candidate as install_v6
from core.onyx_hud_orb_v6 import uninstall_candidate as uninstall_v6
from core.onyx_live_activation_v10 import _load_accepted_hud_v7
assert install_v6(ui) is True
v6_host = ui._CinematicHudV5Host
module, install_hud, uninstall_hud = _load_accepted_hud_v7(Path.cwd())
assert install_hud(ui) is True
module.uninstall_candidate = lambda _ui: False
assert uninstall_hud(ui) is True
assert ui._CinematicHudV5Host is v6_host
assert uninstall_v6(ui) is True
print("REAL_HUD_V7_API_OK")
"""
    result = subprocess.run(
        [str(PYTHON), "-B", "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REAL_HUD_V7_API_OK" in result.stdout


def test_p1_private_authority_ignores_public_rollback_drift() -> None:
    calls: list[str] = []

    class Window:
        pass

    def original_init(_self: object) -> None:
        return None

    def original_setup(_self: object) -> None:
        return None

    def original_shortcut(_self: object) -> None:
        return None

    def poison_init(_self: object) -> None:
        calls.append("poison-init")

    def poison_setup(_self: object) -> None:
        calls.append("poison-setup")

    def poison_shortcut(_self: object) -> None:
        calls.append("poison-shortcut")

    Window.__init__ = poison_init
    Window._on_setup_done = poison_setup
    Window._create_desktop_shortcut = poison_shortcut

    class Wiring:
        def rollback_installation(self) -> None:
            calls.append("wiring")

    def uninstall(_ui: ModuleType) -> bool:
        calls.append("hud")
        return True

    controller = object.__new__(live.OnyxLiveActivationV10)
    controller.contract = SimpleNamespace(
        main_window=Window,
        ui_module=ModuleType("ui"),
        module=ModuleType("host"),
    )
    controller._hud_v7_module = object()
    controller._wiring = object()
    controller._shortcut_v9 = object()
    controller._setup_v9 = object()
    controller._init_v9 = object()
    authority = live._RollbackAuthorityV10(
        controller=controller,
        main_window=Window,
        hud_module=ModuleType("hud"),
        uninstall_hud=uninstall,
        wiring_controller=Wiring(),
        shortcut_v9=original_shortcut,
        setup_v9=original_setup,
        init_v9=original_init,
    )
    assert type(uninstall) is FunctionType
    live._ROLLBACK_AUTHORITIES[id(controller)] = authority
    with patch.dict(os.environ, live.exact_activation_environment(), clear=True):
        controller.rollback_installation()
        assert os.environ == live.v9.exact_activation_environment()
    assert Window.__init__ is original_init
    assert Window._on_setup_done is original_setup
    assert Window._create_desktop_shortcut is original_shortcut
    assert calls == ["wiring", "hud"]


def test_p1_preflight_is_before_main_ui_and_covers_hud_leaves() -> None:
    launcher = (ROOT / "scripts/launch_onyx_live_v10.pyw").read_text(encoding="utf-8")
    core = (ROOT / "core/onyx_live_activation_v10.py").read_text(encoding="utf-8")
    verifier = (
        ROOT / "scripts/verify_onyx_live_activation_v10_c002_acceptance.py"
    ).read_text(encoding="utf-8")
    assert launcher.index("verify_activation_prerequisites") < launcher.index(
        "import main as onyx_main"
    )
    assert "_verify_hud_v7_closure(project)" in core
    assert "HUD_V7_ARTIFACT_PATHS" in core
    assert "runpy.run_path" in core
    assert "importlib.import_module" not in core
    assert "tempfile.mkdtemp" in verifier
    assert 'prefix=".pytest-onyx-live-v10-c002-e6-"' in verifier


def test_p2_cmd_controls_resolve_project_from_arbitrary_cwd() -> None:
    for relative in (
        "scripts/launch_onyx_live_v10_active.cmd",
        "scripts/launch_onyx_live_v10_rollback.cmd",
    ):
        path = ROOT / relative
        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[:2] == ["@echo off", 'cd /d "%~dp0.."']
        assert path.parent.parent.resolve() == ROOT.resolve()


def test_p2_configured_owner_refresh_and_non_windows_v9_delegation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    owner = SimpleNamespace(
        _ready=True,
        _overlay=None,
        _create_desktop_shortcut=lambda: calls.append("shortcut"),
    )
    live._refresh_configured_shortcut(owner)
    assert calls == ["shortcut"]

    launcher = runpy.run_path(
        str(ROOT / "scripts/launch_onyx_live_v10.pyw"),
        run_name="v10_e6_non_windows",
    )
    observed: list[dict[str, str]] = []
    globals_ = launcher["run"].__globals__
    monkeypatch.setitem(globals_, "_run_v9", lambda env: observed.append(dict(env)))
    monkeypatch.setattr(globals_["platform"], "system", lambda: "Linux")
    monkeypatch.setattr(sys, "argv", ["launch_onyx_live_v10.pyw"])
    with patch.dict(os.environ, live.exact_activation_environment(), clear=True):
        launcher["run"]()
    assert observed == [live.v9.exact_activation_environment()]


def test_p3_no_network_live_write_or_phase6_exit_overclaim() -> None:
    core = (
        (ROOT / "core/onyx_live_activation_v10.py").read_text(encoding="utf-8").lower()
    )
    checkpoint = (
        ROOT / "docs/onyx/checkpoints/onyx-live-activation-v10/"
        "ONYX_LIVE_ACTIVATION_V10_CHECKPOINT.md"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "requests.",
        "httpx.",
        "socket.connect",
        "provider_call",
        "phase6_unlocked = true",
    ):
        assert forbidden not in core
    assert "physical activation, shortcut write and provider/network calls: none" in (
        checkpoint
    )
    assert "adds no user-facing\nPhase 6 route" in checkpoint
