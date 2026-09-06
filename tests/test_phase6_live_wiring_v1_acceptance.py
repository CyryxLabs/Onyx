from __future__ import annotations

import hashlib

import pytest

from scripts import verify_phase6_live_wiring_v1_acceptance as acceptance


@pytest.fixture(scope="module")
def verified() -> dict[str, object]:
    return acceptance.verify()


def test_external_acceptance_is_exact_default_off_candidate(
    verified: dict[str, object],
) -> None:
    assert verified["acceptance_id"] == acceptance.ACCEPTANCE_ID
    assert verified["decision"] == "accepted"
    assert verified["candidate_manifest_sha256"] == (
        acceptance.CANDIDATE_MANIFEST_SHA256
    )
    assert verified["artifact_root_sha256"] == acceptance.CANDIDATE_ROOT_SHA256
    assert verified["artifacts"] == 5
    assert verified["frozen_anchors"] == 18
    assert verified["focused_passed"] == 17
    assert verified["cumulative_passed"] == 264
    assert verified["severity"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert verified["default_off"] is True
    assert verified["live_wiring"] is False
    assert verified["network_calls"] == 0
    assert verified["phase6_exit"] is False


@pytest.mark.parametrize(
    ("relative", "expected"),
    tuple(
        (relative, digest)
        for relative, (_size, digest) in acceptance.CANDIDATE_ARTIFACTS.items()
    ),
)
def test_candidate_artifact_is_exact(relative: str, expected: str) -> None:
    assert acceptance._digest(acceptance.PROJECT, relative) == expected


def test_candidate_manifest_and_root_recompute() -> None:
    manifest = acceptance._verify_candidate(acceptance.PROJECT)
    observed = {
        entry["path"]: acceptance._digest(acceptance.PROJECT, entry["path"])
        for entry in manifest["artifacts"]
    }
    assert len(observed) == 5
    assert acceptance._root(observed) == acceptance.CANDIDATE_ROOT_SHA256


def test_all_eighteen_frozen_anchors_are_exact() -> None:
    assert len(acceptance.FROZEN_ANCHORS) == 18
    for relative, expected in acceptance.FROZEN_ANCHORS.items():
        assert acceptance._digest(acceptance.PROJECT, relative) == expected


def test_lifecycle_and_protected_seams_are_exact(
    verified: dict[str, object],
) -> None:
    assert verified["patched_seams"] == 3
    assert verified["protected_seams"] == 3


def test_phase5_exit_entry_is_external_and_does_not_unlock_phase6(
    verified: dict[str, object],
) -> None:
    assert verified["phase5_exit_record_sha256"] == acceptance.PHASE5_EXIT_RECORD_SHA256
    metadata = acceptance._json(acceptance.PROJECT, acceptance.PHASE5_EXIT_METADATA)
    assert metadata["decision"] == "accepted"
    assert metadata["phase6_unlocked"] is False


def test_v9_chain_remains_exact_and_wiring_is_not_composed(
    verified: dict[str, object],
) -> None:
    assert verified["v9_chain_compatible_unwired"] is True
    acceptance._verify_entry_and_v9(acceptance.PROJECT)


def test_external_sha256_manifests_bind_exact_sources_and_artifacts() -> None:
    source = acceptance._manifest_rows(acceptance.PROJECT, acceptance.SOURCE_MANIFEST)
    artifacts = acceptance._manifest_rows(
        acceptance.PROJECT, acceptance.ARTIFACT_MANIFEST
    )
    final = acceptance._manifest_rows(
        acceptance.PROJECT, acceptance.ACCEPTANCE_MANIFEST
    )
    assert source == {
        "scripts/verify_phase6_live_wiring_v1_acceptance.py": acceptance._digest(
            acceptance.PROJECT,
            "scripts/verify_phase6_live_wiring_v1_acceptance.py",
        ),
        "tests/test_phase6_live_wiring_v1_acceptance.py": acceptance._digest(
            acceptance.PROJECT,
            "tests/test_phase6_live_wiring_v1_acceptance.py",
        ),
    }
    record_digest = hashlib.sha256(
        (acceptance.PROJECT / acceptance.ACCEPTANCE_RECORD).read_bytes()
    ).hexdigest()
    metadata_digest = hashlib.sha256(
        (acceptance.PROJECT / acceptance.ACCEPTANCE_METADATA).read_bytes()
    ).hexdigest()
    assert artifacts == {
        acceptance.ACCEPTANCE_RECORD: record_digest,
        acceptance.ACCEPTANCE_METADATA: metadata_digest,
    }
    assert final == {acceptance.ACCEPTANCE_RECORD: record_digest}


def test_bound_verifiers_reproduce_exact_markers(
    verified: dict[str, object],
) -> None:
    assert verified["verifiers"] == acceptance.BOUND_VERIFIERS


def test_noncanonical_sha256_rows_fail_closed(tmp_path) -> None:
    bad = tmp_path / "bad.sha256"
    bad.write_text("bad\n", encoding="utf-8")
    with pytest.raises(acceptance.LiveWiringV1AcceptanceError):
        acceptance._manifest_rows(tmp_path, "bad.sha256")
