from pathlib import Path
from types import SimpleNamespace

import pytest

from core.enhanced_live_audio_v1 import (
    EnhancedAudioCompatibilityV1,
    EnhancedAudioModeV1,
    EnhancedAudioRequestV1,
    EnhancedAudioStateV1,
    apply_live_config,
    bounded_affective_context,
    is_enhanced_config_rejection,
    request_from_file,
    request_from_mapping,
    resolve_status,
)


class _Config:
    model_fields = {"enable_affective_dialog": object(), "proactivity": object()}


class _Proactivity:
    model_fields = {"proactive_audio": object()}

    def __init__(self, proactive_audio: bool):
        self.proactive_audio = proactive_audio


TYPES = SimpleNamespace(LiveConnectConfig=_Config, ProactivityConfig=_Proactivity)
SUPPORTED = EnhancedAudioCompatibilityV1(True, True)


def test_disabled_is_explicit_and_preserves_existing_config() -> None:
    base = {"response_modalities": ["AUDIO"], "tools": ["host-owned"]}
    config, status = apply_live_config(base, EnhancedAudioRequestV1(), TYPES)

    assert config == base
    assert status.state is EnhancedAudioStateV1.DISABLED
    assert status.selected_mode is EnhancedAudioModeV1.EXISTING_AUDIO
    assert status.to_dict()["authority_impact"] is False


def test_supported_opt_in_adds_only_requested_provider_fields() -> None:
    request = EnhancedAudioRequestV1(True, True, True, True)
    base = {"tools": ["unchanged"]}
    config, status = apply_live_config(base, request, TYPES)

    assert status.state is EnhancedAudioStateV1.APPROVED
    assert config["enable_affective_dialog"] is True
    assert config["proactivity"].proactive_audio is True
    assert config["tools"] == ["unchanged"]


def test_retained_fallback_removes_enhanced_fields_for_runtime_lifetime() -> None:
    request = EnhancedAudioRequestV1(True, True, True, True)
    base = {"response_modalities": ["AUDIO"], "tools": ["host-owned"]}

    config, status = apply_live_config(
        base, request, TYPES, fallback_retained=True
    )

    assert config == base
    assert status.state is EnhancedAudioStateV1.DEGRADED
    assert status.selected_mode is EnhancedAudioModeV1.EXISTING_AUDIO
    assert status.reason == "provider_config_rejected"
    assert status.fallback_attempted is True


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("1007 Request contains an invalid argument"),
        ValueError("unknown field enable_affective_dialog"),
    ],
)
def test_provider_setup_rejection_classifier_is_explicit(error: BaseException) -> None:
    assert is_enhanced_config_rejection(error) is True


@pytest.mark.parametrize(
    "error",
    [TimeoutError("timed out"), OSError("Cannot connect"), RuntimeError("1011 unavailable")],
)
def test_network_and_unclassified_failures_do_not_downgrade(
    error: BaseException,
) -> None:
    assert is_enhanced_config_rejection(error) is False


def test_auth_rejection_does_not_masquerade_as_enhanced_config_rejection() -> None:
    assert is_enhanced_config_rejection(
        RuntimeError("1007 API key not valid")
    ) is False


def test_unsupported_sdk_truthfully_falls_back_once() -> None:
    request = EnhancedAudioRequestV1(True, True, True, True)
    first = resolve_status(request, EnhancedAudioCompatibilityV1(False, False))
    second = resolve_status(
        request,
        EnhancedAudioCompatibilityV1(False, False),
        failure="fallback_failed",
        fallback_attempted=first.fallback_attempted,
    )

    assert (first.state, first.selected_mode, first.fallback_attempted) == (
        EnhancedAudioStateV1.DEGRADED,
        EnhancedAudioModeV1.EXISTING_AUDIO,
        True,
    )
    assert (second.state, second.selected_mode, second.fallback_attempted) == (
        EnhancedAudioStateV1.UNAVAILABLE,
        EnhancedAudioModeV1.NO_AUDIO,
        True,
    )


@pytest.mark.parametrize(
    "failure", ["pre_session_failure", "mid_session_failure", "cancelled"]
)
def test_runtime_failures_have_truthful_bounded_fallback(failure: str) -> None:
    status = resolve_status(
        EnhancedAudioRequestV1(True, True, False, True),
        SUPPORTED,
        failure=failure,
    )
    assert status.state is EnhancedAudioStateV1.DEGRADED
    assert status.reason == failure
    assert status.affective_dialog is False
    assert status.proactive_audio is False


def test_fallback_can_be_explicitly_disabled() -> None:
    status = resolve_status(
        EnhancedAudioRequestV1(True, True, False, False),
        EnhancedAudioCompatibilityV1(False, False),
    )
    assert status.state is EnhancedAudioStateV1.UNAVAILABLE
    assert status.selected_mode is EnhancedAudioModeV1.NO_AUDIO


def test_config_requires_exact_boolean_opt_ins(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        '{"enhanced_live_audio_enabled": true, "affective_dialog_enabled": '
        'true, "enhanced_proactive_audio_enabled": "true", '
        '"enhanced_audio_fallback_enabled": true}',
        encoding="utf-8",
    )
    request = request_from_file(path)
    assert request == EnhancedAudioRequestV1(True, True, False, True)
    assert request_from_mapping({"enhanced_live_audio_enabled": 1}).enabled is False


def test_affective_context_is_bounded_advisory_data() -> None:
    context = bounded_affective_context(
        "angry",
        [" cue ", "x" * 200, "", "third", "ignored fifth"],
    )
    assert context == {
        "affect": "uncertain",
        "proactive_cues": ("cue", "x" * 80, "third"),
        "authority_impact": False,
        "tools_allowed": False,
    }
