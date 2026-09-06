from __future__ import annotations

import hashlib
import inspect
import threading
from pathlib import Path

import pytest

from core import llm_client
from core.phase6_local_text_compat_v1 import (
    FEATURE_FLAG,
    LLM_CLIENT_SHA256,
    LocalTextBudgetExceeded,
    LocalTextCancelled,
    LocalTextConfigV1,
    LocalTextContractError,
    LocalTextControlV1,
    LocalTextPrivacyDenied,
    LocalTextProviderV1,
    LocalTextTimeout,
    LocalTextTransportRequestV1,
    LocalTextUnavailable,
    create_local_text_compatibility_v1,
    create_local_text_installation_v1,
    create_local_text_transport_v1,
)


ROOT = Path(__file__).resolve().parents[1]


class FakeTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.requests: list[LocalTextTransportRequestV1] = []

    def __call__(self, request: LocalTextTransportRequestV1) -> object:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def make_adapter(
    provider: LocalTextProviderV1,
    responses: list[object],
    *,
    control: LocalTextControlV1 | None = None,
):
    fake = FakeTransport(responses)
    adapter = create_local_text_compatibility_v1(
        config=LocalTextConfigV1(
            provider=provider,
            base_url="http://127.0.0.1:11434",
            model="local-model",
        ),
        transport=create_local_text_transport_v1(fake),
        control=control,
        environ={FEATURE_FLAG: "true"},
    )
    assert adapter is not None
    return adapter, fake


def test_llm_client_frozen_and_real_public_signatures_characterised() -> None:
    assert hashlib.sha256((ROOT / "core/llm_client.py").read_bytes()).hexdigest() == (
        LLM_CLIENT_SHA256
    )
    assert str(inspect.signature(llm_client.call_llm)) == (
        "(messages: list, tools: list | None = None, timeout: int = 120) -> dict"
    )
    assert str(inspect.signature(llm_client.call_llm_text)) == (
        "(prompt: str, system: str | None = None, model: str | None = None, "
        "timeout: int = 120) -> str"
    )
    assert str(inspect.signature(llm_client.call_llm_stream)) == (
        "(messages: list, tools: list | None = None, timeout: int = 120) "
        "-> Generator[dict, NoneType, NoneType]"
    )


def test_extension_off_is_exact_noop_and_factory_only() -> None:
    originals = (
        llm_client.call_llm,
        llm_client.call_llm_text,
        llm_client.call_llm_stream,
    )
    adapter = create_local_text_compatibility_v1(
        config=LocalTextConfigV1(
            LocalTextProviderV1.OLLAMA, "http://localhost:11434", "m"
        ),
        transport=create_local_text_transport_v1(lambda request: {}),
        environ={},
    )
    assert adapter is None
    assert originals == (
        llm_client.call_llm,
        llm_client.call_llm_text,
        llm_client.call_llm_stream,
    )
    with pytest.raises(LocalTextContractError, match="factory-created"):
        type(create_local_text_transport_v1(lambda request: {}))(
            key=object(), handler=lambda request: {}
        )


@pytest.mark.parametrize(
    "base_url",
    [
        "https://localhost:11434",
        "http://192.168.1.7:11434",
        "http://example.com",
        "http://user:secret@localhost:11434",
        "http://localhost:11434/api/chat",
        "http://localhost:bad",
        "http://localhost:0",
        " http://localhost:11434",
        "http://localhost:11434\n",
    ],
)
def test_privacy_denies_non_loopback_or_embedded_authority(base_url: str) -> None:
    with pytest.raises(LocalTextPrivacyDenied):
        LocalTextConfigV1(LocalTextProviderV1.OLLAMA, base_url, "m")


