"""Gemini Live compatibility Candidate 003: exact host-call parity."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from core.live_model import resolve_live_model

FEATURE_FLAG: Final = "ONYX_PHASE6_GEMINI_LIVE_COMPAT_V1"
API_VERSION: Final = "v1beta"
CANDIDATE: Final = "phase6-gemini-live-compat-candidate-003"
_FACTORY_KEY = object()
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_RESOLVE_LIVE_MODEL = resolve_live_model


class LiveCompatError(RuntimeError):
    pass


class LiveCompatDenied(PermissionError):
    pass


class LiveStatusV1(StrEnum):
    READY = "ready"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    ERROR = "error"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _digest(value: object) -> str:
    return hashlib.sha256(
        value if isinstance(value, bytes) else _canonical(value)
    ).hexdigest()


def _require_digest(value: object, name: str) -> str:
    if type(value) is not str or _HEX.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class LiveConfigAttestationV1:
    model: str
    api_version: str
    response_audio: bool
    input_transcription: bool
    output_transcription: bool
    session_resumption: bool
    voice_name: str
    tools_digest: str
    redacted_digest: str
    system_instruction_present: bool

    def __post_init__(self) -> None:
        if type(self.model) is not str or not self.model:
            raise ValueError("model is required")
        if self.api_version != API_VERSION:
            raise ValueError("exact v1beta API version is required")
        for name in (
            "response_audio",
            "input_transcription",
            "output_transcription",
            "session_resumption",
            "system_instruction_present",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be an exact boolean")
        if type(self.voice_name) is not str or not self.voice_name:
            raise ValueError("voice_name is required")
        _require_digest(self.tools_digest, "tools_digest")
        _require_digest(self.redacted_digest, "redacted_digest")


@dataclass(frozen=True, slots=True)
class EventMetadataV1:
    index: int
    audio_bytes: int
    has_server_content: bool
    has_tool_call: bool

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index < 0:
            raise ValueError("event index is invalid")
        if type(self.audio_bytes) is not int or self.audio_bytes < 0:
            raise ValueError("audio length is invalid")
        if (
            type(self.has_server_content) is not bool
            or type(self.has_tool_call) is not bool
        ):
            raise ValueError("event flags must be exact booleans")

    @property
    def digest(self) -> str:
        return _digest(
            {
                "schema": "OnyxGeminiLiveEventMetadata.v1",
                "index": self.index,
                "audio_bytes": self.audio_bytes,
                "has_server_content": self.has_server_content,
                "has_tool_call": self.has_tool_call,
            }
        )


@dataclass(frozen=True, slots=True)
class LiveReceiptV1:
    status: LiveStatusV1
    request_digest: str
    event_digests: tuple[str, ...]
    elapsed_ms: int
    api_version: str = API_VERSION
    error_type: str | None = None

    def __post_init__(self) -> None:
        if type(self.status) is not LiveStatusV1:
            raise ValueError("exact LiveStatusV1 is required")
        _require_digest(self.request_digest, "request_digest")
        if type(self.event_digests) is not tuple:
            raise ValueError("event_digests must be a tuple")
        for value in self.event_digests:
            _require_digest(value, "event_digest")
        if type(self.elapsed_ms) is not int or self.elapsed_ms < 0:
            raise ValueError("elapsed_ms is invalid")
        if self.api_version != API_VERSION:
            raise ValueError("receipt API version is invalid")
        if self.error_type is not None and type(self.error_type) is not str:
            raise ValueError("error_type is invalid")


@dataclass(frozen=True, slots=True)
class LiveConnectResultV1:
    status: LiveStatusV1
    session: "GeminiLiveSessionV1 | None"
    receipt: LiveReceiptV1

    def __post_init__(self) -> None:
        if type(self.status) is not LiveStatusV1:
            raise ValueError("connect status is invalid")
        if self.status is LiveStatusV1.READY:
            if type(self.session) is not GeminiLiveSessionV1:
                raise ValueError("READY requires an exact session")
        elif self.session is not None:
            raise ValueError("non-READY connect result cannot expose a session")
        if type(self.receipt) is not LiveReceiptV1:
            raise ValueError("exact connect receipt is required")


def _attr(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def attest_live_config(config: object, model: str) -> LiveConfigAttestationV1:
    """Project only non-secret config shape; never retain or hash instruction text."""
    modalities = _attr(config, "response_modalities", ())
    speech = _attr(config, "speech_config")
    voice_config = _attr(speech, "voice_config")
    prebuilt = _attr(voice_config, "prebuilt_voice_config")
    voice = _attr(prebuilt, "voice_name", "")
    tools = _attr(config, "tools", ())
    redacted = {
        "schema": "OnyxGeminiLiveConfigAttestation.v1",
        "model": model,
        "api_version": API_VERSION,
        "response_audio": "AUDIO" in tuple(modalities or ()),
        "input_transcription": _attr(config, "input_audio_transcription") is not None,
        "output_transcription": _attr(config, "output_audio_transcription") is not None,
        "session_resumption": _attr(config, "session_resumption") is not None,
        "voice_name": str(voice),
        "tools_digest": _digest(tools),
        "system_instruction_present": bool(_attr(config, "system_instruction")),
    }
    return LiveConfigAttestationV1(
        model=model,
        api_version=API_VERSION,
        response_audio=redacted["response_audio"],
        input_transcription=redacted["input_transcription"],
        output_transcription=redacted["output_transcription"],
        session_resumption=redacted["session_resumption"],
        voice_name=redacted["voice_name"],
        tools_digest=redacted["tools_digest"],
        redacted_digest=_digest(redacted),
        system_instruction_present=redacted["system_instruction_present"],
    )


def _event_metadata(event: object, index: int) -> EventMetadataV1:
    data = _attr(event, "data")
    return EventMetadataV1(
        index=index,
        audio_bytes=len(data) if isinstance(data, bytes) else 0,
        has_server_content=_attr(event, "server_content") is not None,
        has_tool_call=_attr(event, "tool_call") is not None,
    )


class GeminiLiveSessionV1:
    def __init__(self, *, key: object, handle: object, session: object) -> None:
        if key is not _FACTORY_KEY:
            raise LiveCompatDenied("session construction is factory-only")
        self._handle = handle
        self._session = session
        self._closed = False

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            await self._handle.__aexit__(None, None, None)

    async def send_realtime_input(self, *, media: object) -> None:
        await self._session.send_realtime_input(media=media)

    async def send_client_content(
        self, turns: object, *, turn_complete: bool = True
    ) -> None:
        if type(turn_complete) is not bool:
            raise ValueError("turn_complete must be an exact boolean")
        await self._session.send_client_content(
            turns=turns, turn_complete=turn_complete
        )

    async def send_tool_response(self, function_responses: Sequence[object]) -> None:
        await self._session.send_tool_response(function_responses=function_responses)

    async def receive(
        self,
        *,
        request_digest: str,
        timeout_ms: int,
        max_events: int,
        cancel: asyncio.Event | None = None,
    ) -> LiveReceiptV1:
        _require_digest(request_digest, "request_digest")
        if type(timeout_ms) is not int or not 1 <= timeout_ms <= 120_000:
            raise ValueError("timeout_ms is outside policy")
        if type(max_events) is not int or not 1 <= max_events <= 1024:
            raise ValueError("max_events is outside policy")
        started = time.monotonic()
        digests: list[str] = []

        def receipt(
            status: LiveStatusV1, error: BaseException | None = None
        ) -> LiveReceiptV1:
            return LiveReceiptV1(
                status=status,
                request_digest=request_digest,
                event_digests=tuple(digests),
                elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
                error_type=type(error).__name__ if error else None,
            )

        if cancel is not None and cancel.is_set():
            return receipt(LiveStatusV1.CANCELLED)

        async def collect() -> LiveReceiptV1:
            try:
                async for event in self._session.receive():
                    if cancel is not None and cancel.is_set():
                        return receipt(LiveStatusV1.CANCELLED)
                    if len(digests) >= max_events:
                        raise LiveCompatError("event budget exhausted")
                    digests.append(_event_metadata(event, len(digests)).digest)
                return receipt(LiveStatusV1.COMPLETED)
            except Exception as exc:
                return receipt(LiveStatusV1.ERROR, exc)

        task = asyncio.create_task(collect())
        cancel_task = asyncio.create_task(cancel.wait()) if cancel is not None else None
        waiters = {task, *(() if cancel_task is None else (cancel_task,))}
        done, _ = await asyncio.wait(
            waiters, timeout=timeout_ms / 1000, return_when=asyncio.FIRST_COMPLETED
        )
        if task in done:
            if cancel_task:
                cancel_task.cancel()
            return task.result()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if cancel_task is not None and cancel_task in done:
            return receipt(LiveStatusV1.CANCELLED)
        if cancel_task:
            cancel_task.cancel()
        return receipt(LiveStatusV1.TIMEOUT, TimeoutError())


class GeminiLiveCompatV1:
    def __init__(
        self,
        *,
        key: object,
        client: object,
        model: str,
        config: object,
        attestation: LiveConfigAttestationV1,
    ) -> None:
        if key is not _FACTORY_KEY:
            raise LiveCompatDenied("adapter construction is factory-only")
        if config is None or client is None:
            raise LiveCompatDenied("exact client and host config are required")
        if type(attestation) is not LiveConfigAttestationV1:
            raise ValueError("exact config attestation is required")
        self._client = client
        self.model = model
        self.config = config
        self.attestation = attestation

    async def connect(self) -> LiveConnectResultV1:
        started = time.monotonic()
        request_digest = _digest(
            {
                "schema": "OnyxGeminiLiveConnect.v1",
                "model": self.model,
                "attestation": self.attestation.redacted_digest,
            }
        )
        try:
            handle = self._client.aio.live.connect(model=self.model, config=self.config)
            session = await handle.__aenter__()
        except Exception as exc:
            return LiveConnectResultV1(
                LiveStatusV1.UNAVAILABLE,
                None,
                LiveReceiptV1(
                    LiveStatusV1.UNAVAILABLE,
                    request_digest,
                    (),
                    max(0, int((time.monotonic() - started) * 1000)),
                    error_type=type(exc).__name__,
                ),
            )
        wrapped = GeminiLiveSessionV1(key=_FACTORY_KEY, handle=handle, session=session)
        return LiveConnectResultV1(
            LiveStatusV1.READY,
            wrapped,
            LiveReceiptV1(
                LiveStatusV1.READY,
                request_digest,
                (),
                max(0, int((time.monotonic() - started) * 1000)),
            ),
        )


def create_gemini_live_compat_v1(
    client: object,
    host_config: object,
    *,
    environ: Mapping[str, str] | None = None,
    model_config: Mapping[str, object] | None = None,
) -> GeminiLiveCompatV1:
    source = os.environ if environ is None else environ
    if source.get(FEATURE_FLAG) != "1":
        raise LiveCompatDenied("Gemini Live compatibility is disabled")
    model = _RESOLVE_LIVE_MODEL(environ=source, config=model_config or {})
    attestation = attest_live_config(host_config, model)
    return GeminiLiveCompatV1(
        key=_FACTORY_KEY,
        client=client,
        model=model,
        config=host_config,
        attestation=attestation,
    )


__all__ = [
    "API_VERSION",
    "CANDIDATE",
    "FEATURE_FLAG",
    "EventMetadataV1",
    "GeminiLiveCompatV1",
    "GeminiLiveSessionV1",
    "LiveCompatDenied",
    "LiveCompatError",
    "LiveConfigAttestationV1",
    "LiveConnectResultV1",
    "LiveReceiptV1",
    "LiveStatusV1",
    "attest_live_config",
    "create_gemini_live_compat_v1",
]
