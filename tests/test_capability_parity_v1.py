from __future__ import annotations

from pathlib import Path

from core.capability_parity_v1 import CAPABILITIES, validate_source_parity_v1


ROOT = Path(__file__).resolve().parents[1]


def test_closed_registry_has_full_source_contract_evidence():
    report = validate_source_parity_v1(ROOT)
    assert report["source_contract_coverage_percent"] == 100.0
    assert report["capability_count"] == len(CAPABILITIES) == 42
    assert report["missing_evidence"] == []
    assert report["package_verified"] is False
    assert report["installed_verified"] is False
    assert report["live_provider_verified"] is False
    assert report["operational_parity_certified"] is False
    assert report["reference_head"] == "234dd792737f3acd38ca836aadae94c24ef0ad56"


def test_registry_includes_current_owner_requested_expansions():
    identifiers = {row.capability_id for row in CAPABILITIES}
    assert {"silent_language_memory", "assistant_customization", "repetition_counter", "video_upload", "calorie_tracker"} <= identifiers
    assert {
        "live_voice_selection",
        "audio_device_selection",
        "owner_memory_control",
        "bounded_undo",
        "owner_confirmation",
        "local_action_resolution",
        "unicode_safe_diagnostics",
    } <= identifiers


def test_cyryx_license_and_identity_remain_authoritative():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    identity = (ROOT / "core" / "identity.py").read_text(encoding="utf-8")
    assert license_text.startswith("# Cyryx Labs LLC Software License Agreement")
    assert "Copyright (c) 2026 Cyryx Labs LLC" in license_text
    assert 'ASSISTANT_NAME = "Onyx"' in identity
    assert 'ASSISTANT_TAGLINE = "Cyryx Labs AI assistant"' in identity
