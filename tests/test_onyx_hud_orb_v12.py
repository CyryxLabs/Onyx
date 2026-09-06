from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import core.onyx_hud_orb_v12 as hud_v12
import ui


def test_v12_resynchronises_accepted_v11_ambient_motion(monkeypatch) -> None:
    app = QApplication.instance() or QApplication(["onyx-v12-motion-test"])
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    monkeypatch.setattr(ui.MainWindow, "_create_desktop_shortcut", lambda _self: None)
    hud_v12.uninstall_candidate(ui)
    from core import onyx_hud_orb_v6 as hud_v6
    from core import onyx_hud_orb_v7 as hud_v7
    from core import onyx_hud_orb_v8 as hud_v8
    from core import onyx_hud_orb_v9 as hud_v9

    predecessors = (hud_v6, hud_v7, hud_v8, hud_v9)
    for predecessor in predecessors:
        monkeypatch.setenv(predecessor.FLAG_NAME, "1")
        assert predecessor.install_candidate(ui)
    assert hud_v12.install_current(ui)

    window = ui.MainWindow("")
    window.resize(1000, 700)
    window.show()
    QTest.qWait(180)
    app.processEvents()
    try:
        root = window._v5_host._quick.rootObject()
        entity = root.findChild(QQuickItem, "onyxOrbEntityV7Root")
        assert entity is not None
        assert window._v5_host.renderer_mode == "qml-v11-explicit-exit"
        assert window._v5_host._motion_timer.isActive()
        start_phase = float(entity.property("phase"))
        start_scale = float(entity.property("scale"))
        start_callbacks = window._v5_host.orb_motion_stats()["callbacks"]

        QTest.qWait(750)
        app.processEvents()
        stats = window._v5_host.orb_motion_stats()
        assert stats["running"] is True
        assert stats["active_timers"] == 1
        assert 1 <= stats["callbacks"] - start_callbacks <= 12
        assert float(entity.property("phase")) > start_phase
        assert float(entity.property("scale")) != start_scale

        window.hide()
        app.processEvents()
        hidden_callbacks = window._v5_host.orb_motion_stats()["callbacks"]
        QTest.qWait(180)
        app.processEvents()
        assert window._v5_host.orb_motion_stats()["callbacks"] == hidden_callbacks
        assert not window._v5_host._motion_timer.isActive()
    finally:
        window._exit_requested = True
        window.close()
        window.deleteLater()
        for _ in range(5):
            app.processEvents()
        assert hud_v12.uninstall_candidate(ui)
        for predecessor in reversed(predecessors):
            assert predecessor.uninstall_candidate(ui)
