from __future__ import annotations

import os
from pathlib import Path
import runpy
import subprocess
import types
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core import onyx_live_activation_v13 as live
from core import phase6_live_wiring_v2 as wiring_v2
from core.phase6_provider_registry_v1 import ProviderRegistryV1
from core.phase6_research_cells_v1 import ResearchVerifierPipelineV1
from core.phase6_unified_command_router_v1 import UnifiedCommandRouterV1


ROOT = Path(__file__).resolve().parents[1]


class FakeUI:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.states: list[str] = []
        self.prompt_count = 0
        self.muted = False
        self._win = types.SimpleNamespace(_hud_v5_live=True)

    def write_log(self, value: str) -> None:
        self.logs.append(value)

    def set_state(self, value: str) -> None:
        self.states.append(value)

    def prompt_reconfig(self) -> None:
        self.prompt_count += 1


def active_environment() -> dict[str, str]:
    result = dict(os.environ)
    for name in live.CONTROL_FLAGS:
        result.pop(name, None)
    result.update(live.exact_activation_environment())
    return result


def test_v13_exact_environment_bootstrap_and_launcher_modes() -> None:
    environment = live.exact_activation_environment()
    flags = live.ActivationFlagsV13.from_canonical_environ(environment)
    assert flags.master and flags.wiring_v2
    assert environment[live.LIVE_MASTER_FLAG] == "1"
    assert environment[live.WIRING_V2_FLAG] == "true"
    assert environment[live.v12.LIVE_MASTER_FLAG] == "1"
    restored = live.restore_v12_environment(environment)
    assert live.LIVE_MASTER_FLAG not in restored
    assert live.WIRING_V2_FLAG not in restored
    assert restored[live.v12.LIVE_MASTER_FLAG] == "1"

    bootstrap = runpy.run_path(
        str(ROOT / "scripts/bootstrap_onyx_live_v13.pyw"),
        run_name="_test_bootstrap_v13",
    )
    prepared = bootstrap["_bootstrap_environment"](
        {
            "PATH": "preserved",
            live.LIVE_ROLLBACK_FLAG: "1",
            live.v12.LIVE_ROLLBACK_FLAG: "1",
            live.WIRING_V2_FLAG: "TRUE",
        }
    )
    assert prepared["PATH"] == "preserved"
    assert {name: prepared[name] for name in environment} == environment

    launcher = runpy.run_path(
        str(ROOT / "scripts/launch_onyx_live_v13.pyw"),
        run_name="_test_launcher_v13",
    )
    assert launcher["_launch_mode"]({}) == "legacy"
    assert launcher["_launch_mode"](environment) == "active"
    assert launcher["_launch_mode"]({live.LIVE_ROLLBACK_FLAG: "1"}) == "rollback"
    assert launcher["_launch_mode"]({live.LIVE_MASTER_FLAG: "1"}) == "refuse"


def test_v13_frozen_roots_and_host_preflight_are_exact() -> None:
    result = live._verify_frozen_roots(ROOT)
    assert result["artifact_root_sha256"] == (live.WIRING_V2_ARTIFACT_ROOT_SHA256)
    assert result["component_roots"] == 15
    environment = active_environment()
    with patch.dict(os.environ, environment, clear=True):
        import main

        contract = live.preflight_host(main, environment)
        assert contract.project == ROOT
        assert contract.base.project == ROOT


def test_real_v13_preserves_v9_and_composes_wiring_v2_session() -> None:
    environment = active_environment()
    with patch.dict(os.environ, environment, clear=True):
        import main
        import ui

        app = QApplication.instance() or QApplication([])
        controller = live.OnyxLiveActivationV13(
            live.ActivationFlagsV13.from_canonical_environ(environment),
            live.preflight_host(main, environment),
        )
        try:
            controller.install()
            assert type(controller.phase6_wiring_v2) is (wiring_v2.Phase6LiveWiringV2)
            assert controller.phase6_wiring_v2.installed

            with patch.object(
                ui.MainWindow,
                "_create_lnk_windows",
                lambda *_args, **_kwargs: None,
            ):
                window = ui.MainWindow("")
                window.resize(1000, 700)
                window.show()
                QTest.qWait(200)
                app.processEvents()
                try:
                    assert window.hud.renderer_mode == "qml-v9-arc-free"
                    root = window._v5_host._quick.rootObject()
                    assert root.objectName() == "onyxLiveShellV9Root"
                    command = root.findChild(QQuickItem, "liveCommandInputV7")
                    assert command is not None
                    canvases = [
                        child
                        for child in command.parent().childItems()
                        if callable(getattr(child, "requestPaint", None))
                    ]
                    assert len(canvases) == 1 and not canvases[0].isVisible()
                finally:
                    window.close()
                    window.deleteLater()
                    for _ in range(5):
                        app.processEvents()

            instance = controller._base.wiring_controller._host_type(FakeUI())
            instance._start_phase5_session()
            session = controller.phase6_wiring_v2.session_for(instance)
            assert type(session) is wiring_v2.Phase6OperationalSessionV2
            assert type(session.provider_registry) is ProviderRegistryV1
            assert type(session.research_pipeline) is ResearchVerifierPipelineV1
            assert type(session.router) is UnifiedCommandRouterV1
            assert session.provider_record.descriptor.status.value == (
                "blocked_by_policy"
            )
            instance._stop_phase5_session("test")
            assert session.closed and session.base_session.closed
        finally:
            controller.rollback_all()


@pytest.mark.parametrize("offset", [1, 2])
def test_each_v13_failpoint_restores_exact_v12(offset: int) -> None:
    environment = active_environment()
    with patch.dict(os.environ, environment, clear=True):
        import main
        import ui

        controller = live.OnyxLiveActivationV13(
            live.ActivationFlagsV13.from_canonical_environ(environment),
            live.preflight_host(main, environment),
        )
        try:
            with pytest.raises(live.ActivationV13Error, match="injected V13"):
                controller.install(fail_after=controller.BASE_SEAM_COUNT + offset)
            assert controller.phase6_wiring_v2 is None
            assert id(controller) not in live._ROLLBACK_AUTHORITIES
            assert ui._CinematicHudV5Host.__module__ == ("core.onyx_hud_orb_v9")
            assert controller._base.wiring_controller.installed
            assert live.LIVE_MASTER_FLAG not in os.environ
            assert os.environ[live.v12.LIVE_MASTER_FLAG] == "1"
        finally:
            controller._base.rollback_all()


def test_canonical_v13_preflight_subprocess() -> None:
    result = subprocess.run(
        [
            str(ROOT / ".venv/Scripts/python.exe"),
            "-B",
            "scripts/bootstrap_onyx_live_v13.pyw",
            "--preflight-only",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ONYX_LIVE_V13_HOST_PREFLIGHT_OK" in result.stdout
    assert "hud=v9" in result.stdout
    assert "arcs=0" in result.stdout
    assert "wiring=v2" in result.stdout
    assert "components=5" in result.stdout
    assert "provider_calls=0" in result.stdout
    assert "network_calls=0" in result.stdout
