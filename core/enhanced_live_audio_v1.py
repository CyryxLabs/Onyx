"""Default-off Gemini Live affective/proactive audio configuration contract."""

from __future__ import annotations

import json
import builtins
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final


SCHEMA: Final = "OnyxEnhancedLiveAudioStatus.v1"
MAX_CUES: Final = 4
MAX_CUE_LENGTH: Final = 80
_SAFE_AFFECTS: Final = frozenset(
    {"calm", "concerned", "frustrated", "positive", "sad", "uncertain"}
)


class EnhancedAudioStateV1(StrEnum):
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"
    APPROVED = "approved"


class EnhancedAudioModeV1(StrEnum):
    ENHANCED = "enhanced"
    EXISTING_AUDIO = "existing_audio"
    NO_AUDIO = "no_audio"


@dataclass(frozen=True, slots=True)
class EnhancedAudioRequestV1:
    enabled: bool = False
    affective_dialog: bool = False
    proactive_audio: bool = False
    fallback_to_existing_audio: bool = True

    def __post_init__(self) -> None:
        for field_name in (
            "enabled",
            "affective_dialog",
            "proactive_audio",
            "fallback_to_existing_audio",
        ):
            if type(getattr(self, field_name)) is not bool:
                raise TypeError(f"{field_name} must be an exact boolean")


@dataclass(frozen=True, slots=True)
class EnhancedAudioCompatibilityV1:
    affective_dialog: bool
    proactive_audio: bool


@dataclass(frozen=True, slots=True)
class EnhancedAudioStatusV1:
    state: EnhancedAudioStateV1
    selected_mode: EnhancedAudioModeV1
    reason: str
    affective_dialog: bool
    proactive_audio: bool
    fallback_attempted: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return the pure, JSON-safe status contract used by CLI callers."""
        payload = asdict(self)
        payload.update(schema=SCHEMA, authority_impact=False)
        payload["state"] = self.state.value
        payload["selected_mode"] = self.selected_mode.value
        return payload


def request_from_mapping(value: Mapping[str, object] | None) -> EnhancedAudioRequestV1:
    """Parse explicit opt-ins; non-boolean or absent values remain safely off."""
    source = value if isinstance(value, Mapping) else {}
    return EnhancedAudioRequestV1(
        enabled=source.get("enhanced_live_audio_enabled") is True,
        affective_dialog=source.get("affective_dialog_enabled") is True,
        proactive_audio=source.get("enhanced_proactive_audio_enabled") is True,
        fallback_to_existing_audio=source.get("enhanced_audio_fallback_enabled")
        is True,
    )


def request_from_file(path: Path) -> EnhancedAudioRequestV1:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        value = None
    return request_from_mapping(value if isinstance(value, Mapping) else None)


def detect_compatibility(types_module: object) -> EnhancedAudioCompatibilityV1:
    """Inspect the installed SDK without constructing or contacting a provider."""
    config_type = getattr(types_module, "LiveConnectConfig", None)
    config_fields = getattr(config_type, "model_fields", {})
    proactivity_type = getattr(types_module, "ProactivityConfig", None)
    proactive_fields = getattr(proactivity_type, "model_fields", {})
    return EnhancedAudioCompatibilityV1(
        affective_dialog="enable_affective_dialog" in config_fields,
        proactive_audio=(
            "proactivity" in config_fields and "proactive_audio" in proactive_fields
        ),
    )


def resolve_status(
    request: EnhancedAudioRequestV1,
    compatibility: EnhancedAudioCompatibilityV1,
    *,
    failure: str | None = None,
    fallback_attempted: bool = False,
) -> EnhancedAudioStatusV1:
    """Resolve one mode once; a failed fallback can never recurse into another."""
    requested_features = request.affective_dialog or request.proactive_audio
    supported = (not request.affective_dialog or compatibility.affective_dialog) and (
        not request.proactive_audio or compatibility.proactive_audio
    )
    if not request.enabled or not requested_features:
        return EnhancedAudioStatusV1(
            EnhancedAudioStateV1.DISABLED,
            EnhancedAudioModeV1.EXISTING_AUDIO,
            "explicit_opt_in_required",
            False,
            False,
        )
    if failure is None and supported:
        return EnhancedAudioStatusV1(
            EnhancedAudioStateV1.APPROVED,
            EnhancedAudioModeV1.ENHANCED,
            "supported_opt_in",
            request.affective_dialog,
            request.proactive_audio,
        )
    reason = failure or "provider_sdk_unsupported"
    can_fallback = request.fallback_to_existing_audio and not fallback_attempted
    return EnhancedAudioStatusV1(
        EnhancedAudioStateV1.DEGRADED
        if can_fallback
        else EnhancedAudioStateV1.UNAVAILABLE,
        EnhancedAudioModeV1.EXISTING_AUDIO
        if can_fallback
        else EnhancedAudioModeV1.NO_AUDIO,
        reason,
        False,
        False,
        fallback_attempted=can_fallback or fallback_attempted,
    )


def apply_live_config(
    base: Mapping[str, object],
    request: EnhancedAudioRequestV1,
    types_module: object,
    *,
    fallback_retained: bool = False,
) -> tuple[dict[str, object], EnhancedAudioStatusV1]:
    """Add supported provider fields only; never changes tools or authority inputs."""
    compatibility = detect_compatibility(types_module)
    status = (
        resolve_status(
            request,
            compatibility,
            failure="provider_config_rejected",
        )
        if fallback_retained and request.enabled
        else resolve_status(request, compatibility)
    )
    result = dict(base)
    if status.selected_mode is EnhancedAudioModeV1.ENHANCED:
        if status.affective_dialog:
            result["enable_affective_dialog"] = True
        if status.proactive_audio:
            result["proactivity"] = types_module.ProactivityConfig(proactive_audio=True)
    return result, status


def is_enhanced_config_rejection(error: BaseException) -> bool:
    """Classify provider setup rejection without treating transport faults as one."""
    if isinstance(error, builtins.BaseExceptionGroup):
        leaves = tuple(error.exceptions)
        return bool(leaves) and all(is_enhanced_config_rejection(item) for item in leaves)

    text = f"{type(error).__name__}: {error}".casefold()
    transport_markers = (
        "timeout",
        "timed out",
        "getaddrinfo",
        "connection refused",
        "cannot connect",
        "network",
        "dns",
        "cancelled",
        "canceled",
        "api key not valid",
        "unauthenticated",
        "permission denied",
    )
    if any(marker in text for marker in transport_markers):
        return False

    code = getattr(error, "code", None)
    status_code = getattr(error, "status_code", None)
    invalid_argument = (
        code in {400, 1007, "INVALID_ARGUMENT"}
        or status_code == 400
        or "invalid argument" in text
    )
    explicit_config_rejection = any(
        marker in text
        for marker in (
            "unsupported field",
            "unknown field",
            "unexpected keyword",
            "extra inputs are not permitted",
            "enable_affective_dialog",
            "proactive_audio",
            "proactivity",
        )
    )
    return invalid_argument or explicit_config_rejection


def bounded_affective_context(
    affect: str | None, cues: Sequence[str]
) -> dict[str, object]:
    """Normalize advisory session context; it is data and carries no authority."""
    safe_affect = affect if affect in _SAFE_AFFECTS else "uncertain"
    safe_cues = tuple(
        cue.strip()[:MAX_CUE_LENGTH]
        for cue in cues[:MAX_CUES]
        if type(cue) is str and cue.strip()
    )
    return {
        "affect": safe_affect,
        "proactive_cues": safe_cues,
        "authority_impact": False,
        "tools_allowed": False,
    }