def test_ollama_nonstream_and_text_requests_match_real_surface() -> None:
    adapter, fake = make_adapter(
        LocalTextProviderV1.OLLAMA,
        [
            {
                "message": {
                    "content": "  done ",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "search",
                                "arguments": {"q": "onyx"},
                            }
                        }
                    ],
                }
            },
            {"message": {"content": "  text answer "}},
        ],
    )
    tools = [{"type": "function", "function": {"name": "search"}}]
    assert adapter.call_llm([{"role": "user", "content": "go"}], tools) == {
        "content": "done",
        "tool_calls": [
            {
                "id": "",
                "function": {"name": "search", "arguments": {"q": "onyx"}},
            }
        ],
    }
    chat = fake.requests[0]
    assert chat.endpoint == "http://127.0.0.1:11434/api/chat"
    assert chat.payload == {
        "model": "local-model",
        "messages": [{"role": "user", "content": "go"}],
        "stream": False,
        "keep_alive": -1,
        "options": {"num_predict": 150, "num_gpu": 99},
        "tools": tools,
    }
    assert adapter.call_llm_text("hello", "be concise", "override", 7) == "text answer"
    text = fake.requests[1]
    assert text.timeout_seconds == 7
    assert text.payload == {
        "model": "override",
        "messages": [
            {"role": "system", "content": "be concise"},
            {"role": "user", "content": "hello"},
        ],
        "stream": False,
        "keep_alive": -1,
        "options": {"num_predict": 600},
    }


