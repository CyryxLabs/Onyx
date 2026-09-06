"""Shared production audio contract for Onyx Live sessions.

Onyx has exactly one production speech source: audio returned by Gemini Live
using the original ``Charon`` voice.  Local/system TTS is intentionally not a
fallback.  If this contract cannot be satisfied, the voice channel must remain
silent and surface its degraded state instead of synthesising another voice.
"""

from __future__ import annotations

CHANNELS = 1
SEND_SAMPLE_RATE = 16_000
RECEIVE_SAMPLE_RATE = 24_000
CHUNK_SIZE = 1_024
PCM_BYTES_PER_FRAME = 2
PCM_CHUNK_BYTES = CHUNK_SIZE * PCM_BYTES_PER_FRAME
LIVE_VOICE = "Charon"
SUPPORTED_LIVE_VOICES = ("Charon", "Puck", "Kore", "Fenrir", "Aoede")
VOICE_PROVIDER = "gemini-live"
ORIGINAL_LIVE_MODEL = "models/gemini-2.5-flash-native-audio-preview-12-2025"
# Gemini documents the session-resumption handle as an opaque string but does
# not publish a client-side size limit.  Bound it defensively so an untrusted
# provider payload cannot become unbounded retained process state.  The value
# is measured as UTF-8 bytes (not Python code points) and is never coerced.
MAX_LIVE_SESSION_RESUME_HANDLE_BYTES = 4_096
ORIGINAL_VOICE_STYLE_INSTRUCTION = (
    "[VOICE IDENTITY - IMMUTABLE]\n"
    "Speak with Onyx's natural native-audio voice: warm, composed, human, and "
    "expressive, with subtle cadence and breathing room. Avoid robotic, synthetic, "
    "announcer-like, or operating-system text-to-speech delivery. Match the user's "
    "language naturally while preserving the same voice identity."
)
VOICE_ACCEPTANCE_CAPTURE_SECONDS = 6
MAX_VOICE_ACCEPTANCE_MIC_BYTES = (
    SEND_SAMPLE_RATE * PCM_BYTES_PER_FRAME * VOICE_ACCEPTANCE_CAPTURE_SECONDS
)


class VoiceContractError(RuntimeError):
    """Raised when a live session would violate the original-voice contract."""


class LiveSessionRotation(RuntimeError):
    """Raised when Gemini asks the client to rotate a Live WebSocket cleanly."""


class InvalidLiveSessionResumeHandle(RuntimeError):
    """Raised when a provider supplies an unsafe session-resumption handle."""


def validate_live_session_resume_handle(value: object) -> str:
    """Return a valid opaque Gemini resume handle without coercing *value*.

    Handles must be non-empty strings no larger than
    :data:`MAX_LIVE_SESSION_RESUME_HANDLE_BYTES` when encoded as UTF-8.  Leading
    or trailing whitespace is preserved because the handle is provider-owned;
    whitespace is used only to reject an effectively empty value.
    """

    # Require a plain provider-decoded string.  A subclass can override
    # ``strip``/``encode`` and is not an acceptable opaque wire value.
    if type(value) is not str:
        raise InvalidLiveSessionResumeHandle(
            "Gemini session-resumption handle must be a string"
        )
    if not value.strip():
        raise InvalidLiveSessionResumeHandle(
            "Gemini session-resumption handle must not be empty"
        )
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InvalidLiveSessionResumeHandle(
            "Gemini session-resumption handle must be valid UTF-8"
        ) from exc
    if len(encoded) > MAX_LIVE_SESSION_RESUME_HANDLE_BYTES:
        raise InvalidLiveSessionResumeHandle(
            "Gemini session-resumption handle exceeds the 4096-byte safety limit"
        )
    return value


def validate_optional_live_session_resume_handle(value: object) -> str | None:
    """Validate a retained handle while accepting ``None`` for a fresh session."""

    if value is None:
        return None
    return validate_live_session_resume_handle(value)


def assert_original_live_voice(config: object) -> None:
    """Fail closed unless *config* requests only Gemini Live's original voice.

    This check deliberately accepts no local, operating-system, Edge, Kokoro,
    ElevenLabs, or text-only substitute.  It is kept dependency-free so every
    live activation layer can enforce the same invariant before connecting.
    """

    modalities = getattr(config, "response_modalities", None)
    if list(modalities or ()) != ["AUDIO"]:
        raise VoiceContractError("Gemini Live AUDIO must be the only response modality")

    speech = getattr(config, "speech_config", None)
    voice_config = getattr(speech, "voice_config", None)
    prebuilt = getattr(voice_config, "prebuilt_voice_config", None)
    voice_name = getattr(prebuilt, "voice_name", None)
    if voice_name != LIVE_VOICE:
        raise VoiceContractError(
            f"Onyx original voice must be {LIVE_VOICE}; local/system TTS is disabled"
        )


def assert_selected_live_voice(config: object, expected_voice: str) -> None:
    """Fail closed unless Gemini Native Audio uses an owner-supported voice."""

    if expected_voice not in SUPPORTED_LIVE_VOICES:
        raise VoiceContractError("unsupported Gemini Live voice")
    modalities = getattr(config, "response_modalities", None)
    if list(modalities or ()) != ["AUDIO"]:
        raise VoiceContractError("Gemini Live AUDIO must be the only response modality")
    speech = getattr(config, "speech_config", None)
    voice_config = getattr(speech, "voice_config", None)
    prebuilt = getattr(voice_config, "prebuilt_voice_config", None)
    if getattr(prebuilt, "voice_name", None) != expected_voice:
        raise VoiceContractError("Gemini Live voice selection drifted")
