from __future__ import annotations

import asyncio
import inspect
import threading

import pytest

import main as onyx_main


@pytest.mark.parametrize(
    ("requested", "terminal"),
    (
        ("provider-reconnect", "reconnect"),
        ("provider-resumption-reset", "reconnect"),
        ("provider-session-rotation", "reconnect"),
        ("qt-event-loop-ended", "shutdown"),
        ("voice-tool", "shutdown"),
        ("shutdown", "shutdown"),
    ),
)
def test_phase5_stop_normalizes_runtime_reasons_to_closed_contract(
    requested: str,
    terminal: str,
) -> None:
    events: list[str] = []
    accepted = {"kill", "revoke", "rollback", "end_session", "reconnect", "shutdown"}

    class Governance:
        def end_session(self, reason: str) -> None:
            assert reason in accepted
            events.append(f"governance:{reason}")

    class Bridge:
        def terminate(self, reason: str) -> None:
            assert reason in accepted
            events.append(f"bridge:{reason}")

    host = object.__new__(onyx_main.OnyxLive)
    host._governance_nucleus_v1 = Governance()
    host._phase5 = Bridge()
    host._phase5_cleanup_failures = []
    host._dashboard = None

    host._stop_phase5_session(requested)

    assert events == [f"governance:{terminal}", f"bridge:{terminal}"]
    assert host._phase5 is None
    assert host._phase5_cleanup_failures == []


def test_run_preserves_primary_error_and_attempts_every_cleanup_boundary() -> None:
    events: list[str] = []

    class UI:
        def write_log(self, value: str) -> None:
            events.append("log:" + value.split(":", 1)[0])

    class Phase11:
        def begin_shutdown(self) -> None:
            events.append("phase11.begin")
            raise OSError("begin failed")

        def close(self, timeout: float) -> None:
            events.append(f"phase11.close:{timeout}")
            raise PermissionError("close failed")

    class Worker:
        def start(self) -> bool:
            events.append("worker.start")
            return True

        def stop(self, timeout: float) -> bool:
            events.append(f"worker.stop:{timeout}")
            raise RuntimeError("stop failed")

    host = object.__new__(onyx_main.OnyxLive)
    host.ui = UI()
    host._phase11_missions = Phase11()
    host._mission_worker = Worker()
    host._shutdown_requested = threading.Event()
    host._runtime_task = None

    def stop_phase5(reason: str) -> None:
        events.append(f"phase5.stop:{reason}")
        raise ValueError("phase5 failed")

    async def run_live_loop() -> None:
        events.append("live.run")
        raise LookupError("primary runtime failure")

    host._stop_phase5_session = stop_phase5
    host._run_live_loop = run_live_loop

    with pytest.raises(LookupError, match="primary runtime failure") as raised:
        asyncio.run(host.run())

    assert "phase5.stop:shutdown" in events
    assert "phase11.begin" in events
    assert "worker.stop:15.0" in events
    assert "phase11.close:15.0" in events
    assert host._runtime_task is None
    assert any(
        "cleanup incomplete at Phase 5 session" in note
        for note in getattr(raised.value, "__notes__", ())
    )


def test_run_fails_closed_when_cleanup_is_incomplete_without_primary_error() -> None:
    events: list[str] = []

    class UI:
        def write_log(self, value: str) -> None:
            events.append(value)

    class Worker:
        def start(self) -> bool:
            return True

    host = object.__new__(onyx_main.OnyxLive)
    host.ui = UI()
    host._mission_worker = Worker()
    host._shutdown_requested = threading.Event()
    host._runtime_task = None

    async def run_live_loop() -> None:
        return None

    cleanup_failure = RuntimeError("injected incomplete cleanup")

    async def cleanup_runtime():
        return (("Mission worker", cleanup_failure),)

    host._run_live_loop = run_live_loop
    host._cleanup_runtime = cleanup_runtime

    with pytest.raises(
        onyx_main.RuntimeCleanupError,
        match="Mission worker",
    ) as raised:
        asyncio.run(host.run())

    assert raised.value.failures == (("Mission worker", cleanup_failure),)
    assert raised.value.__cause__ is cleanup_failure
    assert host._runtime_task is None


def test_run_normal_completion_remains_clean() -> None:
    class Worker:
        def start(self) -> bool:
            return True

    host = object.__new__(onyx_main.OnyxLive)
    host._mission_worker = Worker()
    host._shutdown_requested = threading.Event()
    host._runtime_task = None

    async def run_live_loop() -> None:
        return None

    async def cleanup_runtime():
        return ()

    host._run_live_loop = run_live_loop
    host._cleanup_runtime = cleanup_runtime

    assert asyncio.run(host.run()) is None
    assert host._runtime_task is None


