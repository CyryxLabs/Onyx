from __future__ import annotations

import hashlib

import pytest

from scripts import verify_phase6_research_cells_v1_acceptance as acceptance


@pytest.fixture(scope="module")
def verified() -> dict[str, object]:
    return acceptance.verify()


def test_external_acceptance_is_exact_default_off_and_provider_free(
    verified: dict[str, object],
) -> None:
    assert verified["acceptance_id"] == acceptance.ACCEPTANCE_ID
    assert verified["decision"] == "accepted"
    assert verified["candidate_manifest_sha256"] == (
        acceptance.CANDIDATE_MANIFEST_SHA256
    )
    assert verified["artifact_root_sha256"] == acceptance.CANDIDATE_ROOT_SHA256
    assert verified["artifacts"] == 5
    assert verified["frozen_anchors"] == 9
    assert verified["focused_passed"] == 22
    assert verified["cumulative_passed"] == 178
    assert verified["severity"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert verified["pre_acceptance_resolved"] == {"P1": 5}
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
        item["path"]: acceptance._digest(acceptance.PROJECT, item["path"])
        for item in manifest["artifacts"]
    }
    assert acceptance._artifact_root(observed) == acceptance.CANDIDATE_ROOT_SHA256


def test_exact_agentic_core_and_live_anchors_are_bound() -> None:
    assert len(acceptance.FROZEN_ANCHORS) == 9
    for relative, expected in acceptance.FROZEN_ANCHORS.items():
        assert acceptance._digest(acceptance.PROJECT, relative) == expected


def test_cells_and_instruction_profiles_are_distinct_and_exact() -> None:
    assert acceptance.IDENTITIES == {
        "research": "b56857acde92d5caded13274363758c8e23f3a38817cfb7acabfd8dfb6e7dc18",
        "verifier": "50288fcb69c23315b5f831562c107c44784d9589dcdd2e81651d1e8f71545115",
    }
    assert acceptance.INSTRUCTIONS == {
        "research": "78386ecb9216e6ab7e36a6e59372e21ed97f7297dcb932afe479e60f5a803a5d",
        "verifier": "50c72840e0f4c5417a1fc6966168571b191e961d9d63d5f56de919d78853270f",
    }
    assert len(set(acceptance.IDENTITIES.values())) == 2
    assert len(set(acceptance.INSTRUCTIONS.values())) == 2


def test_adversarial_source_contract_and_no_live_surface(
    verified: dict[str, object],
) -> None:
    acceptance._verify_source_contract(acceptance.PROJECT)
    assert verified["live_files_checked"] == 204


def test_external_sha256_manifests_bind_sources_artifacts_and_record() -> None:
    source = acceptance._manifest_rows(acceptance.PROJECT, acceptance.SOURCE_MANIFEST)
    artifacts = acceptance._manifest_rows(
        acceptance.PROJECT, acceptance.ARTIFACT_MANIFEST
    )
    final = acceptance._manifest_rows(
        acceptance.PROJECT, acceptance.ACCEPTANCE_MANIFEST
    )
    assert source == {
        "scripts/verify_phase6_research_cells_v1_acceptance.py": (
            acceptance._digest(
                acceptance.PROJECT,
                "scripts/verify_phase6_research_cells_v1_acceptance.py",
            )
        ),
        "tests/test_phase6_research_cells_v1_acceptance.py": acceptance._digest(
            acceptance.PROJECT,
            "tests/test_phase6_research_cells_v1_acceptance.py",
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
    with pytest.raises(acceptance.ResearchCellsV1AcceptanceError):
        acceptance._manifest_rows(tmp_path, "bad.sha256")
    with pytest.raises(acceptance.ResearchCellsV1AcceptanceError):
        acceptance._parts("../candidate")
