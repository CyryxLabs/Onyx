from __future__ import annotations

import json

import pytest
from types import SimpleNamespace
from unittest.mock import Mock

import main

from core.assistant_identity_profile_v1 import (
    AssistantIdentityProfileError,
    AssistantIdentityProfileV1,
    parse_assistant_alias_intent_v1,
)


def test_alias_never_changes_immutable_product_or_vendor(tmp_path):
    profile = AssistantIdentityProfileV1(tmp_path / "identity.json")
    state = profile.set_alias("Atlas")
    assert state.product_name == "Onyx"
    assert state.vendor_name == "Cyryx Labs"
    assert state.call_alias == "Atlas"
    assert "product is Onyx by Cyryx Labs" in profile.prompt_instruction()
    assert "conversational call alias" in profile.prompt_instruction()


def test_reserved_identity_and_malformed_persisted_identity_fail_closed(tmp_path):
    path = tmp_path / "identity.json"
    profile = AssistantIdentityProfileV1(path)
    with pytest.raises(AssistantIdentityProfileError):
        profile.set_alias("Onyx")
    path.write_text(json.dumps({
        "schema": "onyx.assistant-identity-profile/v1",
        "product_name": "Other",
        "vendor_name": "Cyryx Labs",
        "call_alias": None,
        "updated_at_ns": 1,
    }), encoding="utf-8")
    with pytest.raises(AssistantIdentityProfileError, match="identity drifted"):
        profile.status()


def test_alias_commands_are_bounded_and_clearable(tmp_path):
    profile = AssistantIdentityProfileV1(tmp_path / "identity.json")
    intent = profile.apply_command("Onyx, call yourself Atlas")
    assert intent.alias == "Atlas"
    assert profile.status().call_alias == "Atlas"
    clear = profile.apply_command("use Onyx again")
    assert clear.clear is True
    assert profile.status().call_alias is None
    assert parse_assistant_alias_intent_v1("open the calendar").matched is False


def test_main_host_observes_language_and_alias_without_ui_layout_change(tmp_path):
    host = SimpleNamespace(
        _spoken_language_memory_v1=__import__(
            "core.spoken_language_memory_v1", fromlist=["SpokenLanguageMemoryV1"]
        ).SpokenLanguageMemoryV1(tmp_path / "language.json"),
        _assistant_identity_profile_v1=AssistantIdentityProfileV1(
            tmp_path / "identity.json"
        ),
        ui=SimpleNamespace(write_log=Mock()),
    )
    main.OnyxLive._observe_identity_preferences_v1(
        host, "Onyx, call yourself Atlas"
    )
    assert host._assistant_identity_profile_v1.status().call_alias == "Atlas"
    host.ui.write_log.assert_called_once()