def test_requested_shutdown_still_fails_closed_on_cleanup_error() -> None:
    events: list[str] = []

    class App:
        def quit(self) -> None:
            events.append("app.quit")

    class UI:
        _app = App()

        def write_log(self, value: str) -> None:
            events.append(value)

    class Worker:
        def start(self) -> bool:
            return True

    host = object.__new__(onyx_main.OnyxLive)
    host.ui = UI()
    host._mission_worker = Worker()
    host._shutdown_requested = threading.Event()
    host._shutdown_requested.set()
    host._runtime_task = None

    async def run_live_loop() -> None:
        raise asyncio.CancelledError()

    cleanup_failure = RuntimeError("injected shutdown cleanup failure")

    async def cleanup_runtime():
        return (("Phase 11", cleanup_failure),)

    host._run_live_loop = run_live_loop
    host._cleanup_runtime = cleanup_runtime

    with pytest.raises(onyx_main.RuntimeCleanupError, match="Phase 11"):
        asyncio.run(host.run())

    assert "app.quit" not in events
    assert any("Shutdown blocked safely" in item for item in events)
    assert host._runtime_task is None


def test_cleanup_supports_portable_runtime_without_phase11() -> None:
    events: list[str] = []

    class UI:
        def write_log(self, _value: str) -> None:
            raise AssertionError("successful cleanup must not log errors")

    class Worker:
        def stop(self, timeout: float) -> bool:
            events.append(f"worker.stop:{timeout}")
            return True

    host = object.__new__(onyx_main.OnyxLive)
    host.ui = UI()
    host._phase11_missions = None
    host._mission_worker = Worker()
    host._stop_phase5_session = lambda reason: events.append(
        f"phase5.stop:{reason}"
    )

    assert asyncio.run(host._cleanup_runtime()) == ()
    assert events == ["phase5.stop:shutdown", "worker.stop:15.0"]


def test_cleanup_continues_after_capability_kill_timeout_with_durable_latch_set() -> None:
    events: list[str] = []

    class UI:
        def write_log(self, value: str) -> None:
            events.append(f"log:{value}")

    class Composition:
        local_shutdown = False

        def shutdown(self) -> None:
            self.local_shutdown = True
            events.append("capability.shutdown")

    class Worker:
        def stop(self, timeout: float) -> bool:
            events.append(f"worker.stop:{timeout}")
            return True

    host = object.__new__(onyx_main.OnyxLive)
    host.ui = UI()
    host._capability_composition_v1 = Composition()
    host._phase11_missions = None
    host._mission_worker = Worker()
    host._stop_phase5_session = lambda reason: events.append(
        f"phase5.stop:{reason}"
    )

    async def bounded(boundary, action, *, timeout):
        result = action()
        if boundary == "Capability composition V1":
            assert timeout == 5.0
            assert host._capability_composition_v1.local_shutdown is True
            raise onyx_main.CleanupBoundaryTimeout("participant kill timed out")
        return result

    host._run_bounded_cleanup_action = bounded
    failures = asyncio.run(host._cleanup_runtime())

    assert failures[0][0] == "Capability composition V1"
    assert isinstance(failures[0][1], onyx_main.CleanupBoundaryTimeout)
    assert "phase5.stop:shutdown" in events
    assert "worker.stop:15.0" in events


def test_bridge_terminate_failure_is_aggregated_and_preserves_primary_error() -> None:
    events: list[str] = []
    termination_error = RuntimeError("injected bridge termination failure")

    class UI:
        def write_log(self, value: str) -> None:
            events.append(value)

    class Bridge:
        def terminate(self, reason: str) -> None:
            events.append(f"bridge.terminate:{reason}")
            raise termination_error

    class Worker:
        def start(self) -> bool:
            return True

        def stop(self, timeout: float) -> bool:
            events.append(f"worker.stop:{timeout}")
            return True

    host = object.__new__(onyx_main.OnyxLive)
    host.ui = UI()
    host._phase5 = Bridge()
    host._phase5_cleanup_failures = []
    host._dashboard = None
    host._governance_nucleus_v1 = None
    host._phase11_missions = None
    host._mission_worker = Worker()
    host._shutdown_requested = threading.Event()
    host._runtime_task = None

    async def run_live_loop() -> None:
        raise LookupError("primary runtime failure")

    host._run_live_loop = run_live_loop

    with pytest.raises(LookupError, match="primary runtime failure") as raised:
        asyncio.run(host.run())

    assert "bridge.terminate:shutdown" in events
    assert host._phase5 is None
    assert host._phase5_cleanup_failures == []
    assert any(
        "cleanup incomplete at Phase 5 bridge: RuntimeError" in note
        for note in getattr(raised.value, "__notes__", ())
    )


