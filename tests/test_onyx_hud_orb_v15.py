from __future__ import annotations

import hashlib
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import core.onyx_hud_orb_v15 as hud
import ui


ROOT = Path(__file__).resolve().parents[1]


def test_v15_authenticates_exact_v14_predecessor() -> None:
    predecessor = ROOT / hud.V14_MODULE_RELATIVE_PATH
    assert hashlib.sha256(predecessor.read_bytes()).hexdigest() == hud.V14_MODULE_SHA256


def test_v15_loads_one_humanoid_shell_root() -> None:
    source = (ROOT / hud.QML_RELATIVE_PATH).read_text(encoding="utf-8")
    assert hud.ROOT_OBJECT == "onyxLiveShellV14Root"
    assert 'objectName: "onyxLiveShellV14Root"' in source
    assert "OnyxHumanoidEntityV11" in source
    assert 'root.findObject(root, "onyxOrbLiquidMetalV9Root")' in source
    assert "predecessorOrb.visible = false" in source


def test_v15_remains_explicit_and_reversible() -> None:
    source = Path(hud.__file__).read_text(encoding="utf-8")
    assert 'return "qml-v15-humanoid-stable"' in source
    assert "accepted.install_current(ui_module)" in source
    assert "accepted.uninstall_candidate(ui_module)" in source
    assert "_v13_source_load_count += 1" in source


def test_v15_renders_living_humanoid_and_hides_sphere(monkeypatch) -> None:
    app = QApplication.instance() or QApplication(["onyx-v15-humanoid-test"])
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    monkeypatch.setattr(ui.MainWindow, "_create_desktop_shortcut", lambda _self: None)
    monkeypatch.setattr(ui, "install_current_hud_v10", lambda: True)
    from core import onyx_hud_orb_v6 as hud_v6
    from core import onyx_hud_orb_v7 as hud_v7
    from core import onyx_hud_orb_v8 as hud_v8
    from core import onyx_hud_orb_v9 as hud_v9

    predecessors = (hud_v6, hud_v7, hud_v8, hud_v9)
    for predecessor in predecessors:
        monkeypatch.setenv(predecessor.FLAG_NAME, "1")
        assert predecessor.install_candidate(ui)
    assert hud.install_current(ui)

    window = ui.MainWindow("")
    window.resize(1000, 700)
    window.show()
    QTest.qWait(180)
    app.processEvents()
    try:
        root = window._v5_host._quick.rootObject()
        humanoid = root.findChild(QQuickItem, "onyxHumanoidPresenceV11Root")
        webgl = root.findChild(QQuickItem, "onyxHumanoidThreeWebGLV2")
        fallback = root.findChild(QQuickItem, "onyxHumanoidWebGLFallbackV2")
        sphere = root.findChild(QQuickItem, "onyxOrbLiquidMetalV9Root")
        assert root.objectName() == "onyxLiveShellV14Root"
        assert humanoid is not None and humanoid.isVisible()
        assert sphere is not None and not sphere.isVisible()
        assert window._v5_host.renderer_mode == "qml-v15-humanoid-stable"
        assert window._v5_host.source_load_count == 1
        assert webgl is not None
        assert fallback is not None
        assert bool(webgl.isVisible()) != bool(fallback.isVisible())
    finally:
        window._exit_requested = True
        window.close()
        window.deleteLater()
        for _ in range(5):
            app.processEvents()
        assert hud.uninstall_candidate(ui)
        for predecessor in reversed(predecessors):
            assert predecessor.uninstall_candidate(ui)

