from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import main


def test_transport_rotation_preserves_playback_drain_signal():
    import inspect
    from core.live_voice_continuity_v1 import _run_provider_network_loop_v1

    source = inspect.getsource(_run_provider_network_loop_v1)
    assert "instance._turn_done_event.set()" in source
    assert "instance._turn_done_event.clear()" not in source


def test_playback_releases_speaking_gate_after_transport_end(monkeypatch):
    class Worker:
        def __init__(self, _device):
            self.started = threading.Event()
            self.stopped = threading.Event()
            self.start_error = None
            self.stop_errors = ()
            self.output_underflows = 0

        def start(self):
            self.started.set()

        def request_stop(self):
            self.stopped.set()

    monkeypatch.setattr(main, "_PortAudioPlaybackWorker", Worker)

    async def exercise():
        host = object.__new__(main.OnyxLive)
        host.ui = SimpleNamespace(set_audio_level=lambda value: None)
        host.audio_in_queue = asyncio.Queue()
        host._turn_done_event = asyncio.Event()
        host._is_speaking = True
        host.set_speaking = lambda value: setattr(host, "_is_speaking", value)
        task = asyncio.create_task(host._play_audio())
        try:
            # Simulate the transport ending without sending turn_complete.
            host._turn_done_event.set()
            for _ in range(50):
                await asyncio.sleep(0.01)
                if not host._is_speaking:
                    break
            assert not host._is_speaking
            assert not host._turn_done_event.is_set()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    asyncio.run(exercise())


def test_microphone_callback_only_queues_audio_for_an_active_provider(
    monkeypatch,
) -> None:
    callbacks: list[object] = []
    callback_seen = threading.Event()

    class Stream:
        def __init__(self, *, callback, **_kwargs) -> None:
            callbacks.append(callback)

        def start(self):
            callbacks[-1](
                SimpleNamespace(tobytes=lambda: b"native-audio"),
                1,
                None,
                None,
            )
            callback_seen.set()

        def abort(self) -> None:
            return None

        def close(self) -> None:
            return None

    monkeypatch.setattr(main.sd, "InputStream", Stream)

    async def exercise(active_session: object | None) -> list[object]:
        host = object.__new__(main.OnyxLive)
        host.session = active_session
        host.out_queue = asyncio.Queue()
        host._speaking_lock = threading.Lock()
        host._is_speaking = False
        host._text_turn_pending = threading.Event()
        host._phone_active = False
        host.ui = SimpleNamespace(muted=False)
        callback_seen.clear()
        task = asyncio.create_task(host._listen_audio())
        for _ in range(100):
            if callback_seen.is_set():
                break
            await asyncio.sleep(0.01)
        assert callback_seen.is_set()
        await asyncio.sleep(0)
        queued: list[object] = []
        while not host.out_queue.empty():
            queued.append(host.out_queue.get_nowait())
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return queued

    async def verify() -> None:
        assert await exercise(None) == []
        assert await exercise(object()) == [
            {"data": b"native-audio", "mime_type": "audio/pcm"}
        ]

    asyncio.run(verify())


