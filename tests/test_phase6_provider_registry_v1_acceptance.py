from __future__ import annotations

import hashlib

import pytest

from scripts import verify_phase6_provider_registry_v1_acceptance as acceptance


@pytest.fixture(scope="module")
def verified() -> dict[str, object]:
    return acceptance.verify()


def test_external_acceptance_is_exact_and_default_off(
    verified: dict[str, object],
) -> None:
    assert verified["acceptance_id"] == acceptance.ACCEPTANCE_ID
    assert verified["decision"] == "accepted"
    assert verified["candidate_manifest_sha256"] == (
        acceptance.CANDIDATE_MANIFEST_SHA256
    )
    assert verified["artifact_root_sha256"] == acceptance.CANDIDATE_ROOT_SHA256
    assert verified["artifacts"] == 5
    assert verified["frozen_anchors"] == 7
    assert verified["focused_passed"] == 22
    assert verified["cumulative_passed"] == 156
    assert verified["severity"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert verified["pre_acceptance_resolved"] == {"P1": 2, "P2": 1}
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
def test_candidate_artifact_is_frozen(relative: str, expected: str) -> None:
    assert acceptance._digest(acceptance.PROJECT, relative) == expected


def test_candidate_root_recomputes_independently() -> None:
    manifest = acceptance._verify_candidate(acceptance.PROJECT)
    observed = {
        entry["path"]: acceptance._digest(acceptance.PROJECT, entry["path"])
        for entry in manifest["artifacts"]
    }
    assert acceptance._artifact_root(observed) == acceptance.CANDIDATE_ROOT_SHA256


def test_exact_agentic_core_type_file_and_six_live_anchors_are_bound() -> None:
    assert len(acceptance.FROZEN_ANCHORS) == 7
    for relative, expected in acceptance.FROZEN_ANCHORS.items():
        assert acceptance._digest(acceptance.PROJECT, relative) == expected


def test_privacy_hard_filters_precede_health_and_ranking() -> None:
    acceptance._verify_adversarial_source(acceptance.PROJECT)


def test_no_live_surface_imports_or_enables_candidate(
    verified: dict[str, object],
) -> None:
    assert verified["live_files_checked"] > 10


def test_external_sha256_manifests_bind_sources_artifacts_and_record() -> None:
    source = acceptance._manifest_rows(acceptance.PROJECT, acceptance.SOURCE_MANIFEST)
    artifacts = acceptance._manifest_rows(
        acceptance.PROJECT, acceptance.ARTIFACT_MANIFEST
    )
    final = acceptance._manifest_rows(
        acceptance.PROJECT, acceptance.ACCEPTANCE_MANIFEST
    )
    assert source == {
        "scripts/verify_phase6_provider_registry_v1_acceptance.py": (
            acceptance._digest(
                acceptance.PROJECT,
                "scripts/verify_phase6_provider_registry_v1_acceptance.py",
            )
        ),
        "tests/test_phase6_provider_registry_v1_acceptance.py": acceptance._digest(
            acceptance.PROJECT,
            "tests/test_phase6_provider_registry_v1_acceptance.py",
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


def test_noncanonical_or_malformed_sha256_rows_fail_closed(tmp_path) -> None:
    bad = tmp_path / "bad.sha256"
    bad.write_text("bad\n", encoding="utf-8")
    with pytest.raises(acceptance.ProviderRegistryV1AcceptanceError):
        acceptance._manifest_rows(tmp_path, "bad.sha256")
    with pytest.raises(acceptance.ProviderRegistryV1AcceptanceError):
        acceptance._parts("../candidate")
