from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_current_release_status_exposes_v48_evidence_boundary() -> None:
    status = (ROOT / "docs/onyx/CURRENT_RELEASE_STATUS.md").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(status.split())
    assert "Release V48 / Phase 5 V48, dependency-safe and" in normalized
    assert "49,233 passed" in normalized
    assert "R5 rerun then passed 49,381 tests" in normalized
    assert "zero failures and zero errors" in normalized
    assert "R9 source freeze, artifact rebuild" in normalized
    assert "no known vulnerabilities" in status
    assert "SUPERSEDED_SECURITY_REBUILD_REQUIRED" in status
    assert "R9_REBUILD_REQUIRED" in status
    assert "Formal/public status: **NOT RELEASE-ELIGIBLE**" in status
