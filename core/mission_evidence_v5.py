"""Explicit P4.4 wrapper for one provider-free mission tool.

The legacy :func:`core.mission_tools.run` API is unchanged.  This module is a
new, default-off application service that adds request -> audit -> observation
-> artifact -> evidence/claim -> receipt semantics for ``local_system_status``.
It cannot execute any mutation-shaped operation and never calls a provider.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol, runtime_checkable

from core import mission_tools
from core.artifact_service import (
    ArtifactRecord as ByteArtifactRecord,
    ArtifactService as ByteArtifactService,
)
from core.control_plane_v5 import (
    ActionReceipt,
    ActionRequest,
    ActionReservationLease,
    ArtifactRecord,
    Claim,
    ControlPlaneV5Store,
    EvidenceRecord,
    RECORD_SCHEMA_VERSION,
    action_audit_trace_id,
    action_audit_semantic_contract,
    action_request_contract_sha256,
    action_request_identity,
    assert_redacted,
    claim_identity,
    evidence_verification_sha256,
    evidence_identity,
    provider_request_binding_sha256,
    stable_scope_key,
)
from core.tool_audit import (
    append_semantic_tool_audit_reference,
    find_semantic_tool_audit_reference,
    verify_semantic_tool_audit_reference,
)


_TOOL = "local_system_status"
_CONNECTOR = "local_mission_tools"
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_CAS_PROVENANCE = {"kind": "immutable_bytes", "schema_version": 1}
_RESERVATION_WAIT_SECONDS = 5.0
_CONDITIONS_LOCK = threading.Lock()
_PUBLICATION_RECOVERY_TOKEN_BYTES = 32


@dataclass(slots=True)
class _ConditionEntry:
    condition: threading.Condition
    waiters: int = 0


_CONDITIONS: dict[str, _ConditionEntry] = {}


@contextmanager
def _condition_waiter(request_id: str):
    with _CONDITIONS_LOCK:
        entry = _CONDITIONS.get(request_id)
        if entry is None:
            entry = _ConditionEntry(threading.Condition())
            _CONDITIONS[request_id] = entry
        entry.waiters += 1
    try:
        yield entry.condition
    finally:
        with _CONDITIONS_LOCK:
            current = _CONDITIONS.get(request_id)
            if current is entry:
                entry.waiters -= 1
                if entry.waiters == 0:
                    _CONDITIONS.pop(request_id, None)


def _notify(request_id: str) -> None:
    # Notification without a waiter is a no-op and never grows global state.
    with _CONDITIONS_LOCK:
        entry = _CONDITIONS.get(request_id)
    if entry is not None:
        with entry.condition:
            entry.condition.notify_all()


def _note_secondary_failure(
    primary: BaseException, label: str, secondary: BaseException
) -> None:
    try:
        primary.add_note(f"{label} also failed ({type(secondary).__name__})")
    except BaseException:
        pass


def _publication_recovery_digest(token: object) -> str:
    if not isinstance(token, (bytes, bytearray, memoryview)):
        raise MissionEvidenceV5Error("publication recovery token is invalid")
    raw = bytes(token)
    if len(raw) != _PUBLICATION_RECOVERY_TOKEN_BYTES:
        raise MissionEvidenceV5Error("publication recovery token is invalid")
    return _sha(b"ONYX-PUBLICATION-RECOVERY.v1\0" + raw)


def _publication_manifest_ref(publication: ByteArtifactRecord) -> str:
    return f"publication:{publication.manifest_sha256}"


def _publication_binding_ref(token: object) -> str:
    return f"publication-binding:{_publication_recovery_digest(token)}"


class MissionEvidenceV5Error(RuntimeError):
    pass


class ReconciliationRequired(MissionEvidenceV5Error):
    def __init__(
        self,
        request_id: str,
        receipt_id: str,
        *,
        provider_request_id: str | None = None,
        provider_request_ref: str | None = None,
    ):
        super().__init__("the prior observation is unknown/partial; reconcile without retry")
        self.request_id = request_id
        self.receipt_id = receipt_id
        self.provider_request_id = provider_request_id
        self.provider_request_ref = provider_request_ref


class ArtifactRegistrationRequired(MissionEvidenceV5Error):
    """Bytes were published, but their immutable v5 record was not committed."""

    def __init__(
        self, publication: ByteArtifactRecord, recovery_token: bytes
    ):
        super().__init__(
            "artifact bytes are retained and require explicit record reconciliation"
        )
        self.publication = publication
        if len(recovery_token) != _PUBLICATION_RECOVERY_TOKEN_BYTES:
            raise ValueError("recovery_token has an invalid length")
        self.recovery_token = bytes(recovery_token)


class _ArtifactMetadataRegistrationFailure(MissionEvidenceV5Error):
    """Internal marker for a failure inside the metadata commit only."""


@runtime_checkable
class ArtifactPublisher(Protocol):
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
    ) -> ArtifactRecord: ...

    def read_bytes(
        self,
        *,
        workspace_id: str,
        mission_id: str,
        artifact_id: str,
        max_bytes: int,
    ) -> bytes: ...


@dataclass(frozen=True, slots=True)
class MissionEvidenceResult:
    public_result: dict[str, object]
    request: ActionRequest
    receipt: ActionReceipt
    artifact: ArtifactRecord
    evidence: EvidenceRecord
    claim: Claim
    replayed: bool


AuditWriter = Callable[[ActionRequest], str]
AuditLookup = Callable[[ActionRequest], str | None]
ToolRunner = Callable[[str, dict[str, Any], str], Any]


class ControlPlaneArtifactPublisher:
    """Bind the byte service manifest to the single v5 metadata authority."""

    def __init__(
        self, *, store: ControlPlaneV5Store, service: ByteArtifactService
    ) -> None:
        if not isinstance(store, ControlPlaneV5Store):
            raise TypeError("store must be ControlPlaneV5Store")
        if not isinstance(service, ByteArtifactService):
            raise TypeError("service must be ArtifactService")
        self.store = store
        self.service = service

    def _register(
        self,
        *,
        mission_id: str,
        request_id: str,
        publication: ByteArtifactRecord,
        caller_key: str,
    ) -> ArtifactRecord:
        self.service.lookup(publication)
        try:
            stored = self.store.record_artifact(
                workspace_id=publication.workspace_id,
                mission_id=mission_id,
                content_sha256=publication.sha256,
                relative_path=publication.relative_path,
                byte_length=publication.size,
                media_type=publication.media_type,
                metadata_sha256=publication.manifest_sha256,
                caller_key=caller_key,
                artifact_schema_version=publication.schema_version,
                data_class=publication.data_class,
                source_provenance_sha256=publication.source_provenance_sha256,
                display_name=publication.display_name,
                artifact_created_at=publication.created_at,
                status=publication.status,
                manifest_sha256=publication.manifest_sha256,
                request_id=request_id,
            )
        except Exception as exc:
            # Only an ordinary failure *inside* the metadata registration is
            # recoverable as an immutable-publication orphan.  Cancellation,
            # SystemExit and other BaseException subclasses retain identity.
            raise _ArtifactMetadataRegistrationFailure(
                "artifact metadata registration failed"
            ) from exc
        if (
            stored.workspace_id != publication.workspace_id
            or stored.mission_id != mission_id
            or stored.request_id != request_id
            or stored.content_sha256 != publication.sha256
            or stored.relative_path != publication.relative_path
            or stored.byte_length != publication.size
            or stored.media_type != publication.media_type
            or stored.artifact_schema_version != publication.schema_version
            or stored.data_class != publication.data_class
            or stored.source_provenance_sha256
            != publication.source_provenance_sha256
            or stored.display_name != publication.display_name
            or stored.artifact_created_at != publication.created_at
            or stored.status != publication.status
            or stored.manifest_sha256 != publication.manifest_sha256
        ):
            raise MissionEvidenceV5Error("artifact manifest and v5 record diverge")
        return stored

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
        if workspace_id != self.service.workspace_id:
            raise MissionEvidenceV5Error("artifact service workspace diverges")
        if not isinstance(metadata, dict):
            raise MissionEvidenceV5Error("logical artifact metadata must be an object")
        publication = self.service.publish_bytes(
            content,
            media_type=media_type,
            data_class="internal",
            source_provenance=_CAS_PROVENANCE,
            display_name=None,
        )
        try:
            return self._register(
                mission_id=mission_id,
                request_id=request_id,
                publication=publication,
                caller_key=caller_key,
            )
        except _ArtifactMetadataRegistrationFailure as exc:
            # Publication is content-addressed and immutable.  Never delete it
            # after an uncertain metadata commit; return its exact manifest so
            # an explicit reconciliation can verify and register it later.
            raise ArtifactRegistrationRequired(
                publication, secrets.token_bytes(_PUBLICATION_RECOVERY_TOKEN_BYTES)
            ) from exc.__cause__

    def reconcile_publication(
        self,
        *,
        mission_id: str,
        request_id: str,
        publication: ByteArtifactRecord,
        caller_key: str,
    ) -> ArtifactRecord:
        return self._register(
            mission_id=mission_id,
            request_id=request_id,
            publication=publication,
            caller_key=caller_key,
        )

    def read_bytes(
        self,
        *,
        workspace_id: str,
        mission_id: str,
        artifact_id: str,
        max_bytes: int,
    ) -> bytes:
        if workspace_id != self.service.workspace_id:
            raise MissionEvidenceV5Error("artifact service workspace diverges")
        stored = self.store.get_artifact(
            workspace_id=workspace_id,
            mission_id=mission_id,
            artifact_id=artifact_id,
        )
        if stored.byte_length > max_bytes:
            raise MissionEvidenceV5Error("artifact exceeds the requested read bound")
        publication = ByteArtifactRecord(
            schema_version=stored.artifact_schema_version,
            artifact_id=_publication_identity(workspace_id, stored.content_sha256),
            workspace_id=stored.workspace_id,
            sha256=stored.content_sha256,
            relative_path=stored.relative_path,
            media_type=stored.media_type,
            data_class=stored.data_class,
            source_provenance_sha256=stored.source_provenance_sha256,
            display_name=stored.display_name,
            size=stored.byte_length,
            created_at=stored.artifact_created_at,
            status=stored.status,
        )
        if publication.manifest_sha256 != stored.manifest_sha256:
            raise MissionEvidenceV5Error("stored artifact manifest digest diverges")
        return self.service.read(publication)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise MissionEvidenceV5Error("provider-free result is not canonical JSON") from exc


def _sha(value: bytes | str) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _publication_identity(workspace_id: str, content_sha256: str) -> str:
    """Mirror the ArtifactService v1 CAS identity with fixed-vector coverage."""

    return "artifact-" + _sha(
        _canonical(["OnyxArtifact.v1", workspace_id, content_sha256])
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_audit_writer(request: ActionRequest) -> str:
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
    trace_id = action_audit_trace_id(
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
    contract = action_audit_semantic_contract(request)
    reference = append_semantic_tool_audit_reference(
        contract=contract,
        reason="explicit provider-free P4.4 observation",
    )
    if reference.trace_id != trace_id or not verify_semantic_tool_audit_reference(
        contract=contract, event_hash=reference.event_hash
    ):
        raise MissionEvidenceV5Error("tool audit membership diverged after append")
    return reference.event_hash


def _default_audit_lookup(request: ActionRequest) -> str | None:
    reference = find_semantic_tool_audit_reference(
        contract=action_audit_semantic_contract(request)
    )
    return None if reference is None else reference.event_hash


def _validate_public_result(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise MissionEvidenceV5Error("provider-free tool returned a non-object")
    if set(value) != {
        "status", "data", "evidence", "postconditions", "waiting_for"
    }:
        raise MissionEvidenceV5Error("provider-free tool result shape diverges")
    if value.get("status") != "succeeded" or value.get("waiting_for") is not None:
        raise MissionEvidenceV5Error("provider-free observation did not succeed")
    data = value.get("data")
    if not isinstance(data, dict) or data.get("provider_free") is not True:
        raise MissionEvidenceV5Error("provider-free marker is missing")
    postconditions = value.get("postconditions")
    if (
        not isinstance(postconditions, list)
        or len(postconditions) != 1
        or not isinstance(postconditions[0], dict)
        or postconditions[0].get("name") != "runtime_status_observed"
        or postconditions[0].get("satisfied") is not True
    ):
        raise MissionEvidenceV5Error("runtime postcondition was not observed")
    evidence = value.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise MissionEvidenceV5Error("provider-free observation has no citation")
    assert_redacted(value, "provider-free result")
    _canonical(value)
    return value


class LocalSystemStatusEvidenceService:
    """One-tool P4.4 vertical slice with stable replay and fail-closed unknowns."""

    def __init__(
        self,
        *,
        store: ControlPlaneV5Store,
        artifacts: ArtifactPublisher,
        audit_writer: AuditWriter = _default_audit_writer,
        audit_verifier: Callable[[ActionRequest, str], bool] = lambda request, event_hash: verify_semantic_tool_audit_reference(
            contract=action_audit_semantic_contract(request), event_hash=event_hash
        ),
        audit_lookup: AuditLookup = _default_audit_lookup,
        tool_runner: ToolRunner = mission_tools.run,
        reservation_lease_seconds: int = 30,
    ):
        if not isinstance(store, ControlPlaneV5Store):
            raise TypeError("store must be ControlPlaneV5Store")
        if not isinstance(artifacts, ArtifactPublisher):
            raise TypeError("artifacts must implement ArtifactPublisher")
        if (
            not callable(audit_writer)
            or not callable(audit_verifier)
            or not callable(audit_lookup)
            or not callable(tool_runner)
        ):
            raise TypeError(
                "audit_writer, audit_verifier, audit_lookup and tool_runner must be callable"
            )
        self.store = store
        self.artifacts = artifacts
        self.audit_writer = audit_writer
        self.audit_verifier = audit_verifier
        self.audit_lookup = audit_lookup
        self.tool_runner = tool_runner
        if (
            type(reservation_lease_seconds) is not int
            or not 1 <= reservation_lease_seconds <= 300
        ):
            raise ValueError("reservation_lease_seconds is invalid")
        self.reservation_lease_seconds = reservation_lease_seconds
        self._lock = threading.RLock()

    @staticmethod
    def _keys(caller_key: str) -> tuple[str, str, str, str]:
        seed = _sha("ONYX-P4.4-LOCAL-STATUS\0" + caller_key)
        return (
            "artifact-" + seed[:48],
            "evidence-" + seed[:48],
            "claim-" + seed[:48],
            "receipt-" + seed[:48],
        )

    def _request(
        self, *, workspace_id: str, mission_id: str, caller_key: str
    ) -> tuple[ActionRequest, ActionReservationLease]:
        idempotency_key = stable_scope_key(
            workspace_id=workspace_id,
            mission_id=mission_id,
            operation=_TOOL,
            caller_key=caller_key,
        )
        request_id = action_request_identity(idempotency_key)
        existing = self.store.find_action_request(
            workspace_id=workspace_id,
            mission_id=mission_id,
            request_id=request_id,
        )
        if existing is not None:
            existing_sha256 = action_request_contract_sha256(
                workspace_id=existing.workspace_id,
                mission_id=existing.mission_id,
                request_id=existing.request_id,
                correlation_id=existing.correlation_id,
                connector=existing.connector,
                operation=existing.operation,
                target_sha256=existing.target_sha256,
                payload_sha256=existing.payload_sha256,
                idempotency_key=existing.idempotency_key,
                risk=existing.risk,
                approval_policy=existing.approval_policy,
                dry_run=existing.dry_run,
                verification_plan_sha256=existing.verification_plan_sha256,
                source_context_sha256=existing.source_context_sha256,
                target=existing.target,
                approval_id=existing.approval_id,
                schema_version=existing.schema_version,
            )
            lease = self.store.reserve_action_request(
                workspace_id=workspace_id, mission_id=mission_id,
                idempotency_key=idempotency_key,
                request_sha256=existing_sha256,
                lease_seconds=self.reservation_lease_seconds,
            )
            return existing, lease
        scope = self.store.mission_scope(
            workspace_id=workspace_id, mission_id=mission_id
        )
        proposed = ActionRequest(
            schema_version=RECORD_SCHEMA_VERSION,
            request_id=request_id,
            workspace_id=workspace_id,
            mission_id=mission_id,
            correlation_id=scope.correlation_id,
            connector=_CONNECTOR,
            operation=_TOOL,
            target_sha256=_sha("local-runtime"),
            payload_sha256=_sha(b"{}"),
            idempotency_key=idempotency_key,
            risk="low",
            approval_policy="shadow_only",
            dry_run=True,
            audit_reference_sha256="0" * 64,
            verification_plan_sha256=_sha("runtime_status_observed"),
            source_context_sha256=scope.context_sha256,
            created_at=_now(),
            target="local-runtime",
            approval_id=None,
        )
        request_sha256 = action_request_contract_sha256(
            workspace_id=proposed.workspace_id,
            mission_id=proposed.mission_id,
            request_id=proposed.request_id,
            correlation_id=proposed.correlation_id,
            connector=proposed.connector,
            operation=proposed.operation,
            target_sha256=proposed.target_sha256,
            payload_sha256=proposed.payload_sha256,
            idempotency_key=proposed.idempotency_key,
            risk=proposed.risk,
            approval_policy=proposed.approval_policy,
            dry_run=proposed.dry_run,
            verification_plan_sha256=proposed.verification_plan_sha256,
            source_context_sha256=proposed.source_context_sha256,
            target=proposed.target,
            approval_id=proposed.approval_id,
            schema_version=proposed.schema_version,
        )
        lease = self.store.reserve_action_request(
            workspace_id=workspace_id,
            mission_id=mission_id,
            idempotency_key=idempotency_key,
            request_sha256=request_sha256,
            lease_seconds=self.reservation_lease_seconds,
        )
        if not lease:
            with _condition_waiter(request_id) as condition:
                existing = self.store.find_action_request(
                    workspace_id=workspace_id,
                    mission_id=mission_id,
                    request_id=request_id,
                )
                if existing is None:
                    with condition:
                        condition.wait(timeout=_RESERVATION_WAIT_SECONDS)
                    existing = self.store.find_action_request(
                        workspace_id=workspace_id,
                        mission_id=mission_id,
                        request_id=request_id,
                    )
            if existing is None:
                raise ReconciliationRequired(request_id, "reservation-pending")
            return existing, lease
        audit_reference = lease.audit_reference_sha256
        if audit_reference is None:
            audit_reference = self.audit_lookup(proposed)
        if audit_reference is None:
            try:
                audit_reference = self.audit_writer(proposed)
            except BaseException as primary:
                recovered: str | None = None
                lookup_succeeded = False
                try:
                    recovered = self.audit_lookup(proposed)
                    lookup_succeeded = True
                except BaseException as secondary:
                    _note_secondary_failure(
                        primary, "audit lookup during writer recovery", secondary
                    )
                if lookup_succeeded and recovered is None:
                    try:
                        self.store.abandon_pre_audit_reservation(
                            workspace_id=workspace_id,
                            mission_id=mission_id,
                            request_id=request_id,
                            owner_id=lease.owner_id,
                        )
                    except BaseException as secondary:
                        _note_secondary_failure(
                            primary, "pre-audit reservation abandonment", secondary
                        )
                elif lookup_succeeded:
                    try:
                        self.store.link_action_audit(
                            workspace_id=workspace_id,
                            mission_id=mission_id,
                            request_id=request_id,
                            owner_id=lease.owner_id,
                            audit_reference_sha256=str(recovered),
                            request_sha256=request_sha256,
                            idempotency_key=proposed.idempotency_key,
                            connector=proposed.connector,
                            operation=proposed.operation,
                            target=str(proposed.target),
                            target_sha256=proposed.target_sha256,
                            payload_sha256=proposed.payload_sha256,
                            risk=proposed.risk,
                            approval_policy=proposed.approval_policy,
                            dry_run=proposed.dry_run,
                            source_context_sha256=proposed.source_context_sha256,
                            verification_plan_sha256=proposed.verification_plan_sha256,
                            approval_id=proposed.approval_id,
                        )
                    except BaseException as secondary:
                        _note_secondary_failure(
                            primary, "audit link during writer recovery", secondary
                        )
                try:
                    _notify(request_id)
                except BaseException as secondary:
                    _note_secondary_failure(
                        primary, "request notification during writer recovery", secondary
                    )
                raise
        if (
            not isinstance(audit_reference, str)
            or not re.fullmatch(r"[0-9a-f]{64}", audit_reference)
            or audit_reference == "0" * 64
        ):
            if self.audit_lookup(proposed) is None:
                self.store.abandon_pre_audit_reservation(
                    workspace_id=workspace_id, mission_id=mission_id,
                    request_id=request_id, owner_id=lease.owner_id,
                )
            raise MissionEvidenceV5Error("tool audit returned an invalid event reference")
        try:
            audit_member = self.audit_verifier(proposed, audit_reference)
        except Exception as exc:
            raise MissionEvidenceV5Error(
                "tool audit membership verification failed"
            ) from exc
        if audit_member is not True:
            if self.audit_lookup(proposed) is None:
                self.store.abandon_pre_audit_reservation(
                    workspace_id=workspace_id, mission_id=mission_id,
                    request_id=request_id, owner_id=lease.owner_id,
                )
            raise MissionEvidenceV5Error(
                "tool audit reference is not a verified chain member"
            )
        self.store.link_action_audit(
            workspace_id=workspace_id,
            mission_id=mission_id,
            request_id=request_id,
            owner_id=lease.owner_id,
            audit_reference_sha256=audit_reference,
            request_sha256=request_sha256,
            idempotency_key=proposed.idempotency_key,
            connector=proposed.connector,
            operation=proposed.operation,
            target=str(proposed.target),
            target_sha256=proposed.target_sha256,
            payload_sha256=proposed.payload_sha256,
            risk=proposed.risk,
            approval_policy=proposed.approval_policy,
            dry_run=proposed.dry_run,
            source_context_sha256=proposed.source_context_sha256,
            verification_plan_sha256=proposed.verification_plan_sha256,
            approval_id=proposed.approval_id,
        )
        request = self.store.record_action_request(
            workspace_id=workspace_id,
            mission_id=mission_id,
            connector=_CONNECTOR,
            operation=_TOOL,
            target="local-runtime",
            target_sha256=_sha("local-runtime"),
            payload_sha256=_sha(b"{}"),
            idempotency_key=idempotency_key,
            risk="low",
            approval_policy="shadow_only",
            dry_run=True,
            audit_reference_sha256=audit_reference,
            verification_plan_sha256=_sha("runtime_status_observed"),
            reservation_owner_id=lease.owner_id,
            approval_id=None,
        )
        return request, lease

    def _replay(
        self,
        *,
        workspace_id: str,
        mission_id: str,
        caller_key: str,
        request: ActionRequest,
        receipt: ActionReceipt,
    ) -> MissionEvidenceResult:
        if receipt.outcome in {"unknown", "partial"}:
            raise ReconciliationRequired(
                request.request_id,
                receipt.receipt_id,
                provider_request_id=receipt.provider_request_id,
                provider_request_ref=receipt.provider_request_ref,
            )
        if receipt.outcome != "simulated":
            raise MissionEvidenceV5Error("the prior terminal observation did not succeed")
        evidence_key = "evidence-" + _sha(caller_key)[:48]
        claim_key = "claim-" + _sha(caller_key)[:48]
        evidence = self.store.get_evidence(
            workspace_id=workspace_id,
            mission_id=mission_id,
            evidence_id=evidence_identity(
                workspace_id=workspace_id,
                mission_id=mission_id,
                caller_key=evidence_key,
            ),
        )
        if evidence.artifact_id is None:
            raise MissionEvidenceV5Error("completed observation has no artifact")
        artifact = self.store.get_artifact(
            workspace_id=workspace_id,
            mission_id=mission_id,
            artifact_id=evidence.artifact_id,
        )
        raw = self.artifacts.read_bytes(
            workspace_id=workspace_id,
            mission_id=mission_id,
            artifact_id=artifact.artifact_id,
            max_bytes=64 * 1024,
        )
        if _sha(raw) != artifact.content_sha256 or _sha(raw) != receipt.output_sha256:
            raise MissionEvidenceV5Error("replayed artifact digest diverges")
        try:
            decoded = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MissionEvidenceV5Error("replayed artifact is corrupt") from exc
        public_result = _validate_public_result(decoded)
        claim = self.store.get_claim(
            workspace_id=workspace_id,
            mission_id=mission_id,
            claim_id=claim_identity(
                workspace_id=workspace_id,
                mission_id=mission_id,
                caller_key=claim_key,
            ),
        )
        return MissionEvidenceResult(
            public_result, request, receipt, artifact, evidence, claim, True
        )

    def execute(
        self, *, workspace_id: str, mission_id: str, caller_key: str
    ) -> MissionEvidenceResult:
        with self._lock:
            return self._execute_locked(
                workspace_id=workspace_id,
                mission_id=mission_id,
                caller_key=caller_key,
            )

    def _execute_locked(
        self, *, workspace_id: str, mission_id: str, caller_key: str
    ) -> MissionEvidenceResult:
        request, lease = self._request(
            workspace_id=workspace_id, mission_id=mission_id, caller_key=caller_key
        )
        prior = self.store.latest_action_receipt(
            workspace_id=workspace_id,
            mission_id=mission_id,
            request_id=request.request_id,
        )
        if prior is not None:
            return self._replay(
                workspace_id=workspace_id,
                mission_id=mission_id,
                caller_key=caller_key,
                request=request,
                receipt=prior,
            )
        if not lease:
            with _condition_waiter(request.request_id) as condition:
                with condition:
                    condition.wait(timeout=_RESERVATION_WAIT_SECONDS)
            prior = self.store.latest_action_receipt(
                workspace_id=workspace_id,
                mission_id=mission_id,
                request_id=request.request_id,
            )
            if prior is None:
                raise ReconciliationRequired(request.request_id, "reservation-pending")
            return self._replay(
                workspace_id=workspace_id,
                mission_id=mission_id,
                caller_key=caller_key,
                request=request,
                receipt=prior,
            )

        dispatched = False
        observed: dict[str, object] | None = None
        artifact: ArtifactRecord | None = None
        evidence: EvidenceRecord | None = None
        claim: Claim | None = None
        started_at = _now()
        provider_request_id = request.request_id
        provider_request_ref = f"local-system-status:{request.request_id}"
        try:
            self.store.mark_action_dispatch_unknown(
                workspace_id=workspace_id,
                mission_id=mission_id,
                request_id=request.request_id,
                owner_id=lease.owner_id,
            )
            dispatched = True
            observed = _validate_public_result(
                self.tool_runner(_TOOL, {}, request.idempotency_key)
            )
            raw = _canonical(observed)
            content_sha256 = _sha(raw)
            artifact_key = "artifact-" + _sha(caller_key)[:48]
            artifact = self.artifacts.publish(
                workspace_id=workspace_id,
                mission_id=mission_id,
                request_id=request.request_id,
                content=raw,
                media_type="application/json",
                metadata={
                    "schema_version": 1,
                    "kind": "mission_result_binding",
                },
                caller_key=artifact_key,
            )
            if (
                artifact.workspace_id != workspace_id
                or artifact.mission_id != mission_id
                or artifact.content_sha256 != content_sha256
                or artifact.relative_path
                != f"{content_sha256[:2]}/{content_sha256}"
                or artifact.byte_length != len(raw)
                or artifact.media_type != "application/json"
            ):
                raise MissionEvidenceV5Error(
                    "artifact service returned a divergent scope/manifest"
                )
            evidence_key = "evidence-" + _sha(caller_key)[:48]
            evidence = self.store.record_evidence(
                workspace_id=workspace_id,
                mission_id=mission_id,
                source_kind="tool_output",
                source_identity_sha256=_sha("core.mission_tools:local_system_status"),
                content_sha256=content_sha256,
                artifact_id=artifact.artifact_id,
                credibility_bp=10000,
                freshness="current",
                access_license_sha256=_sha("cyryx-internal-provider-free"),
                observed_at=_now(),
                caller_key=evidence_key,
                title="Onyx local system status observation",
                uri_or_file_ref=f"artifact:{artifact.artifact_id}",
                publisher_or_owner="Cyryx Labs Onyx local runtime",
                published_at=None,
                access_and_license_notes="cyryx-internal-provider-free",
            )
            verification_sha256 = evidence_verification_sha256(evidence)
            claim_text = _canonical(observed["postconditions"]).decode("ascii")
            postcondition_sha256 = _sha(claim_text)
            claim_key = "claim-" + _sha(caller_key)[:48]
            claim = self.store.record_claim(
                workspace_id=workspace_id,
                mission_id=mission_id,
                claim_kind="fact",
                statement_sha256=postcondition_sha256,
                evidence_ids=(evidence.evidence_id,),
                confidence_bp=10000,
                verification_status="single_source",
                valid_until=None,
                contradiction_claim_ids=(),
                caller_key=claim_key,
                text=claim_text,
                verified_at=_now(),
                valid_from=started_at,
            )
            evidence = self.store.get_evidence(
                workspace_id=workspace_id,
                mission_id=mission_id,
                evidence_id=evidence.evidence_id,
            )
            completed_at = _now()
            receipt = self.store.record_action_receipt(
                workspace_id=workspace_id,
                mission_id=mission_id,
                request_id=request.request_id,
                outcome="simulated",
                provider_request_sha256=provider_request_binding_sha256(
                    provider_request_id, provider_request_ref
                ),
                output_sha256=content_sha256,
                verification_sha256=verification_sha256,
                postcondition_sha256=postcondition_sha256,
                error_class="",
                supersedes_receipt_id=None,
                reconciliation=False,
                observed_at=_now(),
                caller_key="receipt-" + _sha(caller_key)[:48],
                provider_request_id=provider_request_id,
                provider_request_ref=provider_request_ref,
                started_at=started_at,
                completed_at=completed_at,
                before_state_ref=None,
                after_state_ref=f"claim:{claim.claim_id}",
                output_ref=f"artifact:{artifact.artifact_id}",
                verification_ref=f"evidence:{evidence.evidence_id}",
                rollback_ref=None,
            )
            result = MissionEvidenceResult(
                observed, request, receipt, artifact, evidence, claim, False
            )
            _notify(request.request_id)
            return result
        except BaseException as primary:
            # If no receipt exists, preserve an observed failure before dispatch,
            # or an unknown result after dispatch/publication may have begun.
            prior_lookup_succeeded = False
            prior_receipt = None
            try:
                prior_receipt = self.store.latest_action_receipt(
                    workspace_id=workspace_id,
                    mission_id=mission_id,
                    request_id=request.request_id,
                )
                prior_lookup_succeeded = True
            except BaseException as secondary:
                _note_secondary_failure(
                    primary, "receipt lookup during failure cleanup", secondary
                )
            if prior_lookup_succeeded and prior_receipt is None:
                if dispatched:
                    try:
                        retained_publication = (
                            primary.publication
                            if isinstance(primary, ArtifactRegistrationRequired)
                            else None
                        )
                        recovery_token = (
                            primary.recovery_token
                            if isinstance(primary, ArtifactRegistrationRequired)
                            else None
                        )
                        self.store.record_action_receipt(
                        workspace_id=workspace_id,
                        mission_id=mission_id,
                        request_id=request.request_id,
                        outcome="unknown",
                        provider_request_sha256=provider_request_binding_sha256(
                            provider_request_id, provider_request_ref
                        ),
                        output_sha256=(
                            retained_publication.sha256
                            if retained_publication is not None
                            else (
                                _sha(_canonical(observed))
                                if observed is not None
                                else _EMPTY_SHA256
                            )
                        ),
                        verification_sha256=(
                            evidence_verification_sha256(evidence)
                            if evidence is not None
                            else _EMPTY_SHA256
                        ),
                        postcondition_sha256=_EMPTY_SHA256,
                        error_class="observation_interrupted",
                        supersedes_receipt_id=None,
                        reconciliation=False,
                        observed_at=_now(),
                        caller_key="failure-" + _sha(caller_key)[:48],
                        provider_request_id=provider_request_id,
                        provider_request_ref=provider_request_ref,
                        started_at=started_at,
                        completed_at=None,
                        before_state_ref=None,
                        after_state_ref=(
                            f"claim:{claim.claim_id}" if claim is not None else None
                        ),
                        output_ref=(
                            _publication_manifest_ref(retained_publication)
                            if retained_publication is not None
                            else (
                                f"artifact:{artifact.artifact_id}"
                                if artifact is not None
                                else None
                            )
                        ),
                        verification_ref=(
                            f"evidence:{evidence.evidence_id}"
                            if evidence is not None else None
                        ),
                        rollback_ref=(
                            _publication_binding_ref(recovery_token)
                            if recovery_token is not None
                            else None
                        ),
                    )
                    except BaseException as secondary:
                        _note_secondary_failure(
                            primary, "unknown receipt persistence", secondary
                        )
            try:
                _notify(request.request_id)
            except BaseException as secondary:
                _note_secondary_failure(primary, "request notification", secondary)
            raise

    def reconcile_published_artifact(
        self,
        *,
        workspace_id: str,
        mission_id: str,
        caller_key: str,
        publication: ByteArtifactRecord,
        recovery_token: bytes,
    ) -> MissionEvidenceResult:
        """Reconcile retained bytes after an unknown metadata-registration outcome.

        This observes the exact immutable publication and never dispatches the
        mission tool a second time.
        """

        with self._lock:
            request, _owns_reservation = self._request(
                workspace_id=workspace_id,
                mission_id=mission_id,
                caller_key=caller_key,
            )
            prior = self.store.latest_action_receipt(
                workspace_id=workspace_id,
                mission_id=mission_id,
                request_id=request.request_id,
            )
            if prior is None or prior.outcome not in {"unknown", "partial"}:
                raise MissionEvidenceV5Error(
                    "request does not have an unknown/partial outcome to reconcile"
                )
            if (
                prior.output_sha256 == _EMPTY_SHA256
                or prior.output_sha256 != publication.sha256
            ):
                raise MissionEvidenceV5Error(
                    "publication digest does not match the interrupted request output"
                )
            expected_manifest_ref = _publication_manifest_ref(publication)
            expected_binding_ref = _publication_binding_ref(recovery_token)
            if (
                prior.output_ref != expected_manifest_ref
                or not isinstance(prior.rollback_ref, str)
                or not hmac.compare_digest(
                    prior.rollback_ref, expected_binding_ref
                )
            ):
                raise MissionEvidenceV5Error(
                    "retained publication does not match the original request binding"
                )
            reconcile = getattr(self.artifacts, "reconcile_publication", None)
            if not callable(reconcile):
                raise MissionEvidenceV5Error(
                    "artifact publisher cannot reconcile retained publications"
                )
            artifact_key = "artifact-" + _sha(caller_key)[:48]
            artifact = reconcile(
                mission_id=mission_id,
                request_id=request.request_id,
                publication=publication,
                caller_key=artifact_key,
            )
            raw = self.artifacts.read_bytes(
                workspace_id=workspace_id,
                mission_id=mission_id,
                artifact_id=artifact.artifact_id,
                max_bytes=64 * 1024,
            )
            if _sha(raw) != publication.sha256 or _sha(raw) != artifact.content_sha256:
                raise MissionEvidenceV5Error("reconciled artifact digest diverges")
            try:
                decoded = json.loads(raw.decode("ascii"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise MissionEvidenceV5Error("reconciled artifact is corrupt") from exc
            observed = _validate_public_result(decoded)
            evidence_key = "evidence-" + _sha(caller_key)[:48]
            evidence = self.store.record_evidence(
                workspace_id=workspace_id,
                mission_id=mission_id,
                source_kind="tool_output",
                source_identity_sha256=_sha(
                    "core.mission_tools:local_system_status"
                ),
                content_sha256=artifact.content_sha256,
                artifact_id=artifact.artifact_id,
                credibility_bp=10000,
                freshness="current",
                access_license_sha256=_sha("cyryx-internal-provider-free"),
                observed_at=_now(),
                caller_key=evidence_key,
                title="Onyx local system status observation",
                uri_or_file_ref=f"artifact:{artifact.artifact_id}",
                publisher_or_owner="Cyryx Labs Onyx local runtime",
                published_at=None,
                access_and_license_notes="cyryx-internal-provider-free",
            )
            verification_sha256 = evidence_verification_sha256(evidence)
            claim_text = _canonical(observed["postconditions"]).decode("ascii")
            postcondition_sha256 = _sha(claim_text)
            claim_key = "claim-" + _sha(caller_key)[:48]
            claim = self.store.record_claim(
                workspace_id=workspace_id,
                mission_id=mission_id,
                claim_kind="fact",
                statement_sha256=postcondition_sha256,
                evidence_ids=(evidence.evidence_id,),
                confidence_bp=10000,
                verification_status="single_source",
                valid_until=None,
                contradiction_claim_ids=(),
                caller_key=claim_key,
                text=claim_text,
                verified_at=_now(),
                valid_from=prior.started_at,
            )
            evidence = self.store.get_evidence(
                workspace_id=workspace_id,
                mission_id=mission_id,
                evidence_id=evidence.evidence_id,
            )
            completed_at = _now()
            receipt = self.store.record_action_receipt(
                workspace_id=workspace_id,
                mission_id=mission_id,
                request_id=request.request_id,
                outcome="simulated",
                provider_request_sha256=provider_request_binding_sha256(
                    str(prior.provider_request_id), str(prior.provider_request_ref)
                ),
                output_sha256=artifact.content_sha256,
                verification_sha256=verification_sha256,
                postcondition_sha256=postcondition_sha256,
                error_class="",
                supersedes_receipt_id=prior.receipt_id,
                reconciliation=True,
                observed_at=_now(),
                caller_key="reconciled-" + _sha(caller_key)[:48],
                provider_request_id=prior.provider_request_id,
                provider_request_ref=prior.provider_request_ref,
                started_at=prior.started_at,
                completed_at=completed_at,
                before_state_ref=prior.before_state_ref,
                after_state_ref=f"claim:{claim.claim_id}",
                output_ref=f"artifact:{artifact.artifact_id}",
                verification_ref=f"evidence:{evidence.evidence_id}",
                rollback_ref=None,
            )
            return MissionEvidenceResult(
                observed, request, receipt, artifact, evidence, claim, True
            )


__all__ = [
    "ArtifactPublisher",
    "ArtifactRegistrationRequired",
    "ControlPlaneArtifactPublisher",
    "LocalSystemStatusEvidenceService",
    "MissionEvidenceResult",
    "MissionEvidenceV5Error",
    "ReconciliationRequired",
]
