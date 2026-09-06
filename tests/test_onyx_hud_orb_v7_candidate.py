from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PyQt6.QtQuick import QQuickItem
from PyQt6.QtQuickWidgets import QQuickWidget
from PyQt6.QtWidgets import QApplication

import ui
from core.onyx_hud_orb_v6 import install_candidate as install_v6
from core.onyx_hud_orb_v6 import uninstall_candidate as uninstall_v6
from core.onyx_hud_orb_v7 import (
    FLAG_NAME,
    candidate_requested,
    install_candidate,
    uninstall_candidate,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def clean_installation(monkeypatch: pytest.MonkeyPatch):
    uninstall_candidate(ui)
    uninstall_v6(ui)
    monkeypatch.delenv(FLAG_NAME, raising=False)
    monkeypatch.delenv("ONYX_HUD_V6_CANDIDATE", raising=False)
    yield
    uninstall_candidate(ui)
    uninstall_v6(ui)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),
        ("", False),
        ("0", False),
        ("true", False),
        ("TRUE", False),
        ("01", False),
        ("1 ", False),
        (" 1", False),
        ("\t1", False),
        ("1\n", False),
        ("1", True),
    ],
)
def test_v7_flag_is_exact(value: str | None, expected: bool) -> None:
    environ = {} if value is None else {FLAG_NAME: value}
    assert candidate_requested(environ) is expected


def test_v7_preserves_all_projection_data_and_actions() -> None:
    shell = (ROOT / "qml/OnyxLiveShellV7.qml").read_text(encoding="utf-8")
    for field in (
        "ownerName",
        "stateLabel",
        "stateDetail",
        "metricsSummary",
        "contentTitle",
        "contentText",
        "transcriptTitle",
        "transcriptText",
        "logText",
    ):
        assert f"uiProjection.{field}" in shell
    for action in (
        "submitCommand(",
        "acceptDroppedFile(",
        "requestFile()",
        "requestInterrupt()",
        "requestMuteToggle()",
        "requestAutonomy()",
        "requestRemote()",
        "requestCamera()",
        "requestSetup()",
        "requestFullscreen()",
        "requestClose()",
        "requestHistory()",
        "requestPermissions()",
    ):
        assert action in shell


def test_v7_is_full_bleed_entity_not_dashboard() -> None:
    combined = (
        (ROOT / "qml/OnyxLiveShellV7.qml").read_text(encoding="utf-8")
        + (ROOT / "qml/components/OnyxOrbEntityV7.qml").read_text(encoding="utf-8")
    ).lower()
    for forbidden in (
        "qtquick3d",
        "webgl",
        "corner bracket",
        "dashboard card",
    ):
        assert forbidden not in combined
    assert "presenceRail" not in combined and "contextRail" not in combined
    assert "quadraticcurveto" in combined and "onyxorbentityv7" in combined
    assert 'source: "../assets/onyx-orb-particle-v6.png"' in combined
    assert "multieffect" in combined and "spheresize" in combined


def test_v7_uses_cyryx_tokens_and_governed_animation() -> None:
    combined = (ROOT / "qml/OnyxLiveShellV7.qml").read_text(encoding="utf-8") + (
        ROOT / "qml/components/OnyxOrbEntityV7.qml"
    ).read_text(encoding="utf-8")
    for token in (
        "#050607",
        "#0A0D0F",
        "#11161A",
        "#1B2227",
        "#8C949E",
        "#C7C9CC",
        "#0F6B68",
        "#19C7C0",
    ):
        assert token in combined
    assert "Math.min(12" in combined
    assert "running: entity.governedFps > 0 && entity.visible" in combined


def test_v7_c003_has_no_external_orbit_geometry() -> None:
    shell = (ROOT / "qml/OnyxLiveShellV7.qml").read_text(encoding="utf-8")
    entity = (ROOT / "qml/components/OnyxOrbEntityV7.qml").read_text(encoding="utf-8")
    shell_above_keel = shell.split("id: keel", maxsplit=1)[0]
    assert "quadraticCurveTo" not in shell_above_keel
    assert "c.arc(" not in shell_above_keel
    assert "c.ellipse(" not in shell_above_keel
    assert "c.arc(" not in entity
    assert "c.ellipse(" not in entity
    assert "border.width" not in entity
    assert "maskEnabled: true" in entity


def test_v7_does_not_change_v9_or_shortcuts() -> None:
    source = (ROOT / "core/onyx_hud_orb_v7.py").read_text(encoding="utf-8")
    assert "launch_onyx_live_v9" not in source
    assert "shortcut" not in source.lower()
    assert os.path.basename("qml/OnyxLiveShellV7.qml") in source


def test_v7_one_widget_projection_and_exact_v6_rollback(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONYX_HUD_V6_CANDIDATE", "1")
    monkeypatch.setenv(FLAG_NAME, "1")
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    assert install_v6(ui)
    v6_host = ui._CinematicHudV5Host
    assert install_candidate(ui)
    window = ui.MainWindow("")
    window.resize(1000, 700)
    window.show()
    for _ in range(8):
        app.processEvents()
    try:
        assert window.hud.renderer_mode == "qml-v7-cinematic"
        assert window.hud.projection is window._v5_projection
        widgets = [w for w in QApplication.allWidgets() if isinstance(w, QQuickWidget)]
        assert widgets == [window._v5_host._quick]
        qml_root = window._v5_host._quick.rootObject()
        assert qml_root.objectName() == "onyxLiveShellV7Root"
        assert qml_root.findChild(QQuickItem, "liveCommandInputV7") is not None
    finally:
        window.close()
        window.deleteLater()
        for _ in range(5):
            app.processEvents()
    assert uninstall_candidate(ui)
    assert ui._CinematicHudV5Host is v6_host


def test_v7_denies_spoofed_v6_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_host = ui._CinematicHudV5Host

    class SpoofedV6Host(base_host):
        @property
        def renderer_mode(self) -> str:
            return "qml-v6-candidate"

    monkeypatch.setenv(FLAG_NAME, "1")
    monkeypatch.setattr(ui, "_CinematicHudV5Host", SpoofedV6Host)
    monkeypatch.setattr(ui, "HUD_V5_LIVE", True)
    ui._ONYX_HUD_V6_INSTALLATION = {
        "base_host": base_host,
        "previous_flag": False,
        "source": str(ROOT / "qml/OnyxLiveShellV6.qml"),
    }
    with pytest.raises(RuntimeError, match="V6 host failed authentication"):
        install_candidate(ui)


def test_v7_rollback_ignores_mutable_ui_marker_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ONYX_HUD_V6_CANDIDATE", "1")
    monkeypatch.setenv(FLAG_NAME, "1")
    assert install_v6(ui)
    v6_host = ui._CinematicHudV5Host
    assert install_candidate(ui)
    ui._ONYX_HUD_V7_INSTALLATION = {
        "base_host": object(),
        "previous_flag": object(),
    }
    ui._CinematicHudV5Host = object()
    ui.HUD_V5_LIVE = object()
    assert uninstall_candidate(ui)
    assert ui._CinematicHudV5Host is v6_host
    assert ui.HUD_V5_LIVE is True
