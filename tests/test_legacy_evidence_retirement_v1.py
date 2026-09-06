from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import verify_legacy_evidence_retirement_v1 as retirement
from scripts import verify_capability_nexus_current_v1 as capability_successor


ROOT = Path(__file__).resolve().parents[1]


def test_ledger_preserves_history_without_rebinding_successor_bytes() -> None:
    ledger = retirement.load_retirement_ledger(ROOT)
    assert ledger["policy"] == {
        "historical_hashes_are_rebound_to_successor_bytes": False,
        "historical_manifests_remain_immutable": True,
        "successor_drift_requires_an_exact_record": True,
    }
    mission = retirement.artifact_retirement(
        ROOT,
        "core/missions.py",
        "fe2074eb132c09beecb9f13c5151659e745cf888676c4244c037e0a7ed7f2fe5",
        historical_bytes=89747,
    )
    assert mission["historical_sha256"] != mission["current_sha256"]
    assert mission["disposition"] == "superseded-runtime-not-rebound"


def test_unrecorded_drift_fails_closed() -> None:
    with pytest.raises(
        retirement.LegacyEvidenceRetirementError,
        match="lacks exact retirement",
    ):
        retirement.artifact_retirement(
            ROOT,
            "core/missions.py",
            "0" * 64,
        )


def test_retirement_ledger_tamper_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / retirement.LEDGER
    target.parent.mkdir(parents=True)
    value = json.loads((ROOT / retirement.LEDGER).read_text(encoding="utf-8"))
    value["policy"]["historical_hashes_are_rebound_to_successor_bytes"] = True
    target.write_text(json.dumps(value) + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(
        retirement.LegacyEvidenceRetirementError,
        match="ledger digest drifted",
    ):
        retirement.load_retirement_ledger(tmp_path)


def test_authority_successor_rejects_unrecorded_module() -> None:
    with pytest.raises(
        retirement.LegacyEvidenceRetirementError,
        match="outside the recorded successor",
    ):
        retirement.verify_phase4_authority_succession(
            ROOT,
            static_modules=[
                "core.control_plane",
                "core.domain_ledger",
                "core.workspaces",
                "core.unreviewed_authority",
            ],
            fresh_import_modules=["core.control_plane", "core.workspaces"],
        )


def test_v15_v32_permission_broker_history_delegates_to_current_successor() -> None:
    assert len(retirement.CAPABILITY_PERMISSION_BROKER_TEST_IDS) == 18
    for nodeid in retirement.CAPABILITY_PERMISSION_BROKER_TEST_IDS:
        binding = retirement.verify_capability_nexus_permission_broker_succession(
            ROOT,
            collected_test_id=nodeid,
            successor_contract=capability_successor.ACCEPTANCE_ID,
            successor_verifier="scripts.verify_capability_nexus_current_v1",
            successor_marker=capability_successor.MARKER,
        )
        assert binding["historical_claim"] == "superseded-not-rebound"
        assert binding["historical_leaf_sha256"] != binding["current_leaf_sha256"]
    result = capability_successor.verify(ROOT)
    assert result["acceptance_id"] == capability_successor.ACCEPTANCE_ID
    assert result["current_inputs"] == 67


def test_permission_broker_history_rejects_an_unregistered_node() -> None:
    with pytest.raises(
        retirement.LegacyEvidenceRetirementError,
        match="permission-broker succession drifted",
    ):
        retirement.verify_capability_nexus_permission_broker_succession(
            ROOT,
            collected_test_id=(
                "tests/test_capability_nexus_v14.py::"
                "test_frozen_history_proof_never_spawns_a_recursive_verifier"
            ),
            successor_contract=capability_successor.ACCEPTANCE_ID,
            successor_verifier="scripts.verify_capability_nexus_current_v1",
            successor_marker=capability_successor.MARKER,
        )
