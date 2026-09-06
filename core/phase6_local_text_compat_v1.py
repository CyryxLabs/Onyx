"""Isolated Phase 6 compatibility seam for local text providers.

The module is deliberately provider-free: a caller must inject a local fake or
host-owned transport through the factory.  Importing it never changes
``core.llm_client``.  Installation is explicit, process-local and reversible.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from urllib.parse import urlsplit

from core import llm_client


FEATURE_FLAG: Final = "ONYX_PHASE6_LOCAL_TEXT_COMPAT_V1"
CANDIDATE: Final = "phase6-local-text-compat-candidate-001"
LLM_CLIENT_SHA256: Final = (
    "e5c0f805e0d10a07e38054316fb9c6423409190cfa0f48bc39694e65c6a4e417"
)
_FACTORY_KEY = object()
_MISSING = object()
_INSTALL_LOCK = threading.RLock()
_SENT_END = re.compile(r"(?<=[.!?])\s+|(?<=\n)\s*\n")


class LocalTextCompatError(RuntimeError):
    """Base error for the isolated compatibility seam."""


class LocalTextUnavailable(LocalTextCompatError):
    pass


class LocalTextTimeout(LocalTextCompatError):
    pass


class LocalTextCancelled(LocalTextCompatError):
    pass


class LocalTextBudgetExceeded(LocalTextCompatError):
    pass


class LocalTextPrivacyDenied(PermissionError):
    pass


class LocalTextContractError(LocalTextCompatError):
    pass


class LocalTextProviderV1(StrEnum):
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"


@dataclass(frozen=True, slots=True)
class LocalTextControlV1:
    """Per-operation cancellation and byte/event budgets."""

    cancel_event: threading.Event | None = None
    maximum_request_bytes: int = 1_048_576
    maximum_response_bytes: int = 1_048_576
    maximum_stream_events: int = 4_096

    def __post_init__(self) -> None:
        if (
            self.cancel_event is not None
            and type(self.cancel_event) is not threading.Event
        ):
            raise ValueError("cancel_event must be an exact threading.Event")
        for name in (
            "maximum_request_bytes",
            "maximum_response_bytes",
            "maximum_stream_events",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive exact integer")


@dataclass(frozen=True, slots=True)
class LocalTextConfigV1:
    provider: LocalTextProviderV1
    base_url: str
    model: str

    def __post_init__(self) -> None:
        if type(self.provider) is not LocalTextProviderV1:
            raise ValueError("exact LocalTextProviderV1 is required")
        if type(self.base_url) is not str or not self.base_url:
            raise ValueError("base_url is required")
        if type(self.model) is not str or not self.model.strip():
            raise ValueError("model is required")
        if self.base_url != self.base_url.strip() or any(
            ord(character) < 32 or ord(character) == 127 for character in self.base_url
        ):
            raise LocalTextPrivacyDenied(
                "local text endpoint contains unsafe whitespace"
            )
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "http":
            raise LocalTextPrivacyDenied("local text endpoint must use http")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise LocalTextPrivacyDenied(
                "credentials/query/fragment denied in local endpoint"
            )
        host = (parsed.hostname or "").lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise LocalTextPrivacyDenied(
                "only loopback local text endpoints are permitted"
            )
        try:
            port = parsed.port
        except ValueError as exc:
            raise LocalTextPrivacyDenied("local text endpoint port is invalid") from exc
        if port is not None and not 1 <= port <= 65_535:
            raise LocalTextPrivacyDenied("local text endpoint port is invalid")
        if parsed.path not in {"", "/"}:
            raise LocalTextPrivacyDenied("base_url must not include an endpoint path")

    @property
    def normalized_base_url(self) -> str:
        return self.base_url.rstrip("/")


@dataclass(frozen=True, slots=True)
class LocalTextTransportRequestV1:
    provider: LocalTextProviderV1
    endpoint: str
    payload: Mapping[str, object]
    timeout_seconds: int
    stream: bool

    def __post_init__(self) -> None:
        if type(self.provider) is not LocalTextProviderV1:
            raise ValueError("request provider is invalid")
        if type(self.endpoint) is not str or not self.endpoint:
            raise ValueError("request endpoint is required")
        if type(self.payload) is not dict:
            raise ValueError("request payload must be an exact dict")
        if type(self.timeout_seconds) is not int or self.timeout_seconds < 1:
            raise ValueError("timeout must be a positive exact integer")
        if type(self.stream) is not bool:
            raise ValueError("stream must be an exact boolean")


TransportHandlerV1 = Callable[
    [LocalTextTransportRequestV1],
    Mapping[str, object] | Iterable[object],
]


class LocalTextTransportV1:
    """Factory-created provider-free transport boundary."""

    __slots__ = ("_handler",)

    def __init__(self, *, key: object, handler: TransportHandlerV1) -> None:
        if key is not _FACTORY_KEY:
            raise LocalTextContractError("transport must be factory-created")
        if not callable(handler):
            raise ValueError("transport handler must be callable")
        self._handler = handler

    def invoke(
        self, request: LocalTextTransportRequestV1
    ) -> Mapping[str, object] | Iterable[object]:
        try:
            return self._handler(request)
        except (
            LocalTextUnavailable,
            LocalTextTimeout,
            LocalTextCancelled,
            LocalTextBudgetExceeded,
            LocalTextPrivacyDenied,
            LocalTextContractError,
        ):
            raise
        except TimeoutError as exc:
            raise LocalTextTimeout("local text transport timed out") from exc
        except (ConnectionError, OSError) as exc:
            raise LocalTextUnavailable("local text transport unavailable") from exc
        except Exception as exc:
            raise LocalTextCompatError("local text transport failed") from exc


def create_local_text_transport_v1(handler: TransportHandlerV1) -> LocalTextTransportV1:
    return LocalTextTransportV1(key=_FACTORY_KEY, handler=handler)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LocalTextContractError("request/response is not JSON-compatible") from exc


def _check_cancelled(control: LocalTextControlV1) -> None:
    if control.cancel_event is not None and control.cancel_event.is_set():
        raise LocalTextCancelled("local text operation cancelled")


def _normalise_tool_calls(raw: object) -> list[dict[str, object]]:
    if raw is None:
        return []
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
        raise LocalTextContractError("tool_calls must be a sequence")
    result: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise LocalTextContractError("tool_call must be an object")
        function = item.get("function")
        if not isinstance(function, Mapping):
            raise LocalTextContractError("tool_call function must be an object")
        name = function.get("name", "")
        arguments = function.get("arguments", {})
        if type(name) is not str:
            raise LocalTextContractError("tool_call function name must be text")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                pass
        result.append(
            {
                "id": item.get("id", "") if type(item.get("id", "")) is str else "",
                "function": {"name": name, "arguments": arguments},
            }
        )
    return result


def _response_message(
    provider: LocalTextProviderV1, response: Mapping[str, object]
) -> Mapping[str, object]:
    if provider is LocalTextProviderV1.OLLAMA:
        message = response.get("message", {})
    else:
        choices = response.get("choices", [])
        if (
            isinstance(choices, (str, bytes, bytearray))
            or not isinstance(choices, Sequence)
            or not choices
            or not isinstance(choices[0], Mapping)
        ):
            raise LocalTextContractError("OpenAI-compatible response has no choice")
        message = choices[0].get("message", {})
    if not isinstance(message, Mapping):
        raise LocalTextContractError("provider response message must be an object")
    return message


class LocalTextCompatibilityV1:
    """Exact chat/text/stream surface with an explicit injected transport."""

    __slots__ = ("_config", "_default_control", "_transport")

    def __init__(
        self,
        *,
        key: object,
        config: LocalTextConfigV1,
        transport: LocalTextTransportV1,
        default_control: LocalTextControlV1,
    ) -> None:
        if key is not _FACTORY_KEY:
            raise LocalTextContractError(
                "compatibility adapter must be factory-created"
            )
        if type(config) is not LocalTextConfigV1:
            raise ValueError("exact LocalTextConfigV1 is required")
        if type(transport) is not LocalTextTransportV1:
            raise ValueError("exact LocalTextTransportV1 is required")
        if type(default_control) is not LocalTextControlV1:
            raise ValueError("exact LocalTextControlV1 is required")
        self._config = config
        self._transport = transport
        self._default_control = default_control

    @property
    def config(self) -> LocalTextConfigV1:
        return self._config

    def _request(
        self,
        payload: dict[str, object],
        *,
        timeout: int,
        stream: bool,
        control: LocalTextControlV1,
    ) -> Mapping[str, object] | Iterable[object]:
        if type(timeout) is not int or timeout < 1:
            raise LocalTextContractError("timeout must be a positive exact integer")
        _check_cancelled(control)
        encoded = _canonical_bytes(payload)
        if len(encoded) > control.maximum_request_bytes:
            raise LocalTextBudgetExceeded("local text request byte budget exhausted")
        suffix = (
            "/api/chat"
            if self._config.provider is LocalTextProviderV1.OLLAMA
            else "/v1/chat/completions"
        )
        result = self._transport.invoke(
            LocalTextTransportRequestV1(
                provider=self._config.provider,
                endpoint=f"{self._config.normalized_base_url}{suffix}",
                payload=payload,
                timeout_seconds=timeout,
                stream=stream,
            )
        )
        _check_cancelled(control)
        return result

    def _chat_payload(
        self,
        messages: list,
        tools: list | None,
        *,
        stream: bool,
        model: str | None = None,
        text_only: bool = False,
    ) -> dict[str, object]:
        if type(messages) is not list:
            raise LocalTextContractError("messages must be an exact list")
        if tools is not None and type(tools) is not list:
            raise LocalTextContractError("tools must be an exact list or None")
        provider = self._config.provider
        payload: dict[str, object] = {
            "model": model or self._config.model,
            "messages": messages,
            "stream": stream,
        }
        if provider is LocalTextProviderV1.OLLAMA:
            payload["keep_alive"] = -1
            payload["options"] = (
                {"num_predict": 600}
                if text_only
                else {"num_predict": 150, "num_gpu": 99}
            )
            if tools:
                payload["tools"] = tools
        else:
            payload["max_tokens"] = 600 if text_only else 150
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"
        return payload

    def call_llm_controlled(
        self,
        messages: list,
        tools: list | None = None,
        timeout: int = 120,
        *,
        control: LocalTextControlV1,
    ) -> dict:
        if type(control) is not LocalTextControlV1:
            raise ValueError("exact LocalTextControlV1 is required")
        payload = self._chat_payload(messages, tools, stream=False)
        result = self._request(payload, timeout=timeout, stream=False, control=control)
        if not isinstance(result, Mapping):
            raise LocalTextContractError("non-stream response must be an object")
        encoded = _canonical_bytes(result)
        if len(encoded) > control.maximum_response_bytes:
            raise LocalTextBudgetExceeded("local text response byte budget exhausted")
        message = _response_message(self._config.provider, result)
        content = message.get("content") or ""
        if type(content) is not str:
            raise LocalTextContractError("response content must be text")
        return {
            "content": content.strip(),
            "tool_calls": _normalise_tool_calls(message.get("tool_calls")),
        }

    def call_llm(
        self, messages: list, tools: list | None = None, timeout: int = 120
    ) -> dict:
        return self.call_llm_controlled(
            messages, tools, timeout, control=self._default_control
        )

    def call_llm_text_controlled(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        timeout: int = 120,
        *,
        control: LocalTextControlV1,
    ) -> str:
        if type(control) is not LocalTextControlV1:
            raise ValueError("exact LocalTextControlV1 is required")
        if type(prompt) is not str:
            raise LocalTextContractError("prompt must be text")
        if system is not None and type(system) is not str:
            raise LocalTextContractError("system must be text or None")
        if model is not None and (type(model) is not str or not model):
            raise LocalTextContractError("model must be non-empty text or None")
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = self._chat_payload(
            messages, None, stream=False, model=model, text_only=True
        )
        result = self._request(payload, timeout=timeout, stream=False, control=control)
        if not isinstance(result, Mapping):
            raise LocalTextContractError("text response must be an object")
        encoded = _canonical_bytes(result)
        if len(encoded) > control.maximum_response_bytes:
            raise LocalTextBudgetExceeded("local text response byte budget exhausted")
        message = _response_message(self._config.provider, result)
        content = message.get("content") or ""
        if type(content) is not str:
            raise LocalTextContractError("text response content must be text")
        return content.strip()

    def call_llm_text(
        self,
        prompt: str,
        system: str | None = None,
        model: str | None = None,
        timeout: int = 120,
    ) -> str:
        return self.call_llm_text_controlled(
            prompt, system, model, timeout, control=self._default_control
        )

    def call_llm_stream_controlled(
        self,
        messages: list,
        tools: list | None = None,
        timeout: int = 120,
        *,
        control: LocalTextControlV1,
    ) -> Iterator[dict]:
        if type(control) is not LocalTextControlV1:
            raise ValueError("exact LocalTextControlV1 is required")
        payload = self._chat_payload(messages, tools, stream=True)
        result = self._request(payload, timeout=timeout, stream=True, control=control)
        if isinstance(result, Mapping) or isinstance(result, (str, bytes, bytearray)):
            raise LocalTextContractError(
                "stream response must be an iterable of chunks"
            )
        return self._normalised_stream(iter(result), control)

    def call_llm_stream(
        self, messages: list, tools: list | None = None, timeout: int = 120
    ) -> Iterator[dict]:
        return self.call_llm_stream_controlled(
            messages, tools, timeout, control=self._default_control
        )

    def _normalised_stream(
        self, chunks: Iterator[object], control: LocalTextControlV1
    ) -> Iterator[dict]:
        full_content = ""
        buffer = ""
        response_bytes = 0
        event_count = 0
        tool_calls: list[dict[str, object]] = []
        fragments: dict[int, dict[str, object]] = {}
        done_seen = False

        while True:
            try:
                raw = next(chunks)
            except StopIteration:
                break
            except (
                LocalTextUnavailable,
                LocalTextTimeout,
                LocalTextCancelled,
                LocalTextBudgetExceeded,
                LocalTextPrivacyDenied,
                LocalTextContractError,
            ):
                raise
            except TimeoutError as exc:
                raise LocalTextTimeout("local text stream timed out") from exc
            except (ConnectionError, OSError) as exc:
                raise LocalTextUnavailable("local text stream unavailable") from exc
            except Exception as exc:
                raise LocalTextCompatError("local text stream failed") from exc
            _check_cancelled(control)
            response_bytes += len(
                raw if isinstance(raw, bytes) else _canonical_bytes(raw)
            )
            if response_bytes > control.maximum_response_bytes:
                raise LocalTextBudgetExceeded("local text stream byte budget exhausted")

            if self._config.provider is LocalTextProviderV1.OLLAMA:
                chunk = _decode_ollama_chunk(raw)
                message = chunk.get("message", {})
                if not isinstance(message, Mapping):
                    raise LocalTextContractError(
                        "Ollama stream message must be an object"
                    )
                text = message.get("content") or ""
                if type(text) is not str:
                    raise LocalTextContractError("Ollama stream content must be text")
                if message.get("tool_calls"):
                    tool_calls.extend(_normalise_tool_calls(message.get("tool_calls")))
                terminal = chunk.get("done") is True
            else:
                decoded = _decode_openai_chunk(raw)
                if decoded is None:
                    done_seen = True
                    break
                chunk = decoded
                choices = chunk.get("choices", [])
                if not isinstance(choices, Sequence) or not choices:
                    continue
                choice = choices[0]
                if not isinstance(choice, Mapping):
                    raise LocalTextContractError(
                        "OpenAI stream choice must be an object"
                    )
                delta = choice.get("delta", {})
                if not isinstance(delta, Mapping):
                    raise LocalTextContractError(
                        "OpenAI stream delta must be an object"
                    )
                text = delta.get("content") or ""
                if type(text) is not str:
                    raise LocalTextContractError("OpenAI stream content must be text")
                _accumulate_openai_tool_fragments(fragments, delta.get("tool_calls"))
                terminal = choice.get("finish_reason") in {
                    "stop",
                    "tool_calls",
                    "length",
                }

            full_content += text
            buffer += text
            while True:
                match = _SENT_END.search(buffer)
                if match is None:
                    break
                sentence = buffer[: match.start() + 1].strip()
                buffer = buffer[match.end() :]
                if sentence:
                    event_count += 1
                    if event_count > control.maximum_stream_events:
                        raise LocalTextBudgetExceeded(
                            "local text stream event budget exhausted"
                        )
                    yield {"type": "sentence", "text": sentence}
                    _check_cancelled(control)
            if terminal:
                done_seen = True
                break

        if self._config.provider is LocalTextProviderV1.OPENAI_COMPATIBLE:
            tool_calls = _finish_openai_tool_fragments(fragments)
        if buffer.strip():
            event_count += 1
            if event_count > control.maximum_stream_events:
                raise LocalTextBudgetExceeded(
                    "local text stream event budget exhausted"
                )
            yield {"type": "sentence", "text": buffer.strip()}
            _check_cancelled(control)
        if not done_seen:
            raise LocalTextContractError(
                "provider stream ended without a terminal marker"
            )
        event_count += 1
        if event_count > control.maximum_stream_events:
            raise LocalTextBudgetExceeded("local text stream event budget exhausted")
        yield {
            "type": "done",
            "content": full_content.strip(),
            "tool_calls": tool_calls,
        }


def _decode_ollama_chunk(raw: object) -> Mapping[str, object]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LocalTextContractError("invalid Ollama stream JSON") from exc
    if not isinstance(raw, Mapping):
        raise LocalTextContractError("Ollama stream chunk must be an object")
    return raw


def _decode_openai_chunk(raw: object) -> Mapping[str, object] | None:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        if not raw.startswith("data:"):
            raise LocalTextContractError("OpenAI stream line must be SSE data")
        data = raw[5:].strip()
        if data == "[DONE]":
            return None
        try:
            raw = json.loads(data)
        except json.JSONDecodeError as exc:
            raise LocalTextContractError("invalid OpenAI stream JSON") from exc
    if not isinstance(raw, Mapping):
        raise LocalTextContractError("OpenAI stream chunk must be an object")
    return raw


def _accumulate_openai_tool_fragments(
    fragments: dict[int, dict[str, object]], raw: object
) -> None:
    if not raw:
        return
    if isinstance(raw, (str, bytes, bytearray)) or not isinstance(raw, Sequence):
        raise LocalTextContractError("OpenAI stream tool_calls must be a sequence")
    for item in raw:
        if not isinstance(item, Mapping):
            raise LocalTextContractError("OpenAI stream tool_call must be an object")
        index = item.get("index", 0)
        if type(index) is not int or index < 0:
            raise LocalTextContractError("OpenAI stream tool index is invalid")
        fragment = fragments.setdefault(index, {"id": "", "name": "", "arguments": ""})
        identifier = item.get("id") or ""
        if type(identifier) is not str:
            raise LocalTextContractError("OpenAI stream tool id must be text")
        if not fragment["id"]:
            fragment["id"] = identifier
        function = item.get("function", {})
        if not isinstance(function, Mapping):
            raise LocalTextContractError("OpenAI stream function must be an object")
        for source, target in (("name", "name"), ("arguments", "arguments")):
            value = function.get(source) or ""
            if type(value) is not str:
                raise LocalTextContractError("OpenAI stream fragment must be text")
            fragment[target] = str(fragment[target]) + value


def _finish_openai_tool_fragments(
    fragments: Mapping[int, Mapping[str, object]],
) -> list[dict[str, object]]:
    raw = [
        {
            "id": fragments[index]["id"],
            "function": {
                "name": fragments[index]["name"],
                "arguments": fragments[index]["arguments"],
            },
        }
        for index in sorted(fragments)
    ]
    return _normalise_tool_calls(raw)


class LocalTextInstallationV1:
    """Transactional optional monkeypatch with exact identity rollback."""

    __slots__ = (
        "_adapter",
        "_installed",
        "_original_owner",
        "_original_owner_present",
        "_originals",
        "_wrappers",
    )

    def __init__(self, *, key: object, adapter: LocalTextCompatibilityV1) -> None:
        if key is not _FACTORY_KEY:
            raise LocalTextContractError("installation must be factory-created")
        self._adapter = adapter
        self._installed = False
        self._original_owner = _MISSING
        self._original_owner_present = False
        self._originals: dict[str, object] = {}
        self._wrappers: dict[str, object] = {}

    @property
    def installed(self) -> bool:
        return self._installed

    def install(self) -> None:
        with _INSTALL_LOCK:
            if self._installed:
                return
            self._original_owner_present = hasattr(
                llm_client, "_onyx_local_text_compat_v1_owner"
            )
            owner = getattr(llm_client, "_onyx_local_text_compat_v1_owner", _MISSING)
            self._original_owner = owner
            if owner is _MISSING:
                owner = None
            if owner is not None and owner is not self:
                raise LocalTextContractError(
                    "another local text adapter owns llm_client"
                )
            originals = {
                "call_llm": llm_client.call_llm,
                "call_llm_text": llm_client.call_llm_text,
                "call_llm_stream": llm_client.call_llm_stream,
            }

            def call_llm(
                messages: list, tools: list | None = None, timeout: int = 120
            ) -> dict:
                return self._adapter.call_llm(messages, tools, timeout)

            def call_llm_text(
                prompt: str,
                system: str | None = None,
                model: str | None = None,
                timeout: int = 120,
            ) -> str:
                return self._adapter.call_llm_text(prompt, system, model, timeout)

            def call_llm_stream(
                messages: list, tools: list | None = None, timeout: int = 120
            ) -> Iterator[dict]:
                return self._adapter.call_llm_stream(messages, tools, timeout)

            wrappers = {
                "call_llm": call_llm,
                "call_llm_text": call_llm_text,
                "call_llm_stream": call_llm_stream,
            }
            try:
                for name, value in wrappers.items():
                    setattr(llm_client, name, value)
                setattr(llm_client, "_onyx_local_text_compat_v1_owner", self)
            except Exception:
                for name, value in originals.items():
                    setattr(llm_client, name, value)
                if self._original_owner_present:
                    setattr(
                        llm_client,
                        "_onyx_local_text_compat_v1_owner",
                        self._original_owner,
                    )
                elif hasattr(llm_client, "_onyx_local_text_compat_v1_owner"):
                    delattr(llm_client, "_onyx_local_text_compat_v1_owner")
                raise
            self._originals = originals
            self._wrappers = wrappers
            self._installed = True

    def rollback(self) -> None:
        with _INSTALL_LOCK:
            if not self._installed:
                return
            drift = [
                name
                for name, wrapper in self._wrappers.items()
                if getattr(llm_client, name) is not wrapper
            ]
            if (
                getattr(llm_client, "_onyx_local_text_compat_v1_owner", _MISSING)
                is not self
            ):
                drift.append("_onyx_local_text_compat_v1_owner")
            for name, original in self._originals.items():
                setattr(llm_client, name, original)
            if self._original_owner_present:
                setattr(
                    llm_client,
                    "_onyx_local_text_compat_v1_owner",
                    self._original_owner,
                )
            elif hasattr(llm_client, "_onyx_local_text_compat_v1_owner"):
                delattr(llm_client, "_onyx_local_text_compat_v1_owner")
            self._installed = False
            self._originals = {}
            self._wrappers = {}
            self._original_owner = _MISSING
            self._original_owner_present = False
            if drift:
                raise LocalTextContractError(
                    f"llm_client drift detected during exact rollback: {','.join(drift)}"
                )

    def __enter__(self) -> "LocalTextInstallationV1":
        self.install()
        return self

    def __exit__(self, *_: object) -> None:
        self.rollback()


def create_local_text_compatibility_v1(
    *,
    config: LocalTextConfigV1,
    transport: LocalTextTransportV1,
    control: LocalTextControlV1 | None = None,
    environ: Mapping[str, str] | None = None,
) -> LocalTextCompatibilityV1 | None:
    """Return an isolated adapter only for the exact, explicit feature flag."""
    values = os.environ if environ is None else environ
    if values.get(FEATURE_FLAG) != "true":
        return None
    return LocalTextCompatibilityV1(
        key=_FACTORY_KEY,
        config=config,
        transport=transport,
        default_control=control if control is not None else LocalTextControlV1(),
    )


def create_local_text_installation_v1(
    adapter: LocalTextCompatibilityV1,
) -> LocalTextInstallationV1:
    if type(adapter) is not LocalTextCompatibilityV1:
        raise ValueError("exact LocalTextCompatibilityV1 is required")
    return LocalTextInstallationV1(key=_FACTORY_KEY, adapter=adapter)


__all__ = [
    "CANDIDATE",
    "FEATURE_FLAG",
    "LLM_CLIENT_SHA256",
    "LocalTextBudgetExceeded",
    "LocalTextCancelled",
    "LocalTextCompatError",
    "LocalTextCompatibilityV1",
    "LocalTextConfigV1",
    "LocalTextContractError",
    "LocalTextControlV1",
    "LocalTextInstallationV1",
    "LocalTextPrivacyDenied",
    "LocalTextProviderV1",
    "LocalTextTimeout",
    "LocalTextTransportRequestV1",
    "LocalTextTransportV1",
    "LocalTextUnavailable",
    "create_local_text_compatibility_v1",
    "create_local_text_installation_v1",
    "create_local_text_transport_v1",
]
