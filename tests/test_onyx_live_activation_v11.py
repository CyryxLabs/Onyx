from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
from types import ModuleType
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core import onyx_live_activation_v11 as live


ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def active_environment() -> dict[str, str]:
    result = dict(os.environ)
    for name in live.CONTROL_FLAGS:
        result.pop(name, None)
    result.update(live.exact_activation_environment())
    return result


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (live.LIVE_MASTER_FLAG, "0"),
        (live.LIVE_MASTER_FLAG, "true"),
        (live.LIVE_MASTER_FLAG, "1 "),
        (live.HUD_V8_FLAG, "0"),
        (live.HUD_V8_FLAG, "true"),
        (live.HUD_V8_FLAG, " 1"),
    ],
)
def test_v11_exact_flags_reject_near_matches(name: str, value: str) -> None:
    environment = live.exact_activation_environment()
    environment[name] = value
    with pytest.raises(live.ActivationV11Error):
        live.ActivationFlagsV11.from_canonical_environ(environment)


def test_v11_exact_environment_and_rollback_contract() -> None:
    environment = live.exact_activation_environment()
    flags = live.ActivationFlagsV11.from_canonical_environ(environment)
    assert flags.master is True and flags.hud_v8 is True
    assert environment[live.LIVE_MASTER_FLAG] == "1"
    assert environment[live.HUD_V8_FLAG] == "1"
    assert environment[live.v10.LIVE_MASTER_FLAG] == "1"
    assert live.exact_rollback_environment() == {live.LIVE_ROLLBACK_FLAG: "1"}
    restored = live.restore_v10_environment(environment)
    assert live.LIVE_MASTER_FLAG not in restored
    assert live.HUD_V8_FLAG not in restored
    assert restored[live.v10.LIVE_MASTER_FLAG] == "1"


def test_runtime_bundle_and_accepted_envelopes_are_exact() -> None:
    verified = live._verify_runtime_bundle(ROOT)
    assert set(verified) == {"pythonw", "bootstrap", "launcher"}
    live._verify_accepted_roots(ROOT)
    for relative, expected in (
        *live.V10_ACCEPTED_ROOTS,
        *live.HUD_V8_ACCEPTED_ROOTS,
    ):
        assert digest(ROOT / relative) == expected


def test_hud_v8_closure_detects_leaf_tamper(tmp_path: Path) -> None:
    candidate = json.loads(
        (
            ROOT / "docs/onyx/checkpoints/hud-orb-v8-candidate/manifest.json"
        ).read_text(encoding="utf-8")
    )
    paths = {
        *(path for path, _expected in live.V10_ACCEPTED_ROOTS),
        *(path for path, _expected in live.HUD_V8_ACCEPTED_ROOTS),
        *(Path(item["path"]) for item in candidate["artifacts"]),
        *(Path(path) for path in candidate["frozen_anchors"]),
    }
    for relative in paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    target = tmp_path / "qml/components/OnyxOrbVoiceLayerV8.qml"
    target.write_bytes(target.read_bytes() + b"\ntamper")
    with pytest.raises(live.ActivationV11Error, match="evidence drift"):
        live._verify_accepted_roots(tmp_path)


def test_bootstrap_clears_conflicting_controls_and_launcher_modes() -> None:
    bootstrap = runpy.run_path(
        str(ROOT / "scripts/bootstrap_onyx_live_v11.pyw"),
        run_name="_test_bootstrap_v11",
    )
    prepared = bootstrap["_bootstrap_environment"](
        {
            "PATH": "preserved",
            live.LIVE_ROLLBACK_FLAG: "1",
            live.v10.LIVE_ROLLBACK_FLAG: "1",
            live.HUD_V8_FLAG: "true",
        }
    )
    assert prepared["PATH"] == "preserved"
    assert {name: prepared[name] for name in live.exact_activation_environment()} == (
        live.exact_activation_environment()
    )
    assert live.LIVE_ROLLBACK_FLAG not in prepared

    launcher = runpy.run_path(
        str(ROOT / "scripts/launch_onyx_live_v11.pyw"),
        run_name="_test_launcher_v11",
    )
    assert launcher["_launch_mode"]({}) == "legacy"
    assert (
        launcher["_launch_mode"](live.exact_activation_environment()) == "active"
    )
    assert (
        launcher["_launch_mode"]({live.LIVE_ROLLBACK_FLAG: "1"}) == "rollback"
    )
    assert launcher["_launch_mode"]({live.LIVE_MASTER_FLAG: "1"}) == "refuse"


def test_preflight_is_clean_and_preserves_accepted_v10() -> None:
    environment = active_environment()
    with patch.dict(os.environ, environment, clear=True):
        import main

        contract = live.preflight_host(main, environment)
        assert contract.project == ROOT
        assert contract.base.project == ROOT
        assert "ui" in sys.modules
    assert digest(ROOT / "core/onyx_live_activation_v10.py") == (
        "36c5710f7bf651b3412cccfb3ddc6586607df1e528acfe19021393c2ecfe1201"
    )


