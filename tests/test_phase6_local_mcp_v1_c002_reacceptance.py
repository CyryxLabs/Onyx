from __future__ import annotations

from scripts import verify_phase6_local_mcp_v1_c002_reacceptance as gate


def test_dependency_only_reacceptance_is_exact() -> None:
    assert gate.verify(run_tests=False) == {
        "candidate": "phase6-local-mcp-candidate-001",
        "reacceptance": "c002-activation-v10-c003",
        "original_artifacts": 6,
        "unchanged_anchors": 4,
        "superseded_anchor": "core/onyx_live_activation_v10.py",
        "activation_v10": "candidate-003-e6-accepted",
        "focused": 0,
        "network_calls": 0,
        "provider_calls": 0,
        "live_activation": False,
        "phase6_exit": False,
    }


def test_original_candidate_remains_byte_bound() -> None:
    assert gate._digest(gate.ORIGINAL_MANIFEST) == gate.ORIGINAL_MANIFEST_SHA256
    assert gate._digest(gate.CURRENT_V10_SOURCE) == gate.CURRENT_V10_SOURCE_SHA256


def test_v10_c003_evidence_is_byte_bound() -> None:
    assert {
        relative: gate._digest(relative)
        for relative in gate.V10_C003_EVIDENCE
    } == gate.V10_C003_EVIDENCE
