from __future__ import annotations

import ast
import asyncio
from types import SimpleNamespace

import pytest

import core.phase6_gemini_live_compat_v1 as candidate_module
from core.phase6_gemini_live_compat_v1 import (
    API_VERSION,
    CANDIDATE,
    FEATURE_FLAG,
    EventMetadataV1,
    GeminiLiveCompatV1,
    LiveCompatDenied,
    LiveReceiptV1,
    LiveStatusV1,
    create_gemini_live_compat_v1,
)


class Config:
    response_modalities = ["AUDIO"]
    input_audio_transcription = {}
    output_audio_transcription = {}
    session_resumption = object()
    system_instruction = "TOP SECRET SYSTEM PROMPT"
    tools = [{"function_declarations": [{"name": "ping"}]}]
    speech_config = SimpleNamespace(
        voice_config=SimpleNamespace(
            prebuilt_voice_config=SimpleNamespace(voice_name="Aoede")
        )
    )


class Session:
    def __init__(self, events=()):
        self.events = events
        self.calls = []

    async def send_realtime_input(self, **kwargs):
        self.calls.append(("realtime", kwargs))

    async def send_client_content(self, **kwargs):
        self.calls.append(("content", kwargs))

    async def send_tool_response(self, **kwargs):
        self.calls.append(("tool", kwargs))

    async def receive(self):
        for event in self.events:
            yield event


class Handle:
    def __init__(self, session, enter_error=None):
        self.session = session
        self.enter_error = enter_error

    async def __aenter__(self):
        if self.enter_error:
            raise self.enter_error
        return self.session

    async def __aexit__(self, *_args):
        return None


class Live:
    def __init__(self, handle, connect_error=None):
        self.handle = handle
        self.connect_error = connect_error
        self.calls = []

    def connect(self, **kwargs):
        self.calls.append(kwargs)
        if self.connect_error:
            raise self.connect_error
        return self.handle


class Client:
    def __init__(self, handle, connect_error=None):
        self.aio = SimpleNamespace(live=Live(handle, connect_error))


def adapter(config=None, *, client=None):
    config = config or Config()
    client = client or Client(Handle(Session()))
    return (
        create_gemini_live_compat_v1(client, config, environ={FEATURE_FLAG: "1"}),
        client,
        config,
    )


@pytest.mark.parametrize("value", [None, "", "true", "TRUE", " 1", "1 "])
def test_exact_default_off(value):
    env = {} if value is None else {FEATURE_FLAG: value}
    with pytest.raises(LiveCompatDenied):
        create_gemini_live_compat_v1(Client(Handle(Session())), Config(), environ=env)


def test_exact_config_identity_passthrough_and_redacted_attestation():
    wrapped, client, config = adapter()
    result = asyncio.run(wrapped.connect())
    assert result.status is LiveStatusV1.READY
    call = client.aio.live.calls[0]
    assert call["config"] is config
    assert call["model"] == wrapped.model
    assert wrapped.attestation.system_instruction_present is True
    assert "TOP SECRET" not in repr(wrapped.attestation)
    assert wrapped.attestation.api_version == API_VERSION


def test_connect_and_enter_failures_are_unavailable():
    for client in (
        Client(Handle(Session()), OSError("connect")),
        Client(Handle(Session(), OSError("enter"))),
    ):
        wrapped, _, _ = adapter(client=client)
        result = asyncio.run(wrapped.connect())
        assert result.status is LiveStatusV1.UNAVAILABLE
        assert result.session is None
        assert result.receipt.status is LiveStatusV1.UNAVAILABLE


def test_exact_send_surfaces_and_content_free_receive_metadata():
    event = SimpleNamespace(
        data=b"secret audio",
        server_content=SimpleNamespace(text="secret transcript"),
        tool_call=None,
    )
    session = Session((event,))
    wrapped, _, _ = adapter(client=Client(Handle(session)))
    connected = asyncio.run(wrapped.connect())
    live = connected.session
    assert live is not None

    async def exercise():
        media = object()
        turns = {"parts": [{"text": "secret"}]}
        tools = [object()]
        await live.send_realtime_input(media=media)
        await live.send_client_content(turns, turn_complete=True)
        await live.send_tool_response(tools)
        receipt = await live.receive(
            request_digest="0" * 64, timeout_ms=1_000, max_events=4
        )
        return media, turns, tools, receipt

    media, turns, tools, receipt = asyncio.run(exercise())
    assert session.calls == [
        ("realtime", {"media": media}),
        ("content", {"turns": turns, "turn_complete": True}),
        ("tool", {"function_responses": tools}),
    ]
    assert receipt.status is LiveStatusV1.COMPLETED
    assert len(receipt.event_digests) == 1
    assert "secret" not in repr(receipt)


