"""Real offscreen QApplication affinity/atomicity gate for Activation V3."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import sys
import threading
import time
import types
from pathlib import Path

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import ui  # noqa: E402
from core import onyx_live_activation_v3 as live  # noqa: E402


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


def controller(authority, timeout=0.3):
    value = live.OnyxLiveActivationV3(
        live.ActivationFlagsV3.from_canonical_environ(),
        live.preflight_host(main),
        authority_factory=lambda: authority,
        ui_timeout_seconds=timeout,
    )
    value.install()
    assert value.start() is live.ActivationV3State.READY
    return value


def window_with_projection():
    window = ui.MainWindow("")
    projection = ui._HudV5Projection(window, "Sir")
    window._v5_projection = projection
    return window, projection


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


def dispose(app, windows):
    for window in windows:
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        window.close()
        window.deleteLater()
    for _ in range(5):
        app.processEvents()


def main_gate():
    app = QApplication.instance() or QApplication([])
    ui.HUD_V5_LIVE = False
    original_check = ui.MainWindow._check_config
    ui.MainWindow._check_config = lambda _self: True
    try:
        # Successful set/correct/forget: two real windows, one open setup overlay.
        authority = Authority()
        active = controller(authority)
        first, first_projection = window_with_projection()
        second, second_projection = window_with_projection()
        first._show_setup()
        assert first._overlay is not None and second._overlay is None
        first_input = first._overlay._name_input
        setter_threads = []
        for projection in (first_projection, second_projection):
            original = projection.set_owner_name

            def tracked(value, call=original):
                setter_threads.append(QThread.currentThread())
                call(value)

            projection.set_owner_name = tracked
        original_input_set = first_input.setText

        def tracked_input(value):
            setter_threads.append(QThread.currentThread())
            original_input_set(value)

        first_input.setText = tracked_input

        for operation, expected in (
            (lambda: active.set_name("Alice"), "Alice"),
            (lambda: active.correct_name("Renée"), "Renée"),
            (active.forget_name, "Sir"),
        ):
            results, errors = from_worker(app, operation)
            assert not errors and len(results) == 1
            assert first_projection.ownerName == expected
            assert second_projection.ownerName == expected
            assert first_input.text() == expected
        assert setter_threads
        assert all(thread == first.thread() for thread in setter_threads)

        # Mutate-then-raise on the final target rolls back every prior target and
        # compensates the already-committed durable owner operation.
        second._show_setup()
        second_input = second._overlay._name_input
        second_previous = second_input.text()
        original_second_set = second_input.setText
        fail_once = [True]

        def mutate_then_raise(value):
            original_second_set(value)
            if fail_once[0]:
                fail_once[0] = False
                raise RuntimeError("mutate then raise")

        second_input.setText = mutate_then_raise
        _results, errors = from_worker(app, lambda: active.set_name("Bob"))
        assert len(errors) == 1 and isinstance(errors[0], live.ActivationV3Error)
        assert active.state is live.ActivationV3State.DEGRADED
        assert authority.snapshot.display_name is None
        assert first_projection.ownerName == "Sir"
        assert second_projection.ownerName == "Sir"
        assert first_input.text() == "Sir"
        # Rollback restores the value that this real setup surface displayed.
        # It must not assume a machine-specific default or persisted owner.
        assert second_input.text() == second_previous
        active.rollback_installation()
        dispose(app, [first, second])

        # No event-loop pumping: timeout cancels before queued delivery, leaves
        # the QObject untouched, compensates durable state, and stays degraded.
        timeout_authority = Authority()
        timeout_controller = controller(timeout_authority, timeout=0.05)
        timed_window, timed_projection = window_with_projection()
        errors = []

        def timed_operation():
            try:
                timeout_controller.set_name("Late")
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=timed_operation, daemon=True)
        worker.start()
        worker.join(1)
        assert not worker.is_alive() and len(errors) == 1
        assert timeout_controller.state is live.ActivationV3State.DEGRADED
        assert timeout_authority.snapshot.display_name is None
        app.processEvents()
        assert timed_projection.ownerName == "Sir"
        timeout_controller.rollback_installation()
        dispose(app, [timed_window])

        # Dispatcher teardown wakes/refuses requests without any UI mutation.
        closed_authority = Authority()
        closed_controller = controller(closed_authority)
        closed_window, _closed_projection = window_with_projection()
        endpoint = closed_window._onyx_owner_ui_dispatcher_v3._endpoint
        dispose(app, [closed_window])
        assert endpoint.is_closed
        results, errors = from_worker(app, lambda: closed_controller.set_name("Nope"))
        assert not results and len(errors) == 1
        assert closed_controller.state is live.ActivationV3State.DEGRADED
        assert closed_authority.snapshot.display_name is None
        closed_controller.rollback_installation()

        print("ONYX_LIVE_ACTIVATION_V3_QT_OK")
        print(
            "affinity=set/correct/forget setup=open/closed windows=2 "
            "atomic_rollback=mutate-then-raise timeout=fail-closed teardown=closed"
        )
    finally:
        ui.MainWindow._check_config = original_check


if __name__ == "__main__":
    main_gate()
