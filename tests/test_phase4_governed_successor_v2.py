from __future__ import annotations

import subprocess
import sys

import pytest

from scripts import verify_phase4_governed_successor_v2 as successor
from scripts.verify_legacy_evidence_retirement_v1 import LegacyEvidenceRetirementError


def test_v2_binds_the_same_exact_static_and_fresh_authority_closure() -> None:
    result = successor.verify()
    assert result["status"] == successor.STATUS
    assert result["predecessor_status"] == "P4_GOVERNED_SUCCESSOR_V1_OK"
    assert result["static_authority"] == successor.EXPECTED_AUTHORITY
    assert result["fresh_import_authority"] == successor.EXPECTED_AUTHORITY
    assert result["authority_closure_consistent"] is True


def test_v2_rejects_fresh_import_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        successor.predecessor,
        "_fresh_import_authority",
        lambda: ["core.control_plane", "core.workspaces"],
    )
    with pytest.raises(LegacyEvidenceRetirementError):
        successor.verify()


def test_v2_cli_emits_only_the_v2_success_marker() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "scripts.verify_phase4_governed_successor_v2"],
        cwd=successor.predecessor.PROJECT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(f"{successor.STATUS} ")
    assert "P4_GOVERNED_SUCCESSOR_V1_OK " not in result.stdout
