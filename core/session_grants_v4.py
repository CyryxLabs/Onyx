"""Phase 5.1 R4: exact-payload, pinned-host session-grant shadow evaluator.

The evaluator is strictly default-off, in-memory and advisory.  It never grants
execution authority and never suppresses the existing trusted callback.  Host
callbacks are pinned at construction and are always invoked outside the store
lock.  Reflection or arbitrary code in the same process is outside this API
boundary; no cryptographic process-isolation claim is made.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import posixpath
import re
import secrets
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import quote, urlsplit, urlunsplit

from memory.store import contains_secret


GRANT_EVALUATOR_FLAG = "ONYX_GRANT_EVALUATOR"
GRANT_SCHEMA_VERSION = 4
GRANT_POLICY_VERSION = "onyx-approval-v4"
MAX_SESSION_LIFETIME_MS = 86_400_000
MAX_TARGETS = 8
MAX_TARGET_LENGTH = 256
MAX_TOTAL_TARGET_CHARS = 2_048
MAX_PAYLOADS = 8
MAX_PAYLOAD_SUMMARY_LENGTH = 256
MAX_TOTAL_PAYLOAD_SUMMARY_CHARS = 2_048
MAX_EFFECT_LENGTH = 256
MAX_PLAN_LENGTH = 512
MAX_PROMPT_LENGTH = 8_192
MAX_USES = 10_000
MAX_COST_MICRO = 1_000_000_000_000_000
MAX_POLICIES = 128
MAX_MISSIONS = 128
MAX_GRANTS = 128
MAX_APPROVALS = 128
MAX_REVOCATIONS = 128

_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_WORKSPACE_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_SLUG = re.compile(r"[a-z][a-z0-9-]{1,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_URI_SCHEME = re.compile(r"[a-z][a-z0-9+.-]{1,15}\Z")
_TOKEN_LIKE = re.compile(r"[A-Za-z0-9]{32,}\Z")
_HEX_LIKE = re.compile(r"[0-9a-fA-F]{16,}\Z")
_PERCENT = re.compile(r"%[0-9A-Fa-f]{2}")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")
_RISKS = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_DATA_CLASSES = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
_EGRESS = frozenset({"none", "local-only", "named-account", "public"})
_WINDOWS_DEVICE = re.compile(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?\Z", re.I)
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
        "audit-unhealthy",
        "expired",
        "kill-switch",
        "owner-revoke",
        "semantic-state-changed",
        "session-ended",
        "use-exhausted",
    }
)


class GrantV4Error(RuntimeError):
    pass


class GrantV4ContractError(ValueError):
    pass


class GrantV4Disabled(GrantV4Error):
    pass


class GrantV4Denied(GrantV4Error):
    pass


class GrantV4CapacityError(GrantV4Error):
    pass


def grant_evaluator_enabled(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return source.get(GRANT_EVALUATOR_FLAG, "").strip().casefold() in {"1", "true"}


def _secret_free(value: str, label: str) -> str:
    if contains_secret(value):
        raise GrantV4ContractError(f"{label} contains secret-shaped material")
    return value


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise GrantV4ContractError(f"{label} is invalid")
    if len(value) >= 32 or _TOKEN_LIKE.fullmatch(value) or _HEX_LIKE.fullmatch(value):
        raise GrantV4ContractError(f"{label} is token-like")
    return _secret_free(value, label)


def _workspace_id(value: object) -> str:
    if not isinstance(value, str) or not _WORKSPACE_ID.fullmatch(value):
        raise GrantV4ContractError("workspace_id must match core.workspaces")
    if len(value) >= 32 or _TOKEN_LIKE.fullmatch(value) or _HEX_LIKE.fullmatch(value):
        raise GrantV4ContractError("workspace_id is token-like")
    return _secret_free(value, "workspace_id")


def _slug(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SLUG.fullmatch(value):
        raise GrantV4ContractError(f"{label} is invalid")
    if len(value) >= 32 or _TOKEN_LIKE.fullmatch(value) or _HEX_LIKE.fullmatch(value):
        raise GrantV4ContractError(f"{label} is token-like")
    return _secret_free(value, label)


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise GrantV4ContractError(f"{label} must be lowercase SHA-256")
    return _secret_free(value, label)


def _enum(value: object, allowed: set[str] | frozenset[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise GrantV4ContractError(f"{label} is invalid")
    return _secret_free(value, label)


def _bounded_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise GrantV4ContractError(f"{label} is out of bounds")
    return value


def _bounded_text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise GrantV4ContractError(f"{label} is invalid")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        raise GrantV4ContractError(f"{label} is invalid")
    return _secret_free(normalized, label)


def _canonical(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _sha(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _expected_attestation_id(sequence: int, challenge_digest: str) -> str:
    _bounded_int(sequence, "attestation_sequence", 1, 2**63 - 1)
    _digest(challenge_digest, "challenge_digest")
    return f"att-{sequence:016x}-{challenge_digest[:8]}"


def _normalize_percent(path: str, label: str) -> str:
    index = 0
    pieces: list[str] = []
    while index < len(path):
        if path[index] != "%":
            pieces.append(path[index])
            index += 1
            continue
        token = path[index : index + 3]
        if not _PERCENT.fullmatch(token):
            raise GrantV4ContractError(f"{label} URI has invalid percent encoding")
        octet = int(token[1:], 16)
        if octet in {0x2E, 0x2F, 0x5C}:
            raise GrantV4ContractError(f"{label} URI has encoded separator/dot ambiguity")
        pieces.append("%" + token[1:].upper())
        index += 3
    return "".join(pieces)


def _normalize_windows(raw: str, label: str) -> str:
    if raw.startswith(("\\\\", "//", "\\\\?\\", "\\\\.\\")):
        raise GrantV4ContractError(f"{label} UNC/device path is forbidden")
    path = PureWindowsPath(raw)
    if not path.is_absolute() or not path.drive or len(path.drive) != 2:
        raise GrantV4ContractError(f"{label} Windows path is invalid")
    parts = raw.replace("/", "\\").split("\\")
    if any(part in {".", ".."} for part in parts):
        raise GrantV4ContractError(f"{label} Windows alias is forbidden")
    for index, part in enumerate(parts):
        if not part:
            raise GrantV4ContractError(f"{label} Windows separator alias is forbidden")
        if index == 0 and part.endswith(":"):
            continue
        if ":" in part or part.endswith((".", " ")) or _WINDOWS_DEVICE.fullmatch(part):
            raise GrantV4ContractError(f"{label} Windows alias/device/ADS is forbidden")
    return str(path).replace("\\", "/").casefold()


def _normalize_uri(raw: str, label: str) -> str:
    try:
        parsed = urlsplit(raw)
        scheme = parsed.scheme.casefold()
        if not _URI_SCHEME.fullmatch(scheme) or parsed.username or parsed.password:
            raise GrantV4ContractError(f"{label} URI is invalid")
        if parsed.query or parsed.fragment:
            raise GrantV4ContractError(f"{label} URI query/fragment is forbidden")
        host = parsed.hostname or ""
        if scheme in {"http", "https"} and not host:
            raise GrantV4ContractError(f"{label} URI host is required")
        port = parsed.port
        raw_authority = parsed.netloc
        if ":" in host:
            if not raw_authority.startswith("[") or "]" not in raw_authority:
                raise GrantV4ContractError(f"{label} IPv6 URI must use brackets")
            host = f"[{ipaddress.IPv6Address(host).compressed}]"
        else:
            try:
                host = host.encode("idna").decode("ascii").casefold()
            except UnicodeError as exc:
                raise GrantV4ContractError(f"{label} URI host is invalid") from exc
            if host.endswith(".") or ".." in host:
                raise GrantV4ContractError(f"{label} URI host alias is forbidden")
        netloc = host
        if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
            netloc = f"{host}:{port}"
        path = _normalize_percent(parsed.path or "/", label)
        segments = path.split("/")
        if any(segment in {".", ".."} for segment in segments):
            raise GrantV4ContractError(f"{label} URI dot segment is forbidden")
        normalized_path = posixpath.normpath(path)
        if not normalized_path.startswith("/"):
            normalized_path = "/" + normalized_path
        if path.endswith("/") and normalized_path != "/":
            normalized_path += "/"
        if normalized_path != path:
            raise GrantV4ContractError(f"{label} URI path is noncanonical")
        return urlunsplit((scheme, netloc, quote(normalized_path, safe="/%-._~"), "", ""))
    except GrantV4ContractError:
        raise
    except (ValueError, UnicodeError) as exc:
        raise GrantV4ContractError(f"{label} URI is invalid") from exc


def _normalize_target(value: object, label: str = "target") -> str:
    try:
        if not isinstance(value, str):
            raise GrantV4ContractError(f"{label} is invalid")
        raw = value.strip()
        if not raw or len(raw) > MAX_TARGET_LENGTH or any(ord(char) < 32 for char in raw):
            raise GrantV4ContractError(f"{label} is invalid")
        _secret_free(raw, label)
        if re.match(r"^[A-Za-z]:[\\/]", raw):
            return _secret_free(_normalize_windows(raw, label), label)
        if PurePosixPath(raw).is_absolute():
            parts = raw.split("/")
            if any(part in {".", ".."} for part in parts):
                raise GrantV4ContractError(f"{label} POSIX alias is forbidden")
            normalized = posixpath.normpath(raw)
            if normalized != raw:
                raise GrantV4ContractError(f"{label} POSIX path is noncanonical")
            return _secret_free(normalized, label)
        if urlsplit(raw).scheme:
            return _secret_free(_normalize_uri(raw, label), label)
        if "/" in raw or "\\" in raw or raw in {".", ".."}:
            raise GrantV4ContractError(f"{label} relative path is forbidden")
        return _safe_id(raw, label)
    except GrantV4ContractError:
        raise
    except (OSError, TypeError, ValueError, UnicodeError) as exc:
        raise GrantV4ContractError(f"{label} is invalid") from exc


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
            raise GrantV4ContractError("always_explicit must be boolean")

    @property
    def key(self) -> tuple[str, str, str]:
        return self.capability, self.tool, self.operation

    def payload(self) -> dict[str, object]:
        return {
            "always_explicit": self.always_explicit,
            "capability": self.capability,
            "max_data_class": self.max_data_class,
            "operation": self.operation,
            "risk": self.risk,
            "tool": self.tool,
        }


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
        if self.schema_version != GRANT_SCHEMA_VERSION:
            raise GrantV4ContractError("unknown grant schema version")
        if self.policy_version != GRANT_POLICY_VERSION:
            raise GrantV4ContractError("unknown grant policy version")
        _safe_id(self.principal_id, "principal_id")
        _safe_id(self.session_id, "session_id")
        _workspace_id(self.workspace_id)
        if not isinstance(self.mission_ids, tuple) or len(self.mission_ids) > MAX_MISSIONS:
            raise GrantV4ContractError("mission collection exceeds its bound")
        missions = tuple(sorted(_safe_id(item, "mission_id") for item in self.mission_ids))
        if len(set(missions)) != len(missions):
            raise GrantV4ContractError("mission IDs are duplicated")
        object.__setattr__(self, "mission_ids", missions)
        if not isinstance(self.policies, tuple) or not 1 <= len(self.policies) <= MAX_POLICIES:
            raise GrantV4ContractError("policy collection exceeds its bound")
        if any(not isinstance(item, HostActionPolicy) for item in self.policies):
            raise GrantV4ContractError("host policy is invalid")
        policies = tuple(sorted(self.policies, key=lambda item: item.key))
        if len({item.key for item in policies}) != len(policies):
            raise GrantV4ContractError("host policies are duplicated")
        object.__setattr__(self, "policies", policies)
        _digest(self.audit_head, "audit_head")
        for name in ("audit_healthy", "session_active", "kill_switch"):
            if type(getattr(self, name)) is not bool:
                raise GrantV4ContractError(f"{name} must be boolean")

    def policy_for(self, capability: str, tool: str, operation: str) -> HostActionPolicy:
        matches = tuple(item for item in self.policies if item.key == (capability, tool, operation))
        if len(matches) != 1:
            raise GrantV4ContractError("unknown or ambiguous host action policy")
        return matches[0]

    def fingerprint(self) -> str:
        return _sha(
            {
                "audit_head": self.audit_head,
                "contract": "HostSemanticState.v4",
                "mission_ids": list(self.mission_ids),
                "policies": [item.payload() for item in self.policies],
                "policy_version": self.policy_version,
                "principal_id": self.principal_id,
                "schema_version": self.schema_version,
                "session_id": self.session_id,
                "workspace_id": self.workspace_id,
            }
        )


@dataclass(frozen=True, slots=True)
class AllowedPayload:
    payload_digest: str
    summary: str
    rule_id: str
    egress: str
    idempotency_key: str

    def __post_init__(self) -> None:
        _digest(self.payload_digest, "payload_digest")
        object.__setattr__(self, "summary", _bounded_text(self.summary, "payload_summary", MAX_PAYLOAD_SUMMARY_LENGTH))
        _safe_id(self.rule_id, "payload_rule_id")
        _enum(self.egress, _EGRESS, "egress")
        _safe_id(self.idempotency_key, "idempotency_key")

    def payload(self) -> dict[str, str]:
        return {
            "egress": self.egress,
            "idempotency_key": self.idempotency_key,
            "payload_digest": self.payload_digest,
            "rule_id": self.rule_id,
            "summary": self.summary,
        }


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
    payloads: tuple[AllowedPayload, ...]
    reversible: bool
    verification_plan: str
    rollback_plan: str
    cost_currency: str
    cost_unit: str
    initial_target: str
    initial_payload_digest: str
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
            raise GrantV4ContractError("target collection exceeds its bound")
        targets = tuple(sorted(_normalize_target(item) for item in self.targets))
        if len(set(targets)) != len(targets) or sum(map(len, targets)) > MAX_TOTAL_TARGET_CHARS:
            raise GrantV4ContractError("targets are duplicate, noncanonical, or exceed total bound")
        object.__setattr__(self, "targets", targets)
        object.__setattr__(self, "account", _normalize_target(self.account, "account"))
        object.__setattr__(self, "path", _normalize_target(self.path, "path"))
        object.__setattr__(self, "effect", _bounded_text(self.effect, "effect", MAX_EFFECT_LENGTH))
        _safe_id(self.environment, "environment")
        _enum(self.data_class, set(_DATA_CLASSES), "data_class")
        if not isinstance(self.payloads, tuple) or not 1 <= len(self.payloads) <= MAX_PAYLOADS:
            raise GrantV4ContractError("payload collection exceeds its bound")
        if any(not isinstance(item, AllowedPayload) for item in self.payloads):
            raise GrantV4ContractError("payload contract is invalid")
        payloads = tuple(sorted(self.payloads, key=lambda item: item.payload_digest))
        if len({item.payload_digest for item in payloads}) != len(payloads):
            raise GrantV4ContractError("payload digests are duplicated")
        if sum(len(item.summary) for item in payloads) > MAX_TOTAL_PAYLOAD_SUMMARY_CHARS:
            raise GrantV4ContractError("payload summaries exceed total bound")
        object.__setattr__(self, "payloads", payloads)
        if type(self.reversible) is not bool:
            raise GrantV4ContractError("reversible must be boolean")
        object.__setattr__(self, "verification_plan", _bounded_text(self.verification_plan, "verification_plan", MAX_PLAN_LENGTH))
        object.__setattr__(self, "rollback_plan", _bounded_text(self.rollback_plan, "rollback_plan", MAX_PLAN_LENGTH))
        if not isinstance(self.cost_currency, str) or not _CURRENCY.fullmatch(self.cost_currency):
            raise GrantV4ContractError("cost_currency is invalid")
        _secret_free(self.cost_currency, "cost_currency")
        _slug(self.cost_unit, "cost_unit")
        initial_target = _normalize_target(self.initial_target, "initial_target")
        object.__setattr__(self, "initial_target", initial_target)
        if initial_target not in targets:
            raise GrantV4ContractError("initial target is outside the finite target set")
        _digest(self.initial_payload_digest, "initial_payload_digest")
        if self.initial_payload_digest not in {item.payload_digest for item in payloads}:
            raise GrantV4ContractError("initial payload is outside the finite payload set")
        initial = _bounded_int(self.initial_cost_micro, "initial_cost_micro", 0, MAX_COST_MICRO)
        per_action = _bounded_int(self.max_cost_per_action_micro, "max_cost_per_action_micro", 0, MAX_COST_MICRO)
        aggregate = _bounded_int(self.max_cost_aggregate_micro, "max_cost_aggregate_micro", 0, MAX_COST_MICRO)
        if aggregate < per_action or initial > per_action or initial > aggregate:
            raise GrantV4ContractError("cost bounds are contradictory")
        _bounded_int(self.max_uses, "max_uses", 1, MAX_USES)
        delay = _bounded_int(self.not_before_delay_ms, "not_before_delay_ms", 0, MAX_SESSION_LIFETIME_MS - 1)
        lifetime = _bounded_int(self.lifetime_ms, "lifetime_ms", 1, MAX_SESSION_LIFETIME_MS)
        if delay >= lifetime:
            raise GrantV4ContractError("grant time bounds are contradictory")


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
    payload_digest: str
    payload_summary: str
    payload_rule_id: str
    egress: str
    idempotency_key: str
    reversible: bool
    verification_plan: str
    rollback_plan: str
    cost_currency: str
    cost_unit: str
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
        _digest(self.payload_digest, "payload_digest")
        object.__setattr__(self, "payload_summary", _bounded_text(self.payload_summary, "payload_summary", MAX_PAYLOAD_SUMMARY_LENGTH))
        _safe_id(self.payload_rule_id, "payload_rule_id")
        _enum(self.egress, _EGRESS, "egress")
        _safe_id(self.idempotency_key, "idempotency_key")
        if type(self.reversible) is not bool:
            raise GrantV4ContractError("reversible must be boolean")
        object.__setattr__(self, "verification_plan", _bounded_text(self.verification_plan, "verification_plan", MAX_PLAN_LENGTH))
        object.__setattr__(self, "rollback_plan", _bounded_text(self.rollback_plan, "rollback_plan", MAX_PLAN_LENGTH))
        if not isinstance(self.cost_currency, str) or not _CURRENCY.fullmatch(self.cost_currency):
            raise GrantV4ContractError("cost_currency is invalid")
        _secret_free(self.cost_currency, "cost_currency")
        _slug(self.cost_unit, "cost_unit")
        _bounded_int(self.cost_micro, "cost_micro", 0, MAX_COST_MICRO)


@dataclass(frozen=True, slots=True)
class HostApprovalResponse:
    approved: bool
    attestation_id: str
    attestation_sequence: int
    challenge_digest: str
    scope_digest: str
    prompt_digest: str

    def __post_init__(self) -> None:
        if type(self.approved) is not bool:
            raise GrantV4ContractError("approval decision must be boolean")
        _safe_id(self.attestation_id, "attestation_id")
        _bounded_int(self.attestation_sequence, "attestation_sequence", 1, 2**63 - 1)
        _digest(self.challenge_digest, "challenge_digest")
        _digest(self.scope_digest, "scope_digest")
        _digest(self.prompt_digest, "prompt_digest")


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
                raise GrantV4ContractError(f"host service {name} is not callable")


@dataclass(frozen=True, slots=True)
class GrantScope:
    schema_version: int
    policy_version: str
    state_fingerprint: str
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
    payloads: tuple[AllowedPayload, ...]
    reversible: bool
    verification_plan: str
    rollback_plan: str
    cost_currency: str
    cost_unit: str
    initial_target: str
    initial_payload_digest: str
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
        "contract": "SessionGrantScope.v4",
        "cost_currency": scope.cost_currency,
        "cost_unit": scope.cost_unit,
        "data_class": scope.data_class,
        "effect": scope.effect,
        "environment": scope.environment,
        "expires_at_ms": scope.expires_at_ms,
        "initial_cost_micro": scope.initial_cost_micro,
        "initial_payload_digest": scope.initial_payload_digest,
        "initial_target": scope.initial_target,
        "issued_at_ms": scope.issued_at_ms,
        "max_cost_aggregate_micro": scope.max_cost_aggregate_micro,
        "max_cost_per_action_micro": scope.max_cost_per_action_micro,
        "max_uses": scope.max_uses,
        "mission_id": scope.mission_id,
        "not_before_ms": scope.not_before_ms,
        "operation": scope.operation,
        "path": scope.path,
        "payloads": [item.payload() for item in scope.payloads],
        "policy_version": scope.policy_version,
        "principal_id": scope.principal_id,
        "reversible": scope.reversible,
        "risk": scope.risk,
        "rollback_plan": scope.rollback_plan,
        "schema_version": scope.schema_version,
        "session_id": scope.session_id,
        "state_fingerprint": scope.state_fingerprint,
        "targets": list(scope.targets),
        "tool": scope.tool,
        "trust_root_id": scope.trust_root_id,
        "verification_plan": scope.verification_plan,
        "workspace_id": scope.workspace_id,
    }


def canonical_scope_digest(scope: GrantScope) -> str:
    return _sha(_scope_payload(scope))


def _prompt_digest(scope_digest: str, challenge_digest: str, summary: str) -> str:
    return _sha(
        {
            "challenge_digest": challenge_digest,
            "contract": "ApprovalPrompt.v4",
            "human_summary": summary,
            "scope_digest": scope_digest,
        }
    )


@dataclass(frozen=True, slots=True)
class ApprovalPrompt:
    scope: GrantScope
    scope_digest: str
    challenge_digest: str
    human_summary: str
    prompt_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.scope, GrantScope):
            raise GrantV4ContractError("approval scope is invalid")
        _digest(self.scope_digest, "scope_digest")
        _digest(self.challenge_digest, "challenge_digest")
        _digest(self.prompt_digest, "prompt_digest")
        summary = _bounded_text(self.human_summary, "human_summary", MAX_PROMPT_LENGTH)
        if not hmac.compare_digest(self.scope_digest, canonical_scope_digest(self.scope)):
            raise GrantV4ContractError("approval scope digest is invalid")
        if not hmac.compare_digest(self.prompt_digest, _prompt_digest(self.scope_digest, self.challenge_digest, summary)):
            raise GrantV4ContractError("approval prompt digest is invalid")


@dataclass(frozen=True, slots=True)
class SessionGrant:
    grant_id: str
    approval_id: str
    approval_sequence: int
    challenge_digest: str
    prompt_digest: str
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
    def __init__(self, services: HostServices) -> None:
        if not isinstance(services, HostServices):
            raise GrantV4ContractError("HostServices is required")
        self._services = services
        self._grants: dict[str, SessionGrant] = {}
        self._approvals: dict[str, str] = {}
        self._revocations: dict[str, GrantRevocation] = {}
        self._uses: dict[str, int] = {}
        self._costs: dict[str, int] = {}
        self._sequence = 0
        self._action_sequence = 0
        self._generation = 0
        self._clock_high_water = 0
        self._last_attestation_sequence = 0
        self._killed = False
        self._audit_unhealthy = False
        self._session_ended = False
        self._fail_closed = False
        self._lock = threading.RLock()

    def _host_snapshot(self) -> tuple[int, HostState]:
        try:
            now = _bounded_int(self._services.monotonic_ms(), "monotonic_ms", 0, 2**63 - 1)
            state = self._services.state()
            if not isinstance(state, HostState):
                raise GrantV4ContractError("host state service returned an invalid value")
            state.__post_init__()
            return now, state
        except GrantV4ContractError:
            self._record_host_failure()
            raise
        except Exception as exc:
            self._record_host_failure()
            raise GrantV4ContractError("host snapshot callback failed") from exc

    def _record_host_failure(self) -> None:
        with self._lock:
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "semantic-state-changed", self._clock_high_water)
            self._fail_closed = True
            self._generation += 1

    def _accept_snapshot_locked(self, raw_now: int, state: HostState) -> int:
        now = max(raw_now, self._clock_high_water)
        self._clock_high_water = now
        self._invalidate_locked(state, now)
        return now

    def _revoke_locked(self, grant_id: str, reason: str, now: int) -> None:
        if grant_id in self._revocations:
            return
        if len(self._revocations) >= MAX_REVOCATIONS:
            self._fail_closed = True
            self._generation += 1
            return
        self._sequence += 1
        self._generation += 1
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
        fingerprint = state.fingerprint()
        for grant in tuple(self._grants.values()):
            if grant.grant_id in self._revocations:
                continue
            if now >= grant.scope.expires_at_ms:
                self._revoke_locked(grant.grant_id, "expired", now)
            elif not hmac.compare_digest(grant.scope.state_fingerprint, fingerprint):
                self._revoke_locked(grant.grant_id, "semantic-state-changed", now)
            elif not hmac.compare_digest(grant.attestation_digest, self._attestation_digest(grant)):
                self._revoke_locked(grant.grant_id, "semantic-state-changed", now)

    def _stop_reason_locked(self) -> str | None:
        if self._fail_closed or self._audit_unhealthy:
            return "audit-unhealthy"
        if self._killed:
            return "kill-switch"
        if self._session_ended:
            return "session-ended"
        return None

    def _local_stop(self) -> str | None:
        with self._lock:
            return self._stop_reason_locked()

    def _cleanup_for_capacity_locked(self) -> None:
        while len(self._grants) >= MAX_GRANTS:
            terminal = sorted(
                (self._revocations[grant_id].sequence, grant.sequence, grant_id)
                for grant_id, grant in self._grants.items()
                if grant_id in self._revocations
            )
            if not terminal:
                raise GrantV4CapacityError("active grant capacity is exhausted")
            _rev_seq, _grant_seq, grant_id = terminal[0]
            grant = self._grants.pop(grant_id)
            self._revocations.pop(grant_id, None)
            self._uses.pop(grant_id, None)
            self._costs.pop(grant_id, None)
            self._approvals.pop(grant.approval_id, None)
        if len(self._approvals) >= MAX_APPROVALS:
            raise GrantV4CapacityError("approval capacity is exhausted")

    @staticmethod
    def _policy(state: HostState, capability: str, tool: str, operation: str) -> HostActionPolicy:
        return state.policy_for(capability, tool, operation)

    def _scope_from_resolved(self, resolved: ResolvedGrantScope, state: HostState, now: int) -> GrantScope:
        if not isinstance(resolved, ResolvedGrantScope):
            raise GrantV4ContractError("grant resolver returned an invalid value")
        resolved.__post_init__()
        if resolved.mission_id is not None and resolved.mission_id not in state.mission_ids:
            raise GrantV4ContractError("grant mission is not host-authorized")
        policy = self._policy(state, resolved.capability, resolved.tool, resolved.operation)
        if policy.always_explicit or policy.risk in {"high", "critical"}:
            raise GrantV4Denied("always-explicit/high-risk action cannot be granted")
        if _DATA_CLASSES[resolved.data_class] > _DATA_CLASSES[policy.max_data_class]:
            raise GrantV4ContractError("grant data class exceeds host policy")
        return GrantScope(
            schema_version=state.schema_version,
            policy_version=state.policy_version,
            state_fingerprint=state.fingerprint(),
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
            payloads=resolved.payloads,
            reversible=resolved.reversible,
            verification_plan=resolved.verification_plan,
            rollback_plan=resolved.rollback_plan,
            cost_currency=resolved.cost_currency,
            cost_unit=resolved.cost_unit,
            initial_target=resolved.initial_target,
            initial_payload_digest=resolved.initial_payload_digest,
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
        payloads = "; ".join(
            f"{item.payload_digest} ({item.summary}; rule {item.rule_id}; egress {item.egress}; idempotency {item.idempotency_key})"
            for item in scope.payloads
        )
        summary = (
            f"Principal {scope.principal_id}; session {scope.session_id}; workspace {scope.workspace_id}; "
            f"mission {scope.mission_id or 'none'}; action {scope.capability}/{scope.tool}/{scope.operation}; "
            f"targets [{', '.join(scope.targets)}]; account {scope.account}; path {scope.path}; "
            f"environment {scope.environment}; effect {scope.effect}; payloads [{payloads}]; "
            f"what leaves device {', '.join(sorted({item.egress for item in scope.payloads}))}; "
            f"data {scope.data_class}; risk {scope.risk}; reversible {scope.reversible}; "
            f"verification {scope.verification_plan}; rollback {scope.rollback_plan}; "
            f"cost {scope.cost_currency} {scope.cost_unit}, initial {scope.initial_cost_micro}, "
            f"per-action max {scope.max_cost_per_action_micro}, aggregate max {scope.max_cost_aggregate_micro}; "
            f"uses {scope.max_uses}; valid {scope.not_before_ms} through {scope.expires_at_ms}."
        )
        return _bounded_text(summary, "human_summary", MAX_PROMPT_LENGTH)

    def request_session_grant(self, invocation_ref: str) -> str:
        reference = _safe_id(invocation_ref, "invocation_ref")
        if not grant_evaluator_enabled():
            raise GrantV4Disabled("grant evaluator is disabled")
        if self._local_stop() is not None:
            raise GrantV4Denied("host session is not healthy")
        raw_now, state = self._host_snapshot()
        resolved = self._services.resolve_grant(reference)
        if not isinstance(resolved, ResolvedGrantScope):
            raise GrantV4ContractError("grant resolver returned an invalid value")
        resolved.__post_init__()
        raw_now, state = self._host_snapshot()
        with self._lock:
            now = self._accept_snapshot_locked(raw_now, state)
            if self._stop_reason_locked() is not None:
                raise GrantV4Denied("host session is not healthy")
            self._cleanup_for_capacity_locked()
            scope = self._scope_from_resolved(resolved, state, now)
            scope_digest = canonical_scope_digest(scope)
            challenge = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
            summary = self._human_summary(scope)
            prompt_digest = _prompt_digest(scope_digest, challenge, summary)
            prompt = ApprovalPrompt(scope, scope_digest, challenge, summary, prompt_digest)
            approval_generation = self._generation
            state_fingerprint = state.fingerprint()
        response = self._services.approve(prompt)
        if not isinstance(response, HostApprovalResponse):
            raise GrantV4ContractError("approval callback returned an invalid value")
        response.__post_init__()
        if self._local_stop() is not None:
            raise GrantV4Denied("host session changed during approval")
        raw_issue_now, issue_state = self._host_snapshot()
        with self._lock:
            issue_now = self._accept_snapshot_locked(raw_issue_now, issue_state)
            if self._stop_reason_locked() is not None or self._generation != approval_generation:
                raise GrantV4Denied("host session changed during approval")
            if not hmac.compare_digest(state_fingerprint, issue_state.fingerprint()) or issue_now >= scope.expires_at_ms:
                raise GrantV4Denied("host state changed during approval")
            if not response.approved:
                raise GrantV4Denied("trusted host denied the exact finite scope")
            echoes = (
                (response.challenge_digest, challenge),
                (response.scope_digest, scope_digest),
                (response.prompt_digest, prompt_digest),
            )
            if not all(hmac.compare_digest(left, right) for left, right in echoes):
                raise GrantV4Denied("approval response did not bind the exact prompt")
            expected_id = _expected_attestation_id(response.attestation_sequence, challenge)
            if not hmac.compare_digest(response.attestation_id, expected_id):
                raise GrantV4Denied("approval ID is not structurally bound")
            if response.attestation_sequence <= self._last_attestation_sequence:
                raise GrantV4Denied("approval attestation sequence was already consumed")
            self._cleanup_for_capacity_locked()
            if response.attestation_id in self._approvals:
                raise GrantV4Denied("approval attestation was already consumed")
            self._sequence += 1
            grant_id = f"grant-{self._sequence:08d}"
            _safe_id(grant_id, "grant_id")
            attestation = _sha(
                {
                    "approval_id": response.attestation_id,
                    "approval_sequence": response.attestation_sequence,
                    "challenge_digest": challenge,
                    "contract": "HostApprovalAttestation.v4",
                    "prompt_digest": prompt_digest,
                    "scope_digest": scope_digest,
                    "trust_root_id": self._services.trust_root_id,
                }
            )
            grant = SessionGrant(
                grant_id,
                response.attestation_id,
                response.attestation_sequence,
                challenge,
                prompt_digest,
                attestation,
                scope,
                scope_digest,
                self._sequence,
            )
            self._grants[grant_id] = grant
            self._approvals[response.attestation_id] = state_fingerprint
            self._last_attestation_sequence = response.attestation_sequence
            self._uses[grant_id] = 0
            self._costs[grant_id] = 0
            return grant_id

    def _attestation_digest(self, grant: SessionGrant) -> str:
        return _sha(
            {
                "approval_id": grant.approval_id,
                "approval_sequence": grant.approval_sequence,
                "challenge_digest": grant.challenge_digest,
                "contract": "HostApprovalAttestation.v4",
                "prompt_digest": grant.prompt_digest,
                "scope_digest": grant.scope_digest,
                "trust_root_id": self._services.trust_root_id,
            }
        )

    def _action_digest(self, reference: str, action: ResolvedAction, state: HostState, now: int, sequence: int, scope_digest: str) -> str:
        try:
            risk = state.policy_for(action.capability, action.tool, action.operation).risk
        except GrantV4ContractError:
            risk = "unknown"
        return _sha(
            {
                "account": action.account,
                "action_sequence": sequence,
                "capability": action.capability,
                "contract": "ActionAudit.v4",
                "cost_currency": action.cost_currency,
                "cost_micro": action.cost_micro,
                "cost_unit": action.cost_unit,
                "data_class": action.data_class,
                "effect": action.effect,
                "egress": action.egress,
                "environment": action.environment,
                "idempotency_key": action.idempotency_key,
                "invocation_ref_sha256": hashlib.sha256(reference.encode()).hexdigest(),
                "mission_id": action.mission_id,
                "observed_at_ms": now,
                "operation": action.operation,
                "path": action.path,
                "payload_digest": action.payload_digest,
                "payload_rule_id": action.payload_rule_id,
                "payload_summary": action.payload_summary,
                "reversible": action.reversible,
                "risk": risk,
                "rollback_plan": action.rollback_plan,
                "scope_digest": scope_digest,
                "state_fingerprint": state.fingerprint(),
                "target": action.target,
                "tool": action.tool,
                "verification_plan": action.verification_plan,
            }
        )

    @staticmethod
    def _scope_matches(scope: GrantScope, action: ResolvedAction, state: HostState, now: int) -> bool:
        if not scope.not_before_ms <= now < scope.expires_at_ms:
            return False
        policy = state.policy_for(action.capability, action.tool, action.operation)
        exact = (
            (scope.state_fingerprint, state.fingerprint()),
            (scope.mission_id or "", action.mission_id or ""),
            (scope.capability, action.capability),
            (scope.tool, action.tool),
            (scope.operation, action.operation),
            (scope.account, action.account),
            (scope.path, action.path),
            (scope.effect, action.effect),
            (scope.environment, action.environment),
            (scope.data_class, action.data_class),
            (scope.risk, policy.risk),
            (scope.verification_plan, action.verification_plan),
            (scope.rollback_plan, action.rollback_plan),
            (scope.cost_currency, action.cost_currency),
            (scope.cost_unit, action.cost_unit),
        )
        payload_matches = tuple(
            item
            for item in scope.payloads
            if hmac.compare_digest(item.payload_digest, action.payload_digest)
            and hmac.compare_digest(item.summary, action.payload_summary)
            and hmac.compare_digest(item.rule_id, action.payload_rule_id)
            and hmac.compare_digest(item.egress, action.egress)
            and hmac.compare_digest(item.idempotency_key, action.idempotency_key)
        )
        return (
            all(hmac.compare_digest(left, right) for left, right in exact)
            and scope.reversible is action.reversible
            and any(hmac.compare_digest(target, action.target) for target in scope.targets)
            and len(payload_matches) == 1
        )

    def _stopped_decision_locked(self, reference: str, reason: str) -> ShadowGrantDecision:
        self._action_sequence += 1
        digest = _sha(
            {
                "action_sequence": self._action_sequence,
                "contract": "StoppedGrantEvaluation.v4",
                "invocation_ref_sha256": hashlib.sha256(reference.encode()).hexdigest(),
                "observed_at_ms": self._clock_high_water,
                "reason": reason,
            }
        )
        return ShadowGrantDecision("would-deny", reason, None, "0" * 64, digest)

    def evaluate(self, invocation_ref: str) -> ShadowGrantDecision:
        reference = _safe_id(invocation_ref, "invocation_ref")
        if not grant_evaluator_enabled():
            digest = _sha({"contract": "DisabledGrantEvaluation.v4", "invocation_ref": reference})
            return ShadowGrantDecision("disabled", "feature-flag-off", None, "0" * 64, digest)
        with self._lock:
            stopped = self._stop_reason_locked()
            if stopped is not None:
                return self._stopped_decision_locked(reference, stopped)
        action = self._services.resolve_action(reference)
        if not isinstance(action, ResolvedAction):
            raise GrantV4ContractError("action resolver returned an invalid value")
        action.__post_init__()
        raw_now, state = self._host_snapshot()
        with self._lock:
            now = self._accept_snapshot_locked(raw_now, state)
            stopped = self._stop_reason_locked()
            if stopped is not None:
                return self._stopped_decision_locked(reference, stopped)
            self._action_sequence += 1
            sequence = self._action_sequence
            zero = "0" * 64
            try:
                policy = self._policy(state, action.capability, action.tool, action.operation)
            except GrantV4ContractError:
                digest = self._action_digest(reference, action, state, now, sequence, zero)
                return ShadowGrantDecision("would-deny", "out-of-scope", None, zero, digest)
            if policy.always_explicit or policy.risk in {"high", "critical"}:
                digest = self._action_digest(reference, action, state, now, sequence, zero)
                return ShadowGrantDecision("would-deny", "out-of-scope", None, zero, digest)
            matches = tuple(
                grant for grant in self._grants.values()
                if grant.grant_id not in self._revocations and self._scope_matches(grant.scope, action, state, now)
            )
            if len(matches) != 1:
                reason = "ambiguous-grant" if len(matches) > 1 else "no-exact-grant"
                digest = self._action_digest(reference, action, state, now, sequence, zero)
                return ShadowGrantDecision("would-deny", reason, None, zero, digest)
            grant = matches[0]
            digest = self._action_digest(reference, action, state, now, sequence, grant.scope_digest)
            used = self._uses[grant.grant_id]
            spent = self._costs[grant.grant_id]
            if used >= grant.scope.max_uses:
                self._revoke_locked(grant.grant_id, "use-exhausted", now)
                return ShadowGrantDecision("would-deny", "out-of-scope", grant.grant_id, grant.scope_digest, digest)
            if action.cost_micro > grant.scope.max_cost_per_action_micro:
                return ShadowGrantDecision("would-deny", "per-action-cost", grant.grant_id, grant.scope_digest, digest)
            if spent + action.cost_micro > grant.scope.max_cost_aggregate_micro:
                return ShadowGrantDecision("would-deny", "aggregate-cost", grant.grant_id, grant.scope_digest, digest)
            used += 1
            spent += action.cost_micro
            self._uses[grant.grant_id] = used
            self._costs[grant.grant_id] = spent
            if used >= grant.scope.max_uses:
                self._revoke_locked(grant.grant_id, "use-exhausted", now)
            elif spent >= grant.scope.max_cost_aggregate_micro:
                self._revoke_locked(grant.grant_id, "aggregate-exhausted", now)
            return ShadowGrantDecision("would-allow", "exact-session-grant", grant.grant_id, grant.scope_digest, digest)

    def revoke(self, grant_id: str) -> None:
        identifier = _safe_id(grant_id, "grant_id")
        with self._lock:
            self._generation += 1
            if identifier not in self._grants:
                raise GrantV4ContractError("unknown grant_id")
            self._revoke_locked(identifier, "owner-revoke", self._clock_high_water)

    def kill(self) -> None:
        with self._lock:
            self._killed = True
            self._generation += 1
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "kill-switch", self._clock_high_water)

    def mark_audit_unhealthy(self) -> None:
        with self._lock:
            self._audit_unhealthy = True
            self._generation += 1
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "audit-unhealthy", self._clock_high_water)

    def end_session(self) -> None:
        with self._lock:
            self._session_ended = True
            self._generation += 1
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "session-ended", self._clock_high_water)

    def snapshot_counts(self) -> dict[str, int]:
        with self._lock:
            return {"approvals": len(self._approvals), "grants": len(self._grants), "revocations": len(self._revocations)}


__all__ = [
    "GRANT_EVALUATOR_FLAG", "GRANT_POLICY_VERSION", "GRANT_SCHEMA_VERSION",
    "MAX_APPROVALS", "MAX_COST_MICRO", "MAX_EFFECT_LENGTH", "MAX_GRANTS",
    "MAX_MISSIONS", "MAX_PAYLOADS", "MAX_PAYLOAD_SUMMARY_LENGTH",
    "MAX_PLAN_LENGTH", "MAX_POLICIES", "MAX_PROMPT_LENGTH", "MAX_REVOCATIONS",
    "MAX_SESSION_LIFETIME_MS", "MAX_TARGETS", "MAX_TARGET_LENGTH",
    "MAX_TOTAL_PAYLOAD_SUMMARY_CHARS", "MAX_TOTAL_TARGET_CHARS", "MAX_USES",
    "AllowedPayload", "ApprovalPrompt", "GrantV4CapacityError",
    "GrantV4ContractError", "GrantV4Denied", "GrantV4Disabled", "HostActionPolicy",
    "HostApprovalResponse", "HostServices", "HostState", "ResolvedAction",
    "ResolvedGrantScope", "SessionGrantShadowStore", "ShadowGrantDecision",
    "canonical_scope_digest", "grant_evaluator_enabled",
]
