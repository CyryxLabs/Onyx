"""Phase 5.1 R2: default-off, host-composed session-grant shadow evaluator.

The module is intentionally absent from application startup and has no owner,
provider, UI, mission or persistence wiring.  Its private sentinels establish a
composition boundary for honest in-process API use; they are not cryptographic
secrets and provide no defence against arbitrary code in the same process.
Every result remains advisory: the existing trusted callback is always required
and this module can never grant dispatch authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from memory.store import contains_secret


GRANT_EVALUATOR_FLAG = "ONYX_GRANT_EVALUATOR"
GRANT_SCHEMA_VERSION = 2
GRANT_POLICY_VERSION = "onyx-approval-v2"
MAX_SESSION_LIFETIME_MS = 24 * 60 * 60 * 1000
MAX_TARGETS = 32
MAX_USES = 10_000
MAX_COST_MICRO = 10**15

_HOST_COMPOSITION_SENTINEL = object()
_HOST_RECORD_SENTINEL = object()
_HOST_REQUEST_SENTINEL = object()
_HOST_GRANT_SENTINEL = object()
_STORE_SENTINEL = object()

_SAFE_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_WORKSPACE_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_SLUG = re.compile(r"[a-z][a-z0-9-]{1,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RISKS = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_DATA_CLASSES = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
_OUTCOMES = frozenset({"disabled", "would_allow", "would_deny"})
_DECISION_REASONS = frozenset(
    {
        "aggregate_cost",
        "always_explicit",
        "audit_head_changed",
        "audit_unhealthy",
        "exact_session_grant",
        "expired",
        "feature_flag_off",
        "kill_switch",
        "no_exact_unique_grant",
        "per_action_cost",
        "policy_changed",
        "risk_not_grantable",
        "schema_changed",
        "session_ended",
        "stale_request",
        "use_limit",
    }
)
_REVOCATION_REASONS = frozenset(
    {
        "audit-head-changed",
        "audit-unhealthy",
        "expired",
        "kill-switch",
        "owner-revoke",
        "policy-changed",
        "schema-changed",
        "session-ended",
    }
)


class GrantV2ContractError(ValueError):
    """A proposed v2 host/grant/action record violates the closed contract."""


class GrantV2AuthorityError(PermissionError):
    """A caller attempted to cross the host-composition boundary."""


def grant_evaluator_enabled(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return source.get(GRANT_EVALUATOR_FLAG, "").strip().casefold() in {"1", "true"}


def _secret_free(value: str, label: str) -> str:
    if contains_secret(value):
        raise GrantV2ContractError(f"{label} contains secret-shaped material")
    return value


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise GrantV2ContractError(f"{label} is invalid")
    if value in {".", ".."} or any(marker in value for marker in ("/", "\\", ":", "@", "?", "#", "%")):
        raise GrantV2ContractError(f"{label} must not be path-like or token-like")
    return _secret_free(value, label)


def _workspace_id(value: object) -> str:
    if not isinstance(value, str) or not _WORKSPACE_ID.fullmatch(value):
        raise GrantV2ContractError("workspace_id must match core.workspaces")
    return _secret_free(value, "workspace_id")


def _slug(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SLUG.fullmatch(value):
        raise GrantV2ContractError(f"{label} is invalid")
    return _secret_free(value, label)


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise GrantV2ContractError(f"{label} must be canonical lowercase SHA-256")
    return _secret_free(value, label)


def _enum(value: object, allowed: set[str] | frozenset[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise GrantV2ContractError(f"{label} is invalid")
    return _secret_free(value, label)


def _bounded_int(value: object, label: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise GrantV2ContractError(f"{label} is out of bounds")
    return value


def _canonical(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def permission_request_digest(action: str, summary: str, details: Mapping | None = None) -> str:
    """Exact compatibility algorithm of ``permission_broker.build_request``."""
    payload = {"action": str(action), "summary": str(summary), "details": dict(details or {})}
    return hashlib.sha256(_canonical(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class HostActionPolicy:
    capability: str
    tool: str
    operation: str
    risk: str
    always_explicit: bool
    max_data_class: str

    def __post_init__(self) -> None:
        _slug(self.capability, "capability")
        _slug(self.tool, "tool")
        _slug(self.operation, "operation")
        _enum(self.risk, set(_RISKS), "risk")
        _enum(self.max_data_class, set(_DATA_CLASSES), "max_data_class")
        if type(self.always_explicit) is not bool:
            raise GrantV2ContractError("always_explicit must be boolean")


@dataclass(frozen=True, slots=True)
class ActionMaterial:
    capability: str
    tool: str
    operation: str
    mission_id: str | None
    target_sha256: str
    payload_sha256: str
    data_class: str
    cost_micro: int
    requested_at_ms: int

    def __post_init__(self) -> None:
        _slug(self.capability, "capability")
        _slug(self.tool, "tool")
        _slug(self.operation, "operation")
        if self.mission_id is not None:
            _safe_id(self.mission_id, "mission_id")
        _digest(self.target_sha256, "target_sha256")
        _digest(self.payload_sha256, "payload_sha256")
        _enum(self.data_class, set(_DATA_CLASSES), "data_class")
        _bounded_int(self.cost_micro, "cost_micro", minimum=0, maximum=MAX_COST_MICRO)
        _bounded_int(self.requested_at_ms, "requested_at_ms", minimum=0, maximum=2**63 - 1)


@dataclass(frozen=True, slots=True, init=False)
class TypedActionRequest:
    schema_version: int
    policy_version: str
    authority_id: str
    principal_id: str
    session_id: str
    workspace_id: str
    mission_id: str | None
    capability: str
    tool: str
    operation: str
    target_sha256: str
    payload_sha256: str
    risk: str
    always_explicit: bool
    data_class: str
    cost_micro: int
    requested_at_ms: int
    action_digest: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise GrantV2AuthorityError("typed actions are composed only by the host authority")

    @classmethod
    def _from_host(cls, sentinel: object, **values: object) -> "TypedActionRequest":
        if sentinel is not _HOST_REQUEST_SENTINEL:
            raise GrantV2AuthorityError("typed actions are composed only by the host authority")
        instance = object.__new__(cls)
        for name in cls.__dataclass_fields__:
            object.__setattr__(instance, name, values[name])
        instance._validate()
        return instance

    def _validate(self) -> None:
        if self.schema_version != GRANT_SCHEMA_VERSION:
            raise GrantV2ContractError("typed action schema version is invalid")
        _slug(self.policy_version, "policy_version")
        _digest(self.authority_id, "authority_id")
        _safe_id(self.principal_id, "principal_id")
        _safe_id(self.session_id, "session_id")
        _workspace_id(self.workspace_id)
        if self.mission_id is not None:
            _safe_id(self.mission_id, "mission_id")
        _slug(self.capability, "capability")
        _slug(self.tool, "tool")
        _slug(self.operation, "operation")
        _digest(self.target_sha256, "target_sha256")
        _digest(self.payload_sha256, "payload_sha256")
        _enum(self.risk, set(_RISKS), "risk")
        _enum(self.data_class, set(_DATA_CLASSES), "data_class")
        if type(self.always_explicit) is not bool:
            raise GrantV2ContractError("always_explicit must be boolean")
        _bounded_int(self.cost_micro, "cost_micro", minimum=0, maximum=MAX_COST_MICRO)
        _bounded_int(self.requested_at_ms, "requested_at_ms", minimum=0, maximum=2**63 - 1)
        _digest(self.action_digest, "action_digest")


def _action_payload(request: TypedActionRequest) -> dict[str, object]:
    return {
        "always_explicit": request.always_explicit,
        "authority_id": request.authority_id,
        "capability": request.capability,
        "contract": "TypedActionRequest.v2",
        "cost_micro": request.cost_micro,
        "data_class": request.data_class,
        "mission_id": request.mission_id,
        "operation": request.operation,
        "payload_sha256": request.payload_sha256,
        "policy_version": request.policy_version,
        "principal_id": request.principal_id,
        "requested_at_ms": request.requested_at_ms,
        "risk": request.risk,
        "schema_version": request.schema_version,
        "session_id": request.session_id,
        "target_sha256": request.target_sha256,
        "tool": request.tool,
        "workspace_id": request.workspace_id,
    }


def canonical_action_digest(request: TypedActionRequest) -> str:
    request._validate()
    return _sha(_action_payload(request))


@dataclass(frozen=True, slots=True)
class GrantApprovalSpec:
    approval_id: str
    grant_id: str
    action: ActionMaterial
    target_sha256: tuple[str, ...]
    max_data_class: str
    risk_ceiling: str
    max_cost_per_action_micro: int
    max_cost_aggregate_micro: int
    max_uses: int
    issued_at_ms: int
    not_before_ms: int
    expires_at_ms: int

    def __post_init__(self) -> None:
        _safe_id(self.approval_id, "approval_id")
        _safe_id(self.grant_id, "grant_id")
        if not isinstance(self.action, ActionMaterial):
            raise GrantV2ContractError("action must be ActionMaterial")
        if not isinstance(self.target_sha256, tuple) or not 1 <= len(self.target_sha256) <= MAX_TARGETS:
            raise GrantV2ContractError("target_sha256 must be a finite tuple")
        if len(set(self.target_sha256)) != len(self.target_sha256):
            raise GrantV2ContractError("target_sha256 contains duplicates")
        for target in self.target_sha256:
            _digest(target, "target_sha256")
        _enum(self.max_data_class, set(_DATA_CLASSES), "max_data_class")
        if self.risk_ceiling not in {"low", "medium"}:
            raise GrantV2ContractError("routine grants are limited to low/medium risk")
        _secret_free(self.risk_ceiling, "risk_ceiling")
        per_action = _bounded_int(
            self.max_cost_per_action_micro,
            "max_cost_per_action_micro",
            minimum=0,
            maximum=MAX_COST_MICRO,
        )
        aggregate = _bounded_int(
            self.max_cost_aggregate_micro,
            "max_cost_aggregate_micro",
            minimum=0,
            maximum=MAX_COST_MICRO,
        )
        if aggregate < per_action:
            raise GrantV2ContractError("aggregate cost is below per-action cost")
        _bounded_int(self.max_uses, "max_uses", minimum=1, maximum=MAX_USES)
        issued = _bounded_int(self.issued_at_ms, "issued_at_ms", minimum=0, maximum=2**63 - 1)
        start = _bounded_int(self.not_before_ms, "not_before_ms", minimum=0, maximum=2**63 - 1)
        expiry = _bounded_int(self.expires_at_ms, "expires_at_ms", minimum=0, maximum=2**63 - 1)
        if not issued <= start < expiry or expiry - issued > MAX_SESSION_LIFETIME_MS:
            raise GrantV2ContractError("grant time window is invalid or exceeds 24 hours")


@dataclass(frozen=True, slots=True, init=False)
class SessionGrant:
    grant_id: str
    approval_id: str
    schema_version: int
    policy_version: str
    authority_id: str
    principal_id: str
    session_id: str
    workspace_id: str
    mission_id: str | None
    capability: str
    tool: str
    operation: str
    target_sha256: tuple[str, ...]
    payload_sha256: str
    action_digest: str
    max_data_class: str
    risk_ceiling: str
    max_cost_per_action_micro: int
    max_cost_aggregate_micro: int
    max_uses: int
    issued_at_ms: int
    not_before_ms: int
    expires_at_ms: int
    approval_digest: str
    scope_digest: str
    audit_head: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise GrantV2AuthorityError("session grants are issued only by the host authority")

    @classmethod
    def _from_host(cls, sentinel: object, **values: object) -> "SessionGrant":
        if sentinel is not _HOST_GRANT_SENTINEL:
            raise GrantV2AuthorityError("session grants are issued only by the host authority")
        instance = object.__new__(cls)
        for name in cls.__dataclass_fields__:
            object.__setattr__(instance, name, values[name])
        return instance


@dataclass(frozen=True, slots=True, init=False)
class HostApprovalRecord:
    approval_id: str
    grant: SessionGrant
    record_digest: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise GrantV2AuthorityError("approval records are composed only by the trusted host")

    @classmethod
    def _from_host(
        cls, sentinel: object, approval_id: str, grant: SessionGrant, record_digest: str
    ) -> "HostApprovalRecord":
        if sentinel is not _HOST_RECORD_SENTINEL:
            raise GrantV2AuthorityError("approval records are composed only by the trusted host")
        instance = object.__new__(cls)
        object.__setattr__(instance, "approval_id", approval_id)
        object.__setattr__(instance, "grant", grant)
        object.__setattr__(instance, "record_digest", record_digest)
        return instance


@dataclass(frozen=True, slots=True)
class GrantRevocation:
    grant_id: str
    reason: str
    revoked_at_ms: int

    def __post_init__(self) -> None:
        _safe_id(self.grant_id, "grant_id")
        _enum(self.reason, _REVOCATION_REASONS, "reason")
        _bounded_int(self.revoked_at_ms, "revoked_at_ms", minimum=0, maximum=2**63 - 1)


@dataclass(frozen=True, slots=True)
class ShadowGrantDecision:
    outcome: str
    reason: str
    grant_id: str | None
    action_digest: str
    callback_required: bool = field(init=False, default=True)
    authority_granted: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        _enum(self.outcome, _OUTCOMES, "outcome")
        _enum(self.reason, _DECISION_REASONS, "reason")
        if self.grant_id is not None:
            _safe_id(self.grant_id, "grant_id")
        _digest(self.action_digest, "action_digest")


def _grant_payload(grant: SessionGrant, *, include_proofs: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "approval_id": grant.approval_id,
        "authority_id": grant.authority_id,
        "capability": grant.capability,
        "contract": "SessionGrant.v2",
        "expires_at_ms": grant.expires_at_ms,
        "grant_id": grant.grant_id,
        "issued_at_ms": grant.issued_at_ms,
        "max_cost_aggregate_micro": grant.max_cost_aggregate_micro,
        "max_cost_per_action_micro": grant.max_cost_per_action_micro,
        "max_data_class": grant.max_data_class,
        "max_uses": grant.max_uses,
        "mission_id": grant.mission_id,
        "not_before_ms": grant.not_before_ms,
        "operation": grant.operation,
        "payload_sha256": grant.payload_sha256,
        "policy_version": grant.policy_version,
        "principal_id": grant.principal_id,
        "risk_ceiling": grant.risk_ceiling,
        "schema_version": grant.schema_version,
        "session_id": grant.session_id,
        "target_sha256": list(grant.target_sha256),
        "tool": grant.tool,
        "workspace_id": grant.workspace_id,
        "action_digest": grant.action_digest,
        "audit_head": grant.audit_head,
    }
    if include_proofs:
        payload.update(
            {"approval_digest": grant.approval_digest, "scope_digest": grant.scope_digest}
        )
    return payload


def _approval_record_digest(record: HostApprovalRecord) -> str:
    return _sha(
        {
            "approval_digest": record.grant.approval_digest,
            "approval_id": record.approval_id,
            "contract": "HostApprovalRecord.v2",
            "scope_digest": record.grant.scope_digest,
        }
    )


class TrustedHostGrantAuthority:
    """Host-owned policy/identity/approval composition; not a security sandbox."""

    def __init__(
        self,
        sentinel: object,
        *,
        principal_id: str,
        session_id: str,
        workspace_id: str,
        mission_ids: Sequence[str],
        action_policies: Sequence[HostActionPolicy],
        audit_head: str,
    ) -> None:
        if sentinel is not _HOST_COMPOSITION_SENTINEL:
            raise GrantV2AuthorityError("authority must be composed by the trusted host")
        self._principal_id = _safe_id(principal_id, "principal_id")
        self._session_id = _safe_id(session_id, "session_id")
        self._workspace_id = _workspace_id(workspace_id)
        self._mission_ids = frozenset(_safe_id(value, "mission_id") for value in mission_ids)
        policies: dict[tuple[str, str, str], HostActionPolicy] = {}
        for policy in action_policies:
            if not isinstance(policy, HostActionPolicy):
                raise GrantV2ContractError("action policy is invalid")
            key = (policy.capability, policy.tool, policy.operation)
            if key in policies:
                raise GrantV2ContractError("duplicate host action policy")
            policies[key] = policy
        if not policies:
            raise GrantV2ContractError("at least one host action policy is required")
        self._policies = policies
        self._schema_version = GRANT_SCHEMA_VERSION
        self._policy_version = GRANT_POLICY_VERSION
        self._audit_head = _digest(audit_head, "audit_head")
        identity_payload = {
            "audit_head": self._audit_head,
            "contract": "TrustedHostGrantAuthority.v2",
            "policy_version": self._policy_version,
            "principal_id": self._principal_id,
            "schema_version": self._schema_version,
            "session_id": self._session_id,
            "workspace_id": self._workspace_id,
        }
        self._authority_id = _sha(identity_payload)
        self._approval_records: dict[str, HostApprovalRecord] = {}
        self._consumed_approvals: set[str] = set()
        self._audit_healthy = True
        self._ended = False
        self._store_opened = False
        self._lock = threading.RLock()

    def resolve_action(self, material: ActionMaterial) -> TypedActionRequest:
        if not isinstance(material, ActionMaterial):
            raise GrantV2ContractError("action material is invalid")
        with self._lock:
            if self._ended or not self._audit_healthy:
                raise GrantV2AuthorityError("host session is not healthy")
            if material.mission_id is not None and material.mission_id not in self._mission_ids:
                raise GrantV2ContractError("mission_id is not host-authorized")
            policy = self._policies.get((material.capability, material.tool, material.operation))
            if policy is None:
                raise GrantV2ContractError("unknown host action policy")
            if _DATA_CLASSES[material.data_class] > _DATA_CLASSES[policy.max_data_class]:
                raise GrantV2ContractError("data class exceeds host policy")
            values: dict[str, object] = {
                "schema_version": self._schema_version,
                "policy_version": self._policy_version,
                "authority_id": self._authority_id,
                "principal_id": self._principal_id,
                "session_id": self._session_id,
                "workspace_id": self._workspace_id,
                "mission_id": material.mission_id,
                "capability": material.capability,
                "tool": material.tool,
                "operation": material.operation,
                "target_sha256": material.target_sha256,
                "payload_sha256": material.payload_sha256,
                "risk": policy.risk,
                "always_explicit": policy.always_explicit,
                "data_class": material.data_class,
                "cost_micro": material.cost_micro,
                "requested_at_ms": material.requested_at_ms,
                "action_digest": "0" * 64,
            }
            request = TypedActionRequest._from_host(_HOST_REQUEST_SENTINEL, **values)
            digest = canonical_action_digest(request)
            values["action_digest"] = digest
            return TypedActionRequest._from_host(_HOST_REQUEST_SENTINEL, **values)

    def _grant_and_expected_approval_locked(
        self, spec: GrantApprovalSpec
    ) -> tuple[SessionGrant, str, str]:
        request = self.resolve_action(spec.action)
        if request.always_explicit or request.risk in {"high", "critical"}:
            raise GrantV2ContractError("always-explicit/high-risk action cannot become a grant")
        if _RISKS[spec.risk_ceiling] < _RISKS[request.risk]:
            raise GrantV2ContractError("risk ceiling is below host-resolved action risk")
        if _DATA_CLASSES[spec.max_data_class] < _DATA_CLASSES[request.data_class]:
            raise GrantV2ContractError("data ceiling is below action data class")
        if not any(hmac.compare_digest(item, request.target_sha256) for item in spec.target_sha256):
            raise GrantV2ContractError("approved targets do not contain the exact action target")
        grant_values: dict[str, object] = {
            "grant_id": spec.grant_id,
            "approval_id": spec.approval_id,
            "schema_version": self._schema_version,
            "policy_version": self._policy_version,
            "authority_id": self._authority_id,
            "principal_id": self._principal_id,
            "session_id": self._session_id,
            "workspace_id": self._workspace_id,
            "mission_id": request.mission_id,
            "capability": request.capability,
            "tool": request.tool,
            "operation": request.operation,
            "target_sha256": spec.target_sha256,
            "payload_sha256": request.payload_sha256,
            "action_digest": request.action_digest,
            "max_data_class": spec.max_data_class,
            "risk_ceiling": spec.risk_ceiling,
            "max_cost_per_action_micro": spec.max_cost_per_action_micro,
            "max_cost_aggregate_micro": spec.max_cost_aggregate_micro,
            "max_uses": spec.max_uses,
            "issued_at_ms": spec.issued_at_ms,
            "not_before_ms": spec.not_before_ms,
            "expires_at_ms": spec.expires_at_ms,
            "approval_digest": "0" * 64,
            "scope_digest": "0" * 64,
            "audit_head": self._audit_head,
        }
        draft = SessionGrant._from_host(_HOST_GRANT_SENTINEL, **grant_values)
        scope_digest = _sha(_grant_payload(draft, include_proofs=False))
        _digest(scope_digest, "scope_digest")
        approval_digest = permission_request_digest(
            "grant.session",
            "Approve exact bounded Onyx session grant?",
            {"scope_digest": scope_digest},
        )
        _digest(approval_digest, "approval_digest")
        grant_values.update({"scope_digest": scope_digest, "approval_digest": approval_digest})
        return (
            SessionGrant._from_host(_HOST_GRANT_SENTINEL, **grant_values),
            scope_digest,
            approval_digest,
        )

    def _preview_approval_digest_for_testing(self, spec: GrantApprovalSpec) -> str:
        """Return the exact digest a trusted callback must return; test-only."""
        with self._lock:
            return self._grant_and_expected_approval_locked(spec)[2]

    def _register_approved_spec(
        self, spec: GrantApprovalSpec, *, trusted_callback_digest: str
    ) -> None:
        callback_digest = _digest(trusted_callback_digest, "trusted_callback_digest")
        with self._lock:
            if spec.approval_id in self._approval_records:
                raise GrantV2ContractError("duplicate approval_id")
            grant, _scope_digest, expected_approval = self._grant_and_expected_approval_locked(spec)
            if not hmac.compare_digest(callback_digest, expected_approval):
                raise GrantV2AuthorityError("trusted callback did not approve the exact grant scope")
            provisional = HostApprovalRecord._from_host(
                _HOST_RECORD_SENTINEL, spec.approval_id, grant, "0" * 64
            )
            record_digest = _approval_record_digest(provisional)
            _digest(record_digest, "record_digest")
            record = HostApprovalRecord._from_host(
                _HOST_RECORD_SENTINEL,
                spec.approval_id,
                grant,
                record_digest,
            )
            self._verify_approval_record_locked(record)
            self._approval_records[spec.approval_id] = record

    def _verify_approval_record_locked(self, record: HostApprovalRecord) -> None:
        grant = record.grant
        if record.approval_id != grant.approval_id:
            raise GrantV2AuthorityError("approval identity mismatch")
        expected_scope = _sha(_grant_payload(grant, include_proofs=False))
        expected_approval = permission_request_digest(
            "grant.session",
            "Approve exact bounded Onyx session grant?",
            {"scope_digest": expected_scope},
        )
        expected_record = _approval_record_digest(record)
        if not (
            hmac.compare_digest(expected_scope, grant.scope_digest)
            and hmac.compare_digest(expected_approval, grant.approval_digest)
            and hmac.compare_digest(expected_record, record.record_digest)
            and hmac.compare_digest(grant.authority_id, self._authority_id)
        ):
            raise GrantV2AuthorityError("approval record verification failed")

    def _consume_approval(self, approval_id: str, *, now_ms: int) -> SessionGrant:
        approval_id = _safe_id(approval_id, "approval_id")
        _bounded_int(now_ms, "now_ms", minimum=0, maximum=2**63 - 1)
        with self._lock:
            if self._ended or not self._audit_healthy:
                raise GrantV2AuthorityError("host authority is unavailable")
            record = self._approval_records.get(approval_id)
            if record is None or approval_id in self._consumed_approvals:
                raise GrantV2AuthorityError("unknown or consumed host approval")
            self._verify_approval_record_locked(record)
            grant = record.grant
            if not grant.not_before_ms <= now_ms < grant.expires_at_ms:
                raise GrantV2AuthorityError("host approval is outside its time window")
            self._consumed_approvals.add(approval_id)
            return grant

    def open_session_store(self) -> "SessionGrantStore":
        with self._lock:
            if self._store_opened:
                raise GrantV2AuthorityError("authority already opened its one session store")
            self._store_opened = True
            return SessionGrantStore(_STORE_SENTINEL, self)

    def _state(self) -> tuple[int, str, str, bool, bool]:
        with self._lock:
            return (
                self._schema_version,
                self._policy_version,
                self._audit_head,
                self._audit_healthy,
                self._ended,
            )

    def mark_audit_unhealthy(self) -> None:
        with self._lock:
            self._audit_healthy = False

    def end_session(self) -> None:
        with self._lock:
            self._ended = True

    def _replace_state_for_testing(
        self,
        *,
        schema_version: int | None = None,
        policy_version: str | None = None,
        audit_head: str | None = None,
    ) -> None:
        """Test-only host-state transition; there is no production wiring in R2."""
        with self._lock:
            if schema_version is not None:
                self._schema_version = _bounded_int(
                    schema_version, "schema_version", minimum=1, maximum=2**31 - 1
                )
            if policy_version is not None:
                self._policy_version = _slug(policy_version, "policy_version")
            if audit_head is not None:
                self._audit_head = _digest(audit_head, "audit_head")


def _compose_host_authority_for_testing(
    *,
    principal_id: str,
    session_id: str,
    workspace_id: str,
    mission_ids: Sequence[str],
    action_policies: Sequence[HostActionPolicy],
    audit_head: str,
) -> TrustedHostGrantAuthority:
    """Fixture-only host composition; intentionally omitted from ``__all__``."""
    authority = TrustedHostGrantAuthority(
        _HOST_COMPOSITION_SENTINEL,
        principal_id=principal_id,
        session_id=session_id,
        workspace_id=workspace_id,
        mission_ids=mission_ids,
        action_policies=action_policies,
        audit_head=audit_head,
    )
    return authority


class SessionGrantStore:
    """One authority-bound, process-local store with no persistence API."""

    def __init__(self, sentinel: object, authority: TrustedHostGrantAuthority) -> None:
        if sentinel is not _STORE_SENTINEL or not isinstance(authority, TrustedHostGrantAuthority):
            raise GrantV2AuthorityError("store must be opened by a trusted host authority")
        self._authority = authority
        self._grants: dict[str, SessionGrant] = {}
        self._revocations: dict[str, GrantRevocation] = {}
        self._uses: dict[str, int] = {}
        self._costs: dict[str, int] = {}
        self._killed = False
        self._session_ended = False
        self._lock = threading.RLock()

    def issue_from_host_approval(self, approval_id: str, *, now_ms: int) -> str:
        grant = self._authority._consume_approval(approval_id, now_ms=now_ms)
        with self._lock:
            if self._killed or self._session_ended:
                raise GrantV2AuthorityError("session store is stopped")
            if grant.grant_id in self._grants:
                raise GrantV2ContractError("grant_id already exists")
            self._grants[grant.grant_id] = grant
            self._uses[grant.grant_id] = 0
            self._costs[grant.grant_id] = 0
            return grant.grant_id

    def _revoke_locked(self, grant_id: str, reason: str, at_ms: int) -> None:
        self._revocations.setdefault(grant_id, GrantRevocation(grant_id, reason, at_ms))

    def revoke(self, grant_id: str, *, at_ms: int) -> None:
        grant_id = _safe_id(grant_id, "grant_id")
        _bounded_int(at_ms, "at_ms", minimum=0, maximum=2**63 - 1)
        with self._lock:
            if grant_id not in self._grants:
                raise GrantV2ContractError("unknown grant_id")
            self._revoke_locked(grant_id, "owner-revoke", at_ms)

    def kill(self, *, at_ms: int) -> None:
        _bounded_int(at_ms, "at_ms", minimum=0, maximum=2**63 - 1)
        with self._lock:
            self._killed = True
            for grant_id in self._grants:
                self._revoke_locked(grant_id, "kill-switch", at_ms)

    def mark_audit_unhealthy(self, *, at_ms: int) -> None:
        _bounded_int(at_ms, "at_ms", minimum=0, maximum=2**63 - 1)
        self._authority.mark_audit_unhealthy()
        with self._lock:
            for grant_id in self._grants:
                self._revoke_locked(grant_id, "audit-unhealthy", at_ms)

    def end_session(self, *, at_ms: int) -> None:
        _bounded_int(at_ms, "at_ms", minimum=0, maximum=2**63 - 1)
        self._authority.end_session()
        with self._lock:
            self._session_ended = True
            for grant_id in self._grants:
                self._revoke_locked(grant_id, "session-ended", at_ms)

    def shadow_evaluate(
        self,
        request: TypedActionRequest,
        *,
        now_ms: int,
        environ: Mapping[str, str] | None = None,
    ) -> ShadowGrantDecision:
        if not isinstance(request, TypedActionRequest):
            raise GrantV2ContractError("request must be host-composed TypedActionRequest")
        _bounded_int(now_ms, "now_ms", minimum=0, maximum=2**63 - 1)
        recomputed = canonical_action_digest(request)
        if not hmac.compare_digest(recomputed, request.action_digest):
            raise GrantV2ContractError("typed action digest is invalid")
        if not grant_evaluator_enabled(environ):
            return ShadowGrantDecision("disabled", "feature_flag_off", None, recomputed)
        if request.always_explicit:
            return ShadowGrantDecision("would_deny", "always_explicit", None, recomputed)
        if request.risk in {"high", "critical"}:
            return ShadowGrantDecision("would_deny", "risk_not_grantable", None, recomputed)
        with self._lock:
            schema, policy, audit_head, audit_healthy, authority_ended = self._authority._state()
            if self._killed:
                return ShadowGrantDecision("would_deny", "kill_switch", None, recomputed)
            if self._session_ended or authority_ended:
                return ShadowGrantDecision("would_deny", "session_ended", None, recomputed)
            if not audit_healthy:
                for grant_id in self._grants:
                    self._revoke_locked(grant_id, "audit-unhealthy", now_ms)
                return ShadowGrantDecision("would_deny", "audit_unhealthy", None, recomputed)
            matches: list[SessionGrant] = []
            terminal_reason: str | None = None
            for grant in self._grants.values():
                if grant.grant_id in self._revocations:
                    continue
                if grant.schema_version != schema:
                    self._revoke_locked(grant.grant_id, "schema-changed", now_ms)
                    terminal_reason = "schema_changed"
                    continue
                if grant.policy_version != policy:
                    self._revoke_locked(grant.grant_id, "policy-changed", now_ms)
                    terminal_reason = "policy_changed"
                    continue
                if not hmac.compare_digest(grant.audit_head, audit_head):
                    self._revoke_locked(grant.grant_id, "audit-head-changed", now_ms)
                    terminal_reason = "audit_head_changed"
                    continue
                if now_ms >= grant.expires_at_ms:
                    self._revoke_locked(grant.grant_id, "expired", now_ms)
                    terminal_reason = "expired"
                    continue
                if self._matches(grant, request, now_ms=now_ms):
                    matches.append(grant)
            if len(matches) != 1:
                return ShadowGrantDecision(
                    "would_deny", terminal_reason or "no_exact_unique_grant", None, recomputed
                )
            grant = matches[0]
            used = self._uses[grant.grant_id]
            spent = self._costs[grant.grant_id]
            if used >= grant.max_uses:
                return ShadowGrantDecision("would_deny", "use_limit", grant.grant_id, recomputed)
            if request.cost_micro > grant.max_cost_per_action_micro:
                return ShadowGrantDecision(
                    "would_deny", "per_action_cost", grant.grant_id, recomputed
                )
            if spent + request.cost_micro > grant.max_cost_aggregate_micro:
                return ShadowGrantDecision(
                    "would_deny", "aggregate_cost", grant.grant_id, recomputed
                )
            self._uses[grant.grant_id] = used + 1
            self._costs[grant.grant_id] = spent + request.cost_micro
            return ShadowGrantDecision(
                "would_allow", "exact_session_grant", grant.grant_id, recomputed
            )

    def _matches(self, grant: SessionGrant, request: TypedActionRequest, *, now_ms: int) -> bool:
        if not grant.not_before_ms <= request.requested_at_ms <= now_ms < grant.expires_at_ms:
            return False
        exact = (
            (grant.authority_id, request.authority_id),
            (grant.principal_id, request.principal_id),
            (grant.session_id, request.session_id),
            (grant.workspace_id, request.workspace_id),
            (grant.mission_id or "", request.mission_id or ""),
            (grant.capability, request.capability),
            (grant.tool, request.tool),
            (grant.operation, request.operation),
            (grant.payload_sha256, request.payload_sha256),
            (grant.action_digest, request.action_digest),
        )
        if not all(hmac.compare_digest(left, right) for left, right in exact):
            return False
        if not any(hmac.compare_digest(item, request.target_sha256) for item in grant.target_sha256):
            return False
        return (
            _RISKS[request.risk] <= _RISKS[grant.risk_ceiling]
            and _DATA_CLASSES[request.data_class] <= _DATA_CLASSES[grant.max_data_class]
        )


__all__ = [
    "GRANT_EVALUATOR_FLAG",
    "GRANT_POLICY_VERSION",
    "GRANT_SCHEMA_VERSION",
    "ActionMaterial",
    "GrantApprovalSpec",
    "GrantV2AuthorityError",
    "GrantV2ContractError",
    "HostActionPolicy",
    "SessionGrantStore",
    "ShadowGrantDecision",
    "TrustedHostGrantAuthority",
    "TypedActionRequest",
    "canonical_action_digest",
    "grant_evaluator_enabled",
    "permission_request_digest",
]
