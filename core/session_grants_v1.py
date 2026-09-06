"""Default-off Phase 5.1 session-grant shadow evaluator.

This module is deliberately absent from application startup.  It never grants
authority or suppresses the existing permission callback: it only reports what
a bounded session grant *would* decide.  Grants live only in this process and
are not serialised, so constructing a new store after restart restores none.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass


GRANT_EVALUATOR_FLAG = "ONYX_GRANT_EVALUATOR"
GRANT_SCHEMA_VERSION = 1
GRANT_POLICY_VERSION = "onyx-approval-v1"
MAX_SESSION_LIFETIME_MS = 24 * 60 * 60 * 1000
MAX_TARGETS = 32
MAX_USES = 10_000
MAX_COST_MICRO = 10**15

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}\Z")
_SLUG = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RISKS = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_DATA_CLASSES = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}


class GrantContractError(ValueError):
    """A host-created grant or request violates the v1 contract."""


def grant_evaluator_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Recognise only explicit opt-in values; all other values are off."""
    source = os.environ if environ is None else environ
    return source.get(GRANT_EVALUATOR_FLAG, "").strip().casefold() in {"1", "true"}


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise GrantContractError(f"{field} is invalid")
    return value


def _slug(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SLUG.fullmatch(value):
        raise GrantContractError(f"{field} is invalid")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise GrantContractError(f"{field} must be canonical lowercase SHA-256")
    return value


def _bounded_int(value: object, field: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise GrantContractError(f"{field} is out of bounds")
    return value


def permission_request_digest(action: str, summary: str, details: Mapping | None = None) -> str:
    """Reproduce ``permission_broker.build_request`` without importing runtime code."""
    payload = {
        "action": str(action),
        "summary": str(summary),
        "details": copy.deepcopy(dict(details or {})),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ShadowActionRequest:
    """Host-materialised, content-free view of one exact permission request."""

    principal_id: str
    session_id: str
    workspace_id: str
    mission_id: str | None
    capability: str
    tool: str
    operation: str
    target_sha256: str
    payload_sha256: str
    action_digest: str
    risk: str
    data_class: str
    cost_micro: int
    requested_at_ms: int
    always_explicit: bool = False

    def __post_init__(self) -> None:
        _identifier(self.principal_id, "principal_id")
        _identifier(self.session_id, "session_id")
        _identifier(self.workspace_id, "workspace_id")
        if self.mission_id is not None:
            _identifier(self.mission_id, "mission_id")
        _slug(self.capability, "capability")
        _slug(self.tool, "tool")
        _slug(self.operation, "operation")
        _digest(self.target_sha256, "target_sha256")
        _digest(self.payload_sha256, "payload_sha256")
        _digest(self.action_digest, "action_digest")
        if self.risk not in _RISKS:
            raise GrantContractError("risk is invalid")
        if self.data_class not in _DATA_CLASSES:
            raise GrantContractError("data_class is invalid")
        _bounded_int(self.cost_micro, "cost_micro", minimum=0, maximum=MAX_COST_MICRO)
        _bounded_int(self.requested_at_ms, "requested_at_ms", minimum=0, maximum=2**63 - 1)
        if type(self.always_explicit) is not bool:
            raise GrantContractError("always_explicit must be boolean")


@dataclass(frozen=True, slots=True)
class SessionGrant:
    """Immutable, exact, low/medium-risk grant issued by the trusted host."""

    grant_id: str
    schema_version: int
    policy_version: str
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
    audit_head: str

    def __post_init__(self) -> None:
        _identifier(self.grant_id, "grant_id")
        if self.schema_version != GRANT_SCHEMA_VERSION:
            raise GrantContractError("unknown grant schema version")
        if self.policy_version != GRANT_POLICY_VERSION:
            raise GrantContractError("unknown grant policy version")
        _identifier(self.principal_id, "principal_id")
        _identifier(self.session_id, "session_id")
        _identifier(self.workspace_id, "workspace_id")
        if self.mission_id is not None:
            _identifier(self.mission_id, "mission_id")
        _slug(self.capability, "capability")
        _slug(self.tool, "tool")
        _slug(self.operation, "operation")
        if not isinstance(self.target_sha256, tuple) or not 1 <= len(self.target_sha256) <= MAX_TARGETS:
            raise GrantContractError("target_sha256 must be a finite non-empty tuple")
        if len(set(self.target_sha256)) != len(self.target_sha256):
            raise GrantContractError("target_sha256 contains duplicates")
        for value in self.target_sha256:
            _digest(value, "target_sha256")
        _digest(self.payload_sha256, "payload_sha256")
        _digest(self.action_digest, "action_digest")
        _digest(self.approval_digest, "approval_digest")
        _digest(self.audit_head, "audit_head")
        if self.max_data_class not in _DATA_CLASSES:
            raise GrantContractError("max_data_class is invalid")
        if self.risk_ceiling not in {"low", "medium"}:
            raise GrantContractError("routine session grants may cover only low/medium risk")
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
            raise GrantContractError("aggregate cost cannot be below per-action cost")
        _bounded_int(self.max_uses, "max_uses", minimum=1, maximum=MAX_USES)
        issued = _bounded_int(self.issued_at_ms, "issued_at_ms", minimum=0, maximum=2**63 - 1)
        start = _bounded_int(self.not_before_ms, "not_before_ms", minimum=0, maximum=2**63 - 1)
        expiry = _bounded_int(self.expires_at_ms, "expires_at_ms", minimum=0, maximum=2**63 - 1)
        if not issued <= start < expiry or expiry - issued > MAX_SESSION_LIFETIME_MS:
            raise GrantContractError("grant time window is invalid or exceeds 24 hours")


@dataclass(frozen=True, slots=True)
class GrantRevocation:
    grant_id: str
    reason: str
    revoked_at_ms: int

    def __post_init__(self) -> None:
        _identifier(self.grant_id, "grant_id")
        _slug(self.reason, "reason")
        _bounded_int(self.revoked_at_ms, "revoked_at_ms", minimum=0, maximum=2**63 - 1)


@dataclass(frozen=True, slots=True)
class ShadowGrantDecision:
    outcome: str
    reason: str
    grant_id: str | None
    action_digest: str
    callback_required: bool = True
    authority_granted: bool = False


class SessionGrantStore:
    """Thread-safe process-local store; there is intentionally no persistence API."""

    def __init__(self, session_id: str) -> None:
        self.session_id = _identifier(session_id, "session_id")
        self._grants: dict[str, SessionGrant] = {}
        self._revocations: dict[str, GrantRevocation] = {}
        self._uses: dict[str, int] = {}
        self._costs: dict[str, int] = {}
        self._killed = False
        self._audit_healthy = True
        self._lock = threading.RLock()

    def issue(self, grant: SessionGrant) -> None:
        if grant.session_id != self.session_id:
            raise GrantContractError("grant belongs to another session")
        with self._lock:
            if self._killed or not self._audit_healthy:
                raise GrantContractError("session cannot issue grants")
            if grant.grant_id in self._grants:
                raise GrantContractError("grant_id already exists")
            self._grants[grant.grant_id] = grant
            self._uses[grant.grant_id] = 0
            self._costs[grant.grant_id] = 0

    def revoke(self, grant_id: str, *, reason: str, revoked_at_ms: int) -> None:
        grant_id = _identifier(grant_id, "grant_id")
        revocation = GrantRevocation(grant_id, reason, revoked_at_ms)
        with self._lock:
            if grant_id not in self._grants:
                raise GrantContractError("unknown grant_id")
            self._revocations.setdefault(grant_id, revocation)

    def kill(self, *, at_ms: int) -> None:
        _bounded_int(at_ms, "at_ms", minimum=0, maximum=2**63 - 1)
        with self._lock:
            self._killed = True
            for grant_id in self._grants:
                self._revocations.setdefault(grant_id, GrantRevocation(grant_id, "kill_switch", at_ms))

    def mark_audit_unhealthy(self, *, at_ms: int) -> None:
        _bounded_int(at_ms, "at_ms", minimum=0, maximum=2**63 - 1)
        with self._lock:
            self._audit_healthy = False
            for grant_id in self._grants:
                self._revocations.setdefault(grant_id, GrantRevocation(grant_id, "audit_unhealthy", at_ms))

    def shadow_evaluate(
        self,
        request: ShadowActionRequest,
        *,
        current_policy_version: str,
        current_audit_head: str,
        now_ms: int,
        environ: Mapping[str, str] | None = None,
    ) -> ShadowGrantDecision:
        """Return a non-authoritative shadow outcome; never suppress the callback."""
        _bounded_int(now_ms, "now_ms", minimum=0, maximum=2**63 - 1)
        _digest(current_audit_head, "current_audit_head")
        if not grant_evaluator_enabled(environ):
            return ShadowGrantDecision("disabled", "feature_flag_off", None, request.action_digest)
        if request.always_explicit:
            return ShadowGrantDecision("would_deny", "always_explicit", None, request.action_digest)
        if request.risk in {"high", "critical"}:
            return ShadowGrantDecision("would_deny", "risk_not_grantable", None, request.action_digest)
        with self._lock:
            if self._killed:
                return ShadowGrantDecision("would_deny", "kill_switch", None, request.action_digest)
            if not self._audit_healthy:
                return ShadowGrantDecision("would_deny", "audit_unhealthy", None, request.action_digest)
            matches: list[SessionGrant] = []
            for grant in self._grants.values():
                if self._matches(
                    grant,
                    request,
                    current_policy_version=current_policy_version,
                    current_audit_head=current_audit_head,
                    now_ms=now_ms,
                ):
                    matches.append(grant)
            if len(matches) != 1:
                return ShadowGrantDecision("would_deny", "no_exact_unique_grant", None, request.action_digest)
            grant = matches[0]
            used = self._uses[grant.grant_id]
            spent = self._costs[grant.grant_id]
            if used >= grant.max_uses:
                return ShadowGrantDecision("would_deny", "use_limit", grant.grant_id, request.action_digest)
            if request.cost_micro > grant.max_cost_per_action_micro:
                return ShadowGrantDecision("would_deny", "per_action_cost", grant.grant_id, request.action_digest)
            if spent + request.cost_micro > grant.max_cost_aggregate_micro:
                return ShadowGrantDecision("would_deny", "aggregate_cost", grant.grant_id, request.action_digest)
            self._uses[grant.grant_id] = used + 1
            self._costs[grant.grant_id] = spent + request.cost_micro
            return ShadowGrantDecision("would_allow", "exact_session_grant", grant.grant_id, request.action_digest)

    def _matches(
        self,
        grant: SessionGrant,
        request: ShadowActionRequest,
        *,
        current_policy_version: str,
        current_audit_head: str,
        now_ms: int,
    ) -> bool:
        if grant.grant_id in self._revocations:
            return False
        if not (
            grant.not_before_ms
            <= request.requested_at_ms
            <= now_ms
            < grant.expires_at_ms
        ):
            return False
        if current_policy_version != grant.policy_version:
            return False
        exact_pairs = (
            (grant.principal_id, request.principal_id),
            (grant.session_id, request.session_id),
            (grant.workspace_id, request.workspace_id),
            (grant.mission_id or "", request.mission_id or ""),
            (grant.capability, request.capability),
            (grant.tool, request.tool),
            (grant.operation, request.operation),
            (grant.payload_sha256, request.payload_sha256),
            (grant.action_digest, request.action_digest),
            (grant.audit_head, current_audit_head),
        )
        if not all(hmac.compare_digest(left, right) for left, right in exact_pairs):
            return False
        if not any(hmac.compare_digest(target, request.target_sha256) for target in grant.target_sha256):
            return False
        return (
            _RISKS[request.risk] <= _RISKS[grant.risk_ceiling]
            and _DATA_CLASSES[request.data_class] <= _DATA_CLASSES[grant.max_data_class]
        )


__all__ = [
    "GRANT_EVALUATOR_FLAG",
    "GRANT_POLICY_VERSION",
    "GRANT_SCHEMA_VERSION",
    "GrantContractError",
    "SessionGrant",
    "SessionGrantStore",
    "ShadowActionRequest",
    "ShadowGrantDecision",
    "grant_evaluator_enabled",
    "permission_request_digest",
]
