from __future__ import annotations

import asyncio
import inspect
import json
import threading

import pytest

import main as onyx_main


def test_farewell_needs_real_tagged_pcm_before_completion() -> None:
    async def exercise() -> None:
        complete = asyncio.Event()
        farewell = onyx_main._ShutdownFarewellTurn(complete)
        farewell.bind(41)
        farewell.provider_finished(41)
        assert farewell.provider_complete is True
        assert farewell.audio_seen is False
        assert not complete.is_set()

        farewell.enqueue_audio(41)
        assert farewell.audio_seen is True
        assert not complete.is_set()
        farewell.audio_drained(41, played=True)
        assert complete.is_set()

    asyncio.run(exercise())


def test_shutdown_quiesce_discards_old_pcm_and_realtime_input() -> None:
    events: list[str] = []

    class UI:
        muted = False

        def write_log(self, value: str) -> None:
            events.append(value)

        def set_state(self, _value: str) -> None:
            pass

        def set_audio_level(self, _value: float) -> None:
            pass

    host = object.__new__(onyx_main.OnyxLive)
    host.ui = UI()
    host._shutdown_input_quiesced = threading.Event()
    host._external_action_tasks = set()
    host._phone_active = True
    host._pending_vision = (b"x", "image/png", "question", "screen")
    host._vision_close_pending = True
    host._vision_busy = True
    host._turn_done_event = None
    host._speaking_lock = threading.Lock()
    host._is_speaking = True
    host.out_queue = asyncio.Queue()
    host.audio_in_queue = asyncio.Queue()
    host.out_queue.put_nowait({"data": b"old mic"})
    host.audio_in_queue.put_nowait((3, b"old playback"))

    host._quiesce_runtime_input()

    assert host.out_queue.empty()
    assert host.audio_in_queue.empty()
    assert host._pending_vision is None
    assert host._phone_active is False
    assert any("input barrier active" in item for item in events)


def test_global_tool_barrier_refuses_dispatch_after_shutdown() -> None:
    async def exercise() -> None:
        host = object.__new__(onyx_main.OnyxLive)
        host._shutdown_input_quiesced = threading.Event()
        host._shutdown_input_quiesced.set()
        host._external_action_tasks = set()
        called = False

        async def forbidden(_fc):
            nonlocal called
            called = True

        host._execute_tool_unbarriered = forbidden
        fc = type("Call", (), {"name": "send_message", "id": "v35"})()
        response = await host._execute_tool(fc)
        assert called is False
        assert "shutdown is already in progress" in response.response["result"]

    asyncio.run(exercise())


def test_timed_out_cleanup_worker_blocks_dependent_cleanup() -> None:
    async def exercise() -> None:
        host = object.__new__(onyx_main.OnyxLive)
        host._cleanup_worker_guard = threading.Lock()
        host._active_cleanup_worker = None
        release = threading.Event()
        second_called = False

        def hung() -> None:
            release.wait(2.0)

        with pytest.raises(onyx_main.CleanupBoundaryTimeout):
            await host._run_bounded_cleanup_action("first", hung, timeout=0.03)

        def second() -> None:
            nonlocal second_called
            second_called = True

        with pytest.raises(onyx_main.CleanupBoundaryTimeout, match="not started"):
            await host._run_bounded_cleanup_action("second", second, timeout=0.03)
        assert second_called is False
        release.set()

    asyncio.run(exercise())


def test_provider_batch_stops_after_shutdown_tool_and_recovery_is_actionable() -> None:
    receiver = inspect.getsource(onyx_main.OnyxLive._receive_audio)
    failure = inspect.getsource(onyx_main.OnyxLive._surface_shutdown_cleanup_failure)
    recovery = inspect.getsource(onyx_main.OnyxLive._present_active_shutdown_recovery)
    assert "if self._runtime_input_is_quiesced():\n                                break" in receiver
    assert "_present_active_shutdown_recovery" in failure
    assert "present_shutdown_recovery" in recovery
    assert "request_retry_shutdown" in recovery
    assert "force_exit_after_cleanup_failure" in recovery


def test_blocking_actions_are_daemon_tracked_and_block_dependent_cleanup() -> None:
    async def exercise() -> None:
        host = object.__new__(onyx_main.OnyxLive)
        host._shutdown_input_quiesced = threading.Event()
        host._blocking_action_guard = threading.Lock()
        host._blocking_action_serial_lock = threading.Lock()
        host._blocking_action_workers = set()
        release = threading.Event()
        observed: list[bool] = []

        def blocking() -> str:
            observed.append(threading.current_thread().daemon)
            release.wait(2.0)
            return "done"

        task = asyncio.create_task(host._run_external_action(blocking, timeout=1.0))
        while not host._blocking_action_workers:
            await asyncio.sleep(0)
        with pytest.raises(onyx_main.CleanupBoundaryTimeout):
            await host._drain_external_actions_for_shutdown(timeout=0.03)
        assert observed == [True]
        release.set()
        assert await task == "done"
        await host._drain_external_actions_for_shutdown(timeout=0.1)

    asyncio.run(exercise())


def test_dispatcher_has_no_untracked_default_executor_boundaries() -> None:
    source = inspect.getsource(onyx_main.OnyxLive._execute_tool_unbarriered)
    assert "asyncio.to_thread" not in source
    assert "run_in_executor" not in source
    assert "_run_external_action" in source


def test_force_exit_records_daemon_limitations_and_releases_qt(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    class UI:
        def write_log(self, message: str) -> None:
            events.append(message)

        def set_state(self, state: str) -> None:
            events.append(f"state:{state}")

        def show_content(self, title: str, message: str) -> None:
            events.append(f"content:{title}:{message}")

        def present_shutdown_recovery(self, message, retry, force) -> None:
            events.append("recovery.presented")

        def request_exit(self) -> None:
            events.append("qt.exit")

    host = object.__new__(onyx_main.OnyxLive)
    host.ui = UI()
    host._force_exit_authorized = threading.Event()
    host._shutdown_worker_snapshot = lambda: {
        "external_actions": [],
        "cleanup_worker": {
            "boundary": "PortAudio playback",
            "alive": True,
            "daemon": True,
            "completed": False,
        },
        "audio_workers": [],
        "all_observed_workers_daemon": True,
    }
    failures = (
        ("PortAudio playback", onyx_main.CleanupBoundaryTimeout("hung")),
    )
    monkeypatch.setattr(onyx_main, "runtime_dir", lambda: tmp_path)

    host._surface_shutdown_cleanup_failure(failures)
    escalation = tmp_path / "shutdown-escalation-v1.json"
    assert escalation.is_file()
    assert host._shutdown_escalation_persisted is True
    capability = host._shutdown_recovery_capability
    assert isinstance(capability, str) and len(capability) == 64
    assert host.force_exit_after_cleanup_failure("not-the-capability") is False
    assert host.force_exit_after_cleanup_failure(capability) is True
    assert host.force_exit_after_cleanup_failure(capability) is False
    assert host._force_exit_authorized.is_set()
    assert events[-1] == "qt.exit"
    receipt = json.loads(
        (tmp_path / "shutdown-force-exit-v1.json").read_text(encoding="utf-8")
    )
    assert receipt["known_workers_daemon_isolated"] is True
    assert receipt["installer_ipc_available"] is False
    assert "does not prove success" in receipt["limitations"]
