from __future__ import annotations

import hashlib
import json

import pytest

from core import mission_tools
from core.control_plane_v5 import (
    ArtifactRecord,
    ControlPlaneV5Disabled,
    ControlPlaneV5Store,
    action_audit_semantic_contract,
    action_audit_trace_id,
    action_request_contract_sha256,
)
from core.mission_evidence_v5 import (
    LocalSystemStatusEvidenceService,
    ReconciliationRequired,
)
from p44_v5_support import Authority, Vault


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class FakeAudit:
    def __init__(self):
        self.members: dict[str, str] = {}
        self.written_requests = []

    def write(self, request):
        self.written_requests.append(request)
        request_sha256 = action_request_contract_sha256(
            workspace_id=request.workspace_id,
            mission_id=request.mission_id,
            request_id=request.request_id,
            correlation_id=request.correlation_id,
            connector=request.connector,
            operation=request.operation,
            target_sha256=request.target_sha256,
            payload_sha256=request.payload_sha256,
            idempotency_key=request.idempotency_key,
            risk=request.risk,
            approval_policy=request.approval_policy,
            dry_run=request.dry_run,
            verification_plan_sha256=request.verification_plan_sha256,
            source_context_sha256=request.source_context_sha256,
            target=request.target,
            approval_id=request.approval_id,
            schema_version=request.schema_version,
        )
        trace = action_audit_trace_id(
            workspace_id=request.workspace_id,
            mission_id=request.mission_id,
            request_id=request.request_id,
            request_sha256=request_sha256,
            idempotency_key=request.idempotency_key,
            connector=request.connector,
            operation=request.operation,
            target_sha256=request.target_sha256,
            payload_sha256=request.payload_sha256,
            risk=request.risk,
            approval_policy=request.approval_policy,
            dry_run=request.dry_run,
            correlation_id=request.correlation_id,
            source_context_sha256=request.source_context_sha256,
            target=request.target,
            approval_id=request.approval_id,
            schema_version=request.schema_version,
        )
        event_hash = hashlib.sha256(request.request_id.encode()).hexdigest()
        self.members[trace] = event_hash
        return event_hash

    @staticmethod
    def trace(value):
        if isinstance(value, dict):
            encoded = json.dumps(
                value["request"], ensure_ascii=True, sort_keys=True,
                separators=(",", ":"),
            )
            version = str(value["contract"]).rsplit(".v", 1)[-1]
            return hashlib.sha256(
                (f"ONYX-V5-AUDIT-TRACE.v{version}\0" + encoded).encode("ascii")
            ).hexdigest()
        request = value
        request_sha256 = action_request_contract_sha256(
            workspace_id=request.workspace_id, mission_id=request.mission_id,
            request_id=request.request_id, correlation_id=request.correlation_id,
            connector=request.connector, operation=request.operation,
            target_sha256=request.target_sha256,
            payload_sha256=request.payload_sha256,
            idempotency_key=request.idempotency_key, risk=request.risk,
            approval_policy=request.approval_policy, dry_run=request.dry_run,
            verification_plan_sha256=request.verification_plan_sha256,
            source_context_sha256=request.source_context_sha256,
            target=request.target,
            approval_id=request.approval_id,
            schema_version=request.schema_version,
        )
        return action_audit_trace_id(
            workspace_id=request.workspace_id, mission_id=request.mission_id,
            request_id=request.request_id, request_sha256=request_sha256,
            idempotency_key=request.idempotency_key, connector=request.connector,
            operation=request.operation, target_sha256=request.target_sha256,
            payload_sha256=request.payload_sha256, risk=request.risk,
            approval_policy=request.approval_policy, dry_run=request.dry_run,
            correlation_id=request.correlation_id,
            source_context_sha256=request.source_context_sha256,
            target=request.target,
            approval_id=request.approval_id,
            schema_version=request.schema_version,
        )

    def verify(self, value, event_hash):
        trace_id = self.trace(value)
        return self.members.get(trace_id) == event_hash

    def lookup(self, value):
        return self.members.get(self.trace(value))


