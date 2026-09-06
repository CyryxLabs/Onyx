from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import verify_phase6_live_integration_v2_acceptance as acceptance


@pytest.fixture(scope="module")
def verified() -> dict[str, object]:
    return acceptance.verify()


def test_external_acceptance_validates_exact_frozen_candidate(
    verified: dict[str, object],
) -> None:
    assert verified["acceptance_id"] == acceptance.ACCEPTANCE_ID
    assert verified["manifest_sha256"] == acceptance.CANDIDATE_MANIFEST_SHA256
    assert verified["artifact_root_sha256"] == acceptance.CANDIDATE_ROOT_SHA256
    assert verified["candidate_artifacts"] == 6
    assert verified["focused_passed"] == 23
    assert verified["cumulative_passed"] == 241
    assert verified["severity"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert (
        verified["scope"]
        == "phase6-live-integration-v2-isolated-default-off-unwired-handoff"
    )


@pytest.mark.parametrize(
    ("relative", "expected"),
    tuple(
        (relative, digest)
        for relative, (_bytes, digest) in acceptance.CANDIDATE_ARTIFACTS.items()
    )
    + (
        (acceptance.CANDIDATE_MANIFEST, acceptance.CANDIDATE_MANIFEST_SHA256),
        (acceptance.V1_MANIFEST, acceptance.V1_MANIFEST_SHA256),
        (acceptance.V1_REJECTION, acceptance.V1_REJECTION_SHA256),
    ),
)
def test_candidate_and_v1_anchors_are_exact(relative: str, expected: str) -> None:
    assert acceptance._digest(acceptance.PROJECT, relative) == expected


def test_acceptance_manifest_binds_only_external_record() -> None:
    digest, relative = acceptance._manifest_line(
        acceptance._text(acceptance.PROJECT, acceptance.ACCEPTANCE_MANIFEST)
    )
    assert relative == acceptance.ACCEPTANCE_RECORD
    assert (
        digest
        == hashlib.sha256((acceptance.PROJECT / relative).read_bytes()).hexdigest()
    )


def test_malformed_acceptance_manifest_fails_closed() -> None:
    with pytest.raises(acceptance.LiveIntegrationV2AcceptanceError):
        acceptance._manifest_line("bad\n")
    record = acceptance._text(acceptance.PROJECT, acceptance.ACCEPTANCE_RECORD)
    assert acceptance.CANDIDATE_MANIFEST_SHA256 in record
    assert acceptance.CANDIDATE_ROOT_SHA256 in record


def test_two_v1_p1s_are_reproduced_and_v2_closures_are_exact(
    verified: dict[str, object],
) -> None:
    assert verified["p1"] == {
        "v1_incomplete_identity_reproduced": True,
        "v1_arbitrary_dependencies_reproduced": True,
        "v2_complete_identity_closed": True,
        "v2_operational_factory_sealed": True,
    }


def test_all_bound_verifiers_reproduce_their_markers(
    verified: dict[str, object],
) -> None:
    assert verified["verifiers"] == {
        relative: marker
        for relative, (_digest, marker) in acceptance.BOUND_VERIFIERS.items()
    }


def test_v1_remains_exact_rejected_default_off_and_never_live() -> None:
    acceptance._verify_v1_rejection(acceptance.PROJECT)


def test_v2_remains_strict_default_off_and_unwired(
    verified: dict[str, object],
) -> None:
    assert verified["live_files_checked"] >= 2
    manifest = acceptance._text(acceptance.PROJECT, acceptance.CANDIDATE_MANIFEST)
    assert '"default": "off"' in manifest
    assert '"live_wiring": false' in manifest


def test_noncanonical_and_linked_paths_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(acceptance.LiveIntegrationV2AcceptanceError):
        acceptance._canonical_relative("../core/phase6_live_integration_v2.py")
    target = tmp_path / "target.txt"
    target.write_text("target\n", encoding="utf-8", newline="\n")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable on this host")
    with pytest.raises(acceptance.LiveIntegrationV2AcceptanceError):
        acceptance._regular_path(tmp_path, "link.txt")
