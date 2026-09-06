"""Phase 5.1 R3: pinned-host, default-off session-grant shadow evaluation.

Callers submit only opaque invocation references.  An instance is permanently
bound to host-owned resolver, policy-state, approval and monotonic-clock
services supplied at construction.  A caller can construct a separate shadow
instance with different callbacks, but cannot use those callbacks to approve or
mutate an existing instance.  Python reflection/arbitrary same-process code is
explicitly outside this API boundary; this module does not claim cryptographic
or process isolation.

There is no startup/UI/provider/owner-data wiring and no persistence.  Every
decision remains advisory with the trusted callback still required.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import posixpath
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from memory.store import contains_secret


GRANT_EVALUATOR_FLAG = "ONYX_GRANT_EVALUATOR"
GRANT_SCHEMA_VERSION = 3
GRANT_POLICY_VERSION = "onyx-approval-v3"
MAX_SESSION_LIFETIME_MS = 86_400_000
MAX_TARGETS = 32
MAX_USES = 10_000
MAX_COST_MICRO = 1_000_000_000_000_000
MAX_POLICIES = 128
MAX_MISSIONS = 128
MAX_GRANTS = 128
MAX_APPROVALS = 128
MAX_REVOCATIONS = 128
MAX_TARGET_LENGTH = 512
MAX_EFFECT_LENGTH = 256

_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_WORKSPACE_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_SLUG = re.compile(r"[a-z][a-z0-9-]{1,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_URI_SCHEME = re.compile(r"[a-z][a-z0-9+.-]{1,15}\Z")
_TOKEN_LIKE = re.compile(r"[A-Za-z0-9]{32,}\Z")
_HEX_LIKE = re.compile(r"[0-9a-fA-F]{16,}\Z")
_RISKS = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_DATA_CLASSES = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
_DECISION_REASONS = frozenset(
    {
        "aggregate-cost",
        "ambiguous-grant",
        "audit-unhealthy",
        "exact-session-grant",
        "feature-flag-off",
        "kill-switch",
        "no-exact-grant",
        "out-of-scope",
        "per-action-cost",
        "session-ended",
    }
)
_REVOCATION_REASONS = frozenset(
    {
        "aggregate-exhausted",
        "audit-head-changed",
        "audit-unhealthy",
        "expired",
        "identity-changed",
        "kill-switch",
        "owner-revoke",
        "policy-changed",
        "schema-changed",
        "session-ended",
        "use-exhausted",
    }
)


class GrantV3Error(RuntimeError):
    pass


class GrantV3ContractError(ValueError):
    pass


class GrantV3Disabled(GrantV3Error):
    pass


class GrantV3Denied(GrantV3Error):
    pass


class GrantV3CapacityError(GrantV3Error):
    pass


def grant_evaluator_enabled(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return source.get(GRANT_EVALUATOR_FLAG, "").strip().casefold() in {"1", "true"}


def _secret_free(value: str, label: str) -> str:
    if contains_secret(value):
        raise GrantV3ContractError(f"{label} contains secret-shaped material")
    return value


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise GrantV3ContractError(f"{label} is invalid")
    if len(value) >= 32 or _TOKEN_LIKE.fullmatch(value) or _HEX_LIKE.fullmatch(value):
        raise GrantV3ContractError(f"{label} is token-like")
    return _secret_free(value, label)


def _workspace_id(value: object) -> str:
    if not isinstance(value, str) or not _WORKSPACE_ID.fullmatch(value):
        raise GrantV3ContractError("workspace_id must match core.workspaces")
    if len(value) >= 32 or _TOKEN_LIKE.fullmatch(value) or _HEX_LIKE.fullmatch(value):
        raise GrantV3ContractError("workspace_id is token-like")
    return _secret_free(value, "workspace_id")


def _slug(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SLUG.fullmatch(value):
        raise GrantV3ContractError(f"{label} is invalid")
    if len(value) >= 32 or _TOKEN_LIKE.fullmatch(value) or _HEX_LIKE.fullmatch(value):
        raise GrantV3ContractError(f"{label} is token-like")
    return _secret_free(value, label)


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise GrantV3ContractError(f"{label} must be lowercase SHA-256")
    return _secret_free(value, label)


def _enum(value: object, allowed: set[str] | frozenset[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise GrantV3ContractError(f"{label} is invalid")
    return _secret_free(value, label)


def _bounded_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise GrantV3ContractError(f"{label} is out of bounds")
    return value


def _bounded_text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise GrantV3ContractError(f"{label} is invalid")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        raise GrantV3ContractError(f"{label} is invalid")
    return _secret_free(normalized, label)


def _canonical(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _normalize_target(value: object, label: str = "target") -> str:
    if not isinstance(value, str):
        raise GrantV3ContractError(f"{label} is invalid")
    raw = value.strip()
    if not raw or len(raw) > MAX_TARGET_LENGTH or any(ord(char) < 32 for char in raw):
        raise GrantV3ContractError(f"{label} is invalid")
    _secret_free(raw, label)
    windows = PureWindowsPath(raw)
    posix = PurePosixPath(raw)
    if windows.is_absolute():
        normalized = str(windows).replace("\\", "/")
        if len(normalized) >= 2 and normalized[1] == ":":
            normalized = normalized[0].casefold() + normalized[1:]
        return _secret_free(normalized, label)
    if posix.is_absolute():
        normalized = posixpath.normpath(raw)
        return _secret_free(normalized, label)
    parsed = urlsplit(raw)
    if parsed.scheme:
        scheme = parsed.scheme.casefold()
        if not _URI_SCHEME.fullmatch(scheme) or parsed.username or parsed.password:
            raise GrantV3ContractError(f"{label} URI is invalid")
        if parsed.query or parsed.fragment:
            raise GrantV3ContractError(f"{label} URI query/fragment is forbidden")
        host = (parsed.hostname or "").casefold()
        if scheme in {"http", "https"} and not host:
            raise GrantV3ContractError(f"{label} URI host is required")
        port = parsed.port
        netloc = host
        if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
            netloc = f"{host}:{port}"
        decoded_path = unquote(parsed.path or "/")
        normalized_path = posixpath.normpath(decoded_path)
        if decoded_path.endswith("/") and normalized_path != "/":
            normalized_path += "/"
        if not normalized_path.startswith("/"):
            normalized_path = "/" + normalized_path
        normalized = urlunsplit((scheme, netloc, quote(normalized_path, safe="/-._~"), "", ""))
        return _secret_free(normalized, label)
    if "/" in raw or "\\" in raw or raw in {".", ".."}:
        raise GrantV3ContractError(f"{label} relative path is forbidden")
    return _safe_id(raw, label)


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
            raise GrantV3ContractError("always_explicit must be boolean")

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.capability, self.tool, self.operation)


@dataclass(frozen=True, slots=True)
class HostState:
    schema_version: int
    policy_version: str
    principal_id: str
    session_id: str
    workspace_id: str
    mission_ids: tuple[str, ...]
    policies: tuple[HostActionPolicy, ...]
    audit_head: str
    audit_healthy: bool = True
    session_active: bool = True
    kill_switch: bool = False

    def __post_init__(self) -> None:
        _bounded_int(self.schema_version, "schema_version", 1, 2**31 - 1)
        _slug(self.policy_version, "policy_version")
        _safe_id(self.principal_id, "principal_id")
        _safe_id(self.session_id, "session_id")
        _workspace_id(self.workspace_id)
        if not isinstance(self.mission_ids, tuple) or len(self.mission_ids) > MAX_MISSIONS:
            raise GrantV3ContractError("mission collection exceeds its bound")
        missions = tuple(sorted(_safe_id(item, "mission_id") for item in self.mission_ids))
        if len(set(missions)) != len(missions):
            raise GrantV3ContractError("mission IDs are duplicated")
        object.__setattr__(self, "mission_ids", missions)
        if not isinstance(self.policies, tuple) or not 1 <= len(self.policies) <= MAX_POLICIES:
            raise GrantV3ContractError("policy collection exceeds its bound")
        if any(not isinstance(item, HostActionPolicy) for item in self.policies):
            raise GrantV3ContractError("host policy is invalid")
        policies = tuple(sorted(self.policies, key=lambda item: item.key))
        if len({item.key for item in policies}) != len(policies):
            raise GrantV3ContractError("host policies are duplicated")
        object.__setattr__(self, "policies", policies)
        _digest(self.audit_head, "audit_head")
        for name in ("audit_healthy", "session_active", "kill_switch"):
            if type(getattr(self, name)) is not bool:
                raise GrantV3ContractError(f"{name} must be boolean")

    def policy_for(self, capability: str, tool: str, operation: str) -> HostActionPolicy:
        key = (capability, tool, operation)
        matches = tuple(policy for policy in self.policies if policy.key == key)
        if len(matches) != 1:
            raise GrantV3ContractError("unknown or ambiguous host action policy")
        return matches[0]


@dataclass(frozen=True, slots=True)
class ResolvedGrantScope:
    mission_id: str | None
    capability: str
    tool: str
    operation: str
    targets: tuple[str, ...]
    account: str
    path: str
    effect: str
    environment: str
    data_class: str
    initial_target: str
    initial_cost_micro: int
    max_cost_per_action_micro: int
    max_cost_aggregate_micro: int
    max_uses: int
    not_before_delay_ms: int
    lifetime_ms: int

    def __post_init__(self) -> None:
        if self.mission_id is not None:
            _safe_id(self.mission_id, "mission_id")
        _slug(self.capability, "capability")
        _slug(self.tool, "tool")
        _slug(self.operation, "operation")
        if not isinstance(self.targets, tuple) or not 1 <= len(self.targets) <= MAX_TARGETS:
            raise GrantV3ContractError("target collection exceeds its bound")
        targets = tuple(sorted(_normalize_target(item) for item in self.targets))
        if len(set(targets)) != len(targets):
            raise GrantV3ContractError("targets are duplicate or noncanonical")
        object.__setattr__(self, "targets", targets)
        object.__setattr__(self, "account", _normalize_target(self.account, "account"))
        object.__setattr__(self, "path", _normalize_target(self.path, "path"))
        object.__setattr__(self, "effect", _bounded_text(self.effect, "effect", MAX_EFFECT_LENGTH))
        _safe_id(self.environment, "environment")
        _enum(self.data_class, set(_DATA_CLASSES), "data_class")
        initial_target = _normalize_target(self.initial_target, "initial_target")
        object.__setattr__(self, "initial_target", initial_target)
        if initial_target not in targets:
            raise GrantV3ContractError("initial target is outside the finite target set")
        initial = _bounded_int(self.initial_cost_micro, "initial_cost_micro", 0, MAX_COST_MICRO)
        per_action = _bounded_int(
            self.max_cost_per_action_micro, "max_cost_per_action_micro", 0, MAX_COST_MICRO
        )
        aggregate = _bounded_int(
            self.max_cost_aggregate_micro, "max_cost_aggregate_micro", 0, MAX_COST_MICRO
        )
        if aggregate < per_action or initial > per_action or initial > aggregate:
            raise GrantV3ContractError("cost bounds are contradictory")
        _bounded_int(self.max_uses, "max_uses", 1, MAX_USES)
        delay = _bounded_int(
            self.not_before_delay_ms, "not_before_delay_ms", 0, MAX_SESSION_LIFETIME_MS - 1
        )
        lifetime = _bounded_int(self.lifetime_ms, "lifetime_ms", 1, MAX_SESSION_LIFETIME_MS)
        if delay >= lifetime:
            raise GrantV3ContractError("grant time bounds are contradictory")


@dataclass(frozen=True, slots=True)
class ResolvedAction:
    mission_id: str | None
    capability: str
    tool: str
    operation: str
    target: str
    account: str
    path: str
    effect: str
    environment: str
    data_class: str
    cost_micro: int

    def __post_init__(self) -> None:
        if self.mission_id is not None:
            _safe_id(self.mission_id, "mission_id")
        _slug(self.capability, "capability")
        _slug(self.tool, "tool")
        _slug(self.operation, "operation")
        object.__setattr__(self, "target", _normalize_target(self.target))
        object.__setattr__(self, "account", _normalize_target(self.account, "account"))
        object.__setattr__(self, "path", _normalize_target(self.path, "path"))
        object.__setattr__(self, "effect", _bounded_text(self.effect, "effect", MAX_EFFECT_LENGTH))
        _safe_id(self.environment, "environment")
        _enum(self.data_class, set(_DATA_CLASSES), "data_class")
        _bounded_int(self.cost_micro, "cost_micro", 0, MAX_COST_MICRO)


@dataclass(frozen=True, slots=True)
class HostApprovalResponse:
    approved: bool
    attestation_id: str
    attestation_sequence: int

    def __post_init__(self) -> None:
        if type(self.approved) is not bool:
            raise GrantV3ContractError("approval decision must be boolean")
        _safe_id(self.attestation_id, "attestation_id")
        _bounded_int(self.attestation_sequence, "attestation_sequence", 1, 2**63 - 1)


@dataclass(frozen=True, slots=True)
class HostServices:
    trust_root_id: str
    resolve_grant: Callable[[str], ResolvedGrantScope]
    resolve_action: Callable[[str], ResolvedAction]
    approve: Callable[["ApprovalPrompt"], HostApprovalResponse]
    state: Callable[[], HostState]
    monotonic_ms: Callable[[], int]

    def __post_init__(self) -> None:
        _safe_id(self.trust_root_id, "trust_root_id")
        for name in ("resolve_grant", "resolve_action", "approve", "state", "monotonic_ms"):
            if not callable(getattr(self, name)):
                raise GrantV3ContractError(f"host service {name} is not callable")


@dataclass(frozen=True, slots=True)
class GrantScope:
    schema_version: int
    policy_version: str
    trust_root_id: str
    principal_id: str
    session_id: str
    workspace_id: str
    mission_id: str | None
    capability: str
    tool: str
    operation: str
    targets: tuple[str, ...]
    account: str
    path: str
    effect: str
    environment: str
    data_class: str
    risk: str
    initial_target: str
    initial_cost_micro: int
    max_cost_per_action_micro: int
    max_cost_aggregate_micro: int
    max_uses: int
    issued_at_ms: int
    not_before_ms: int
    expires_at_ms: int


def _scope_payload(scope: GrantScope) -> dict[str, object]:
    return {
        "account": scope.account,
        "capability": scope.capability,
        "contract": "SessionGrantScope.v3",
        "data_class": scope.data_class,
        "effect": scope.effect,
        "environment": scope.environment,
        "expires_at_ms": scope.expires_at_ms,
        "issued_at_ms": scope.issued_at_ms,
        "initial_cost_micro": scope.initial_cost_micro,
        "initial_target": scope.initial_target,
        "max_cost_aggregate_micro": scope.max_cost_aggregate_micro,
        "max_cost_per_action_micro": scope.max_cost_per_action_micro,
        "max_uses": scope.max_uses,
        "mission_id": scope.mission_id,
        "not_before_ms": scope.not_before_ms,
        "operation": scope.operation,
        "path": scope.path,
        "policy_version": scope.policy_version,
        "principal_id": scope.principal_id,
        "risk": scope.risk,
        "schema_version": scope.schema_version,
        "session_id": scope.session_id,
        "targets": list(scope.targets),
        "tool": scope.tool,
        "trust_root_id": scope.trust_root_id,
        "workspace_id": scope.workspace_id,
    }


def canonical_scope_digest(scope: GrantScope) -> str:
    return _sha(_scope_payload(scope))


@dataclass(frozen=True, slots=True)
class ApprovalPrompt:
    scope: GrantScope
    scope_digest: str
    human_summary: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, GrantScope):
            raise GrantV3ContractError("approval scope is invalid")
        _digest(self.scope_digest, "scope_digest")
        if not hmac.compare_digest(self.scope_digest, canonical_scope_digest(self.scope)):
            raise GrantV3ContractError("approval scope digest is invalid")
        _bounded_text(self.human_summary, "human_summary", 2_000)


@dataclass(frozen=True, slots=True)
class SessionGrant:
    grant_id: str
    approval_id: str
    approval_sequence: int
    attestation_digest: str
    scope: GrantScope
    scope_digest: str
    sequence: int


@dataclass(frozen=True, slots=True)
class GrantRevocation:
    grant_id: str
    reason: str
    revoked_at_ms: int
    sequence: int

    def __post_init__(self) -> None:
        _safe_id(self.grant_id, "grant_id")
        _enum(self.reason, _REVOCATION_REASONS, "reason")
        _bounded_int(self.revoked_at_ms, "revoked_at_ms", 0, 2**63 - 1)
        _bounded_int(self.sequence, "sequence", 1, 2**63 - 1)


@dataclass(frozen=True, slots=True)
class ShadowGrantDecision:
    outcome: str
    reason: str
    grant_id: str | None
    scope_digest: str
    action_audit_digest: str
    callback_required: bool = field(init=False, default=True)
    authority_granted: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        _enum(self.outcome, {"disabled", "would-allow", "would-deny"}, "outcome")
        _enum(self.reason, _DECISION_REASONS, "reason")
        if self.grant_id is not None:
            _safe_id(self.grant_id, "grant_id")
        _digest(self.scope_digest, "scope_digest")
        _digest(self.action_audit_digest, "action_audit_digest")


class SessionGrantShadowStore:
    """One session-only shadow store pinned to immutable host service objects."""

    def __init__(self, services: HostServices) -> None:
        if not isinstance(services, HostServices):
            raise GrantV3ContractError("HostServices is required")
        self._services = services
        self._grants: dict[str, SessionGrant] = {}
        self._approvals: dict[str, str] = {}
        self._revocations: dict[str, GrantRevocation] = {}
        self._uses: dict[str, int] = {}
        self._costs: dict[str, int] = {}
        self._sequence = 0
        self._action_sequence = 0
        self._last_attestation_sequence = 0
        self._clock_high_water = 0
        self._killed = False
        self._audit_unhealthy = False
        self._session_ended = False
        self._fail_closed = False
        self._lock = threading.RLock()

    def _now_locked(self) -> int:
        raw = self._services.monotonic_ms()
        now = _bounded_int(raw, "monotonic_ms", 0, 2**63 - 1)
        if now < self._clock_high_water:
            return self._clock_high_water
        self._clock_high_water = now
        return now

    def _state_locked(self) -> HostState:
        state = self._services.state()
        if not isinstance(state, HostState):
            raise GrantV3ContractError("host state service returned an invalid value")
        state.__post_init__()
        return state

    @staticmethod
    def _policy(state: HostState, capability: str, tool: str, operation: str) -> HostActionPolicy:
        return state.policy_for(capability, tool, operation)

    def _revoke_locked(self, grant_id: str, reason: str, now: int) -> None:
        if grant_id in self._revocations:
            return
        if len(self._revocations) >= MAX_REVOCATIONS:
            self._fail_closed = True
            return
        self._sequence += 1
        self._revocations[grant_id] = GrantRevocation(grant_id, reason, now, self._sequence)

    def _invalidate_locked(self, state: HostState, now: int) -> None:
        if self._fail_closed:
            return
        if self._killed or state.kill_switch:
            self._killed = True
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "kill-switch", now)
            return
        if self._audit_unhealthy or not state.audit_healthy:
            self._audit_unhealthy = True
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "audit-unhealthy", now)
            return
        if self._session_ended or not state.session_active:
            self._session_ended = True
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "session-ended", now)
            return
        for grant in tuple(self._grants.values()):
            if grant.grant_id in self._revocations:
                continue
            scope = grant.scope
            if now >= scope.expires_at_ms:
                self._revoke_locked(grant.grant_id, "expired", now)
            elif scope.schema_version != state.schema_version:
                self._revoke_locked(grant.grant_id, "schema-changed", now)
            elif scope.policy_version != state.policy_version:
                self._revoke_locked(grant.grant_id, "policy-changed", now)
            elif not hmac.compare_digest(grant.attestation_digest, self._attestation_digest(grant)):
                self._revoke_locked(grant.grant_id, "policy-changed", now)
            elif not hmac.compare_digest(scope.principal_id, state.principal_id) or not hmac.compare_digest(
                scope.session_id, state.session_id
            ) or not hmac.compare_digest(scope.workspace_id, state.workspace_id):
                self._revoke_locked(grant.grant_id, "identity-changed", now)
            elif not hmac.compare_digest(self._approvals[grant.approval_id], state.audit_head):
                self._revoke_locked(grant.grant_id, "audit-head-changed", now)

    def _cleanup_for_capacity_locked(self) -> None:
        while len(self._grants) >= MAX_GRANTS:
            terminal = sorted(
                (
                    (self._revocations[grant_id].sequence, grant.sequence, grant_id)
                    for grant_id, grant in self._grants.items()
                    if grant_id in self._revocations
                )
            )
            if not terminal:
                raise GrantV3CapacityError("active grant capacity is exhausted")
            _rev_seq, _grant_seq, grant_id = terminal[0]
            grant = self._grants.pop(grant_id)
            self._revocations.pop(grant_id, None)
            self._uses.pop(grant_id, None)
            self._costs.pop(grant_id, None)
            self._approvals.pop(grant.approval_id, None)
        if len(self._approvals) >= MAX_APPROVALS:
            raise GrantV3CapacityError("approval capacity is exhausted")

    def _stop_reason_locked(self) -> str | None:
        if self._fail_closed or self._audit_unhealthy:
            return "audit-unhealthy"
        if self._killed:
            return "kill-switch"
        if self._session_ended:
            return "session-ended"
        return None

    def _scope_from_resolved(self, resolved: ResolvedGrantScope, state: HostState, now: int) -> GrantScope:
        if not isinstance(resolved, ResolvedGrantScope):
            raise GrantV3ContractError("grant resolver returned an invalid value")
        resolved.__post_init__()
        if resolved.mission_id is not None and resolved.mission_id not in state.mission_ids:
            raise GrantV3ContractError("grant mission is not host-authorized")
        policy = self._policy(state, resolved.capability, resolved.tool, resolved.operation)
        if policy.always_explicit or policy.risk in {"high", "critical"}:
            raise GrantV3Denied("always-explicit/high-risk action cannot be granted")
        if _DATA_CLASSES[resolved.data_class] > _DATA_CLASSES[policy.max_data_class]:
            raise GrantV3ContractError("grant data class exceeds host policy")
        return GrantScope(
            schema_version=state.schema_version,
            policy_version=state.policy_version,
            trust_root_id=self._services.trust_root_id,
            principal_id=state.principal_id,
            session_id=state.session_id,
            workspace_id=state.workspace_id,
            mission_id=resolved.mission_id,
            capability=resolved.capability,
            tool=resolved.tool,
            operation=resolved.operation,
            targets=resolved.targets,
            account=resolved.account,
            path=resolved.path,
            effect=resolved.effect,
            environment=resolved.environment,
            data_class=resolved.data_class,
            risk=policy.risk,
            initial_target=resolved.initial_target,
            initial_cost_micro=resolved.initial_cost_micro,
            max_cost_per_action_micro=resolved.max_cost_per_action_micro,
            max_cost_aggregate_micro=resolved.max_cost_aggregate_micro,
            max_uses=resolved.max_uses,
            issued_at_ms=now,
            not_before_ms=now + resolved.not_before_delay_ms,
            expires_at_ms=now + resolved.lifetime_ms,
        )

    @staticmethod
    def _human_summary(scope: GrantScope) -> str:
        targets = ", ".join(scope.targets)
        return (
            f"Principal {scope.principal_id} in session {scope.session_id}, workspace "
            f"{scope.workspace_id}, mission {scope.mission_id or 'none'} requests "
            f"{scope.capability}/{scope.tool}/{scope.operation}; targets [{targets}]; "
            f"account {scope.account}; path {scope.path}; environment {scope.environment}; "
            f"effect {scope.effect}; data {scope.data_class}; risk {scope.risk}; "
            f"initial target {scope.initial_target}; initial cost {scope.initial_cost_micro}; "
            f"per-action cost {scope.max_cost_per_action_micro}; aggregate cost "
            f"{scope.max_cost_aggregate_micro}; uses {scope.max_uses}; valid from "
            f"{scope.not_before_ms} through {scope.expires_at_ms}."
        )

    def request_session_grant(self, invocation_ref: str) -> str:
        reference = _safe_id(invocation_ref, "invocation_ref")
        if not grant_evaluator_enabled():
            raise GrantV3Disabled("grant evaluator is disabled")
        with self._lock:
            preflight_now = self._now_locked()
            preflight_state = self._state_locked()
            self._invalidate_locked(preflight_state, preflight_now)
            if self._stop_reason_locked() is not None:
                raise GrantV3Denied("host session is not healthy")
        resolved = self._services.resolve_grant(reference)
        if not isinstance(resolved, ResolvedGrantScope):
            raise GrantV3ContractError("grant resolver returned an invalid value")
        with self._lock:
            now = self._now_locked()
            state = self._state_locked()
            self._invalidate_locked(state, now)
            if self._stop_reason_locked() is not None:
                raise GrantV3Denied("host session is not healthy")
            self._cleanup_for_capacity_locked()
            scope = self._scope_from_resolved(resolved, state, now)
            scope_digest = canonical_scope_digest(scope)
            prompt = ApprovalPrompt(scope, scope_digest, self._human_summary(scope))
        response = self._services.approve(prompt)
        if not isinstance(response, HostApprovalResponse):
            raise GrantV3ContractError("approval callback returned an invalid value")
        response.__post_init__()
        if not response.approved:
            raise GrantV3Denied("trusted host denied the exact finite scope")
        with self._lock:
            issue_now = self._now_locked()
            issue_state = self._state_locked()
            self._invalidate_locked(issue_state, issue_now)
            if issue_state != state or issue_now >= scope.expires_at_ms:
                raise GrantV3Denied("host state changed during approval")
            self._cleanup_for_capacity_locked()
            if response.attestation_id in self._approvals:
                raise GrantV3Denied("approval attestation was already consumed")
            if response.attestation_sequence <= self._last_attestation_sequence:
                raise GrantV3Denied("approval attestation sequence was already consumed")
            self._sequence += 1
            grant_id = f"grant-{self._sequence:08d}"
            _safe_id(grant_id, "grant_id")
            attestation = _sha(
                {
                    "approved": True,
                    "attestation_id": response.attestation_id,
                    "attestation_sequence": response.attestation_sequence,
                    "contract": "HostApprovalAttestation.v3",
                    "scope_digest": scope_digest,
                    "trust_root_id": self._services.trust_root_id,
                }
            )
            _digest(attestation, "attestation_digest")
            grant = SessionGrant(
                grant_id,
                response.attestation_id,
                response.attestation_sequence,
                attestation,
                scope,
                scope_digest,
                self._sequence,
            )
            self._grants[grant_id] = grant
            self._approvals[response.attestation_id] = issue_state.audit_head
            self._last_attestation_sequence = response.attestation_sequence
            self._uses[grant_id] = 0
            self._costs[grant_id] = 0
            return grant_id

    def _attestation_digest(self, grant: SessionGrant) -> str:
        return _sha(
            {
                "approved": True,
                "attestation_id": grant.approval_id,
                "attestation_sequence": grant.approval_sequence,
                "contract": "HostApprovalAttestation.v3",
                "scope_digest": grant.scope_digest,
                "trust_root_id": self._services.trust_root_id,
            }
        )

    def _action_digest(
        self,
        reference: str,
        resolved: ResolvedAction,
        state: HostState,
        now: int,
        sequence: int,
        scope_digest: str,
    ) -> str:
        try:
            risk = self._policy(
                state, resolved.capability, resolved.tool, resolved.operation
            ).risk
        except GrantV3ContractError:
            risk = "unknown"
        return _sha(
            {
                "account": resolved.account,
                "action_sequence": sequence,
                "capability": resolved.capability,
                "contract": "ActionAudit.v3",
                "cost_micro": resolved.cost_micro,
                "data_class": resolved.data_class,
                "effect": resolved.effect,
                "environment": resolved.environment,
                "invocation_ref_sha256": hashlib.sha256(reference.encode("utf-8")).hexdigest(),
                "mission_id": resolved.mission_id,
                "observed_at_ms": now,
                "operation": resolved.operation,
                "path": resolved.path,
                "policy_version": state.policy_version,
                "principal_id": state.principal_id,
                "risk": risk,
                "schema_version": state.schema_version,
                "scope_digest": scope_digest,
                "session_id": state.session_id,
                "target": resolved.target,
                "tool": resolved.tool,
                "workspace_id": state.workspace_id,
            }
        )

    @staticmethod
    def _scope_matches(
        scope: GrantScope, resolved: ResolvedAction, state: HostState, now: int
    ) -> bool:
        if not scope.not_before_ms <= now < scope.expires_at_ms:
            return False
        policy = state.policy_for(resolved.capability, resolved.tool, resolved.operation)
        exact = (
            (scope.principal_id, state.principal_id),
            (scope.session_id, state.session_id),
            (scope.workspace_id, state.workspace_id),
            (scope.mission_id or "", resolved.mission_id or ""),
            (scope.capability, resolved.capability),
            (scope.tool, resolved.tool),
            (scope.operation, resolved.operation),
            (scope.account, resolved.account),
            (scope.path, resolved.path),
            (scope.effect, resolved.effect),
            (scope.environment, resolved.environment),
            (scope.data_class, resolved.data_class),
            (scope.risk, policy.risk),
        )
        return all(hmac.compare_digest(left, right) for left, right in exact) and any(
            hmac.compare_digest(target, resolved.target) for target in scope.targets
        )

    def evaluate(self, invocation_ref: str) -> ShadowGrantDecision:
        reference = _safe_id(invocation_ref, "invocation_ref")
        if not grant_evaluator_enabled():
            digest = _sha({"contract": "DisabledGrantEvaluation.v3", "invocation_ref": reference})
            return ShadowGrantDecision("disabled", "feature-flag-off", None, "0" * 64, digest)
        with self._lock:
            preflight_now = self._now_locked()
            preflight_state = self._state_locked()
            self._invalidate_locked(preflight_state, preflight_now)
            stopped = self._stop_reason_locked()
            if stopped is not None:
                self._action_sequence += 1
                digest = _sha(
                    {
                        "action_sequence": self._action_sequence,
                        "contract": "StoppedGrantEvaluation.v3",
                        "invocation_ref_sha256": hashlib.sha256(
                            reference.encode("utf-8")
                        ).hexdigest(),
                        "observed_at_ms": preflight_now,
                        "reason": stopped,
                    }
                )
                return ShadowGrantDecision(
                    "would-deny", stopped, None, "0" * 64, digest
                )
        resolved = self._services.resolve_action(reference)
        if not isinstance(resolved, ResolvedAction):
            raise GrantV3ContractError("action resolver returned an invalid value")
        resolved.__post_init__()
        with self._lock:
            now = self._now_locked()
            state = self._state_locked()
            self._invalidate_locked(state, now)
            self._action_sequence += 1
            sequence = self._action_sequence
            zero = "0" * 64
            if self._fail_closed or self._audit_unhealthy:
                digest = self._action_digest(reference, resolved, state, now, sequence, zero)
                return ShadowGrantDecision("would-deny", "audit-unhealthy", None, zero, digest)
            if self._killed:
                digest = self._action_digest(reference, resolved, state, now, sequence, zero)
                return ShadowGrantDecision("would-deny", "kill-switch", None, zero, digest)
            if self._session_ended:
                digest = self._action_digest(reference, resolved, state, now, sequence, zero)
                return ShadowGrantDecision("would-deny", "session-ended", None, zero, digest)
            try:
                policy = self._policy(
                    state, resolved.capability, resolved.tool, resolved.operation
                )
            except GrantV3ContractError:
                digest = self._action_digest(reference, resolved, state, now, sequence, zero)
                return ShadowGrantDecision(
                    "would-deny", "out-of-scope", None, zero, digest
                )
            if policy.always_explicit or policy.risk in {"high", "critical"}:
                digest = self._action_digest(reference, resolved, state, now, sequence, zero)
                return ShadowGrantDecision("would-deny", "out-of-scope", None, zero, digest)
            matches = tuple(
                grant
                for grant in self._grants.values()
                if grant.grant_id not in self._revocations
                and self._scope_matches(grant.scope, resolved, state, now)
            )
            if not matches:
                digest = self._action_digest(reference, resolved, state, now, sequence, zero)
                return ShadowGrantDecision("would-deny", "no-exact-grant", None, zero, digest)
            if len(matches) != 1:
                digest = self._action_digest(reference, resolved, state, now, sequence, zero)
                return ShadowGrantDecision("would-deny", "ambiguous-grant", None, zero, digest)
            grant = matches[0]
            digest = self._action_digest(
                reference, resolved, state, now, sequence, grant.scope_digest
            )
            used = self._uses[grant.grant_id]
            spent = self._costs[grant.grant_id]
            if used >= grant.scope.max_uses:
                self._revoke_locked(grant.grant_id, "use-exhausted", now)
                return ShadowGrantDecision(
                    "would-deny", "out-of-scope", grant.grant_id, grant.scope_digest, digest
                )
            if resolved.cost_micro > grant.scope.max_cost_per_action_micro:
                return ShadowGrantDecision(
                    "would-deny", "per-action-cost", grant.grant_id, grant.scope_digest, digest
                )
            if spent + resolved.cost_micro > grant.scope.max_cost_aggregate_micro:
                self._revoke_locked(grant.grant_id, "aggregate-exhausted", now)
                return ShadowGrantDecision(
                    "would-deny", "aggregate-cost", grant.grant_id, grant.scope_digest, digest
                )
            self._uses[grant.grant_id] = used + 1
            self._costs[grant.grant_id] = spent + resolved.cost_micro
            if used + 1 >= grant.scope.max_uses:
                self._revoke_locked(grant.grant_id, "use-exhausted", now)
            elif spent + resolved.cost_micro >= grant.scope.max_cost_aggregate_micro:
                self._revoke_locked(grant.grant_id, "aggregate-exhausted", now)
            return ShadowGrantDecision(
                "would-allow", "exact-session-grant", grant.grant_id, grant.scope_digest, digest
            )

    def revoke(self, grant_id: str) -> None:
        identifier = _safe_id(grant_id, "grant_id")
        with self._lock:
            now = self._now_locked()
            if identifier not in self._grants:
                raise GrantV3ContractError("unknown grant_id")
            self._revoke_locked(identifier, "owner-revoke", now)

    def kill(self) -> None:
        with self._lock:
            now = self._now_locked()
            self._killed = True
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "kill-switch", now)

    def mark_audit_unhealthy(self) -> None:
        with self._lock:
            now = self._now_locked()
            self._audit_unhealthy = True
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "audit-unhealthy", now)

    def end_session(self) -> None:
        with self._lock:
            now = self._now_locked()
            self._session_ended = True
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "session-ended", now)

    def snapshot_counts(self) -> dict[str, int]:
        with self._lock:
            return {
                "approvals": len(self._approvals),
                "grants": len(self._grants),
                "revocations": len(self._revocations),
            }


__all__ = [
    "GRANT_EVALUATOR_FLAG",
    "GRANT_POLICY_VERSION",
    "GRANT_SCHEMA_VERSION",
    "MAX_APPROVALS",
    "MAX_COST_MICRO",
    "MAX_GRANTS",
    "MAX_MISSIONS",
    "MAX_POLICIES",
    "MAX_REVOCATIONS",
    "MAX_SESSION_LIFETIME_MS",
    "MAX_TARGETS",
    "MAX_USES",
    "ApprovalPrompt",
    "GrantV3CapacityError",
    "GrantV3ContractError",
    "GrantV3Denied",
    "GrantV3Disabled",
    "HostActionPolicy",
    "HostApprovalResponse",
    "HostServices",
    "HostState",
    "ResolvedAction",
    "ResolvedGrantScope",
    "SessionGrantShadowStore",
    "ShadowGrantDecision",
    "canonical_scope_digest",
    "grant_evaluator_enabled",
]