class Artifacts:
    def __init__(self, store: ControlPlaneV5Store):
        self.store = store
        self.values: dict[tuple[str, str], bytes] = {}
        self.publish_calls = 0
        self.read_calls = 0

    def publish(
        self,
        *,
        workspace_id: str,
        mission_id: str,
        request_id: str,
        content: bytes,
        media_type: str,
        metadata: dict[str, object],
        caller_key: str,
    ) -> ArtifactRecord:
        self.publish_calls += 1
        content_sha256 = digest_bytes(content)
        record = self.store.record_artifact(
            workspace_id=workspace_id,
            mission_id=mission_id,
            content_sha256=content_sha256,
            relative_path=f"{content_sha256[:2]}/{content_sha256}",
            byte_length=len(content),
            media_type=media_type,
            metadata_sha256=hashlib.sha256(repr(sorted(metadata.items())).encode()).hexdigest(),
            caller_key=caller_key,
            request_id=request_id,
        )
        self.values[(workspace_id, mission_id, record.artifact_id)] = content
        return record

    def read_bytes(
        self, *, workspace_id: str, mission_id: str, artifact_id: str, max_bytes: int
    ) -> bytes:
        self.read_calls += 1
        value = self.values[(workspace_id, mission_id, artifact_id)]
        if len(value) > max_bytes:
            raise RuntimeError("oversized")
        return value


@pytest.fixture
def service(tmp_path):
    audit_authority = FakeAudit()
    store = ControlPlaneV5Store(
        path=tmp_path / "v5.sqlite3",
        source=Authority(),
        key_vault=Vault(),
        state_vault=Vault(),
        pending_vault=Vault(),
        enabled=True,
        audit_reference_verifier=audit_authority.verify,
        semantic_audit_verifier=audit_authority.verify,
    ).initialize()
    artifacts = Artifacts(store)
    audits = []
    calls: list[str] = []

    def runner(tool, args, key):
        calls.append(key)
        return mission_tools.run(tool, args, key)

    def audit(request):
        audits.append(request)
        return audit_authority.write(request)

    value = LocalSystemStatusEvidenceService(
        store=store,
        artifacts=artifacts,
        audit_writer=audit,
        audit_verifier=audit_authority.verify,
        audit_lookup=audit_authority.lookup,
        tool_runner=runner,
    )
    return value, artifacts, audits, calls


def test_real_provider_free_tool_pipeline_and_replay_without_rerun(service):
    value, artifacts, audits, calls = service
    first = value.execute(
        workspace_id="workspace-a",
        mission_id="mission-a",
        caller_key="morning-runtime-status",
    )
    assert first.public_result == mission_tools.run(
        "local_system_status", {}, first.request.idempotency_key
    )
    assert first.public_result["data"]["provider_free"] is True
    assert first.receipt.outcome == "simulated"
    assert first.receipt.postcondition_sha256 != "0" * 64
    assert first.evidence.artifact_id == first.artifact.artifact_id
    assert first.claim.evidence_ids == (first.evidence.evidence_id,)
    assert first.claim.verification_status == "single_source"
    assert first.request.schema_version == 3
    assert first.request.target == "local-runtime"
    assert audits[0].schema_version == first.request.schema_version
    assert action_audit_semantic_contract(audits[0]) == (
        action_audit_semantic_contract(first.request)
    )
    assert first.claim.text is not None
    assert first.evidence.access_and_license_notes == "cyryx-internal-provider-free"
    assert first.evidence.claim_ids == (first.claim.claim_id,)
    assert first.evidence.title == "Onyx local system status observation"
    assert first.receipt.provider_request_id == first.request.request_id
    assert first.receipt.provider_request_ref == (
        f"local-system-status:{first.request.request_id}"
    )
    assert first.receipt.output_ref == f"artifact:{first.artifact.artifact_id}"
    assert first.receipt.verification_ref == (
        f"evidence:{first.evidence.evidence_id}"
    )
    assert first.receipt.after_state_ref == f"claim:{first.claim.claim_id}"
    assert first.receipt.started_at
    assert first.receipt.completed_at
    assert not first.replayed
    assert len(calls) == len(audits) == artifacts.publish_calls == 1

    replay = value.execute(
        workspace_id="workspace-a",
        mission_id="mission-a",
        caller_key="morning-runtime-status",
    )
    assert replay.public_result == first.public_result
    assert replay.request == first.request
    assert replay.receipt == first.receipt
    assert replay.replayed
    assert len(calls) == len(audits) == artifacts.publish_calls == 1
    assert artifacts.read_calls == 1
    value.store.verify_integrity(full=True)


