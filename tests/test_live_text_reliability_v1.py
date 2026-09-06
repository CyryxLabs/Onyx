from __future__ import annotations

import asyncio
from collections import deque
from types import SimpleNamespace
import threading

import main
import pytest
from core.audio_contract import LiveSessionRotation


class _Session:
    def __init__(self) -> None:
        self.payloads: list[dict[str, object]] = []

    async def send_client_content(self, **payload: object) -> None:
        self.payloads.append(payload)


def _host() -> main.OnyxLive:
    host = main.OnyxLive.__new__(main.OnyxLive)
    host.ui = SimpleNamespace(logs=[], write_log=lambda value: host.ui.logs.append(value))
    host.session = None
    host._loop = None
    host._shutdown_requested = threading.Event()
    host._shutdown_sequence_started = threading.Event()
    host._shutdown_input_quiesced = threading.Event()
    host._installer_shutdown_active = threading.Event()
    host._external_action_tasks = set()
    host._text_turn_pending = threading.Event()
    host._text_command_queue = deque()
    host._text_command_queue_lock = threading.Lock()
    host._text_command_counter = 0
    host._active_text_command = None
    host._text_dispatch_lock = None
    host._pending_learning_input = None
    host._text_command_latency_started_at = None
    return host


def test_offline_text_is_retained_and_dispatched_after_reconnect() -> None:
    async def scenario() -> None:
        host = _host()
        host._loop = asyncio.get_running_loop()
        command = host._queue_text_command_v1("hello")
        assert command is not None
        await host._flush_text_commands_v1()
        assert len(host._text_command_queue) == 1

        session = _Session()
        host.session = session
        await host._flush_text_commands_v1()

        assert session.payloads == [
            {"turns": {"parts": [{"text": "hello"}]}, "turn_complete": True}
        ]
        assert host._active_text_command is command
        assert host._text_turn_pending.is_set()

    asyncio.run(scenario())


def test_transport_rotation_retries_only_a_turn_with_no_provider_response() -> None:
    async def scenario() -> None:
        host = _host()
        host._loop = asyncio.get_running_loop()
        host.session = _Session()
        command = host._queue_text_command_v1("retain me")
        await host._flush_text_commands_v1()

        host._provider_transport_ended_v1()
        assert host._active_text_command is None
        assert tuple(host._text_command_queue) == (command,)
        assert not host._text_turn_pending.is_set()

        host.session = _Session()
        await host._flush_text_commands_v1()
        host._mark_text_response_started_v1()
        host._provider_transport_ended_v1()

        assert host._active_text_command is None
        assert not host._text_command_queue
        assert any("not replayed" in item for item in host.ui.logs)

    asyncio.run(scenario())


def test_completed_text_turn_dispatches_next_queued_command_in_order() -> None:
    async def scenario() -> None:
        host = _host()
        host._loop = asyncio.get_running_loop()
        session = _Session()
        host.session = session
        first = host._queue_text_command_v1("first")
        second = host._queue_text_command_v1("second")
        await host._flush_text_commands_v1()
        assert host._active_text_command is first

        host._complete_text_command_v1()
        await asyncio.sleep(0)
        assert host._active_text_command is second
        assert [payload["turns"]["parts"][0]["text"] for payload in session.payloads] == [
            "first",
            "second",
        ]

    asyncio.run(scenario())


def test_silent_provider_rotates_once_then_releases_the_command() -> None:
    async def scenario() -> None:
        host = _host()
        host._loop = asyncio.get_running_loop()
        host._text_response_timeout_s = 0.02
        host.session = _Session()
        command = host._queue_text_command_v1("answer me")
        await host._flush_text_commands_v1()

        with pytest.raises(LiveSessionRotation, match="deadline"):
            await host._watch_text_command_response_v1()
        assert host._active_text_command is command

        host._provider_transport_ended_v1()
        host.session = _Session()
        await host._flush_text_commands_v1()
        assert command["attempts"] == 2

        with pytest.raises(RuntimeError, match="after retry"):
            await host._watch_text_command_response_v1()
        assert host._active_text_command is None
        assert not host._text_turn_pending.is_set()
        assert any("released instead of blocking" in item for item in host.ui.logs)

    asyncio.run(scenario())