def test_cancel_timeout_and_strict_invariants():
    wrapped, _, _ = adapter(client=Client(Handle(Session())))
    live = asyncio.run(wrapped.connect()).session
    assert live is not None
    cancel = asyncio.Event()
    cancel.set()
    receipt = asyncio.run(
        live.receive(
            request_digest="0" * 64,
            timeout_ms=100,
            max_events=1,
            cancel=cancel,
        )
    )
    assert receipt.status is LiveStatusV1.CANCELLED
    with pytest.raises(ValueError):
        EventMetadataV1(-1, 0, False, False)
    with pytest.raises(ValueError):
        LiveReceiptV1(LiveStatusV1.ERROR, "bad", (), 0)
    with pytest.raises(LiveCompatDenied):
        GeminiLiveCompatV1(
            key=object(),
            client=object(),
            model="models/x",
            config=Config(),
            attestation=object(),
        )
    with pytest.raises(TypeError):
        asyncio.run(live.send_realtime_input(object()))


def test_ast_characterizes_exact_current_host_calls_and_config():
    assert CANDIDATE == "phase6-gemini-live-compat-candidate-003"
    host_source = open("main.py", encoding="utf-8").read()
    host_tree = ast.parse(host_source)
    host_calls = [
        node
        for node in ast.walk(host_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    connect = [node for node in host_calls if node.func.attr == "connect"]
    assert any(
        {kw.arg for kw in node.keywords} == {"model", "config"} for node in connect
    )
    content = [node for node in host_calls if node.func.attr == "send_client_content"]
    assert content and any(
        {"turns", "turn_complete"} <= {kw.arg for kw in node.keywords}
        for node in content
    )
    assert all(
        {"turns", "turn_complete"} <= {kw.arg for kw in node.keywords}
        or (
            len(node.keywords) == 1
            and node.keywords[0].arg is None
            and isinstance(node.keywords[0].value, ast.Name)
            and node.keywords[0].value.id == "payload"
        )
        for node in content
    )
    host_realtime = [
        node for node in host_calls if node.func.attr == "send_realtime_input"
    ]
    assert host_realtime
    host_keywords = {kw.arg for kw in host_realtime[0].keywords}
    assert host_keywords == {"media"}
    assert "audio" not in host_keywords
    config = [node for node in host_calls if node.func.attr == "LiveConnectConfig"]
    assert len(config) == 1
    assert len(config[0].keywords) == 1
    assert config[0].keywords[0].arg is None
    assert isinstance(config[0].keywords[0].value, ast.Name)
    assert config[0].keywords[0].value.id == "live_config_kwargs"
    config_payloads = [
        node.value
        for node in ast.walk(host_tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "live_config_kwargs"
            for target in node.targets
        )
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "dict"
    ]
    assert config_payloads
    assert "system_instruction" in {
        kw.arg for kw in config_payloads[0].keywords
    }

    wrapper_tree = ast.parse(open(candidate_module.__file__, encoding="utf-8").read())
    wrapper_methods = [
        node
        for node in ast.walk(wrapper_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "send_realtime_input"
    ]
    assert len(wrapper_methods) == 1
    wrapper = wrapper_methods[0]
    assert [arg.arg for arg in wrapper.args.kwonlyargs] == ["media"]
    assert not wrapper.args.args[1:]
    wrapper_calls = [
        node
        for node in ast.walk(wrapper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "send_realtime_input"
    ]
    assert len(wrapper_calls) == 1
    wrapper_keywords = {kw.arg for kw in wrapper_calls[0].keywords}
    assert wrapper_keywords == host_keywords == {"media"}
    assert "audio" not in wrapper_keywords