def test_unknown_outcome_never_blindly_reexecutes(tmp_path):
    audit_authority = FakeAudit()
    store = ControlPlaneV5Store(
        path=tmp_path / "v5.sqlite3",
        source=Authority(),
        key_vault=Vault(),
        state_vault=Vault(),
        pending_vault=Vault(),
        enabled=True,
        audit_reference_verifier=audit_authority.verify,
        semantic_audit_verifier=audit_authority.verify,
    ).initialize()
    artifacts = Artifacts(store)
    calls = 0

    def interrupted(_tool, _args, _key):
        nonlocal calls
        calls += 1
        raise RuntimeError("interrupted")

    value = LocalSystemStatusEvidenceService(
        store=store,
        artifacts=artifacts,
        audit_writer=audit_authority.write,
        audit_verifier=audit_authority.verify,
        audit_lookup=audit_authority.lookup,
        tool_runner=interrupted,
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        value.execute(
            workspace_id="workspace-a",
            mission_id="mission-a",
            caller_key="interrupted-status",
        )
    with pytest.raises(ReconciliationRequired) as reconciliation:
        value.execute(
            workspace_id="workspace-a",
            mission_id="mission-a",
            caller_key="interrupted-status",
        )
    assert reconciliation.value.provider_request_id == reconciliation.value.request_id
    assert reconciliation.value.provider_request_ref == (
        f"local-system-status:{reconciliation.value.request_id}"
    )
    assert calls == 1
    assert artifacts.publish_calls == 0


def test_default_off_has_no_audit_tool_or_artifact_side_effect(tmp_path):
    audit_authority = FakeAudit()
    store = ControlPlaneV5Store(
        path=tmp_path / "off.sqlite3",
        source=Authority(),
        key_vault=Vault(),
        state_vault=Vault(),
        enabled=False,
        audit_reference_verifier=audit_authority.verify,
    )
    artifacts = Artifacts(store)
    effects: list[str] = []
    value = LocalSystemStatusEvidenceService(
        store=store,
        artifacts=artifacts,
        audit_writer=lambda request: (
            effects.append("audit")
            or audit_authority.write(request)
        ),
        audit_verifier=audit_authority.verify,
        audit_lookup=audit_authority.lookup,
        tool_runner=lambda *_args: effects.append("tool"),
    )
    with pytest.raises(ControlPlaneV5Disabled):
        value.execute(
            workspace_id="workspace-a",
            mission_id="mission-a",
            caller_key="disabled-status",
        )
    assert effects == []
    assert artifacts.publish_calls == 0
    assert not store.path.exists()


def test_secret_canary_is_rejected_before_artifact(tmp_path):
    audit_authority = FakeAudit()
    store = ControlPlaneV5Store(
        path=tmp_path / "v5.sqlite3",
        source=Authority(),
        key_vault=Vault(),
        state_vault=Vault(),
        pending_vault=Vault(),
        enabled=True,
        audit_reference_verifier=audit_authority.verify,
        semantic_audit_verifier=audit_authority.verify,
    ).initialize()
    artifacts = Artifacts(store)

    def leaking(_tool, _args, _key):
        return {
            "status": "succeeded",
            "data": {
                "provider_free": True,
                "citation": "local-runtime",
                "detail": "api_key=sk-this-must-never-persist",
            },
            "evidence": [{"type": "citation", "value": "local-runtime"}],
            "postconditions": [
                {"name": "runtime_status_observed", "satisfied": True}
            ],
            "waiting_for": None,
        }

    value = LocalSystemStatusEvidenceService(
        store=store,
        artifacts=artifacts,
        audit_writer=audit_authority.write,
        audit_verifier=audit_authority.verify,
        audit_lookup=audit_authority.lookup,
        tool_runner=leaking,
    )
    with pytest.raises(Exception, match="secret-shaped"):
        value.execute(
            workspace_id="workspace-a",
            mission_id="mission-a",
            caller_key="secret-canary",
        )
    assert artifacts.publish_calls == 0
    with pytest.raises(ReconciliationRequired):
        value.execute(
            workspace_id="workspace-a",
            mission_id="mission-a",
            caller_key="secret-canary",
        )
