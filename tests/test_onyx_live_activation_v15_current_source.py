from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from scripts import verify_onyx_live_activation_v15_current_source as anchor


COPY_PATHS = (
    anchor.MANIFEST_RELATIVE,
    anchor.PREDECESSOR_MANIFEST,
    "core/onyx_live_activation_v15.py",
    f"docs/onyx/acceptance/{anchor.ACCEPTANCE_ID}.md",
)
LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "").strip()
INSTALLED_SOURCE = (
    Path(LOCALAPPDATA)
    / "Programs/Cyryx Labs/Onyx/_internal/core/onyx_live_activation_v15.py"
    if LOCALAPPDATA
    else None
)


def _fixture(tmp_path: Path) -> Path:
    for relative in COPY_PATHS:
        source = anchor.ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return tmp_path


def test_current_v15_source_identity_anchor_is_exact_and_narrow() -> None:
    result = anchor.verify()
    assert result["acceptance_id"] == anchor.ACCEPTANCE_ID
    assert result["source_sha256"] == anchor.SOURCE_SHA256
    assert result["scope"] == "current_source_byte_identity_only"
    assert result["functional_acceptance"] is False


@pytest.mark.parametrize("relative", COPY_PATHS)
def test_current_v15_source_identity_anchor_rejects_tamper(
    tmp_path: Path,
    relative: str,
) -> None:
    project = _fixture(tmp_path)
    target = project / relative
    target.write_bytes(target.read_bytes() + b"tamper")
    with pytest.raises(anchor.LiveActivationV15SourceAnchorError):
        anchor.verify(project)


@pytest.mark.skipif(
    INSTALLED_SOURCE is None or not INSTALLED_SOURCE.is_file(),
    reason="canonical Windows install is unavailable",
)
def test_current_v15_source_matches_canonical_installed_payload() -> None:
    result = anchor.verify(require_installed=True)
    assert result["installed_payload_verified"] is True
