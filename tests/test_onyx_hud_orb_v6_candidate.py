from __future__ import annotations

import hashlib
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QApplication

import ui
from core.onyx_hud_orb_v6 import (
    FLAG_NAME,
    candidate_requested,
    install_candidate,
    uninstall_candidate,
)
from core.paths import resource_root
from scripts.capture_hud_orb_v6_evidence import _verify_single_quick_widget


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def clean_installation(monkeypatch: pytest.MonkeyPatch):
    uninstall_candidate(ui)
    monkeypatch.delenv(FLAG_NAME, raising=False)
    yield
    uninstall_candidate(ui)


def _close(app: QApplication, window: ui.MainWindow) -> None:
    window.close()
    window.deleteLater()
    for _ in range(5):
        app.processEvents()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),
        ("", False),
        ("0", False),
        ("true", False),
        ("TRUE", False),
        ("True", False),
        ("yes", False),
        ("01", False),
        (" 1 ", False),
        ("1 ", False),
        (" 1", False),
        ("\t1", False),
        ("1\n", False),
        ("1", True),
    ],
)
def test_v6_flag_is_exact(value: str | None, expected: bool) -> None:
    environ = {} if value is None else {FLAG_NAME: value}
    assert candidate_requested(environ) is expected


def test_default_off_does_not_mutate_accepted_v5() -> None:
    host = ui._CinematicHudV5Host
    requested = ui.HUD_V5_LIVE
    assert install_candidate(ui) is False
    assert ui._CinematicHudV5Host is host
    assert ui.HUD_V5_LIVE is requested


def test_installation_is_transactional_idempotent_and_reversible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = ui._CinematicHudV5Host
    requested = ui.HUD_V5_LIVE
    monkeypatch.setenv(FLAG_NAME, "1")
    assert install_candidate(ui)
    installed = ui._CinematicHudV5Host
    assert installed is not host
    assert install_candidate(ui)
    assert ui._CinematicHudV5Host is installed
    assert uninstall_candidate(ui)
    assert ui._CinematicHudV5Host is host
    assert ui.HUD_V5_LIVE is requested
    assert not uninstall_candidate(ui)


def test_rollback_preserves_non_boolean_previous_flag_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = object()
    monkeypatch.setattr(ui, "HUD_V5_LIVE", sentinel)
    monkeypatch.setenv(FLAG_NAME, "1")
    assert install_candidate(ui)
    assert ui.HUD_V5_LIVE is True
    assert uninstall_candidate(ui)
    assert ui.HUD_V5_LIVE is sentinel


