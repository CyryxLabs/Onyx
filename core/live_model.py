"""Single source of truth for the Gemini Live model used by Onyx."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping as MappingABC
from pathlib import Path
from typing import Any, Mapping

from core.audio_contract import ORIGINAL_LIVE_MODEL, VoiceContractError


# Voice identity includes both the prebuilt voice and the native-audio model.
# Gemini 3.1 changed the acoustic rendering even when the voice name remained
# ``Charon``.  Keep Onyx on the original accepted model and fail closed if an
# environment/config override attempts to select a different voice model.
DEFAULT_LIVE_MODEL = ORIGINAL_LIVE_MODEL
LIVE_MODEL_ENV = "ONYX_LIVE_MODEL"
MODEL_RE = re.compile(r"^(?:models/)?[a-z0-9][a-z0-9._-]{2,127}$")


def _media_mime_type(media: object) -> str:
    if isinstance(media, MappingABC):
        value = media.get("mime_type", media.get("mimeType", ""))
    else:
        value = getattr(media, "mime_type", "")
    return value.strip().casefold() if isinstance(value, str) else ""


def _live_input_kwargs(
    *,
    media: object | None = None,
    audio: object | None = None,
    audio_stream_end: bool | None = None,
    video: object | None = None,
    text: str | None = None,
    activity_start: object | None = None,
    activity_end: object | None = None,
) -> dict[str, object]:
    """Translate only legacy audio media to the current Live API keyword."""

    if audio is None and media is not None and _media_mime_type(media).startswith(
        "audio/"
    ):
        audio, media = media, None
    values = {
        "media": media,
        "audio": audio,
        "audio_stream_end": audio_stream_end,
        "video": video,
        "text": text,
        "activity_start": activity_start,
        "activity_end": activity_end,
    }
    return {name: value for name, value in values.items() if value is not None}


class LiveAudioTransportAdapter:
    """Session-local compatibility adapter for legacy Onyx audio calls.

    The Google SDK class is deliberately never modified.  Each connected
    session is wrapped for its own lifetime, translating only audio passed via
    the historical ``media=`` keyword to the current ``audio=`` keyword.
    Everything else is delegated to the real SDK session unchanged.
    """

    __slots__ = ("_session",)

    def __init__(self, session: object) -> None:
        sender = getattr(session, "send_realtime_input", None)
        if not callable(sender):
            raise TypeError("Gemini Live session must provide send_realtime_input")
        self._session = session

    @property
    def raw_session(self) -> object:
        """Return the unmodified provider session for lifecycle/readback checks."""

        return self._session

    async def send_realtime_input(
        self,
        *,
        media: object | None = None,
        audio: object | None = None,
        audio_stream_end: bool | None = None,
        video: object | None = None,
        text: str | None = None,
        activity_start: object | None = None,
        activity_end: object | None = None,
    ) -> Any:
        kwargs = _live_input_kwargs(
            media=media,
            audio=audio,
            audio_stream_end=audio_stream_end,
            video=video,
            text=text,
            activity_start=activity_start,
            activity_end=activity_end,
        )
        return await self._session.send_realtime_input(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._session, name)


def adapt_live_audio_transport(session: object) -> LiveAudioTransportAdapter:
    """Return an idempotent session-local audio transport adapter."""

    if isinstance(session, LiveAudioTransportAdapter):
        return session
    return LiveAudioTransportAdapter(session)


def unwrap_live_audio_transport(session: object) -> object:
    """Rollback/read back a session adapter without touching provider state."""

    if isinstance(session, LiveAudioTransportAdapter):
        return session.raw_session
    return session


def install_live_audio_transport_compat(
    session: object,
) -> LiveAudioTransportAdapter:
    """Compatibility alias for the former global installer.

    This function now installs compatibility only on the supplied session by
    returning its adapter.  It never mutates the session class or Google SDK.
    """

    return adapt_live_audio_transport(session)


def resolve_live_model(
    config_path: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    config: Mapping[str, object] | None = None,
) -> str:
    """Resolve and validate the runtime model.

    Precedence is ``ONYX_LIVE_MODEL``, then the historical migration alias,
    then an intentional ``live_model``
    config entry, then :data:`DEFAULT_LIVE_MODEL`.  Supplying ``config`` avoids
    filesystem access; an absent config file is treated like an empty config.
    """
    environment = os.environ if environ is None else environ
    candidate = environment.get(LIVE_MODEL_ENV)
    if candidate is None:
        loaded = config
        if loaded is None and config_path is not None:
            try:
                value = json.loads(Path(config_path).read_text(encoding="utf-8"))
                loaded = value if isinstance(value, dict) else {}
            except FileNotFoundError:
                loaded = {}
        if loaded is not None:
            configured = loaded.get("live_model")
            candidate = configured if isinstance(configured, str) else None
    model = (candidate or DEFAULT_LIVE_MODEL).strip()
    if not MODEL_RE.fullmatch(model):
        raise ValueError("Configured Gemini Live model name is malformed")
    if model != ORIGINAL_LIVE_MODEL:
        raise VoiceContractError(
            "Onyx original voice requires "
            f"{ORIGINAL_LIVE_MODEL}; alternate Gemini/system voice models are disabled"
        )
    return model
