"""Real offscreen Qt gate for V6's inherited single setup projection."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import sys
import types
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.qt_compat import sip  # noqa: E402
import main  # noqa: E402
import ui  # noqa: E402
from core import onyx_live_activation_v6 as live  # noqa: E402


class Snapshot:
    def __init__(self, name=None):
        self.display_name = name
        self.reconciled = True
        self.state = types.SimpleNamespace(value="known" if name else "unknown")

    @property
    def name_known(self):
        return self.display_name is not None


class Authority:
    def __init__(self):
        self.snapshot = Snapshot()

    def reconcile(self):
        return self.snapshot

    def begin_contact(self):
        return "Before we continue, what name should I use for you?"

    def prompt_directive(self):
        return "owner-directive"

    def set_name(self, value):
        self.snapshot = Snapshot(str(value))
        return self.snapshot

    correct_name = set_name

    def forget_name(self):
        self.snapshot = Snapshot()
        return self.snapshot


def main_gate():
    app = QApplication.instance() or QApplication([])
    original_check = ui.MainWindow._check_config
    original_hud = ui.HUD_V5_LIVE
    ui.MainWindow._check_config = lambda _self: False
    ui.HUD_V5_LIVE = True
    controller = live.OnyxLiveActivationV6(
        live.ActivationFlagsV6.from_canonical_environ(
            live.exact_activation_environment()
        ),
        live.preflight_host(main),
        authority_factory=Authority,
    )
    window = None
    try:
        controller.install()
        assert controller.start() is live.ActivationV6State.READY
        window = ui.MainWindow("")
        window.show()
        for _ in range(8):
            app.processEvents()
        assert window._hud_v5_live
        assert window._v5_host is not None and not window._v5_host._loaded
        first = window._overlay
        assert first is not None and first.isVisible()
        assert first._name_input.isEnabled() and first._name_input.isVisible()
        assert first._key_input.isVisible()
        visible = [
            item for item in window.findChildren(ui.SetupOverlay) if item.isVisible()
        ]
        assert visible == [first]
        window._show_setup()
        window._show_setup()
        app.processEvents()
        assert window._overlay is first
        assert [
            item for item in window.findChildren(ui.SetupOverlay) if item.isVisible()
        ] == [first]
        assert window.centralWidget().objectName() == "OnyxCinematicSurfaceV5"
        first.hide()
        window._overlay = None
        window._v5_host.load_source()
        window._v5_host.show()
        window._v5_host.sync_animation()
        app.processEvents()
        assert window._v5_host._loaded and window._hud_v5_live
        assert not any(
            item.isVisible() for item in window.findChildren(ui.SetupOverlay)
        )
        print("ONYX_LIVE_ACTIVATION_V6_QT_OK")
        print(
            "setup_surfaces=1 repeated_requests=idempotent hud=v5 "
            "setup_controls=accessible renderer=suspended/resumed"
        )
    finally:
        if window is not None and not sip.isdeleted(window):
            window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            window.close()
            window.deleteLater()
            app.processEvents()
        controller.rollback_installation()
        ui.MainWindow._check_config = original_check
        ui.HUD_V5_LIVE = original_hud


if __name__ == "__main__":
    main_gate()
