from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts import verify_phase6_local_text_compat_v1_acceptance as acceptance


ROOT = Path(__file__).resolve().parents[1]


def test_external_e6_acceptance_is_reproducible() -> None:
    result = acceptance.verify(run_tests=False)
    assert result["decision"] == "accepted"
    assert result["focused_passed"] == 31
    assert result["network_calls"] == 0
    assert result["provider_calls"] == 0


def test_candidate_manifest_identity_tamper_fails_closed(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    relative = acceptance.CANDIDATE_MANIFEST
    target = project / relative
    target.parent.mkdir(parents=True)
    shutil.copy2(ROOT / relative, target)
    value = json.loads(target.read_text(encoding="utf-8"))
    value["candidate"] = "substituted"
    target.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(acceptance.LocalTextAcceptanceError, match="manifest drifted"):
        acceptance._verify_candidate(project)


def test_canonical_path_gate_rejects_traversal_and_symlink(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(acceptance.LocalTextAcceptanceError, match="non-canonical"):
        acceptance._path(project, "../outside")
    outside = tmp_path / "outside"
    outside.write_text("outside", encoding="utf-8")
    link = project / "link"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    with pytest.raises(acceptance.LocalTextAcceptanceError, match="linked"):
        acceptance._path(project, "link")
