from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest

from core.control_plane_v5 import (
    ControlPlaneV5Conflict,
    ControlPlaneV5Disabled,
    ControlPlaneV5IntegrityError,
    ControlPlaneV5IsolationError,
    ControlPlaneV5Store,
    MissionScope,
    V4AuthorityStatus,
    action_request_contract_sha256,
    evidence_verification_sha256,
    provider_request_binding_sha256,
    stable_scope_key,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def accept_test_audit(_trace_id: str, event_hash: str) -> bool:
    return event_hash == digest("audit")


class Vault:
    def __init__(self):
        self.value: bytes | None = None

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, value: bytes | bytearray) -> None:
        self.value = bytes(value)

    def delete(self) -> bool:
        existed = self.value is not None
        self.value = None
        return existed


@dataclass
class Authority:
    root: str = digest("v4-root")

    def status(self) -> V4AuthorityStatus:
        return V4AuthorityStatus(
            "accepted-v4", 4, digest("v4-schema"), self.root, 12
        )

    def read_scope(self, workspace_id: str, mission_id: str) -> MissionScope:
        if workspace_id not in {"workspace-a", "workspace-b"}:
            raise RuntimeError("unknown")
        if mission_id != f"mission-{workspace_id[-1]}":
            raise RuntimeError("cross-scope")
        return MissionScope(
            workspace_id,
            mission_id,
            f"correlation-{workspace_id[-1]}",
            3,
            digest(f"context-{workspace_id}"),
            self.root,
        )


@pytest.fixture
def store(tmp_path):
    key, state, pending = Vault(), Vault(), Vault()
    value = ControlPlaneV5Store(
        path=tmp_path / "control_plane_v5.sqlite3",
        source=Authority(),
        key_vault=key,
        state_vault=state,
        pending_vault=pending,
        enabled=True,
        audit_reference_verifier=accept_test_audit,
        semantic_audit_verifier=accept_test_audit,
    ).initialize()
    return value, key, state


def positive_receipt_bindings(
    value, request, *, suffix: str, postcondition_text: str
):
    postcondition = digest(postcondition_text)
    content = digest(f"output-{suffix}")
    artifact = value.record_artifact(
        workspace_id=request.workspace_id,
        mission_id=request.mission_id,
        request_id=request.request_id,
        content_sha256=content,
        relative_path=f"{content[:2]}/{content}",
        byte_length=12,
        media_type="application/json",
        metadata_sha256=digest(f"metadata-{suffix}"),
        caller_key=f"artifact-{suffix}",
        source_provenance_sha256=digest("provider-free-local"),
        artifact_created_at="2026-07-17T12:00:00+00:00",
        manifest_sha256=digest(f"manifest-{suffix}"),
    )
    evidence = value.record_evidence(
        workspace_id=request.workspace_id,
        mission_id=request.mission_id,
        source_kind="tool_output",
        source_identity_sha256=digest("local-system-status"),
        content_sha256=content,
        artifact_id=artifact.artifact_id,
        credibility_bp=10000,
        freshness="current",
        access_license_sha256=digest("cyryx-internal"),
        observed_at="2026-07-17T12:00:00+00:00",
        caller_key=f"evidence-{suffix}",
        title="Local system status",
        uri_or_file_ref=f"artifact:{artifact.artifact_id}",
        publisher_or_owner="Cyryx Labs Onyx local runtime",
        access_and_license_notes="cyryx-internal",
    )
    claim = value.record_claim(
        workspace_id=request.workspace_id,
        mission_id=request.mission_id,
        claim_kind="fact",
        statement_sha256=postcondition,
        evidence_ids=(evidence.evidence_id,),
        confidence_bp=10000,
        verification_status="single_source",
        valid_until=None,
        contradiction_claim_ids=(),
        caller_key=f"claim-{suffix}",
        text=postcondition_text,
        verified_at="2026-07-17T12:00:00+00:00",
        valid_from="2026-07-17T12:00:00+00:00",
    )
    return artifact, evidence, claim


def test_default_off_creates_no_database(tmp_path):
    path = tmp_path / "off.sqlite3"
    value = ControlPlaneV5Store(
        path=path,
        source=Authority(),
        key_vault=Vault(),
        state_vault=Vault(),
        enabled=False,
    )
    with pytest.raises(ControlPlaneV5Disabled):
        value.initialize()
    assert not path.exists()


def test_v5_sidecar_has_no_production_startup_imports():
    project = Path(__file__).parents[1]
    for relative in (
        "main.py",
        "ui.py",
        "dashboard/server.py",
        "core/missions.py",
        "core/mission_tools.py",
    ):
        source = (project / relative).read_text(encoding="utf-8")
        assert "control_plane_v5" not in source
        assert "mission_evidence_v5" not in source


