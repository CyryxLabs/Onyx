from __future__ import annotations

import os
from pathlib import Path
import runpy
import shutil
import subprocess
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core import onyx_live_activation_v12 as live


ROOT = Path(__file__).resolve().parents[1]


def active_environment() -> dict[str, str]:
    result = dict(os.environ)
    for name in live.CONTROL_FLAGS:
        result.pop(name, None)
    result.update(live.exact_activation_environment())
    return result


def test_v12_exact_environment_and_modes() -> None:
    environment = live.exact_activation_environment()
    flags = live.ActivationFlagsV12.from_canonical_environ(environment)
    assert flags.master is True and flags.hud_v9 is True
    assert environment[live.LIVE_MASTER_FLAG] == "1"
    assert environment[live.HUD_V9_FLAG] == "1"
    assert environment[live.v11.LIVE_MASTER_FLAG] == "1"
    restored = live.restore_v11_environment(environment)
    assert live.LIVE_MASTER_FLAG not in restored
    assert live.HUD_V9_FLAG not in restored
    assert restored[live.v11.LIVE_MASTER_FLAG] == "1"

    launcher = runpy.run_path(
        str(ROOT / "scripts/launch_onyx_live_v12.pyw"),
        run_name="_test_launcher_v12",
    )
    assert launcher["_launch_mode"]({}) == "legacy"
    assert launcher["_launch_mode"](environment) == "active"
    assert (
        launcher["_launch_mode"]({live.LIVE_ROLLBACK_FLAG: "1"}) == "rollback"
    )
    assert launcher["_launch_mode"]({live.LIVE_MASTER_FLAG: "1"}) == "refuse"


def test_v12_roots_and_host_preflight_are_exact() -> None:
    environment = active_environment()
    live._verify_v9_roots(ROOT)
    with patch.dict(os.environ, environment, clear=True):
        import main

        contract = live.preflight_host(main, environment)
        assert contract.project == ROOT
        assert contract.base.project == ROOT


def test_arbitrary_v11_code_drift_is_rejected(tmp_path: Path) -> None:
    required = {
        *(relative for relative, _digest in live.V11_ACCEPTED_ROOTS),
        *(relative for relative, _digest in live.HUD_V9_ROOTS),
        live.BOOTSTRAP_RELATIVE,
        live.CANONICAL_LAUNCHER_RELATIVE,
    }
    for relative in required:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)

    predecessor = tmp_path / live.V11_ACCEPTED_ROOTS[0][0]
    with predecessor.open("ab") as handle:
        handle.write(b"\n# arbitrary V11 code drift\n")

    with pytest.raises(live.ActivationV12Error, match="V11 predecessor drift"):
        live._verify_v9_roots(tmp_path)


def test_real_v12_removes_arcs_and_preserves_voice_layer() -> None:
    environment = active_environment()
    with patch.dict(os.environ, environment, clear=True):
        import main
        import ui

        app = QApplication.instance() or QApplication([])
        controller = live.OnyxLiveActivationV12(
            live.ActivationFlagsV12.from_canonical_environ(environment),
            live.preflight_host(main, environment),
        )
        try:
            controller.install()
            window = ui.MainWindow("")
            window.resize(1000, 700)
            window.show()
            QTest.qWait(250)
            app.processEvents()
            try:
                assert window.hud.renderer_mode == "qml-v9-arc-free"
                root = window._v5_host._quick.rootObject()
                assert root.objectName() == "onyxLiveShellV9Root"
                command = root.findChild(QQuickItem, "liveCommandInputV7")
                voice = root.findChild(QQuickItem, "onyxOrbVoiceLayerV8")
                assert command is not None and voice is not None
                canvases = [
                    child
                    for child in command.parent().childItems()
                    if callable(getattr(child, "requestPaint", None))
                ]
                assert len(canvases) == 1
                assert canvases[0].isVisible() is False
                window.hud.set_operational_state("SPEAKING")
                QTest.qWait(180)
                app.processEvents()
                assert float(voice.property("phase")) > 0
            finally:
                window.close()
                window.deleteLater()
                for _ in range(5):
                    app.processEvents()
        finally:
            controller.rollback_all()


@pytest.mark.parametrize("offset", [1, 2])
def test_each_v12_failpoint_restores_exact_v11(offset: int) -> None:
    environment = active_environment()
    with patch.dict(os.environ, environment, clear=True):
        import main
        import ui

        controller = live.OnyxLiveActivationV12(
            live.ActivationFlagsV12.from_canonical_environ(environment),
            live.preflight_host(main, environment),
        )
        try:
            with pytest.raises(live.ActivationV12Error, match="injected V12"):
                controller.install(fail_after=controller.BASE_SEAM_COUNT + offset)
            assert id(controller) not in live._ROLLBACK_AUTHORITIES
            assert ui._CinematicHudV5Host.__module__ == (
                "_onyx_v11_verified_hud_v8"
            )
            assert live.LIVE_MASTER_FLAG not in os.environ
            assert os.environ[live.v11.LIVE_MASTER_FLAG] == "1"
        finally:
            controller._base.rollback_all()


def test_canonical_v12_preflight_subprocess() -> None:
    result = subprocess.run(
        [
            str(ROOT / ".venv/Scripts/python.exe"),
            "-B",
            "scripts/bootstrap_onyx_live_v12.pyw",
            "--preflight-only",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ONYX_LIVE_V12_HOST_PREFLIGHT_OK" in result.stdout
    assert "hud=v9" in result.stdout
    assert "arcs=0" in result.stdout
    assert "network_calls=0" in result.stdout
