from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scripts import verify_phase5_capability_nexus_v32_acceptance as acceptance


COPY_PATHS = (
    acceptance.ACCEPTANCE_RECORD,
    acceptance.ACCEPTANCE_MANIFEST,
    acceptance.ROOT_MANIFEST,
    acceptance.ARTIFACT_MANIFEST,
    acceptance.BUNDLE,
    acceptance.V31_ROOT_MANIFEST,
    acceptance.V31_ARTIFACT_MANIFEST,
    acceptance.CAPABILITY_MATRIX,
    acceptance.VERIFICATION_EVIDENCE,
)


def _copy_acceptance_fixture(tmp_path: Path) -> Path:
    for relative in COPY_PATHS:
        source = acceptance.PROJECT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return tmp_path


def test_external_acceptance_validates_without_rerunning_expensive_parent() -> None:
    result = acceptance.verify(run_parent=False)
    assert result == {
        "acceptance_id": acceptance.ACCEPTANCE_ID,
        "record_sha256": acceptance._digest(acceptance.PROJECT, acceptance.ACCEPTANCE_RECORD),
        "root_sha256": acceptance.ROOT_SHA256,
        "artifact_sha256": acceptance.ARTIFACT_SHA256,
        "bundle_sha256": acceptance.BUNDLE_SHA256,
        "parent": None,
        "scope": "phase5.3-default-off-shadow-only-handoff",
    }


@pytest.mark.parametrize(
    "relative",
    (
        acceptance.ACCEPTANCE_RECORD,
        acceptance.ACCEPTANCE_MANIFEST,
        acceptance.ROOT_MANIFEST,
        acceptance.ARTIFACT_MANIFEST,
        acceptance.BUNDLE,
        acceptance.V31_ROOT_MANIFEST,
        acceptance.V31_ARTIFACT_MANIFEST,
    ),
)
def test_record_manifest_and_candidate_anchor_tamper_fail_closed(tmp_path: Path, relative: str) -> None:
    project = _copy_acceptance_fixture(tmp_path)
    target = project / relative
    target.write_bytes(target.read_bytes() + b"tamper")
    with pytest.raises(acceptance.CapabilityNexusV32AcceptanceError):
        acceptance.verify(project, run_parent=False)


def test_mutable_projections_are_required_but_excluded_from_frozen_v32_dag() -> None:
    artifacts = acceptance._text(acceptance.PROJECT, acceptance.ARTIFACT_MANIFEST)
    assert acceptance.CAPABILITY_MATRIX not in artifacts
    assert acceptance.VERIFICATION_EVIDENCE not in artifacts
    assert acceptance.ACCEPTANCE_RECORD not in artifacts
    assert acceptance.ACCEPTANCE_MANIFEST not in artifacts
    assert acceptance.ACCEPTANCE_ID in acceptance._text(acceptance.PROJECT, acceptance.CAPABILITY_MATRIX)
    assert acceptance.ACCEPTANCE_ID in acceptance._text(acceptance.PROJECT, acceptance.VERIFICATION_EVIDENCE)


def test_default_verification_requires_exact_parent_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = {
        "artifacts": 496,
        "focused_passed": 2021,
        "live_scan_files": 111,
        "root_sha256": acceptance.ROOT_SHA256,
    }
    calls: list[Path] = []

    def fake_parent(project: Path) -> dict[str, object]:
        calls.append(project)
        return expected

    monkeypatch.setattr(acceptance, "_run_parent", fake_parent)
    result = acceptance.verify()
    assert calls == [acceptance.PROJECT]
    assert result["parent"] == expected
