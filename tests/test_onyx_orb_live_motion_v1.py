from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PySide6.QtCore import QObject, QTimer
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import core.onyx_hud_orb_v8 as hud_v8
import core.onyx_hud_orb_v9 as hud_v9
import ui
from core.onyx_hud_orb_v6 import install_candidate as install_v6
from core.onyx_hud_orb_v6 import uninstall_candidate as uninstall_v6
from core.onyx_hud_orb_v7 import install_candidate as install_v7
from core.onyx_hud_orb_v7 import uninstall_candidate as uninstall_v7


@pytest.fixture(autouse=True)
def _clean_hud(monkeypatch: pytest.MonkeyPatch):
    hud_v9.uninstall_candidate(ui)
    hud_v8.uninstall_candidate(ui)
    uninstall_v7(ui)
    uninstall_v6(ui)
    for flag in (
        "ONYX_HUD_V6_CANDIDATE",
        "ONYX_HUD_V7_LIVE",
        hud_v8.FLAG_NAME,
        hud_v9.FLAG_NAME,
    ):
        monkeypatch.setenv(flag, "1")
    yield
    hud_v9.uninstall_candidate(ui)
    hud_v8.uninstall_candidate(ui)
    uninstall_v7(ui)
    uninstall_v6(ui)


def test_current_v9_orb_moves_reacts_and_stops_without_visual_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    monkeypatch.setattr(
        ui.MainWindow,
        "_create_desktop_shortcut",
        lambda _self: None,
    )
    assert install_v6(ui)
    assert install_v7(ui)
    assert hud_v8.install_candidate(ui)
    assert hud_v9.install_candidate(ui)

    window = ui.MainWindow("")
    window.resize(1000, 700)
    window.show()
    QTest.qWait(150)
    app.processEvents()
    try:
        root = window._v5_host._quick.rootObject()
        entity = root.findChild(QQuickItem, "onyxOrbEntityV7Root")
        voice = root.findChild(QQuickItem, "onyxOrbVoiceLayerV8")
        assert entity is not None and voice is not None
        timer_count = len(window._v5_host.findChildren(QTimer))
        assert window._v5_host._motion_timer.isActive()
        start = float(entity.property("phase"))
        QTest.qWait(180)
        app.processEvents()
        assert float(entity.property("phase")) > start
        assert float(entity.property("scale")) != 1.0
        listening_start = window._v5_host.orb_motion_stats()["callbacks"]
        QTest.qWait(550)
        app.processEvents()
        listening_stats = window._v5_host.orb_motion_stats()
        assert 1 <= listening_stats["callbacks"] - listening_start <= 12
        assert listening_stats["target_fps"] <= 16

        window.hud.set_muted(True)
        app.processEvents()
        muted_start = window._v5_host.orb_motion_stats()["callbacks"]
        QTest.qWait(180)
        app.processEvents()
        assert window._v5_host.orb_motion_stats() == {
            "callbacks": muted_start,
            "active_timers": 0,
            "target_fps": 0,
            "running": False,
        }
        window.hud.set_muted(False)
        app.processEvents()

        window.hud.set_operational_state("SPEAKING")
        window._apply_audio_level(0.85)
        QTest.qWait(100)
        app.processEvents()
        assert window._v5_host.projection.audioLevel == pytest.approx(0.85)
        assert window._v5_host._motion.audio_level == pytest.approx(0.85)
        assert float(voice.property("level")) == pytest.approx(0.85)
        assert 0 < window._v5_host._motion.target_fps <= 30
        speaking_start = window._v5_host.orb_motion_stats()["callbacks"]
        QTest.qWait(520)
        app.processEvents()
        speaking_stats = window._v5_host.orb_motion_stats()
        assert 1 <= speaking_stats["callbacks"] - speaking_start <= 18

        window.hud.set_reduced_motion(True)
        app.processEvents()
        assert not window._v5_host._motion_timer.isActive()
        assert window._v5_host.orb_motion_stats()["target_fps"] == 0
        assert float(entity.property("scale")) == 1.0
        assert float(entity.property("rotation")) == 0.0
        window.hud.set_reduced_motion(False)
        app.processEvents()
        assert window._v5_host._motion_timer.isActive()
        assert len(window._v5_host.findChildren(QTimer)) == timer_count
        object_count = len(root.findChildren(QObject))
        for _ in range(3):
            window.hud.set_muted(True)
            app.processEvents()
            window.hud.set_muted(False)
            app.processEvents()
        QTest.qWait(120)
        app.processEvents()
        assert len(root.findChildren(QObject)) == object_count

        window.hide()
        app.processEvents()
        assert not window._v5_host._motion_timer.isActive()
        hidden_start = window._v5_host.orb_motion_stats()["callbacks"]
        QTest.qWait(180)
        app.processEvents()
        assert window._v5_host.orb_motion_stats()["callbacks"] == hidden_start
    finally:
        window.close()
        window.deleteLater()
        for _ in range(5):
            app.processEvents()
