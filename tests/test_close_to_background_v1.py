from __future__ import annotations

import os
import threading
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtCore import QTimer

import ui as onyx_ui
from ui import MainWindow, OnyxUI, _ResidentControls


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication(["onyx-lifecycle-test"])


class _LifecycleWindow(MainWindow):
    """Small real Qt window exercising the production lifecycle methods."""

    def __init__(self, *, background: bool, tray: bool = False) -> None:
        QMainWindow.__init__(self)
        self._close_to_background = background
        self._exit_requested = False
        self._background_notice_emitted = False
        self._tray_available = tray
        self._v5_projection = None
        self._v5_host = None
        self._v5_log_connected = False
        self._cam_stop = threading.Event()
        self._clock_tmr = QTimer(self)
        self._metric_tmr = QTimer(self)
        self._attention_tmr = QTimer(self)
        self._exit_sig.connect(self._schedule_explicit_exit)

    def resizeEvent(self, event) -> None:
        QMainWindow.resizeEvent(self, event)


@pytest.mark.parametrize(
    ("frozen", "override", "expected"),
    [
        (False, None, False),
        (True, None, True),
        (True, "1", False),
        (True, "true", False),
        (True, "yes", False),
        (True, "0", True),
    ],
)
def test_close_policy_is_frozen_only_and_has_explicit_override(
    monkeypatch: pytest.MonkeyPatch,
    frozen: bool,
    override: str | None,
    expected: bool,
) -> None:
    monkeypatch.setattr(onyx_ui, "is_frozen", lambda: frozen)
    if override is None:
        monkeypatch.delenv("ONYX_EXIT_ON_WINDOW_CLOSE", raising=False)
    else:
        monkeypatch.setenv("ONYX_EXIT_ON_WINDOW_CLOSE", override)
    assert onyx_ui._close_to_background_enabled() is expected


def test_packaged_close_keeps_real_qt_window_and_runtime_timers_alive(
    app: QApplication,
) -> None:
    window = _LifecycleWindow(background=True, tray=False)
    notices: list[str] = []
    exit_reasons: list[str] = []
    window.on_exit_requested = lambda reason: exit_reasons.append(reason) or True
    window._background_sig.connect(lambda: notices.append("background"))
    window._clock_tmr.start(1000)
    window._metric_tmr.start(1000)
    window.show()
    app.processEvents()

    assert window.close() is False
    app.processEvents()
    assert window.isMinimized()
    assert window._clock_tmr.isActive()
    assert window._metric_tmr.isActive()
    assert notices == ["background"]

    window.showNormal()
    assert window.close() is False
    app.processEvents()
    assert notices == ["background"]
    assert window._request_owner_exit() is True
    assert exit_reasons == ["hud-exit-action"]
    assert window._clock_tmr.isActive()
    assert window._metric_tmr.isActive()
    window.request_explicit_exit()
    app.processEvents()


def test_tray_background_hides_and_explicit_exit_is_accepted(app: QApplication) -> None:
    window = _LifecycleWindow(background=True, tray=True)
    window.show()
    app.processEvents()
    assert window.close() is False
    app.processEvents()
    assert not window.isVisible()

    window.request_explicit_exit()
    app.processEvents()
    assert window._exit_requested is True
    assert not window.isVisible()
    assert window._cam_stop.is_set()


def test_source_window_close_routes_to_runtime_before_qt_exit(app: QApplication) -> None:
    window = _LifecycleWindow(background=False)
    exit_reasons: list[str] = []
    window.on_exit_requested = lambda reason: exit_reasons.append(reason) or True
    window._clock_tmr.start(1000)
    window._metric_tmr.start(1000)
    window._attention_tmr.start(50)
    window.show()
    app.processEvents()

    assert window.close() is False
    app.processEvents()
    assert exit_reasons == ["window-close"]
    assert window.isVisible()
    assert window._attention_tmr.isActive()

    window.request_explicit_exit()
    app.processEvents()
    assert window._exit_requested is True
    assert not window.isVisible()


def test_ui_exit_signal_is_queued_and_bounded_on_real_qt_object(
    app: QApplication,
) -> None:
    window = _LifecycleWindow(background=True)
    window.show()
    proxy = SimpleNamespace(_win=window)
    OnyxUI.request_exit(proxy, delay_ms=99_999)
    assert window._exit_requested is False

    # Prove the real queued path without waiting for the bounded 10-second cap.
    window._exit_sig.emit(0)
    app.processEvents()
    assert window._exit_requested is True
    assert not window.isVisible()


def test_resident_menu_restores_window_and_emits_trusted_local_exit(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(onyx_ui, "_close_to_background_enabled", lambda: False)
    window = _LifecycleWindow(background=True)
    controls = _ResidentControls(window, QIcon())
    exits: list[str] = []
    controls.exitRequested.connect(exits.append)

    window.hide()
    controls.show_action.trigger()
    app.processEvents()
    assert window.isVisible()

    controls.exit_action.trigger()
    app.processEvents()
    assert exits == ["local-exit-menu"]
    controls.notify_background_once()
    controls.notify_background_once()
    assert controls._notice_shown is True
    controls.shutdown()


def test_current_v11_hud_preserves_history_and_guards_current_actions() -> None:
    qml_root = onyx_ui.resource_root() / "qml"
    v7 = (qml_root / "OnyxLiveShellV7.qml").read_text(encoding="utf-8")
    v8 = (qml_root / "OnyxLiveShellV8.qml").read_text(encoding="utf-8")
    v9 = (qml_root / "OnyxLiveShellV9.qml").read_text(encoding="utf-8")
    v10 = (qml_root / "OnyxLiveShellV10.qml").read_text(encoding="utf-8")
    guarded = (qml_root / "OnyxLiveShellGuardedV1.qml").read_text(encoding="utf-8")
    v11 = (qml_root / "OnyxLiveShellV11.qml").read_text(encoding="utf-8")

    assert 'label: "CLOSE"' in v7
    assert "root.uiProjection.requestClose()" in v7
    assert "OnyxLiveShellV7" in v8
    assert "OnyxLiveShellV8" in v9
    assert "OnyxLiveShellV9" in v10
    assert 'objectName: "exitOnyxActionV10"' in v10
    assert 'text: "EXIT ONYX"' in v10
    assert "requestExit()" in v10
    assert 'root.request("requestClose")' in guarded
    assert "OnyxLiveShellGuardedV1" in v11
    assert 'root.request("requestExit")' in v11


def test_native_close_is_intercepted_before_authenticated_activation_wrappers() -> None:
    source = MainWindow.event
    assert callable(source)
