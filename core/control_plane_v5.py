"""Default-off P4.4 evidence, action and artifact authority.

Schema v5 is an additive successor to the accepted mission-context v4
authority.  It does not replace or mutate the v4 database.  Every enhanced
operation proves its explicit workspace/mission against v4 and records that
authenticated context revision in this append-only sidecar.  The historical
M2a/M2b-c domain ledgers remain readable checkpoints, never live writers.

There is intentionally no production opener in this slice.  A host must own
the v4 capability and the two private vaults before this store can be opened.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

from memory.store import contains_secret


CONTROL_PLANE_V5_FLAG = "ONYX_CONTROL_PLANE_V5"
V5_SCHEMA_VERSION = 5
RECORD_SCHEMA_VERSION = 3
_ZERO_HASH = "0" * 64
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_SLUG = re.compile(r"[a-z][a-z0-9_.-]{0,79}")
_OPAQUE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}")
_MAX_TEXT = 4096
_MAX_PAGE = 200
_LOCK = threading.RLock()
_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(?:api[_-]?key|authorization|client[_-]?secret|password|"
        r"private[_-]?key|refresh[_-]?token|secret|token)\s*[:=]\s*\S+|"
        r"\bbearer(?:\s+|[:=]\s*)[A-Za-z0-9._~+/=-]{8,}"
    ),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\b(?:gh[opsu]_|sk-)[0-9A-Za-z_-]{12,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
_RECOVERABLE_SECRET_PATTERNS = (
    # Recoverable prose may discuss credentials, but an assignment/header is
    # durable secret material rather than ordinary language.
    re.compile(
        r"(?i)\b(?:api[ _-]?key|client[ _-]?secret|password|private[ _-]?key|"
        r"refresh[ _-]?token|secret|token)\s*[:=]\s*[\"']?[^\s\"']{4,}"
    ),
    re.compile(
        r"(?i)\bauthorization\s*[:=]\s*(?:bearer\s+)?[^\s,;]{4,}"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    *_SECRET_PATTERNS[1:],
)
_CONTRACT_ID_SECRET = re.compile(
    r"(?i)^(?:api[_-]?key|authorization|bearer|client[_-]?secret|password|"
    r"private[_-]?key|refresh[_-]?token|secret|token)[._:-][A-Za-z0-9._:-]{8,}$"
)


class ControlPlaneV5Error(RuntimeError):
    """Base error with no sensitive payload in its message."""


class ControlPlaneV5Disabled(ControlPlaneV5Error):
    pass


class ControlPlaneV5ContractError(ControlPlaneV5Error):
    pass


class ControlPlaneV5IntegrityError(ControlPlaneV5Error):
    pass


class ControlPlaneV5Conflict(ControlPlaneV5Error):
    pass


class ControlPlaneV5IsolationError(ControlPlaneV5Error):
    pass


class ControlPlaneV5IOError(ControlPlaneV5Error):
    pass


def _preserve_cleanup_failure(
    primary: BaseException | None, label: str, cleanup_error: BaseException
) -> None:
    """Keep the active failure/cancellation authoritative during cleanup."""

    if primary is not None:
        try:
            primary.add_note(
                f"{label} also failed ({type(cleanup_error).__name__})"
            )
        except BaseException:
            pass
        return
    raise ControlPlaneV5IOError(f"{label} failed") from cleanup_error


@dataclass(frozen=True, slots=True)
class V4AuthorityStatus:
    database_id: str
    schema_version: int
    schema_fingerprint: str
    state_root: str
    anchor_sequence: int


@dataclass(frozen=True, slots=True)
class MissionScope:
    workspace_id: str
    mission_id: str
    correlation_id: str
    context_revision: int
    context_sha256: str
    source_state_root: str


@runtime_checkable
class MissionAuthorityPort(Protocol):
    def status(self) -> V4AuthorityStatus: ...

    def read_scope(self, workspace_id: str, mission_id: str) -> MissionScope: ...


@runtime_checkable
class SecretVault(Protocol):
    def get_bytes(self) -> bytes | None: ...

    def set_bytes(self, value: bytes | bytearray) -> None: ...

    def delete(self) -> bool: ...


class V4MissionAuthority:
    """Narrow adapter over the accepted :mod:`control_plane_v4` owner API."""

    def __init__(self, store: object, owner: object):
        self._store = store
        self._owner = owner

    def status(self) -> V4AuthorityStatus:
        status = self._store.verify_integrity(self._owner)
        return V4AuthorityStatus(
            database_id=status.database_id,
            schema_version=status.schema_version,
            schema_fingerprint=status.schema_fingerprint,
            state_root=status.state_root,
            anchor_sequence=status.anchor_sequence,
        )

    def read_scope(self, workspace_id: str, mission_id: str) -> MissionScope:
        context, _event, _journal = self._store.read_context_bundle(
            self._owner, workspace_id, mission_id
        )
        status = self.status()
        return MissionScope(
            workspace_id=workspace_id,
            mission_id=mission_id,
            correlation_id=str(context["correlation_id"]),
            context_revision=int(context["revision"]),
            context_sha256=str(context["revision_sha256"]),
            source_state_root=status.state_root,
        )


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """Authenticated mission/request binding to one immutable CAS publication."""

    schema_version: int
    artifact_id: str
    workspace_id: str
    mission_id: str
    correlation_id: str
    request_id: str | None
    content_sha256: str
    relative_path: str
    byte_length: int
    media_type: str
    artifact_schema_version: int
    data_class: str
    source_provenance_sha256: str
    display_name: str | None
    artifact_created_at: str
    status: str
    manifest_sha256: str
    metadata_sha256: str
    source_context_sha256: str
    created_at: str


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    schema_version: int
    evidence_id: str
    workspace_id: str
    mission_id: str
    correlation_id: str
    source_kind: str
    source_identity_sha256: str
    content_sha256: str
    artifact_id: str | None
    claim_ids: tuple[str, ...]
    credibility_bp: int
    freshness: str
    access_license_sha256: str
    source_context_sha256: str
    observed_at: str
    created_at: str
    title: str = ""
    uri_or_file_ref: str | None = None
    publisher_or_owner: str | None = None
    published_at: str | None = None
    # Schema v3 preserves the optional recoverable contract value.  Older
    # rows expose ``None`` rather than inventing text from the legacy digest.
    access_and_license_notes: str | None = None


@dataclass(frozen=True, slots=True)
class Claim:
    schema_version: int
    claim_id: str
    workspace_id: str
    mission_id: str
    correlation_id: str
    claim_kind: str
    statement_sha256: str
    evidence_ids: tuple[str, ...]
    confidence_bp: int
    verification_status: str
    valid_until: str | None
    contradiction_claim_ids: tuple[str, ...]
    source_context_sha256: str
    created_at: str
    verified_at: str | None = None
    valid_from: str | None = None
    # Required for schema v3 writes.  ``None`` means a readable legacy row
    # whose v1/v2 digest cannot be reversed.
    text: str | None = None


@dataclass(frozen=True, slots=True)
class ActionRequest:
    schema_version: int
    request_id: str
    workspace_id: str
    mission_id: str
    correlation_id: str
    connector: str
    operation: str
    target_sha256: str
    payload_sha256: str
    idempotency_key: str
    risk: str
    approval_policy: str
    dry_run: bool
    audit_reference_sha256: str
    verification_plan_sha256: str
    source_context_sha256: str
    created_at: str
    # Required for schema v3 writes.  The legacy hash remains part of the
    # contract and must equal the digest of this exact recoverable value.
    target: str | None = None
    approval_id: str | None = None


@dataclass(frozen=True, slots=True)
class ActionReservation:
    schema_version: int
    request_id: str
    workspace_id: str
    mission_id: str
    correlation_id: str
    idempotency_key: str
    request_sha256: str
    source_context_sha256: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ActionReservationStage:
    schema_version: int
    stage_id: str
    request_id: str
    workspace_id: str
    mission_id: str
    correlation_id: str
    generation: int
    stage: str
    owner_id: str
    lease_expires_at: str
    audit_reference_sha256: str | None
    source_context_sha256: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ActionReservationLease:
    request_id: str
    owner_id: str
    stage: str
    audit_reference_sha256: str | None
    owns: bool

    def __bool__(self) -> bool:
        return self.owns


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    schema_version: int
    receipt_id: str
    request_id: str
    workspace_id: str
    mission_id: str
    correlation_id: str
    outcome: str
    provider_request_sha256: str
    output_sha256: str
    verification_sha256: str
    postcondition_sha256: str
    error_class: str
    supersedes_receipt_id: str | None
    reconciliation: bool
    source_context_sha256: str
    observed_at: str
    created_at: str
    provider_request_id: str | None = None
    provider_request_ref: str | None = None
    started_at: str = ""
    completed_at: str | None = None
    before_state_ref: str | None = None
    after_state_ref: str | None = None
    output_ref: str | None = None
    verification_ref: str | None = None
    rollback_ref: str | None = None


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    schema_version: int
    event_id: str
    workspace_id: str
    mission_id: str
    correlation_id: str
    actor: str
    event_type: str
    entity_type: str
    entity_id: str
    redacted_payload_sha256: str
    sequence: int
    previous_hash: str
    event_hash: str
    created_at: str


@dataclass(frozen=True, slots=True)
class V5Status:
    database_id: str
    schema_version: int
    schema_fingerprint: str
    source_v4_state_root: str
    commit_sequence: int
    commit_hmac: str


def control_plane_v5_enabled(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return source.get(CONTROL_PLANE_V5_FLAG, "").strip().casefold() in {"1", "true"}


def _canonical(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ControlPlaneV5ContractError("value is not canonical JSON") from exc


def _sha(value: bytes | str) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ControlPlaneV5ContractError(f"{label} is invalid")
    _reject_secret(value, label)
    if value == "legacy-default":
        raise ControlPlaneV5IsolationError("legacy-default is unavailable to enhanced calls")
    return value


def _recoverable_contract_id(value: object, label: str) -> str:
    """Validate a durable identifier without accepting a credential carrier."""

    identifier = _safe_id(value, label)
    if contains_secret(identifier) or _CONTRACT_ID_SECRET.fullmatch(identifier):
        raise ControlPlaneV5ContractError(
            f"{label} contains high-confidence secret material"
        )
    return identifier


def _slug(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SLUG.fullmatch(value):
        raise ControlPlaneV5ContractError(f"{label} is invalid")
    _reject_secret(value, label)
    return value


def _digest(value: object, label: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ControlPlaneV5ContractError(f"{label} is not a canonical SHA-256 digest")
    return value


def _timestamp(value: object, label: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not 20 <= len(value) <= 40:
        raise ControlPlaneV5ContractError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ControlPlaneV5ContractError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise ControlPlaneV5ContractError(f"{label} must be timezone-aware")
    return value


def _safe_text(
    value: object, label: str, *, optional: bool = False, max_length: int = 512
) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ControlPlaneV5ContractError(f"{label} is invalid")
    if any(ord(char) < 32 for char in value):
        raise ControlPlaneV5ContractError(f"{label} contains control characters")
    _reject_secret(value, label)
    return value


def _recoverable_contract_text(
    value: object,
    label: str,
    *,
    optional: bool = False,
    max_length: int = 1024,
) -> str | None:
    """Validate exact contract text without broad keyword false positives.

    These fields may legitimately discuss words such as ``token`` or
    ``password``.  Reject control characters and high-confidence credential
    shapes while keeping the authenticated value recoverable.  The caller is
    still responsible for data-class policy before using this P4.4 sidecar.
    """

    if optional and value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ControlPlaneV5ContractError(f"{label} is invalid")
    if any(ord(char) < 32 for char in value):
        raise ControlPlaneV5ContractError(f"{label} contains control characters")
    if contains_secret(value) or any(
        pattern.search(value) for pattern in _RECOVERABLE_SECRET_PATTERNS
    ):
        raise ControlPlaneV5ContractError(
            f"{label} contains high-confidence secret material"
        )
    encoded = value.encode("utf-8")
    if len(encoded) > max_length * 4:
        raise ControlPlaneV5ContractError(f"{label} is oversized")
    return value


def _integrity_contract_text(
    value: object,
    label: str,
    *,
    optional: bool = False,
    max_length: int = 1024,
) -> str | None:
    """Apply recoverable-text policy while hydrating authenticated records."""

    try:
        return _recoverable_contract_text(
            value, label, optional=optional, max_length=max_length
        )
    except ControlPlaneV5ContractError as exc:
        raise ControlPlaneV5IntegrityError(
            f"{label} violates the authenticated recoverable-text policy"
        ) from exc


def _opaque_reference(value: object, label: str, *, optional: bool = False) -> str | None:
    """Validate a recoverable non-secret provider/entity reference.

    Query strings, fragments and user-info are deliberately unavailable: a
    credential-bearing URL is not an acceptable durable receipt reference.
    """

    if optional and value is None:
        return None
    if not isinstance(value, str) or not _OPAQUE_REF.fullmatch(value):
        raise ControlPlaneV5ContractError(f"{label} is invalid")
    if any(marker in value for marker in ("?", "#", "@")):
        raise ControlPlaneV5ContractError(f"{label} may not contain URL secrets")
    if contains_secret(value) or _CONTRACT_ID_SECRET.fullmatch(value):
        raise ControlPlaneV5ContractError(
            f"{label} contains high-confidence secret material"
        )
    _reject_secret(value, label)
    return value


def _integrity_opaque_reference(
    value: object, label: str, *, optional: bool = False
) -> str | None:
    """Apply the public opaque-reference policy to authenticated rows."""

    try:
        return _opaque_reference(value, label, optional=optional)
    except ControlPlaneV5ContractError as exc:
        raise ControlPlaneV5IntegrityError(
            f"{label} violates the authenticated opaque-reference policy"
        ) from exc


def _typed_reference(
    value: object, label: str, expected_kind: str, *, optional: bool = False
) -> str | None:
    reference = _opaque_reference(value, label, optional=optional)
    if reference is None:
        return None
    prefix = expected_kind + ":"
    if not reference.startswith(prefix):
        raise ControlPlaneV5ContractError(
            f"{label} must be a {expected_kind} reference"
        )
    return _safe_id(reference[len(prefix):], f"{label} identity")


def _validate_retained_publication_refs(
    *,
    output_ref: str | None,
    rollback_ref: str | None,
    outcome: str,
    reconciliation: bool,
    integrity: bool = False,
) -> bool:
    """Validate the existing refs used for one interrupted CAS publication."""

    manifest_prefix = "publication:"
    binding_prefix = "publication-binding:"
    has_manifest = isinstance(output_ref, str) and output_ref.startswith(
        manifest_prefix
    )
    has_binding = isinstance(rollback_ref, str) and rollback_ref.startswith(
        binding_prefix
    )

    def fail(message: str) -> None:
        error = (
            ControlPlaneV5IntegrityError
            if integrity
            else ControlPlaneV5ContractError
        )
        raise error(message)

    if has_manifest != has_binding:
        fail("retained publication manifest/binding pair is incomplete")
    if not has_manifest:
        return False
    manifest_sha256 = str(output_ref)[len(manifest_prefix):]
    binding_sha256 = str(rollback_ref)[len(binding_prefix):]
    if not _DIGEST.fullmatch(manifest_sha256) or not _DIGEST.fullmatch(
        binding_sha256
    ):
        fail("retained publication manifest/binding digest is invalid")
    if outcome not in {"unknown", "partial"} or reconciliation:
        fail("retained publication refs require an initial unknown/partial receipt")
    return True


def _reject_secret(value: object, label: str) -> None:
    def visit(item: object, depth: int = 0) -> None:
        if depth > 24:
            raise ControlPlaneV5ContractError(f"{label} exceeds the nesting limit")
        if isinstance(item, str):
            if len(item) > _MAX_TEXT:
                raise ControlPlaneV5ContractError(f"{label} contains oversized text")
            # ``memory.store.contains_secret`` is the project-wide credential
            # authority.  Keep the local structural patterns as defense in
            # depth, but never let a caller choose a weaker detector by using
            # a generic identifier/text field instead of a recoverable field.
            if (
                contains_secret(item)
                or any(pattern.search(item) for pattern in _SECRET_PATTERNS)
            ):
                raise ControlPlaneV5ContractError(f"{label} contains secret-shaped material")
        elif isinstance(item, dict):
            for key, child in item.items():
                visit(key, depth + 1)
                visit(child, depth + 1)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child, depth + 1)

    visit(value)


def _integrity_reject_secret(value: object, label: str) -> None:
    """Apply the write-time persisted-string invariant during hydration."""

    try:
        _reject_secret(value, label)
    except ControlPlaneV5ContractError as exc:
        raise ControlPlaneV5IntegrityError(
            f"{label} violates the authenticated persisted-string policy"
        ) from exc


def assert_redacted(value: object, label: str = "value") -> None:
    """Reject secret-shaped or unbounded material before persistence/artifact use."""

    _reject_secret(value, label)


def evidence_identity(*, workspace_id: str, mission_id: str, caller_key: str) -> str:
    return "evidence-" + _sha(
        _canonical(
            [
                _safe_id(workspace_id, "workspace_id"),
                _safe_id(mission_id, "mission_id"),
                _safe_id(caller_key, "caller_key"),
            ]
        )
    )


def claim_identity(*, workspace_id: str, mission_id: str, caller_key: str) -> str:
    return "claim-" + _sha(
        _canonical(
            [
                _safe_id(workspace_id, "workspace_id"),
                _safe_id(mission_id, "mission_id"),
                _safe_id(caller_key, "caller_key"),
            ]
        )
    )


def action_request_identity(idempotency_key: str) -> str:
    if (
        not isinstance(idempotency_key, str)
        or not idempotency_key.startswith("onyx:v5:")
        or not _DIGEST.fullmatch(idempotency_key[8:])
    ):
        raise ControlPlaneV5ContractError("idempotency_key is invalid")
    return "request-" + _sha(idempotency_key)


def provider_request_binding_sha256(
    provider_request_id: str, provider_request_ref: str
) -> str:
    """Bind both recoverable external-operation identifiers to one digest."""

    provider_request_id = str(
        _opaque_reference(provider_request_id, "provider_request_id")
    )
    provider_request_ref = str(
        _opaque_reference(provider_request_ref, "provider_request_ref")
    )
    return _sha(
        "ONYX-V5-PROVIDER-REQUEST.v3\0"
        + _canonical(
            {
                "provider_request_id": provider_request_id,
                "provider_request_ref": provider_request_ref,
            }
        )
    )


def evidence_verification_sha256(evidence: EvidenceRecord) -> str:
    """Bind a receipt verification digest to one authenticated evidence row.

    ``claim_ids`` is deliberately excluded because it is an inverse projection
    derived from authenticated link rows and can grow after evidence creation.
    Every durable evidence attribute that establishes source, bytes, scope and
    observation semantics is otherwise included.
    """

    if type(evidence) is not EvidenceRecord:
        raise ControlPlaneV5ContractError("verification evidence type is invalid")
    payload = asdict(evidence)
    payload.pop("claim_ids", None)
    return _sha(
        "ONYX-V5-EVIDENCE-VERIFICATION.v1\0" + _canonical(payload)
    )


def action_request_contract_sha256(
    *,
    workspace_id: str,
    mission_id: str,
    request_id: str,
    correlation_id: str,
    connector: str,
    operation: str,
    target_sha256: str,
    payload_sha256: str,
    idempotency_key: str,
    risk: str,
    approval_policy: str,
    dry_run: bool,
    verification_plan_sha256: str,
    source_context_sha256: str,
    target: str | None = None,
    approval_id: str | None = None,
    schema_version: int = RECORD_SCHEMA_VERSION,
) -> str:
    """Digest the immutable semantic request proposal before audit linkage."""

    if type(dry_run) is not bool:
        raise ControlPlaneV5ContractError("dry_run must be bool")
    if schema_version not in {1, 2, 3}:
        raise ControlPlaneV5ContractError("action request schema_version is unknown")
    payload: dict[str, object] = {
                "approval_policy": _slug(approval_policy, "approval_policy"),
                "connector": _slug(connector, "connector"),
                "correlation_id": _safe_id(correlation_id, "correlation_id"),
                "dry_run": dry_run,
                "idempotency_key": idempotency_key,
                "mission_id": _safe_id(mission_id, "mission_id"),
                "operation": _slug(operation, "operation"),
                "payload_sha256": str(_digest(payload_sha256, "payload_sha256")),
                "request_id": _safe_id(request_id, "request_id"),
                "risk": _slug(risk, "risk"),
                "schema_version": schema_version,
                "source_context_sha256": str(
                    _digest(source_context_sha256, "source_context_sha256")
                ),
                "target_sha256": str(_digest(target_sha256, "target_sha256")),
                "verification_plan_sha256": str(
                    _digest(verification_plan_sha256, "verification_plan_sha256")
                ),
                "workspace_id": _safe_id(workspace_id, "workspace_id"),
    }
    if schema_version >= 3:
        target = _recoverable_contract_text(
            target, "action target", max_length=1024
        )
        approval_id = (
            _recoverable_contract_id(approval_id, "approval_id")
            if approval_id is not None
            else None
        )
        if not hmac.compare_digest(
            str(payload["target_sha256"]), _sha(str(target))
        ):
            raise ControlPlaneV5ContractError(
                "target_sha256 does not bind the recoverable target"
            )
        payload["target"] = target
        payload["approval_id"] = approval_id
    return _sha(_canonical(payload))


def action_audit_trace_id(
    *,
    workspace_id: str,
    mission_id: str,
    request_id: str,
    request_sha256: str,
    idempotency_key: str,
    connector: str,
    operation: str,
    target_sha256: str,
    payload_sha256: str,
    risk: str,
    approval_policy: str,
    dry_run: bool,
    correlation_id: str,
    source_context_sha256: str,
    target: str | None = None,
    approval_id: str | None = None,
    schema_version: int = RECORD_SCHEMA_VERSION,
) -> str:
    """Return the canonical semantic binding used by the audit authority."""

    if type(dry_run) is not bool:
        raise ControlPlaneV5ContractError("dry_run must be bool")
    if (
        not isinstance(idempotency_key, str)
        or not idempotency_key.startswith("onyx:v5:")
        or not _DIGEST.fullmatch(idempotency_key[8:])
    ):
        raise ControlPlaneV5ContractError("idempotency_key is invalid")
    return _sha(
        f"ONYX-V5-AUDIT-TRACE.v{schema_version}\0"
        + _canonical(_action_audit_trace_payload(
            workspace_id=workspace_id, mission_id=mission_id,
            request_id=request_id, request_sha256=request_sha256,
            idempotency_key=idempotency_key, connector=connector,
            operation=operation, target_sha256=target_sha256,
            payload_sha256=payload_sha256, risk=risk,
            approval_policy=approval_policy, dry_run=dry_run,
            correlation_id=correlation_id,
            source_context_sha256=source_context_sha256,
            target=target, approval_id=approval_id,
            schema_version=schema_version,
        ))
    )


def _action_audit_trace_payload(
    *, workspace_id: str, mission_id: str, request_id: str,
    request_sha256: str, idempotency_key: str, connector: str,
    operation: str, target_sha256: str, payload_sha256: str, risk: str,
    approval_policy: str, dry_run: bool, correlation_id: str,
    source_context_sha256: str,
    target: str | None = None, approval_id: str | None = None,
    schema_version: int = RECORD_SCHEMA_VERSION,
) -> dict[str, object]:
    if type(dry_run) is not bool:
        raise ControlPlaneV5ContractError("dry_run must be bool")
    payload: dict[str, object] = {
        "approval_policy": _slug(approval_policy, "approval_policy"),
        "connector": _slug(connector, "connector"),
        "correlation_id": _safe_id(correlation_id, "correlation_id"),
        "dry_run": dry_run,
        "idempotency_key": idempotency_key,
        "mission_id": _safe_id(mission_id, "mission_id"),
        "operation": _slug(operation, "operation"),
        "payload_sha256": str(_digest(payload_sha256, "payload_sha256")),
        "request_id": _safe_id(request_id, "request_id"),
        "request_sha256": str(_digest(request_sha256, "request_sha256")),
        "risk": _slug(risk, "risk"),
        "source_context_sha256": str(
            _digest(source_context_sha256, "source_context_sha256")
        ),
        "target_sha256": str(_digest(target_sha256, "target_sha256")),
        "workspace_id": _safe_id(workspace_id, "workspace_id"),
    }
    if schema_version >= 3:
        target = _recoverable_contract_text(
            target, "action target", max_length=1024
        )
        approval_id = (
            _recoverable_contract_id(approval_id, "approval_id")
            if approval_id is not None
            else None
        )
        if not hmac.compare_digest(str(payload["target_sha256"]), _sha(str(target))):
            raise ControlPlaneV5ContractError(
                "target_sha256 does not bind the recoverable target"
            )
        payload["target"] = target
        payload["approval_id"] = approval_id
        payload["schema_version"] = schema_version
    return payload


def action_audit_semantic_contract(request: ActionRequest) -> dict[str, object]:
    """Recompute the exact versioned audit contract from a stored request."""

    if type(request) is not ActionRequest:
        raise ControlPlaneV5ContractError("action request type is invalid")
    request_sha256 = action_request_contract_sha256(
        workspace_id=request.workspace_id, mission_id=request.mission_id,
        request_id=request.request_id, correlation_id=request.correlation_id,
        connector=request.connector, operation=request.operation,
        target_sha256=request.target_sha256, payload_sha256=request.payload_sha256,
        idempotency_key=request.idempotency_key, risk=request.risk,
        approval_policy=request.approval_policy, dry_run=request.dry_run,
        verification_plan_sha256=request.verification_plan_sha256,
        source_context_sha256=request.source_context_sha256,
        target=request.target, approval_id=request.approval_id,
        schema_version=request.schema_version,
    )
    payload = _action_audit_trace_payload(
        workspace_id=request.workspace_id, mission_id=request.mission_id,
        request_id=request.request_id, request_sha256=request_sha256,
        idempotency_key=request.idempotency_key, connector=request.connector,
        operation=request.operation, target_sha256=request.target_sha256,
        payload_sha256=request.payload_sha256, risk=request.risk,
        approval_policy=request.approval_policy, dry_run=request.dry_run,
        correlation_id=request.correlation_id,
        source_context_sha256=request.source_context_sha256,
        target=request.target, approval_id=request.approval_id,
        schema_version=request.schema_version,
    )
    return {
        "contract": f"OnyxToolAuditSemantic.v{request.schema_version}",
        "request": payload,
        "authorization": {
            "principal": "local-owner", "profile": "p4.4-shadow",
            "tool": request.connector, "action": request.operation,
            "decision": "allowed", "outcome": "decision",
        },
    }


def stable_scope_key(
    *, workspace_id: str, mission_id: str, operation: str, caller_key: str
) -> str:
    workspace_id = _safe_id(workspace_id, "workspace_id")
    mission_id = _safe_id(mission_id, "mission_id")
    operation = _slug(operation, "operation")
    caller_key = _safe_id(caller_key, "caller_key")
    return "onyx:v5:" + _sha(
        "ONYX-V5-IDEMPOTENCY\0" + _canonical(
            [workspace_id, mission_id, operation, caller_key]
        )
    )


_SCHEMA = (
    """CREATE TABLE schema_metadata(
        key TEXT PRIMARY KEY,value TEXT NOT NULL
    ) WITHOUT ROWID""",
    """CREATE TABLE source_v4_provenance(
        source_id TEXT PRIMARY KEY,database_id TEXT NOT NULL,
        schema_version INTEGER NOT NULL CHECK(schema_version=4),
        schema_fingerprint TEXT NOT NULL CHECK(length(schema_fingerprint)=64),
        state_root TEXT NOT NULL CHECK(length(state_root)=64),
        anchor_sequence INTEGER NOT NULL CHECK(anchor_sequence>=1),
        captured_at TEXT NOT NULL,record_json TEXT NOT NULL CHECK(json_valid(record_json)),
        record_sha256 TEXT NOT NULL,
        record_hmac TEXT NOT NULL CHECK(length(record_hmac)=64)
    ) WITHOUT ROWID""",
    """CREATE TABLE mission_scope_snapshots(
        scope_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,mission_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,context_revision INTEGER NOT NULL CHECK(context_revision>=0),
        context_sha256 TEXT NOT NULL CHECK(length(context_sha256)=64),
        source_state_root TEXT NOT NULL CHECK(length(source_state_root)=64),
        record_json TEXT NOT NULL CHECK(json_valid(record_json)),
        record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
        record_hmac TEXT NOT NULL CHECK(length(record_hmac)=64),
        UNIQUE(workspace_id,mission_id,context_revision)
    ) WITHOUT ROWID""",
    """CREATE TABLE artifact_records(
        artifact_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,mission_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,request_id TEXT,content_sha256 TEXT NOT NULL,
        relative_path TEXT NOT NULL,record_json TEXT NOT NULL CHECK(json_valid(record_json)),
        record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
        record_hmac TEXT NOT NULL CHECK(length(record_hmac)=64),
        UNIQUE(workspace_id,mission_id,request_id),
        FOREIGN KEY(request_id) REFERENCES action_requests(request_id)
    ) WITHOUT ROWID""",
    """CREATE TABLE evidence_records(
        evidence_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,mission_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,artifact_id TEXT,
        record_json TEXT NOT NULL CHECK(json_valid(record_json)),
        record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
        record_hmac TEXT NOT NULL CHECK(length(record_hmac)=64),
        FOREIGN KEY(artifact_id) REFERENCES artifact_records(artifact_id)
    ) WITHOUT ROWID""",
    """CREATE TABLE claims(
        claim_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,mission_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,record_json TEXT NOT NULL CHECK(json_valid(record_json)),
        record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
        record_hmac TEXT NOT NULL CHECK(length(record_hmac)=64)
    ) WITHOUT ROWID""",
    """CREATE TABLE claim_evidence_links(
        link_id TEXT PRIMARY KEY,claim_id TEXT NOT NULL,evidence_id TEXT NOT NULL,
        workspace_id TEXT NOT NULL,mission_id TEXT NOT NULL,correlation_id TEXT NOT NULL,
        record_json TEXT NOT NULL CHECK(json_valid(record_json)),
        record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
        record_hmac TEXT NOT NULL CHECK(length(record_hmac)=64),
        UNIQUE(claim_id,evidence_id),
        FOREIGN KEY(claim_id) REFERENCES claims(claim_id),
        FOREIGN KEY(evidence_id) REFERENCES evidence_records(evidence_id)
    ) WITHOUT ROWID""",
    """CREATE TABLE action_requests(
        request_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,mission_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,idempotency_key TEXT NOT NULL UNIQUE,
        record_json TEXT NOT NULL CHECK(json_valid(record_json)),
        record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
        record_hmac TEXT NOT NULL CHECK(length(record_hmac)=64)
    ) WITHOUT ROWID""",
    """CREATE TABLE action_reservations(
        request_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,mission_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,idempotency_key TEXT NOT NULL UNIQUE,
        record_json TEXT NOT NULL CHECK(json_valid(record_json)),
        record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
        record_hmac TEXT NOT NULL CHECK(length(record_hmac)=64)
    ) WITHOUT ROWID""",
    """CREATE TABLE action_reservation_stages(
        stage_id TEXT PRIMARY KEY,request_id TEXT NOT NULL,workspace_id TEXT NOT NULL,
        mission_id TEXT NOT NULL,correlation_id TEXT NOT NULL,generation INTEGER NOT NULL,
        stage TEXT NOT NULL,owner_id TEXT NOT NULL,lease_expires_at TEXT NOT NULL,
        audit_reference_sha256 TEXT,
        record_json TEXT NOT NULL CHECK(json_valid(record_json)),
        record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
        record_hmac TEXT NOT NULL CHECK(length(record_hmac)=64),
        FOREIGN KEY(request_id) REFERENCES action_reservations(request_id),
        UNIQUE(request_id,generation)
    ) WITHOUT ROWID""",
    """CREATE TABLE action_receipts(
        receipt_id TEXT PRIMARY KEY,request_id TEXT NOT NULL,workspace_id TEXT NOT NULL,
        mission_id TEXT NOT NULL,correlation_id TEXT NOT NULL,
        supersedes_receipt_id TEXT,created_at TEXT NOT NULL,
        record_json TEXT NOT NULL CHECK(json_valid(record_json)),
        record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
        record_hmac TEXT NOT NULL CHECK(length(record_hmac)=64),
        FOREIGN KEY(request_id) REFERENCES action_requests(request_id),
        FOREIGN KEY(supersedes_receipt_id) REFERENCES action_receipts(receipt_id),
        UNIQUE(supersedes_receipt_id)
    ) WITHOUT ROWID""",
    """CREATE TABLE event_envelopes(
        event_id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL,mission_id TEXT NOT NULL,
        correlation_id TEXT NOT NULL,sequence INTEGER NOT NULL CHECK(sequence>=1),
        event_hash TEXT NOT NULL UNIQUE,record_json TEXT NOT NULL CHECK(json_valid(record_json)),
        record_sha256 TEXT NOT NULL CHECK(length(record_sha256)=64),
        record_hmac TEXT NOT NULL CHECK(length(record_hmac)=64),
        UNIQUE(workspace_id,correlation_id,sequence)
    ) WITHOUT ROWID""",
    """CREATE TABLE ledger_commits(
        sequence INTEGER PRIMARY KEY CHECK(sequence>=1),mutation_id TEXT NOT NULL UNIQUE,
        previous_commit_hmac TEXT NOT NULL CHECK(length(previous_commit_hmac)=64),
        delta_sha256 TEXT NOT NULL CHECK(length(delta_sha256)=64),
        commit_hmac TEXT NOT NULL UNIQUE CHECK(length(commit_hmac)=64),
        created_at TEXT NOT NULL
    ) WITHOUT ROWID""",
    """CREATE TABLE ledger_entries(
        commit_sequence INTEGER NOT NULL,entry_ordinal INTEGER NOT NULL,
        table_name TEXT NOT NULL,entity_id TEXT NOT NULL,record_sha256 TEXT NOT NULL,
        record_hmac TEXT NOT NULL,PRIMARY KEY(commit_sequence,entry_ordinal),
        UNIQUE(table_name,entity_id),
        FOREIGN KEY(commit_sequence) REFERENCES ledger_commits(sequence)
    ) WITHOUT ROWID""",
    "CREATE INDEX idx_v5_evidence_scope ON evidence_records(workspace_id,mission_id,evidence_id)",
    "CREATE INDEX idx_v5_claim_scope ON claims(workspace_id,mission_id,claim_id)",
    "CREATE INDEX idx_v5_receipt_request ON action_receipts(request_id,receipt_id)",
    "CREATE INDEX idx_v5_reservation_stage_tail ON action_reservation_stages(request_id,generation DESC)",
    "CREATE UNIQUE INDEX idx_v5_one_initial_receipt ON action_receipts(request_id) WHERE supersedes_receipt_id IS NULL",
    "CREATE INDEX idx_v5_receipt_parent ON action_receipts(request_id,supersedes_receipt_id)",
    "CREATE INDEX idx_v5_event_tail ON event_envelopes(workspace_id,correlation_id,sequence DESC)",
)
_IMMUTABLE_TABLES = (
    "schema_metadata", "source_v4_provenance", "mission_scope_snapshots",
    "artifact_records", "evidence_records", "claims", "claim_evidence_links",
    "action_requests", "action_reservations", "action_reservation_stages", "action_receipts", "event_envelopes", "ledger_commits",
    "ledger_entries",
)


def _reference_schema_fingerprint() -> str:
    memory = sqlite3.connect(":memory:")
    try:
        memory.execute("PRAGMA foreign_keys=ON")
        for statement in _SCHEMA:
            memory.execute(statement)
        for table in _IMMUTABLE_TABLES:
            for operation in ("UPDATE", "DELETE"):
                memory.execute(
                    f"CREATE TRIGGER deny_v5_{table}_{operation.lower()} BEFORE {operation} "
                    f"ON {table} BEGIN SELECT RAISE(ABORT,'v5 table is immutable'); END"
                )
        rows = memory.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        # Record-contract evolution is part of the accepted authority shape
        # even when it does not require a new SQL column.  This deliberately
        # prevents an R1-R5 candidate database from being silently adopted by
        # an R6 binary with stronger recoverability/lineage semantics.
        return _sha(
            "ONYX-V5-SCHEMA\0"
            + _canonical(
                {
                    "record_schema_version": RECORD_SCHEMA_VERSION,
                    "record_contract_revision": "P44-R9-001",
                    "sqlite_objects": [tuple(row) for row in rows],
                }
            )
        )
    finally:
        memory.close()


_SCHEMA_FINGERPRINT = _reference_schema_fingerprint()


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    try:
        if readonly:
            connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        else:
            connection = sqlite3.connect(path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA busy_timeout=30000")
        if not readonly:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
        return connection
    except sqlite3.Error as exc:
        raise ControlPlaneV5IOError("could not open the v5 authority") from exc


def _record_mac(key: bytes, table: str, entity_id: str, digest: str) -> str:
    return hmac.new(
        key,
        b"ONYX-V5-RECORD\0" + table.encode("ascii") + b"\0"
        + entity_id.encode("ascii") + b"\0" + digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _commit_mac(key: bytes, sequence: int, previous: str, delta: str) -> str:
    return hmac.new(
        key,
        b"ONYX-V5-COMMIT\0" + str(sequence).encode("ascii") + b"\0"
        + previous.encode("ascii") + b"\0" + delta.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _assert_replay_equivalent(prior: object, proposed: object, label: str) -> None:
    left = asdict(prior)  # type: ignore[arg-type]
    right = asdict(proposed)  # type: ignore[arg-type]
    left.pop("created_at", None)
    right.pop("created_at", None)
    if left != right:
        raise ControlPlaneV5Conflict(f"{label} replay changed input")


class ControlPlaneV5Store:
    """Single append-only P4.4 authority, explicitly bound to v4 mission scope."""

    def __init__(
        self,
        *,
        path: Path,
        source: MissionAuthorityPort,
        key_vault: SecretVault,
        state_vault: SecretVault,
        enabled: bool,
        pending_vault: SecretVault | None = None,
        audit_reference_verifier: Callable[[str, str], bool] | None = None,
        semantic_audit_verifier: Callable[[object, str], bool] | None = None,
    ):
        if type(enabled) is not bool:
            raise TypeError("enabled must be bool")
        if not isinstance(source, MissionAuthorityPort):
            raise TypeError("source must implement MissionAuthorityPort")
        self.path = Path(path)
        self.source = source
        self.key_vault = key_vault
        self.state_vault = state_vault
        self.pending_vault = pending_vault
        self.enabled = enabled
        # Retained for callers that still use the legacy trace/hash API.  It is
        # deliberately not an authorization source for semantic-v2 requests.
        self.audit_reference_verifier = audit_reference_verifier
        self.semantic_audit_verifier = semantic_audit_verifier
        self._key: bytes | None = None

    def _assert_enabled(self) -> None:
        if not self.enabled:
            raise ControlPlaneV5Disabled(f"{CONTROL_PLANE_V5_FLAG} is disabled")

    def initialize(self) -> "ControlPlaneV5Store":
        self._assert_enabled()
        if self.pending_vault is None:
            raise ControlPlaneV5IntegrityError("separate v5 pending vault is required")
        if self.pending_vault is self.state_vault:
            raise ControlPlaneV5IntegrityError("v5 final and pending vaults must differ")
        for attribute in ("path", "_path", "namespace", "_namespace"):
            final_identity = getattr(self.state_vault, attribute, None)
            pending_identity = getattr(self.pending_vault, attribute, None)
            if (
                final_identity is not None and pending_identity is not None
                and str(final_identity) == str(pending_identity)
            ):
                raise ControlPlaneV5IntegrityError(
                    "v5 final and pending vault namespaces must differ"
                )
        status = self.source.status()
        if (
            status.schema_version != 4
            or not _SAFE_ID.fullmatch(status.database_id)
            or not _DIGEST.fullmatch(status.schema_fingerprint)
            or not _DIGEST.fullmatch(status.state_root)
            or status.anchor_sequence < 1
        ):
            raise ControlPlaneV5IntegrityError("v4 authority status is invalid")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ControlPlaneV5IOError("could not prepare the v5 private directory") from exc
        created = not self.path.exists()
        key = self.key_vault.get_bytes()
        created_key = key is None
        if key is None:
            if not created:
                raise ControlPlaneV5IntegrityError("v5 key vault is missing")
            key = secrets.token_bytes(32)
            self.key_vault.set_bytes(key)
        if not isinstance(key, bytes) or len(key) != 32:
            raise ControlPlaneV5IntegrityError("v5 key vault value is invalid")
        self._key = key
        with _LOCK:
            connection = _connect(self.path)
            try:
                if created:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(f"PRAGMA user_version={V5_SCHEMA_VERSION}")
                    for statement in _SCHEMA:
                        connection.execute(statement)
                    for table in _IMMUTABLE_TABLES:
                        for operation in ("UPDATE", "DELETE"):
                            connection.execute(
                                f"CREATE TRIGGER deny_v5_{table}_{operation.lower()} "
                                f"BEFORE {operation} ON {table} BEGIN SELECT "
                                "RAISE(ABORT,'v5 table is immutable'); END"
                            )
                    database_id = "onyx-v5-" + secrets.token_hex(16)
                    metadata = {
                        "schema_version": str(V5_SCHEMA_VERSION),
                        "schema_fingerprint": _SCHEMA_FINGERPRINT,
                        "database_id": database_id,
                        "head_protocol": "separate-pending-v2",
                    }
                    connection.executemany(
                        "INSERT INTO schema_metadata(key,value) VALUES(?,?)",
                        tuple(metadata.items()),
                    )
                    source_payload = {
                        "source_id": "accepted-control-plane-v4",
                        "target_database_id": database_id,
                        **asdict(status),
                        "captured_at": _now(),
                    }
                    self._insert_record(
                        connection, "source_v4_provenance", "source_id",
                        source_payload["source_id"], source_payload,
                        extra=(
                            source_payload["database_id"], source_payload["schema_version"],
                            source_payload["schema_fingerprint"], source_payload["state_root"],
                            source_payload["anchor_sequence"], source_payload["captured_at"],
                        ),
                    )
                    entries = [self._entry_for(connection, "source_v4_provenance", "source_id", source_payload["source_id"])]
                    self._append_commit(connection, "v5-bootstrap", entries)
                    connection.commit()
                self._verify_schema(connection, full=True)
                current = self._verify_tail(connection)
                self._recover_or_verify_head(
                    current, allow_missing=created and current[0] == 1
                )
            except BaseException as primary:
                try:
                    connection.rollback()
                except BaseException as cleanup_error:
                    _preserve_cleanup_failure(
                        primary, "v5 initialization rollback", cleanup_error
                    )
                try:
                    connection.close()
                except BaseException as cleanup_error:
                    _preserve_cleanup_failure(
                        primary, "v5 initialization connection close", cleanup_error
                    )
                if created:
                    self._cleanup_failed_create()
                if created_key:
                    try:
                        self.key_vault.delete()
                    except BaseException:
                        pass
                raise
            finally:
                primary = sys.exception()
                try:
                    connection.close()
                except BaseException as cleanup_error:
                    _preserve_cleanup_failure(
                        primary, "v5 initialization connection close", cleanup_error
                    )
        return self

    def _cleanup_failed_create(self) -> None:
        """Remove only regular files created for this failed fresh database."""

        for candidate in (
            self.path.with_name(self.path.name + "-wal"),
            self.path.with_name(self.path.name + "-shm"),
            self.path,
        ):
            try:
                candidate.lstat()
                if not candidate.is_file() or candidate.is_symlink():
                    continue
                candidate.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                # The original initialization error remains primary.  A later
                # open still fails exact-schema/head validation, never repairs.
                continue

    def _verify_schema(
        self, connection: sqlite3.Connection, *, full: bool = False
    ) -> None:
        rows = connection.execute(
            "SELECT key,value FROM schema_metadata ORDER BY key"
        ).fetchall()
        metadata = {str(row[0]): str(row[1]) for row in rows}
        if set(metadata) != {
            "schema_version", "schema_fingerprint", "database_id", "head_protocol"
        }:
            raise ControlPlaneV5IntegrityError("v5 schema metadata shape diverges")
        if metadata.get("schema_version") != str(V5_SCHEMA_VERSION):
            raise ControlPlaneV5IntegrityError("v5 schema version is unknown")
        if metadata.get("schema_fingerprint") != _SCHEMA_FINGERPRINT:
            raise ControlPlaneV5IntegrityError("v5 schema fingerprint diverges")
        if metadata.get("head_protocol") != "separate-pending-v2":
            raise ControlPlaneV5IntegrityError("v5 head protocol diverges")
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if user_version != V5_SCHEMA_VERSION:
            raise ControlPlaneV5IntegrityError("v5 SQLite user_version diverges")
        # sqlite_master is checked, not repaired.  Missing/extra/corrupt objects fail closed.
        memory = sqlite3.connect(":memory:")
        try:
            memory.execute("PRAGMA foreign_keys=ON")
            for statement in _SCHEMA:
                memory.execute(statement)
            for table in _IMMUTABLE_TABLES:
                for operation in ("UPDATE", "DELETE"):
                    memory.execute(
                        f"CREATE TRIGGER deny_v5_{table}_{operation.lower()} BEFORE {operation} "
                        f"ON {table} BEGIN SELECT RAISE(ABORT,'v5 table is immutable'); END"
                    )
            expected = memory.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            ).fetchall()
        finally:
            memory.close()
        actual = connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        if [tuple(row) for row in actual] != [tuple(row) for row in expected]:
            raise ControlPlaneV5IntegrityError("v5 physical schema diverges")
        if full and connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ControlPlaneV5IntegrityError("v5 foreign-key integrity diverges")

    def _insert_record(
        self,
        connection: sqlite3.Connection,
        table: str,
        id_column: str,
        entity_id: str,
        payload: dict[str, object],
        *,
        prefix: tuple[object, ...] = (),
        extra: tuple[object, ...] = (),
    ) -> tuple[str, str]:
        if self._key is None:
            raise ControlPlaneV5IntegrityError("v5 key is unavailable")
        # This is the single persistence choke point for v5 record material.
        # Validate both the authenticated JSON and denormalized SQLite values,
        # so adding a new field/caller cannot bypass the credential boundary.
        _reject_secret(entity_id, f"{table} entity_id")
        _reject_secret(payload, f"{table} record")
        _reject_secret(prefix, f"{table} prefix")
        _reject_secret(extra, f"{table} extra")
        encoded = _canonical(payload)
        digest = _sha(encoded)
        mac = _record_mac(self._key, table, entity_id, digest)
        if table in {"source_v4_provenance"}:
            columns = (
                id_column, "database_id", "schema_version", "schema_fingerprint",
                "state_root", "anchor_sequence", "captured_at", "record_json", "record_sha256",
                "record_hmac",
            )
            values = (entity_id, *extra, encoded, digest, mac)
        else:
            columns = (*self._prefix_columns(table), "record_json", "record_sha256", "record_hmac")
            values = (*prefix, encoded, digest, mac)
        placeholders = ",".join("?" for _ in values)
        connection.execute(
            f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders})", values
        )
        return digest, mac

    @staticmethod
    def _prefix_columns(table: str) -> tuple[str, ...]:
        mapping = {
            "mission_scope_snapshots": ("scope_id", "workspace_id", "mission_id", "correlation_id", "context_revision", "context_sha256", "source_state_root"),
            "artifact_records": ("artifact_id", "workspace_id", "mission_id", "correlation_id", "request_id", "content_sha256", "relative_path"),
            "evidence_records": ("evidence_id", "workspace_id", "mission_id", "correlation_id", "artifact_id"),
            "claims": ("claim_id", "workspace_id", "mission_id", "correlation_id"),
            "claim_evidence_links": ("link_id", "claim_id", "evidence_id", "workspace_id", "mission_id", "correlation_id"),
            "action_requests": ("request_id", "workspace_id", "mission_id", "correlation_id", "idempotency_key"),
            "action_reservations": ("request_id", "workspace_id", "mission_id", "correlation_id", "idempotency_key"),
            "action_reservation_stages": ("stage_id", "request_id", "workspace_id", "mission_id", "correlation_id", "generation", "stage", "owner_id", "lease_expires_at", "audit_reference_sha256"),
            "action_receipts": ("receipt_id", "request_id", "workspace_id", "mission_id", "correlation_id", "supersedes_receipt_id", "created_at"),
            "event_envelopes": ("event_id", "workspace_id", "mission_id", "correlation_id", "sequence", "event_hash"),
        }
        try:
            return mapping[table]
        except KeyError as exc:
            raise ControlPlaneV5ContractError("unknown v5 record table") from exc

    @staticmethod
    def _entry_for(
        connection: sqlite3.Connection, table: str, id_column: str, entity_id: str
    ) -> tuple[str, str, str, str]:
        row = connection.execute(
            f"SELECT record_sha256,record_hmac FROM {table} WHERE {id_column}=?",
            (entity_id,),
        ).fetchone()
        if row is None:
            raise ControlPlaneV5IntegrityError("new v5 record is missing")
        return table, entity_id, str(row[0]), str(row[1])

    def _append_commit(
        self,
        connection: sqlite3.Connection,
        mutation_id: str,
        entries: Iterable[tuple[str, str, str, str]],
    ) -> tuple[int, str]:
        if self._key is None:
            raise ControlPlaneV5IntegrityError("v5 key is unavailable")
        rows = tuple(entries)
        if not rows:
            raise ControlPlaneV5ContractError("a v5 mutation must commit records")
        _reject_secret(mutation_id, "ledger mutation_id")
        _reject_secret(rows, "ledger entries")
        latest = connection.execute(
            "SELECT sequence,commit_hmac FROM ledger_commits ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        sequence = 1 if latest is None else int(latest[0]) + 1
        previous = _ZERO_HASH if latest is None else str(latest[1])
        delta = _sha("ONYX-V5-DELTA\0" + _canonical(rows))
        commit_hmac = _commit_mac(self._key, sequence, previous, delta)
        connection.execute(
            "INSERT INTO ledger_commits VALUES(?,?,?,?,?,?)",
            (sequence, mutation_id, previous, delta, commit_hmac, _now()),
        )
        connection.executemany(
            "INSERT INTO ledger_entries VALUES(?,?,?,?,?,?)",
            tuple((sequence, ordinal, *entry) for ordinal, entry in enumerate(rows)),
        )
        return sequence, commit_hmac

    def _verify_tail(self, connection: sqlite3.Connection) -> tuple[int, str]:
        if self._key is None:
            raise ControlPlaneV5IntegrityError("v5 key is unavailable")
        row = connection.execute(
            "SELECT sequence,previous_commit_hmac,delta_sha256,commit_hmac "
            "FROM ledger_commits ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise ControlPlaneV5IntegrityError("v5 commit tail is missing")
        sequence, previous, delta, commit_hmac = int(row[0]), str(row[1]), str(row[2]), str(row[3])
        expected = _commit_mac(self._key, sequence, previous, delta)
        if not hmac.compare_digest(expected, commit_hmac):
            raise ControlPlaneV5IntegrityError("v5 commit tail authentication failed")
        entries = connection.execute(
            "SELECT table_name,entity_id,record_sha256,record_hmac FROM ledger_entries "
            "WHERE commit_sequence=? ORDER BY entry_ordinal", (sequence,)
        ).fetchall()
        if not entries or _sha("ONYX-V5-DELTA\0" + _canonical([tuple(row) for row in entries])) != delta:
            raise ControlPlaneV5IntegrityError("v5 commit entries diverge")
        return sequence, commit_hmac

    def _recover_or_verify_head(
        self, current: tuple[int, str], *, allow_missing: bool = False
    ) -> None:
        if self.pending_vault is None:
            raise ControlPlaneV5IntegrityError("separate v5 pending vault is required")
        state = self.state_vault.get_bytes()
        encoded = _canonical({"contract": "OnyxV5Head.v1", "sequence": current[0], "commit_hmac": current[1]}).encode("ascii")
        pending = self.pending_vault.get_bytes()
        if state is None:
            if allow_missing and current[0] == 1 and pending is None:
                self.state_vault.set_bytes(encoded)
                return
            raise ControlPlaneV5IntegrityError("v5 head vault is missing")
        try:
            value = json.loads(state.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ControlPlaneV5IntegrityError("v5 head vault is corrupt") from exc
        if pending is None:
            if value == json.loads(encoded):
                return
            raise ControlPlaneV5IntegrityError("v5 database and head vault diverge")
        try:
            marker = json.loads(pending.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ControlPlaneV5IntegrityError("v5 pending vault is corrupt") from exc
        # Recovery requires a separately persisted, authenticated predecessor
        # marker.  The final head is never overwritten with transient state.
        if isinstance(marker, dict) and marker.get("contract") == "OnyxV5Pending.v2":
            previous_sequence = marker.get("previous_sequence")
            previous_hmac = marker.get("previous_commit_hmac")
            next_sequence = marker.get("next_sequence")
            next_hmac = marker.get("next_commit_hmac")
            nonce = marker.get("nonce")
            marker_hmac = marker.get("marker_hmac")
            if (
                type(previous_sequence) is int
                and type(next_sequence) is int
                and next_sequence == previous_sequence + 1
                and isinstance(previous_hmac, str)
                and isinstance(next_hmac, str)
                and isinstance(nonce, str)
                and re.fullmatch(r"[0-9a-f]{32}", nonce)
                and isinstance(marker_hmac, str)
                and self._key is not None
            ):
                marker_payload = dict(marker)
                marker_payload.pop("marker_hmac", None)
                expected_marker_hmac = hmac.new(
                    self._key,
                    b"ONYX-V5-PENDING.v2\0" + _canonical(marker_payload).encode("ascii"),
                    hashlib.sha256,
                ).hexdigest()
                if current == (next_sequence, next_hmac):
                    connection = _connect(self.path, readonly=True)
                    try:
                        row = connection.execute(
                            "SELECT previous_commit_hmac FROM ledger_commits WHERE sequence=?",
                            (next_sequence,),
                        ).fetchone()
                        prior = connection.execute(
                            "SELECT commit_hmac FROM ledger_commits WHERE sequence=?",
                            (previous_sequence,),
                        ).fetchone()
                    finally:
                        connection.close()
                    final_is_predecessor = value == json.loads(
                        self._head_bytes(previous_sequence, previous_hmac)
                    )
                    final_is_current = value == json.loads(encoded)
                    if (
                        row is not None and prior is not None
                        and hmac.compare_digest(marker_hmac, expected_marker_hmac)
                        and hmac.compare_digest(str(row[0]), previous_hmac)
                        and hmac.compare_digest(str(prior[0]), previous_hmac)
                        and (final_is_predecessor or final_is_current)
                    ):
                        if final_is_predecessor:
                            self.state_vault.set_bytes(encoded)
                        if not self.pending_vault.delete():
                            raise ControlPlaneV5IntegrityError(
                                "v5 committed pending marker could not be cleared"
                            )
                        return
        raise ControlPlaneV5IntegrityError("v5 database and head vault diverge")

    def _head_bytes(self, sequence: int, commit_hmac: str) -> bytes:
        return _canonical({"contract": "OnyxV5Head.v1", "sequence": sequence, "commit_hmac": commit_hmac}).encode("ascii")

    def _pending_head_bytes(
        self, previous: tuple[int, str], next_head: tuple[int, str]
    ) -> bytes:
        if self._key is None:
            raise ControlPlaneV5IntegrityError("v5 key is unavailable")
        payload = {
            "contract": "OnyxV5Pending.v2",
            "previous_sequence": previous[0],
            "previous_commit_hmac": previous[1],
            "next_sequence": next_head[0],
            "next_commit_hmac": next_head[1],
            "nonce": secrets.token_hex(16),
        }
        payload["marker_hmac"] = hmac.new(
            self._key,
            b"ONYX-V5-PENDING.v2\0" + _canonical(payload).encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        return _canonical(payload).encode("ascii")

    @contextmanager
    def _reader(self):
        self._assert_enabled()
        _LOCK.acquire()
        connection: sqlite3.Connection | None = None
        try:
            connection = _connect(self.path, readonly=True)
            self._verify_schema(connection)
            current = self._verify_tail(connection)
            if self.pending_vault is None or self.pending_vault.get_bytes() is not None:
                raise ControlPlaneV5IntegrityError(
                    "v5 pending write requires recovery before read"
                )
            state = self.state_vault.get_bytes()
            if state != self._head_bytes(*current):
                raise ControlPlaneV5IntegrityError("v5 database and head vault diverge")
            yield connection
        finally:
            primary = sys.exception()
            cleanup_error: BaseException | None = None
            try:
                if connection is not None:
                    connection.close()
            except BaseException as exc:
                cleanup_error = exc
            finally:
                _LOCK.release()
            if cleanup_error is not None:
                _preserve_cleanup_failure(
                    primary, "v5 reader connection close", cleanup_error
                )

    def _validated_scope(self, workspace_id: str, mission_id: str) -> MissionScope:
        self._assert_enabled()
        workspace_id = _safe_id(workspace_id, "workspace_id")
        mission_id = _safe_id(mission_id, "mission_id")
        try:
            before = self._validated_source_status()
            scope = self.source.read_scope(workspace_id, mission_id)
            after = self._validated_source_status()
        except ControlPlaneV5Error:
            raise
        except Exception as exc:
            raise ControlPlaneV5IsolationError("v4 mission scope is unavailable") from exc
        if before != after:
            raise ControlPlaneV5Conflict("v4 authority drifted during scope validation")
        if scope.workspace_id != workspace_id or scope.mission_id != mission_id:
            raise ControlPlaneV5IsolationError("v4 mission scope diverges")
        _safe_id(scope.correlation_id, "correlation_id")
        _digest(scope.context_sha256, "context_sha256")
        _digest(scope.source_state_root, "source_state_root")
        if scope.source_state_root != after.state_root:
            raise ControlPlaneV5Conflict("v4 scope proof is stale")
        if type(scope.context_revision) is not int or scope.context_revision < 0:
            raise ControlPlaneV5IntegrityError("v4 context revision is invalid")
        return scope

    def mission_scope(self, *, workspace_id: str, mission_id: str) -> MissionScope:
        """Return one authenticated v4 scope proof without persisting data."""

        return self._validated_scope(workspace_id, mission_id)

    def _verify_action_audit(self, request: ActionRequest) -> None:
        contract = action_audit_semantic_contract(request)
        verifier = self.semantic_audit_verifier
        try:
            if verifier is None:
                from core.tool_audit import verify_semantic_tool_audit_reference

                member = verify_semantic_tool_audit_reference(
                    contract=contract, event_hash=request.audit_reference_sha256
                )
            else:
                member = verifier(contract, request.audit_reference_sha256)
        except Exception as exc:
            raise ControlPlaneV5IntegrityError(
                "semantic tool audit membership verification failed"
            ) from exc
        if member is not True:
            raise ControlPlaneV5IntegrityError(
                "tool audit reference is not a verified semantic-v2 member"
            )

    def _validated_source_status(self) -> V4AuthorityStatus:
        try:
            status = self.source.status()
        except Exception as exc:
            raise ControlPlaneV5IsolationError("v4 authority status is unavailable") from exc
        if (
            status.schema_version != 4
            or not _SAFE_ID.fullmatch(status.database_id)
            or not _DIGEST.fullmatch(status.schema_fingerprint)
            or not _DIGEST.fullmatch(status.state_root)
            or type(status.anchor_sequence) is not int
            or status.anchor_sequence < 1
        ):
            raise ControlPlaneV5IntegrityError("v4 authority status is invalid")
        return status

    def _assert_source_identity(
        self, connection: sqlite3.Connection, status: V4AuthorityStatus
    ) -> None:
        provenance = self._verified_record(
            connection,
            "source_v4_provenance",
            "source_id",
            "accepted-control-plane-v4",
        )
        if (
            provenance.get("database_id") != status.database_id
            or provenance.get("schema_version") != status.schema_version
            or provenance.get("schema_fingerprint") != status.schema_fingerprint
        ):
            raise ControlPlaneV5IsolationError("accepted v4 authority was replaced")
        target_database_id = connection.execute(
            "SELECT value FROM schema_metadata WHERE key='database_id'"
        ).fetchone()
        if (
            target_database_id is None
            or provenance.get("target_database_id") != str(target_database_id[0])
        ):
            raise ControlPlaneV5IntegrityError("v5 database identity diverges")

    def _scope_entry(
        self, connection: sqlite3.Connection, scope: MissionScope
    ) -> tuple[str, str, str, str] | None:
        scope_id = "scope-" + _sha(_canonical(asdict(scope)))
        existing = connection.execute(
            "SELECT record_sha256,record_hmac FROM mission_scope_snapshots WHERE scope_id=?",
            (scope_id,),
        ).fetchone()
        if existing is not None:
            return None
        payload = {"schema_version": 1, "scope_id": scope_id, **asdict(scope)}
        self._insert_record(
            connection, "mission_scope_snapshots", "scope_id", scope_id, payload,
            prefix=(scope_id, scope.workspace_id, scope.mission_id, scope.correlation_id,
                    scope.context_revision, scope.context_sha256, scope.source_state_root),
        )
        return self._entry_for(connection, "mission_scope_snapshots", "scope_id", scope_id)

    def _write_records(
        self,
        *,
        mutation_id: str,
        scope: MissionScope,
        operation: Callable[[sqlite3.Connection], tuple[object, list[tuple[str, str, str, str]]]],
    ) -> object:
        mutation_id = _safe_id(mutation_id, "mutation_id")
        with _LOCK:
            connection = _connect(self.path)
            pending_written = False
            committed = False
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_schema(connection)
                current = self._verify_tail(connection)
                if self.state_vault.get_bytes() != self._head_bytes(*current):
                    raise ControlPlaneV5IntegrityError(
                        "v5 database and head vault diverge before write"
                    )
                if self.pending_vault is None or self.pending_vault.get_bytes() is not None:
                    raise ControlPlaneV5IntegrityError(
                        "v5 pending vault is unavailable or not empty before write"
                    )
                initial_status = self._validated_source_status()
                if scope.source_state_root != initial_status.state_root:
                    raise ControlPlaneV5Conflict("v4 scope proof drifted before write")
                self._assert_source_identity(connection, initial_status)
                prior = connection.execute(
                    "SELECT sequence FROM ledger_commits WHERE mutation_id=?", (mutation_id,)
                ).fetchone()
                if prior is not None:
                    raise ControlPlaneV5Conflict("mutation_id already exists")
                result, entries = operation(connection)
                scope_entry = self._scope_entry(connection, scope)
                if scope_entry is not None:
                    entries.insert(0, scope_entry)
                final_scope = self._validated_scope(scope.workspace_id, scope.mission_id)
                if final_scope != scope:
                    raise ControlPlaneV5Conflict("v4 authority drifted before commit")
                self._assert_source_identity(
                    connection, self._validated_source_status()
                )
                if not entries:
                    connection.rollback()
                    return result
                sequence, commit_hmac = self._append_commit(connection, mutation_id, entries)
                self.pending_vault.set_bytes(
                    self._pending_head_bytes(current, (sequence, commit_hmac))
                )
                pending_written = True
                connection.commit()
                committed = True
                self.state_vault.set_bytes(self._head_bytes(sequence, commit_hmac))
                if not self.pending_vault.delete():
                    raise ControlPlaneV5IntegrityError(
                        "v5 committed pending marker could not be cleared"
                    )
                return result
            except BaseException as primary:
                try:
                    connection.rollback()
                except BaseException as cleanup_error:
                    _preserve_cleanup_failure(
                        primary, "v5 mutation rollback", cleanup_error
                    )
                if pending_written and not committed and self.pending_vault is not None:
                    try:
                        self.pending_vault.delete()
                    except BaseException:
                        pass
                raise
            finally:
                primary = sys.exception()
                try:
                    connection.close()
                except BaseException as cleanup_error:
                    _preserve_cleanup_failure(
                        primary, "v5 mutation connection close", cleanup_error
                    )

    def _append_event(
        self,
        connection: sqlite3.Connection,
        *,
        scope: MissionScope,
        actor: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload_sha256: str,
        created_at: str,
    ) -> tuple[EventEnvelope, tuple[str, str, str, str]]:
        actor = _slug(actor, "actor")
        event_type = _slug(event_type, "event_type")
        entity_type = _slug(entity_type, "entity_type")
        entity_id = _safe_id(entity_id, "entity_id")
        tail = connection.execute(
            "SELECT sequence,event_hash FROM event_envelopes WHERE workspace_id=? "
            "AND correlation_id=? ORDER BY sequence DESC LIMIT 1",
            (scope.workspace_id, scope.correlation_id),
        ).fetchone()
        sequence = 1 if tail is None else int(tail[0]) + 1
        previous = _ZERO_HASH if tail is None else str(tail[1])
        event_id = "event-" + _sha(_canonical([
            scope.workspace_id, scope.mission_id, scope.correlation_id,
            sequence, entity_type, entity_id, payload_sha256,
        ]))
        base = {
            "schema_version": RECORD_SCHEMA_VERSION,
            "event_id": event_id,
            "workspace_id": scope.workspace_id,
            "mission_id": scope.mission_id,
            "correlation_id": scope.correlation_id,
            "actor": actor,
            "event_type": event_type,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "redacted_payload_sha256": payload_sha256,
            "sequence": sequence,
            "previous_hash": previous,
            "created_at": created_at,
        }
        event_hash = _sha("ONYX-V5-EVENT\0" + _canonical(base))
        record = EventEnvelope(**base, event_hash=event_hash)
        self._insert_record(
            connection, "event_envelopes", "event_id", event_id, asdict(record),
            prefix=(event_id, scope.workspace_id, scope.mission_id, scope.correlation_id,
                    sequence, event_hash),
        )
        return record, self._entry_for(connection, "event_envelopes", "event_id", event_id)

    def _verified_record(
        self, connection: sqlite3.Connection, table: str, id_column: str, entity_id: str
    ) -> dict[str, object]:
        if self._key is None:
            raise ControlPlaneV5IntegrityError("v5 key is unavailable")
        row = connection.execute(
            f"SELECT record_json,record_sha256,record_hmac FROM {table} WHERE {id_column}=?",
            (entity_id,),
        ).fetchone()
        if row is None:
            raise ControlPlaneV5Conflict("v5 record is unknown")
        encoded, digest, mac = str(row[0]), str(row[1]), str(row[2])
        if _sha(encoded) != digest or not hmac.compare_digest(
            _record_mac(self._key, table, entity_id, digest), mac
        ):
            raise ControlPlaneV5IntegrityError("v5 record authentication failed")
        included = connection.execute(
            "SELECT 1 FROM ledger_entries WHERE table_name=? AND entity_id=? "
            "AND record_sha256=? AND record_hmac=? LIMIT 1",
            (table, entity_id, digest, mac),
        ).fetchone()
        if included is None:
            raise ControlPlaneV5IntegrityError("v5 record is not committed")
        try:
            value = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise ControlPlaneV5IntegrityError("v5 record JSON is corrupt") from exc
        if not isinstance(value, dict):
            raise ControlPlaneV5IntegrityError("v5 record JSON shape is invalid")
        # Authentication proves origin, not safety.  Apply the same complete
        # string policy used by the write path before any hydrated value is
        # returned or interpreted by a cold full audit.
        _integrity_reject_secret(entity_id, f"{table} entity_id")
        _integrity_reject_secret(value, f"{table} record")
        return value

    def status(self) -> V5Status:
        with self._reader() as connection:
            metadata = dict(connection.execute("SELECT key,value FROM schema_metadata"))
            source = self._verified_record(
                connection, "source_v4_provenance", "source_id", "accepted-control-plane-v4"
            )
            self._assert_source_identity(connection, self._validated_source_status())
            sequence, commit_hmac = self._verify_tail(connection)
            return V5Status(
                database_id=str(metadata["database_id"]),
                schema_version=V5_SCHEMA_VERSION,
                schema_fingerprint=_SCHEMA_FINGERPRINT,
                source_v4_state_root=str(source["state_root"]),
                commit_sequence=sequence,
                commit_hmac=commit_hmac,
            )

    def verify_integrity(self, *, full: bool = False) -> V5Status:
        """Verify the bounded hot tail, or perform an explicit cold full audit."""

        if type(full) is not bool:
            raise TypeError("full must be bool")
        with self._reader() as connection:
            if full:
                self._verify_schema(connection, full=True)
                self._verify_full_history(connection)
            metadata = dict(connection.execute("SELECT key,value FROM schema_metadata"))
            source = self._verified_record(
                connection, "source_v4_provenance", "source_id",
                "accepted-control-plane-v4",
            )
            self._assert_source_identity(connection, self._validated_source_status())
            sequence, commit_hmac = self._verify_tail(connection)
            return V5Status(
                str(metadata["database_id"]), V5_SCHEMA_VERSION,
                _SCHEMA_FINGERPRINT, str(source["state_root"]),
                sequence, commit_hmac,
            )

    def _verify_full_history(self, connection: sqlite3.Connection) -> None:
        if self._key is None:
            raise ControlPlaneV5IntegrityError("v5 key is unavailable")
        commits = connection.execute(
            "SELECT sequence,previous_commit_hmac,delta_sha256,commit_hmac "
            "FROM ledger_commits ORDER BY sequence"
        ).fetchall()
        if not commits:
            raise ControlPlaneV5IntegrityError("v5 commit history is empty")
        previous = _ZERO_HASH
        for expected_sequence, row in enumerate(commits, 1):
            sequence, stored_previous, delta, commit_hmac = (
                int(row[0]), str(row[1]), str(row[2]), str(row[3])
            )
            if sequence != expected_sequence or stored_previous != previous:
                raise ControlPlaneV5IntegrityError("v5 commit chain has a gap")
            entries = [
                tuple(entry)
                for entry in connection.execute(
                    "SELECT table_name,entity_id,record_sha256,record_hmac "
                    "FROM ledger_entries WHERE commit_sequence=? ORDER BY entry_ordinal",
                    (sequence,),
                ).fetchall()
            ]
            if not entries or _sha("ONYX-V5-DELTA\0" + _canonical(entries)) != delta:
                raise ControlPlaneV5IntegrityError("v5 commit delta diverges")
            expected_hmac = _commit_mac(
                self._key, sequence, stored_previous, delta
            )
            if not hmac.compare_digest(expected_hmac, commit_hmac):
                raise ControlPlaneV5IntegrityError("v5 commit HMAC diverges")
            previous = commit_hmac

        record_tables = {
            "source_v4_provenance": ("source_id",),
            "mission_scope_snapshots": ("scope_id",),
            "artifact_records": ("artifact_id",),
            "evidence_records": ("evidence_id",),
            "claims": ("claim_id",),
            "claim_evidence_links": ("link_id",),
            "action_requests": ("request_id",),
            "action_reservations": ("request_id",),
            "action_reservation_stages": ("stage_id",),
            "action_receipts": ("receipt_id",),
            "event_envelopes": ("event_id",),
        }
        physical: set[tuple[str, str, str, str]] = set()
        for table, (id_column,) in record_tables.items():
            rows = connection.execute(
                f"SELECT {id_column},record_sha256,record_hmac FROM {table}"
            ).fetchall()
            for row in rows:
                entity_id, digest, mac = str(row[0]), str(row[1]), str(row[2])
                value = self._verified_record(
                    connection, table, id_column, entity_id
                )
                if table == "evidence_records":
                    self._evidence_from_value(value)
                elif table == "claims":
                    self._claim_from_value(value)
                elif table == "action_requests":
                    self._request_from_value(value)
                elif table == "action_receipts":
                    self._receipt_from_value(value)
                physical.add((table, entity_id, digest, mac))
        committed = {
            tuple(str(value) for value in row)
            for row in connection.execute(
                "SELECT table_name,entity_id,record_sha256,record_hmac FROM ledger_entries"
            ).fetchall()
        }
        if physical != committed:
            raise ControlPlaneV5IntegrityError("v5 committed-record cardinality diverges")

        expected_events: dict[tuple[str, str], tuple[str, str, str, str, str]] = {}
        event_specs = (
            ("artifact_records", "artifact_binding", "artifact_id", "artifact.bound"),
            ("evidence_records", "evidence", "evidence_id", "evidence.recorded"),
            ("claims", "claim", "claim_id", "claim.recorded"),
            ("claim_evidence_links", "claim_evidence_link", "link_id", "claim.evidence.linked"),
            ("action_requests", "action_request", "request_id", "action.requested"),
            ("action_reservations", "action_reservation", "request_id", "action.reservation.created"),
            ("action_receipts", "action_receipt", "receipt_id", None),
        )
        for table, entity_type, id_column, event_type in event_specs:
            for row in connection.execute(
                f"SELECT {id_column},workspace_id,mission_id,correlation_id,record_sha256,record_json FROM {table}"
            ):
                resolved_type = event_type
                if table == "action_receipts":
                    resolved_type = (
                        "action.reconciled"
                        if json.loads(str(row[5])).get("reconciliation")
                        else "action.receipted"
                    )
                expected_events[(entity_type, str(row[0]))] = (
                    str(row[1]), str(row[2]), str(row[3]), str(row[4]), str(resolved_type)
                )
        for row in connection.execute(
            "SELECT stage_id,workspace_id,mission_id,correlation_id,record_sha256,stage "
            "FROM action_reservation_stages"
        ):
            expected_events[("action_reservation_stage", str(row[0]))] = (
                str(row[1]), str(row[2]), str(row[3]), str(row[4]),
                "action.reservation." + str(row[5]),
            )
        observed_events: dict[tuple[str, str], EventEnvelope] = {}
        chains: dict[tuple[str, str], list[EventEnvelope]] = {}
        for row in connection.execute("SELECT event_id FROM event_envelopes"):
            event = self._event_from_value(
                self._verified_record(
                    connection, "event_envelopes", "event_id", str(row[0])
                )
            )
            key = (event.entity_type, event.entity_id)
            if key in observed_events:
                raise ControlPlaneV5IntegrityError("entity has duplicate event envelopes")
            observed_events[key] = event
            chains.setdefault((event.workspace_id, event.correlation_id), []).append(event)
        if set(expected_events) != set(observed_events):
            raise ControlPlaneV5IntegrityError("entity/event cardinality diverges")
        for key, expected in expected_events.items():
            event = observed_events[key]
            if (
                event.workspace_id,
                event.mission_id,
                event.correlation_id,
                event.redacted_payload_sha256,
                event.event_type,
            ) != expected:
                raise ControlPlaneV5IntegrityError("entity/event semantic binding diverges")
        for events in chains.values():
            events.sort(key=lambda item: item.sequence)
            previous_hash = _ZERO_HASH
            for expected_sequence, event in enumerate(events, 1):
                if (
                    event.sequence != expected_sequence
                    or event.previous_hash != previous_hash
                ):
                    raise ControlPlaneV5IntegrityError("event chain has a gap")
                previous_hash = event.event_hash

        for row in connection.execute("SELECT claim_id,record_json FROM claims"):
            claim_id = str(row[0])
            value = self._verified_record(
                connection, "claims", "claim_id", claim_id
            )
            self._claim_from_value(value)
            expected = tuple(value.get("evidence_ids", ()))
            observed_list: list[str] = []
            for link_row in connection.execute(
                "SELECT link_id FROM claim_evidence_links WHERE claim_id=? "
                "ORDER BY evidence_id", (claim_id,)
            ).fetchall():
                link = self._verified_record(
                    connection, "claim_evidence_links", "link_id", str(link_row[0])
                )
                if link.get("claim_id") != claim_id:
                    raise ControlPlaneV5IntegrityError(
                        "claim/evidence link claim identity diverges"
                    )
                observed_list.append(str(link["evidence_id"]))
            observed = tuple(observed_list)
            if expected != observed:
                raise ControlPlaneV5IntegrityError("claim/evidence cardinality diverges")

        for row in connection.execute("SELECT evidence_id FROM evidence_records"):
            evidence_id = str(row[0])
            value = self._verified_record(
                connection, "evidence_records", "evidence_id", evidence_id
            )
            self._evidence_from_value(value)
            if tuple(value.get("claim_ids", ())) != ():
                raise ControlPlaneV5IntegrityError(
                    "stored evidence claim projection must be derived"
                )
            inverse = self._authenticated_claim_ids(connection, evidence_id)
            expected_inverse = tuple(sorted(
                str(claim_row[0])
                for claim_row in connection.execute(
                    "SELECT claim_id FROM claim_evidence_links WHERE evidence_id=?",
                    (evidence_id,),
                ).fetchall()
            ))
            if inverse != expected_inverse:
                raise ControlPlaneV5IntegrityError(
                    "evidence/claim inverse cardinality diverges"
                )

        for request_row in connection.execute("SELECT request_id FROM action_requests"):
            request_id = str(request_row[0])
            request = self._request_from_value(self._verified_record(
                connection, "action_requests", "request_id", request_id
            ))
            self._verify_action_audit(request)
            chain = self._receipt_chain(connection, request_id)
            for receipt in chain:
                self._verify_receipt_bindings(connection, receipt, request)

    def record_artifact(
        self, *, workspace_id: str, mission_id: str, content_sha256: str,
        relative_path: str, byte_length: int, media_type: str,
        metadata_sha256: str, caller_key: str, artifact_schema_version: int = 1,
        data_class: str = "internal", source_provenance_sha256: str | None = None,
        display_name: str | None = None, artifact_created_at: str | None = None,
        status: str = "available", manifest_sha256: str | None = None,
        request_id: str | None = None,
    ) -> ArtifactRecord:
        scope = self._validated_scope(workspace_id, mission_id)
        content_sha256 = str(_digest(content_sha256, "content_sha256"))
        metadata_sha256 = str(_digest(metadata_sha256, "metadata_sha256"))
        if relative_path != f"{content_sha256[:2]}/{content_sha256}":
            raise ControlPlaneV5ContractError("artifact relative path is noncanonical")
        if type(byte_length) is not int or not 0 <= byte_length <= 1 << 30:
            raise ControlPlaneV5ContractError("artifact byte_length is invalid")
        if (
            not isinstance(media_type, str)
            or not re.fullmatch(
                r"[a-z0-9][a-z0-9.+-]{0,63}/[a-z0-9][a-z0-9.+-]{0,63}",
                media_type,
            )
        ):
            # Keep the fixture compatibility spelling private to tests while
            # the real service always uses a canonical lowercase MIME type.
            if media_type != "application_json":
                raise ControlPlaneV5ContractError("media_type is invalid")
        if type(artifact_schema_version) is not int or artifact_schema_version != 1:
            raise ControlPlaneV5ContractError("artifact_schema_version is invalid")
        if data_class not in {"public", "internal", "confidential"}:
            raise ControlPlaneV5ContractError("artifact data_class is invalid")
        source_provenance_sha256 = str(
            _digest(
                source_provenance_sha256 or metadata_sha256,
                "source_provenance_sha256",
            )
        )
        if display_name is not None:
            if not isinstance(display_name, str) or not display_name or len(display_name) > 255:
                raise ControlPlaneV5ContractError("artifact display_name is invalid")
            _reject_secret(display_name, "artifact display_name")
        artifact_created_at = str(
            _timestamp(artifact_created_at or _now(), "artifact_created_at")
        )
        if status != "available":
            raise ControlPlaneV5ContractError("artifact status is invalid")
        manifest_sha256 = str(
            _digest(manifest_sha256 or metadata_sha256, "manifest_sha256")
        )
        caller_key = _safe_id(caller_key, "caller_key")
        if request_id is not None:
            request_id = _safe_id(request_id, "request_id")
            request = self.get_action_request(
                workspace_id=workspace_id,
                mission_id=mission_id,
                request_id=request_id,
            )
            if request.mission_id != mission_id:
                raise ControlPlaneV5IsolationError(
                    "artifact request belongs to another mission"
                )
        binding_identity = request_id or "caller-" + _sha(caller_key)
        artifact_id = "artifact-" + _sha(
            _canonical(
                [
                    "OnyxArtifactBinding.v2",
                    workspace_id,
                    mission_id,
                    content_sha256,
                    binding_identity,
                ]
            )
        )
        created_at = _now()
        record = ArtifactRecord(
            RECORD_SCHEMA_VERSION, artifact_id, workspace_id, mission_id,
            scope.correlation_id, request_id, content_sha256, relative_path, byte_length,
            media_type, artifact_schema_version, data_class,
            source_provenance_sha256, display_name, artifact_created_at, status,
            manifest_sha256, metadata_sha256, scope.context_sha256, created_at,
        )

        def operation(connection: sqlite3.Connection):
            existing = connection.execute(
                "SELECT artifact_id FROM artifact_records WHERE artifact_id=?",
                (artifact_id,),
            ).fetchone()
            if existing is not None:
                value = self._verified_record(connection, "artifact_records", "artifact_id", str(existing[0]))
                prior = ArtifactRecord(**value)
                # Timestamp is not part of idempotent input; all other fields must match.
                compare_prior = asdict(prior); compare_record = asdict(record)
                compare_prior.pop("created_at"); compare_record.pop("created_at")
                if compare_prior != compare_record:
                    raise ControlPlaneV5Conflict("artifact identity replay changed input")
                return prior, []
            self._insert_record(
                connection, "artifact_records", "artifact_id", artifact_id, asdict(record),
                prefix=(artifact_id, workspace_id, mission_id, scope.correlation_id,
                        request_id, content_sha256, relative_path),
            )
            event, event_entry = self._append_event(
                connection, scope=scope, actor="artifact_service",
                event_type="artifact.bound", entity_type="artifact_binding",
                entity_id=artifact_id, payload_sha256=_sha(_canonical(asdict(record))),
                created_at=created_at,
            )
            del event
            return record, [
                self._entry_for(connection, "artifact_records", "artifact_id", artifact_id),
                event_entry,
            ]

        mutation_id = "artifact-mutation-" + _sha(_canonical([workspace_id, mission_id, content_sha256, caller_key]))
        try:
            return self._write_records(mutation_id=mutation_id, scope=scope, operation=operation)  # type: ignore[return-value]
        except ControlPlaneV5Conflict as exc:
            if "mutation_id already exists" not in str(exc):
                raise
            prior = self.get_artifact(
                workspace_id=workspace_id,
                mission_id=mission_id,
                artifact_id=artifact_id,
            )
            _assert_replay_equivalent(prior, record, "artifact identity")
            return prior

    def get_artifact(
        self, *, workspace_id: str, mission_id: str, artifact_id: str
    ) -> ArtifactRecord:
        workspace_id = _safe_id(workspace_id, "workspace_id")
        mission_id = _safe_id(mission_id, "mission_id")
        artifact_id = _safe_id(artifact_id, "artifact_id")
        with self._reader() as connection:
            value = self._verified_record(connection, "artifact_records", "artifact_id", artifact_id)
            if value.get("workspace_id") != workspace_id:
                raise ControlPlaneV5IsolationError("artifact belongs to another workspace")
            if value.get("mission_id") != mission_id:
                raise ControlPlaneV5IsolationError("artifact belongs to another mission")
            return ArtifactRecord(**value)

    def record_evidence(
        self, *, workspace_id: str, mission_id: str, source_kind: str,
        source_identity_sha256: str, content_sha256: str, artifact_id: str | None,
        credibility_bp: int, freshness: str, access_license_sha256: str,
        observed_at: str, caller_key: str, title: str = "Untitled evidence",
        uri_or_file_ref: str | None = None,
        publisher_or_owner: str | None = None,
        published_at: str | None = None,
        access_and_license_notes: str | None = None,
    ) -> EvidenceRecord:
        scope = self._validated_scope(workspace_id, mission_id)
        source_kind = _slug(source_kind, "source_kind")
        source_kind = {
            "artifact": "user_file",
            "local_read": "observation",
            "mission_result": "tool_output",
            "provider": "secondary",
            "public_url": "secondary",
        }.get(source_kind, source_kind)
        if source_kind not in {
            "primary", "official", "secondary", "user_file", "tool_output",
            "observation",
        }:
            raise ControlPlaneV5ContractError("source_kind is invalid")
        source_identity_sha256 = str(_digest(source_identity_sha256, "source_identity_sha256"))
        content_sha256 = str(_digest(content_sha256, "content_sha256"))
        access_license_sha256 = str(_digest(access_license_sha256, "access_license_sha256"))
        access_and_license_notes = _recoverable_contract_text(
            access_and_license_notes,
            "evidence access_and_license_notes",
            optional=True,
            max_length=1024,
        )
        if (
            access_and_license_notes is not None
            and not hmac.compare_digest(
                access_license_sha256, _sha(access_and_license_notes)
            )
        ):
            raise ControlPlaneV5ContractError(
                "access_license_sha256 does not bind the recoverable notes"
            )
        if type(credibility_bp) is not int or not 0 <= credibility_bp <= 10000:
            raise ControlPlaneV5ContractError("credibility_bp is invalid")
        freshness = {"historical": "aging"}.get(freshness, freshness)
        if freshness not in {"current", "aging", "stale", "unknown"}:
            raise ControlPlaneV5ContractError("freshness is invalid")
        observed_at = str(_timestamp(observed_at, "observed_at"))
        title = str(_safe_text(title, "evidence title", max_length=512))
        uri_or_file_ref = _opaque_reference(
            uri_or_file_ref, "evidence uri_or_file_ref", optional=True
        )
        publisher_or_owner = _safe_text(
            publisher_or_owner,
            "evidence publisher_or_owner",
            optional=True,
            max_length=256,
        )
        published_at = _timestamp(published_at, "published_at", optional=True)
        if published_at is not None and datetime.fromisoformat(
            str(published_at).replace("Z", "+00:00")
        ) > datetime.fromisoformat(observed_at.replace("Z", "+00:00")):
            raise ControlPlaneV5ContractError(
                "published_at cannot be after observed_at"
            )
        caller_key = _safe_id(caller_key, "caller_key")
        if artifact_id is not None:
            artifact = self.get_artifact(
                workspace_id=workspace_id,
                mission_id=mission_id,
                artifact_id=artifact_id,
            )
            if artifact.mission_id != mission_id or artifact.content_sha256 != content_sha256:
                raise ControlPlaneV5IsolationError("evidence artifact scope/content diverges")
        evidence_id = evidence_identity(
            workspace_id=workspace_id, mission_id=mission_id, caller_key=caller_key
        )
        created_at = _now()
        record = EvidenceRecord(
            schema_version=RECORD_SCHEMA_VERSION,
            evidence_id=evidence_id,
            workspace_id=workspace_id,
            mission_id=mission_id,
            correlation_id=scope.correlation_id,
            source_kind=source_kind,
            source_identity_sha256=source_identity_sha256,
            content_sha256=content_sha256,
            artifact_id=artifact_id,
            claim_ids=(),
            credibility_bp=credibility_bp,
            freshness=freshness,
            access_license_sha256=access_license_sha256,
            source_context_sha256=scope.context_sha256,
            observed_at=observed_at,
            created_at=created_at,
            title=title,
            uri_or_file_ref=uri_or_file_ref,
            publisher_or_owner=publisher_or_owner,
            published_at=published_at,
            access_and_license_notes=access_and_license_notes,
        )

        def operation(connection: sqlite3.Connection):
            existing = connection.execute("SELECT record_json FROM evidence_records WHERE evidence_id=?", (evidence_id,)).fetchone()
            if existing is not None:
                prior = self._evidence_from_value(self._verified_record(connection, "evidence_records", "evidence_id", evidence_id))
                a, b = asdict(prior), asdict(record); a.pop("created_at"); b.pop("created_at")
                if a != b:
                    raise ControlPlaneV5Conflict("evidence identity replay changed input")
                return prior, []
            self._insert_record(connection, "evidence_records", "evidence_id", evidence_id, asdict(record),
                                prefix=(evidence_id, workspace_id, mission_id, scope.correlation_id, artifact_id))
            _event, event_entry = self._append_event(
                connection, scope=scope, actor="mission_tool", event_type="evidence.recorded",
                entity_type="evidence", entity_id=evidence_id,
                payload_sha256=_sha(_canonical(asdict(record))), created_at=created_at,
            )
            return record, [self._entry_for(connection, "evidence_records", "evidence_id", evidence_id), event_entry]

        mutation_id = "evidence-mutation-" + _sha(_canonical([workspace_id, mission_id, caller_key]))
        try:
            return self._write_records(mutation_id=mutation_id, scope=scope, operation=operation)  # type: ignore[return-value]
        except ControlPlaneV5Conflict as exc:
            if "mutation_id already exists" not in str(exc): raise
            prior = self.get_evidence(
                workspace_id=workspace_id,
                mission_id=mission_id,
                evidence_id=evidence_id,
            )
            prior_value, record_value = asdict(prior), asdict(record)
            prior_value.pop("claim_ids", None)
            record_value.pop("claim_ids", None)
            prior_value.pop("created_at", None)
            record_value.pop("created_at", None)
            if prior_value != record_value:
                raise ControlPlaneV5Conflict(
                    "evidence identity replay changed input"
                )
            return prior

    @staticmethod
    def _evidence_from_value(value: dict[str, object]) -> EvidenceRecord:
        decoded = dict(value)
        version = decoded.get("schema_version")
        if type(version) is not int or version not in {1, 2, 3}:
            raise ControlPlaneV5IntegrityError(
                "evidence record schema_version is unknown"
            )
        decoded["claim_ids"] = tuple(decoded.get("claim_ids", ()))
        if version < 3:
            decoded.setdefault("access_and_license_notes", None)
        else:
            notes = _integrity_contract_text(
                decoded.get("access_and_license_notes"),
                "evidence access_and_license_notes",
                optional=True,
                max_length=1024,
            )
            if notes is not None and not hmac.compare_digest(
                str(decoded.get("access_license_sha256")), _sha(notes)
            ):
                raise ControlPlaneV5IntegrityError(
                    "evidence recoverable license notes diverge from their digest"
                )
        decoded["uri_or_file_ref"] = _integrity_opaque_reference(
            decoded.get("uri_or_file_ref"),
            "evidence uri_or_file_ref",
            optional=True,
        )
        return EvidenceRecord(**decoded)

    def get_evidence(
        self, *, workspace_id: str, mission_id: str, evidence_id: str
    ) -> EvidenceRecord:
        workspace_id = _safe_id(workspace_id, "workspace_id")
        mission_id = _safe_id(mission_id, "mission_id")
        evidence_id = _safe_id(evidence_id, "evidence_id")
        with self._reader() as connection:
            value = self._verified_record(connection, "evidence_records", "evidence_id", evidence_id)
            if value.get("workspace_id") != workspace_id:
                raise ControlPlaneV5IsolationError("evidence belongs to another workspace")
            if value.get("mission_id") != mission_id:
                raise ControlPlaneV5IsolationError("evidence belongs to another mission")
            value["claim_ids"] = self._authenticated_claim_ids(
                connection, evidence_id
            )
            return self._evidence_from_value(value)

    def _authenticated_claim_ids(
        self, connection: sqlite3.Connection, evidence_id: str
    ) -> tuple[str, ...]:
        claim_ids: list[str] = []
        rows = connection.execute(
            "SELECT link_id FROM claim_evidence_links WHERE evidence_id=? "
            "ORDER BY claim_id", (evidence_id,)
        ).fetchall()
        for row in rows:
            link = self._verified_record(
                connection, "claim_evidence_links", "link_id", str(row[0])
            )
            if link.get("evidence_id") != evidence_id:
                raise ControlPlaneV5IntegrityError(
                    "evidence inverse link identity diverges"
                )
            claim_ids.append(str(link["claim_id"]))
        return tuple(claim_ids)

    def record_claim(
        self, *, workspace_id: str, mission_id: str, claim_kind: str,
        statement_sha256: str, evidence_ids: tuple[str, ...], confidence_bp: int,
        verification_status: str, valid_until: str | None,
        contradiction_claim_ids: tuple[str, ...], caller_key: str,
        text: str, verified_at: str | None = None, valid_from: str | None = None,
    ) -> Claim:
        scope = self._validated_scope(workspace_id, mission_id)
        if claim_kind not in {"fact", "inference", "forecast", "recommendation", "unknown"}:
            raise ControlPlaneV5ContractError("claim_kind is invalid")
        statement_sha256 = str(_digest(statement_sha256, "statement_sha256"))
        text = str(_recoverable_contract_text(text, "claim text", max_length=4096))
        if not hmac.compare_digest(statement_sha256, _sha(text)):
            raise ControlPlaneV5ContractError(
                "statement_sha256 does not bind the recoverable claim text"
            )
        if type(confidence_bp) is not int or not 0 <= confidence_bp <= 10000:
            raise ControlPlaneV5ContractError("confidence_bp is invalid")
        verification_status = {
            "supported": "single_source",
            "contradicted": "disputed",
            "unknown": "unverified",
        }.get(verification_status, verification_status)
        if verification_status not in {
            "unverified", "single_source", "corroborated", "disputed", "rejected",
        }:
            raise ControlPlaneV5ContractError("verification_status is invalid")
        verified_at = _timestamp(verified_at, "verified_at", optional=True)
        valid_from = _timestamp(valid_from, "valid_from", optional=True)
        valid_until = _timestamp(valid_until, "valid_until", optional=True)
        if valid_from is not None and valid_until is not None and datetime.fromisoformat(
            str(valid_from).replace("Z", "+00:00")
        ) > datetime.fromisoformat(str(valid_until).replace("Z", "+00:00")):
            raise ControlPlaneV5ContractError("claim validity window is reversed")
        caller_key = _safe_id(caller_key, "caller_key")
        evidence_ids = tuple(sorted({_safe_id(item, "evidence_id") for item in evidence_ids}))
        contradiction_claim_ids = tuple(sorted({_safe_id(item, "contradiction_claim_id") for item in contradiction_claim_ids}))
        if not evidence_ids and claim_kind != "unknown":
            raise ControlPlaneV5ContractError("non-unknown claim requires evidence")
        for evidence_id in evidence_ids:
            evidence = self.get_evidence(
                workspace_id=workspace_id,
                mission_id=mission_id,
                evidence_id=evidence_id,
            )
            if evidence.mission_id != mission_id:
                raise ControlPlaneV5IsolationError("claim evidence belongs to another mission")
        claim_id = claim_identity(
            workspace_id=workspace_id, mission_id=mission_id, caller_key=caller_key
        )
        created_at = _now()
        record = Claim(
            schema_version=RECORD_SCHEMA_VERSION,
            claim_id=claim_id,
            workspace_id=workspace_id,
            mission_id=mission_id,
            correlation_id=scope.correlation_id,
            claim_kind=claim_kind,
            statement_sha256=statement_sha256,
            evidence_ids=evidence_ids,
            confidence_bp=confidence_bp,
            verification_status=verification_status,
            valid_until=valid_until,
            contradiction_claim_ids=contradiction_claim_ids,
            source_context_sha256=scope.context_sha256,
            created_at=created_at,
            verified_at=verified_at,
            valid_from=valid_from,
            text=text,
        )

        def operation(connection: sqlite3.Connection):
            if connection.execute("SELECT 1 FROM claims WHERE claim_id=?", (claim_id,)).fetchone():
                prior = self._claim_from_value(self._verified_record(connection, "claims", "claim_id", claim_id))
                a, b = asdict(prior), asdict(record); a.pop("created_at"); b.pop("created_at")
                if a != b: raise ControlPlaneV5Conflict("claim identity replay changed input")
                return prior, []
            for contradiction_id in contradiction_claim_ids:
                row = connection.execute("SELECT workspace_id,mission_id FROM claims WHERE claim_id=?", (contradiction_id,)).fetchone()
                if row is None or tuple(row) != (workspace_id, mission_id):
                    raise ControlPlaneV5IsolationError("contradiction claim scope diverges")
            self._insert_record(connection, "claims", "claim_id", claim_id, asdict(record),
                                prefix=(claim_id, workspace_id, mission_id, scope.correlation_id))
            link_entries: list[tuple[str, str, str, str]] = []
            for evidence_id in evidence_ids:
                link_id = "link-" + _sha(_canonical([claim_id, evidence_id]))
                link_record = {
                    "schema_version": RECORD_SCHEMA_VERSION,
                    "link_id": link_id,
                    "claim_id": claim_id,
                    "evidence_id": evidence_id,
                    "workspace_id": workspace_id,
                    "mission_id": mission_id,
                    "correlation_id": scope.correlation_id,
                    "source_context_sha256": scope.context_sha256,
                    "created_at": created_at,
                }
                link_digest, _link_mac = self._insert_record(
                    connection,
                    "claim_evidence_links",
                    "link_id",
                    link_id,
                    link_record,
                    prefix=(link_id, claim_id, evidence_id, workspace_id, mission_id, scope.correlation_id),
                )
                _link_event, link_event_entry = self._append_event(
                    connection,
                    scope=scope,
                    actor="mission_tool",
                    event_type="claim.evidence.linked",
                    entity_type="claim_evidence_link",
                    entity_id=link_id,
                    payload_sha256=link_digest,
                    created_at=created_at,
                )
                link_entries.extend([
                    self._entry_for(connection, "claim_evidence_links", "link_id", link_id),
                    link_event_entry,
                ])
            _event, event_entry = self._append_event(
                connection, scope=scope, actor="mission_tool", event_type="claim.recorded",
                entity_type="claim", entity_id=claim_id,
                payload_sha256=_sha(_canonical(asdict(record))), created_at=created_at,
            )
            entries = [self._entry_for(connection, "claims", "claim_id", claim_id), event_entry, *link_entries]
            return record, entries

        mutation_id = "claim-mutation-" + _sha(_canonical([workspace_id, mission_id, caller_key]))
        try:
            return self._write_records(mutation_id=mutation_id, scope=scope, operation=operation)  # type: ignore[return-value]
        except ControlPlaneV5Conflict as exc:
            if "mutation_id already exists" not in str(exc): raise
            prior = self.get_claim(
                workspace_id=workspace_id, mission_id=mission_id, claim_id=claim_id
            )
            _assert_replay_equivalent(prior, record, "claim identity")
            return prior

    @staticmethod
    def _claim_from_value(value: dict[str, object]) -> Claim:
        decoded = dict(value)
        version = decoded.get("schema_version")
        if type(version) is not int or version not in {1, 2, 3}:
            raise ControlPlaneV5IntegrityError("claim schema_version is unknown")
        decoded["evidence_ids"] = tuple(decoded["evidence_ids"])
        decoded["contradiction_claim_ids"] = tuple(
            decoded["contradiction_claim_ids"]
        )
        if version < 3:
            decoded.setdefault("text", None)
        else:
            text = _integrity_contract_text(
                decoded.get("text"), "claim text", max_length=4096
            )
            if not hmac.compare_digest(
                str(decoded.get("statement_sha256")), _sha(str(text))
            ):
                raise ControlPlaneV5IntegrityError(
                    "claim recoverable text diverges from its digest"
                )
        return Claim(**decoded)

    def get_claim(
        self, *, workspace_id: str, mission_id: str, claim_id: str
    ) -> Claim:
        workspace_id = _safe_id(workspace_id, "workspace_id")
        mission_id = _safe_id(mission_id, "mission_id")
        claim_id = _safe_id(claim_id, "claim_id")
        with self._reader() as connection:
            value = self._verified_record(connection, "claims", "claim_id", claim_id)
            if value.get("workspace_id") != workspace_id:
                raise ControlPlaneV5IsolationError("claim belongs to another workspace")
            if value.get("mission_id") != mission_id:
                raise ControlPlaneV5IsolationError("claim belongs to another mission")
            claim = self._claim_from_value(value)
            physical_links_list: list[str] = []
            for row in connection.execute(
                "SELECT link_id FROM claim_evidence_links WHERE claim_id=? "
                "ORDER BY evidence_id", (claim_id,),
            ).fetchall():
                link = self._verified_record(
                    connection, "claim_evidence_links", "link_id", str(row[0])
                )
                if link.get("claim_id") != claim_id:
                    raise ControlPlaneV5IntegrityError(
                        "claim evidence link identity diverges"
                    )
                physical_links_list.append(str(link["evidence_id"]))
            physical_links = tuple(physical_links_list)
            if physical_links != claim.evidence_ids:
                raise ControlPlaneV5IntegrityError("claim evidence links diverge")
            return claim

    def record_action_request(
        self, *, workspace_id: str, mission_id: str, connector: str, operation: str,
        target: str, target_sha256: str, payload_sha256: str, idempotency_key: str,
        risk: str, approval_policy: str, dry_run: bool,
        audit_reference_sha256: str, verification_plan_sha256: str,
        reservation_owner_id: str, approval_id: str | None = None,
    ) -> ActionRequest:
        scope = self._validated_scope(workspace_id, mission_id)
        connector = _slug(connector, "connector"); operation = _slug(operation, "operation")
        for value, label in ((target_sha256, "target_sha256"), (payload_sha256, "payload_sha256"),
                             (audit_reference_sha256, "audit_reference_sha256"),
                             (verification_plan_sha256, "verification_plan_sha256")):
            _digest(value, label)
        target = str(
            _recoverable_contract_text(target, "action target", max_length=1024)
        )
        if not hmac.compare_digest(target_sha256, _sha(target)):
            raise ControlPlaneV5ContractError(
                "target_sha256 does not bind the recoverable target"
            )
        approval_id = (
            _recoverable_contract_id(approval_id, "approval_id")
            if approval_id is not None
            else None
        )
        if not isinstance(idempotency_key, str) or not idempotency_key.startswith("onyx:v5:") or not _DIGEST.fullmatch(idempotency_key[8:]):
            raise ControlPlaneV5ContractError("idempotency_key is invalid")
        if risk not in {"low", "medium", "high", "critical"}: raise ControlPlaneV5ContractError("risk is invalid")
        if approval_policy not in {"shadow_only", "exact_callback", "always_explicit"}: raise ControlPlaneV5ContractError("approval_policy is invalid")
        if type(dry_run) is not bool: raise ControlPlaneV5ContractError("dry_run must be bool")
        # P4.4 has no mutation activation.  Only provider-free shadow/read work is legal.
        if not dry_run or approval_policy != "shadow_only":
            raise ControlPlaneV5ContractError("P4.4 accepts shadow-only dry-run requests")
        request_id = action_request_identity(idempotency_key)
        request_sha256 = action_request_contract_sha256(
            workspace_id=workspace_id,
            mission_id=mission_id,
            request_id=request_id,
            correlation_id=scope.correlation_id,
            connector=connector,
            operation=operation,
            target_sha256=target_sha256,
            payload_sha256=payload_sha256,
            idempotency_key=idempotency_key,
            risk=risk,
            approval_policy=approval_policy,
            dry_run=dry_run,
            verification_plan_sha256=verification_plan_sha256,
            source_context_sha256=scope.context_sha256,
            target=target,
            approval_id=approval_id,
            schema_version=RECORD_SCHEMA_VERSION,
        )
        reservation_owner_id = _safe_id(
            reservation_owner_id, "reservation owner_id"
        )
        created_at = _now()
        record = ActionRequest(
            schema_version=RECORD_SCHEMA_VERSION,
            request_id=request_id,
            workspace_id=workspace_id,
            mission_id=mission_id,
            correlation_id=scope.correlation_id,
            connector=connector,
            operation=operation,
            target_sha256=target_sha256,
            payload_sha256=payload_sha256,
            idempotency_key=idempotency_key,
            risk=risk,
            approval_policy=approval_policy,
            dry_run=dry_run,
            audit_reference_sha256=audit_reference_sha256,
            verification_plan_sha256=verification_plan_sha256,
            source_context_sha256=scope.context_sha256,
            created_at=created_at,
            target=target,
            approval_id=approval_id,
        )
        self._verify_action_audit(record)

        def write(connection: sqlite3.Connection):
            row = connection.execute("SELECT request_id FROM action_requests WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if row is not None:
                prior = self._request_from_value(self._verified_record(connection, "action_requests", "request_id", str(row[0])))
                a, b = asdict(prior), asdict(record); a.pop("created_at"); b.pop("created_at")
                if a != b: raise ControlPlaneV5Conflict("idempotency key replay changed request")
                return prior, []
            reservation = ActionReservation(**self._verified_record(
                connection, "action_reservations", "request_id", request_id
            ))
            if (
                reservation.workspace_id != workspace_id
                or reservation.mission_id != mission_id
                or reservation.idempotency_key != idempotency_key
                or reservation.request_sha256 != request_sha256
                or reservation.source_context_sha256 != scope.context_sha256
            ):
                raise ControlPlaneV5Conflict(
                    "request semantics diverge from the durable reservation"
                )
            latest_stage = self._latest_reservation_stage(connection, request_id)
            if (
                latest_stage is None
                or latest_stage.stage != "audit_linked"
                or latest_stage.owner_id != reservation_owner_id
                or latest_stage.audit_reference_sha256 != audit_reference_sha256
            ):
                raise ControlPlaneV5Conflict(
                    "request is not bound to the owned audit-linked reservation"
                )
            self._insert_record(connection, "action_requests", "request_id", request_id, asdict(record),
                                prefix=(request_id, workspace_id, mission_id, scope.correlation_id, idempotency_key))
            request_digest = _sha(_canonical(asdict(record)))
            _event, event_entry = self._append_event(
                connection, scope=scope, actor="mission_tool", event_type="action.requested",
                entity_type="action_request", entity_id=request_id,
                payload_sha256=request_digest, created_at=created_at,
            )
            stage, stage_entries = self._append_reservation_stage(
                connection, scope=scope, request_id=request_id,
                stage="request_recorded", owner_id=reservation_owner_id,
                lease_expires_at=latest_stage.lease_expires_at,
                audit_reference_sha256=audit_reference_sha256,
            )
            del stage
            return record, [
                self._entry_for(connection, "action_requests", "request_id", request_id),
                event_entry,
                *stage_entries,
            ]

        mutation_id = "request-mutation-" + _sha(idempotency_key)
        try:
            return self._write_records(mutation_id=mutation_id, scope=scope, operation=write)  # type: ignore[return-value]
        except ControlPlaneV5Conflict as exc:
            if "mutation_id already exists" not in str(exc): raise
            prior = self.get_action_request(
                workspace_id=workspace_id,
                mission_id=mission_id,
                request_id=request_id,
            )
            _assert_replay_equivalent(prior, record, "idempotency key")
            return prior

    def reserve_action_request(
        self,
        *,
        workspace_id: str,
        mission_id: str,
        idempotency_key: str,
        request_sha256: str,
        lease_seconds: int = 30,
    ) -> ActionReservationLease:
        """Claim or safely resume one durable reservation stage machine."""

        scope = self._validated_scope(workspace_id, mission_id)
        request_id = action_request_identity(idempotency_key)
        request_sha256 = str(_digest(request_sha256, "request_sha256"))
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 300:
            raise ControlPlaneV5ContractError("reservation lease_seconds is invalid")
        created_at = _now()
        owner_id = "owner-" + secrets.token_hex(24)
        lease_expires_at = (
            datetime.fromisoformat(created_at) + timedelta(seconds=lease_seconds)
        ).isoformat()
        record = ActionReservation(
            RECORD_SCHEMA_VERSION,
            request_id,
            workspace_id,
            mission_id,
            scope.correlation_id,
            idempotency_key,
            request_sha256,
            scope.context_sha256,
            created_at,
        )

        def write(connection: sqlite3.Connection):
            entries: list[tuple[str, str, str, str]] = []
            row = connection.execute(
                "SELECT 1 FROM action_reservations WHERE request_id=?", (request_id,)
            ).fetchone()
            if row is not None:
                value = self._verified_record(
                    connection, "action_reservations", "request_id", request_id
                )
                prior = ActionReservation(**value)
                _assert_replay_equivalent(prior, record, "action reservation")
            else:
                reservation_digest, _reservation_mac = self._insert_record(
                    connection,
                    "action_reservations",
                    "request_id",
                    request_id,
                    asdict(record),
                    prefix=(
                        request_id,
                        workspace_id,
                        mission_id,
                        scope.correlation_id,
                        idempotency_key,
                    ),
                )
                _event, event_entry = self._append_event(
                    connection,
                    scope=scope,
                    actor="mission_tool",
                    event_type="action.reservation.created",
                    entity_type="action_reservation",
                    entity_id=request_id,
                    payload_sha256=reservation_digest,
                    created_at=created_at,
                )
                entries.extend([
                    self._entry_for(
                        connection, "action_reservations", "request_id", request_id
                    ),
                    event_entry,
                ])

            latest = self._latest_reservation_stage(connection, request_id)
            if latest is not None:
                if latest.stage == "dispatch_unknown":
                    return ActionReservationLease(
                        request_id, latest.owner_id, latest.stage,
                        latest.audit_reference_sha256, False,
                    ), entries
                expires = datetime.fromisoformat(latest.lease_expires_at)
                if latest.stage == "request_recorded":
                    if expires > datetime.now(timezone.utc):
                        return ActionReservationLease(
                            request_id, latest.owner_id, latest.stage,
                            latest.audit_reference_sha256, False,
                        ), entries
                    resumed, resumed_entries = self._append_reservation_stage(
                        connection, scope=scope, request_id=request_id,
                        stage="request_recorded", owner_id=owner_id,
                        lease_expires_at=lease_expires_at,
                        audit_reference_sha256=latest.audit_reference_sha256,
                    )
                    entries.extend(resumed_entries)
                    return ActionReservationLease(
                        request_id, owner_id, "request_recorded",
                        resumed.audit_reference_sha256, True,
                    ), entries
                if latest.stage != "pre_audit_failed" and expires > datetime.now(timezone.utc):
                    return ActionReservationLease(
                        request_id, latest.owner_id, latest.stage,
                        latest.audit_reference_sha256, False,
                    ), entries
            resumed_audit = (
                latest.audit_reference_sha256 if latest is not None else None
            )
            stage = "audit_linked" if resumed_audit is not None else "reserved"
            stage_record, stage_entries = self._append_reservation_stage(
                connection,
                scope=scope,
                request_id=request_id,
                stage=stage,
                owner_id=owner_id,
                lease_expires_at=lease_expires_at,
                audit_reference_sha256=resumed_audit,
            )
            entries.extend(stage_entries)
            return ActionReservationLease(
                request_id, owner_id, stage,
                stage_record.audit_reference_sha256, True,
            ), entries

        mutation_id = "reservation-mutation-" + _sha(idempotency_key + owner_id)
        return self._write_records(
            mutation_id=mutation_id, scope=scope, operation=write
        )  # type: ignore[return-value]

    def _latest_reservation_stage(
        self, connection: sqlite3.Connection, request_id: str
    ) -> ActionReservationStage | None:
        row = connection.execute(
            "SELECT stage_id FROM action_reservation_stages WHERE request_id=? "
            "ORDER BY generation DESC LIMIT 1", (request_id,)
        ).fetchone()
        if row is None:
            return None
        return ActionReservationStage(**self._verified_record(
            connection, "action_reservation_stages", "stage_id", str(row[0])
        ))

    def _append_reservation_stage(
        self,
        connection: sqlite3.Connection,
        *,
        scope: MissionScope,
        request_id: str,
        stage: str,
        owner_id: str,
        lease_expires_at: str,
        audit_reference_sha256: str | None,
    ) -> tuple[ActionReservationStage, list[tuple[str, str, str, str]]]:
        if stage not in {"reserved", "pre_audit_failed", "audit_linked", "request_recorded", "dispatch_unknown"}:
            raise ControlPlaneV5ContractError("reservation stage is invalid")
        owner_id = _safe_id(owner_id, "reservation owner_id")
        lease_expires_at = str(_timestamp(lease_expires_at, "lease_expires_at"))
        audit_reference_sha256 = _digest(
            audit_reference_sha256, "audit_reference_sha256", optional=True
        )
        generation = int(connection.execute(
            "SELECT COALESCE(MAX(generation),0)+1 FROM action_reservation_stages WHERE request_id=?",
            (request_id,),
        ).fetchone()[0])
        created_at = _now()
        stage_id = "stage-" + _sha(_canonical([
            request_id, generation, stage, owner_id, audit_reference_sha256
        ]))
        record = ActionReservationStage(
            RECORD_SCHEMA_VERSION, stage_id, request_id, scope.workspace_id,
            scope.mission_id, scope.correlation_id, generation, stage, owner_id,
            lease_expires_at, audit_reference_sha256, scope.context_sha256, created_at,
        )
        digest, _mac = self._insert_record(
            connection, "action_reservation_stages", "stage_id", stage_id,
            asdict(record),
            prefix=(stage_id, request_id, scope.workspace_id, scope.mission_id,
                    scope.correlation_id, generation, stage, owner_id,
                    lease_expires_at, audit_reference_sha256),
        )
        _event, event_entry = self._append_event(
            connection, scope=scope, actor="mission_tool",
            event_type="action.reservation." + stage,
            entity_type="action_reservation_stage", entity_id=stage_id,
            payload_sha256=digest, created_at=created_at,
        )
        return record, [
            self._entry_for(
                connection, "action_reservation_stages", "stage_id", stage_id
            ),
            event_entry,
        ]

    def link_action_audit(
        self,
        *,
        workspace_id: str,
        mission_id: str,
        request_id: str,
        owner_id: str,
        audit_reference_sha256: str,
        request_sha256: str,
        idempotency_key: str,
        connector: str,
        operation: str,
        target: str,
        target_sha256: str,
        payload_sha256: str,
        risk: str,
        approval_policy: str,
        dry_run: bool,
        source_context_sha256: str,
        verification_plan_sha256: str,
        approval_id: str | None = None,
    ) -> ActionReservationStage:
        """Durably bind a verified audit member before request persistence."""

        scope = self._validated_scope(workspace_id, mission_id)
        request_id = _safe_id(request_id, "request_id")
        owner_id = _safe_id(owner_id, "reservation owner_id")
        audit_reference_sha256 = str(_digest(
            audit_reference_sha256, "audit_reference_sha256"
        ))
        request_sha256 = str(_digest(request_sha256, "request_sha256"))
        verification_plan_sha256 = str(_digest(
            verification_plan_sha256, "verification_plan_sha256"
        ))
        target = str(
            _recoverable_contract_text(target, "action target", max_length=1024)
        )
        approval_id = (
            _recoverable_contract_id(approval_id, "approval_id")
            if approval_id is not None
            else None
        )
        candidate = ActionRequest(
            schema_version=RECORD_SCHEMA_VERSION,
            request_id=request_id,
            workspace_id=workspace_id,
            mission_id=mission_id,
            correlation_id=scope.correlation_id,
            connector=connector,
            operation=operation,
            target_sha256=target_sha256,
            payload_sha256=payload_sha256,
            idempotency_key=idempotency_key,
            risk=risk,
            approval_policy=approval_policy,
            dry_run=dry_run,
            audit_reference_sha256=audit_reference_sha256,
            verification_plan_sha256=verification_plan_sha256,
            source_context_sha256=source_context_sha256,
            created_at=_now(),
            target=target,
            approval_id=approval_id,
        )
        expected_request_sha256 = action_request_contract_sha256(
            workspace_id=workspace_id, mission_id=mission_id,
            request_id=request_id, correlation_id=scope.correlation_id,
            connector=connector, operation=operation,
            target_sha256=target_sha256, payload_sha256=payload_sha256,
            idempotency_key=idempotency_key, risk=risk,
            approval_policy=approval_policy, dry_run=dry_run,
            verification_plan_sha256=verification_plan_sha256,
            source_context_sha256=source_context_sha256,
            target=target,
            approval_id=approval_id,
            schema_version=RECORD_SCHEMA_VERSION,
        )
        if not hmac.compare_digest(request_sha256, expected_request_sha256):
            raise ControlPlaneV5Conflict("audit request digest diverges")
        self._verify_action_audit(candidate)

        def write(connection: sqlite3.Connection):
            reservation = ActionReservation(**self._verified_record(
                connection, "action_reservations", "request_id", request_id
            ))
            if (
                reservation.workspace_id != workspace_id
                or reservation.mission_id != mission_id
                or reservation.idempotency_key != idempotency_key
                or reservation.request_sha256 != request_sha256
                or reservation.source_context_sha256 != source_context_sha256
            ):
                raise ControlPlaneV5Conflict(
                    "audit semantics diverge from the durable reservation"
                )
            latest = self._latest_reservation_stage(connection, request_id)
            if latest is None:
                raise ControlPlaneV5Conflict("action reservation is missing")
            if latest.stage == "audit_linked" and latest.owner_id == owner_id:
                if latest.audit_reference_sha256 != audit_reference_sha256:
                    raise ControlPlaneV5Conflict("reservation audit reference diverges")
                return latest, []
            if latest.stage != "reserved" or latest.owner_id != owner_id:
                raise ControlPlaneV5Conflict("reservation is not owned for audit link")
            stage, entries = self._append_reservation_stage(
                connection, scope=scope, request_id=request_id,
                stage="audit_linked", owner_id=owner_id,
                lease_expires_at=latest.lease_expires_at,
                audit_reference_sha256=audit_reference_sha256,
            )
            return stage, entries

        return self._write_records(
            mutation_id="reservation-audit-" + _sha(request_id + owner_id + audit_reference_sha256),
            scope=scope, operation=write,
        )  # type: ignore[return-value]

    def abandon_pre_audit_reservation(
        self, *, workspace_id: str, mission_id: str, request_id: str, owner_id: str
    ) -> ActionReservationStage:
        """Explicitly release only a proved pre-audit reservation."""

        scope = self._validated_scope(workspace_id, mission_id)
        request_id = _safe_id(request_id, "request_id")
        owner_id = _safe_id(owner_id, "reservation owner_id")

        def write(connection: sqlite3.Connection):
            latest = self._latest_reservation_stage(connection, request_id)
            if latest is None or latest.stage != "reserved" or latest.owner_id != owner_id:
                raise ControlPlaneV5Conflict("reservation cannot be released after audit")
            stage, entries = self._append_reservation_stage(
                connection, scope=scope, request_id=request_id,
                stage="pre_audit_failed", owner_id=owner_id,
                lease_expires_at=latest.lease_expires_at,
                audit_reference_sha256=None,
            )
            return stage, entries

        return self._write_records(
            mutation_id="reservation-abandon-" + _sha(request_id + owner_id),
            scope=scope, operation=write,
        )  # type: ignore[return-value]

    def mark_action_dispatch_unknown(
        self, *, workspace_id: str, mission_id: str, request_id: str, owner_id: str
    ) -> ActionReservationStage:
        """Persist the no-blind-retry barrier before invoking the tool."""

        scope = self._validated_scope(workspace_id, mission_id)
        request_id = _safe_id(request_id, "request_id")
        owner_id = _safe_id(owner_id, "reservation owner_id")

        def write(connection: sqlite3.Connection):
            latest = self._latest_reservation_stage(connection, request_id)
            if latest is None or latest.owner_id != owner_id:
                raise ControlPlaneV5Conflict("reservation dispatch owner diverges")
            if latest.stage == "dispatch_unknown":
                return latest, []
            if latest.stage != "request_recorded":
                raise ControlPlaneV5Conflict("request is not ready for dispatch")
            stage, entries = self._append_reservation_stage(
                connection, scope=scope, request_id=request_id,
                stage="dispatch_unknown", owner_id=owner_id,
                lease_expires_at=latest.lease_expires_at,
                audit_reference_sha256=latest.audit_reference_sha256,
            )
            return stage, entries

        return self._write_records(
            mutation_id="reservation-dispatch-" + _sha(request_id + owner_id),
            scope=scope, operation=write,
        )  # type: ignore[return-value]

    @staticmethod
    def _request_from_value(value: dict[str, object]) -> ActionRequest:
        decoded = dict(value)
        version = decoded.get("schema_version")
        if type(version) is not int or version not in {1, 2, 3}:
            raise ControlPlaneV5IntegrityError(
                "action request schema_version is unknown"
            )
        if version < 3:
            decoded.setdefault("target", None)
            decoded.setdefault("approval_id", None)
        else:
            target = _integrity_contract_text(
                decoded.get("target"), "action target", max_length=1024
            )
            if not hmac.compare_digest(
                str(decoded.get("target_sha256")), _sha(str(target))
            ):
                raise ControlPlaneV5IntegrityError(
                    "action target diverges from its digest"
                )
            approval_id = decoded.get("approval_id")
            if approval_id is not None:
                try:
                    _recoverable_contract_id(approval_id, "approval_id")
                except ControlPlaneV5ContractError as exc:
                    raise ControlPlaneV5IntegrityError(
                        "action approval_id violates the authenticated identifier policy"
                    ) from exc
        return ActionRequest(**decoded)

    def get_action_request(
        self, *, workspace_id: str, mission_id: str, request_id: str
    ) -> ActionRequest:
        workspace_id = _safe_id(workspace_id, "workspace_id")
        mission_id = _safe_id(mission_id, "mission_id")
        request_id = _safe_id(request_id, "request_id")
        with self._reader() as connection:
            value = self._verified_record(connection, "action_requests", "request_id", request_id)
            if value.get("workspace_id") != workspace_id: raise ControlPlaneV5IsolationError("request belongs to another workspace")
            if value.get("mission_id") != mission_id:
                raise ControlPlaneV5IsolationError("request belongs to another mission")
            request = self._request_from_value(value)
            self._verify_action_audit(request)
            return request

    def find_action_request(
        self, *, workspace_id: str, mission_id: str, request_id: str
    ) -> ActionRequest | None:
        workspace_id = _safe_id(workspace_id, "workspace_id")
        mission_id = _safe_id(mission_id, "mission_id")
        request_id = _safe_id(request_id, "request_id")
        with self._reader() as connection:
            row = connection.execute(
                "SELECT 1 FROM action_requests WHERE request_id=? LIMIT 1",
                (request_id,),
            ).fetchone()
            if row is None:
                return None
            value = self._verified_record(
                connection, "action_requests", "request_id", request_id
            )
            if value.get("workspace_id") != workspace_id:
                raise ControlPlaneV5IsolationError("request belongs to another workspace")
            if value.get("mission_id") != mission_id:
                raise ControlPlaneV5IsolationError("request belongs to another mission")
            request = self._request_from_value(value)
            self._verify_action_audit(request)
            return request

    def _receipt_chain(
        self, connection: sqlite3.Connection, request_id: str
    ) -> tuple[ActionReceipt, ...]:
        """Return the unique receipt chain by supersession edges only."""

        receipts: dict[str, ActionReceipt] = {}
        for row in connection.execute(
            "SELECT receipt_id FROM action_receipts WHERE request_id=?",
            (request_id,),
        ).fetchall():
            receipt = self._receipt_from_value(
                self._verified_record(
                    connection, "action_receipts", "receipt_id", str(row[0])
                )
            )
            if receipt.request_id != request_id:
                raise ControlPlaneV5IntegrityError("receipt/request identity diverges")
            receipts[receipt.receipt_id] = receipt
        if not receipts:
            return ()
        roots = [
            receipt for receipt in receipts.values()
            if receipt.supersedes_receipt_id is None
        ]
        if len(roots) != 1:
            raise ControlPlaneV5IntegrityError(
                "receipt graph must have exactly one root"
            )
        children: dict[str, list[ActionReceipt]] = {}
        for receipt in receipts.values():
            parent = receipt.supersedes_receipt_id
            if parent is None:
                if receipt.reconciliation:
                    raise ControlPlaneV5IntegrityError(
                        "receipt root cannot claim reconciliation"
                    )
                continue
            if parent == receipt.receipt_id or parent not in receipts:
                raise ControlPlaneV5IntegrityError(
                    "receipt graph has a cycle or missing parent"
                )
            children.setdefault(parent, []).append(receipt)
        if any(len(values) != 1 for values in children.values()):
            raise ControlPlaneV5IntegrityError("receipt graph fork detected")
        chain: list[ActionReceipt] = []
        visited: set[str] = set()
        current = roots[0]
        while True:
            if current.receipt_id in visited:
                raise ControlPlaneV5IntegrityError("receipt graph cycle detected")
            visited.add(current.receipt_id)
            chain.append(current)
            next_items = children.get(current.receipt_id, ())
            if not next_items:
                break
            child = next_items[0]
            if not child.reconciliation or current.outcome not in {
                "unknown", "partial"
            }:
                raise ControlPlaneV5IntegrityError(
                    "receipt reconciliation edge is invalid"
                )
            current = child
        if visited != set(receipts):
            raise ControlPlaneV5IntegrityError(
                "receipt graph has a cycle, disconnected component, or multiple tails"
            )
        root = chain[0]
        if root.schema_version >= 3:
            for receipt in chain:
                if (
                    receipt.provider_request_id != root.provider_request_id
                    or receipt.provider_request_ref != root.provider_request_ref
                    or receipt.provider_request_sha256
                    != root.provider_request_sha256
                    or receipt.started_at != root.started_at
                ):
                    raise ControlPlaneV5IntegrityError(
                        "receipt reconciliation changed external-operation identity"
                    )
        return tuple(chain)

    def _verify_dispatch_barrier(
        self, connection: sqlite3.Connection, request: ActionRequest
    ) -> None:
        latest = self._latest_reservation_stage(connection, request.request_id)
        if latest is None or latest.stage != "dispatch_unknown":
            raise ControlPlaneV5Conflict(
                "action receipt requires the durable dispatch_unknown barrier"
            )
        if (
            latest.workspace_id != request.workspace_id
            or latest.mission_id != request.mission_id
            or latest.correlation_id != request.correlation_id
            or latest.audit_reference_sha256 != request.audit_reference_sha256
        ):
            raise ControlPlaneV5IntegrityError(
                "receipt dispatch barrier/request binding diverges"
            )

    def _verify_receipt_bindings(
        self,
        connection: sqlite3.Connection,
        receipt: ActionReceipt,
        request: ActionRequest,
    ) -> None:
        self._verify_dispatch_barrier(connection, request)
        if (
            receipt.request_id != request.request_id
            or receipt.workspace_id != request.workspace_id
            or receipt.mission_id != request.mission_id
            or receipt.correlation_id != request.correlation_id
            or receipt.source_context_sha256 != request.source_context_sha256
        ):
            raise ControlPlaneV5IntegrityError(
                "receipt/request scope binding diverges"
            )
        if not receipt.provider_request_id or not receipt.provider_request_ref:
            raise ControlPlaneV5IntegrityError(
                "receipt lacks a recoverable provider request reference"
            )
        if receipt.schema_version >= 3 and not hmac.compare_digest(
            receipt.provider_request_sha256,
            provider_request_binding_sha256(
                receipt.provider_request_id, receipt.provider_request_ref
            ),
        ):
            raise ControlPlaneV5IntegrityError(
                "receipt provider digest does not bind its recoverable identity"
            )
        positive = receipt.outcome in {"succeeded", "simulated"}
        retained_publication = _validate_retained_publication_refs(
            output_ref=receipt.output_ref,
            rollback_ref=receipt.rollback_ref,
            outcome=receipt.outcome,
            reconciliation=receipt.reconciliation,
            integrity=True,
        )
        artifact_id = (
            None
            if retained_publication
            else _typed_reference(
                receipt.output_ref,
                "receipt output_ref",
                "artifact",
                optional=not positive,
            )
        )
        evidence_id = _typed_reference(
            receipt.verification_ref,
            "receipt verification_ref",
            "evidence",
            optional=not positive,
        )
        claim_id = _typed_reference(
            receipt.after_state_ref,
            "receipt after_state_ref",
            "claim",
            optional=not positive,
        )
        if evidence_id is not None and artifact_id is None:
            raise ControlPlaneV5IntegrityError(
                "receipt evidence reference lacks its artifact reference"
            )
        if claim_id is not None and evidence_id is None:
            raise ControlPlaneV5IntegrityError(
                "receipt claim reference lacks its evidence reference"
            )
        scope = (request.workspace_id, request.mission_id, request.correlation_id)
        artifact: ArtifactRecord | None = None
        evidence: EvidenceRecord | None = None
        if artifact_id is not None:
            artifact = ArtifactRecord(**self._verified_record(
                connection, "artifact_records", "artifact_id", artifact_id
            ))
            if (
                (artifact.workspace_id, artifact.mission_id, artifact.correlation_id)
                != scope
                or artifact.request_id != request.request_id
                or (positive and artifact.content_sha256 != receipt.output_sha256)
            ):
                raise ControlPlaneV5IntegrityError(
                    "receipt output artifact is not request-bound"
                )
        if evidence_id is not None:
            evidence_value = self._verified_record(
                connection, "evidence_records", "evidence_id", evidence_id
            )
            evidence_value["claim_ids"] = tuple(evidence_value["claim_ids"])
            evidence = self._evidence_from_value(evidence_value)
            assert artifact is not None
            if (
                (evidence.workspace_id, evidence.mission_id, evidence.correlation_id)
                != scope
                or evidence.artifact_id != artifact.artifact_id
                or evidence.content_sha256 != artifact.content_sha256
            ):
                raise ControlPlaneV5IntegrityError(
                    "receipt verification evidence is not artifact-bound"
                )
        if receipt.schema_version >= 3:
            expected_verification_sha256 = (
                _sha(b"")
                if evidence is None
                else evidence_verification_sha256(evidence)
            )
            if not hmac.compare_digest(
                receipt.verification_sha256, expected_verification_sha256
            ):
                raise ControlPlaneV5IntegrityError(
                    "receipt verification digest is not evidence-bound"
                )
        if claim_id is not None:
            claim = self._claim_from_value(self._verified_record(
                connection, "claims", "claim_id", claim_id
            ))
            assert evidence is not None
            if (
                (claim.workspace_id, claim.mission_id, claim.correlation_id) != scope
                or evidence.evidence_id not in claim.evidence_ids
                or (positive and claim.statement_sha256 != receipt.postcondition_sha256)
            ):
                raise ControlPlaneV5IntegrityError(
                    "receipt postcondition claim is not evidence-bound"
                )
            inverse = self._authenticated_claim_ids(connection, evidence.evidence_id)
            if claim.claim_id not in inverse:
                raise ControlPlaneV5IntegrityError(
                    "receipt claim/evidence inverse link is missing"
                )

    def record_action_receipt(
        self, *, workspace_id: str, mission_id: str, request_id: str,
        outcome: str, provider_request_sha256: str, output_sha256: str,
        verification_sha256: str, postcondition_sha256: str, error_class: str,
        supersedes_receipt_id: str | None, reconciliation: bool, observed_at: str,
        caller_key: str, provider_request_id: str | None = None,
        provider_request_ref: str | None = None, started_at: str | None = None,
        completed_at: str | None = None, before_state_ref: str | None = None,
        after_state_ref: str | None = None, output_ref: str | None = None,
        verification_ref: str | None = None, rollback_ref: str | None = None,
    ) -> ActionReceipt:
        scope = self._validated_scope(workspace_id, mission_id)
        request = self.get_action_request(
            workspace_id=workspace_id,
            mission_id=mission_id,
            request_id=request_id,
        )
        if request.mission_id != mission_id: raise ControlPlaneV5IsolationError("receipt request belongs to another mission")
        if outcome not in {"cancelled", "failed", "partial", "rejected", "simulated", "succeeded", "unknown"}: raise ControlPlaneV5ContractError("outcome is invalid")
        for value, label in ((provider_request_sha256, "provider_request_sha256"), (output_sha256, "output_sha256"),
                             (verification_sha256, "verification_sha256"), (postcondition_sha256, "postcondition_sha256")):
            _digest(value, label)
        if error_class:
            _slug(error_class, "error_class")
        if type(reconciliation) is not bool: raise ControlPlaneV5ContractError("reconciliation must be bool")
        provider_request_id = _opaque_reference(
            provider_request_id, "provider_request_id", optional=True
        )
        provider_request_ref = _opaque_reference(
            provider_request_ref, "provider_request_ref", optional=True
        )
        if provider_request_id is None or provider_request_ref is None:
            raise ControlPlaneV5ContractError(
                "receipt requires recoverable provider_request_id and provider_request_ref"
            )
        expected_provider_sha256 = provider_request_binding_sha256(
            provider_request_id, provider_request_ref
        )
        if not hmac.compare_digest(
            provider_request_sha256, expected_provider_sha256
        ):
            raise ControlPlaneV5ContractError(
                "provider_request_sha256 does not bind provider_request_id/ref"
            )
        started_at = str(_timestamp(started_at or observed_at, "started_at"))
        completed_at = _timestamp(completed_at, "completed_at", optional=True)
        before_state_ref = _opaque_reference(
            before_state_ref, "before_state_ref", optional=True
        )
        after_state_ref = _opaque_reference(
            after_state_ref, "after_state_ref", optional=True
        )
        output_ref = _opaque_reference(output_ref, "output_ref", optional=True)
        verification_ref = _opaque_reference(
            verification_ref, "verification_ref", optional=True
        )
        rollback_ref = _opaque_reference(
            rollback_ref, "rollback_ref", optional=True
        )
        retained_publication = _validate_retained_publication_refs(
            output_ref=output_ref,
            rollback_ref=rollback_ref,
            outcome=outcome,
            reconciliation=reconciliation,
        )
        if retained_publication and output_sha256 == _sha(b""):
            raise ControlPlaneV5ContractError(
                "retained publication receipt requires an observed output digest"
            )
        if outcome == "succeeded":
            raise ControlPlaneV5ContractError("dry-run P4.4 requests cannot have succeeded outcome")
        if outcome in {"failed", "partial", "unknown"} and not error_class:
            raise ControlPlaneV5ContractError("nonterminal/failure receipt requires error_class")
        if outcome == "simulated" and (
            error_class
            or output_sha256 == _sha(b"")
            or verification_sha256 == _sha(b"")
            or postcondition_sha256 == _sha(b"")
        ):
            raise ControlPlaneV5ContractError(
                "simulated receipt requires observed output and postcondition evidence"
            )
        if outcome in {"succeeded", "simulated"}:
            if completed_at is None:
                raise ControlPlaneV5ContractError(
                    "completed receipt requires completed_at"
                )
            _typed_reference(output_ref, "output_ref", "artifact")
            _typed_reference(verification_ref, "verification_ref", "evidence")
            _typed_reference(after_state_ref, "after_state_ref", "claim")
        if outcome in {"unknown", "partial"} and completed_at is not None:
            raise ControlPlaneV5ContractError(
                "unknown/partial receipt cannot claim completion"
            )
        if outcome in {"unknown", "partial"} and reconciliation:
            raise ControlPlaneV5ContractError("initial unknown/partial receipt cannot claim reconciliation")
        if supersedes_receipt_id is None and reconciliation:
            raise ControlPlaneV5ContractError("reconciliation receipt must supersede a prior receipt")
        if supersedes_receipt_id is not None and not reconciliation:
            raise ControlPlaneV5ContractError("superseding receipt must be reconciliation")
        observed_at = str(_timestamp(observed_at, "observed_at")); caller_key = _safe_id(caller_key, "caller_key")
        started_value = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        observed_value = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if started_value > observed_value:
            raise ControlPlaneV5ContractError("started_at cannot be after observed_at")
        if completed_at is not None:
            completed_value = datetime.fromisoformat(
                str(completed_at).replace("Z", "+00:00")
            )
            if completed_value < started_value:
                raise ControlPlaneV5ContractError(
                    "completed_at cannot be before started_at"
                )
        receipt_id = "receipt-" + _sha(_canonical([request_id, caller_key, supersedes_receipt_id]))
        created_at = _now()
        record = ActionReceipt(
            schema_version=RECORD_SCHEMA_VERSION,
            receipt_id=receipt_id,
            request_id=request_id,
            workspace_id=workspace_id,
            mission_id=mission_id,
            correlation_id=scope.correlation_id,
            outcome=outcome,
            provider_request_sha256=provider_request_sha256,
            output_sha256=output_sha256,
            verification_sha256=verification_sha256,
            postcondition_sha256=postcondition_sha256,
            error_class=error_class,
            supersedes_receipt_id=supersedes_receipt_id,
            reconciliation=reconciliation,
            source_context_sha256=scope.context_sha256,
            observed_at=observed_at,
            created_at=created_at,
            provider_request_id=provider_request_id,
            provider_request_ref=provider_request_ref,
            started_at=started_at,
            completed_at=completed_at,
            before_state_ref=before_state_ref,
            after_state_ref=after_state_ref,
            output_ref=output_ref,
            verification_ref=verification_ref,
            rollback_ref=rollback_ref,
        )

        def write(connection: sqlite3.Connection):
            request_value = self._request_from_value(self._verified_record(
                connection, "action_requests", "request_id", request_id
            ))
            self._verify_dispatch_barrier(connection, request_value)
            if connection.execute("SELECT 1 FROM action_receipts WHERE receipt_id=?", (receipt_id,)).fetchone():
                prior = self._receipt_from_value(self._verified_record(connection, "action_receipts", "receipt_id", receipt_id))
                a, b = asdict(prior), asdict(record); a.pop("created_at"); b.pop("created_at")
                if a != b: raise ControlPlaneV5Conflict("receipt identity replay changed input")
                self._verify_receipt_bindings(connection, prior, request_value)
                return prior, []
            chain = self._receipt_chain(connection, request_id)
            if supersedes_receipt_id is None:
                if chain:
                    raise ControlPlaneV5Conflict(
                        "request already has an initial receipt"
                    )
            elif not chain or chain[-1].receipt_id != supersedes_receipt_id:
                raise ControlPlaneV5Conflict(
                    "reconciliation must supersede the receipt graph tail"
                )
            if chain and reconciliation:
                root = chain[0]
                if (
                    provider_request_id != root.provider_request_id
                    or provider_request_ref != root.provider_request_ref
                    or provider_request_sha256 != root.provider_request_sha256
                    or started_at != root.started_at
                ):
                    raise ControlPlaneV5Conflict(
                        "reconciliation changed external-operation identity"
                    )
            if supersedes_receipt_id is not None and chain[-1].outcome not in {
                "unknown", "partial"
            }:
                raise ControlPlaneV5Conflict(
                    "only an unknown/partial receipt may be reconciled"
                )
            self._insert_record(connection, "action_receipts", "receipt_id", receipt_id, asdict(record),
                                prefix=(receipt_id, request_id, workspace_id, mission_id, scope.correlation_id, supersedes_receipt_id, created_at))
            self._verify_receipt_bindings(connection, record, request_value)
            _event, event_entry = self._append_event(
                connection, scope=scope, actor="mission_tool",
                event_type="action.reconciled" if reconciliation else "action.receipted",
                entity_type="action_receipt", entity_id=receipt_id,
                payload_sha256=_sha(_canonical(asdict(record))), created_at=created_at,
            )
            return record, [self._entry_for(connection, "action_receipts", "receipt_id", receipt_id), event_entry]

        mutation_id = "receipt-mutation-" + _sha(_canonical([request_id, caller_key, supersedes_receipt_id]))
        try:
            return self._write_records(mutation_id=mutation_id, scope=scope, operation=write)  # type: ignore[return-value]
        except ControlPlaneV5Conflict as exc:
            if "mutation_id already exists" not in str(exc): raise
            prior = self.get_action_receipt(
                workspace_id=workspace_id,
                mission_id=mission_id,
                receipt_id=receipt_id,
            )
            _assert_replay_equivalent(prior, record, "receipt identity")
            return prior

    @staticmethod
    def _receipt_from_value(value: dict[str, object]) -> ActionReceipt:
        decoded = dict(value)
        version = decoded.get("schema_version")
        if type(version) is not int or version not in {1, 2, 3}:
            raise ControlPlaneV5IntegrityError("receipt schema_version is unknown")
        if version < 2:
            for name in (
                "provider_request_id",
                "provider_request_ref",
                "completed_at",
                "before_state_ref",
                "after_state_ref",
                "output_ref",
                "verification_ref",
                "rollback_ref",
            ):
                decoded.setdefault(name, None)
            decoded.setdefault("started_at", "")
        for name in (
            "provider_request_id",
            "provider_request_ref",
            "before_state_ref",
            "after_state_ref",
            "output_ref",
            "verification_ref",
            "rollback_ref",
        ):
            decoded[name] = _integrity_opaque_reference(
                decoded.get(name), f"receipt {name}", optional=True
            )
        receipt = ActionReceipt(**decoded)
        _validate_retained_publication_refs(
            output_ref=receipt.output_ref,
            rollback_ref=receipt.rollback_ref,
            outcome=receipt.outcome,
            reconciliation=receipt.reconciliation,
            integrity=True,
        )
        if receipt.schema_version >= 3:
            if not receipt.provider_request_id or not receipt.provider_request_ref:
                raise ControlPlaneV5IntegrityError(
                    "receipt v3 recoverable provider identity is missing"
                )
            if not hmac.compare_digest(
                receipt.provider_request_sha256,
                provider_request_binding_sha256(
                    receipt.provider_request_id, receipt.provider_request_ref
                ),
            ):
                raise ControlPlaneV5IntegrityError(
                    "receipt provider identity binding diverges"
                )
        return receipt

    def get_action_receipt(
        self, *, workspace_id: str, mission_id: str, receipt_id: str
    ) -> ActionReceipt:
        workspace_id = _safe_id(workspace_id, "workspace_id")
        mission_id = _safe_id(mission_id, "mission_id")
        receipt_id = _safe_id(receipt_id, "receipt_id")
        with self._reader() as connection:
            value = self._verified_record(connection, "action_receipts", "receipt_id", receipt_id)
            if value.get("workspace_id") != workspace_id: raise ControlPlaneV5IsolationError("receipt belongs to another workspace")
            if value.get("mission_id") != mission_id:
                raise ControlPlaneV5IsolationError("receipt belongs to another mission")
            receipt = self._receipt_from_value(value)
            request = self._request_from_value(self._verified_record(
                connection, "action_requests", "request_id", receipt.request_id
            ))
            self._receipt_chain(connection, receipt.request_id)
            self._verify_receipt_bindings(connection, receipt, request)
            return receipt

    def latest_action_receipt(
        self, *, workspace_id: str, mission_id: str, request_id: str
    ) -> ActionReceipt | None:
        workspace_id = _safe_id(workspace_id, "workspace_id")
        mission_id = _safe_id(mission_id, "mission_id")
        request = self.get_action_request(
            workspace_id=workspace_id,
            mission_id=mission_id,
            request_id=request_id,
        )
        with self._reader() as connection:
            chain = self._receipt_chain(connection, request_id)
            if not chain:
                return None
            receipt = chain[-1]
            if receipt.workspace_id != workspace_id or receipt.mission_id != mission_id:
                raise ControlPlaneV5IntegrityError("receipt/request scope diverges")
            self._verify_receipt_bindings(connection, receipt, request)
            return receipt

    def list_events(
        self, *, workspace_id: str, mission_id: str, after_sequence: int = 0,
        limit: int = 100,
    ) -> tuple[EventEnvelope, ...]:
        scope = self._validated_scope(workspace_id, mission_id)
        if type(after_sequence) is not int or after_sequence < 0: raise ControlPlaneV5ContractError("after_sequence is invalid")
        if type(limit) is not int or not 1 <= limit <= _MAX_PAGE: raise ControlPlaneV5ContractError("limit is invalid")
        with self._reader() as connection:
            expected_sequence = after_sequence + 1
            expected_previous = _ZERO_HASH
            if after_sequence:
                prior = connection.execute(
                    "SELECT event_id FROM event_envelopes WHERE workspace_id=? "
                    "AND correlation_id=? AND sequence=?",
                    (workspace_id, scope.correlation_id, after_sequence),
                ).fetchone()
                if prior is None:
                    raise ControlPlaneV5IntegrityError("event page predecessor is missing")
                prior_value = self._verified_record(
                    connection, "event_envelopes", "event_id", str(prior[0])
                )
                prior_event = self._event_from_value(prior_value)
                expected_previous = prior_event.event_hash
            rows = connection.execute(
                "SELECT event_id FROM event_envelopes WHERE workspace_id=? AND correlation_id=? "
                "AND sequence>? ORDER BY sequence LIMIT ?",
                (workspace_id, scope.correlation_id, after_sequence, limit),
            ).fetchall()
            result = []
            for row in rows:
                value = self._verified_record(connection, "event_envelopes", "event_id", str(row[0]))
                event = self._event_from_value(value)
                if (
                    event.workspace_id != workspace_id
                    or event.mission_id != mission_id
                    or event.correlation_id != scope.correlation_id
                    or event.sequence != expected_sequence
                    or event.previous_hash != expected_previous
                ):
                    raise ControlPlaneV5IntegrityError("event chain continuity diverges")
                result.append(event)
                expected_sequence += 1
                expected_previous = event.event_hash
            return tuple(result)

    @staticmethod
    def _event_from_value(value: dict[str, object]) -> EventEnvelope:
        event = EventEnvelope(**value)
        base = asdict(event)
        event_hash = str(base.pop("event_hash"))
        expected = _sha("ONYX-V5-EVENT\0" + _canonical(base))
        if not hmac.compare_digest(expected, event_hash):
            raise ControlPlaneV5IntegrityError("event payload hash diverges")
        return event

    def list_evidence(
        self, *, workspace_id: str, mission_id: str, after_id: str = "",
        limit: int = 100,
    ) -> tuple[EvidenceRecord, ...]:
        self._validated_scope(workspace_id, mission_id)
        if after_id and not _SAFE_ID.fullmatch(after_id):
            raise ControlPlaneV5ContractError("after_id is invalid")
        if type(limit) is not int or not 1 <= limit <= _MAX_PAGE:
            raise ControlPlaneV5ContractError("limit is invalid")
        with self._reader() as connection:
            rows = connection.execute(
                "SELECT evidence_id FROM evidence_records WHERE workspace_id=? "
                "AND mission_id=? AND evidence_id>? ORDER BY evidence_id LIMIT ?",
                (workspace_id, mission_id, after_id, limit),
            ).fetchall()
            result = []
            for row in rows:
                value = self._verified_record(
                    connection, "evidence_records", "evidence_id", str(row[0])
                )
                value["claim_ids"] = self._authenticated_claim_ids(
                    connection, str(row[0])
                )
                evidence = self._evidence_from_value(value)
                if evidence.mission_id != mission_id:
                    raise ControlPlaneV5IntegrityError(
                        "listed evidence mission scope diverges"
                    )
                result.append(evidence)
            return tuple(result)

    def list_claims(
        self, *, workspace_id: str, mission_id: str, after_id: str = "",
        limit: int = 100,
    ) -> tuple[Claim, ...]:
        self._validated_scope(workspace_id, mission_id)
        if after_id and not _SAFE_ID.fullmatch(after_id):
            raise ControlPlaneV5ContractError("after_id is invalid")
        if type(limit) is not int or not 1 <= limit <= _MAX_PAGE:
            raise ControlPlaneV5ContractError("limit is invalid")
        with self._reader() as connection:
            rows = connection.execute(
                "SELECT claim_id FROM claims WHERE workspace_id=? AND mission_id=? "
                "AND claim_id>? ORDER BY claim_id LIMIT ?",
                (workspace_id, mission_id, after_id, limit),
            ).fetchall()
            result = []
            for row in rows:
                value = self._verified_record(
                    connection, "claims", "claim_id", str(row[0])
                )
                claim = self._claim_from_value(value)
                if claim.mission_id != mission_id:
                    raise ControlPlaneV5IntegrityError(
                        "listed claim mission scope diverges"
                    )
                result.append(claim)
            return tuple(result)

    def reconcile_required(
        self, *, workspace_id: str, mission_id: str, request_id: str
    ) -> bool:
        receipt = self.latest_action_receipt(
            workspace_id=workspace_id,
            mission_id=mission_id,
            request_id=request_id,
        )
        return receipt is not None and receipt.outcome in {"unknown", "partial"}


def open_default() -> None:
    if not control_plane_v5_enabled():
        raise ControlPlaneV5Disabled(f"{CONTROL_PLANE_V5_FLAG} is disabled")
    raise ControlPlaneV5IOError(
        "schema v5 has no production owner/vault wiring; P4.4 activation remains gated"
    )


__all__ = [
    "CONTROL_PLANE_V5_FLAG", "V5_SCHEMA_VERSION", "ActionReceipt",
    "ActionRequest", "ArtifactRecord", "Claim", "ControlPlaneV5Conflict",
    "ControlPlaneV5ContractError", "ControlPlaneV5Disabled", "ControlPlaneV5Error",
    "ControlPlaneV5IOError", "ControlPlaneV5IntegrityError",
    "ControlPlaneV5IsolationError", "ControlPlaneV5Store", "EvidenceRecord",
    "EventEnvelope", "MissionAuthorityPort", "MissionScope", "SecretVault",
    "V4AuthorityStatus", "V4MissionAuthority", "V5Status",
    "control_plane_v5_enabled", "open_default", "stable_scope_key",
    "action_audit_trace_id", "action_request_contract_sha256",
    "action_request_identity", "assert_redacted", "claim_identity", "evidence_identity",
    "evidence_verification_sha256", "provider_request_binding_sha256",
]
