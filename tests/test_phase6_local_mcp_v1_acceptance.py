from __future__ import annotations

import hashlib

import pytest

from scripts import verify_phase6_local_mcp_v1_acceptance as acceptance


@pytest.fixture(scope="module")
def verified() -> dict[str, object]:
    return acceptance.verify()


def test_external_e6_decision_is_exact(verified: dict[str, object]) -> None:
    assert verified == {
        "acceptance_id": acceptance.ACCEPTANCE_ID,
        "decision": "accepted",
        "candidate_manifest_sha256": acceptance.CANDIDATE_MANIFEST_SHA256,
        "artifact_root_sha256": acceptance.CANDIDATE_ROOT_SHA256,
        "artifacts": 6,
        "frozen_anchors": 5,
        "focused_passed": 27,
        "cumulative_passed": 59,
        "findings": {"P0": 0, "P1": 0, "P2": 0, "P3": 0},
        "network_calls": 0,
        "provider_calls": 0,
        "default_off": True,
        "live_activation": False,
        "phase6_exit": False,
    }


@pytest.mark.parametrize(
    ("relative", "size", "expected"),
    tuple(
        (relative, size, digest)
        for relative, (size, digest) in acceptance.CANDIDATE_ARTIFACTS.items()
    ),
)
def test_candidate_artifact_is_immutable(
    relative: str, size: int, expected: str
) -> None:
    path = acceptance._path(acceptance.PROJECT, relative)
    assert path.stat().st_size == size
    assert acceptance._digest(acceptance.PROJECT, relative) == expected


def test_candidate_root_and_frozen_anchors_recompute() -> None:
    records = {
        relative: acceptance._digest(acceptance.PROJECT, relative)
        for relative in acceptance.CANDIDATE_ARTIFACTS
    }
    assert acceptance._root(records) == acceptance.CANDIDATE_ROOT_SHA256
    for relative, expected in acceptance.FROZEN_ANCHORS.items():
        assert acceptance._digest(acceptance.PROJECT, relative) == expected


def test_sha256_envelopes_bind_sources_artifacts_and_decision() -> None:
    sources = acceptance._manifest_rows(acceptance.PROJECT, acceptance.SOURCE_MANIFEST)
    assert sources == {
        relative: acceptance._digest(acceptance.PROJECT, relative)
        for relative in (
            "scripts/verify_phase6_local_mcp_v1_acceptance.py",
            "tests/test_phase6_local_mcp_v1_acceptance.py",
        )
    }
    artifacts = acceptance._manifest_rows(
        acceptance.PROJECT, acceptance.ARTIFACT_MANIFEST
    )
    assert artifacts == {
        relative: acceptance._digest(acceptance.PROJECT, relative)
        for relative in (
            acceptance.ACCEPTANCE_RECORD,
            acceptance.ACCEPTANCE_METADATA,
        )
    }
    final = acceptance._manifest_rows(
        acceptance.PROJECT, acceptance.ACCEPTANCE_MANIFEST
    )
    record_digest = hashlib.sha256(
        (acceptance.PROJECT / acceptance.ACCEPTANCE_RECORD).read_bytes()
    ).hexdigest()
    assert final == {acceptance.ACCEPTANCE_RECORD: record_digest}


def test_no_live_or_phase6_exit_claim(verified: dict[str, object]) -> None:
    assert verified["default_off"] is True
    assert verified["live_activation"] is False
    assert verified["network_calls"] == 0
    assert verified["provider_calls"] == 0
    assert verified["phase6_exit"] is False
