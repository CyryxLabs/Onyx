from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pytest

from scripts import verify_r11_projection_retirement_v1 as retirement

from core.approval_inbox_v15 import (
    ApprovalInboxFeatureGateV15,
    ApprovalInboxProjectionV15,
    ApprovalInboxV15ContractError,
    DeterministicInboxClockV15,
    HostInboxItemV15,
    HostInboxSnapshotV15,
    HostInboxSourceV15,
)


PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "tests/fixtures/r11_projection_retirement_v1.json"
RECORD_SHA256 = "4b87a75f4a4e882823b523d7a190d1eda91a034b295d48a6f0208dadc6f2bb07"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load() -> dict[str, object]:
    raw = RECORD.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == RECORD_SHA256
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in raw
    assert raw.endswith(b"\n")
    return json.loads(raw.decode("utf-8"))


def _manifest_closure(*roots: str) -> dict[str, str]:
    queue = list(roots)
    visited: set[str] = set()
    expected: dict[str, str] = {}
    while queue:
        relative = queue.pop(0)
        if relative in visited:
            continue
        visited.add(relative)
        for line in (PROJECT / relative).read_text(encoding="utf-8").splitlines():
            digest, separator, child = line.partition("  ")
            assert separator and len(digest) == 64
            prior = expected.setdefault(child, digest)
            assert prior == digest
            if child.endswith(".sha256"):
                queue.append(child)
    return expected


def test_r11_retirement_is_authenticated_and_preserves_original_anchors() -> None:
    record = _load()
    assert record["schema"] == "onyx.test.r11-projection-retirement.v1"
    assert record["disposition"] == "superseded-unreproducible-not-rebound"
    assert record["policy"] == {
        "current_tamper_coverage_required": True,
        "historical_hashes_are_rebound_to_live_bytes": False,
        "historical_manifests_remain_immutable": True,
        "live_mutable_targets_are_historical_authority": False,
        "missing_historical_bytes_may_be_fabricated": False,
    }
    lineage = record["lineage"]
    assert type(lineage) is dict
    for anchor in lineage.values():
        assert type(anchor) is dict
        assert _sha(PROJECT / anchor["path"]) == anchor["sha256"]


def test_r11_retirement_records_exact_23_recoverable_and_12_unavailable() -> None:
    record = _load()
    projections = record["projections"]
    assert type(projections) is list
    assert [entry["path"] for entry in projections] == sorted(
        entry["path"] for entry in projections
    )
    assert len({entry["path"] for entry in projections}) == 35
    recoverable = [
        entry for entry in projections if entry["state"] == "recoverable-exact"
    ]
    unavailable = [
        entry
        for entry in projections
        if entry["state"] == "unavailable-tombstoned"
    ]
    assert record["counts"] == {
        "total": 35,
        "recoverable_exact": 23,
        "unavailable_tombstoned": 12,
    }
    assert len(recoverable) == 23
    assert len(unavailable) == 12
    assert all(entry["git_blob_oid"] is None for entry in unavailable)

    closure = _manifest_closure(
        "docs/onyx/VE-SOURCE-P51-GRANTS-R11-001.sha256",
        "docs/onyx/VE-ACCEPTANCE-P51-GRANTS-R11-E6-001.sha256",
    )
    witness = record["witness"]
    assert type(witness) is dict
    assert _sha(PROJECT / witness["path"]) == witness["sha256"]
    materialized = json.loads(
        (PROJECT / witness["path"]).read_text(encoding="utf-8")
    )["materialized_tree"]["files"]
    direct_v9 = {
        "docs/onyx/CAPABILITY_MATRIX.md",
        "docs/onyx/VERIFICATION_EVIDENCE.md",
    }
    for entry in projections:
        relative = entry["path"]
        digest = entry["historical_sha256"]
        assert closure[relative] == digest
        if relative in direct_v9:
            snapshot = (
                PROJECT
                / "docs/onyx/checkpoints/phase5-approval-inbox-v9/"
                "mutable-projections"
                / f"{digest}.snapshot"
            )
            assert _sha(snapshot) == digest
        else:
            assert materialized[relative] == digest
        assert _sha(PROJECT / relative) != digest


def test_projection_implementation_successors_bind_old_blobs_and_current_bytes() -> None:
    successors = retirement.load_retirement_record()["implementation_successors"]
    assert [entry["path"] for entry in successors] == sorted(
        entry["path"] for entry in successors
    )
    assert len(successors) == 3
    for entry in successors:
        assert _sha(PROJECT / entry["path"]) == entry["current_sha256"]
        historical = retirement.historical_blob(
            entry["git_blob_oid"], entry["historical_sha256"]
        )
        assert hashlib.sha256(historical).hexdigest() == entry["historical_sha256"]
        assert entry["historical_sha256"] != entry["current_sha256"]


