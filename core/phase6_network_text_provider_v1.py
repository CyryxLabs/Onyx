"""Default-off, source-only Phase 6 network text provider boundary.

The module is deliberately absent from live wiring.  It never imports or
changes voice code.  A client exists only when an exact ProviderRegistryV1
instance issues an opaque authority, a trusted live-activation account
capability, an OS-vault resolver and durable attempt store are injected, and
the exact feature gate is enabled.

Security invariants:

* fixed HTTPS origin/path/model policies; redirects and response-origin drift
  are denied; the stdlib transport validates platform TLS and never retries;
* authority issuance and immediate pre-dispatch verification require the
  authenticated ProviderRegistryV1 planner to return the exact route READY;
* credentials are resolved from a fixed account-binding alias and appear only
  in the outbound authentication header;
* durable reserve-before-dispatch provides at-most-once behavior across process
  restarts; an uncertain dispatch is reconciliation-required and never resent;
* schemas, arguments, bytes, locally observable output, events and monotonic
  wall time are bounded; stream+tools fails closed before dispatch;
* receipts contain hashes and routing identity only, never prompt, output,
  credential alias, URL, model response, or exception text.

Trust boundary: the account resolver is a capability owned by the future live
activation successor.  This source-only module cannot construct it from an
identity, owner, workspace, account, request, or model-supplied value.  Python
already executing inside the trusted Onyx process is part of the TCB; model and
request data are not.  No request API accepts an account or credential alias.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Final, Protocol
from urllib.parse import urlsplit

from core.phase6_agentic_core_v1 import DataClassV1, RouteRequestV1
from core.phase6_provider_registry_v1 import (
    ProviderRecordV1,
    ProviderRegistryV1,
    ProviderRegistryV1ContractError,
    ProviderRegistryV1Denied,
    ProviderRoutePlanStatusV1,
    ProviderRoutePlanV1,
    ProviderRouteTargetV1,
)


FEATURE_FLAG: Final = "ONYX_PHASE6_NETWORK_TEXT_PROVIDER_V1"
ENABLED_VALUE: Final = "true"
MAX_REQUEST_BYTES: Final = 1_048_576
MAX_RESPONSE_BYTES: Final = 2_097_152
MAX_OUTPUT_TOKENS: Final = 32_768
MAX_MESSAGES: Final = 128
MAX_TOOLS: Final = 64
MAX_STREAM_EVENTS: Final = 8_192
MAX_TEXT_BYTES: Final = 262_144
MAX_SCHEMA_BYTES: Final = 65_536
MAX_CREDENTIAL_BYTES: Final = 16_384
MAX_TIMEOUT_SECONDS: Final = 600
OUTPUT_UTF8_BYTES_PER_TOKEN: Final = 4
OUTPUT_CHARACTERS_PER_TOKEN: Final = 4
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}\Z")
_TOOL_NAME = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|authorization|credentials?|password|secret|"
    r"access[_-]?token|refresh[_-]?token|bearer[_-]?token)\Z",
    re.I,
)
_SCHEMA_KEYS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "const",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "pattern",
        "description",
    }
)


class NetworkTextError(RuntimeError):
    """Base error; messages intentionally contain no provider response data."""


class NetworkTextContractError(ValueError):
    pass


class NetworkTextDenied(PermissionError):
    pass


class NetworkTextCredentialUnavailable(NetworkTextDenied):
    pass


class NetworkTextPostDispatchDenied(NetworkTextDenied):
    pass


class NetworkTextNotDispatched(NetworkTextError):
    """Injected transport proof that no request bytes left the process."""


class NetworkTextReconciliationRequired(NetworkTextError):
    pass


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(child) for key, child in value.items()}
    if type(value) in {list, tuple}:
        return [_thaw(child) for child in value]
    return value


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            _thaw(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise NetworkTextContractError("value is not canonical JSON") from exc


def _sha(value: object) -> str:
    raw = value if type(value) is bytes else _canonical(value)
    return hashlib.sha256(raw).hexdigest()


def _text(value: object, label: str, maximum: int, *, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value) or "\x00" in value:
        raise NetworkTextContractError(f"{label} is invalid")
    if len(value.encode("utf-8")) > maximum:
        raise NetworkTextContractError(f"{label} exceeds its byte budget")
    return value


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise NetworkTextContractError(f"{label} is not canonical")
    return value


def _validate_json(value: object, *, label: str, maximum: int) -> bytes:
    def visit(item: object, depth: int = 0) -> None:
        if depth > 12:
            raise NetworkTextContractError(f"{label} is too deeply nested")
        if item is None or type(item) in {bool, int}:
            return
        if type(item) is float:
            if item != item or item in {float("inf"), float("-inf")}:
                raise NetworkTextContractError(f"{label} has a non-finite number")
            return
        if type(item) is str:
            _text(item, label, MAX_TEXT_BYTES, empty=True)
            return
        if type(item) in {list, tuple}:
            if len(item) > 256:
                raise NetworkTextContractError(f"{label} has too many items")
            for child in item:
                visit(child, depth + 1)
            return
        if isinstance(item, Mapping):
            if len(item) > 128:
                raise NetworkTextContractError(f"{label} has too many fields")
            for key, child in item.items():
                if type(key) is not str or not key or len(key) > 128:
                    raise NetworkTextContractError(f"{label} has an invalid field")
                if _SENSITIVE_KEY.fullmatch(key):
                    raise NetworkTextDenied(f"{label} contains a credential field")
                visit(child, depth + 1)
            return
        raise NetworkTextContractError(f"{label} contains an unsupported value")

    visit(value)
    encoded = _canonical(value)
    if len(encoded) > maximum:
        raise NetworkTextContractError(f"{label} exceeds its byte budget")
    return encoded


def _deep_freeze(value: object) -> object:
    if type(value) is dict:
        return MappingProxyType(
            {str(key): _deep_freeze(child) for key, child in value.items()}
        )
    if type(value) is list:
        return tuple(_deep_freeze(child) for child in value)
    return value


class NetworkTextProviderV1(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GROQ = "groq"
    OPENROUTER = "openrouter"


class NetworkTextProtocolV1(StrEnum):
    ANTHROPIC_MESSAGES = "anthropic_messages"
    OPENAI_CHAT_COMPLETIONS = "openai_chat_completions"


@dataclass(frozen=True, slots=True)
class NetworkTextRouteV1:
    provider: NetworkTextProviderV1
    protocol: NetworkTextProtocolV1
    adapter_id: str
    origin: str
    path: str
    api_version: str
    models: tuple[str, ...]
    output_token_field: str

    def __post_init__(self) -> None:
        if type(self.provider) is not NetworkTextProviderV1:
            raise NetworkTextContractError("provider route is invalid")
        if type(self.protocol) is not NetworkTextProtocolV1:
            raise NetworkTextContractError("provider protocol is invalid")
        _identifier(self.adapter_id, "adapter_id")
        _text(self.origin, "origin", 253)
        _text(self.path, "path", 2_048)
        _text(self.api_version, "api_version", 128)
        if (
            type(self.models) is not tuple
            or not self.models
            or len(set(self.models)) != len(self.models)
        ):
            raise NetworkTextContractError("model allowlist is invalid")
        for model in self.models:
            _text(model, "model", 256)
        if self.output_token_field not in {"max_tokens", "max_completion_tokens"}:
            raise NetworkTextContractError("output token field is invalid")

    @property
    def digest(self) -> str:
        return _sha(
            {
                "schema": "OnyxNetworkTextRoute.v1",
                "provider": self.provider.value,
                "protocol": self.protocol.value,
                "adapter_id": self.adapter_id,
                "origin": self.origin,
                "path": self.path,
                "api_version": self.api_version,
                "models": self.models,
                "output_token_field": self.output_token_field,
            }
        )


# Anthropic IDs are pinned, active Claude API IDs from the official model
# overview/deprecation pages as verified on 2026-08-05.  Convenience aliases and
# retired claude-sonnet-4-20250514 / claude-3-5-haiku-20241022 are excluded.
ROUTES: Final = (
    NetworkTextRouteV1(
        NetworkTextProviderV1.ANTHROPIC,
        NetworkTextProtocolV1.ANTHROPIC_MESSAGES,
        "network_text_anthropic_v1",
        "api.anthropic.com",
        "/v1/messages",
        "2023-06-01",
        (
            "claude-fable-5",
            "claude-haiku-4-5-20251001",
            "claude-opus-4-8",
            "claude-sonnet-4-6",
            "claude-sonnet-5",
        ),
        "max_tokens",
    ),
    NetworkTextRouteV1(
        NetworkTextProviderV1.OPENAI,
        NetworkTextProtocolV1.OPENAI_CHAT_COMPLETIONS,
        "network_text_openai_v1",
        "api.openai.com",
        "/v1/chat/completions",
        "v1",
        ("gpt-4.1", "gpt-4.1-mini"),
        "max_tokens",
    ),
    NetworkTextRouteV1(
        NetworkTextProviderV1.GROQ,
        NetworkTextProtocolV1.OPENAI_CHAT_COMPLETIONS,
        "network_text_groq_v1",
        "api.groq.com",
        "/openai/v1/chat/completions",
        "openai-v1",
        ("llama-3.3-70b-versatile", "openai/gpt-oss-120b"),
        "max_completion_tokens",
    ),
    NetworkTextRouteV1(
        NetworkTextProviderV1.OPENROUTER,
        NetworkTextProtocolV1.OPENAI_CHAT_COMPLETIONS,
        "network_text_openrouter_v1",
        "openrouter.ai",
        "/api/v1/chat/completions",
        "openai-v1",
        ("anthropic/claude-sonnet-4.6", "openai/gpt-4.1"),
        "max_tokens",
    ),
)
_ROUTES_BY_PROVIDER: Final = MappingProxyType(
    {route.provider: route for route in ROUTES}
)


@dataclass(frozen=True, slots=True)
class NetworkTextFeatureGateV1:
    enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise NetworkTextContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "NetworkTextFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class NetworkTextBudgetV1:
    maximum_request_bytes: int = MAX_REQUEST_BYTES
    maximum_response_bytes: int = MAX_RESPONSE_BYTES
    maximum_output_tokens: int = 4_096
    maximum_stream_events: int = MAX_STREAM_EVENTS
    timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        integers = (
            ("maximum_request_bytes", self.maximum_request_bytes, MAX_REQUEST_BYTES),
            ("maximum_response_bytes", self.maximum_response_bytes, MAX_RESPONSE_BYTES),
            ("maximum_output_tokens", self.maximum_output_tokens, MAX_OUTPUT_TOKENS),
            ("maximum_stream_events", self.maximum_stream_events, MAX_STREAM_EVENTS),
        )
        for label, value, maximum in integers:
            if type(value) is not int or not 1 <= value <= maximum:
                raise NetworkTextContractError(f"{label} is outside its bound")
        if type(self.timeout_seconds) not in {int, float} or isinstance(
            self.timeout_seconds, bool
        ):
            raise NetworkTextContractError("timeout_seconds is invalid")
        timeout = float(self.timeout_seconds)
        if not 0.01 <= timeout <= MAX_TIMEOUT_SECONDS:
            raise NetworkTextContractError("timeout_seconds is outside its bound")

    @property
    def maximum_output_utf8_bytes(self) -> int:
        return min(
            MAX_TEXT_BYTES,
            self.maximum_output_tokens * OUTPUT_UTF8_BYTES_PER_TOKEN,
        )

    @property
    def maximum_output_characters(self) -> int:
        return min(
            MAX_TEXT_BYTES,
            self.maximum_output_tokens * OUTPUT_CHARACTERS_PER_TOKEN,
        )


@dataclass(frozen=True, slots=True)
class NetworkTextMessageV1:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant"}:
            raise NetworkTextContractError("message role is invalid")
        _text(self.content, "message content", MAX_TEXT_BYTES, empty=True)


@dataclass(frozen=True, slots=True)
class NetworkTextToolV1:
    name: str
    description: str
    input_schema: Mapping[str, object]

    def __post_init__(self) -> None:
        if type(self.name) is not str or _TOOL_NAME.fullmatch(self.name) is None:
            raise NetworkTextContractError("tool name is invalid")
        _text(self.description, "tool description", 8_192, empty=True)
        if type(self.input_schema) is not dict:
            raise NetworkTextContractError("tool schema must be an exact object")
        _validate_schema(self.input_schema)
        object.__setattr__(self, "input_schema", _deep_freeze(self.input_schema))


@dataclass(frozen=True, slots=True)
class NetworkTextRequestV1:
    request_id: str
    messages: tuple[NetworkTextMessageV1, ...]
    tools: tuple[NetworkTextToolV1, ...] = ()
    stream: bool = False
    budget: NetworkTextBudgetV1 = NetworkTextBudgetV1()
    data_class: DataClassV1 = DataClassV1.INTERNAL

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        if (
            type(self.messages) is not tuple
            or not self.messages
            or len(self.messages) > MAX_MESSAGES
            or any(type(item) is not NetworkTextMessageV1 for item in self.messages)
        ):
            raise NetworkTextContractError("messages are invalid")
        if (
            type(self.tools) is not tuple
            or len(self.tools) > MAX_TOOLS
            or any(type(item) is not NetworkTextToolV1 for item in self.tools)
            or len({item.name for item in self.tools}) != len(self.tools)
        ):
            raise NetworkTextContractError("tools are invalid")
        if type(self.stream) is not bool:
            raise NetworkTextContractError("stream must be exact bool")
        if type(self.budget) is not NetworkTextBudgetV1:
            raise NetworkTextContractError("budget must be exact")
        if type(self.data_class) is not DataClassV1:
            raise NetworkTextContractError("data_class must be exact")

    @property
    def digest(self) -> str:
        return _sha(
            {
                "schema": "OnyxNetworkTextRequest.v1",
                "request_id": self.request_id,
                "messages": [
                    {"role": item.role, "content_digest": _sha(item.content.encode())}
                    for item in self.messages
                ],
                "tools": [
                    {
                        "name": item.name,
                        "description_digest": _sha(item.description.encode()),
                        "schema_digest": _sha(item.input_schema),
                    }
                    for item in self.tools
                ],
                "stream": self.stream,
                "data_class": self.data_class.value,
                "budget": {
                    "maximum_request_bytes": self.budget.maximum_request_bytes,
                    "maximum_response_bytes": self.budget.maximum_response_bytes,
                    "maximum_output_tokens": self.budget.maximum_output_tokens,
                    "maximum_stream_events": self.budget.maximum_stream_events,
                    "timeout_millis": int(self.budget.timeout_seconds * 1_000),
                },
            }
        )


def _validate_schema(schema: object, depth: int = 0) -> None:
    if depth > 8 or type(schema) is not dict:
        raise NetworkTextContractError("tool schema is invalid")
    _validate_json(schema, label="tool schema", maximum=MAX_SCHEMA_BYTES)
    unknown = set(schema) - _SCHEMA_KEYS
    if unknown:
        raise NetworkTextContractError("tool schema keyword is unsupported")
    for name in ("minLength", "maxLength", "minItems", "maxItems"):
        if name in schema and (
            type(schema[name]) is not int or not 0 <= schema[name] <= 65_536
        ):
            raise NetworkTextContractError("tool schema bound is invalid")
    for name in ("minimum", "maximum"):
        if name in schema and (
            type(schema[name]) not in {int, float}
            or isinstance(schema[name], bool)
        ):
            raise NetworkTextContractError("tool schema numeric bound is invalid")
    if "pattern" in schema:
        if type(schema["pattern"]) is not str or len(schema["pattern"]) > 1_024:
            raise NetworkTextContractError("tool schema pattern is invalid")
        try:
            re.compile(schema["pattern"])
        except re.error as exc:
            raise NetworkTextContractError("tool schema pattern is invalid") from exc
    if "description" in schema:
        _text(schema["description"], "schema description", 8_192, empty=True)
    if "enum" in schema and (
        type(schema["enum"]) is not list
        or not schema["enum"]
        or len(schema["enum"]) > 128
    ):
        raise NetworkTextContractError("tool schema enum is invalid")
    kind = schema.get("type")
    if kind not in {"object", "array", "string", "integer", "number", "boolean", "null"}:
        raise NetworkTextContractError("tool schema type is unsupported")
    properties = schema.get("properties", {})
    if kind == "object":
        if type(properties) is not dict or len(properties) > 64:
            raise NetworkTextContractError("tool schema properties are invalid")
        for name, child in properties.items():
            if type(name) is not str or not name or len(name) > 128:
                raise NetworkTextContractError("tool property name is invalid")
            _validate_schema(child, depth + 1)
        required = schema.get("required", [])
        if type(required) is not list or any(
            type(name) is not str or name not in properties for name in required
        ):
            raise NetworkTextContractError("tool required properties are invalid")
        if len(set(required)) != len(required):
            raise NetworkTextContractError("tool required properties are duplicated")
        if schema.get("additionalProperties", False) is not False:
            raise NetworkTextContractError("additional tool properties are denied")
    elif "properties" in schema or "required" in schema or "additionalProperties" in schema:
        raise NetworkTextContractError("object keywords require object schema")
    if kind == "array":
        if "items" not in schema:
            raise NetworkTextContractError("array tool schema requires items")
        _validate_schema(schema["items"], depth + 1)
    elif "items" in schema:
        raise NetworkTextContractError("items requires array schema")


def _validate_tool_value(value: object, schema: Mapping[str, object]) -> None:
    kind = schema["type"]
    valid = {
        "object": isinstance(value, Mapping),
        "array": type(value) in {list, tuple},
        "string": type(value) is str,
        "integer": type(value) is int,
        "number": type(value) in {int, float} and not isinstance(value, bool),
        "boolean": type(value) is bool,
        "null": value is None,
    }[str(kind)]
    if not valid:
        raise NetworkTextContractError("tool arguments violate declared type")
    if "enum" in schema and value not in schema["enum"]:
        raise NetworkTextContractError("tool arguments violate enum")
    if "const" in schema and value != schema["const"]:
        raise NetworkTextContractError("tool arguments violate const")
    if kind == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", ())
        if any(name not in value for name in required):
            raise NetworkTextContractError("tool arguments miss required property")
        if set(value) - set(properties):
            raise NetworkTextContractError("tool arguments contain unknown property")
        for name, child in value.items():
            _validate_tool_value(child, properties[name])
    elif kind == "array":
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise NetworkTextContractError("tool array is too short")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise NetworkTextContractError("tool array is too long")
        for child in value:
            _validate_tool_value(child, schema["items"])
    elif kind == "string":
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise NetworkTextContractError("tool string is too short")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise NetworkTextContractError("tool string is too long")
        if "pattern" in schema:
            try:
                matched = re.fullmatch(str(schema["pattern"]), value)
            except re.error as exc:
                raise NetworkTextContractError("tool schema pattern is invalid") from exc
            if matched is None:
                raise NetworkTextContractError("tool string violates pattern")
    elif kind in {"integer", "number"}:
        if "minimum" in schema and value < schema["minimum"]:
            raise NetworkTextContractError("tool number is too small")
        if "maximum" in schema and value > schema["maximum"]:
            raise NetworkTextContractError("tool number is too large")


@dataclass(frozen=True, slots=True)
class NetworkTextToolCallV1:
    call_id: str
    name: str
    arguments: Mapping[str, object]

    def __post_init__(self) -> None:
        _text(self.call_id, "tool call id", 256, empty=True)
        if type(self.name) is not str or _TOOL_NAME.fullmatch(self.name) is None:
            raise NetworkTextContractError("tool call name is invalid")
        if type(self.arguments) is not dict:
            raise NetworkTextContractError("tool arguments must be an exact object")
        _validate_json(
            self.arguments, label="tool arguments", maximum=MAX_SCHEMA_BYTES
        )
        object.__setattr__(self, "arguments", _deep_freeze(self.arguments))

    @property
    def digest(self) -> str:
        return _sha(
            {
                "schema": "OnyxNetworkTextToolCall.v1",
                "call_id": self.call_id,
                "name": self.name,
                "arguments": self.arguments,
            }
        )


def _tool_calls_digest(calls: tuple[NetworkTextToolCallV1, ...]) -> str:
    return _sha(
        {
            "schema": "OnyxNetworkTextToolCalls.v1",
            "calls": [call.digest for call in calls],
        }
    )


@dataclass(frozen=True, slots=True)
class NetworkTextResultV1:
    request_id: str
    status: str
    content: str
    tool_calls: tuple[NetworkTextToolCallV1, ...]
    adapter_id: str
    request_digest: str
    route_digest: str
    authority_digest: str
    content_digest: str
    tool_calls_digest: str
    provider_calls: int
    output_emitted: bool
    reason: str
    receipt_digest: str

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        if self.status not in {
            "completed",
            "auth_missing",
            "blocked",
            "cancelled",
            "unavailable",
            "rejected",
            "malformed",
            "budget_exceeded",
            "reconciliation_required",
            "partial_failure",
        }:
            raise NetworkTextContractError("result status is invalid")
        _text(self.content, "result content", MAX_TEXT_BYTES, empty=True)
        if type(self.tool_calls) is not tuple or any(
            type(item) is not NetworkTextToolCallV1 for item in self.tool_calls
        ):
            raise NetworkTextContractError("result tool calls are invalid")
        _identifier(self.adapter_id, "adapter_id")
        for digest in (
            self.request_digest,
            self.route_digest,
            self.authority_digest,
            self.content_digest,
            self.tool_calls_digest,
            self.receipt_digest,
        ):
            if type(digest) is not str or _DIGEST.fullmatch(digest) is None:
                raise NetworkTextContractError("result digest is invalid")
        if self.content_digest != _sha(self.content.encode("utf-8")):
            raise NetworkTextContractError("content digest mismatch")
        if self.tool_calls_digest != _tool_calls_digest(self.tool_calls):
            raise NetworkTextContractError("tool-call digest mismatch")
        if type(self.provider_calls) is not int or self.provider_calls not in {0, 1}:
            raise NetworkTextContractError("provider call accounting is invalid")
        if type(self.output_emitted) is not bool:
            raise NetworkTextContractError("output accounting is invalid")
        _identifier(self.reason, "reason")
        if self.receipt_digest != _sha(self.receipt_payload()):
            raise NetworkTextContractError("receipt digest mismatch")

    def receipt_payload(self) -> dict[str, object]:
        return {
            "schema": "OnyxNetworkTextReceipt.v1",
            "request_id": self.request_id,
            "status": self.status,
            "adapter_id": self.adapter_id,
            "request_digest": self.request_digest,
            "route_digest": self.route_digest,
            "authority_digest": self.authority_digest,
            "content_digest": self.content_digest,
            "tool_calls_digest": self.tool_calls_digest,
            "provider_calls": self.provider_calls,
            "output_emitted": self.output_emitted,
            "reason": self.reason,
        }

    def stored_payload(self) -> dict[str, object]:
        """Exact replay payload. Unlike receipts, the private store holds output."""

        return {
            **self.receipt_payload(),
            "schema": "OnyxNetworkTextStoredResult.v1",
            "content": self.content,
            "tool_calls": [
                {
                    "call_id": call.call_id,
                    "name": call.name,
                    "arguments": _thaw(call.arguments),
                }
                for call in self.tool_calls
            ],
            "receipt_digest": self.receipt_digest,
        }

    @classmethod
    def from_stored_payload(cls, raw: Mapping[str, object]) -> "NetworkTextResultV1":
        if raw.get("schema") != "OnyxNetworkTextStoredResult.v1":
            raise NetworkTextContractError("stored result schema is invalid")
        calls_raw = raw.get("tool_calls")
        if type(calls_raw) is not list or len(calls_raw) > MAX_TOOLS:
            raise NetworkTextContractError("stored tool calls are invalid")
        calls: list[NetworkTextToolCallV1] = []
        for item in calls_raw:
            if type(item) is not dict:
                raise NetworkTextContractError("stored tool call is invalid")
            calls.append(
                NetworkTextToolCallV1(
                    item.get("call_id"), item.get("name"), item.get("arguments")
                )
            )
        return cls(
            raw.get("request_id"),
            raw.get("status"),
            raw.get("content"),
            tuple(calls),
            raw.get("adapter_id"),
            raw.get("request_digest"),
            raw.get("route_digest"),
            raw.get("authority_digest"),
            raw.get("content_digest"),
            raw.get("tool_calls_digest"),
            raw.get("provider_calls"),
            raw.get("output_emitted"),
            raw.get("reason"),
            raw.get("receipt_digest"),
        )


@dataclass(frozen=True, slots=True)
class NetworkTextConfigV1:
    provider: NetworkTextProviderV1
    model: str

    def __post_init__(self) -> None:
        if type(self.provider) is not NetworkTextProviderV1:
            raise NetworkTextContractError("provider is invalid")
        route = _ROUTES_BY_PROVIDER[self.provider]
        if self.model not in route.models:
            raise NetworkTextDenied("model is not allowlisted for provider route")


class NetworkTextAccountResolverV1(Protocol):
    """Trusted activation capability; never implemented from request data."""

    def resolve_current_account(
        self, provider: NetworkTextProviderV1
    ) -> tuple[str, str, str]: ...


@dataclass(frozen=True, slots=True)
class _NetworkTextAccountBindingV1:
    provider: NetworkTextProviderV1
    owner_id: str
    workspace_id: str
    account_id: str

    def __post_init__(self) -> None:
        if type(self.provider) is not NetworkTextProviderV1:
            raise NetworkTextContractError("binding provider is invalid")
        _identifier(self.owner_id, "owner_id")
        _identifier(self.workspace_id, "workspace_id")
        _identifier(self.account_id, "account_id")

    @property
    def credential_alias(self) -> str:
        return (
            f"onyx/network-text/{self.owner_id}/{self.workspace_id}/"
            f"{self.provider.value}/{self.account_id}"
        )

    @property
    def digest(self) -> str:
        return _sha(
            {
                "schema": "OnyxNetworkTextAccountBinding.v1",
                "provider": self.provider.value,
                "owner_id": self.owner_id,
                "workspace_id": self.workspace_id,
                "account_id": self.account_id,
                "credential_alias_digest": _sha(self.credential_alias.encode()),
            }
        )

    def __eq__(self, other: object) -> bool:
        return type(other) is _NetworkTextAccountBindingV1 and hmac.compare_digest(
            self.digest, other.digest
        )


@dataclass(frozen=True, slots=True)
class _NetworkTextDispatchVerificationV1:
    binding: _NetworkTextAccountBindingV1
    credential_alias: str
    authority_digest: str
    request_digest: str
    route_decision_digest: str

    def __post_init__(self) -> None:
        if type(self.binding) is not _NetworkTextAccountBindingV1:
            raise NetworkTextContractError("dispatch binding is invalid")
        if self.credential_alias != self.binding.credential_alias:
            raise NetworkTextDenied("dispatch credential alias drifted")
        for digest in (
            self.authority_digest,
            self.request_digest,
            self.route_decision_digest,
        ):
            if type(digest) is not str or _DIGEST.fullmatch(digest) is None:
                raise NetworkTextContractError("dispatch digest is invalid")


def _resolve_current_account(
    resolver: NetworkTextAccountResolverV1,
    provider: NetworkTextProviderV1,
) -> _NetworkTextAccountBindingV1:
    callback = getattr(resolver, "resolve_current_account", None)
    if not callable(callback):
        raise NetworkTextContractError(
            "trusted live-activation account resolver required"
        )
    try:
        resolved = callback(provider)
    except NetworkTextError:
        raise
    except Exception as exc:
        raise NetworkTextDenied("current host account resolution failed") from exc
    if type(resolved) is not tuple or len(resolved) != 3:
        raise NetworkTextDenied("current host account resolution is invalid")
    return _NetworkTextAccountBindingV1(provider, *resolved)


def _route_plan_digest(plan: ProviderRoutePlanV1) -> str:
    return _sha(
        {
            "schema": "OnyxAuthenticatedProviderRouteDecision.v1",
            "status": plan.status.value,
            "reason": plan.reason,
            "request_digest": plan.request_digest,
            "targets": [
                {
                    "adapter_id": target.adapter_id,
                    "provider_id": target.provider_id,
                    "api_version": target.api_version,
                    "model_id": target.model_id,
                    "record_version": target.record_version,
                    "provider_record_digest": target.provider_record_digest,
                    "health_digest": target.health_digest,
                    "health_status": target.health_status.value,
                }
                for target in plan.ordered_targets
            ],
            "considered": plan.considered,
            "exclusion_digest": plan.exclusion_digest,
        }
    )


class NetworkTextAuthorityV1:
    """Opaque registry-issued authority. Direct construction is denied."""

    __slots__ = (
        "_account_binding",
        "_authority_digest",
        "_model",
        "_provider_record_digest",
        "_registry_digest",
        "_route_decision_digest",
        "_route_digest",
        "_seal",
    )

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise NetworkTextDenied("authority construction is issuer-only")

    @property
    def digest(self) -> str:
        return self._authority_digest


class NetworkTextAuthorityIssuerV1:
    __slots__ = (
        "_account_resolver",
        "_key",
        "_records",
        "_registry",
        "_registry_digest",
    )

    def __init__(
        self,
        *,
        registry: ProviderRegistryV1,
        account_resolver: NetworkTextAccountResolverV1,
    ) -> None:
        if type(registry) is not ProviderRegistryV1:
            raise NetworkTextContractError("exact ProviderRegistryV1 required")
        if not callable(getattr(account_resolver, "resolve_current_account", None)):
            raise NetworkTextContractError(
                "trusted live-activation account resolver required"
            )
        records = registry.records
        self._registry = registry
        self._registry_digest = registry.digest
        self._records = tuple(records)
        self._account_resolver = account_resolver
        registry_key = getattr(registry, "_authentication_key", None)
        if type(registry_key) is not bytes or len(registry_key) != 32:
            raise NetworkTextDenied("registry authentication binding is unavailable")
        # Stable across a registry reload with the same protected registry key,
        # but domain-separated from provider-health authentication.
        self._key = hmac.new(
            registry_key,
            b"OnyxNetworkTextAuthorityIssuer.v1",
            hashlib.sha256,
        ).digest()

    def _attest_registry(self) -> None:
        if (
            type(self._registry) is not ProviderRegistryV1
            or self._registry.digest != self._registry_digest
            or self._registry.records != self._records
            or type(self._key) is not bytes
            or len(self._key) != 32
        ):
            raise NetworkTextDenied("provider registry binding drifted")

    @staticmethod
    def _policy(
        binding: _NetworkTextAccountBindingV1,
        request: NetworkTextRequestV1 | None,
    ) -> RouteRequestV1:
        data_class = DataClassV1.INTERNAL if request is None else request.data_class
        structured = False if request is None else bool(request.tools)
        maximum_latency = (
            MAX_TIMEOUT_SECONDS * 1_000
            if request is None
            else max(1, int(request.budget.timeout_seconds * 1_000))
        )
        return RouteRequestV1(
            binding.workspace_id,
            data_class,
            "text",
            False,
            structured,
            maximum_latency,
            1_000_000_000,
            0,
        )

    def _ready_route(
        self,
        config: NetworkTextConfigV1,
        binding: _NetworkTextAccountBindingV1,
        request: NetworkTextRequestV1 | None,
    ) -> tuple[ProviderRecordV1, str]:
        route = _ROUTES_BY_PROVIDER[config.provider]
        policy = self._policy(binding, request)
        try:
            plan = self._registry.plan_route(
                policy, now_ms=time.time_ns() // 1_000_000
            )
        except (ProviderRegistryV1ContractError, ProviderRegistryV1Denied) as exc:
            raise NetworkTextDenied("provider registry route decision denied") from exc
        if (
            type(plan) is not ProviderRoutePlanV1
            or plan.status is not ProviderRoutePlanStatusV1.READY
        ):
            raise NetworkTextDenied("provider registry route is not ready")
        target = next(
            (
                item
                for item in plan.ordered_targets
                if type(item) is ProviderRouteTargetV1
                and item.adapter_id == route.adapter_id
                and item.provider_id == config.provider.value
                and item.api_version == route.api_version
                and item.model_id == config.model
            ),
            None,
        )
        if type(target) is not ProviderRouteTargetV1:
            raise NetworkTextDenied("provider registry did not select exact route")
        record = next(
            (
                item
                for item in self._records
                if item.adapter_id == target.adapter_id
                and item.provider_id == target.provider_id
                and item.api_version == target.api_version
                and item.model_id == target.model_id
                and item.record_version == target.record_version
                and item.digest == target.provider_record_digest
            ),
            None,
        )
        if (
            type(record) is not ProviderRecordV1
            or not record.descriptor.network_required
            or record.descriptor.local_private
        ):
            raise NetworkTextDenied("provider route violates network policy")
        return record, _route_plan_digest(plan)

    def issue(self, config: NetworkTextConfigV1) -> NetworkTextAuthorityV1:
        self._attest_registry()
        if type(config) is not NetworkTextConfigV1:
            raise NetworkTextContractError("exact config required")
        binding = _resolve_current_account(self._account_resolver, config.provider)
        route = _ROUTES_BY_PROVIDER[config.provider]
        record, decision_digest = self._ready_route(config, binding, None)
        payload = {
            "schema": "OnyxNetworkTextAuthority.v1",
            "registry_digest": self._registry_digest,
            "provider_record_digest": record.digest,
            "route_digest": route.digest,
            "route_decision_digest": decision_digest,
            "model": config.model,
            "account_binding_digest": binding.digest,
        }
        encoded = _canonical(payload)
        seal = hmac.new(self._key, encoded, hashlib.sha256).hexdigest()
        authority_digest = _sha(
            {
                "schema": "OnyxSealedNetworkTextAuthority.v1",
                "payload_digest": _sha(encoded),
                "seal": seal,
            }
        )
        authority = object.__new__(NetworkTextAuthorityV1)
        authority._registry_digest = self._registry_digest
        authority._provider_record_digest = record.digest
        authority._route_digest = route.digest
        authority._route_decision_digest = decision_digest
        authority._model = config.model
        authority._account_binding = binding
        authority._seal = seal
        authority._authority_digest = authority_digest
        return authority

    def verify(
        self,
        authority: NetworkTextAuthorityV1,
        config: NetworkTextConfigV1,
        request: NetworkTextRequestV1 | None = None,
    ) -> _NetworkTextAccountBindingV1:
        self._attest_registry()
        if type(authority) is not NetworkTextAuthorityV1:
            raise NetworkTextDenied("exact opaque authority required")
        if type(config) is not NetworkTextConfigV1:
            raise NetworkTextContractError("exact config required")
        route = _ROUTES_BY_PROVIDER[config.provider]
        binding = _resolve_current_account(self._account_resolver, config.provider)
        record, issuance_decision_digest = self._ready_route(config, binding, None)
        if request is not None:
            request_record, _ = self._ready_route(config, binding, request)
            if request_record.digest != record.digest:
                raise NetworkTextDenied("provider registry request route drifted")
        payload = {
            "schema": "OnyxNetworkTextAuthority.v1",
            "registry_digest": self._registry_digest,
            "provider_record_digest": record.digest,
            "route_digest": route.digest,
            "route_decision_digest": issuance_decision_digest,
            "model": config.model,
            "account_binding_digest": binding.digest,
        }
        expected_seal = hmac.new(
            self._key, _canonical(payload), hashlib.sha256
        ).hexdigest()
        expected_digest = _sha(
            {
                "schema": "OnyxSealedNetworkTextAuthority.v1",
                "payload_digest": _sha(_canonical(payload)),
                "seal": expected_seal,
            }
        )
        if (
            authority._registry_digest != self._registry_digest
            or authority._provider_record_digest != record.digest
            or authority._route_digest != route.digest
            or authority._route_decision_digest != issuance_decision_digest
            or authority._model != config.model
            or authority._account_binding != binding
            or not hmac.compare_digest(authority._seal, expected_seal)
            or not hmac.compare_digest(authority._authority_digest, expected_digest)
        ):
            raise NetworkTextDenied("network text authority is forged or drifted")
        return binding

    def verify_dispatch(
        self,
        authority: NetworkTextAuthorityV1,
        config: NetworkTextConfigV1,
        request: NetworkTextRequestV1,
    ) -> _NetworkTextDispatchVerificationV1:
        if type(request) is not NetworkTextRequestV1:
            raise NetworkTextContractError("exact network text request required")
        binding = self.verify(authority, config, request)
        _, decision_digest = self._ready_route(config, binding, request)
        return _NetworkTextDispatchVerificationV1(
            binding,
            binding.credential_alias,
            authority.digest,
            request.digest,
            decision_digest,
        )


def create_network_text_authority_issuer_v1(
    *,
    registry: ProviderRegistryV1,
    account_resolver: NetworkTextAccountResolverV1 | None = None,
) -> NetworkTextAuthorityIssuerV1:
    if account_resolver is None:
        raise NetworkTextContractError(
            "trusted live-activation account resolver required"
        )
    return NetworkTextAuthorityIssuerV1(
        registry=registry, account_resolver=account_resolver
    )


class NetworkTextAttemptStateV1(StrEnum):
    RESERVED = "reserved"
    UNKNOWN = "unknown"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class NetworkTextAttemptKeyV1:
    owner_id: str
    workspace_id: str
    request_id: str

    def __post_init__(self) -> None:
        _identifier(self.owner_id, "owner_id")
        _identifier(self.workspace_id, "workspace_id")
        _identifier(self.request_id, "request_id")


@dataclass(frozen=True, slots=True)
class NetworkTextAttemptDecisionV1:
    state: NetworkTextAttemptStateV1
    lease_id: str | None
    result: NetworkTextResultV1 | None

    def __post_init__(self) -> None:
        if type(self.state) is not NetworkTextAttemptStateV1:
            raise NetworkTextContractError("attempt state is invalid")
        if self.state is NetworkTextAttemptStateV1.RESERVED:
            _text(self.lease_id, "lease_id", 128)
            if self.result is not None:
                raise NetworkTextContractError("reserved attempt has a result")
        elif self.state is NetworkTextAttemptStateV1.COMPLETED:
            if self.lease_id is not None or type(self.result) is not NetworkTextResultV1:
                raise NetworkTextContractError("completed attempt is invalid")
        elif self.lease_id is not None or self.result is not None:
            raise NetworkTextContractError("unknown attempt is invalid")


class NetworkTextAttemptStoreV1(Protocol):
    def reserve(
        self, key: NetworkTextAttemptKeyV1, request_digest: str
    ) -> NetworkTextAttemptDecisionV1: ...

    def complete(
        self,
        key: NetworkTextAttemptKeyV1,
        request_digest: str,
        lease_id: str,
        result: NetworkTextResultV1,
    ) -> None: ...

    def mark_unknown(
        self, key: NetworkTextAttemptKeyV1, request_digest: str, lease_id: str
    ) -> None: ...

    def release_not_dispatched(
        self, key: NetworkTextAttemptKeyV1, request_digest: str, lease_id: str
    ) -> None: ...

    def reconcile_not_dispatched(
        self, key: NetworkTextAttemptKeyV1, request_digest: str
    ) -> None: ...

    def reconcile_completed(
        self,
        key: NetworkTextAttemptKeyV1,
        request_digest: str,
        result: NetworkTextResultV1,
    ) -> None: ...


class SqliteNetworkTextAttemptStoreV1:
    """Crash-durable at-most-once store; every mutation is a full transaction."""

    __slots__ = ("_path", "_lock")

    def __init__(self, path: Path | str) -> None:
        raw = Path(path)
        if not raw.is_absolute() or raw.suffix.lower() not in {".sqlite", ".db"}:
            raise NetworkTextContractError("attempt store path must be absolute SQLite")
        raw.parent.mkdir(parents=True, exist_ok=True)
        self._path = raw
        self._lock = threading.RLock()
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS network_text_attempts (
                    owner_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    state TEXT NOT NULL,
                    lease_id TEXT,
                    result_json BLOB,
                    PRIMARY KEY (owner_id, workspace_id, request_id)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=10.0, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _identity(key: NetworkTextAttemptKeyV1) -> tuple[str, str, str]:
        if type(key) is not NetworkTextAttemptKeyV1:
            raise NetworkTextContractError("exact attempt key required")
        return key.owner_id, key.workspace_id, key.request_id

    @staticmethod
    def _request_digest(value: str) -> str:
        if type(value) is not str or _DIGEST.fullmatch(value) is None:
            raise NetworkTextContractError("request digest is invalid")
        return value

    def reserve(
        self, key: NetworkTextAttemptKeyV1, request_digest: str
    ) -> NetworkTextAttemptDecisionV1:
        identity = self._identity(key)
        digest = self._request_digest(request_digest)
        lease = secrets.token_hex(24)
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT request_digest, state, result_json FROM network_text_attempts "
                "WHERE owner_id=? AND workspace_id=? AND request_id=?",
                identity,
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO network_text_attempts VALUES (?, ?, ?, ?, ?, ?, NULL)",
                    (*identity, digest, NetworkTextAttemptStateV1.RESERVED.value, lease),
                )
                connection.execute("COMMIT")
                return NetworkTextAttemptDecisionV1(
                    NetworkTextAttemptStateV1.RESERVED, lease, None
                )
            if not hmac.compare_digest(str(row[0]), digest):
                connection.execute("ROLLBACK")
                raise NetworkTextDenied("request id was reused with different content")
            state = NetworkTextAttemptStateV1(str(row[1]))
            if state is NetworkTextAttemptStateV1.COMPLETED:
                if type(row[2]) is not bytes:
                    connection.execute("ROLLBACK")
                    raise NetworkTextDenied("stored completed result is unavailable")
                try:
                    payload = json.loads(row[2].decode("utf-8"))
                    result = NetworkTextResultV1.from_stored_payload(payload)
                except Exception as exc:
                    connection.execute("ROLLBACK")
                    raise NetworkTextDenied("stored completed result failed attestation") from exc
                if result.request_digest != digest:
                    connection.execute("ROLLBACK")
                    raise NetworkTextDenied("stored result request digest drifted")
                connection.execute("COMMIT")
                return NetworkTextAttemptDecisionV1(
                    NetworkTextAttemptStateV1.COMPLETED, None, result
                )
            # A pre-existing reservation is ambiguous to this caller.  Leave
            # its lease intact so an actually in-flight owner can still commit;
            # after a crash it remains reconciliation-required on every read.
            connection.execute("COMMIT")
            return NetworkTextAttemptDecisionV1(
                NetworkTextAttemptStateV1.UNKNOWN, None, None
            )

    def _leased_mutation(
        self,
        key: NetworkTextAttemptKeyV1,
        request_digest: str,
        lease_id: str,
        *,
        state: NetworkTextAttemptStateV1 | None,
        result: NetworkTextResultV1 | None = None,
    ) -> None:
        identity = self._identity(key)
        digest = self._request_digest(request_digest)
        _text(lease_id, "lease_id", 128)
        encoded = None if result is None else _canonical(result.stored_payload())
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if state is None:
                cursor = connection.execute(
                    "DELETE FROM network_text_attempts WHERE owner_id=? AND workspace_id=? "
                    "AND request_id=? AND request_digest=? AND state=? AND lease_id=?",
                    (
                        *identity,
                        digest,
                        NetworkTextAttemptStateV1.RESERVED.value,
                        lease_id,
                    ),
                )
            else:
                cursor = connection.execute(
                    "UPDATE network_text_attempts SET state=?, lease_id=NULL, result_json=? "
                    "WHERE owner_id=? AND workspace_id=? AND request_id=? "
                    "AND request_digest=? AND state=? AND lease_id=?",
                    (
                        state.value,
                        encoded,
                        *identity,
                        digest,
                        NetworkTextAttemptStateV1.RESERVED.value,
                        lease_id,
                    ),
                )
            if cursor.rowcount != 1:
                connection.execute("ROLLBACK")
                raise NetworkTextDenied("attempt lease is stale or forged")
            connection.execute("COMMIT")

    def complete(self, key, request_digest, lease_id, result) -> None:
        if type(result) is not NetworkTextResultV1:
            raise NetworkTextContractError("exact result required")
        if result.request_digest != request_digest or result.request_id != key.request_id:
            raise NetworkTextDenied("completed result does not match attempt")
        self._leased_mutation(
            key,
            request_digest,
            lease_id,
            state=NetworkTextAttemptStateV1.COMPLETED,
            result=result,
        )

    def mark_unknown(self, key, request_digest, lease_id) -> None:
        self._leased_mutation(
            key,
            request_digest,
            lease_id,
            state=NetworkTextAttemptStateV1.UNKNOWN,
        )

    def release_not_dispatched(self, key, request_digest, lease_id) -> None:
        self._leased_mutation(
            key, request_digest, lease_id, state=None
        )

    def _reconcile(
        self,
        key: NetworkTextAttemptKeyV1,
        request_digest: str,
        result: NetworkTextResultV1 | None,
    ) -> None:
        identity = self._identity(key)
        digest = self._request_digest(request_digest)
        if result is not None and (
            type(result) is not NetworkTextResultV1
            or result.request_id != key.request_id
            or result.request_digest != digest
        ):
            raise NetworkTextDenied("reconciled result does not match attempt")
        encoded = None if result is None else _canonical(result.stored_payload())
        with self._lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT request_digest, state FROM network_text_attempts "
                "WHERE owner_id=? AND workspace_id=? AND request_id=?",
                identity,
            ).fetchone()
            if (
                row is None
                or not hmac.compare_digest(str(row[0]), digest)
                or row[1]
                not in {
                    NetworkTextAttemptStateV1.RESERVED.value,
                    NetworkTextAttemptStateV1.UNKNOWN.value,
                }
            ):
                connection.execute("ROLLBACK")
                raise NetworkTextDenied("attempt is not awaiting reconciliation")
            if result is None:
                connection.execute(
                    "DELETE FROM network_text_attempts WHERE owner_id=? AND workspace_id=? "
                    "AND request_id=?",
                    identity,
                )
            else:
                connection.execute(
                    "UPDATE network_text_attempts SET state=?, lease_id=NULL, result_json=? "
                    "WHERE owner_id=? AND workspace_id=? AND request_id=?",
                    (
                        NetworkTextAttemptStateV1.COMPLETED.value,
                        encoded,
                        *identity,
                    ),
                )
            connection.execute("COMMIT")

    def reconcile_not_dispatched(self, key, request_digest) -> None:
        self._reconcile(key, request_digest, None)

    def reconcile_completed(self, key, request_digest, result) -> None:
        self._reconcile(key, request_digest, result)


class CredentialResolverV1(Protocol):
    def resolve(self, alias: str) -> bytes | None: ...


class NetworkTextCancellationV1:
    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True, slots=True)
class NetworkTextHttpRequestV1:
    url: str
    origin: str
    path: str
    headers: Mapping[str, str]
    body: bytes
    timeout_seconds: float
    stream: bool
    maximum_response_bytes: int

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != self.origin
            or parsed.hostname != self.origin
            or parsed.port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != self.path
            or parsed.query
            or parsed.fragment
        ):
            raise NetworkTextDenied("HTTP route is not exact")
        if type(self.headers) is not dict or not self.headers:
            raise NetworkTextContractError("HTTP headers are invalid")
        for key, value in self.headers.items():
            if type(key) is not str or type(value) is not str:
                raise NetworkTextContractError("HTTP header is invalid")
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
        if type(self.body) is not bytes or not self.body:
            raise NetworkTextContractError("HTTP body is invalid")
        if type(self.timeout_seconds) not in {int, float} or isinstance(
            self.timeout_seconds, bool
        ):
            raise NetworkTextContractError("HTTP timeout is invalid")
        if not 0.001 <= float(self.timeout_seconds) <= MAX_TIMEOUT_SECONDS:
            raise NetworkTextContractError("HTTP timeout is outside its bound")
        if type(self.stream) is not bool:
            raise NetworkTextContractError("HTTP stream flag is invalid")
        if type(self.maximum_response_bytes) is not int or not (
            1 <= self.maximum_response_bytes <= MAX_RESPONSE_BYTES
        ):
            raise NetworkTextContractError("HTTP response budget is invalid")


@dataclass(frozen=True, slots=True)
class NetworkTextHttpResponseV1:
    status_code: int
    final_url: str
    body: bytes | Iterable[bytes]
    dispatched: bool = True

    def __post_init__(self) -> None:
        if type(self.status_code) is not int or not 100 <= self.status_code <= 599:
            raise NetworkTextContractError("HTTP status is invalid")
        _text(self.final_url, "HTTP final URL", 2_048)
        if type(self.dispatched) is not bool or not self.dispatched:
            raise NetworkTextContractError("a response must prove dispatch")
        if type(self.body) is not bytes and not isinstance(self.body, Iterable):
            raise NetworkTextContractError("HTTP response body is invalid")


class NetworkTextHttpTransportV1(Protocol):
    def post(
        self,
        request: NetworkTextHttpRequestV1,
        cancellation: NetworkTextCancellationV1,
    ) -> NetworkTextHttpResponseV1: ...


class StdlibNetworkTextHttpTransportV1:
    """TLS-validating, redirect-disabled stdlib transport with no retry."""

    __slots__ = ("_opener",)

    def __init__(self) -> None:
        context = ssl.create_default_context()

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        self._opener = urllib.request.build_opener(
            _NoRedirect(), urllib.request.HTTPSHandler(context=context)
        )

    def post(self, request, cancellation):
        if type(request) is not NetworkTextHttpRequestV1:
            raise NetworkTextContractError("exact HTTP request required")
        if type(cancellation) is not NetworkTextCancellationV1:
            raise NetworkTextContractError("exact cancellation token required")
        if cancellation.cancelled:
            raise NetworkTextNotDispatched("cancelled before dispatch")
        wire = urllib.request.Request(  # noqa: S310 - exact HTTPS route validated
            request.url,
            data=request.body,
            headers=dict(request.headers),
            method="POST",
        )
        try:
            response = self._opener.open(wire, timeout=float(request.timeout_seconds))
        except urllib.error.HTTPError as exc:
            response = exc
        except Exception as exc:
            # urllib cannot prove whether DNS/socket/TLS failures happened before
            # peer dispatch, so uncertainty is durable and never retried.
            raise NetworkTextReconciliationRequired(
                "provider outcome requires reconciliation"
            ) from exc
        final_url = response.geturl()
        status = int(response.code)
        if request.stream:

            def chunks() -> Iterator[bytes]:
                total = 0
                try:
                    while True:
                        if cancellation.cancelled:
                            raise NetworkTextReconciliationRequired(
                                "provider outcome requires reconciliation"
                            )
                        chunk = response.readline(65_537)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > request.maximum_response_bytes:
                            raise NetworkTextPostDispatchDenied(
                                "HTTP response exceeded budget"
                            )
                        yield bytes(chunk)
                except NetworkTextError:
                    raise
                except Exception as exc:
                    raise NetworkTextReconciliationRequired(
                        "provider outcome requires reconciliation"
                    ) from exc
                finally:
                    response.close()

            body: bytes | Iterable[bytes] = chunks()
        else:
            try:
                body = response.read(request.maximum_response_bytes + 1)
            except Exception as exc:
                raise NetworkTextReconciliationRequired(
                    "provider outcome requires reconciliation"
                ) from exc
            finally:
                response.close()
            if len(body) > request.maximum_response_bytes:
                raise NetworkTextPostDispatchDenied(
                    "HTTP response exceeded budget"
                )
        return NetworkTextHttpResponseV1(status, final_url, body, True)


def _strict_json(raw: bytes, maximum: int) -> dict[str, object]:
    if type(raw) is not bytes or len(raw) > maximum:
        raise NetworkTextPostDispatchDenied("provider response exceeded budget")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise NetworkTextContractError("provider response has duplicate keys")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise NetworkTextContractError("provider response is malformed") from exc
    if type(value) is not dict:
        raise NetworkTextContractError("provider response must be an object")
    _validate_json(value, label="provider response", maximum=maximum)
    return value


def _sse_data_frames(
    body: Iterable[bytes],
    *,
    maximum_bytes: int,
    cancellation: NetworkTextCancellationV1,
    remaining: object,
) -> Iterator[bytes]:
    buffer = b""
    total = 0
    for raw in body:
        if cancellation.cancelled or remaining() <= 0:
            raise NetworkTextReconciliationRequired(
                "provider outcome requires reconciliation"
            )
        if type(raw) is not bytes:
            raise NetworkTextContractError("stream chunk must be bytes")
        total += len(raw)
        if total > maximum_bytes:
            raise NetworkTextPostDispatchDenied("stream response exceeded budget")
        buffer += raw
        if len(buffer) > maximum_bytes:
            raise NetworkTextPostDispatchDenied("stream frame exceeded budget")
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            line = line.rstrip(b"\r").strip()
            if not line or line.startswith(b":") or line.startswith(b"event:"):
                continue
            if not line.startswith(b"data:"):
                raise NetworkTextContractError("stream frame is malformed")
            yield line[5:].strip()
    if buffer.strip():
        line = buffer.rstrip(b"\r").strip()
        if line.startswith(b"data:"):
            yield line[5:].strip()
        elif not line.startswith((b":", b"event:")):
            raise NetworkTextContractError("stream frame is malformed")


def _tool_arguments(value: object) -> dict[str, object]:
    if type(value) is str:
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise NetworkTextContractError("tool arguments are malformed") from exc
    if type(value) is not dict:
        raise NetworkTextContractError("tool arguments must be an object")
    _validate_json(value, label="tool arguments", maximum=MAX_SCHEMA_BYTES)
    return value


def _validate_tool_call(
    call_id: object,
    name: object,
    arguments: object,
    offered: Mapping[str, NetworkTextToolV1],
) -> NetworkTextToolCallV1:
    identifier = _text(call_id, "tool call id", 256, empty=True)
    tool_name = _text(name, "tool call name", 128)
    tool = offered.get(tool_name)
    if tool is None:
        raise NetworkTextDenied("provider returned an unoffered tool")
    parsed = _tool_arguments(arguments)
    _validate_tool_value(parsed, tool.input_schema)
    return NetworkTextToolCallV1(identifier, tool_name, parsed)


def _anthropic_response(
    payload: Mapping[str, object], offered: Mapping[str, NetworkTextToolV1]
) -> tuple[str, tuple[NetworkTextToolCallV1, ...]]:
    blocks = payload.get("content")
    if isinstance(blocks, (str, bytes)) or not isinstance(blocks, Sequence):
        raise NetworkTextContractError("Anthropic content is malformed")
    if len(blocks) > MAX_STREAM_EVENTS:
        raise NetworkTextContractError("Anthropic content has too many blocks")
    text_parts: list[str] = []
    calls: list[NetworkTextToolCallV1] = []
    for block in blocks:
        if not isinstance(block, Mapping):
            raise NetworkTextContractError("Anthropic block is malformed")
        if block.get("type") == "text":
            text_parts.append(
                _text(block.get("text"), "response text", MAX_TEXT_BYTES, empty=True)
            )
        elif block.get("type") == "tool_use":
            calls.append(
                _validate_tool_call(
                    block.get("id"), block.get("name"), block.get("input"), offered
                )
            )
        else:
            raise NetworkTextContractError("Anthropic block type is unsupported")
    return "".join(text_parts), tuple(calls)


def _openai_response(
    payload: Mapping[str, object], offered: Mapping[str, NetworkTextToolV1]
) -> tuple[str, tuple[NetworkTextToolCallV1, ...]]:
    choices = payload.get("choices")
    if (
        isinstance(choices, (str, bytes))
        or not isinstance(choices, Sequence)
        or len(choices) != 1
        or not isinstance(choices[0], Mapping)
    ):
        raise NetworkTextContractError("OpenAI-compatible choices are malformed")
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        raise NetworkTextContractError("OpenAI-compatible message is malformed")
    content = message.get("content") or ""
    _text(content, "response content", MAX_TEXT_BYTES, empty=True)
    raw_calls = message.get("tool_calls") or []
    if isinstance(raw_calls, (str, bytes)) or not isinstance(raw_calls, Sequence):
        raise NetworkTextContractError("tool calls are malformed")
    if len(raw_calls) > MAX_TOOLS:
        raise NetworkTextContractError("too many tool calls")
    calls: list[NetworkTextToolCallV1] = []
    for item in raw_calls:
        if not isinstance(item, Mapping) or not isinstance(
            item.get("function"), Mapping
        ):
            raise NetworkTextContractError("tool call is malformed")
        function = item["function"]
        calls.append(
            _validate_tool_call(
                item.get("id"),
                function.get("name"),
                function.get("arguments"),
                offered,
            )
        )
    return content, tuple(calls)


class NetworkTextReconciliationDecisionV1(StrEnum):
    CONFIRMED_NOT_DISPATCHED = "confirmed_not_dispatched"
    COMPLETED = "completed"


class NetworkTextClientV1:
    __slots__ = (
        "_attempt_store",
        "_authority",
        "_config",
        "_initial_binding",
        "_issuer",
        "_resolver",
        "_route",
        "_transport",
    )

    def __init__(
        self,
        *,
        config: NetworkTextConfigV1,
        authority: NetworkTextAuthorityV1,
        authority_issuer: NetworkTextAuthorityIssuerV1,
        account_resolver: NetworkTextAccountResolverV1,
        credential_resolver: CredentialResolverV1,
        transport: NetworkTextHttpTransportV1,
        attempt_store: NetworkTextAttemptStoreV1,
    ) -> None:
        if type(config) is not NetworkTextConfigV1:
            raise NetworkTextContractError("exact config required")
        if type(authority_issuer) is not NetworkTextAuthorityIssuerV1:
            raise NetworkTextContractError("exact authority issuer required")
        if account_resolver is not authority_issuer._account_resolver:
            raise NetworkTextDenied(
                "client account resolver is not the issuing live capability"
            )
        initial_binding = authority_issuer.verify(authority, config)
        for dependency, method, label in (
            (credential_resolver, "resolve", "credential resolver"),
            (transport, "post", "HTTP transport"),
            (attempt_store, "reserve", "attempt store"),
        ):
            if not hasattr(dependency, method):
                raise NetworkTextContractError(f"{label} is invalid")
        self._config = config
        self._initial_binding = initial_binding
        self._authority = authority
        self._issuer = authority_issuer
        self._resolver = credential_resolver
        self._transport = transport
        self._attempt_store = attempt_store
        self._route = _ROUTES_BY_PROVIDER[config.provider]

    @property
    def adapter_id(self) -> str:
        return self._route.adapter_id

    def _binding(
        self, request: NetworkTextRequestV1 | None = None
    ) -> _NetworkTextAccountBindingV1:
        return self._issuer.verify(self._authority, self._config, request)

    def _dispatch_verification(
        self, request: NetworkTextRequestV1
    ) -> _NetworkTextDispatchVerificationV1:
        return self._issuer.verify_dispatch(
            self._authority, self._config, request
        )

    def _key(self, request: NetworkTextRequestV1) -> NetworkTextAttemptKeyV1:
        return NetworkTextAttemptKeyV1(
            self._initial_binding.owner_id,
            self._initial_binding.workspace_id,
            request.request_id,
        )

    def _result(
        self,
        request: NetworkTextRequestV1,
        *,
        status: str,
        reason: str,
        content: str = "",
        tool_calls: tuple[NetworkTextToolCallV1, ...] = (),
        provider_calls: int = 0,
        output_emitted: bool = False,
    ) -> NetworkTextResultV1:
        content_digest = _sha(content.encode("utf-8"))
        calls_digest = _tool_calls_digest(tool_calls)
        payload = {
            "schema": "OnyxNetworkTextReceipt.v1",
            "request_id": request.request_id,
            "status": status,
            "adapter_id": self.adapter_id,
            "request_digest": request.digest,
            "route_digest": self._route.digest,
            "authority_digest": self._authority.digest,
            "content_digest": content_digest,
            "tool_calls_digest": calls_digest,
            "provider_calls": provider_calls,
            "output_emitted": output_emitted,
            "reason": reason,
        }
        return NetworkTextResultV1(
            request.request_id,
            status,
            content,
            tool_calls,
            self.adapter_id,
            request.digest,
            self._route.digest,
            self._authority.digest,
            content_digest,
            calls_digest,
            provider_calls,
            output_emitted,
            reason,
            _sha(payload),
        )

    @staticmethod
    def _remaining(deadline: float) -> float:
        return deadline - time.monotonic()

    @staticmethod
    def _check_before_dispatch(
        cancellation: NetworkTextCancellationV1, deadline: float
    ) -> None:
        if cancellation.cancelled:
            raise NetworkTextNotDispatched("cancelled before dispatch")
        if NetworkTextClientV1._remaining(deadline) <= 0:
            raise NetworkTextNotDispatched("deadline elapsed before dispatch")

    def _payload(self, request: NetworkTextRequestV1) -> dict[str, object]:
        system = "\n\n".join(
            item.content for item in request.messages if item.role == "system"
        )
        ordinary = [item for item in request.messages if item.role != "system"]
        if not ordinary:
            raise NetworkTextContractError("request requires a non-system message")
        if self._route.protocol is NetworkTextProtocolV1.ANTHROPIC_MESSAGES:
            payload: dict[str, object] = {
                "model": self._config.model,
                self._route.output_token_field: request.budget.maximum_output_tokens,
                "messages": [
                    {"role": item.role, "content": item.content} for item in ordinary
                ],
                "stream": request.stream,
            }
            if system:
                payload["system"] = system
            if request.tools:
                payload["tools"] = [
                    {
                        "name": item.name,
                        "description": item.description,
                        "input_schema": _thaw(item.input_schema),
                    }
                    for item in request.tools
                ]
            return payload
        payload = {
            "model": self._config.model,
            self._route.output_token_field: request.budget.maximum_output_tokens,
            "messages": [
                {"role": item.role, "content": item.content}
                for item in request.messages
            ],
            "stream": request.stream,
        }
        if request.tools:
            payload.update(
                {
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": item.name,
                                "description": item.description,
                                "parameters": _thaw(item.input_schema),
                            },
                        }
                        for item in request.tools
                    ],
                    "tool_choice": "auto",
                }
            )
        return payload

    def _wire_request(
        self,
        request: NetworkTextRequestV1,
        credential: bytes,
        remaining_seconds: float,
    ) -> NetworkTextHttpRequestV1:
        try:
            secret = credential.decode("ascii")
        except UnicodeDecodeError as exc:
            raise NetworkTextCredentialUnavailable(
                "vault credential is invalid"
            ) from exc
        if not secret or len(credential) > MAX_CREDENTIAL_BYTES or any(
            ord(character) < 33 or ord(character) > 126 for character in secret
        ):
            raise NetworkTextCredentialUnavailable("vault credential is invalid")
        body = _canonical(self._payload(request))
        if len(body) > request.budget.maximum_request_bytes:
            raise NetworkTextDenied("request exceeded byte budget")
        headers = {
            "Accept": "text/event-stream" if request.stream else "application/json",
            "Content-Type": "application/json",
            "User-Agent": "CyryxLabs-Onyx/1",
        }
        if self._route.protocol is NetworkTextProtocolV1.ANTHROPIC_MESSAGES:
            headers["x-api-key"] = secret
            headers["anthropic-version"] = self._route.api_version
        else:
            headers["Authorization"] = f"Bearer {secret}"
        return NetworkTextHttpRequestV1(
            f"https://{self._route.origin}{self._route.path}",
            self._route.origin,
            self._route.path,
            headers,
            body,
            max(0.001, remaining_seconds),
            request.stream,
            request.budget.maximum_response_bytes,
        )

    def _credential(
        self,
        binding: _NetworkTextAccountBindingV1,
        cancellation: NetworkTextCancellationV1,
        deadline: float,
    ) -> bytes:
        self._check_before_dispatch(cancellation, deadline)
        try:
            credential = self._resolver.resolve(binding.credential_alias)
        except Exception as exc:
            raise NetworkTextCredentialUnavailable(
                "vault credential resolution failed"
            ) from exc
        self._check_before_dispatch(cancellation, deadline)
        if type(credential) is not bytes:
            raise NetworkTextCredentialUnavailable("vault credential is unavailable")
        return credential

    def _dispatch_reserved(
        self,
        request: NetworkTextRequestV1,
        credential: bytes,
        cancellation: NetworkTextCancellationV1,
        deadline: float,
        verification: _NetworkTextDispatchVerificationV1,
        credential_resolver: CredentialResolverV1,
    ) -> NetworkTextHttpResponseV1:
        self._check_before_dispatch(cancellation, deadline)
        wire = self._wire_request(
            request, credential, self._remaining(deadline)
        )
        self._check_before_dispatch(cancellation, deadline)
        try:
            current = self._dispatch_verification(request)
        except Exception as exc:
            raise NetworkTextNotDispatched(
                "dispatch authority changed before transport"
            ) from exc
        if (
            self._resolver is not credential_resolver
            or current.binding.provider is not self._config.provider
            or current.binding.provider is not verification.binding.provider
            or current.binding.owner_id != verification.binding.owner_id
            or current.binding.workspace_id != verification.binding.workspace_id
            or current.binding.account_id != verification.binding.account_id
            or current.credential_alias != verification.credential_alias
            or current.authority_digest != verification.authority_digest
            or current.request_digest != verification.request_digest
            or current.route_decision_digest
            != verification.route_decision_digest
            or self._authority.digest != current.authority_digest
        ):
            raise NetworkTextNotDispatched(
                "dispatch authority changed before transport"
            )
        self._check_before_dispatch(cancellation, deadline)
        try:
            response = self._transport.post(wire, cancellation)
        except NetworkTextNotDispatched:
            raise
        except (NetworkTextPostDispatchDenied, NetworkTextReconciliationRequired):
            raise
        except Exception as exc:
            raise NetworkTextReconciliationRequired(
                "provider outcome requires reconciliation"
            ) from exc
        if type(response) is not NetworkTextHttpResponseV1:
            raise NetworkTextReconciliationRequired(
                "provider outcome requires reconciliation"
            )
        parsed = urlsplit(response.final_url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != self._route.origin
            or parsed.hostname != self._route.origin
            or parsed.port is not None
            or parsed.path != self._route.path
            or parsed.query
            or parsed.fragment
        ):
            raise NetworkTextPostDispatchDenied(
                "redirect or response-origin spoof denied"
            )
        if self._remaining(deadline) <= 0 or cancellation.cancelled:
            raise NetworkTextReconciliationRequired(
                "provider outcome requires reconciliation"
            )
        return response

    @staticmethod
    def _output_within_budget(
        content: str,
        calls: tuple[NetworkTextToolCallV1, ...],
        budget: NetworkTextBudgetV1,
    ) -> bool:
        arguments = _canonical(
            [
                {"id": call.call_id, "name": call.name, "arguments": call.arguments}
                for call in calls
            ]
        )
        return (
            len(content) + len(arguments.decode("utf-8"))
            <= budget.maximum_output_characters
            and len(content.encode("utf-8")) + len(arguments)
            <= budget.maximum_output_utf8_bytes
        )

    def _known_result(
        self,
        request: NetworkTextRequestV1,
        response: NetworkTextHttpResponseV1,
    ) -> NetworkTextResultV1:
        if type(response.body) is not bytes:
            return self._result(
                request,
                status="malformed",
                reason="nonstream_body_invalid",
                provider_calls=1,
            )
        if len(response.body) > request.budget.maximum_response_bytes:
            return self._result(
                request,
                status="budget_exceeded",
                reason="response_bytes_exceeded",
                provider_calls=1,
            )
        if response.status_code != 200:
            return self._result(
                request,
                status="rejected",
                reason="provider_http_rejected",
                provider_calls=1,
            )
        offered = MappingProxyType({tool.name: tool for tool in request.tools})
        try:
            payload = _strict_json(response.body, request.budget.maximum_response_bytes)
            if self._route.protocol is NetworkTextProtocolV1.ANTHROPIC_MESSAGES:
                content, calls = _anthropic_response(payload, offered)
            else:
                content, calls = _openai_response(payload, offered)
            if not self._output_within_budget(content, calls, request.budget):
                return self._result(
                    request,
                    status="budget_exceeded",
                    reason="local_output_budget_exceeded",
                    provider_calls=1,
                )
        except NetworkTextPostDispatchDenied:
            return self._result(
                request,
                status="budget_exceeded",
                reason="response_budget_denied",
                provider_calls=1,
            )
        except NetworkTextDenied:
            return self._result(
                request,
                status="blocked",
                reason="tool_policy_denied",
                provider_calls=1,
            )
        except NetworkTextContractError:
            return self._result(
                request,
                status="malformed",
                reason="response_schema_invalid",
                provider_calls=1,
            )
        return self._result(
            request,
            status="completed",
            reason="provider_completed",
            content=content,
            tool_calls=calls,
            provider_calls=1,
            output_emitted=bool(content or calls),
        )

    def _preflight_result(
        self,
        request: NetworkTextRequestV1,
        cancellation: NetworkTextCancellationV1,
    ) -> NetworkTextResultV1 | None:
        if request.stream and request.tools:
            return self._result(
                request, status="blocked", reason="stream_tools_unsupported"
            )
        if cancellation.cancelled:
            return self._result(
                request, status="cancelled", reason="cancelled_before_dispatch"
            )
        return None

    def _invoke_once(
        self,
        request: NetworkTextRequestV1,
        cancellation: NetworkTextCancellationV1,
    ) -> NetworkTextResultV1:
        deadline = time.monotonic() + float(request.budget.timeout_seconds)
        wire_key = self._key(request)
        decision = self._attempt_store.reserve(wire_key, request.digest)
        if decision.state is NetworkTextAttemptStateV1.COMPLETED:
            assert decision.result is not None
            if (
                decision.result.authority_digest != self._authority.digest
                or decision.result.route_digest != self._route.digest
                or decision.result.adapter_id != self.adapter_id
            ):
                raise NetworkTextDenied("replayed result authority drifted")
            return decision.result
        if decision.state is NetworkTextAttemptStateV1.UNKNOWN:
            return self._result(
                request,
                status="reconciliation_required",
                reason="prior_dispatch_unknown",
            )
        assert decision.lease_id is not None
        return self._invoke_claimed(
            request,
            cancellation,
            wire_key,
            decision.lease_id,
            deadline,
            release_on_not_dispatched=True,
        )

    def _invoke_claimed(
        self,
        request: NetworkTextRequestV1,
        cancellation: NetworkTextCancellationV1,
        wire_key: NetworkTextAttemptKeyV1,
        lease: str,
        deadline: float,
        *,
        release_on_not_dispatched: bool,
    ) -> NetworkTextResultV1:
        try:
            verification = self._dispatch_verification(request)
        except NetworkTextDenied:
            if release_on_not_dispatched:
                self._attempt_store.release_not_dispatched(
                    wire_key, request.digest, lease
                )
            raise
        except NetworkTextContractError as exc:
            if release_on_not_dispatched:
                self._attempt_store.release_not_dispatched(
                    wire_key, request.digest, lease
                )
            raise NetworkTextDenied(
                "dispatch authority unavailable before credential lookup"
            ) from exc
        binding = verification.binding
        credential_resolver = self._resolver
        try:
            credential = self._credential(binding, cancellation, deadline)
        except (NetworkTextCredentialUnavailable, NetworkTextNotDispatched):
            if release_on_not_dispatched:
                self._attempt_store.release_not_dispatched(
                    wire_key, request.digest, lease
                )
            raise
        try:
            response = self._dispatch_reserved(
                request,
                credential,
                cancellation,
                deadline,
                verification,
                credential_resolver,
            )
        except NetworkTextNotDispatched:
            if release_on_not_dispatched:
                self._attempt_store.release_not_dispatched(
                    wire_key, request.digest, lease
                )
            raise
        except NetworkTextPostDispatchDenied:
            result = self._result(
                request,
                status="blocked",
                reason="post_dispatch_denied",
                provider_calls=1,
            )
            self._attempt_store.complete(wire_key, request.digest, lease, result)
            return result
        except NetworkTextDenied:
            if release_on_not_dispatched:
                self._attempt_store.release_not_dispatched(
                    wire_key, request.digest, lease
                )
            raise
        except NetworkTextReconciliationRequired:
            self._attempt_store.mark_unknown(wire_key, request.digest, lease)
            return self._result(
                request,
                status="reconciliation_required",
                reason="dispatch_outcome_unknown",
                provider_calls=1,
            )
        result = self._known_result(request, response)
        self._attempt_store.complete(wire_key, request.digest, lease, result)
        return result

    def invoke(
        self,
        request: NetworkTextRequestV1,
        cancellation: NetworkTextCancellationV1 | None = None,
    ) -> NetworkTextResultV1:
        if type(request) is not NetworkTextRequestV1 or request.stream:
            raise NetworkTextContractError("exact non-stream request required")
        token = NetworkTextCancellationV1() if cancellation is None else cancellation
        if type(token) is not NetworkTextCancellationV1:
            raise NetworkTextContractError("exact cancellation token required")
        preflight = self._preflight_result(request, token)
        if preflight is not None:
            return preflight
        try:
            return self._invoke_once(request, token)
        except NetworkTextNotDispatched:
            return self._result(
                request,
                status="cancelled" if token.cancelled else "unavailable",
                reason=(
                    "cancelled_before_dispatch"
                    if token.cancelled
                    else "safe_not_dispatched"
                ),
            )
        except NetworkTextCredentialUnavailable:
            return self._result(request, status="auth_missing", reason="auth_missing")
        except NetworkTextDenied:
            return self._result(request, status="blocked", reason="request_denied")

    def reconcile(
        self,
        request: NetworkTextRequestV1,
        decision: NetworkTextReconciliationDecisionV1,
        *,
        completed_result: NetworkTextResultV1 | None = None,
    ) -> NetworkTextResultV1 | None:
        if type(request) is not NetworkTextRequestV1:
            raise NetworkTextContractError("exact request required")
        if type(decision) is not NetworkTextReconciliationDecisionV1:
            raise NetworkTextContractError("exact reconciliation decision required")
        key = self._key(request)
        if decision is NetworkTextReconciliationDecisionV1.CONFIRMED_NOT_DISPATCHED:
            if completed_result is not None:
                raise NetworkTextContractError("not-dispatched proof has no result")
            self._attempt_store.reconcile_not_dispatched(key, request.digest)
            return None
        if type(completed_result) is not NetworkTextResultV1:
            raise NetworkTextContractError("completed reconciliation requires result")
        if (
            completed_result.request_id != request.request_id
            or completed_result.request_digest != request.digest
            or completed_result.authority_digest != self._authority.digest
            or completed_result.route_digest != self._route.digest
            or completed_result.adapter_id != self.adapter_id
        ):
            raise NetworkTextDenied("reconciled result authority does not match")
        self._attempt_store.reconcile_completed(
            key, request.digest, completed_result
        )
        return completed_result

    def stream(
        self,
        request: NetworkTextRequestV1,
        cancellation: NetworkTextCancellationV1 | None = None,
    ) -> Iterator[dict[str, object]]:
        if type(request) is not NetworkTextRequestV1 or not request.stream:
            raise NetworkTextContractError("exact stream request required")
        token = NetworkTextCancellationV1() if cancellation is None else cancellation
        if type(token) is not NetworkTextCancellationV1:
            raise NetworkTextContractError("exact cancellation token required")
        return self._stream(request, token, propagate_not_dispatched=False)

    def _stream(
        self,
        request: NetworkTextRequestV1,
        token: NetworkTextCancellationV1,
        *,
        propagate_not_dispatched: bool,
    ) -> Iterator[dict[str, object]]:
        preflight = self._preflight_result(request, token)
        if preflight is not None:
            yield {"type": "done", "result": preflight}
            return
        deadline = time.monotonic() + float(request.budget.timeout_seconds)
        key = self._key(request)
        try:
            decision = self._attempt_store.reserve(key, request.digest)
        except NetworkTextDenied:
            yield {
                "type": "done",
                "result": self._result(
                    request, status="blocked", reason="request_denied"
                ),
            }
            return
        if decision.state is NetworkTextAttemptStateV1.COMPLETED:
            assert decision.result is not None
            if (
                decision.result.authority_digest != self._authority.digest
                or decision.result.route_digest != self._route.digest
                or decision.result.adapter_id != self.adapter_id
            ):
                raise NetworkTextDenied("replayed result authority drifted")
            yield {"type": "done", "result": decision.result}
            return
        if decision.state is NetworkTextAttemptStateV1.UNKNOWN:
            yield {
                "type": "done",
                "result": self._result(
                    request,
                    status="reconciliation_required",
                    reason="prior_dispatch_unknown",
                ),
            }
            return
        assert decision.lease_id is not None
        lease = decision.lease_id
        try:
            verification = self._dispatch_verification(request)
        except (NetworkTextContractError, NetworkTextDenied):
            self._attempt_store.release_not_dispatched(key, request.digest, lease)
            yield {
                "type": "done",
                "result": self._result(
                    request, status="blocked", reason="request_denied"
                ),
            }
            return
        binding = verification.binding
        credential_resolver = self._resolver
        try:
            credential = self._credential(binding, token, deadline)
        except (NetworkTextCredentialUnavailable, NetworkTextNotDispatched) as exc:
            self._attempt_store.release_not_dispatched(key, request.digest, lease)
            if isinstance(exc, NetworkTextCredentialUnavailable):
                yield {
                    "type": "done",
                    "result": self._result(
                        request, status="auth_missing", reason="auth_missing"
                    ),
                }
                return
            if propagate_not_dispatched:
                raise
            yield {
                "type": "done",
                "result": self._result(
                    request,
                    status="cancelled" if token.cancelled else "unavailable",
                    reason=(
                        "cancelled_before_dispatch"
                        if token.cancelled
                        else "safe_not_dispatched"
                    ),
                ),
            }
            return
        try:
            response = self._dispatch_reserved(
                request,
                credential,
                token,
                deadline,
                verification,
                credential_resolver,
            )
        except NetworkTextNotDispatched:
            self._attempt_store.release_not_dispatched(key, request.digest, lease)
            if propagate_not_dispatched:
                raise
            yield {
                "type": "done",
                "result": self._result(
                    request,
                    status="cancelled" if token.cancelled else "unavailable",
                    reason=(
                        "cancelled_before_dispatch"
                        if token.cancelled
                        else "safe_not_dispatched"
                    ),
                ),
            }
            return
        except NetworkTextPostDispatchDenied:
            result = self._result(
                request,
                status="blocked",
                reason="post_dispatch_denied",
                provider_calls=1,
            )
            self._attempt_store.complete(key, request.digest, lease, result)
            yield {"type": "done", "result": result}
            return
        except NetworkTextReconciliationRequired:
            self._attempt_store.mark_unknown(key, request.digest, lease)
            yield {
                "type": "done",
                "result": self._result(
                    request,
                    status="reconciliation_required",
                    reason="dispatch_outcome_unknown",
                    provider_calls=1,
                ),
            }
            return
        if response.status_code != 200 or type(response.body) is bytes:
            result = self._result(
                request,
                status=("rejected" if response.status_code != 200 else "malformed"),
                reason=(
                    "provider_http_rejected"
                    if response.status_code != 200
                    else "stream_body_invalid"
                ),
                provider_calls=1,
            )
            self._attempt_store.complete(key, request.digest, lease, result)
            yield {"type": "done", "result": result}
            return
        content = ""
        emitted = False
        events = 0
        terminal = False
        try:
            for data in _sse_data_frames(
                response.body,
                maximum_bytes=request.budget.maximum_response_bytes,
                cancellation=token,
                remaining=lambda: self._remaining(deadline),
            ):
                if data == b"[DONE]":
                    terminal = True
                    break
                payload = _strict_json(data, request.budget.maximum_response_bytes)
                text = ""
                if self._route.protocol is NetworkTextProtocolV1.ANTHROPIC_MESSAGES:
                    kind = payload.get("type")
                    if kind == "message_stop":
                        terminal = True
                        break
                    if kind == "content_block_delta":
                        delta = payload.get("delta")
                        if (
                            not isinstance(delta, Mapping)
                            or delta.get("type") != "text_delta"
                        ):
                            raise NetworkTextContractError(
                                "Anthropic stream delta is malformed"
                            )
                        text = _text(
                            delta.get("text"),
                            "stream text",
                            MAX_TEXT_BYTES,
                            empty=True,
                        )
                    elif kind in {
                        "message_start",
                        "content_block_start",
                        "content_block_stop",
                        "message_delta",
                        "ping",
                    }:
                        continue
                    else:
                        raise NetworkTextContractError(
                            "Anthropic stream event is unsupported"
                        )
                else:
                    choices = payload.get("choices")
                    if (
                        not isinstance(choices, Sequence)
                        or len(choices) != 1
                        or not isinstance(choices[0], Mapping)
                    ):
                        raise NetworkTextContractError(
                            "OpenAI stream choice is malformed"
                        )
                    choice = choices[0]
                    delta = choice.get("delta")
                    if not isinstance(delta, Mapping):
                        raise NetworkTextContractError(
                            "OpenAI stream delta is malformed"
                        )
                    if delta.get("tool_calls"):
                        raise NetworkTextDenied("stream tool calls are denied")
                    text = delta.get("content") or ""
                    _text(text, "stream text", MAX_TEXT_BYTES, empty=True)
                    if choice.get("finish_reason") is not None:
                        terminal = True
                if text:
                    proposed = content + text
                    if not self._output_within_budget(
                        proposed, (), request.budget
                    ):
                        raise NetworkTextPostDispatchDenied(
                            "local output budget exceeded"
                        )
                    events += 1
                    if events > request.budget.maximum_stream_events:
                        raise NetworkTextPostDispatchDenied(
                            "stream event budget exceeded"
                        )
                    content = proposed
                    emitted = True
                    yield {"type": "text", "text": text}
                if terminal:
                    break
            if not terminal:
                raise NetworkTextReconciliationRequired(
                    "provider outcome requires reconciliation"
                )
        except (NetworkTextReconciliationRequired, TimeoutError):
            self._attempt_store.mark_unknown(key, request.digest, lease)
            result = self._result(
                request,
                status="partial_failure" if emitted else "reconciliation_required",
                reason=(
                    "partial_output_failure"
                    if emitted
                    else "dispatch_outcome_unknown"
                ),
                content=content,
                provider_calls=1,
                output_emitted=emitted,
            )
            yield {"type": "done", "result": result}
            return
        except NetworkTextPostDispatchDenied:
            result = self._result(
                request,
                status="partial_failure" if emitted else "budget_exceeded",
                reason=(
                    "partial_output_failure"
                    if emitted
                    else "response_budget_denied"
                ),
                content=content,
                provider_calls=1,
                output_emitted=emitted,
            )
            self._attempt_store.complete(key, request.digest, lease, result)
            yield {"type": "done", "result": result}
            return
        except (NetworkTextDenied, NetworkTextContractError):
            result = self._result(
                request,
                status="partial_failure" if emitted else "malformed",
                reason=(
                    "partial_output_failure"
                    if emitted
                    else "response_schema_invalid"
                ),
                content=content,
                provider_calls=1,
                output_emitted=emitted,
            )
            self._attempt_store.complete(key, request.digest, lease, result)
            yield {"type": "done", "result": result}
            return
        except Exception:
            self._attempt_store.mark_unknown(key, request.digest, lease)
            result = self._result(
                request,
                status="partial_failure" if emitted else "reconciliation_required",
                reason=(
                    "partial_output_failure"
                    if emitted
                    else "dispatch_outcome_unknown"
                ),
                content=content,
                provider_calls=1,
                output_emitted=emitted,
            )
            yield {"type": "done", "result": result}
            return
        result = self._result(
            request,
            status="completed",
            reason="provider_completed",
            content=content,
            provider_calls=1,
            output_emitted=emitted,
        )
        self._attempt_store.complete(key, request.digest, lease, result)
        yield {"type": "done", "result": result}


class NetworkTextProviderPoolV1:
    __slots__ = ("_clients", "_owner_id", "_store", "_workspace_id")

    def __init__(self, *, clients: tuple[NetworkTextClientV1, ...]) -> None:
        if (
            type(clients) is not tuple
            or not clients
            or any(type(item) is not NetworkTextClientV1 for item in clients)
            or len({item.adapter_id for item in clients}) != len(clients)
        ):
            raise NetworkTextContractError("client pool is invalid")
        first_binding = clients[0]._initial_binding
        store = clients[0]._attempt_store
        for client in clients:
            binding = client._initial_binding
            if (
                binding.owner_id != first_binding.owner_id
                or binding.workspace_id != first_binding.workspace_id
                or client._attempt_store is not store
            ):
                raise NetworkTextDenied(
                    "pool clients must share host scope and durable store"
                )
        self._clients = clients
        self._owner_id = first_binding.owner_id
        self._workspace_id = first_binding.workspace_id
        self._store = store

    def invoke(
        self,
        request: NetworkTextRequestV1,
        cancellation: NetworkTextCancellationV1 | None = None,
    ) -> NetworkTextResultV1:
        if type(request) is not NetworkTextRequestV1 or request.stream:
            raise NetworkTextContractError("exact non-stream request required")
        token = NetworkTextCancellationV1() if cancellation is None else cancellation
        if type(token) is not NetworkTextCancellationV1:
            raise NetworkTextContractError("exact cancellation token required")
        first = self._clients[0]
        key = NetworkTextAttemptKeyV1(
            self._owner_id, self._workspace_id, request.request_id
        )
        try:
            decision = self._store.reserve(key, request.digest)
        except NetworkTextDenied:
            return first._result(
                request, status="blocked", reason="request_denied"
            )
        if decision.state is NetworkTextAttemptStateV1.COMPLETED:
            assert decision.result is not None
            owner = next(
                (
                    client
                    for client in self._clients
                    if client.adapter_id == decision.result.adapter_id
                    and client._route.digest == decision.result.route_digest
                    and client._authority.digest == decision.result.authority_digest
                ),
                None,
            )
            if owner is None:
                return first._result(
                    request, status="blocked", reason="replay_owner_unavailable"
                )
            return decision.result
        if decision.state is NetworkTextAttemptStateV1.UNKNOWN:
            return first._result(
                request,
                status="reconciliation_required",
                reason="prior_dispatch_unknown",
            )
        assert decision.lease_id is not None
        lease = decision.lease_id
        deadline = time.monotonic() + float(request.budget.timeout_seconds)
        for client in self._clients:
            try:
                return client._invoke_claimed(
                    request,
                    token,
                    key,
                    lease,
                    deadline,
                    release_on_not_dispatched=False,
                )
            except NetworkTextNotDispatched:
                if token.cancelled:
                    self._store.release_not_dispatched(key, request.digest, lease)
                    return client._result(
                        request,
                        status="cancelled",
                        reason="cancelled_before_dispatch",
                    )
                continue
            except NetworkTextCredentialUnavailable:
                self._store.release_not_dispatched(key, request.digest, lease)
                return client._result(
                    request, status="auth_missing", reason="auth_missing"
                )
            except NetworkTextDenied:
                self._store.release_not_dispatched(key, request.digest, lease)
                return client._result(
                    request, status="blocked", reason="request_denied"
                )
        self._store.release_not_dispatched(key, request.digest, lease)
        return self._clients[-1]._result(
            request,
            status="unavailable",
            reason="all_routes_not_dispatched",
        )


def create_network_text_client_v1(
    *,
    gate: NetworkTextFeatureGateV1,
    config: NetworkTextConfigV1 | None = None,
    authority: NetworkTextAuthorityV1 | None = None,
    authority_issuer: NetworkTextAuthorityIssuerV1 | None = None,
    account_resolver: NetworkTextAccountResolverV1 | None = None,
    credential_resolver: CredentialResolverV1 | None = None,
    transport: NetworkTextHttpTransportV1 | None = None,
    attempt_store: NetworkTextAttemptStoreV1 | None = None,
) -> NetworkTextClientV1 | None:
    if type(gate) is not NetworkTextFeatureGateV1:
        raise NetworkTextContractError("exact feature gate required")
    if not gate.enabled:
        return None
    if (
        type(config) is not NetworkTextConfigV1
        or type(authority) is not NetworkTextAuthorityV1
        or type(authority_issuer) is not NetworkTextAuthorityIssuerV1
        or account_resolver is None
        or credential_resolver is None
        or transport is None
        or attempt_store is None
    ):
        raise NetworkTextContractError("enabled client requires injected dependencies")
    return NetworkTextClientV1(
        config=config,
        authority=authority,
        authority_issuer=authority_issuer,
        account_resolver=account_resolver,
        credential_resolver=credential_resolver,
        transport=transport,
        attempt_store=attempt_store,
    )


def create_network_text_pool_v1(
    *,
    gate: NetworkTextFeatureGateV1,
    clients: tuple[NetworkTextClientV1, ...] = (),
) -> NetworkTextProviderPoolV1 | None:
    if type(gate) is not NetworkTextFeatureGateV1:
        raise NetworkTextContractError("exact feature gate required")
    if not gate.enabled:
        return None
    return NetworkTextProviderPoolV1(clients=clients)


__all__ = [
    "CredentialResolverV1",
    "FEATURE_FLAG",
    "MAX_RESPONSE_BYTES",
    "NetworkTextAccountResolverV1",
    "NetworkTextAttemptDecisionV1",
    "NetworkTextAttemptKeyV1",
    "NetworkTextAttemptStateV1",
    "NetworkTextAttemptStoreV1",
    "NetworkTextAuthorityIssuerV1",
    "NetworkTextAuthorityV1",
    "NetworkTextBudgetV1",
    "NetworkTextCancellationV1",
    "NetworkTextClientV1",
    "NetworkTextConfigV1",
    "NetworkTextContractError",
    "NetworkTextCredentialUnavailable",
    "NetworkTextDenied",
    "NetworkTextError",
    "NetworkTextFeatureGateV1",
    "NetworkTextHttpRequestV1",
    "NetworkTextHttpResponseV1",
    "NetworkTextHttpTransportV1",
    "NetworkTextMessageV1",
    "NetworkTextNotDispatched",
    "NetworkTextPostDispatchDenied",
    "NetworkTextProtocolV1",
    "NetworkTextProviderPoolV1",
    "NetworkTextProviderV1",
    "NetworkTextReconciliationDecisionV1",
    "NetworkTextReconciliationRequired",
    "NetworkTextRequestV1",
    "NetworkTextResultV1",
    "NetworkTextRouteV1",
    "NetworkTextToolCallV1",
    "NetworkTextToolV1",
    "ROUTES",
    "SqliteNetworkTextAttemptStoreV1",
    "StdlibNetworkTextHttpTransportV1",
    "create_network_text_authority_issuer_v1",
    "create_network_text_client_v1",
    "create_network_text_pool_v1",
]
