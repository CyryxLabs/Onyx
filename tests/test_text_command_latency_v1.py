from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from main import OnyxLive


ROOT = Path(__file__).resolve().parents[1]


def test_text_command_bypasses_serial_external_action_lane() -> None:
    host = OnyxLive.__new__(OnyxLive)
    host._loop = SimpleNamespace()
    host._runtime_task = SimpleNamespace()
    host._runtime_input_is_quiesced = lambda: False
    host._run_external_action = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("text command entered the serialized external-action lane")
    )
    called: list[str] = []

    assert host._dispatch_ui_worker(
        "text-command-v5", lambda: called.append("sent")
    ) is True
    assert called == ["sent"]


def test_non_text_ui_action_retains_governed_worker_lane() -> None:
    host = OnyxLive.__new__(OnyxLive)
    loop = asyncio.new_event_loop()
    try:
        host._loop = loop
        host._runtime_task = SimpleNamespace()
        host._runtime_input_is_quiesced = lambda: False
        scheduled: list[object] = []
        original = asyncio.run_coroutine_threadsafe
        asyncio.run_coroutine_threadsafe = lambda coroutine, _loop: scheduled.append(coroutine)
        try:
            assert host._dispatch_ui_worker("file-action", lambda: None) is True
        finally:
            asyncio.run_coroutine_threadsafe = original
        assert len(scheduled) == 1
        scheduled[0].close()
    finally:
        loop.close()


def test_live_text_latency_is_measured_at_dispatch_and_first_audio() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'self._text_command_latency_started_at = float(command["queued_at"])' in source
    assert "text command {command['id']} accepted by live" in source
    assert "first response audio in" in source
    assert "_watch_text_command_response_v1" in source
    assert "Gemini typed response deadline exceeded after retry" in source


def test_typed_turn_temporarily_excludes_ambient_microphone_frames() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "self._text_turn_pending    = threading.Event()" in source
    assert "self._text_turn_pending.set()" in source
    assert "and not self._text_turn_pending.is_set()" in source
    assert source.count("self._text_turn_pending.clear()") >= 5