def test_initialize_reopen_and_missing_vault_fail_closed(tmp_path):
    path = tmp_path / "v5.sqlite3"
    key, state, pending = Vault(), Vault(), Vault()
    first = ControlPlaneV5Store(
        path=path, source=Authority(), key_vault=key, state_vault=state,
        pending_vault=pending, enabled=True
    ).initialize()
    assert first.status().schema_version == 5
    reopened = ControlPlaneV5Store(
        path=path, source=Authority(), key_vault=key, state_vault=state,
        pending_vault=pending, enabled=True
    ).initialize()
    assert reopened.status() == first.status()
    with pytest.raises(ControlPlaneV5IntegrityError):
        ControlPlaneV5Store(
            path=path,
            source=Authority(),
            key_vault=Vault(),
            state_vault=state,
            pending_vault=pending,
            enabled=True,
        ).initialize()


def test_action_unknown_requires_explicit_reconciliation(store):
    value, _key, _state = store
    idempotency = stable_scope_key(
        workspace_id="workspace-a",
        mission_id="mission-a",
        operation="local_system_status",
        caller_key="daily-status",
    )
    scope = value.mission_scope(workspace_id="workspace-a", mission_id="mission-a")
    request_id = "request-" + digest(idempotency)
    request_sha256 = action_request_contract_sha256(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request_id,
        correlation_id=scope.correlation_id,
        connector="local_mission_tools",
        operation="local_system_status",
        target="local-runtime",
        target_sha256=digest("local-runtime"),
        payload_sha256=digest("{}"),
        idempotency_key=idempotency,
        risk="low",
        approval_policy="shadow_only",
        dry_run=True,
        verification_plan_sha256=digest("runtime_status_observed"),
        source_context_sha256=scope.context_sha256,
    )
    lease = value.reserve_action_request(
        workspace_id="workspace-a",
        mission_id="mission-a",
        idempotency_key=idempotency,
        request_sha256=request_sha256,
    )
    value.link_action_audit(
        workspace_id="workspace-a", mission_id="mission-a",
        request_id=request_id, owner_id=lease.owner_id,
        audit_reference_sha256=digest("audit"),
        request_sha256=request_sha256,
        idempotency_key=idempotency,
        connector="local_mission_tools",
        operation="local_system_status",
        target="local-runtime",
        target_sha256=digest("local-runtime"),
        payload_sha256=digest("{}"),
        risk="low",
        approval_policy="shadow_only",
        dry_run=True,
        source_context_sha256=scope.context_sha256,
        verification_plan_sha256=digest("runtime_status_observed"),
    )
    request = value.record_action_request(
        workspace_id="workspace-a",
        mission_id="mission-a",
        connector="local_mission_tools",
        operation="local_system_status",
        target="local-runtime",
        target_sha256=digest("local-runtime"),
        payload_sha256=digest("{}"),
        idempotency_key=idempotency,
        risk="low",
        approval_policy="shadow_only",
        dry_run=True,
        audit_reference_sha256=digest("audit"),
        verification_plan_sha256=digest("runtime_status_observed"),
        reservation_owner_id=lease.owner_id,
    )
    replay = value.record_action_request(
        workspace_id="workspace-a",
        mission_id="mission-a",
        connector="local_mission_tools",
        operation="local_system_status",
        target="local-runtime",
        target_sha256=digest("local-runtime"),
        payload_sha256=digest("{}"),
        idempotency_key=idempotency,
        risk="low",
        approval_policy="shadow_only",
        dry_run=True,
        audit_reference_sha256=digest("audit"),
        verification_plan_sha256=digest("runtime_status_observed"),
        reservation_owner_id=lease.owner_id,
    )
    assert replay.request_id == request.request_id
    value.mark_action_dispatch_unknown(
        workspace_id="workspace-a", mission_id="mission-a",
        request_id=request.request_id, owner_id=lease.owner_id,
    )
    unknown = value.record_action_receipt(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
        outcome="unknown",
        provider_request_sha256=provider_request_binding_sha256(
            request.request_id, f"local-system-status:{request.request_id}"
        ),
        output_sha256=digest("none"),
        verification_sha256=digest(""),
        postcondition_sha256=digest("not-observed"),
        error_class="observation_interrupted",
        supersedes_receipt_id=None,
        reconciliation=False,
        observed_at="2026-07-17T12:00:00+00:00",
        caller_key="initial-observation",
        provider_request_id=request.request_id,
        provider_request_ref=f"local-system-status:{request.request_id}",
        started_at="2026-07-17T11:59:59+00:00",
    )
    assert value.reconcile_required(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
    )
    postcondition = digest("observed")
    artifact, evidence, claim = positive_receipt_bindings(
        value, request, suffix="reconciliation", postcondition_text="observed"
    )
    positive = dict(
        provider_request_id=request.request_id,
        provider_request_ref=f"local-system-status:{request.request_id}",
        started_at="2026-07-17T11:59:59+00:00",
        completed_at="2026-07-17T12:01:00+00:00",
        output_ref=f"artifact:{artifact.artifact_id}",
        verification_ref=f"evidence:{evidence.evidence_id}",
        after_state_ref=f"claim:{claim.claim_id}",
    )
    with pytest.raises(ControlPlaneV5Conflict):
        value.record_action_receipt(
            workspace_id="workspace-a",
            mission_id="mission-a",
            request_id=request.request_id,
            outcome="simulated",
            provider_request_sha256=provider_request_binding_sha256(
                request.request_id,
                f"local-system-status:{request.request_id}",
            ),
            output_sha256=artifact.content_sha256,
            verification_sha256=evidence_verification_sha256(evidence),
            postcondition_sha256=postcondition,
            error_class="",
            supersedes_receipt_id=None,
            reconciliation=False,
            observed_at="2026-07-17T12:01:00+00:00",
            caller_key="blind-retry",
            **positive,
        )
    reconciled = value.record_action_receipt(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
        outcome="simulated",
        provider_request_sha256=provider_request_binding_sha256(
            request.request_id, f"local-system-status:{request.request_id}"
        ),
        output_sha256=artifact.content_sha256,
        verification_sha256=evidence_verification_sha256(evidence),
        postcondition_sha256=postcondition,
        error_class="",
        supersedes_receipt_id=unknown.receipt_id,
        reconciliation=True,
        observed_at="2026-07-17T12:01:00+00:00",
        caller_key="explicit-reconciliation",
        **positive,
    )
    assert reconciled.reconciliation
    assert not value.reconcile_required(
        workspace_id="workspace-a",
        mission_id="mission-a",
        request_id=request.request_id,
    )


