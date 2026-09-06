from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import core.onyx_hud_orb_v13 as hud_v13
import ui


def test_v13_loads_one_living_liquid_metal_root(monkeypatch) -> None:
    app = QApplication.instance() or QApplication(["onyx-v13-liquid-metal-test"])
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    monkeypatch.setattr(ui.MainWindow, "_create_desktop_shortcut", lambda _self: None)
    monkeypatch.setattr(ui, "install_current_hud_v10", lambda: True)
    hud_v13.uninstall_candidate(ui)
    from core import onyx_hud_orb_v6 as hud_v6
    from core import onyx_hud_orb_v7 as hud_v7
    from core import onyx_hud_orb_v8 as hud_v8
    from core import onyx_hud_orb_v9 as hud_v9

    predecessors = (hud_v6, hud_v7, hud_v8, hud_v9)
    for predecessor in predecessors:
        monkeypatch.setenv(predecessor.FLAG_NAME, "1")
        assert predecessor.install_candidate(ui)
    assert hud_v13.install_current(ui)

    window = ui.MainWindow("")
    window.resize(1000, 700)
    window.show()
    QTest.qWait(180)
    app.processEvents()
    try:
        root = window._v5_host._quick.rootObject()
        entity = root.findChild(QQuickItem, "onyxOrbLiquidMetalV9Root")
        assert root.objectName() == "onyxLiveShellV12Root"
        assert entity is not None
        assert window._v5_host.renderer_mode == "qml-v13-explicit-exit"
        assert window._v5_host.source_load_count == 1
        assert window._v5_host._motion_timer.isActive()
        start_phase = float(entity.property("phase"))
        QTest.qWait(500)
        app.processEvents()
        assert float(entity.property("phase")) > start_phase
        assert window._v5_host.orb_motion_stats()["active_timers"] == 1

        window._v5_host.set_reduced_motion(True)
        app.processEvents()
        assert not window._v5_host._motion_timer.isActive()
    finally:
        window._exit_requested = True
        window.close()
        window.deleteLater()
        for _ in range(5):
            app.processEvents()
        assert hud_v13.uninstall_candidate(ui)
        for predecessor in reversed(predecessors):
            assert predecessor.uninstall_candidate(ui)