def test_bridge_terminate_failure_raises_runtime_cleanup_error_without_primary() -> None:
    termination_error = RuntimeError("injected bridge termination failure")

    class UI:
        def write_log(self, _value: str) -> None:
            pass

    class Bridge:
        def terminate(self, _reason: str) -> None:
            raise termination_error

    class Worker:
        def start(self) -> bool:
            return True

        def stop(self, _timeout: float) -> bool:
            return True

    host = object.__new__(onyx_main.OnyxLive)
    host.ui = UI()
    host._phase5 = Bridge()
    host._phase5_cleanup_failures = []
    host._dashboard = None
    host._governance_nucleus_v1 = None
    host._phase11_missions = None
    host._mission_worker = Worker()
    host._shutdown_requested = threading.Event()
    host._runtime_task = None
    host._run_live_loop = lambda: asyncio.sleep(0)

    with pytest.raises(
        onyx_main.RuntimeCleanupError,
        match="Phase 5 bridge",
    ) as raised:
        asyncio.run(host.run())

    assert raised.value.failures == (("Phase 5 bridge", termination_error),)
    assert raised.value.__cause__ is termination_error


def test_shutdown_tool_delegates_exit_to_clean_runtime_and_launcher_owner() -> None:
    source = inspect.getsource(onyx_main.OnyxLive._execute_tool_unbarriered)
    shutdown = source[source.index('elif name == "shutdown_onyx"') :]
    shutdown = shutdown[: shutdown.index("\n            else:")]

    assert '_begin_shutdown_sequence(' in shutdown
    assert '"voice-tool"' in shutdown
    assert "prompt_farewell=False" in shutdown
    assert "os._exit" not in shutdown
    assert "rollback_all" not in shutdown
    assert "_onyx_live_activation_v15" not in shutdown


def test_runtime_owns_and_cancels_dashboard_tasks_before_final_cleanup() -> None:
    run_source = inspect.getsource(onyx_main.OnyxLive._run_live_loop)
    cleanup_source = inspect.getsource(onyx_main.OnyxLive._cleanup_runtime)

    assert "self._dashboard_runtime_tasks = (" in run_source
    assert "task.cancel()" in cleanup_source
    assert "timeout=10.0" in cleanup_source
    assert 'await attempt("Dashboard runtime", stop_dashboard_tasks)' in cleanup_source


def test_cross_thread_shutdown_is_idempotent_and_cancels_on_the_owner_loop() -> None:
    events: list[str] = []

    class UI:
        def write_log(self, value: str) -> None:
            events.append(value)

    class Task:
        def cancel(self) -> None:
            events.append("task.cancel")

    class Loop:
        def call_soon_threadsafe(self, callback) -> None:
            events.append("loop.dispatch")
            callback()

    host = object.__new__(onyx_main.OnyxLive)
    host.ui = UI()
    host._shutdown_requested = threading.Event()
    host._runtime_task = Task()
    host._loop = Loop()

    assert host.request_shutdown("qt-event-loop-ended") is True
    assert host.request_shutdown("duplicate") is False
    assert host._shutdown_requested.is_set()
    assert events.count("loop.dispatch") == 1
    assert events.count("task.cancel") == 1
    assert sum("Runtime shutdown requested" in item for item in events) == 1


def test_main_runtime_thread_is_owned_and_joined_after_qt_returns() -> None:
    source = inspect.getsource(onyx_main.main)

    assert "daemon=True" in source
    assert 'name="onyx-live-runtime"' in source
    assert 'request_shutdown("qt-event-loop-ended")' in source
    assert "runtime_thread.join(timeout=0.5 if force_exit else 60.0)" in source
    assert "final daemon isolation" in source


def test_live_loop_does_not_swallow_explicit_task_cancellation() -> None:
    source = inspect.getsource(onyx_main.OnyxLive._run_live_loop)

    cancellation = source.index("except asyncio.CancelledError:")
    broad = source.index("except BaseException as e:")
    assert cancellation < broad
    assert "while not self._shutdown_requested.is_set():" in source
    assert "if self._shutdown_requested.is_set():\n                return" in source
