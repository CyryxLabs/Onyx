from __future__ import annotations

import asyncio
import inspect
import threading
import time

import pytest

import main as onyx_main


def _farewell_host() -> object:
    host = object.__new__(onyx_main.OnyxLive)
    host._shutdown_farewell_complete = asyncio.Event()
    host._shutdown_farewell_turn = onyx_main._ShutdownFarewellTurn(
        host._shutdown_farewell_complete
    )
    host._provider_turn_counter = 0
    host._provider_turn_active = None
    host._provider_turn_complete_event = asyncio.Event()
    host._provider_turn_complete_event.set()
    return host


def test_farewell_barrier_requires_exact_turn_and_its_audio_drain() -> None:
    async def exercise() -> None:
        host = _farewell_host()
        farewell = host._shutdown_farewell_turn
        farewell.bind(7)
        farewell.enqueue_audio(7)

        farewell.provider_finished(6)
        farewell.audio_drained(6, played=True)
        assert not host._shutdown_farewell_complete.is_set()

        farewell.provider_finished(7)
        assert not host._shutdown_farewell_complete.is_set()
        farewell.audio_drained(7, played=True)
        assert host._shutdown_farewell_complete.is_set()

    asyncio.run(exercise())


def test_failed_audio_write_cannot_claim_farewell_completion() -> None:
    async def exercise() -> None:
        host = _farewell_host()
        farewell = host._shutdown_farewell_turn
        farewell.bind(3)
        farewell.enqueue_audio(3)
        farewell.provider_finished(3)
        farewell.audio_drained(3, played=False)
        assert not host._shutdown_farewell_complete.is_set()

    asyncio.run(exercise())


def test_local_exit_binds_only_the_next_provider_generation() -> None:
    events: list[str] = []

    async def exercise() -> None:
        host = _farewell_host()

        class Session:
            async def send_client_content(self, **_payload) -> None:
                events.append("farewell.sent")
                assert host._shutdown_farewell_turn.turn_id == 12
                host._shutdown_farewell_turn.provider_finished(11)
                assert not host._shutdown_farewell_complete.is_set()
                host._shutdown_farewell_turn.enqueue_audio(12)
                host._shutdown_farewell_turn.provider_finished(12)
                host._shutdown_farewell_turn.audio_drained(12, played=True)

        class UI:
            def write_log(self, value: str) -> None:
                events.append(value)

        host.ui = UI()
        host.session = Session()
        host._provider_turn_counter = 11
        host.request_shutdown = lambda reason: events.append(f"shutdown:{reason}")
        await host._coordinate_shutdown_after_farewell(
            "local-exit",
            prompt_farewell=True,
        )

    asyncio.run(exercise())
    assert events == ["farewell.sent", "shutdown:local-exit"]


def test_shutdown_input_barrier_drains_realtime_queue_and_rejects_new_text() -> None:
    events: list[str] = []

    class UI:
        def write_log(self, value: str) -> None:
            events.append(value)

    host = object.__new__(onyx_main.OnyxLive)
    host.ui = UI()
    host._shutdown_input_quiesced = threading.Event()
    host._phone_active = True
    host.out_queue = asyncio.Queue()
    host.out_queue.put_nowait({"data": b"old microphone audio"})
    host._quiesce_runtime_input()
    host._on_text_command("new remote command")

    assert host._shutdown_input_quiesced.is_set()
    assert host._phone_active is False
    assert host.out_queue.empty()
    assert any("input barrier active" in item for item in events)
    assert any("Text input ignored" in item for item in events)

    microphone = inspect.getsource(onyx_main.OnyxLive._listen_audio)
    relay = inspect.getsource(onyx_main.OnyxLive._relay_phone_audio)
    sender = inspect.getsource(onyx_main.OnyxLive._send_realtime)
    assert "_runtime_input_is_quiesced()" in microphone
    assert "_runtime_input_is_quiesced()" in relay
    assert "_runtime_input_is_quiesced()" in sender


def test_hung_cleanup_is_bounded_and_runs_only_on_a_daemon_boundary() -> None:
    observed: list[bool] = []
    release = threading.Event()

    def hung() -> None:
        observed.append(threading.current_thread().daemon)
        release.wait(2.0)

    host = object.__new__(onyx_main.OnyxLive)
    started = time.monotonic()
    try:
        with pytest.raises(onyx_main.CleanupBoundaryTimeout):
            asyncio.run(
                host._run_bounded_cleanup_action(
                    "Injected hung cleanup",
                    hung,
                    timeout=0.05,
                )
            )
    finally:
        release.set()

    assert observed == [True]
    assert time.monotonic() - started < 0.75


def test_cleanup_failure_keeps_qt_resident_and_surfaces_recovery_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class UI:
        def request_exit(self) -> None:
            events.append("qt.exit")

        def set_state(self, value: str) -> None:
            events.append(f"state:{value}")

        def write_log(self, value: str) -> None:
            events.append(value)

        def show_content(self, title: str, _text: str) -> None:
            events.append(f"surface:{title}")

    class Worker:
        def start(self) -> bool:
            return True

    host = object.__new__(onyx_main.OnyxLive)
    host.ui = UI()
    host._mission_worker = Worker()
    host._shutdown_requested = threading.Event()
    host._shutdown_requested.set()
    host._runtime_task = None
    host._cleanup_complete = threading.Event()
    host._cleanup_watchdog = None
    host._run_live_loop = lambda: asyncio.sleep(0)
    failure = RuntimeError("cleanup failed")
    host._cleanup_runtime = lambda: asyncio.sleep(
        0, result=(("Injected boundary", failure),)
    )
    monkeypatch.setattr(onyx_main, "runtime_dir", lambda: (_ for _ in ()).throw(OSError()))

    with pytest.raises(onyx_main.RuntimeCleanupError):
        asyncio.run(host.run())

    assert "qt.exit" not in events
    assert "state:ERROR" in events
    assert "surface:SHUTDOWN BLOCKED" in events
    assert any("Shutdown blocked safely" in item for item in events)


def test_runtime_cleanup_has_no_unbounded_to_thread_waits() -> None:
    cleanup = inspect.getsource(onyx_main.OnyxLive._cleanup_runtime)
    assert "asyncio.to_thread" not in cleanup
    assert "_run_bounded_cleanup_action" in cleanup
    assert "timeout=17.0" in cleanup