def test_real_v11_composes_one_v8_renderer_and_rolls_back_exactly() -> None:
    environment = active_environment()
    with patch.dict(os.environ, environment, clear=True):
        import main
        import ui

        app = QApplication.instance() or QApplication([])
        contract = live.preflight_host(main, environment)
        controller = live.OnyxLiveActivationV11(
            live.ActivationFlagsV11.from_canonical_environ(environment),
            contract,
        )
        try:
            controller.install()
            v8_host = ui._CinematicHudV5Host
            assert v8_host.__module__ == "_onyx_v11_verified_hud_v8"
            assert controller._base._hud_v7_module.__name__ == (
                "_onyx_v10_verified_hud_v7"
            )
            assert (
                controller._base._hud_v7_module._ACTIVE_INSTALLATIONS[
                    id(ui)
                ].installed_host.__module__
                == "_onyx_v10_verified_hud_v7"
            )
            window = ui.MainWindow("")
            window.resize(1000, 700)
            window.show()
            QTest.qWait(250)
            app.processEvents()
            try:
                assert window.hud.renderer_mode == "qml-v8-voice-reactive"
                root = window._v5_host._quick.rootObject()
                assert root.objectName() == "onyxLiveShellV8Root"
                voice = root.findChild(QQuickItem, "onyxOrbVoiceLayerV8")
                assert voice is not None
                widgets = [
                    widget
                    for widget in QApplication.allWidgets()
                    if isinstance(widget, QQuickWidget)
                ]
                assert widgets == [window._v5_host._quick]
                window.hud.set_operational_state("SPEAKING")
                QTest.qWait(250)
                app.processEvents()
                assert float(voice.property("phase")) > 0
                window.hud.set_operational_state("LISTENING")
                QTest.qWait(150)
                app.processEvents()
                assert float(voice.property("phase")) == 0
            finally:
                window.close()
                window.deleteLater()
                for _ in range(5):
                    app.processEvents()
            controller.rollback_installation()
            assert ui._CinematicHudV5Host is not v8_host
            assert ui._CinematicHudV5Host.__module__ == (
                "_onyx_v10_verified_hud_v7"
            )
        finally:
            controller.rollback_all()


@pytest.mark.parametrize("offset", [1, 2])
def test_each_v11_failpoint_restores_exact_v10(offset: int) -> None:
    environment = active_environment()
    with patch.dict(os.environ, environment, clear=True):
        import main
        import ui

        controller = live.OnyxLiveActivationV11(
            live.ActivationFlagsV11.from_canonical_environ(environment),
            live.preflight_host(main, environment),
        )
        try:
            with pytest.raises(live.ActivationV11Error, match="injected V11"):
                controller.install(fail_after=controller.BASE_SEAM_COUNT + offset)
            assert controller._hud_v8_module is None
            assert controller._shortcut_v10 is None
            assert id(controller) not in live._ROLLBACK_AUTHORITIES
            assert ui._CinematicHudV5Host.__module__ == (
                "_onyx_v10_verified_hud_v7"
            )
            assert live.LIVE_MASTER_FLAG not in os.environ
            assert os.environ[live.v10.LIVE_MASTER_FLAG] == "1"
        finally:
            controller.rollback_all()


def test_private_v7_bridge_rejects_spoof_before_aliasing() -> None:
    ui_module = ModuleType("ui_spoof")
    accepted_v7 = ModuleType("_onyx_v10_verified_hud_v7")
    accepted_v7._ACTIVE_INSTALLATIONS = {}
    accepted_v7._INSTALLATION_TOKEN = object()
    ui_module._ONYX_HUD_V7_INSTALLATION = accepted_v7._INSTALLATION_TOKEN
    ui_module._CinematicHudV5Host = type("Spoof", (), {})
    called: list[object] = []

    def install(value: object) -> bool:
        called.append(value)
        return True

    with pytest.raises(live.ActivationV11Error, match="bridge authentication"):
        live._install_accepted_hud_v8(ui_module, accepted_v7, install)
    assert called == []


def test_shortcut_spec_targets_only_verified_v11_bootstrap() -> None:
    spec = live.ShortcutSpecV11(
        link="C:/Users/Test/Desktop/Onyx.lnk",
        target=str(ROOT / ".venv/Scripts/pythonw.exe"),
        arguments=str(ROOT / live.BOOTSTRAP_RELATIVE),
        working_directory=str(ROOT),
        icon=str(ROOT / "config/onyx.ico"),
    )
    assert Path(spec.arguments).name == "bootstrap_onyx_live_v11.pyw"
    with pytest.raises(live.ActivationV11Error):
        live.ShortcutSpecV11(
            link=spec.link,
            target=spec.target,
            arguments=str(ROOT / "scripts/bootstrap_onyx_live_v10.pyw"),
            working_directory=spec.working_directory,
            icon=spec.icon,
        )


def test_canonical_preflight_subprocess_imports_no_live_window() -> None:
    result = subprocess.run(
        [
            str(ROOT / ".venv/Scripts/python.exe"),
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
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ONYX_LIVE_V11_HOST_PREFLIGHT_OK" in result.stdout
    assert "hud=v8" in result.stdout
    assert "network_calls=0" in result.stdout


def test_v11_does_not_modify_v10_or_hud_v8_accepted_bytes() -> None:
    expected = {
        **{path.as_posix(): value for path, value in live.V10_ACCEPTED_ROOTS},
        **{path.as_posix(): value for path, value in live.HUD_V8_ACCEPTED_ROOTS},
    }
    for relative, value in expected.items():
        assert digest(ROOT / relative) == value
    source = (ROOT / "core/onyx_live_activation_v11.py").read_text(
        encoding="utf-8"
    )
    assert "OnyxLiveActivationV10" in source
    assert "qml-v8-voice-reactive" not in source
    assert "subprocess" not in source
