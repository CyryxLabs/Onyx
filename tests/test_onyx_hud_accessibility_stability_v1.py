from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import core.onyx_hud_orb_v10 as hud_v10
import core.onyx_hud_orb_v11 as hud_v11
import core.onyx_hud_orb_v12 as hud_v12
import core.onyx_hud_orb_v13 as hud_v13
import core.onyx_hud_orb_v17 as hud_v17
import core.onyx_hud_orb_v8 as hud_v8
import core.onyx_hud_orb_v9 as hud_v9
import ui
from core.onyx_hud_orb_v6 import install_candidate as install_v6
from core.onyx_hud_orb_v6 import uninstall_candidate as uninstall_v6
from core.onyx_hud_orb_v7 import install_candidate as install_v7
from core.onyx_hud_orb_v7 import uninstall_candidate as uninstall_v7


@pytest.fixture(autouse=True)
def clean_hud_chain() -> None:
    ui.uninstall_current_hud_v10()
    hud_v13.uninstall_candidate(ui)
    hud_v12.uninstall_candidate(ui)
    hud_v11.uninstall_candidate(ui)
    hud_v10.uninstall_candidate(ui)
    hud_v9.uninstall_candidate(ui)
    hud_v8.uninstall_candidate(ui)
    uninstall_v7(ui)
    uninstall_v6(ui)
    yield
    ui.uninstall_current_hud_v10()
    hud_v13.uninstall_candidate(ui)
    hud_v12.uninstall_candidate(ui)
    hud_v11.uninstall_candidate(ui)
    hud_v10.uninstall_candidate(ui)
    hud_v9.uninstall_candidate(ui)
    hud_v8.uninstall_candidate(ui)
    uninstall_v7(ui)
    uninstall_v6(ui)


def test_current_host_publishes_only_the_final_qml_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("ONYX_HUD_V6_CANDIDATE", "1")
    monkeypatch.setenv("ONYX_HUD_V7_LIVE", "1")
    monkeypatch.setenv(hud_v8.FLAG_NAME, "1")
    monkeypatch.setenv(hud_v9.FLAG_NAME, "1")
    monkeypatch.setattr(ui.MainWindow, "_check_config", lambda _self: True)
    monkeypatch.setattr(ui.MainWindow, "_create_desktop_shortcut", lambda _self: None)

    assert install_v6(ui) and install_v7(ui)
    assert hud_v8.install_candidate(ui) and hud_v9.install_candidate(ui)
    assert ui.install_current_hud_v10()

    window = ui.MainWindow("")
    window.show()
    QTest.qWait(200)
    app.processEvents()
    try:
        host = window._v5_host
        assert host is not None
        assert host.source_load_count == 1
        assert host._quick.rootObject().objectName() == hud_v17.ROOT_OBJECT
        assert window.findChildren(QQuickWidget) == [host._quick]
    finally:
        window.request_explicit_exit()
        window.deleteLater()
        app.processEvents()


def test_direct_base_resolution_rejects_untrusted_mro() -> None:
    class FakeHost:
        pass

    with pytest.raises(RuntimeError, match="direct base is unavailable"):
        hud_v11._accepted_direct_v5_base(ui, FakeHost)