def test_workspace_mission_isolation_and_bounded_events(store):
    value, _key, _state = store
    with pytest.raises(ControlPlaneV5IsolationError):
        value.record_evidence(
            workspace_id="workspace-a",
            mission_id="mission-b",
            source_kind="observation",
            source_identity_sha256=digest("source"),
            content_sha256=digest("content"),
            artifact_id=None,
            credibility_bp=10000,
            freshness="current",
            access_license_sha256=digest("internal"),
            observed_at="2026-07-17T12:00:00+00:00",
            caller_key="cross-scope",
        )
    evidence = value.record_evidence(
        workspace_id="workspace-a",
        mission_id="mission-a",
        source_kind="observation",
        source_identity_sha256=digest("source"),
        content_sha256=digest("content"),
        artifact_id=None,
        credibility_bp=10000,
        freshness="current",
        access_license_sha256=digest("internal"),
        observed_at="2026-07-17T12:00:00+00:00",
        caller_key="isolated-evidence",
    )
    with pytest.raises(ControlPlaneV5IsolationError):
        value.get_evidence(
            workspace_id="workspace-b",
            mission_id="mission-b",
            evidence_id=evidence.evidence_id,
        )
    events = value.list_events(
        workspace_id="workspace-a", mission_id="mission-a", limit=1
    )
    assert len(events) == 1


def test_record_and_schema_tamper_fail_closed(store):
    value, _key, _state = store
    evidence = value.record_evidence(
        workspace_id="workspace-a",
        mission_id="mission-a",
        source_kind="observation",
        source_identity_sha256=digest("source"),
        content_sha256=digest("content"),
        artifact_id=None,
        credibility_bp=10000,
        freshness="current",
        access_license_sha256=digest("internal"),
        observed_at="2026-07-17T12:00:00+00:00",
        caller_key="tamper-evidence",
    )
    connection = sqlite3.connect(value.path)
    try:
        connection.execute("PRAGMA writable_schema=ON")
        connection.execute(
            "UPDATE sqlite_master SET sql=sql || ' ' "
            "WHERE name='evidence_records'"
        )
        connection.execute("PRAGMA writable_schema=OFF")
        connection.commit()
    finally:
        connection.close()
    # A direct row update is blocked by immutable triggers.
    with pytest.raises((ControlPlaneV5IntegrityError, sqlite3.DatabaseError)):
        value.get_evidence(
            workspace_id="workspace-a",
            mission_id="mission-a",
            evidence_id=evidence.evidence_id,
        )
