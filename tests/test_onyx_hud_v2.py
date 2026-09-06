from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickView
from PySide6.QtWidgets import QApplication

from core.paths import resource_root
from core.render_governor import RenderGovernor
from core.ui_projection import OnyxUIProjection


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def load_qml(path: Path, properties: dict[str, object]):
    engine = QQmlEngine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
    errors = "\n".join(error.toString() for error in component.errors())
    assert component.status() == QQmlComponent.Status.Ready, errors
    root = component.createWithInitialProperties(properties)
    errors = "\n".join(error.toString() for error in component.errors())
    assert root is not None, errors
    # PySide6 may release a parentless object when its creating component is
    # collected. Keep the component alive for the duration of the assertion.
    return engine, component, root


def test_projection_preserves_host_callback_contracts() -> None:
    callbacks = {
        name: Mock()
        for name in ("command", "mute", "settings", "history", "permissions", "close")
    }
    projection = OnyxUIProjection(callbacks=callbacks)

    projection.set_operational_state("thinking")
    projection.set_muted(False)
    projection.set_reduced_motion(False)
    projection.set_surface_active(True)
    assert projection.state == "THINKING"
    assert projection.submitCommand("  inspect the workspace  ")
    projection.requestMuteToggle()
    projection.requestSettings()
    projection.requestHistory()
    projection.requestPermissions()
    projection.requestClose()

    callbacks["command"].assert_called_once_with("inspect the workspace")
    callbacks["mute"].assert_called_once_with(True)
    callbacks["settings"].assert_called_once_with()
    callbacks["history"].assert_called_once_with()
    callbacks["permissions"].assert_called_once_with()
    callbacks["close"].assert_called_once_with()


def test_projection_lifecycle_and_audio_are_bounded() -> None:
    now = [20.0]
    governor = RenderGovernor(clock=lambda: now[0], settle_seconds=0.1)
    projection = OnyxUIProjection(governor=governor)
    projection.set_lifecycle(visible=True, minimized=False)
    projection.set_operational_state("SPEAKING")
    assert projection.animationRunning
    assert projection.targetFps == 30
    assert projection.set_audio_level(0.8, now=20.0)
    assert not projection.set_audio_level(0.3, now=20.049)
    assert projection.audioLevel == 0.8

    projection.set_lifecycle(visible=True, minimized=True)
    assert not projection.animationRunning
    assert projection.targetFps == 0
    projection.set_lifecycle(visible=False, minimized=False)
    assert not projection.animationRunning


def test_projection_contains_callback_failures() -> None:
    def fail() -> None:
        raise RuntimeError("private implementation detail")

    projection = OnyxUIProjection(callbacks={"settings": fail})
    assert not projection.requestSettings()
    assert projection.lastCallbackError == "settings: RuntimeError"
    assert "private implementation detail" not in projection.lastCallbackError


def test_v2_orb_and_shell_instantiate_with_public_qt_apis(app: QApplication) -> None:
    projection = OnyxUIProjection()
    projection.set_lifecycle(visible=False, minimized=False)

    engine, component, orb = load_qml(
        resource_root() / "qml" / "components" / "OnyxOrbV2.qml",
        {"projection": projection},
    )
    assert orb.objectName() == "onyxOrbV2Root"
    assert orb.property("boundedNodeCount") <= 160
    assert not orb.property("simulationRunning")
    orb.deleteLater()
    del component
    del engine

    engine, component, shell = load_qml(
        resource_root() / "qml" / "OnyxShell.qml",
        {"uiProjection": projection},
    )
    assert shell.objectName() == "onyxShellRoot"
    assert len(shell.findChildren(QObject, "onyxOrbV2Root")) == 1
    shell.deleteLater()
    del component
    del engine
    app.processEvents()


def test_shell_loads_through_public_qquickview_context_contract(
    app: QApplication,
) -> None:
    projection = OnyxUIProjection()
    view = QQuickView()
    view.rootContext().setContextProperty("onyxUIProjection", projection)
    view.setSource(QUrl.fromLocalFile(str(resource_root() / "qml" / "OnyxShell.qml")))
    errors = "\n".join(error.toString() for error in view.errors())
    assert view.status() == QQuickView.Status.Ready, errors
    assert view.rootObject() is not None
    assert view.rootObject().objectName() == "onyxShellRoot"
    view.close()
    app.processEvents()


def test_geometry_and_brand_contract_prohibit_the_old_visual_language() -> None:
    qml_root = resource_root() / "qml"
    candidates = [
        qml_root / "OnyxShell.qml",
        *sorted((qml_root / "components").glob("*.qml")),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in candidates)
    lowered = combined.lower()

    for forbidden in (
        "#sphere",
        "qtquick3d",
        "crosshair",
        "octagon",
        "bracket",
        "cornermarker",
    ):
        assert forbidden not in lowered
    assert combined.count("OnyxOrbV2 {") == 1
    assert "Math.min(160, projection.particleBudget)" in combined
    # Later cinematic successors use a packaged raster texture. The security
    # boundary is local-only assets, not a blanket prohibition on Image.
    assert "http://" not in lowered and "https://" not in lowered
    for state in (
        "INITIALISING",
        "LISTENING",
        "THINKING",
        "PROCESSING",
        "SPEAKING",
        "OFFLINE",
    ):
        assert state in combined

    approved = {
        "#050607",
        "#0a0d0f",
        "#11161a",
        "#1b2227",
        "#8c949e",
        "#c7c9cc",
        "#0f6b68",
        "#19c7c0",
    }
    import re

    opaque_colors = {
        value.lower() for value in re.findall(r"#[0-9a-fA-F]{6}", combined)
    }
    assert opaque_colors <= approved


def test_qml_tree_is_packaged_without_external_shader_or_asset_paths() -> None:
    root = resource_root()
    spec = (root / "packaging" / "onyx.spec").read_text(encoding="utf-8")
    assert '(str(RUNTIME_SOURCES / "qml"), "qml")' in spec
    for path in (
        root / "qml" / "OnyxShell.qml",
        root / "qml" / "components" / "OnyxOrbV2.qml",
        root / "qml" / "components" / "HoloPanel.qml",
        root / "qml" / "components" / "StatusPill.qml",
        root / "qml" / "components" / "TelemetryBar.qml",
    ):
        assert path.is_file()
        text = path.read_text(encoding="utf-8").lower()
        assert ".qsb" not in text
        assert "file:/" not in text


def test_candidate_is_not_live_wired() -> None:
    root = resource_root()
    for relative in (
        "main.py",
        "ui.py",
        "dashboard/server.py",
        "core/permission_broker.py",
    ):
        text = (root / relative).read_text(encoding="utf-8")
        assert "OnyxShell.qml" not in text
        assert "OnyxOrbV2.qml" not in text
        assert "from core.ui_projection import OnyxUIProjection" not in text
        assert "OnyxUIProjection(" not in text
