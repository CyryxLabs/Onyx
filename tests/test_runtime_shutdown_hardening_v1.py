from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

import main as onyx_main


def _bare_host(ui) -> onyx_main.OnyxLive:
    host = object.__new__(onyx_main.OnyxLive)
    host.ui = ui
    host._blocking_action_guard = threading.Lock()
    host._blocking_action_serial_lock = threading.Lock()
    host._blocking_action_workers = set()
    host._cleanup_worker_guard = threading.Lock()
    host._active_cleanup_worker = None
    host._cleanup_retry_guard = threading.Lock()
    host._cleanup_retry_active = False
    host._cleanup_complete = threading.Event()
    host._audio_capture_worker = None
    host._audio_playback_worker = None
    host._shutdown_input_quiesced = threading.Event()
    host._shutdown_cleanup_failures = ()
    host._shutdown_recovery_active = False
    host._shutdown_recovery_message = ""
    host._shutdown_recovery_capability = None
    host._shutdown_escalation_persisted = False
    host._force_exit_authorized = threading.Event()
    return host


def test_ui_external_work_is_runtime_owned_and_quiesced() -> None:
    async def exercise() -> None:
        completed = asyncio.Event()
        result: list[object] = []
        host = _bare_host(SimpleNamespace())
        host._loop = asyncio.get_running_loop()
        host._runtime_task = asyncio.current_task()

        def done(value, error) -> None:
            result.extend((value, error))
            completed.set()

        assert host._dispatch_ui_worker("dayops-status", lambda: "ok", done) is True
        await asyncio.wait_for(completed.wait(), timeout=2.0)
        assert result == ["ok", None]
        await host._drain_external_actions_for_shutdown(timeout=1.0)

        host._shutdown_input_quiesced.set()
        assert host._dispatch_ui_worker("file-intake", lambda: "late", done) is False

    asyncio.run(exercise())


def test_recovery_stays_live_and_force_capability_is_single_use(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    presented: list[tuple[str, object, object]] = []
    exits: list[str] = []
    ui = SimpleNamespace(
        set_state=lambda _state: None,
        write_log=lambda _message: None,
        show_content=lambda _title, _message: None,
        present_shutdown_recovery=lambda message, retry, force: presented.append(
            (message, retry, force)
        ),
        request_exit=lambda: exits.append("exit"),
    )
    host = _bare_host(ui)
    monkeypatch.setattr(onyx_main, "runtime_dir", lambda: tmp_path)
    failure = (("Mission worker", RuntimeError("still active")),)

    host._surface_shutdown_cleanup_failure(failure)
    assert host._shutdown_recovery_active is True
    assert host._shutdown_escalation_persisted is True
    assert len(presented) == 1
    escalation = json.loads(
        (tmp_path / "shutdown-escalation-v1.json").read_text(encoding="utf-8")
    )
    assert escalation["boundaries"][0]["name"] == "Mission worker"
    assert escalation["worker_state"]["external_actions"] == []

    # A later HUD/tray EXIT re-presents the same active recovery surface.
    assert host.request_owner_shutdown("tray-exit") is True
    assert len(presented) == 2
    force = presented[-1][2]
    assert force() is True
    assert exits == ["exit"]
    assert host._force_exit_authorized.is_set()
    assert force() is False
    receipt = json.loads(
        (tmp_path / "shutdown-force-exit-v1.json").read_text(encoding="utf-8")
    )
    assert receipt["cleanup_failure_observed"] is True
    assert receipt["recovery_active_at_confirmation"] is True
    assert receipt["capability_consumed"] is True


def test_force_exit_without_persisted_failure_is_denied() -> None:
    host = _bare_host(SimpleNamespace(write_log=lambda _message: None))
    assert host.force_exit_after_cleanup_failure("invented") is False
    assert not host._force_exit_authorized.is_set()


def test_retry_refuses_to_race_a_live_registered_worker() -> None:
    calls: list[str] = []
    ui = SimpleNamespace(
        present_shutdown_recovery=lambda *_args: calls.append("presented")
    )
    host = _bare_host(ui)
    host._shutdown_recovery_active = True
    host._shutdown_recovery_message = "blocked"
    host._shutdown_recovery_capability = "token"
    record = onyx_main._TrackedBlockingAction("dayops")
    host._blocking_action_workers.add(record)
    assert host.request_retry_shutdown() is False
    assert calls == ["presented"]


def test_raw_output_underflow_is_observed_without_killing_playback() -> None:
    worker = onyx_main._PortAudioPlaybackWorker()
    completed, outcome = worker.write(b"\x00\x00")
    worker._callback(
        bytearray(2),
        1,
        None,
        SimpleNamespace(output_underflow=True),
    )
    assert completed.wait(1.0)
    assert outcome == {"played": True}
    assert worker.output_underflows == 1
    assert not worker.stop_requested.is_set()


def test_playback_stop_interrupts_callback_stream_without_a_blocking_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations: list[tuple[str, str]] = []

    class Stream:
        def __init__(self, **kwargs) -> None:
            assert callable(kwargs["callback"])

        def start(self) -> None:
            operations.append(("start", threading.current_thread().name))

        def abort(self) -> None:
            operations.append(("abort", threading.current_thread().name))

        def close(self) -> None:
            operations.append(("close", threading.current_thread().name))

    monkeypatch.setattr(onyx_main.sd, "RawOutputStream", Stream)
    worker = onyx_main._PortAudioPlaybackWorker()
    worker.start()
    assert worker.started.wait(1.0)
    worker.request_stop()
    assert worker.stopped.wait(1.0)
    assert operations == [
        ("start", "onyx-portaudio-playback"),
        ("abort", "onyx-portaudio-playback"),
        ("close", "onyx-portaudio-playback"),
    ]


def test_capture_stop_aborts_and_closes_on_the_stream_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations: list[tuple[str, str]] = []

    class Stream:
        def __init__(self, **kwargs) -> None:
            assert callable(kwargs["callback"])

        def start(self) -> None:
            operations.append(("start", threading.current_thread().name))

        def abort(self) -> None:
            operations.append(("abort", threading.current_thread().name))

        def close(self) -> None:
            operations.append(("close", threading.current_thread().name))

    monkeypatch.setattr(onyx_main.sd, "InputStream", Stream)
    worker = onyx_main._PortAudioCaptureWorker(lambda *_args: None)
    worker.start()
    assert worker.started.wait(1.0)
    worker.request_stop()
    assert worker.stopped.wait(1.0)
    assert worker.stop_error is None
    assert operations == [
        ("start", "onyx-portaudio-capture"),
        ("abort", "onyx-portaudio-capture"),
        ("close", "onyx-portaudio-capture"),
    ]
