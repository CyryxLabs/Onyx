from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_current_release_status_exposes_security_successor_boundary() -> None:
    status = (ROOT / "docs/onyx/CURRENT_RELEASE_STATUS.md").read_text(
        encoding="utf-8"
    )
    assert "Release V47 / Phase 5 V47, dependency-safe source" in status
    assert "no known vulnerabilities" in status
    assert "170 focused tests with 1 expected platform skip" in status
    assert "SUPERSEDED_SECURITY_REBUILD_REQUIRED" in status
    assert "R9_REBUILD_REQUIRED" in status
    assert "Formal/public status: **NOT RELEASE-ELIGIBLE**" in status