def test_v6_renders_with_one_quick_widget_and_v5_projection(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(FLAG_NAME, "1")
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    assert install_candidate(ui)
    window = ui.MainWindow("")
    window.show()
    for _ in range(10):
        app.processEvents()
    try:
        assert window._hud_v5_live
        assert window.hud.renderer_mode == "qml-v6-candidate"
        assert window.hud.projection is window._v5_projection
        widgets = [
            widget
            for widget in QApplication.allWidgets()
            if isinstance(widget, QQuickWidget)
        ]
        assert widgets == [window._v5_host._quick]
        root = window._v5_host._quick.rootObject()
        assert root.objectName() == "onyxLiveShellV6Root"
        assert root.findChild(QQuickItem, "onyxOrbParticleV6Root") is not None
        command = root.findChild(QQuickItem, "liveCommandInputV6")
        assert command is not None and command.isVisible() and command.isEnabled()
        assert _verify_single_quick_widget(window._v5_host._quick) == 1

        rogue = QQuickWidget()
        try:
            with pytest.raises(RuntimeError, match="renderer count mismatch"):
                _verify_single_quick_widget(window._v5_host._quick)
        finally:
            rogue.deleteLater()
            app.processEvents()
    finally:
        _close(app, window)


def test_v6_minimize_stops_all_animation(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(FLAG_NAME, "1")
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    assert install_candidate(ui)
    window = ui.MainWindow("")
    window.show()
    for _ in range(5):
        app.processEvents()
    try:
        window.hud.set_operational_state("THINKING")
        window.hud.sync_animation()
        assert window.hud.projection.targetFps == 16
        assert window.hud.projection.animationRunning
        window.showMinimized()
        for _ in range(5):
            app.processEvents()
        assert window.hud.projection.targetFps == 0
        assert not window.hud.projection.animationRunning
    finally:
        _close(app, window)


def test_v6_preserves_every_public_control_and_accessibility_contract() -> None:
    shell = (resource_root() / "qml" / "OnyxLiveShellV6.qml").read_text(
        encoding="utf-8"
    )
    for label in (
        "FILE",
        "INTERRUPT",
        "MUTE",
        "AUTONOMY",
        "REMOTE",
        "CAMERA",
        "SETUP",
        "FULLSCREEN",
        "CLOSE",
        "HISTORY",
        "ACCESS",
        "RUN",
    ):
        assert f'"{label}"' in shell
    for action in (
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
    assert "Accessible.role: Accessible.EditableText" in shell
    assert "DropArea" in shell and "acceptDroppedFile" in shell


def test_v6_is_entity_layout_not_rectangular_or_corner_dashboard() -> None:
    shell = (
        (resource_root() / "qml" / "OnyxLiveShellV6.qml")
        .read_text(encoding="utf-8")
        .lower()
    )
    orb = (
        (resource_root() / "qml" / "components" / "OnyxOrbParticleV6.qml")
        .read_text(encoding="utf-8")
        .lower()
    )
    for forbidden in (
        "corner bracket",
        "cornerbracket",
        "dashboard card",
        "panel card",
        "qtquick3d",
        "webgl",
    ):
        assert forbidden not in shell
        assert forbidden not in orb
    assert 'source: "../assets/onyx-orb-particle-v6.png"' in orb
    assert "math.min(32, projection.particlebudget)" in orb
    assert "running: root.simulationrunning" in orb
    assert "ctx.clearrect(0, 0, width, height)" in orb
    assert "frameclock" in orb


def test_v6_uses_only_cyryx_design_tokens() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            resource_root() / "qml" / "OnyxLiveShellV6.qml",
            resource_root() / "qml" / "components" / "OnyxOrbParticleV6.qml",
        )
    ).lower()
    for token in (
        "#050607",
        "#0a0d0f",
        "#11161a",
        "#1b2227",
        "#8c949e",
        "#c7c9cc",
        "#0f6b68",
        "#19c7c0",
    ):
        assert token in combined


def test_v6_asset_is_exact() -> None:
    asset = resource_root() / "qml" / "assets" / "onyx-orb-particle-v6.png"
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == (
        "9582f4df844cbf03df45a97d6a7c351e9ad9dd291f097b53326f6d1597e44582"
    )


def test_capture_never_asserts_a_constant_renderer_count() -> None:
    source = (resource_root() / "scripts" / "capture_hud_orb_v6_evidence.py").read_text(
        encoding="utf-8"
    )
    assert "QApplication.allWidgets()" in source
    assert "isinstance(widget, QQuickWidget)" in source
    assert '"quick_widgets": 1' not in source
    assert '"quick_widgets": quick_widget_count' in source


def test_accepted_v5_visual_anchors_and_pyside_hosts_are_current() -> None:
    expected = {
        "qml/OnyxLiveShellV5.qml": "9ff4d3d5d3771d1bbf2c2f8fe68793fd05e8cc80fd0c0644d700596d7cd39e47",
        "qml/components/OnyxOrbCinematicV5.qml": "adff9ee062fff1c735bd28d4a77591581b6e4ce131067b1724699da5055e2622",
        "core/render_governor_v3.py": "ee1f2145eb90e930e1663287bc0e71ff6f0809b9b4bce18e445c2f47e80d1de8",
    }
    for relative, digest in expected.items():
        assert (
            hashlib.sha256((resource_root() / relative).read_bytes()).hexdigest()
            == digest
        )
    for relative in ("ui.py", "core/ui_projection_v3.py"):
        source = (resource_root() / relative).read_text(encoding="utf-8")
        assert "PySide6" in source and "PyQt6" not in source
