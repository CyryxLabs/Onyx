from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import main as onyx_main
from core.shutdown_intent_v1 import (
    ShutdownIntentGateV1,
    is_explicit_shutdown_intent_v1,
)


@pytest.mark.parametrize(
    "utterance",
    [
        "Onyx, desligue",
        "Pode encerrar a sessão, por favor",
        "Feche o Onyx",
        "Onyx, shut down",
        "Please close the assistant",
        "Goodbye Onyx",
        "tchau",
    ],
)
def test_explicit_shutdown_commands_are_recognised(utterance: str) -> None:
    assert is_explicit_shutdown_intent_v1(utterance) is True


@pytest.mark.parametrize(
    "utterance",
    [
        "não desligue o Onyx",
        "do not shut down Onyx",
        "what does shutdown Onyx mean",
        "stop speaking for a moment",
        "close the browser",
        "goodbye is an English word",
        "Onyx",
        "",
    ],
)
def test_ambiguous_or_negated_language_cannot_authorise_shutdown(
    utterance: str,
) -> None:
    assert is_explicit_shutdown_intent_v1(utterance) is False


def test_shutdown_intent_capability_is_short_lived_and_single_use() -> None:
    gate = ShutdownIntentGateV1(ttl_seconds=5.0)
    assert gate.observe("Onyx, desligue", now=10.0) is True
    digest = gate.consume(now=14.9)
    assert isinstance(digest, str) and len(digest) == 64
    assert gate.consume(now=14.9) is None

    assert gate.observe("please close Onyx", now=20.0) is True
    assert gate.consume(now=25.1) is None


def test_later_transcript_correction_revokes_armed_shutdown() -> None:
    gate = ShutdownIntentGateV1(ttl_seconds=20.0)
    assert gate.observe("Onyx, desligue", now=10.0) is True
    assert gate.observe("Onyx, desligue não, espere", now=11.0) is False
    assert gate.consume(now=12.0) is None


def test_model_cannot_shutdown_without_recent_explicit_owner_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class UI:
        muted = False

        def set_state(self, value: str) -> None:
            events.append(value)

        def write_log(self, value: str) -> None:
            events.append(value)

    host = object.__new__(onyx_main.OnyxLive)
    host.ui = UI()
    host._governance_nucleus_v1 = None
    host._shutdown_intent_gate_v1 = ShutdownIntentGateV1()
    host.request_shutdown = lambda _reason: events.append("shutdown")
    host.speak = lambda _text: events.append("speak")
    monkeypatch.setattr(
        onyx_main,
        "authorize_model_tool",
        lambda _name, _args: (True, "approved"),
    )
    function_call = SimpleNamespace(name="shutdown_onyx", args={}, id="fc-1")

    response = asyncio.run(host._execute_tool(function_call))

    assert response.response["result"].startswith("Shutdown refused")
    assert "shutdown" not in events
    assert "speak" not in events


def test_explicit_owner_intent_allows_one_shutdown_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class UI:
        muted = False

        def set_state(self, value: str) -> None:
            events.append(value)

        def write_log(self, value: str) -> None:
            events.append(value)

    host = object.__new__(onyx_main.OnyxLive)
    host.ui = UI()
    host._governance_nucleus_v1 = None
    host._shutdown_intent_gate_v1 = ShutdownIntentGateV1()
    host._shutdown_intent_gate_v1.observe("Onyx, desligue")
    host._begin_shutdown_sequence = lambda reason, prompt_farewell: events.append(
        f"sequence:{reason}:{prompt_farewell}"
    )
    monkeypatch.setattr(
        onyx_main,
        "authorize_model_tool",
        lambda _name, _args: (True, "approved"),
    )
    function_call = SimpleNamespace(name="shutdown_onyx", args={}, id="fc-2")

    response = asyncio.run(host._execute_tool(function_call))

    assert response.response["result"].startswith("Shutdown authorized")
    assert "sequence:voice-tool:False" in events
    assert host._shutdown_intent_gate_v1.consume() is None


def test_local_exit_farewell_uses_live_gemini_and_then_requests_cleanup() -> None:
    events: list[str] = []

    class Session:
        async def send_client_content(self, **payload) -> None:
            events.append(str(payload))
            host._provider_turn_active = 1
            host._shutdown_farewell_turn.enqueue_audio(1)
            host._shutdown_farewell_turn.provider_finished(1)
            host._shutdown_farewell_turn.audio_drained(1, played=True)

    class UI:
        def write_log(self, value: str) -> None:
            events.append(value)

    host = object.__new__(onyx_main.OnyxLive)
    host.ui = UI()
    host.session = Session()
    host._turn_done_event = asyncio.Event()
    host._shutdown_farewell_complete = asyncio.Event()
    host._shutdown_farewell_turn = onyx_main._ShutdownFarewellTurn(
        host._shutdown_farewell_complete
    )
    host._provider_turn_counter = 0
    host._provider_turn_active = None
    host._provider_turn_complete_event = asyncio.Event()
    host._provider_turn_complete_event.set()
    host.request_shutdown = lambda reason: events.append(f"shutdown:{reason}")

    async def exercise() -> None:
        await host._coordinate_shutdown_after_farewell(
            "local-exit-menu",
            prompt_farewell=True,
        )

    asyncio.run(exercise())

    assert any("current Onyx voice" in item for item in events)
    assert "shutdown:local-exit-menu" in events
    assert not any("system voice" in item.lower() for item in events)
