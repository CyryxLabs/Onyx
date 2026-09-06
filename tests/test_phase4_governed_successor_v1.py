from __future__ import annotations

import subprocess
import sys

import pytest

from scripts import verify_phase4_exit_candidate_r3 as historical
from scripts import verify_phase4_governed_successor_v1 as successor
from scripts.verify_legacy_evidence_retirement_v1 import (
    LegacyEvidenceRetirementError,
)


def test_historical_verifier_remains_exact_and_rejects_current_authority() -> None:
    with pytest.raises(RuntimeError, match="authority-bearing module"):
        historical.verify_static_authority_closure()
    with pytest.raises(RuntimeError, match="fresh startup import probe failed"):
        historical.verify_fresh_import_probe()


def test_governed_successor_has_a_distinct_truthful_marker() -> None:
    result = successor.verify()
    assert result["status"] == "P4_GOVERNED_SUCCESSOR_V1_OK"
    assert result["historical_gate"] == "P4_EXIT_CANDIDATE_R3_RETIRED"
    assert result["historical_verifier_state"] == "preserved-exact"
    assert result["historical_tests_state"] == "superseded-not-rebound"
    assert result["static_authority"] == [
        "core.control_plane",
        "core.domain_ledger",
        "core.workspaces",
    ]
    assert result["fresh_import_authority"] == [
        "core.control_plane",
        "core.workspaces",
    ]


def test_governed_successor_rejects_unregistered_authority(monkeypatch) -> None:
    monkeypatch.setattr(
        successor,
        "_static_authority",
        lambda: [
            "core.control_plane",
            "core.domain_ledger",
            "core.unreviewed_authority",
            "core.workspaces",
        ],
    )
    monkeypatch.setattr(
        successor,
        "_fresh_import_authority",
        lambda: ["core.control_plane", "core.workspaces"],
    )
    with pytest.raises(
        LegacyEvidenceRetirementError,
        match="outside the recorded successor",
    ):
        successor.verify()


def test_governed_successor_cli_emits_only_its_new_marker() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "scripts.verify_phase4_governed_successor_v1"],
        cwd=successor.PROJECT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "P4_GOVERNED_SUCCESSOR_V1_OK" in result.stdout
    assert "P4_EXIT_CANDIDATE_R3_SOURCE_OK" not in result.stdout
