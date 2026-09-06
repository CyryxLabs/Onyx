from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_current_release_status_distinguishes_installed_frozen_and_source() -> None:
    status = (ROOT / "docs/onyx/CURRENT_RELEASE_STATUS.md").read_text(
        encoding="utf-8"
    )
    assert "Onyx 1.1.9 Windows x64 V41, unsigned diagnostic" in status
    assert "V45, source-validated; artifacts not yet built" in status
    assert "V46 authenticated successor; not yet frozen or built" in status
    assert "Formal/public status: **NOT RELEASE-ELIGIBLE**" in status
    assert "No V45 artifact has been built" in status
    assert "or installed" in status
    assert "V46 remains source-only" in status