def test_playback_stream_lifecycle_has_one_thread_owner(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    class Stream:
        def __init__(self, *, callback, blocksize, **_kwargs) -> None:
            self.callback = callback
            self.blocksize = blocksize

        def start(self) -> None:
            calls.append(("start", threading.get_ident()))
            self.callback(bytearray(self.blocksize * 2), self.blocksize, None, None)

        def abort(self) -> None:
            calls.append(("abort", threading.get_ident()))

        def close(self) -> None:
            calls.append(("close", threading.get_ident()))

    monkeypatch.setattr(
        main.sd,
        "RawOutputStream",
        Stream,
    )
    playback = main._PortAudioPlaybackWorker()
    completed, outcome = playback.write(b"\x00\x00" * main.CHUNK_SIZE)
    owner_thread = threading.get_ident()
    playback.start()
    assert completed.wait(1.0)
    assert outcome == {"played": True}
    playback.request_stop()
    assert playback.stopped.wait(1.0)

    assert [name for name, _thread in calls] == [
        "start",
        "abort",
        "close",
    ]
    native_threads = {thread for _name, thread in calls}
    assert len(native_threads) == 1
    assert owner_thread not in native_threads


def test_transient_output_underflow_is_counted_without_killing_playback() -> None:
    playback = main._PortAudioPlaybackWorker()
    completed, outcome = playback.write(b"\x01\x00" * main.CHUNK_SIZE)

    playback._callback(
        bytearray(main.CHUNK_SIZE * 2),
        main.CHUNK_SIZE,
        None,
        SimpleNamespace(output_underflow=True),
    )

    assert completed.is_set()
    assert outcome == {"played": True}
    assert playback.output_underflows == 1
    assert not playback.stop_requested.is_set()


def test_interrupt_discards_worker_buffer_at_next_callback_boundary() -> None:
    playback = main._PortAudioPlaybackWorker()
    first_done, first_outcome = playback.write(b"\x01\x00" * (main.CHUNK_SIZE * 2))
    second_done, second_outcome = playback.write(b"\x02\x00" * main.CHUNK_SIZE)
    playback._callback(
        bytearray(main.CHUNK_SIZE * 2), main.CHUNK_SIZE, None, None
    )
    assert not first_done.is_set()

    playback.discard_pending()
    playback._callback(
        bytearray(main.CHUNK_SIZE * 2), main.CHUNK_SIZE, None, None
    )

    assert first_done.is_set()
    assert second_done.is_set()
    assert first_outcome == {"discarded": True}
    assert second_outcome == {"discarded": True}


def test_interrupt_does_not_discard_audio_queued_after_its_causal_cutoff() -> None:
    playback = main._PortAudioPlaybackWorker()
    old_done, old_outcome = playback.write(b"\x01\x00" * main.CHUNK_SIZE)
    playback.discard_pending()
    new_done, new_outcome = playback.write(b"\x02\x00" * main.CHUNK_SIZE)
    outdata = bytearray(main.CHUNK_SIZE * 2)

    playback._callback(outdata, main.CHUNK_SIZE, None, None)

    assert old_done.is_set()
    assert old_outcome == {"discarded": True}
    assert new_done.is_set()
    assert new_outcome == {"played": True}
    assert outdata == b"\x02\x00" * main.CHUNK_SIZE


def test_interrupt_linearizes_with_concurrent_audio_publication() -> None:
    playback = main._PortAudioPlaybackWorker()
    publication_started = threading.Event()
    release_publication = threading.Event()
    original_put = playback.commands.put_nowait

    def delayed_put(item) -> None:
        publication_started.set()
        assert release_publication.wait(1.0)
        original_put(item)

    playback.commands.put_nowait = delayed_put
    result: list[tuple[threading.Event, dict[str, object]]] = []
    producer = threading.Thread(
        target=lambda: result.append(
            playback.write(b"\x01\x00" * main.CHUNK_SIZE)
        )
    )
    producer.start()
    assert publication_started.wait(1.0)

    interrupted = threading.Event()
    interrupter = threading.Thread(
        target=lambda: (playback.discard_pending(), interrupted.set())
    )
    interrupter.start()
    assert not interrupted.wait(0.05)
    release_publication.set()
    producer.join(1.0)
    interrupter.join(1.0)
    assert interrupted.is_set()

    outdata = bytearray(main.CHUNK_SIZE * 2)
    playback._callback(outdata, main.CHUNK_SIZE, None, None)
    completed, outcome = result[0]
    assert completed.is_set()
    assert outcome == {"discarded": True}
    assert outdata == b"\x00" * (main.CHUNK_SIZE * 2)


def test_second_interrupt_during_discard_is_not_lost() -> None:
    playback = main._PortAudioPlaybackWorker()
    first_done, first_outcome = playback.write(
        b"\x01\x00" * main.CHUNK_SIZE
    )
    playback.discard_pending()
    second_done, second_outcome = playback.write(
        b"\x02\x00" * main.CHUNK_SIZE
    )
    first_discard_finished = threading.Event()
    release_first_discard = threading.Event()
    original_discard = playback._discard_buffered
    calls = 0

    def delayed_discard() -> None:
        nonlocal calls
        calls += 1
        original_discard()
        if calls == 1:
            first_discard_finished.set()
            assert release_first_discard.wait(1.0)

    playback._discard_buffered = delayed_discard
    outdata = bytearray(main.CHUNK_SIZE * 2)
    callback = threading.Thread(
        target=lambda: playback._callback(
            outdata, main.CHUNK_SIZE, None, None
        )
    )
    callback.start()
    assert first_discard_finished.wait(1.0)
    playback.discard_pending()
    release_first_discard.set()
    callback.join(1.0)

    assert not callback.is_alive()
    assert calls == 2
    assert first_done.is_set() and first_outcome == {"discarded": True}
    assert second_done.is_set() and second_outcome == {"discarded": True}
    assert outdata == b"\x00" * (main.CHUNK_SIZE * 2)
    assert not playback.discard_requested.is_set()


def test_pipeline_has_no_silence_inserted_between_unaligned_provider_slices() -> None:
    playback = main._PortAudioPlaybackWorker()
    source = b"".join(
        bytes([value, 0]) * 1_200
        for value in (1, 2, 3)
    )
    receipts = [
        playback.write(source[offset : offset + 2_400])
        for offset in range(0, len(source), 2_400)
    ]
    rendered = bytearray()
    while not all(completed.is_set() for completed, _outcome in receipts):
        outdata = bytearray(main.CHUNK_SIZE * 2)
        playback._callback(outdata, main.CHUNK_SIZE, None, None)
        rendered.extend(outdata)

    assert bytes(rendered[: len(source)]) == source
    assert all(outcome == {"played": True} for _completed, outcome in receipts)


def test_play_loop_pipelines_chunks_before_the_first_completion(monkeypatch) -> None:
    writes: list[tuple[threading.Event, dict[str, object]]] = []

    class Playback:
        def __init__(self, _device=None) -> None:
            self.started = threading.Event()
            self.stopped = threading.Event()
            self.start_error = None
            self.stop_errors = ()
            self.output_underflows = 0

        def start(self) -> None:
            self.started.set()

        def write(self, _chunk):
            receipt = (threading.Event(), {})
            writes.append(receipt)
            return receipt

        def request_stop(self) -> None:
            for completed, outcome in writes:
                outcome.setdefault("error", RuntimeError("stopped by test"))
                completed.set()
            self.stopped.set()

        def discard_pending(self) -> None:
            return None

    monkeypatch.setattr(main, "_PortAudioPlaybackWorker", Playback)

    async def verify() -> None:
        host = object.__new__(main.OnyxLive)
        host.audio_in_queue = asyncio.Queue()
        host.audio_in_queue.put_nowait((1, b"first"))
        host.audio_in_queue.put_nowait((1, b"second"))
        host._audio_device_selection_v1 = None
        host._audio_playback_worker = None
        host._turn_done_event = asyncio.Event()
        host._shutdown_farewell_turn = None
        host._interrupted = False
        host.set_speaking = lambda _value: None
        host._emit_audio_level = lambda _chunk: None
        host.ui = SimpleNamespace(
            muted=False,
            set_audio_level=lambda _value: None,
            write_log=lambda _message: None,
        )

        task = asyncio.create_task(host._play_audio())
        for _ in range(100):
            if len(writes) == 2:
                break
            await asyncio.sleep(0.005)
        assert len(writes) == 2
        assert not writes[0][0].is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    import pytest

    asyncio.run(verify())