def test_every_recoverable_r11_projection_has_exact_git_blob_bytes() -> None:
    projections = _load()["projections"]
    recoverable = [
        entry for entry in projections if entry["state"] == "recoverable-exact"
    ]
    for entry in recoverable:
        oid = entry["git_blob_oid"]
        data = retirement.historical_blob(oid, entry["historical_sha256"])
        assert hashlib.sha256(data).hexdigest() == entry["historical_sha256"]


def test_retirement_registry_fails_if_a_registered_node_is_not_collected() -> None:
    registered = retirement.registered_test_ids()
    missing = min(registered)
    sources = {nodeid.split("::", 1)[0] for nodeid in registered}
    with pytest.raises(
        retirement.R11ProjectionRetirementError,
        match="no longer collected",
    ):
        retirement.require_registered_tests_collected(
            registered - {missing}, covered_sources=sources
        )


@pytest.mark.parametrize("version", range(2, 8))
def test_each_historical_verifier_executes_v10_tamper_against_retired_projection(
    tmp_path: Path, version: int
) -> None:
    module = importlib.import_module(
        f"scripts.verify_phase5_approval_inbox_v{version}"
    )
    root = tmp_path / f"v{version}"
    copied = retirement.materialize_r11(module, root)
    assert "core/session_grants_v10.py" in copied
    target = root / "core/session_grants_v10.py"
    target.write_bytes(target.read_bytes() + b"\n# successor tamper\n")
    with pytest.raises(
        retirement.R11ProjectionRetirementError,
        match="session_grants_v10.py",
    ):
        retirement.verify_r11(
            module,
            root,
            (module.R11_ROOT, module.R11_ACCEPTANCE_MANIFEST),
        )


def test_current_non_authoritative_projection_tamper_fails_closed(
    tmp_path: Path,
) -> None:
    module = importlib.import_module("scripts.verify_phase5_approval_inbox_v7")
    root = tmp_path / "current-projection"
    retirement.materialize_r11(module, root)
    target = root / "main.py"
    target.write_bytes(target.read_bytes() + b"\n# projected drift\n")
    with pytest.raises(
        retirement.R11ProjectionRetirementError,
        match="main.py",
    ):
        retirement.verify_r11(
            module,
            root,
            (module.R11_ROOT, module.R11_ACCEPTANCE_MANIFEST),
        )


def _successor_item() -> HostInboxItemV15:
    return HostInboxItemV15(
        item_id="item-001",
        action_request_id="request-001",
        principal_id="owner-primary",
        session_id="session-local",
        workspace_id="workspace-main",
        workspace_display="Cyryx Main",
        mission_id="mission-daily",
        mission_display="Daily operations",
        account_id="account-local",
        account_display="Local workspace account",
        connector_id="calendar-local",
        connector_version="1.0",
        tool_id="calendar-tool",
        operation="create-draft",
        environment="local-draft",
        reason="Prepare reviewed item",
        target_display="Calendar draft",
        target_digest="1" * 64,
        payload_summary="Create a reversible draft",
        payload_digest="2" * 64,
        attachment_set_digest="3" * 64,
        policy_version="onyx-policy-1",
        action_schema_version="action-1",
        data_class="internal",
        egress="local-only",
        effect_summary="Creates a draft only",
        reversibility="reversible",
        idempotency_summary="One draft for the request",
        idempotency_key="4" * 64,
        verification_plan="Read the draft back and compare its digest",
        rollback_plan="Delete the local draft before any external action",
        cost_micro=1,
        currency="USD",
        risk="low",
        created_at_ms=10_001,
        expires_at_ms=100_001,
        always_explicit=False,
        batch_eligible=True,
    )


def test_successor_v15_rejects_tampered_review_proof() -> None:
    record = _load()
    successor = record["successor"]
    assert successor == {
        "authority": False,
        "contract": "ApprovalInboxProjectionV15",
        "module": "core/approval_inbox_v15.py",
        "sha256": "f9627e6b9e840dbca8e098a047e56da4647d24ef80f201c5585a41d405d52061",
        "use": "current-test-only-integrity-target",
    }
    assert _sha(PROJECT / successor["module"]) == successor["sha256"]
    gate = ApprovalInboxFeatureGateV15(
        environ={"ONYX_APPROVAL_INBOX_V15": "true"}, epoch_reader=lambda: 1
    )
    source = HostInboxSourceV15(
        principal_id="owner-primary",
        session_id="session-local",
        capture_callback=lambda: HostInboxSnapshotV15(
            1, 55_000, (_successor_item(),)
        ),
    )
    projection = ApprovalInboxProjectionV15(
        gate=gate,
        source=source,
        clock=DeterministicInboxClockV15(1_000),
    )
    page = projection.open_page()
    review = page.items[0]
    tampered = review.review_proof[:-1] + (
        "A" if review.review_proof[-1] != "A" else "B"
    )
    with pytest.raises(ApprovalInboxV15ContractError):
        projection.preview_calm_batch(
            page.snapshot_id,
            page.view_digest,
            ((review.item_id, tampered),),
        )
