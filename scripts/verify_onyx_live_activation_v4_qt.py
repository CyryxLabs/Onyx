"""Real offscreen QApplication readback/rollback gate for Activation V4."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import sys
import threading
import time
import types
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt
from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.qt_compat import sip  # noqa: E402
import main  # noqa: E402
import ui  # noqa: E402
from core import onyx_live_activation_v4 as live  # noqa: E402


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

    def correct_name(self, value):
        self.snapshot = Snapshot(str(value))
        return self.snapshot

    def forget_name(self):
        self.snapshot = Snapshot()
        return self.snapshot


class ProbeProjection(QObject):
    def __init__(self, parent, mode="normal", value="Sir"):
        super().__init__(parent)
        self.mode = mode
        self.value = value
        self.calls = 0

    @property
    def ownerName(self):
        if self.mode == "getter_throws":
            raise RuntimeError("getter failure")
        return self.value

    def set_owner_name(self, value):
        self.calls += 1
        if self.mode == "noop":
            return
        if self.mode == "wrong":
            self.value = value + "!"
            return
        if self.mode == "rollback_noop":
            if self.calls == 1:
                self.value = value
            return
        if self.mode == "destroy":
            self.value = value
            sip.delete(self)
            return
        self.value = value


def make_controller(authority, timeout=0.3):
    value = live.OnyxLiveActivationV4(
        live.ActivationFlagsV4.from_canonical_environ(),
        live.preflight_host(main),
        authority_factory=lambda: authority,
        ui_timeout_seconds=timeout,
    )
    value.install()
    assert value.start() is live.ActivationV4State.READY
    return value


def make_window():
    # _check_config is false in this gate, so the tenth seam always has a live
    # real QLineEdit target to synchronise before construction completes.
    return ui.MainWindow("")


def close_setup(window):
    assert window._overlay is not None
    window._overlay.hide()
    window._overlay = None


def from_worker(app, function):
    result = []
    errors = []

    def invoke():
        try:
            result.append(function())
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=invoke, daemon=True)
    worker.start()
    deadline = time.monotonic() + 5
    while worker.is_alive() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    worker.join(0.2)
    assert not worker.is_alive(), "worker deadlocked"
    return result, errors


def dispose(app, controller, windows):
    for window in windows:
        if not sip.isdeleted(window):
            window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            window.close()
            window.deleteLater()
    for _ in range(5):
        app.processEvents()
    controller.rollback_installation()


def failure_scenario(app, mode, *, second_mode=None):
    authority = Authority()
    controller = make_controller(authority)
    first = make_window()
    close_setup(first)
    first_projection = ProbeProjection(first, mode)
    first._v5_projection = first_projection
    windows = [first]
    if second_mode is not None:
        second = make_window()
        close_setup(second)
        second_projection = ProbeProjection(second, second_mode)
        second._v5_projection = second_projection
        windows.append(second)
        first_projection.calls = 0
        second_projection.calls = 0
    _results, errors = from_worker(app, lambda: controller.set_name("Mismatch"))
    assert len(errors) == 1 and isinstance(errors[0], live.ActivationV4Error)
    assert controller.state is live.ActivationV4State.DEGRADED
    assert authority.snapshot.display_name is None
    message = str(errors[0])
    observed = (
        None if sip.isdeleted(first_projection) else first_projection.value,
        first_projection.calls,
        sip.isdeleted(first_projection),
    )
    dispose(app, controller, windows)
    return observed, message


def main_gate():
    app = QApplication.instance() or QApplication([])
    ui.HUD_V5_LIVE = False
    original_check = ui.MainWindow._check_config
    ui.MainWindow._check_config = lambda _self: False
    try:
        # Successful real targets: two windows, setup open/closed, worker
        # affinity, and exact readback for set/correct/forget.
        authority = Authority()
        active = make_controller(authority)
        first = make_window()
        second = make_window()
        close_setup(second)
        first_projection = ui._HudV5Projection(first, "Sir")
        second_projection = ui._HudV5Projection(second, "Sir")
        first._v5_projection = first_projection
        second._v5_projection = second_projection
        first_input = first._overlay._name_input
        setter_threads = []
        for projection in (first_projection, second_projection):
            original = projection.set_owner_name

            def tracked(value, call=original):
                setter_threads.append(QThread.currentThread())
                call(value)

            projection.set_owner_name = tracked

        for operation, expected in (
            (lambda: active.set_name("  Alice   Smith  "), "Alice Smith"),
            (lambda: active.correct_name("Renée"), "Renée"),
            (active.forget_name, "Sir"),
        ):
            results, errors = from_worker(app, operation)
            assert len(results) == 1 and not errors
            assert first_projection.ownerName == expected
            assert second_projection.ownerName == expected
            assert first_input.text() == expected
        assert setter_threads
        assert all(thread == first.thread() for thread in setter_threads)

        # A small direct GUI-thread performance gate also exercises the exact
        # direct-dispatch equality path without an event-loop wait.
        started = time.perf_counter()
        for index in range(64):
            active.correct_name(f"Owner {index}")
        elapsed = time.perf_counter() - started
        assert elapsed < 2.0
        active.forget_name()
        dispose(app, active, [first, second])

        no_op, no_op_message = failure_scenario(app, "noop")
        assert no_op[0] == "Sir"
        assert "UiApplyReadbackMismatch" in no_op_message

        wrong, wrong_message = failure_scenario(app, "wrong")
        assert wrong[0] != "Mismatch"
        assert "UiApplyReadbackMismatch" in wrong_message

        getter, getter_message = failure_scenario(app, "getter_throws")
        assert getter[1] == 0
        assert "RuntimeError" in getter_message

        rollback, compound_message = failure_scenario(
            app, "rollback_noop", second_mode="wrong"
        )
        assert rollback[0] == "Mismatch", rollback
        assert "rollback=UiRollbackReadbackMismatch" in compound_message

        destroyed, destroyed_message = failure_scenario(app, "destroy")
        assert destroyed[2]
        assert "UiTargetDestroyed" in destroyed_message
        assert "rollback=UiTargetDestroyed" in destroyed_message

        print("ONYX_LIVE_ACTIVATION_V4_QT_OK")
        print(
            "readback=set/correct/forget normalized=exact windows=2 "
            "setup=open/closed no-op=refused wrong=refused getter=refused "
            "rollback-no-op=compound destroyed=compound affinity=pass "
            f"direct64_ms={elapsed * 1000:.3f}"
        )
    finally:
        ui.MainWindow._check_config = original_check


if __name__ == "__main__":
    main_gate()
