"""Default-off M2a shadow records over the existing control-plane v2 schema.

This module is deliberately not an operational ledger.  It records typed,
redacted shadow observations only.  It cannot dispatch tools, authorize an
action, change mission state, or infer success.  A future reviewed schema-v3
migration with database-enforced immutability is required before any runtime
integration.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone

from core.control_plane import ControlPlaneError, ControlPlaneIOError
from core.workspaces import (
    LEGACY_WORKSPACE_ID,
    WorkspaceError,
    WorkspaceRegistry,
)


M2A_DOMAIN_LEDGER_FLAG = "ONYX_M2A_DOMAIN_LEDGER_V1"
DOMAIN_CONTRACT_VERSION = 1
_ZERO_HASH = "0" * 64
_EMPTY_MATERIAL_HASHES = frozenset(
    {
        hashlib.sha256(b"m2a:bytes\0").hexdigest(),
        hashlib.sha256(b"m2a:text\0").hexdigest(),
    }
)
_LEDGER_LOCK = threading.RLock()
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_ENTITY_ID = re.compile(
    r"m2a-(?:evidence|claim|request|receipt|event|event-head)-[0-9a-f]{64}"
)
_CORRELATION_ID = re.compile(r"m2a-correlation-[0-9a-f]{64}")
_IDEMPOTENCY_KEY = re.compile(r"m2a:[0-9a-f]{64}")
_SLUG = re.compile(r"[a-z][a-z0-9_.-]{0,79}")
_MAX_PAYLOAD_BYTES = 8192
_MAX_JSON_DEPTH = 32
_MAX_JSON_ITEMS = 1024

_SOURCE_KINDS = frozenset(
    {"artifact", "local_read", "mission_result", "observation", "provider", "public_url"}
)
_FRESHNESS = frozenset({"current", "historical", "unknown"})
_CLAIM_KINDS = frozenset({"fact", "forecast", "inference", "recommendation", "unknown"})
_VERIFICATION = frozenset({"contradicted", "supported", "unknown", "unverified"})
_RISKS = frozenset({"critical", "high", "low", "medium"})
_APPROVAL_POLICIES = frozenset({"always_explicit", "exact_callback", "shadow_only"})
_DATA_CLASSES = frozenset({"confidential", "internal", "public", "restricted"})
_OUTCOMES = frozenset(
    {"cancelled", "failed", "partial", "rejected", "simulated", "succeeded", "unknown"}
)
_REQUEST_STATUSES = frozenset({"proposed", "recorded", "reconciliation_required"})
_EVENT_TYPES = frozenset(
    {"action.receipt.recorded", "action.request.recorded", "claim.recorded", "evidence.recorded"}
)
_ENTITY_TYPES = frozenset(
    {"action_receipt", "action_request", "claim", "evidence"}
)

_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_-]?key|authorization|bearer|client[_-]?secret|password|private[_-]?key|refresh[_-]?token|secret|token)\s*[:= ]\s*\S+"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\b(?:gh[opsu]_|sk-)[0-9A-Za-z_-]{12,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


class DomainLedgerError(ControlPlaneError):
    """Base error for the M2a shadow repository."""


class DomainLedgerDisabled(DomainLedgerError):
    """Raised when the M2a flag is not explicitly enabled."""


class DomainContractError(DomainLedgerError):
    """Raised when input or a persisted row violates the v1 contract."""


class DomainIsolationError(DomainLedgerError):
    """Raised for missing, inactive, legacy, or cross-workspace scope."""


class DomainConflict(DomainLedgerError):
    """Raised when an idempotent identity is replayed with different input."""


class DomainIntegrityError(DomainLedgerError):
    """Raised when persisted shadow records or their event chain diverge."""


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    evidence_id: str
    workspace_id: str
    mission_id: str | None
    correlation_id: str
    source_kind: str
    source_identity_sha256: str
    content_sha256: str
    artifact_id: str | None
    credibility_bp: int
    freshness: str
    validity_seconds: int | None
    observed_at: str
    valid_until: str | None
    access_license_sha256: str
    input_sha256: str
    created_at: str


@dataclass(frozen=True, slots=True)
class ClaimRecord:
    claim_id: str
    workspace_id: str
    mission_id: str | None
    correlation_id: str
    claim_kind: str
    statement_sha256: str
    evidence_ids: tuple[str, ...]
    confidence_bp: int
    verification_status: str
    validity_seconds: int | None
    valid_until: str | None
    contradiction_claim_ids: tuple[str, ...]
    supersedes_claim_id: str | None
    input_sha256: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ActionRequestRecord:
    request_id: str
    workspace_id: str
    mission_id: str | None
    correlation_id: str
    connector: str
    operation: str
    target_sha256: str
    payload_sha256: str
    idempotency_key: str
    risk: str
    approval_policy: str
    data_class: str
    dry_run: bool
    verification_plan_sha256: str
    rollback_plan_sha256: str
    input_sha256: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ActionReceiptRecord:
    receipt_id: str
    request_id: str
    workspace_id: str
    correlation_id: str
    outcome: str
    provider_request_sha256: str
    before_sha256: str
    after_sha256: str
    output_sha256: str
    verification_sha256: str
    rollback_sha256: str
    error_class: str
    supersedes_receipt_id: str | None
    reconciliation: bool
    input_sha256: str
    observed_at: str
    created_at: str


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    event_id: str
    workspace_id: str
    mission_id: str | None
    correlation_id: str
    event_type: str
    entity_type: str
    entity_id: str
    entity_sha256: str
    parent_entity_id: str | None
    parent_entity_sha256: str | None
    previous_hash: str
    event_hash: str
    created_at: str


def m2a_domain_ledger_enabled(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return source.get(M2A_DOMAIN_LEDGER_FLAG, "").strip().casefold() in {"1", "true"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_json(value: object, *, depth: int = 0, items: list[int] | None = None) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise DomainContractError("canonical shadow payload exceeds the depth limit")
    counter = [0] if items is None else items
    counter[0] += 1
    if counter[0] > _MAX_JSON_ITEMS:
        raise DomainContractError("canonical shadow payload exceeds the item limit")
    if value is None or type(value) in {bool, int, str}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise DomainContractError("canonical shadow payload contains a non-finite number")
        return
    if type(value) is list:
        for item in value:
            _validate_json(item, depth=depth + 1, items=counter)
        return
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise DomainContractError("canonical shadow payload keys must be strings")
        for item in value.values():
            _validate_json(item, depth=depth + 1, items=counter)
        return
    raise DomainContractError("canonical shadow payload contains a non-JSON type")


def _canonical(value: object) -> str:
    try:
        _validate_json(value)
        text = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    except DomainContractError:
        raise
    except (RecursionError, TypeError, ValueError) as exc:
        raise DomainContractError("canonical shadow payload is invalid") from exc
    if len(text.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise DomainContractError("canonical shadow payload is too large")
    return text


def _sha(value: bytes | str) -> str:
    encoded = value.encode("utf-8") if isinstance(value, str) else bytes(value)
    return hashlib.sha256(encoded).hexdigest()


def _safe_material(value: object, label: str, *, allow_empty: bool = False) -> bytes:
    if isinstance(value, bytes):
        raw = bytes(value)
        scan = raw.decode("utf-8", errors="ignore")
        framed = b"m2a:bytes\0" + raw
    elif isinstance(value, str):
        scan = value
        raw = value.encode("utf-8")
        framed = b"m2a:text\0" + raw
    else:
        raise DomainContractError(f"{label} must be text or bytes")
    if not allow_empty and not raw:
        raise DomainContractError(f"{label} is required")
    if len(raw) > 1_048_576:
        raise DomainContractError(f"{label} is too large")
    if any(pattern.search(scan) for pattern in _SECRET_PATTERNS):
        raise DomainContractError(f"{label} resembles credential or secret material")
    return framed


def _material_present(value: bytes) -> bool:
    return value not in {b"m2a:bytes\0", b"m2a:text\0"}


def _safe_key(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise DomainContractError(f"{label} must be a bounded host key")
    _safe_material(value, label)
    return value


def _slug(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SLUG.fullmatch(value):
        raise DomainContractError(f"{label} is invalid")
    return value


def _enum(value: object, allowed: frozenset[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise DomainContractError(f"{label} is unsupported")
    return value


def _digest(value: object, label: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise DomainIntegrityError(f"{label} is not a canonical SHA-256 digest")
    return value


def _timestamp(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise DomainIntegrityError(f"{label} is not a UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise DomainIntegrityError(f"{label} is not a UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise DomainIntegrityError(f"{label} is not UTC")
    return value


def _validity_seconds(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 1 <= value <= 31_536_000:
        raise DomainContractError("validity_seconds must be 1..31536000")
    return value


def _basis_points(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= 10_000:
        raise DomainContractError(f"{label} must be 0..10000 basis points")
    return value


def _entity_id(kind: str, workspace_id: str, caller_key: str) -> str:
    identity = f"{workspace_id}\0{kind}\0{caller_key}"
    return f"m2a-{kind}-{_sha(identity)}"


def _correlation_id(workspace_id: str, correlation_key: str) -> str:
    identity = f"{workspace_id}\0correlation\0{correlation_key}"
    return f"m2a-correlation-{_sha(identity)}"


def _idempotency_key(workspace_id: str, caller_key: str) -> str:
    return "m2a:" + _sha(f"{workspace_id}\0{caller_key}")


def _event_identity(
    workspace_id: str,
    mission_id: str | None,
    correlation_id: str,
    event_type: str,
    payload_text: str,
    previous_hash: str,
    created_at: str,
) -> str:
    return "m2a-event-" + _row_digest(
        (
            workspace_id,
            mission_id,
            correlation_id,
            event_type,
            payload_text,
            previous_hash,
            created_at,
        )
    )


def _parse_payload(text: object, keys: frozenset[str], label: str) -> dict[str, object]:
    if not isinstance(text, str) or len(text.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise DomainIntegrityError(f"{label} payload is invalid")
    try:
        value = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise DomainIntegrityError(f"{label} payload is malformed") from exc
    try:
        canonical = _canonical(value)
    except DomainContractError as exc:
        raise DomainIntegrityError(f"{label} payload violates canonical bounds") from exc
    if not isinstance(value, dict) or set(value) != keys or canonical != text:
        raise DomainIntegrityError(f"{label} payload is not exact canonical JSON")
    return value


def _row_digest(row: Iterable[object]) -> str:
    return _sha(_canonical(list(row)))


_EVIDENCE_KEYS = frozenset(
    {
        "access_license_sha256",
        "artifact_id",
        "contract",
        "correlation_id",
        "credibility_bp",
        "freshness",
        "input_sha256",
        "observed_at",
        "source_identity_sha256",
        "source_kind",
        "valid_until",
        "validity_seconds",
    }
)
_CLAIM_KEYS = frozenset(
    {
        "claim_kind",
        "contract",
        "contradiction_claim_ids",
        "confidence_bp",
        "correlation_id",
        "evidence_ids",
        "input_sha256",
        "mission_id",
        "statement_sha256",
        "supersedes_claim_id",
        "valid_until",
        "validity_seconds",
    }
)
_REQUEST_KEYS = frozenset(
    {
        "approval_policy",
        "connector",
        "contract",
        "correlation_id",
        "data_class",
        "dry_run",
        "input_sha256",
        "operation",
        "risk",
        "rollback_plan_sha256",
        "target_sha256",
        "verification_plan_sha256",
    }
)
_RECEIPT_KEYS = frozenset(
    {
        "after_sha256",
        "before_sha256",
        "contract",
        "correlation_id",
        "error_class",
        "input_sha256",
        "observed_at",
        "output_sha256",
        "provider_request_sha256",
        "reconciliation",
        "rollback_sha256",
        "supersedes_receipt_id",
        "verification_sha256",
        "workspace_id",
    }
)
_EVENT_KEYS = frozenset(
    {
        "actor",
        "contract",
        "entity_id",
        "entity_sha256",
        "entity_type",
        "parent_entity_id",
        "parent_entity_sha256",
    }
)
_HEAD_KEYS = frozenset({"contract", "correlation_id", "event_count", "head_hash"})


def _record_digest(record: object) -> str:
    normalized = json.loads(
        json.dumps(asdict(record), allow_nan=False, ensure_ascii=True, separators=(",", ":"))
    )
    return _sha(_canonical(normalized))


def _exact_ids(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not _ENTITY_ID.fullmatch(item) for item in value
    ):
        raise DomainIntegrityError(f"{label} is invalid")
    result = tuple(value)
    if result != tuple(sorted(set(result))):
        raise DomainIntegrityError(f"{label} must be sorted and unique")
    return result


class DomainLedgerRepository:
    """Workspace-bound, default-off M2a shadow repository.

    ``legacy-default`` is intentionally unavailable.  Records created here are
    evidence shadows only and are never consulted by current authorization,
    dispatch, mission, or tool-audit paths.
    """

    def __init__(
        self,
        registry: WorkspaceRegistry,
        workspace_id: str,
        *,
        enabled: bool | None = None,
    ):
        if not isinstance(registry, WorkspaceRegistry):
            raise TypeError("registry must be a WorkspaceRegistry")
        if enabled is not None and type(enabled) is not bool:
            raise TypeError("enabled must be bool or None")
        if not isinstance(workspace_id, str) or not _SAFE_ID.fullmatch(workspace_id):
            raise DomainIsolationError("an explicit valid workspace_id is required")
        if workspace_id == LEGACY_WORKSPACE_ID:
            raise DomainIsolationError("legacy-default is unavailable to M2a shadow records")
        self.registry = registry
        self.workspace_id = workspace_id
        self.enabled = m2a_domain_ledger_enabled() if enabled is None else enabled

    def initialize(self) -> "DomainLedgerRepository":
        if not self.enabled:
            raise DomainLedgerDisabled(
                f"{M2A_DOMAIN_LEDGER_FLAG} is disabled; M2a is not part of runtime"
            )
        self.registry.initialize()
        try:
            record = self.registry.require_active(self.workspace_id)
        except WorkspaceError as exc:
            raise DomainIsolationError("M2a workspace is unavailable") from exc
        if record.workspace_id != self.workspace_id:
            raise DomainIsolationError("workspace resolver returned another scope")
        self.verify_integrity()
        return self

    def _connection(self) -> sqlite3.Connection:
        if not self.enabled:
            raise DomainLedgerDisabled(f"{M2A_DOMAIN_LEDGER_FLAG} is disabled")
        return self.registry._connection()

    @contextmanager
    def _transaction(self, *, write: bool) -> Iterable[sqlite3.Connection]:
        with _LEDGER_LOCK:
            connection = self._connection()
            if connection.in_transaction:
                raise DomainLedgerError("control-plane connection already has a transaction")
            try:
                connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                self._validate_workspace_locked(connection)
                yield connection
                connection.execute("COMMIT")
            except DomainLedgerError:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            except sqlite3.DatabaseError as exc:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise ControlPlaneIOError(f"M2a shadow repository database failure: {exc}") from exc
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def _validate_workspace_locked(self, connection: sqlite3.Connection) -> None:
        if self.workspace_id == LEGACY_WORKSPACE_ID:
            raise DomainIsolationError("legacy-default is unavailable to M2a shadow records")
        row = connection.execute(
            "SELECT status FROM workspaces WHERE workspace_id=?", (self.workspace_id,)
        ).fetchone()
        if row is None or row[0] != "active":
            raise DomainIsolationError("M2a workspace is missing or inactive")

    def _validate_mission_locked(
        self, connection: sqlite3.Connection, mission_id: str | None
    ) -> None:
        if mission_id is None:
            return
        if not isinstance(mission_id, str) or not _SAFE_ID.fullmatch(mission_id):
            raise DomainContractError("mission_id is invalid")
        row = connection.execute(
            "SELECT workspace_id,operational_phase FROM mission_contexts WHERE mission_id=?",
            (mission_id,),
        ).fetchone()
        if row is None:
            raise DomainIsolationError("mission context is unavailable")
        if row[0] != self.workspace_id:
            raise DomainIsolationError("mission context belongs to another workspace")
        if row[1] == "PENDING_REVIEW":
            raise DomainIsolationError("mission context is pending review")

    @staticmethod
    def _before_event_append() -> None:
        """Fault-injection seam used only by tests."""

    @staticmethod
    def _before_commit() -> None:
        """Fault-injection seam used only by tests."""

    @staticmethod
    def _evidence_from_row(row: Iterable[object]) -> EvidenceRecord:
        values = tuple(row)
        if len(values) != 7:
            raise DomainIntegrityError("evidence row width is invalid")
        evidence_id, workspace_id, mission_id, version, content_hash, payload_text, created_at = values
        payload = _parse_payload(payload_text, _EVIDENCE_KEYS, "evidence")
        if (
            not isinstance(evidence_id, str)
            or not evidence_id.startswith("m2a-evidence-")
            or not _ENTITY_ID.fullmatch(evidence_id)
            or type(version) is not int
            or version != DOMAIN_CONTRACT_VERSION
            or payload.get("contract") != "EvidenceRecord.v1"
            or payload.get("source_kind") not in _SOURCE_KINDS
            or payload.get("freshness") not in _FRESHNESS
            or type(payload.get("credibility_bp")) is not int
            or not 0 <= int(payload["credibility_bp"]) <= 10_000
        ):
            raise DomainIntegrityError("evidence row violates the v1 contract")
        _digest(content_hash, "evidence content_sha256")
        _digest(payload.get("source_identity_sha256"), "evidence source identity")
        _digest(payload.get("access_license_sha256"), "evidence access/license")
        _digest(payload.get("input_sha256"), "evidence input")
        observed_at = _timestamp(payload.get("observed_at"), "evidence observed_at")
        persisted_at = _timestamp(created_at, "evidence created_at")
        if observed_at != persisted_at:
            raise DomainIntegrityError("evidence observed/created timestamps diverge")
        validity = payload.get("validity_seconds")
        if validity is not None and (type(validity) is not int or not 1 <= validity <= 31_536_000):
            raise DomainIntegrityError("evidence validity_seconds is invalid")
        valid_until = payload.get("valid_until")
        if (validity is None) != (valid_until is None):
            raise DomainIntegrityError("evidence validity window is incomplete")
        if valid_until is not None:
            _timestamp(valid_until, "evidence valid_until")
            expected = datetime.fromisoformat(observed_at) + timedelta(seconds=validity)
            if datetime.fromisoformat(str(valid_until)) != expected:
                raise DomainIntegrityError("evidence validity window diverges")
        correlation = payload.get("correlation_id")
        if not isinstance(correlation, str) or not _CORRELATION_ID.fullmatch(correlation):
            raise DomainIntegrityError("evidence correlation_id is invalid")
        artifact_id = payload.get("artifact_id")
        if artifact_id is not None and (
            not isinstance(artifact_id, str) or not _SAFE_ID.fullmatch(artifact_id)
        ):
            raise DomainIntegrityError("evidence artifact_id is invalid")
        if mission_id is not None and (
            not isinstance(mission_id, str) or not _SAFE_ID.fullmatch(mission_id)
        ):
            raise DomainIntegrityError("evidence mission_id is invalid")
        return EvidenceRecord(
            str(evidence_id),
            str(workspace_id),
            mission_id if isinstance(mission_id, str) else None,
            correlation,
            str(payload["source_kind"]),
            str(payload["source_identity_sha256"]),
            str(content_hash),
            artifact_id if isinstance(artifact_id, str) else None,
            int(payload["credibility_bp"]),
            str(payload["freshness"]),
            validity if isinstance(validity, int) else None,
            observed_at,
            valid_until if isinstance(valid_until, str) else None,
            str(payload["access_license_sha256"]),
            str(payload["input_sha256"]),
            persisted_at,
        )

    @staticmethod
    def _claim_from_row(row: Iterable[object]) -> ClaimRecord:
        values = tuple(row)
        if len(values) != 7:
            raise DomainIntegrityError("claim row width is invalid")
        claim_id, workspace_id, version, status, payload_text, created_at, updated_at = values
        payload = _parse_payload(payload_text, _CLAIM_KEYS, "claim")
        if (
            not isinstance(claim_id, str)
            or not claim_id.startswith("m2a-claim-")
            or not _ENTITY_ID.fullmatch(claim_id)
            or type(version) is not int
            or version != DOMAIN_CONTRACT_VERSION
            or status not in _VERIFICATION
            or payload.get("contract") != "Claim.v1"
            or payload.get("claim_kind") not in _CLAIM_KINDS
            or type(payload.get("confidence_bp")) is not int
            or not 0 <= int(payload["confidence_bp"]) <= 10_000
        ):
            raise DomainIntegrityError("claim row violates the v1 contract")
        _digest(payload.get("statement_sha256"), "claim statement")
        _digest(payload.get("input_sha256"), "claim input")
        correlation = payload.get("correlation_id")
        if not isinstance(correlation, str) or not _CORRELATION_ID.fullmatch(correlation):
            raise DomainIntegrityError("claim correlation_id is invalid")
        evidence_ids = _exact_ids(payload.get("evidence_ids"), "claim evidence_ids")
        contradictions = _exact_ids(
            payload.get("contradiction_claim_ids"), "claim contradiction IDs"
        )
        mission_id = payload.get("mission_id")
        if mission_id is not None and (
            not isinstance(mission_id, str) or not _SAFE_ID.fullmatch(mission_id)
        ):
            raise DomainIntegrityError("claim mission_id is invalid")
        supersedes = payload.get("supersedes_claim_id")
        if supersedes is not None and (
            not isinstance(supersedes, str)
            or not supersedes.startswith("m2a-claim-")
            or not _ENTITY_ID.fullmatch(supersedes)
        ):
            raise DomainIntegrityError("claim supersedes identity is invalid")
        if claim_id in contradictions or claim_id == supersedes:
            raise DomainIntegrityError("claim cannot contradict or supersede itself")
        validity = payload.get("validity_seconds")
        if validity is not None and (type(validity) is not int or not 1 <= validity <= 31_536_000):
            raise DomainIntegrityError("claim validity_seconds is invalid")
        created = _timestamp(created_at, "claim created_at")
        updated = _timestamp(updated_at, "claim updated_at")
        if created != updated:
            raise DomainIntegrityError("M2a claims are immutable revisions")
        valid_until = payload.get("valid_until")
        if (validity is None) != (valid_until is None):
            raise DomainIntegrityError("claim validity window is incomplete")
        if valid_until is not None:
            _timestamp(valid_until, "claim valid_until")
            expected = datetime.fromisoformat(created) + timedelta(seconds=validity)
            if datetime.fromisoformat(str(valid_until)) != expected:
                raise DomainIntegrityError("claim validity window diverges")
        return ClaimRecord(
            str(claim_id),
            str(workspace_id),
            mission_id if isinstance(mission_id, str) else None,
            correlation,
            str(payload["claim_kind"]),
            str(payload["statement_sha256"]),
            evidence_ids,
            int(payload["confidence_bp"]),
            str(status),
            validity if isinstance(validity, int) else None,
            valid_until if isinstance(valid_until, str) else None,
            contradictions,
            supersedes if isinstance(supersedes, str) else None,
            str(payload["input_sha256"]),
            created,
            updated,
        )

    @staticmethod
    def _request_from_row(row: Iterable[object]) -> ActionRequestRecord:
        values = tuple(row)
        if len(values) != 10:
            raise DomainIntegrityError("action request row width is invalid")
        (
            request_id,
            workspace_id,
            mission_id,
            version,
            idem,
            status,
            payload_hash,
            payload_text,
            created_at,
            updated_at,
        ) = values
        payload = _parse_payload(payload_text, _REQUEST_KEYS, "action request")
        if (
            not isinstance(request_id, str)
            or not request_id.startswith("m2a-request-")
            or not _ENTITY_ID.fullmatch(request_id)
            or type(version) is not int
            or version != DOMAIN_CONTRACT_VERSION
            or not isinstance(idem, str)
            or not _IDEMPOTENCY_KEY.fullmatch(idem)
            or request_id != "m2a-request-" + idem.removeprefix("m2a:")
            or status not in _REQUEST_STATUSES
            or payload.get("contract") != "ActionRequest.v1"
            or payload.get("risk") not in _RISKS
            or payload.get("approval_policy") not in _APPROVAL_POLICIES
            or payload.get("data_class") not in _DATA_CLASSES
            or type(payload.get("dry_run")) is not bool
            or payload.get("dry_run") is not True
            or not isinstance(payload.get("connector"), str)
            or not _SLUG.fullmatch(str(payload["connector"]))
            or not isinstance(payload.get("operation"), str)
            or not _SLUG.fullmatch(str(payload["operation"]))
        ):
            raise DomainIntegrityError("action request row violates the v1 shadow contract")
        _digest(payload_hash, "action request payload")
        for key in (
            "input_sha256",
            "rollback_plan_sha256",
            "target_sha256",
            "verification_plan_sha256",
        ):
            _digest(payload.get(key), f"action request {key}")
        correlation = payload.get("correlation_id")
        if not isinstance(correlation, str) or not _CORRELATION_ID.fullmatch(correlation):
            raise DomainIntegrityError("action request correlation_id is invalid")
        if mission_id is not None and (
            not isinstance(mission_id, str) or not _SAFE_ID.fullmatch(mission_id)
        ):
            raise DomainIntegrityError("action request mission_id is invalid")
        created = _timestamp(created_at, "action request created_at")
        updated = _timestamp(updated_at, "action request updated_at")
        if datetime.fromisoformat(updated) < datetime.fromisoformat(created):
            raise DomainIntegrityError("action request update precedes creation")
        return ActionRequestRecord(
            str(request_id),
            str(workspace_id),
            mission_id if isinstance(mission_id, str) else None,
            correlation,
            str(payload["connector"]),
            str(payload["operation"]),
            str(payload["target_sha256"]),
            str(payload_hash),
            str(idem),
            str(payload["risk"]),
            str(payload["approval_policy"]),
            str(payload["data_class"]),
            True,
            str(payload["verification_plan_sha256"]),
            str(payload["rollback_plan_sha256"]),
            str(payload["input_sha256"]),
            str(status),
            created,
            updated,
        )

    @staticmethod
    def _receipt_from_row(row: Iterable[object]) -> ActionReceiptRecord:
        values = tuple(row)
        if len(values) != 7:
            raise DomainIntegrityError("action receipt row width is invalid")
        receipt_id, request_id, version, outcome, payload_text, created_at, request_workspace = values
        payload = _parse_payload(payload_text, _RECEIPT_KEYS, "action receipt")
        if (
            not isinstance(receipt_id, str)
            or not receipt_id.startswith("m2a-receipt-")
            or not _ENTITY_ID.fullmatch(receipt_id)
            or not isinstance(request_id, str)
            or not request_id.startswith("m2a-request-")
            or not _ENTITY_ID.fullmatch(request_id)
            or type(version) is not int
            or version != DOMAIN_CONTRACT_VERSION
            or outcome not in _OUTCOMES
            or payload.get("contract") != "ActionReceipt.v1"
            or payload.get("workspace_id") != request_workspace
            or type(payload.get("reconciliation")) is not bool
        ):
            raise DomainIntegrityError("action receipt row violates the v1 shadow contract")
        for key in (
            "after_sha256",
            "before_sha256",
            "input_sha256",
            "output_sha256",
            "provider_request_sha256",
            "rollback_sha256",
            "verification_sha256",
        ):
            _digest(payload.get(key), f"action receipt {key}")
        correlation = payload.get("correlation_id")
        if not isinstance(correlation, str) or not _CORRELATION_ID.fullmatch(correlation):
            raise DomainIntegrityError("action receipt correlation_id is invalid")
        supersedes = payload.get("supersedes_receipt_id")
        reconciliation = payload.get("reconciliation") is True
        if reconciliation != (supersedes is not None):
            raise DomainIntegrityError("receipt reconciliation contract is incomplete")
        if supersedes is not None and (
            not isinstance(supersedes, str)
            or not supersedes.startswith("m2a-receipt-")
            or not _ENTITY_ID.fullmatch(supersedes)
            or supersedes == receipt_id
        ):
            raise DomainIntegrityError("receipt supersedes identity is invalid")
        error_class = payload.get("error_class")
        if not isinstance(error_class, str) or (
            error_class and not _SLUG.fullmatch(error_class)
        ):
            raise DomainIntegrityError("receipt error_class is invalid")
        if outcome == "succeeded" and (
            payload.get("verification_sha256") in _EMPTY_MATERIAL_HASHES
            or (
                payload.get("after_sha256") in _EMPTY_MATERIAL_HASHES
                and payload.get("output_sha256") in _EMPTY_MATERIAL_HASHES
            )
        ):
            raise DomainIntegrityError(
                "shadow succeeded observation lacks material verification proof"
            )
        if outcome == "failed" and (
            not error_class
            or (
                payload.get("verification_sha256") in _EMPTY_MATERIAL_HASHES
                and payload.get("output_sha256") in _EMPTY_MATERIAL_HASHES
            )
        ):
            raise DomainIntegrityError(
                "shadow failed observation lacks error/evidence proof"
            )
        observed = _timestamp(payload.get("observed_at"), "receipt observed_at")
        created = _timestamp(created_at, "receipt created_at")
        if observed != created:
            raise DomainIntegrityError("receipt observed/created timestamps diverge")
        return ActionReceiptRecord(
            str(receipt_id),
            str(request_id),
            str(request_workspace),
            correlation,
            str(outcome),
            str(payload["provider_request_sha256"]),
            str(payload["before_sha256"]),
            str(payload["after_sha256"]),
            str(payload["output_sha256"]),
            str(payload["verification_sha256"]),
            str(payload["rollback_sha256"]),
            error_class,
            supersedes if isinstance(supersedes, str) else None,
            reconciliation,
            str(payload["input_sha256"]),
            observed,
            created,
        )

    @staticmethod
    def _event_from_row(row: Iterable[object]) -> EventEnvelope:
        values = tuple(row)
        if len(values) != 10:
            raise DomainIntegrityError("event envelope row width is invalid")
        (
            event_id,
            workspace_id,
            mission_id,
            correlation_id,
            version,
            event_type,
            payload_text,
            previous_hash,
            event_hash,
            created_at,
        ) = values
        payload = _parse_payload(payload_text, _EVENT_KEYS, "event envelope")
        if (
            not isinstance(event_id, str)
            or not event_id.startswith("m2a-event-")
            or not _ENTITY_ID.fullmatch(event_id)
            or type(version) is not int
            or version != DOMAIN_CONTRACT_VERSION
            or event_type not in _EVENT_TYPES
            or payload.get("contract") != "EventEnvelope.v1"
            or payload.get("actor") != "m2a-shadow-repository"
            or payload.get("entity_type") not in _ENTITY_TYPES
            or not isinstance(correlation_id, str)
            or not _CORRELATION_ID.fullmatch(correlation_id)
        ):
            raise DomainIntegrityError("event envelope violates the v1 shadow contract")
        entity_id = payload.get("entity_id")
        if not isinstance(entity_id, str) or not _ENTITY_ID.fullmatch(entity_id):
            raise DomainIntegrityError("event entity identity is invalid")
        _digest(payload.get("entity_sha256"), "event entity digest")
        parent_id = payload.get("parent_entity_id")
        parent_hash = payload.get("parent_entity_sha256")
        if (parent_id is None) != (parent_hash is None):
            raise DomainIntegrityError("event parent identity/digest is incomplete")
        if parent_id is not None and (
            not isinstance(parent_id, str) or not _ENTITY_ID.fullmatch(parent_id)
        ):
            raise DomainIntegrityError("event parent identity is invalid")
        _digest(parent_hash, "event parent digest", optional=True)
        _digest(previous_hash, "event previous_hash")
        _digest(event_hash, "event event_hash")
        created = _timestamp(created_at, "event created_at")
        expected = _row_digest(
            (
                event_id,
                workspace_id,
                mission_id,
                correlation_id,
                version,
                event_type,
                payload_text,
                previous_hash,
                created,
            )
        )
        expected_id = _event_identity(
            str(workspace_id),
            mission_id if isinstance(mission_id, str) else None,
            str(correlation_id),
            str(event_type),
            str(payload_text),
            str(previous_hash),
            created,
        )
        if event_hash != expected or event_id != expected_id:
            raise DomainIntegrityError("event envelope hash diverges")
        if mission_id is not None and (
            not isinstance(mission_id, str) or not _SAFE_ID.fullmatch(mission_id)
        ):
            raise DomainIntegrityError("event mission_id is invalid")
        return EventEnvelope(
            str(event_id),
            str(workspace_id),
            mission_id if isinstance(mission_id, str) else None,
            str(correlation_id),
            str(event_type),
            str(payload["entity_type"]),
            entity_id,
            str(payload["entity_sha256"]),
            parent_id if isinstance(parent_id, str) else None,
            parent_hash if isinstance(parent_hash, str) else None,
            str(previous_hash),
            str(event_hash),
            created,
        )

    def _heads_locked(
        self, connection: sqlite3.Connection
    ) -> dict[str, tuple[str, int, str, str]]:
        heads: dict[str, tuple[str, int, str, str]] = {}
        rows = connection.execute(
            "SELECT projection_id,workspace_id,schema_version,projection_type,payload_json,"
            "created_at,updated_at FROM projections WHERE workspace_id=? AND "
            "(projection_type='m2a_event_chain_head' OR projection_id LIKE 'm2a-event-head-%')",
            (self.workspace_id,),
        ).fetchall()
        for row in rows:
            projection_id, workspace_id, version, projection_type, payload_text, created, updated = row
            payload = _parse_payload(payload_text, _HEAD_KEYS, "event-chain head")
            correlation = payload.get("correlation_id")
            head_hash = payload.get("head_hash")
            count = payload.get("event_count")
            if (
                workspace_id != self.workspace_id
                or type(version) is not int
                or version != DOMAIN_CONTRACT_VERSION
                or projection_type != "m2a_event_chain_head"
                or payload.get("contract") != "EventChainHead.v1"
                or not isinstance(correlation, str)
                or not _CORRELATION_ID.fullmatch(correlation)
                or not isinstance(head_hash, str)
                or not _DIGEST.fullmatch(head_hash)
                or type(count) is not int
                or count < 1
                or projection_id != _entity_id("event-head", self.workspace_id, correlation)
            ):
                raise DomainIntegrityError("event-chain head violates the v1 contract")
            created_at = _timestamp(created, "event-chain head created_at")
            updated_at = _timestamp(updated, "event-chain head updated_at")
            if correlation in heads:
                raise DomainIntegrityError("duplicate event-chain head")
            heads[correlation] = (head_hash, count, created_at, updated_at)
        return heads

    def _ordered_events_locked(
        self, connection: sqlite3.Connection
    ) -> dict[str, tuple[EventEnvelope, ...]]:
        rows = connection.execute(
            "SELECT event_id,workspace_id,mission_id,correlation_id,schema_version,event_type,"
            "payload_json,previous_hash,event_hash,created_at FROM event_envelopes "
            "WHERE workspace_id=?",
            (self.workspace_id,),
        ).fetchall()
        grouped: dict[str, list[EventEnvelope]] = {}
        for row in rows:
            event = self._event_from_row(row)
            if event.workspace_id != self.workspace_id:
                raise DomainIsolationError("event envelope crossed workspace scope")
            grouped.setdefault(event.correlation_id, []).append(event)
        heads = self._heads_locked(connection)
        if set(grouped) != set(heads):
            raise DomainIntegrityError("event chains and head projections diverge")
        ordered: dict[str, tuple[EventEnvelope, ...]] = {}
        for correlation, events in grouped.items():
            children: dict[str, EventEnvelope] = {}
            for event in events:
                if event.previous_hash in children:
                    raise DomainIntegrityError("event chain forks")
                children[event.previous_hash] = event
            chain: list[EventEnvelope] = []
            cursor = _ZERO_HASH
            while cursor in children:
                event = children[cursor]
                chain.append(event)
                cursor = event.event_hash
            if len(chain) != len(events):
                raise DomainIntegrityError("event chain is disconnected or cyclic")
            head_hash, count, created_at, updated_at = heads[correlation]
            if (
                not chain
                or cursor != head_hash
                or len(chain) != count
                or chain[0].created_at != created_at
                or chain[-1].created_at != updated_at
            ):
                raise DomainIntegrityError("event-chain head/count/timestamps diverge")
            if any(
                datetime.fromisoformat(later.created_at)
                < datetime.fromisoformat(earlier.created_at)
                for earlier, later in zip(chain, chain[1:])
            ):
                raise DomainIntegrityError("event chain timestamps move backwards")
            ordered[correlation] = tuple(chain)
        return ordered

    def _load_entities_locked(
        self, connection: sqlite3.Connection
    ) -> tuple[
        dict[str, EvidenceRecord],
        dict[str, ClaimRecord],
        dict[str, ActionRequestRecord],
        dict[str, ActionReceiptRecord],
    ]:
        evidence = {
            record.evidence_id: record
            for record in (
                self._evidence_from_row(row)
                for row in connection.execute(
                    "SELECT evidence_id,workspace_id,mission_id,schema_version,content_sha256,"
                    "payload_json,created_at FROM evidence_records WHERE workspace_id=?",
                    (self.workspace_id,),
                ).fetchall()
            )
        }
        claims = {
            record.claim_id: record
            for record in (
                self._claim_from_row(row)
                for row in connection.execute(
                    "SELECT claim_id,workspace_id,schema_version,verification_status,payload_json,"
                    "created_at,updated_at FROM claims WHERE workspace_id=?",
                    (self.workspace_id,),
                ).fetchall()
            )
        }
        requests = {
            record.request_id: record
            for record in (
                self._request_from_row(row)
                for row in connection.execute(
                    "SELECT request_id,workspace_id,mission_id,schema_version,idempotency_key,status,"
                    "payload_sha256,payload_json,created_at,updated_at FROM action_requests "
                    "WHERE workspace_id=?",
                    (self.workspace_id,),
                ).fetchall()
            )
        }
        receipts = {
            record.receipt_id: record
            for record in (
                self._receipt_from_row(row)
                for row in connection.execute(
                    "SELECT r.receipt_id,r.request_id,r.schema_version,r.outcome,r.payload_json,"
                    "r.created_at,q.workspace_id FROM action_receipts r JOIN action_requests q "
                    "ON q.request_id=r.request_id WHERE q.workspace_id=?",
                    (self.workspace_id,),
                ).fetchall()
            )
        }
        if any(record.workspace_id != self.workspace_id for record in evidence.values()):
            raise DomainIsolationError("evidence crossed workspace scope")
        if any(record.workspace_id != self.workspace_id for record in claims.values()):
            raise DomainIsolationError("claim crossed workspace scope")
        if any(record.workspace_id != self.workspace_id for record in requests.values()):
            raise DomainIsolationError("action request crossed workspace scope")
        if any(record.workspace_id != self.workspace_id for record in receipts.values()):
            raise DomainIsolationError("action receipt crossed workspace scope")
        return evidence, claims, requests, receipts

    def _verify_locked(self, connection: sqlite3.Connection) -> None:
        foreign = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign:
            raise DomainIntegrityError("control-plane foreign-key integrity failed")
        evidence, claims, requests, receipts = self._load_entities_locked(connection)
        chains = self._ordered_events_locked(connection)
        events = [event for chain in chains.values() for event in chain]
        by_entity: dict[tuple[str, str], list[EventEnvelope]] = {}
        for event in events:
            by_entity.setdefault((event.entity_type, event.entity_id), []).append(event)

        for record in evidence.values():
            self._validate_mission_locked(connection, record.mission_id)
            if record.artifact_id is not None:
                artifact = connection.execute(
                    "SELECT 1 FROM artifact_index WHERE artifact_id=? AND workspace_id=?",
                    (record.artifact_id, self.workspace_id),
                ).fetchone()
                if artifact is None:
                    raise DomainIntegrityError("evidence artifact reference is unavailable")
            linked = by_entity.get(("evidence", record.evidence_id), [])
            if len(linked) != 1 or linked[0].event_type != "evidence.recorded":
                raise DomainIntegrityError("evidence event binding is missing or duplicated")
            if (
                linked[0].entity_sha256 != _record_digest(record)
                or linked[0].mission_id != record.mission_id
                or linked[0].correlation_id != record.correlation_id
                or linked[0].parent_entity_id is not None
            ):
                raise DomainIntegrityError("evidence event digest/scope diverges")

        for record in claims.values():
            self._validate_mission_locked(connection, record.mission_id)
            for evidence_id in record.evidence_ids:
                source = evidence.get(evidence_id)
                if source is None:
                    raise DomainIntegrityError("claim references unavailable evidence")
                if source.mission_id != record.mission_id:
                    raise DomainIsolationError("claim/evidence mission scopes diverge")
            for claim_id in record.contradiction_claim_ids:
                referenced = claims.get(claim_id)
                if referenced is None:
                    raise DomainIntegrityError("claim contradiction reference is unavailable")
                if referenced.mission_id != record.mission_id:
                    raise DomainIsolationError("contradictory claims cross mission scope")
            if record.supersedes_claim_id is not None:
                superseded = claims.get(record.supersedes_claim_id)
                if superseded is None:
                    raise DomainIntegrityError("superseded claim is unavailable")
                if superseded.mission_id != record.mission_id:
                    raise DomainIsolationError("claim revision crosses mission scope")
            linked = by_entity.get(("claim", record.claim_id), [])
            if len(linked) != 1 or linked[0].event_type != "claim.recorded":
                raise DomainIntegrityError("claim event binding is missing or duplicated")
            if (
                linked[0].entity_sha256 != _record_digest(record)
                or linked[0].mission_id != record.mission_id
                or linked[0].correlation_id != record.correlation_id
                or linked[0].parent_entity_id is not None
            ):
                raise DomainIntegrityError("claim event digest/scope diverges")

        receipts_by_request: dict[str, list[ActionReceiptRecord]] = {}
        for receipt in receipts.values():
            request = requests.get(receipt.request_id)
            if request is None:
                raise DomainIntegrityError("receipt references unavailable request")
            if receipt.correlation_id != request.correlation_id:
                raise DomainIntegrityError("receipt/request correlations diverge")
            linked = by_entity.get(("action_receipt", receipt.receipt_id), [])
            if len(linked) != 1 or linked[0].event_type != "action.receipt.recorded":
                raise DomainIntegrityError("receipt event binding is missing or duplicated")
            event = linked[0]
            if (
                event.entity_sha256 != _record_digest(receipt)
                or event.parent_entity_id != request.request_id
                or event.mission_id != request.mission_id
                or event.correlation_id != request.correlation_id
            ):
                raise DomainIntegrityError("receipt event digest/scope diverges")
            receipts_by_request.setdefault(request.request_id, []).append(receipt)

        event_position = {event.event_id: index for index, event in enumerate(events)}
        for request in requests.values():
            self._validate_mission_locked(connection, request.mission_id)
            request_events = by_entity.get(("action_request", request.request_id), [])
            if len(request_events) != 1 or request_events[0].event_type != "action.request.recorded":
                raise DomainIntegrityError("action request event binding is missing or duplicated")
            initial = replace(request, status="proposed", updated_at=request.created_at)
            if (
                request_events[0].entity_sha256 != _record_digest(initial)
                or request_events[0].mission_id != request.mission_id
                or request_events[0].correlation_id != request.correlation_id
                or request_events[0].parent_entity_id is not None
            ):
                raise DomainIntegrityError("action request initial event diverges")
            related = receipts_by_request.get(request.request_id, [])
            if not related:
                if request.status != "proposed" or request.updated_at != request.created_at:
                    raise DomainIntegrityError("receipt-free action request status diverges")
                continue
            related.sort(
                key=lambda item: event_position[
                    by_entity[("action_receipt", item.receipt_id)][0].event_id
                ]
            )
            if related[0].reconciliation or related[0].supersedes_receipt_id is not None:
                raise DomainIntegrityError("initial receipt is marked as reconciliation")
            for previous, current in zip(related, related[1:]):
                if not current.reconciliation or current.supersedes_receipt_id != previous.receipt_id:
                    raise DomainIntegrityError("receipt reconciliation chain diverges")
                if previous.outcome not in {"partial", "unknown"}:
                    raise DomainIntegrityError("receipt reconciles a terminal observation")
            latest = related[-1]
            expected_status = (
                "reconciliation_required"
                if latest.outcome in {"partial", "unknown"}
                else "recorded"
            )
            if request.status != expected_status or request.updated_at != latest.created_at:
                raise DomainIntegrityError("action request shadow status diverges from receipt")
            latest_event = by_entity[("action_receipt", latest.receipt_id)][0]
            if latest_event.parent_entity_sha256 != _record_digest(request):
                raise DomainIntegrityError("latest receipt does not seal current request status")

        known = {
            *(('evidence', key) for key in evidence),
            *(('claim', key) for key in claims),
            *(('action_request', key) for key in requests),
            *(('action_receipt', key) for key in receipts),
        }
        if set(by_entity) != known:
            raise DomainIntegrityError("event envelopes contain unknown or missing entities")

    def verify_integrity(self) -> None:
        with self._transaction(write=False) as connection:
            self._verify_locked(connection)

    def _append_event_locked(
        self,
        connection: sqlite3.Connection,
        *,
        mission_id: str | None,
        correlation_id: str,
        event_type: str,
        entity_type: str,
        entity_id: str,
        entity_sha256: str,
        parent_entity_id: str | None = None,
        parent_entity_sha256: str | None = None,
    ) -> EventEnvelope:
        self._before_event_append()
        chains = self._ordered_events_locked(connection)
        chain = chains.get(correlation_id, ())
        previous_hash = chain[-1].event_hash if chain else _ZERO_HASH
        payload_text = _canonical(
            {
                "actor": "m2a-shadow-repository",
                "contract": "EventEnvelope.v1",
                "entity_id": entity_id,
                "entity_sha256": entity_sha256,
                "entity_type": entity_type,
                "parent_entity_id": parent_entity_id,
                "parent_entity_sha256": parent_entity_sha256,
            }
        )
        created_at = _now()
        event_id = _event_identity(
            self.workspace_id,
            mission_id,
            correlation_id,
            event_type,
            payload_text,
            previous_hash,
            created_at,
        )
        event_hash = _row_digest(
            (
                event_id,
                self.workspace_id,
                mission_id,
                correlation_id,
                DOMAIN_CONTRACT_VERSION,
                event_type,
                payload_text,
                previous_hash,
                created_at,
            )
        )
        connection.execute(
            "INSERT INTO event_envelopes VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                self.workspace_id,
                mission_id,
                correlation_id,
                DOMAIN_CONTRACT_VERSION,
                event_type,
                payload_text,
                previous_hash,
                event_hash,
                created_at,
            ),
        )
        projection_id = _entity_id("event-head", self.workspace_id, correlation_id)
        existing = connection.execute(
            "SELECT created_at FROM projections WHERE projection_id=?", (projection_id,)
        ).fetchone()
        head_payload = _canonical(
            {
                "contract": "EventChainHead.v1",
                "correlation_id": correlation_id,
                "event_count": len(chain) + 1,
                "head_hash": event_hash,
            }
        )
        connection.execute(
            "INSERT INTO projections VALUES(?,?,?,?,?,?,?) ON CONFLICT(projection_id) "
            "DO UPDATE SET schema_version=excluded.schema_version,projection_type=excluded.projection_type,"
            "payload_json=excluded.payload_json,updated_at=excluded.updated_at",
            (
                projection_id,
                self.workspace_id,
                DOMAIN_CONTRACT_VERSION,
                "m2a_event_chain_head",
                head_payload,
                str(existing[0]) if existing else created_at,
                created_at,
            ),
        )
        return self._event_from_row(
            (
                event_id,
                self.workspace_id,
                mission_id,
                correlation_id,
                DOMAIN_CONTRACT_VERSION,
                event_type,
                payload_text,
                previous_hash,
                event_hash,
                created_at,
            )
        )

    def record_evidence(
        self,
        caller_key: str,
        correlation_key: str,
        source_kind: str,
        source_identity: bytes | str,
        content: bytes | str,
        *,
        mission_id: str | None = None,
        credibility_bp: int = 5_000,
        freshness: str = "unknown",
        validity_seconds: int | None = None,
        artifact_id: str | None = None,
        access_license_note: bytes | str = "",
    ) -> EvidenceRecord:
        caller = _safe_key(caller_key, "caller_key")
        correlation_key = _safe_key(correlation_key, "correlation_key")
        source_kind = _enum(source_kind, _SOURCE_KINDS, "source_kind")
        credibility = _basis_points(credibility_bp, "credibility_bp")
        freshness = _enum(freshness, _FRESHNESS, "freshness")
        validity = _validity_seconds(validity_seconds)
        source_hash = _sha(_safe_material(source_identity, "source_identity"))
        content_hash = _sha(_safe_material(content, "content"))
        access_hash = _sha(
            _safe_material(access_license_note, "access_license_note", allow_empty=True)
        )
        if artifact_id is not None:
            artifact_id = _safe_key(artifact_id, "artifact_id")
        correlation = _correlation_id(self.workspace_id, correlation_key)
        evidence_id = _entity_id("evidence", self.workspace_id, caller)
        semantic = {
            "artifact_id": artifact_id,
            "content_sha256": content_hash,
            "correlation_id": correlation,
            "credibility_bp": credibility,
            "freshness": freshness,
            "mission_id": mission_id,
            "source_identity_sha256": source_hash,
            "source_kind": source_kind,
            "validity_seconds": validity,
            "access_license_sha256": access_hash,
        }
        input_hash = _sha(_canonical(semantic))
        with self._transaction(write=True) as connection:
            self._verify_locked(connection)
            self._validate_mission_locked(connection, mission_id)
            existing = connection.execute(
                "SELECT evidence_id,workspace_id,mission_id,schema_version,content_sha256,"
                "payload_json,created_at FROM evidence_records WHERE evidence_id=?",
                (evidence_id,),
            ).fetchone()
            if existing is not None:
                record = self._evidence_from_row(existing)
                if record.workspace_id != self.workspace_id:
                    raise DomainIsolationError("evidence identity belongs to another workspace")
                if record.mission_id != mission_id or record.correlation_id != correlation:
                    raise DomainIntegrityError("evidence replay scope diverges")
                if record.input_sha256 != input_hash:
                    raise DomainConflict("evidence caller key was replayed with different input")
                return record
            if artifact_id is not None:
                artifact = connection.execute(
                    "SELECT 1 FROM artifact_index WHERE artifact_id=? AND workspace_id=?",
                    (artifact_id, self.workspace_id),
                ).fetchone()
                if artifact is None:
                    raise DomainContractError("artifact reference is unavailable in this workspace")
            created_at = _now()
            valid_until = (
                (datetime.fromisoformat(created_at) + timedelta(seconds=validity)).isoformat()
                if validity is not None
                else None
            )
            payload_text = _canonical(
                {
                    "access_license_sha256": access_hash,
                    "artifact_id": artifact_id,
                    "contract": "EvidenceRecord.v1",
                    "correlation_id": correlation,
                    "credibility_bp": credibility,
                    "freshness": freshness,
                    "input_sha256": input_hash,
                    "observed_at": created_at,
                    "source_identity_sha256": source_hash,
                    "source_kind": source_kind,
                    "valid_until": valid_until,
                    "validity_seconds": validity,
                }
            )
            connection.execute(
                "INSERT INTO evidence_records VALUES(?,?,?,?,?,?,?)",
                (
                    evidence_id,
                    self.workspace_id,
                    mission_id,
                    DOMAIN_CONTRACT_VERSION,
                    content_hash,
                    payload_text,
                    created_at,
                ),
            )
            record = self._evidence_from_row(
                (
                    evidence_id,
                    self.workspace_id,
                    mission_id,
                    DOMAIN_CONTRACT_VERSION,
                    content_hash,
                    payload_text,
                    created_at,
                )
            )
            self._append_event_locked(
                connection,
                mission_id=mission_id,
                correlation_id=correlation,
                event_type="evidence.recorded",
                entity_type="evidence",
                entity_id=evidence_id,
                entity_sha256=_record_digest(record),
            )
            self._verify_locked(connection)
            self._before_commit()
            return record

    def record_claim(
        self,
        caller_key: str,
        correlation_key: str,
        statement: bytes | str,
        evidence_ids: Iterable[str],
        *,
        mission_id: str | None = None,
        claim_kind: str = "unknown",
        confidence_bp: int = 0,
        verification_status: str = "unverified",
        validity_seconds: int | None = None,
        contradiction_claim_ids: Iterable[str] = (),
        supersedes_claim_id: str | None = None,
    ) -> ClaimRecord:
        caller = _safe_key(caller_key, "caller_key")
        correlation_key = _safe_key(correlation_key, "correlation_key")
        statement_hash = _sha(_safe_material(statement, "statement"))
        claim_kind = _enum(claim_kind, _CLAIM_KINDS, "claim_kind")
        confidence = _basis_points(confidence_bp, "confidence_bp")
        status = _enum(verification_status, _VERIFICATION, "verification_status")
        validity = _validity_seconds(validity_seconds)
        evidence = tuple(sorted(set(evidence_ids)))
        contradictions = tuple(sorted(set(contradiction_claim_ids)))
        if any(
            not isinstance(item, str)
            or not item.startswith("m2a-evidence-")
            or not _ENTITY_ID.fullmatch(item)
            for item in evidence
        ):
            raise DomainContractError("evidence_ids contain an invalid identity")
        if any(
            not isinstance(item, str)
            or not item.startswith("m2a-claim-")
            or not _ENTITY_ID.fullmatch(item)
            for item in contradictions
        ):
            raise DomainContractError("contradiction_claim_ids contain an invalid identity")
        if supersedes_claim_id is not None and (
            not isinstance(supersedes_claim_id, str)
            or not supersedes_claim_id.startswith("m2a-claim-")
            or not _ENTITY_ID.fullmatch(supersedes_claim_id)
        ):
            raise DomainContractError("supersedes_claim_id is invalid")
        correlation = _correlation_id(self.workspace_id, correlation_key)
        claim_id = _entity_id("claim", self.workspace_id, caller)
        if claim_id in contradictions or claim_id == supersedes_claim_id:
            raise DomainContractError("claim cannot contradict or supersede itself")
        semantic = {
            "claim_kind": claim_kind,
            "confidence_bp": confidence,
            "contradiction_claim_ids": list(contradictions),
            "correlation_id": correlation,
            "evidence_ids": list(evidence),
            "mission_id": mission_id,
            "statement_sha256": statement_hash,
            "supersedes_claim_id": supersedes_claim_id,
            "validity_seconds": validity,
            "verification_status": status,
        }
        input_hash = _sha(_canonical(semantic))
        with self._transaction(write=True) as connection:
            self._verify_locked(connection)
            self._validate_mission_locked(connection, mission_id)
            existing = connection.execute(
                "SELECT claim_id,workspace_id,schema_version,verification_status,payload_json,"
                "created_at,updated_at FROM claims WHERE claim_id=?",
                (claim_id,),
            ).fetchone()
            if existing is not None:
                record = self._claim_from_row(existing)
                if record.workspace_id != self.workspace_id:
                    raise DomainIsolationError("claim identity belongs to another workspace")
                if record.mission_id != mission_id or record.correlation_id != correlation:
                    raise DomainIntegrityError("claim replay scope diverges")
                if record.input_sha256 != input_hash:
                    raise DomainConflict("claim caller key was replayed with different input")
                return record
            scoped_evidence = {
                row[0]: self._evidence_from_row(row)
                for row in connection.execute(
                    "SELECT evidence_id,workspace_id,mission_id,schema_version,content_sha256,"
                    "payload_json,created_at FROM evidence_records WHERE evidence_id IN "
                    f"({','.join('?' for _ in evidence)})"
                    if evidence
                    else "SELECT evidence_id,workspace_id,mission_id,schema_version,content_sha256,"
                    "payload_json,created_at FROM evidence_records WHERE 0",
                    evidence,
                ).fetchall()
            }
            if set(scoped_evidence) != set(evidence):
                raise DomainIsolationError("claim evidence is unavailable or cross-workspace")
            if any(item.workspace_id != self.workspace_id for item in scoped_evidence.values()):
                raise DomainIsolationError("claim evidence crossed workspace scope")
            if any(item.mission_id != mission_id for item in scoped_evidence.values()):
                raise DomainIsolationError("claim/evidence mission scopes diverge")
            referenced_claims = tuple(
                item for item in (*contradictions, supersedes_claim_id) if item is not None
            )
            if referenced_claims:
                rows = connection.execute(
                    "SELECT claim_id,workspace_id,schema_version,verification_status,payload_json,"
                    "created_at,updated_at FROM claims WHERE claim_id IN "
                    f"({','.join('?' for _ in referenced_claims)})",
                    referenced_claims,
                ).fetchall()
                referenced = {row[0]: self._claim_from_row(row) for row in rows}
                if set(referenced) != set(referenced_claims) or any(
                    row.workspace_id != self.workspace_id or row.mission_id != mission_id
                    for row in referenced.values()
                ):
                    raise DomainIsolationError("claim reference is unavailable or cross-workspace")
            created_at = _now()
            valid_until = (
                (datetime.fromisoformat(created_at) + timedelta(seconds=validity)).isoformat()
                if validity is not None
                else None
            )
            payload_text = _canonical(
                {
                    "claim_kind": claim_kind,
                    "confidence_bp": confidence,
                    "contract": "Claim.v1",
                    "contradiction_claim_ids": list(contradictions),
                    "correlation_id": correlation,
                    "evidence_ids": list(evidence),
                    "input_sha256": input_hash,
                    "mission_id": mission_id,
                    "statement_sha256": statement_hash,
                    "supersedes_claim_id": supersedes_claim_id,
                    "valid_until": valid_until,
                    "validity_seconds": validity,
                }
            )
            connection.execute(
                "INSERT INTO claims VALUES(?,?,?,?,?,?,?)",
                (
                    claim_id,
                    self.workspace_id,
                    DOMAIN_CONTRACT_VERSION,
                    status,
                    payload_text,
                    created_at,
                    created_at,
                ),
            )
            record = self._claim_from_row(
                (
                    claim_id,
                    self.workspace_id,
                    DOMAIN_CONTRACT_VERSION,
                    status,
                    payload_text,
                    created_at,
                    created_at,
                )
            )
            self._append_event_locked(
                connection,
                mission_id=mission_id,
                correlation_id=correlation,
                event_type="claim.recorded",
                entity_type="claim",
                entity_id=claim_id,
                entity_sha256=_record_digest(record),
            )
            self._verify_locked(connection)
            self._before_commit()
            return record

    def record_action_request(
        self,
        caller_key: str,
        correlation_key: str,
        connector: str,
        operation: str,
        target: bytes | str,
        payload: bytes | str,
        *,
        mission_id: str | None = None,
        risk: str = "low",
        approval_policy: str = "shadow_only",
        data_class: str = "internal",
        dry_run: bool = True,
        verification_plan: bytes | str = "",
        rollback_plan: bytes | str = "",
    ) -> ActionRequestRecord:
        caller = _safe_key(caller_key, "caller_key")
        correlation_key = _safe_key(correlation_key, "correlation_key")
        connector = _slug(connector, "connector")
        operation = _slug(operation, "operation")
        risk = _enum(risk, _RISKS, "risk")
        approval_policy = _enum(
            approval_policy, _APPROVAL_POLICIES, "approval_policy"
        )
        data_class = _enum(data_class, _DATA_CLASSES, "data_class")
        if type(dry_run) is not bool or dry_run is not True:
            raise DomainContractError("M2a action requests must remain dry-run shadows")
        target_hash = _sha(_safe_material(target, "target"))
        payload_hash = _sha(_safe_material(payload, "payload", allow_empty=True))
        verification_hash = _sha(
            _safe_material(verification_plan, "verification_plan", allow_empty=True)
        )
        rollback_hash = _sha(
            _safe_material(rollback_plan, "rollback_plan", allow_empty=True)
        )
        correlation = _correlation_id(self.workspace_id, correlation_key)
        idem = _idempotency_key(self.workspace_id, caller)
        request_id = "m2a-request-" + idem.removeprefix("m2a:")
        semantic = {
            "approval_policy": approval_policy,
            "connector": connector,
            "correlation_id": correlation,
            "data_class": data_class,
            "dry_run": True,
            "mission_id": mission_id,
            "operation": operation,
            "payload_sha256": payload_hash,
            "risk": risk,
            "rollback_plan_sha256": rollback_hash,
            "target_sha256": target_hash,
            "verification_plan_sha256": verification_hash,
        }
        input_hash = _sha(_canonical(semantic))
        with self._transaction(write=True) as connection:
            self._verify_locked(connection)
            self._validate_mission_locked(connection, mission_id)
            existing = connection.execute(
                "SELECT request_id,workspace_id,mission_id,schema_version,idempotency_key,status,"
                "payload_sha256,payload_json,created_at,updated_at FROM action_requests "
                "WHERE idempotency_key=?",
                (idem,),
            ).fetchone()
            if existing is not None:
                record = self._request_from_row(existing)
                if record.workspace_id != self.workspace_id:
                    raise DomainIsolationError("idempotency key crossed workspace scope")
                if record.input_sha256 != input_hash:
                    raise DomainConflict(
                        "action caller key was replayed with different materialized input"
                    )
                return record
            created_at = _now()
            payload_text = _canonical(
                {
                    "approval_policy": approval_policy,
                    "connector": connector,
                    "contract": "ActionRequest.v1",
                    "correlation_id": correlation,
                    "data_class": data_class,
                    "dry_run": True,
                    "input_sha256": input_hash,
                    "operation": operation,
                    "risk": risk,
                    "rollback_plan_sha256": rollback_hash,
                    "target_sha256": target_hash,
                    "verification_plan_sha256": verification_hash,
                }
            )
            connection.execute(
                "INSERT INTO action_requests VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    request_id,
                    self.workspace_id,
                    mission_id,
                    DOMAIN_CONTRACT_VERSION,
                    idem,
                    "proposed",
                    payload_hash,
                    payload_text,
                    created_at,
                    created_at,
                ),
            )
            record = self._request_from_row(
                (
                    request_id,
                    self.workspace_id,
                    mission_id,
                    DOMAIN_CONTRACT_VERSION,
                    idem,
                    "proposed",
                    payload_hash,
                    payload_text,
                    created_at,
                    created_at,
                )
            )
            self._append_event_locked(
                connection,
                mission_id=mission_id,
                correlation_id=correlation,
                event_type="action.request.recorded",
                entity_type="action_request",
                entity_id=request_id,
                entity_sha256=_record_digest(record),
            )
            self._verify_locked(connection)
            self._before_commit()
            return record

    def _record_receipt(
        self,
        request_id: str,
        caller_key: str,
        outcome: str,
        *,
        reconciliation: bool,
        supersedes_receipt_id: str | None,
        provider_request_id: bytes | str = "",
        before: bytes | str = "",
        after: bytes | str = "",
        output: bytes | str = "",
        verification: bytes | str = "",
        rollback: bytes | str = "",
        error_class: str = "",
    ) -> ActionReceiptRecord:
        if (
            not isinstance(request_id, str)
            or not request_id.startswith("m2a-request-")
            or not _ENTITY_ID.fullmatch(request_id)
        ):
            raise DomainContractError("request_id is invalid")
        caller = _safe_key(caller_key, "caller_key")
        outcome = _enum(outcome, _OUTCOMES, "outcome")
        if type(reconciliation) is not bool:
            raise TypeError("reconciliation must be bool")
        if reconciliation != (supersedes_receipt_id is not None):
            raise DomainContractError("reconciliation requires the superseded receipt")
        if supersedes_receipt_id is not None and (
            not isinstance(supersedes_receipt_id, str)
            or not supersedes_receipt_id.startswith("m2a-receipt-")
            or not _ENTITY_ID.fullmatch(supersedes_receipt_id)
        ):
            raise DomainContractError("supersedes_receipt_id is invalid")
        if not isinstance(error_class, str) or (
            error_class and not _SLUG.fullmatch(error_class)
        ):
            raise DomainContractError("error_class is invalid")
        materials = {
            "after": _safe_material(after, "after", allow_empty=True),
            "before": _safe_material(before, "before", allow_empty=True),
            "output": _safe_material(output, "output", allow_empty=True),
            "provider_request": _safe_material(
                provider_request_id, "provider_request_id", allow_empty=True
            ),
            "rollback": _safe_material(
                rollback, "receipt rollback", allow_empty=True
            ),
            "verification": _safe_material(
                verification, "receipt verification", allow_empty=True
            ),
        }
        hashes = {
            "after_sha256": _sha(materials["after"]),
            "before_sha256": _sha(materials["before"]),
            "output_sha256": _sha(materials["output"]),
            "provider_request_sha256": _sha(materials["provider_request"]),
            "rollback_sha256": _sha(materials["rollback"]),
            "verification_sha256": _sha(materials["verification"]),
        }
        receipt_id = _entity_id(
            "receipt", self.workspace_id, f"{request_id}:{caller}"
        )
        semantic = {
            **hashes,
            "error_class": error_class,
            "outcome": outcome,
            "reconciliation": reconciliation,
            "request_id": request_id,
            "supersedes_receipt_id": supersedes_receipt_id,
        }
        input_hash = _sha(_canonical(semantic))
        with self._transaction(write=True) as connection:
            self._verify_locked(connection)
            existing = connection.execute(
                "SELECT r.receipt_id,r.request_id,r.schema_version,r.outcome,r.payload_json,"
                "r.created_at,q.workspace_id FROM action_receipts r JOIN action_requests q "
                "ON q.request_id=r.request_id WHERE r.receipt_id=?",
                (receipt_id,),
            ).fetchone()
            if existing is not None:
                record = self._receipt_from_row(existing)
                if record.workspace_id != self.workspace_id:
                    raise DomainIsolationError("receipt caller key crossed workspace scope")
                if record.input_sha256 != input_hash:
                    raise DomainConflict("receipt caller key was replayed with different input")
                return record
            request_row = connection.execute(
                "SELECT request_id,workspace_id,mission_id,schema_version,idempotency_key,status,"
                "payload_sha256,payload_json,created_at,updated_at FROM action_requests "
                "WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if request_row is None:
                raise DomainContractError("action request is unavailable")
            request = self._request_from_row(request_row)
            if request.workspace_id != self.workspace_id:
                raise DomainIsolationError("action request belongs to another workspace")
            receipt_map = {
                record.receipt_id: record
                for record in (
                    self._receipt_from_row(row)
                    for row in connection.execute(
                        "SELECT r.receipt_id,r.request_id,r.schema_version,r.outcome,r.payload_json,"
                        "r.created_at,q.workspace_id FROM action_receipts r JOIN action_requests q "
                        "ON q.request_id=r.request_id WHERE r.request_id=?",
                        (request_id,),
                    ).fetchall()
                )
            }
            chains = self._ordered_events_locked(connection)
            receipts = [
                receipt_map[event.entity_id]
                for event in chains.get(request.correlation_id, ())
                if event.entity_type == "action_receipt"
                and event.parent_entity_id == request_id
                and event.entity_id in receipt_map
            ]
            if len(receipts) != len(receipt_map):
                raise DomainIntegrityError("receipt event order is incomplete")
            if not reconciliation and receipts:
                raise DomainConflict("initial receipt already exists")
            if reconciliation:
                if not receipts or receipts[-1].receipt_id != supersedes_receipt_id:
                    raise DomainConflict("reconciliation must supersede the latest receipt")
                if receipts[-1].outcome not in {"partial", "unknown"}:
                    raise DomainConflict("terminal receipt cannot be reconciled")
            if outcome == "succeeded" and (
                not _material_present(materials["verification"])
                or (
                    not _material_present(materials["after"])
                    and not _material_present(materials["output"])
                )
            ):
                raise DomainContractError(
                    "shadow succeeded requires verification plus after/output observation"
                )
            if outcome == "failed" and (
                not error_class
                or (
                    not _material_present(materials["verification"])
                    and not _material_present(materials["output"])
                )
            ):
                raise DomainContractError(
                    "shadow failed requires error_class plus verification/output evidence"
                )
            created_at = _now()
            payload_text = _canonical(
                {
                    **hashes,
                    "contract": "ActionReceipt.v1",
                    "correlation_id": request.correlation_id,
                    "error_class": error_class,
                    "input_sha256": input_hash,
                    "observed_at": created_at,
                    "reconciliation": reconciliation,
                    "supersedes_receipt_id": supersedes_receipt_id,
                    "workspace_id": self.workspace_id,
                }
            )
            connection.execute(
                "INSERT INTO action_receipts VALUES(?,?,?,?,?,?)",
                (
                    receipt_id,
                    request_id,
                    DOMAIN_CONTRACT_VERSION,
                    outcome,
                    payload_text,
                    created_at,
                ),
            )
            status = (
                "reconciliation_required"
                if outcome in {"partial", "unknown"}
                else "recorded"
            )
            changed = connection.execute(
                "UPDATE action_requests SET status=?,updated_at=? WHERE request_id=? "
                "AND workspace_id=? AND status=?",
                (status, created_at, request_id, self.workspace_id, request.status),
            ).rowcount
            if changed != 1:
                raise DomainConflict("action request shadow status changed concurrently")
            receipt = self._receipt_from_row(
                (
                    receipt_id,
                    request_id,
                    DOMAIN_CONTRACT_VERSION,
                    outcome,
                    payload_text,
                    created_at,
                    self.workspace_id,
                )
            )
            current_request = replace(request, status=status, updated_at=created_at)
            self._append_event_locked(
                connection,
                mission_id=request.mission_id,
                correlation_id=request.correlation_id,
                event_type="action.receipt.recorded",
                entity_type="action_receipt",
                entity_id=receipt_id,
                entity_sha256=_record_digest(receipt),
                parent_entity_id=request_id,
                parent_entity_sha256=_record_digest(current_request),
            )
            self._verify_locked(connection)
            self._before_commit()
            return receipt

    def record_initial_receipt(
        self,
        request_id: str,
        caller_key: str,
        outcome: str,
        **details: bytes | str,
    ) -> ActionReceiptRecord:
        return self._record_receipt(
            request_id,
            caller_key,
            outcome,
            reconciliation=False,
            supersedes_receipt_id=None,
            **details,
        )

    def record_reconciliation_receipt(
        self,
        request_id: str,
        caller_key: str,
        outcome: str,
        supersedes_receipt_id: str,
        **details: bytes | str,
    ) -> ActionReceiptRecord:
        return self._record_receipt(
            request_id,
            caller_key,
            outcome,
            reconciliation=True,
            supersedes_receipt_id=supersedes_receipt_id,
            **details,
        )

    def get_evidence(self, evidence_id: str) -> EvidenceRecord:
        with self._transaction(write=False) as connection:
            self._verify_locked(connection)
            row = connection.execute(
                "SELECT evidence_id,workspace_id,mission_id,schema_version,content_sha256,"
                "payload_json,created_at FROM evidence_records WHERE evidence_id=? "
                "AND workspace_id=?",
                (evidence_id, self.workspace_id),
            ).fetchone()
            if row is None:
                raise DomainIsolationError("evidence is unavailable in this workspace")
            return self._evidence_from_row(row)

    def list_evidence(self, *, mission_id: str | None = None) -> tuple[EvidenceRecord, ...]:
        with self._transaction(write=False) as connection:
            self._verify_locked(connection)
            if mission_id is not None:
                self._validate_mission_locked(connection, mission_id)
                rows = connection.execute(
                    "SELECT evidence_id,workspace_id,mission_id,schema_version,content_sha256,"
                    "payload_json,created_at FROM evidence_records WHERE workspace_id=? "
                    "AND mission_id=? ORDER BY created_at,evidence_id",
                    (self.workspace_id, mission_id),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT evidence_id,workspace_id,mission_id,schema_version,content_sha256,"
                    "payload_json,created_at FROM evidence_records WHERE workspace_id=? "
                    "ORDER BY created_at,evidence_id",
                    (self.workspace_id,),
                ).fetchall()
            return tuple(self._evidence_from_row(row) for row in rows)

    def get_claim(self, claim_id: str) -> ClaimRecord:
        with self._transaction(write=False) as connection:
            self._verify_locked(connection)
            row = connection.execute(
                "SELECT claim_id,workspace_id,schema_version,verification_status,payload_json,"
                "created_at,updated_at FROM claims WHERE claim_id=? AND workspace_id=?",
                (claim_id, self.workspace_id),
            ).fetchone()
            if row is None:
                raise DomainIsolationError("claim is unavailable in this workspace")
            return self._claim_from_row(row)

    def list_claims(self, *, mission_id: str | None = None) -> tuple[ClaimRecord, ...]:
        with self._transaction(write=False) as connection:
            self._verify_locked(connection)
            records = tuple(
                self._claim_from_row(row)
                for row in connection.execute(
                    "SELECT claim_id,workspace_id,schema_version,verification_status,payload_json,"
                    "created_at,updated_at FROM claims WHERE workspace_id=? "
                    "ORDER BY created_at,claim_id",
                    (self.workspace_id,),
                ).fetchall()
            )
            if mission_id is not None:
                self._validate_mission_locked(connection, mission_id)
                records = tuple(item for item in records if item.mission_id == mission_id)
            return records

    def get_action_request(self, request_id: str) -> ActionRequestRecord:
        with self._transaction(write=False) as connection:
            self._verify_locked(connection)
            row = connection.execute(
                "SELECT request_id,workspace_id,mission_id,schema_version,idempotency_key,status,"
                "payload_sha256,payload_json,created_at,updated_at FROM action_requests "
                "WHERE request_id=? AND workspace_id=?",
                (request_id, self.workspace_id),
            ).fetchone()
            if row is None:
                raise DomainIsolationError("action request is unavailable in this workspace")
            return self._request_from_row(row)

    def get_receipt(self, receipt_id: str) -> ActionReceiptRecord:
        with self._transaction(write=False) as connection:
            self._verify_locked(connection)
            row = connection.execute(
                "SELECT r.receipt_id,r.request_id,r.schema_version,r.outcome,r.payload_json,"
                "r.created_at,q.workspace_id FROM action_receipts r JOIN action_requests q "
                "ON q.request_id=r.request_id WHERE r.receipt_id=? AND q.workspace_id=?",
                (receipt_id, self.workspace_id),
            ).fetchone()
            if row is None:
                raise DomainIsolationError("action receipt is unavailable in this workspace")
            return self._receipt_from_row(row)

    def list_receipts(self, request_id: str) -> tuple[ActionReceiptRecord, ...]:
        request = self.get_action_request(request_id)
        with self._transaction(write=False) as connection:
            self._verify_locked(connection)
            records = {
                record.receipt_id: record
                for record in (
                    self._receipt_from_row(row)
                    for row in connection.execute(
                "SELECT r.receipt_id,r.request_id,r.schema_version,r.outcome,r.payload_json,"
                "r.created_at,q.workspace_id FROM action_receipts r JOIN action_requests q "
                        "ON q.request_id=r.request_id WHERE r.request_id=? AND q.workspace_id=?",
                (request.request_id, self.workspace_id),
                    ).fetchall()
                )
            }
            ordered = tuple(
                records[event.entity_id]
                for event in self._ordered_events_locked(connection).get(
                    request.correlation_id, ()
                )
                if event.entity_type == "action_receipt"
                and event.parent_entity_id == request.request_id
                and event.entity_id in records
            )
            if len(ordered) != len(records):
                raise DomainIntegrityError("receipt event order is incomplete")
            return ordered

    def list_events(self, correlation_id: str) -> tuple[EventEnvelope, ...]:
        if not isinstance(correlation_id, str) or not _CORRELATION_ID.fullmatch(correlation_id):
            raise DomainContractError("correlation_id is invalid")
        with self._transaction(write=False) as connection:
            self._verify_locked(connection)
            return self._ordered_events_locked(connection).get(correlation_id, ())


__all__ = [
    "ActionReceiptRecord",
    "ActionRequestRecord",
    "ClaimRecord",
    "DOMAIN_CONTRACT_VERSION",
    "DomainConflict",
    "DomainContractError",
    "DomainIntegrityError",
    "DomainIsolationError",
    "DomainLedgerDisabled",
    "DomainLedgerError",
    "DomainLedgerRepository",
    "EvidenceRecord",
    "EventEnvelope",
    "M2A_DOMAIN_LEDGER_FLAG",
    "m2a_domain_ledger_enabled",
]