def test_openai_compatible_nonstream_and_tool_call_normalisation() -> None:
    adapter, fake = make_adapter(
        LocalTextProviderV1.OPENAI_COMPATIBLE,
        [
            {
                "choices": [
                    {
                        "message": {
                            "content": " ok ",
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "function": {
                                        "name": "search",
                                        "arguments": '{"q":"onyx"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ],
    )
    tools = [{"type": "function", "function": {"name": "search"}}]
    result = adapter.call_llm([{"role": "user", "content": "go"}], tools, 9)
    assert result == {
        "content": "ok",
        "tool_calls": [
            {
                "id": "c1",
                "function": {"name": "search", "arguments": {"q": "onyx"}},
            }
        ],
    }
    request = fake.requests[0]
    assert request.endpoint.endswith("/v1/chat/completions")
    assert request.timeout_seconds == 9
    assert request.payload["max_tokens"] == 150
    assert request.payload["tool_choice"] == "auto"
    assert "keep_alive" not in request.payload
    assert len(fake.requests) == 1


def test_tool_call_parity_between_providers() -> None:
    expected = [{"id": "c1", "function": {"name": "run", "arguments": {"x": 1}}}]
    ollama, _ = make_adapter(
        LocalTextProviderV1.OLLAMA,
        [{"message": {"content": "", "tool_calls": expected}}],
    )
    openai, _ = make_adapter(
        LocalTextProviderV1.OPENAI_COMPATIBLE,
        [
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "function": {
                                        "name": "run",
                                        "arguments": '{"x":1}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ],
    )
    assert ollama.call_llm([])["tool_calls"] == expected
    assert openai.call_llm([])["tool_calls"] == expected


def test_ollama_stream_sentence_done_and_tools() -> None:
    adapter, fake = make_adapter(
        LocalTextProviderV1.OLLAMA,
        [
            [
                {"message": {"content": "Hello. "}, "done": False},
                {
                    "message": {
                        "content": "World",
                        "tool_calls": [
                            {
                                "id": "t",
                                "function": {
                                    "name": "run",
                                    "arguments": {"x": 1},
                                },
                            }
                        ],
                    },
                    "done": False,
                },
                {"message": {"content": ""}, "done": True},
            ]
        ],
    )
    events = list(adapter.call_llm_stream([{"role": "user", "content": "go"}]))
    assert events == [
        {"type": "sentence", "text": "Hello."},
        {"type": "sentence", "text": "World"},
        {
            "type": "done",
            "content": "Hello. World",
            "tool_calls": [
                {
                    "id": "t",
                    "function": {"name": "run", "arguments": {"x": 1}},
                }
            ],
        },
    ]
    assert fake.requests[0].stream is True
    assert fake.requests[0].payload["stream"] is True


def test_openai_sse_stream_fragmented_tool_call_parity() -> None:
    adapter, _ = make_adapter(
        LocalTextProviderV1.OPENAI_COMPATIBLE,
        [
            [
                'data: {"choices":[{"delta":{"content":"Hello. ","tool_calls":'
                '[{"index":0,"id":"c1","function":{"name":"ru","arguments":"{\\"x\\":"}}]},'
                '"finish_reason":null}]}',
                'data: {"choices":[{"delta":{"content":"World","tool_calls":'
                '[{"index":0,"function":{"name":"n","arguments":"1}"}}]},'
                '"finish_reason":"tool_calls"}]}',
            ]
        ],
    )
    assert list(adapter.call_llm_stream([])) == [
        {"type": "sentence", "text": "Hello."},
        {"type": "sentence", "text": "World"},
        {
            "type": "done",
            "content": "Hello. World",
            "tool_calls": [
                {
                    "id": "c1",
                    "function": {"name": "run", "arguments": {"x": 1}},
                }
            ],
        },
    ]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (ConnectionError("offline"), LocalTextUnavailable),
        (TimeoutError("slow"), LocalTextTimeout),
        (LocalTextUnavailable("offline"), LocalTextUnavailable),
        (LocalTextTimeout("slow"), LocalTextTimeout),
    ],
)
def test_unavailable_timeout_are_explicit_and_never_cross_route(
    source: BaseException, expected: type[BaseException]
) -> None:
    adapter, fake = make_adapter(LocalTextProviderV1.OLLAMA, [source])
    with pytest.raises(expected):
        adapter.call_llm([])
    assert len(fake.requests) == 1
    assert fake.requests[0].provider is LocalTextProviderV1.OLLAMA


def test_pre_cancel_and_midstream_cancel_are_fail_closed() -> None:
    event = threading.Event()
    event.set()
    adapter, fake = make_adapter(
        LocalTextProviderV1.OLLAMA,
        [{"message": {"content": "never"}}],
        control=LocalTextControlV1(cancel_event=event),
    )
    with pytest.raises(LocalTextCancelled):
        adapter.call_llm([])
    assert fake.requests == []

    event2 = threading.Event()

    def chunks():
        yield {"message": {"content": "First. "}, "done": False}
        event2.set()
        yield {"message": {"content": "Never"}, "done": True}

    stream_adapter, _ = make_adapter(
        LocalTextProviderV1.OLLAMA,
        [chunks()],
        control=LocalTextControlV1(cancel_event=event2),
    )
    iterator = stream_adapter.call_llm_stream([])
    assert next(iterator) == {"type": "sentence", "text": "First."}
    with pytest.raises(LocalTextCancelled):
        next(iterator)


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (TimeoutError("late timeout"), LocalTextTimeout),
        (ConnectionError("late unavailable"), LocalTextUnavailable),
        (OSError("late unavailable"), LocalTextUnavailable),
    ],
)
def test_lazy_stream_transport_failures_are_typed_without_retry(
    failure: BaseException, expected: type[BaseException]
) -> None:
    def chunks():
        yield {"message": {"content": "First. "}, "done": False}
        raise failure

    adapter, fake = make_adapter(LocalTextProviderV1.OLLAMA, [chunks()])
    iterator = adapter.call_llm_stream([])
    assert next(iterator) == {"type": "sentence", "text": "First."}
    with pytest.raises(expected):
        next(iterator)
    assert len(fake.requests) == 1
    assert fake.requests[0].provider is LocalTextProviderV1.OLLAMA


def test_controlled_text_and_factory_reject_non_exact_control() -> None:
    transport = create_local_text_transport_v1(
        lambda request: {"message": {"content": "unused"}}
    )
    with pytest.raises(ValueError, match="exact LocalTextControlV1"):
        create_local_text_compatibility_v1(
            config=LocalTextConfigV1(
                LocalTextProviderV1.OLLAMA, "http://localhost:11434", "m"
            ),
            transport=transport,
            control=False,  # type: ignore[arg-type]
            environ={FEATURE_FLAG: "true"},
        )

    adapter, _ = make_adapter(LocalTextProviderV1.OLLAMA, [])
    with pytest.raises(ValueError, match="exact LocalTextControlV1"):
        adapter.call_llm_text_controlled(  # type: ignore[arg-type]
            "prompt", control=False
        )


def test_request_response_and_stream_event_budgets() -> None:
    adapter, fake = make_adapter(
        LocalTextProviderV1.OLLAMA,
        [{"message": {"content": "x"}}],
    )
    with pytest.raises(LocalTextBudgetExceeded, match="request"):
        adapter.call_llm_controlled(
            [{"role": "user", "content": "long"}],
            control=LocalTextControlV1(maximum_request_bytes=4),
        )
    assert fake.requests == []

    adapter2, _ = make_adapter(
        LocalTextProviderV1.OLLAMA,
        [{"message": {"content": "long response"}}],
    )
    with pytest.raises(LocalTextBudgetExceeded, match="response"):
        adapter2.call_llm_controlled(
            [], control=LocalTextControlV1(maximum_response_bytes=4)
        )

    adapter3, _ = make_adapter(
        LocalTextProviderV1.OLLAMA,
        [
            [
                {"message": {"content": "One. Two. "}, "done": False},
                {"message": {"content": ""}, "done": True},
            ]
        ],
    )
    with pytest.raises(LocalTextBudgetExceeded, match="event"):
        list(
            adapter3.call_llm_stream_controlled(
                [], control=LocalTextControlV1(maximum_stream_events=1)
            )
        )


def test_malformed_response_and_unterminated_stream_fail_closed() -> None:
    adapter, _ = make_adapter(LocalTextProviderV1.OPENAI_COMPATIBLE, [{"choices": []}])
    with pytest.raises(LocalTextContractError, match="no choice"):
        adapter.call_llm([])
    stream, _ = make_adapter(
        LocalTextProviderV1.OLLAMA,
        [[{"message": {"content": "partial"}, "done": False}]],
    )
    with pytest.raises(LocalTextContractError, match="terminal"):
        list(stream.call_llm_stream([]))


def test_explicit_install_and_exact_rollback_restore_all_identities() -> None:
    adapter, _ = make_adapter(
        LocalTextProviderV1.OLLAMA,
        [
            {"message": {"content": "chat"}},
            {"message": {"content": "text"}},
            [{"message": {"content": "stream"}, "done": True}],
        ],
    )
    originals = {
        "call_llm": llm_client.call_llm,
        "call_llm_text": llm_client.call_llm_text,
        "call_llm_stream": llm_client.call_llm_stream,
    }
    installation = create_local_text_installation_v1(adapter)
    with installation:
        assert installation.installed is True
        assert llm_client.call_llm([])["content"] == "chat"
        assert llm_client.call_llm_text("p") == "text"
        assert list(llm_client.call_llm_stream([]))[-1]["content"] == "stream"
    assert installation.installed is False
    assert all(getattr(llm_client, name) is value for name, value in originals.items())
    assert not hasattr(llm_client, "_onyx_local_text_compat_v1_owner")


def test_rollback_restores_originals_even_when_drift_is_detected() -> None:
    adapter, _ = make_adapter(LocalTextProviderV1.OLLAMA, [])
    installation = create_local_text_installation_v1(adapter)
    original = llm_client.call_llm
    installation.install()
    llm_client.call_llm = lambda *_args, **_kwargs: {}  # type: ignore[assignment]
    with pytest.raises(LocalTextContractError, match="drift detected"):
        installation.rollback()
    assert llm_client.call_llm is original
    assert not installation.installed


def test_rollback_detects_owner_drift_and_restores_original_owner_state() -> None:
    adapter, _ = make_adapter(LocalTextProviderV1.OLLAMA, [])
    installation = create_local_text_installation_v1(adapter)
    originals = {
        "call_llm": llm_client.call_llm,
        "call_llm_text": llm_client.call_llm_text,
        "call_llm_stream": llm_client.call_llm_stream,
    }
    assert not hasattr(llm_client, "_onyx_local_text_compat_v1_owner")
    installation.install()
    llm_client._onyx_local_text_compat_v1_owner = object()  # type: ignore[attr-defined]
    with pytest.raises(LocalTextContractError, match="drift detected"):
        installation.rollback()
    assert all(getattr(llm_client, name) is value for name, value in originals.items())
    assert not hasattr(llm_client, "_onyx_local_text_compat_v1_owner")


def test_no_real_network_module_is_imported_by_candidate() -> None:
    source = (ROOT / "core/phase6_local_text_compat_v1.py").read_text("utf-8")
    for token in (
        "import requests",
        "import httpx",
        "import aiohttp",
        "import socket",
        "requests.post",
    ):
        assert token not in source
