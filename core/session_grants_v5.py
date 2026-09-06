"""Phase 5.1 R5: exact-action, two-phase session-grant shadow evaluator.

Strictly default-off, session-only and advisory.  It neither authorizes an
action nor suppresses the existing trusted callback.  Every host callback runs
outside the store lock; all callback values are copied and revalidated at the
trust boundary.
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
GRANT_SCHEMA_VERSION = 5
GRANT_POLICY_VERSION = "onyx-approval-v5"
MAX_MONOTONIC_MS = 9_223_372_036_854_775_807
MAX_SESSION_LIFETIME_MS = 86_400_000
MAX_RESERVATION_LIFETIME_MS = 60_000
MAX_BINDINGS = 16
MAX_TARGET_DISPLAY_LENGTH = 256
MAX_TOTAL_TARGET_DISPLAY_CHARS = 2_048
MAX_PAYLOAD_SUMMARY_LENGTH = 256
MAX_TOTAL_PAYLOAD_SUMMARY_CHARS = 2_048
MAX_EFFECT_LENGTH = 256
MAX_PLAN_LENGTH = 512
MAX_PROMPT_LENGTH = 12_288
MAX_USES = 10_000
MAX_COST_MICRO = 1_000_000_000_000_000
MAX_POLICIES = 128
MAX_MISSIONS = 128
MAX_GRANTS = 128
MAX_APPROVALS = 128
MAX_REVOCATIONS = 128
MAX_RESERVATIONS = 128
MAX_RECEIPTS = 1_024
MAX_OUTCOMES = 1_024

_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_SLUG = re.compile(r"[a-z][a-z0-9-]{1,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_NUMERIC_HOST = re.compile(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*\Z", re.I)
_PERCENT = re.compile(r"%[0-9A-Fa-f]{2}")
_WINDOWS_DEVICE = re.compile(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?\Z", re.I)
_TOKEN_LIKE = re.compile(r"[A-Za-z0-9]{32,}\Z")
_HEX_LIKE = re.compile(r"[0-9a-fA-F]{16,}\Z")
_RISKS = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_DATA_CLASSES = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
_EGRESS = frozenset({"none", "local-only", "named-account", "public"})
_OUTCOMES = frozenset({"verified", "cancelled", "denied", "unverified"})
_DECISION_REASONS = frozenset(
    {
        "aggregate-cost", "ambiguous-grant", "audit-unhealthy", "exact-session-grant",
        "feature-flag-off", "kill-switch", "no-exact-grant", "out-of-scope",
        "per-action-cost", "reservation-capacity", "session-ended",
    }
)
_COMMIT_REASONS = frozenset({"cancelled", "denied", "unverified", "verified-commit"})
_REVOCATION_REASONS = frozenset(
    {"aggregate-exhausted", "audit-unhealthy", "expired", "kill-switch", "owner-revoke", "semantic-state-changed", "session-ended", "use-exhausted"}
)


class GrantV5Error(RuntimeError):
    pass


class GrantV5ContractError(ValueError):
    pass


class GrantV5Disabled(GrantV5Error):
    pass


class GrantV5Denied(GrantV5Error):
    pass


class GrantV5CapacityError(GrantV5Error):
    pass


def grant_evaluator_enabled(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return source.get(GRANT_EVALUATOR_FLAG, "").strip().casefold() in {"1", "true"}


def _secret_free(value: str, label: str) -> str:
    if contains_secret(value):
        raise GrantV5ContractError(f"{label} contains secret-shaped material")
    return value


def _safe_id(value: object, label: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise GrantV5ContractError(f"{label} is invalid")
    if len(value) >= 32 or _TOKEN_LIKE.fullmatch(value) or _HEX_LIKE.fullmatch(value):
        raise GrantV5ContractError(f"{label} is token-like")
    return _secret_free(value, label)


def _slug(value: object, label: str) -> str:
    if type(value) is not str or not _SLUG.fullmatch(value):
        raise GrantV5ContractError(f"{label} is invalid")
    if len(value) >= 32 or _TOKEN_LIKE.fullmatch(value) or _HEX_LIKE.fullmatch(value):
        raise GrantV5ContractError(f"{label} is token-like")
    return _secret_free(value, label)


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise GrantV5ContractError(f"{label} must be lowercase SHA-256")
    return _secret_free(value, label)


def _enum(value: object, allowed: set[str] | frozenset[str], label: str) -> str:
    if type(value) is not str or value not in allowed:
        raise GrantV5ContractError(f"{label} is invalid")
    return _secret_free(value, label)


def _bounded_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise GrantV5ContractError(f"{label} is out of bounds")
    return value


def _bounded_text(value: object, label: str, maximum: int) -> str:
    if type(value) is not str:
        raise GrantV5ContractError(f"{label} is invalid")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        raise GrantV5ContractError(f"{label} is invalid")
    return _secret_free(normalized, label)


def _checked_expiry(now_ms: int, lifetime_ms: int, label: str = "expiry") -> int:
    now = _bounded_int(now_ms, "monotonic_ms", 0, MAX_MONOTONIC_MS)
    lifetime = _bounded_int(lifetime_ms, "lifetime_ms", 1, MAX_SESSION_LIFETIME_MS)
    if now > MAX_MONOTONIC_MS - lifetime:
        raise GrantV5ContractError(f"{label} overflows monotonic domain")
    return now + lifetime


def _canonical(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _sha(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _expected_attestation_id(sequence: int, challenge: str) -> str:
    _bounded_int(sequence, "attestation_sequence", 1, MAX_MONOTONIC_MS)
    _digest(challenge, "challenge_digest")
    return f"att-{sequence:016x}-{challenge[:8]}"


def _canonical_percent_path(path: str, label: str) -> str:
    index = 0
    while index < len(path):
        if path[index] != "%":
            index += 1
            continue
        token = path[index : index + 3]
        if not _PERCENT.fullmatch(token):
            raise GrantV5ContractError(f"{label} URI percent encoding is invalid")
        if int(token[1:], 16) in {0x2E, 0x2F, 0x5C}:
            raise GrantV5ContractError(f"{label} URI encoded separator/dot is forbidden")
        index += 3
    return path


def _canonical_host(parsed: object, raw_authority: str, label: str) -> str:
    try:
        hostname = getattr(parsed, "hostname")
        port = getattr(parsed, "port")
    except (ValueError, UnicodeError) as exc:
        raise GrantV5ContractError(f"{label} URI authority is invalid") from exc
    if not hostname or "%" in raw_authority or "@" in raw_authority:
        raise GrantV5ContractError(f"{label} URI authority is invalid")
    if ":" in hostname:
        if not raw_authority.startswith("[") or "]" not in raw_authority or "%" in hostname:
            raise GrantV5ContractError(f"{label} IPv6 authority is invalid")
        try:
            canonical = ipaddress.IPv6Address(hostname).compressed
        except ValueError as exc:
            raise GrantV5ContractError(f"{label} IPv6 authority is invalid") from exc
        if hostname != canonical:
            raise GrantV5ContractError(f"{label} IPv6 authority is noncanonical")
        host = f"[{canonical}]"
    elif _NUMERIC_HOST.fullmatch(hostname):
        pieces = hostname.split(".")
        if len(pieces) != 4 or any(not piece.isdecimal() or (len(piece) > 1 and piece.startswith("0")) for piece in pieces):
            raise GrantV5ContractError(f"{label} alternate IPv4 form is forbidden")
        try:
            canonical = str(ipaddress.IPv4Address(hostname))
        except ValueError as exc:
            raise GrantV5ContractError(f"{label} IPv4 authority is invalid") from exc
        if hostname != canonical:
            raise GrantV5ContractError(f"{label} IPv4 authority is noncanonical")
        host = canonical
    else:
        if not hostname.isascii() or hostname != hostname.casefold() or hostname.endswith("."):
            raise GrantV5ContractError(f"{label} DNS authority is noncanonical")
        labels = hostname.split(".")
        if any(not _DNS_LABEL.fullmatch(part) for part in labels) or len(hostname) > 253:
            raise GrantV5ContractError(f"{label} DNS authority is invalid")
        host = hostname
    scheme = getattr(parsed, "scheme").casefold()
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    return host


def _canonical_windows(raw: str, label: str) -> str:
    if raw.startswith(("\\\\", "//", "\\\\?\\", "\\\\.\\")):
        raise GrantV5ContractError(f"{label} UNC/device path is forbidden")
    path = PureWindowsPath(raw)
    if not path.is_absolute() or len(path.drive) != 2:
        raise GrantV5ContractError(f"{label} Windows path is invalid")
    parts = raw.replace("/", "\\").split("\\")
    for index, part in enumerate(parts):
        if not part:
            raise GrantV5ContractError(f"{label} Windows separator alias is forbidden")
        if index == 0 and re.fullmatch(r"[A-Za-z]:", part):
            continue
        if part in {".", ".."} or ":" in part or part.endswith((".", " ")) or _WINDOWS_DEVICE.fullmatch(part):
            raise GrantV5ContractError(f"{label} Windows alias/device/ADS is forbidden")
    drive = path.drive[0].casefold() + ":"
    return drive + "/" + "/".join(parts[1:])


def _canonical_target_display(value: object, label: str = "target_display") -> str:
    try:
        if type(value) is not str:
            raise GrantV5ContractError(f"{label} is invalid")
        raw = value.strip()
        if not raw or len(raw) > MAX_TARGET_DISPLAY_LENGTH or any(ord(char) < 32 for char in raw):
            raise GrantV5ContractError(f"{label} is invalid")
        _secret_free(raw, label)
        if re.match(r"^[A-Za-z]:[\\/]", raw):
            return _secret_free(_canonical_windows(raw, label), label)
        if PurePosixPath(raw).is_absolute():
            if "\\" in raw or any(part in {".", ".."} for part in raw.split("/")):
                raise GrantV5ContractError(f"{label} POSIX alias is forbidden")
            if posixpath.normpath(raw) != raw:
                raise GrantV5ContractError(f"{label} POSIX path is noncanonical")
            return _secret_free(raw, label)
        if "\\" in raw:
            raise GrantV5ContractError(f"{label} raw URI backslash is forbidden")
        parsed = urlsplit(raw)
        if parsed.scheme:
            if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise GrantV5ContractError(f"{label} URI is invalid")
            if not raw.isascii():
                raise GrantV5ContractError(f"{label} URI must be ASCII canonical")
            host = _canonical_host(parsed, parsed.netloc, label)
            path = _canonical_percent_path(parsed.path or "/", label)
            if any(part in {".", ".."} for part in path.split("/")):
                raise GrantV5ContractError(f"{label} URI dot segment is forbidden")
            normalized = posixpath.normpath(path)
            if path.endswith("/") and normalized != "/":
                normalized += "/"
            if normalized != path:
                raise GrantV5ContractError(f"{label} URI path is noncanonical")
            canonical = urlunsplit((parsed.scheme, host, quote(path, safe="/%-._~"), "", ""))
            if canonical != raw:
                raise GrantV5ContractError(f"{label} URI is noncanonical")
            return _secret_free(canonical, label)
        return _safe_id(raw, label)
    except GrantV5ContractError:
        raise
    except (KeyError, OSError, TypeError, ValueError, UnicodeError) as exc:
        raise GrantV5ContractError(f"{label} is invalid") from exc


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
            raise GrantV5ContractError("always_explicit must be boolean")

    @property
    def key(self) -> tuple[str, str, str]:
        return self.capability, self.tool, self.operation

    def payload(self) -> dict[str, object]:
        return {"always_explicit": self.always_explicit, "capability": self.capability, "max_data_class": self.max_data_class, "operation": self.operation, "risk": self.risk, "tool": self.tool}


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
    credential_epoch: int
    vault_generation: int
    audit_healthy: bool = True
    session_active: bool = True
    kill_switch: bool = False

    def __post_init__(self) -> None:
        if self.schema_version != GRANT_SCHEMA_VERSION or self.policy_version != GRANT_POLICY_VERSION:
            raise GrantV5ContractError("unknown grant schema/policy version")
        _safe_id(self.principal_id, "principal_id")
        _safe_id(self.session_id, "session_id")
        _safe_id(self.workspace_id, "workspace_id")
        if type(self.mission_ids) is not tuple or len(self.mission_ids) > MAX_MISSIONS:
            raise GrantV5ContractError("mission collection exceeds its bound")
        missions = tuple(sorted(_safe_id(item, "mission_id") for item in self.mission_ids))
        if len(set(missions)) != len(missions):
            raise GrantV5ContractError("mission IDs are duplicated")
        object.__setattr__(self, "mission_ids", missions)
        if type(self.policies) is not tuple or not 1 <= len(self.policies) <= MAX_POLICIES or any(type(item) is not HostActionPolicy for item in self.policies):
            raise GrantV5ContractError("policy collection is invalid")
        policies = tuple(sorted(self.policies, key=lambda item: item.key))
        if len({item.key for item in policies}) != len(policies):
            raise GrantV5ContractError("host policies are duplicated")
        object.__setattr__(self, "policies", policies)
        _digest(self.audit_head, "audit_head")
        _bounded_int(self.credential_epoch, "credential_epoch", 0, MAX_MONOTONIC_MS)
        _bounded_int(self.vault_generation, "vault_generation", 0, MAX_MONOTONIC_MS)
        if any(type(getattr(self, name)) is not bool for name in ("audit_healthy", "session_active", "kill_switch")):
            raise GrantV5ContractError("host state booleans are invalid")

    def policy_for(self, capability: str, tool: str, operation: str) -> HostActionPolicy:
        values = tuple(item for item in self.policies if item.key == (capability, tool, operation))
        if len(values) != 1:
            raise GrantV5ContractError("unknown or ambiguous host policy")
        return values[0]

    def fingerprint(self) -> str:
        return _sha({"audit_head": self.audit_head, "contract": "HostSemanticState.v5", "credential_epoch": self.credential_epoch, "mission_ids": list(self.mission_ids), "policies": [item.payload() for item in self.policies], "policy_version": self.policy_version, "principal_id": self.principal_id, "schema_version": self.schema_version, "session_id": self.session_id, "vault_generation": self.vault_generation, "workspace_id": self.workspace_id})


def _copy_policy(value: object) -> HostActionPolicy:
    if type(value) is not HostActionPolicy:
        raise GrantV5ContractError("host policy concrete type is invalid")
    return HostActionPolicy(value.capability, value.tool, value.operation, value.risk, value.always_explicit, value.max_data_class)


def _copy_state(value: object) -> HostState:
    if type(value) is not HostState:
        raise GrantV5ContractError("host state concrete type is invalid")
    return HostState(value.schema_version, value.policy_version, value.principal_id, value.session_id, value.workspace_id, tuple(value.mission_ids), tuple(_copy_policy(item) for item in value.policies), value.audit_head, value.credential_epoch, value.vault_generation, value.audit_healthy, value.session_active, value.kill_switch)


@dataclass(frozen=True, slots=True)
class ActionBinding:
    target_identity: str
    target_display: str
    payload_digest: str
    payload_summary: str
    payload_rule_id: str
    egress: str
    idempotency_key: str

    def __post_init__(self) -> None:
        _digest(self.target_identity, "target_identity")
        object.__setattr__(self, "target_display", _canonical_target_display(self.target_display))
        _digest(self.payload_digest, "payload_digest")
        object.__setattr__(self, "payload_summary", _bounded_text(self.payload_summary, "payload_summary", MAX_PAYLOAD_SUMMARY_LENGTH))
        _safe_id(self.payload_rule_id, "payload_rule_id")
        _enum(self.egress, _EGRESS, "egress")
        _safe_id(self.idempotency_key, "idempotency_key")

    def payload(self) -> dict[str, str]:
        return {"egress": self.egress, "idempotency_key": self.idempotency_key, "payload_digest": self.payload_digest, "payload_rule_id": self.payload_rule_id, "payload_summary": self.payload_summary, "target_display": self.target_display, "target_identity": self.target_identity}

    def digest(self) -> str:
        return _sha({"binding": self.payload(), "contract": "ExactActionBinding.v5"})


def _copy_binding(value: object) -> ActionBinding:
    if type(value) is not ActionBinding:
        raise GrantV5ContractError("action binding concrete type is invalid")
    return ActionBinding(value.target_identity, value.target_display, value.payload_digest, value.payload_summary, value.payload_rule_id, value.egress, value.idempotency_key)


@dataclass(frozen=True, slots=True)
class ResolvedGrantScope:
    mission_id: str | None
    capability: str
    tool: str
    operation: str
    bindings: tuple[ActionBinding, ...]
    account: str
    path: str
    effect: str
    environment: str
    data_class: str
    reversible: bool
    verification_plan: str
    rollback_plan: str
    cost_currency: str
    cost_unit: str
    initial_binding_digest: str
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
        if type(self.bindings) is not tuple or not 1 <= len(self.bindings) <= MAX_BINDINGS:
            raise GrantV5ContractError("action binding collection is invalid")
        if any(type(item) is not ActionBinding for item in self.bindings):
            raise GrantV5ContractError("action binding concrete type is invalid")
        bindings = tuple(sorted((_copy_binding(item) for item in self.bindings), key=lambda item: item.digest()))
        if len({item.digest() for item in bindings}) != len(bindings):
            raise GrantV5ContractError("action bindings are duplicated")
        if sum(len(item.target_display) for item in bindings) > MAX_TOTAL_TARGET_DISPLAY_CHARS or sum(len(item.payload_summary) for item in bindings) > MAX_TOTAL_PAYLOAD_SUMMARY_CHARS:
            raise GrantV5ContractError("action binding display/summary total exceeds bound")
        object.__setattr__(self, "bindings", bindings)
        _safe_id(self.account, "account")
        object.__setattr__(self, "path", _canonical_target_display(self.path, "path"))
        object.__setattr__(self, "effect", _bounded_text(self.effect, "effect", MAX_EFFECT_LENGTH))
        _safe_id(self.environment, "environment")
        _enum(self.data_class, set(_DATA_CLASSES), "data_class")
        if type(self.reversible) is not bool:
            raise GrantV5ContractError("reversible is invalid")
        object.__setattr__(self, "verification_plan", _bounded_text(self.verification_plan, "verification_plan", MAX_PLAN_LENGTH))
        object.__setattr__(self, "rollback_plan", _bounded_text(self.rollback_plan, "rollback_plan", MAX_PLAN_LENGTH))
        if type(self.cost_currency) is not str or not _CURRENCY.fullmatch(self.cost_currency):
            raise GrantV5ContractError("cost_currency is invalid")
        _secret_free(self.cost_currency, "cost_currency")
        _slug(self.cost_unit, "cost_unit")
        _digest(self.initial_binding_digest, "initial_binding_digest")
        if self.initial_binding_digest not in {item.digest() for item in bindings}:
            raise GrantV5ContractError("initial binding is outside finite exact set")
        initial = _bounded_int(self.initial_cost_micro, "initial_cost_micro", 0, MAX_COST_MICRO)
        per_action = _bounded_int(self.max_cost_per_action_micro, "max_cost_per_action_micro", 0, MAX_COST_MICRO)
        aggregate = _bounded_int(self.max_cost_aggregate_micro, "max_cost_aggregate_micro", 0, MAX_COST_MICRO)
        if aggregate < per_action or initial > per_action or initial > aggregate:
            raise GrantV5ContractError("cost bounds are contradictory")
        _bounded_int(self.max_uses, "max_uses", 1, MAX_USES)
        delay = _bounded_int(self.not_before_delay_ms, "not_before_delay_ms", 0, MAX_SESSION_LIFETIME_MS - 1)
        lifetime = _bounded_int(self.lifetime_ms, "lifetime_ms", 1, MAX_SESSION_LIFETIME_MS)
        if delay >= lifetime:
            raise GrantV5ContractError("time bounds are contradictory")


def _copy_resolved_scope(value: object) -> ResolvedGrantScope:
    if type(value) is not ResolvedGrantScope:
        raise GrantV5ContractError("grant resolver concrete type is invalid")
    return ResolvedGrantScope(value.mission_id, value.capability, value.tool, value.operation, tuple(_copy_binding(item) for item in value.bindings), value.account, value.path, value.effect, value.environment, value.data_class, value.reversible, value.verification_plan, value.rollback_plan, value.cost_currency, value.cost_unit, value.initial_binding_digest, value.initial_cost_micro, value.max_cost_per_action_micro, value.max_cost_aggregate_micro, value.max_uses, value.not_before_delay_ms, value.lifetime_ms)


@dataclass(frozen=True, slots=True)
class ResolvedAction:
    mission_id: str | None
    capability: str
    tool: str
    operation: str
    binding: ActionBinding
    account: str
    path: str
    effect: str
    environment: str
    data_class: str
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
        if type(self.binding) is not ActionBinding:
            raise GrantV5ContractError("action binding concrete type is invalid")
        object.__setattr__(self, "binding", _copy_binding(self.binding))
        _safe_id(self.account, "account")
        object.__setattr__(self, "path", _canonical_target_display(self.path, "path"))
        object.__setattr__(self, "effect", _bounded_text(self.effect, "effect", MAX_EFFECT_LENGTH))
        _safe_id(self.environment, "environment")
        _enum(self.data_class, set(_DATA_CLASSES), "data_class")
        if type(self.reversible) is not bool:
            raise GrantV5ContractError("reversible is invalid")
        object.__setattr__(self, "verification_plan", _bounded_text(self.verification_plan, "verification_plan", MAX_PLAN_LENGTH))
        object.__setattr__(self, "rollback_plan", _bounded_text(self.rollback_plan, "rollback_plan", MAX_PLAN_LENGTH))
        if type(self.cost_currency) is not str or not _CURRENCY.fullmatch(self.cost_currency):
            raise GrantV5ContractError("cost_currency is invalid")
        _secret_free(self.cost_currency, "cost_currency")
        _slug(self.cost_unit, "cost_unit")
        _bounded_int(self.cost_micro, "cost_micro", 0, MAX_COST_MICRO)


def _copy_action(value: object) -> ResolvedAction:
    if type(value) is not ResolvedAction:
        raise GrantV5ContractError("action resolver concrete type is invalid")
    return ResolvedAction(value.mission_id, value.capability, value.tool, value.operation, _copy_binding(value.binding), value.account, value.path, value.effect, value.environment, value.data_class, value.reversible, value.verification_plan, value.rollback_plan, value.cost_currency, value.cost_unit, value.cost_micro)


@dataclass(frozen=True, slots=True)
class ResolvedOutcome:
    reservation_id: str
    status: str
    callback_approved: bool
    dispatched: bool
    receipt_verified: bool
    receipt_digest: str

    def __post_init__(self) -> None:
        _safe_id(self.reservation_id, "reservation_id")
        _enum(self.status, _OUTCOMES, "outcome_status")
        if any(type(getattr(self, name)) is not bool for name in ("callback_approved", "dispatched", "receipt_verified")):
            raise GrantV5ContractError("outcome booleans are invalid")
        _digest(self.receipt_digest, "receipt_digest")
        flags = self.callback_approved, self.dispatched, self.receipt_verified
        expected = {"verified": (True, True, True), "unverified": (True, True, False), "denied": (False, False, False), "cancelled": (False, False, False)}[self.status]
        if flags != expected:
            raise GrantV5ContractError("outcome status/flags are contradictory")


def _copy_outcome(value: object) -> ResolvedOutcome:
    if type(value) is not ResolvedOutcome:
        raise GrantV5ContractError("outcome resolver concrete type is invalid")
    return ResolvedOutcome(value.reservation_id, value.status, value.callback_approved, value.dispatched, value.receipt_verified, value.receipt_digest)


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
            raise GrantV5ContractError("approval decision is invalid")
        _safe_id(self.attestation_id, "attestation_id")
        _bounded_int(self.attestation_sequence, "attestation_sequence", 1, MAX_MONOTONIC_MS)
        _digest(self.challenge_digest, "challenge_digest")
        _digest(self.scope_digest, "scope_digest")
        _digest(self.prompt_digest, "prompt_digest")


def _copy_approval(value: object) -> HostApprovalResponse:
    if type(value) is not HostApprovalResponse:
        raise GrantV5ContractError("approval response concrete type is invalid")
    return HostApprovalResponse(value.approved, value.attestation_id, value.attestation_sequence, value.challenge_digest, value.scope_digest, value.prompt_digest)


@dataclass(frozen=True, slots=True)
class HostServices:
    trust_root_id: str
    resolve_grant: Callable[[str], ResolvedGrantScope]
    resolve_action: Callable[[str], ResolvedAction]
    resolve_outcome: Callable[[str], ResolvedOutcome]
    approve: Callable[["ApprovalPrompt"], HostApprovalResponse]
    state: Callable[[], HostState]
    monotonic_ms: Callable[[], int]

    def __post_init__(self) -> None:
        _safe_id(self.trust_root_id, "trust_root_id")
        for name in ("resolve_grant", "resolve_action", "resolve_outcome", "approve", "state", "monotonic_ms"):
            if not callable(getattr(self, name)):
                raise GrantV5ContractError(f"host service {name} is not callable")


@dataclass(frozen=True, slots=True)
class GrantScope:
    state_fingerprint: str
    trust_root_id: str
    principal_id: str
    session_id: str
    workspace_id: str
    mission_id: str | None
    capability: str
    tool: str
    operation: str
    bindings: tuple[ActionBinding, ...]
    account: str
    path: str
    effect: str
    environment: str
    data_class: str
    risk: str
    reversible: bool
    verification_plan: str
    rollback_plan: str
    cost_currency: str
    cost_unit: str
    initial_binding_digest: str
    initial_cost_micro: int
    max_cost_per_action_micro: int
    max_cost_aggregate_micro: int
    max_uses: int
    issued_at_ms: int
    not_before_ms: int
    expires_at_ms: int


def _scope_payload(scope: GrantScope) -> dict[str, object]:
    return {"account": scope.account, "bindings": [item.payload() for item in scope.bindings], "capability": scope.capability, "contract": "SessionGrantScope.v5", "cost_currency": scope.cost_currency, "cost_unit": scope.cost_unit, "data_class": scope.data_class, "effect": scope.effect, "environment": scope.environment, "expires_at_ms": scope.expires_at_ms, "initial_binding_digest": scope.initial_binding_digest, "initial_cost_micro": scope.initial_cost_micro, "issued_at_ms": scope.issued_at_ms, "max_cost_aggregate_micro": scope.max_cost_aggregate_micro, "max_cost_per_action_micro": scope.max_cost_per_action_micro, "max_uses": scope.max_uses, "mission_id": scope.mission_id, "not_before_ms": scope.not_before_ms, "operation": scope.operation, "path": scope.path, "principal_id": scope.principal_id, "reversible": scope.reversible, "risk": scope.risk, "rollback_plan": scope.rollback_plan, "session_id": scope.session_id, "state_fingerprint": scope.state_fingerprint, "tool": scope.tool, "trust_root_id": scope.trust_root_id, "verification_plan": scope.verification_plan, "workspace_id": scope.workspace_id}


def canonical_scope_digest(scope: GrantScope) -> str:
    return _sha(_scope_payload(scope))


def _prompt_digest(scope_digest: str, challenge: str, summary: str) -> str:
    return _sha({"challenge_digest": challenge, "contract": "ApprovalPrompt.v5", "human_summary": summary, "scope_digest": scope_digest})


@dataclass(frozen=True, slots=True)
class ApprovalPrompt:
    scope: GrantScope
    scope_digest: str
    challenge_digest: str
    human_summary: str
    prompt_digest: str


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


@dataclass(frozen=True, slots=True)
class ActionReservation:
    reservation_id: str
    grant_id: str
    binding_digest: str
    action_audit_digest: str
    cost_micro: int
    state_fingerprint: str
    created_at_ms: int
    expires_at_ms: int
    sequence: int


@dataclass(frozen=True, slots=True)
class OutcomeRecord:
    reservation_id: str
    status: str
    callback_approved: bool
    dispatched: bool
    receipt_verified: bool
    receipt_digest: str
    sequence: int


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


@dataclass(frozen=True, slots=True)
class ShadowCommitDecision:
    committed: bool
    reason: str
    reservation_id: str
    grant_id: str
    receipt_digest: str
    callback_required: bool = field(init=False, default=True)
    authority_granted: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        if type(self.committed) is not bool:
            raise GrantV5ContractError("commit result is invalid")
        _enum(self.reason, _COMMIT_REASONS, "commit_reason")
        _safe_id(self.reservation_id, "reservation_id")
        _safe_id(self.grant_id, "grant_id")
        _digest(self.receipt_digest, "receipt_digest")


class SessionGrantShadowStore:
    def __init__(self, services: HostServices) -> None:
        if type(services) is not HostServices:
            raise GrantV5ContractError("HostServices concrete type is required")
        self._services = services
        self._grants: dict[str, SessionGrant] = {}
        self._approvals: set[str] = set()
        self._revocations: dict[str, GrantRevocation] = {}
        self._reservations: dict[str, ActionReservation] = {}
        self._uses: dict[str, int] = {}
        self._costs: dict[str, int] = {}
        self._receipts: dict[str, tuple[int, str]] = {}
        self._outcome_records: dict[str, OutcomeRecord] = {}
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

    def _record_host_failure(self) -> None:
        with self._lock:
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "semantic-state-changed", self._clock_high_water)
            self._reservations.clear()
            self._fail_closed = True
            self._generation += 1

    def _snapshot_outside_lock(self) -> tuple[int, HostState]:
        try:
            raw_now = self._services.monotonic_ms()
            now = _bounded_int(raw_now, "monotonic_ms", 0, MAX_MONOTONIC_MS)
            state = _copy_state(self._services.state())
            return now, state
        except GrantV5ContractError:
            self._record_host_failure()
            raise
        except Exception as exc:
            self._record_host_failure()
            raise GrantV5ContractError("host snapshot callback failed") from exc

    def _call_resolver(self, name: str, reference: str) -> object:
        try:
            return getattr(self._services, name)(reference)
        except GrantV5ContractError:
            self._record_host_failure()
            raise
        except Exception as exc:
            self._record_host_failure()
            raise GrantV5ContractError(f"host {name} callback failed") from exc

    def _copy_boundary(self, copier: Callable[[object], object], value: object) -> object:
        try:
            return copier(value)
        except GrantV5ContractError:
            self._record_host_failure()
            raise
        except Exception as exc:
            self._record_host_failure()
            raise GrantV5ContractError("host boundary copy failed") from exc

    def _accept_snapshot_locked(self, raw_now: int, state: HostState) -> int:
        now = max(raw_now, self._clock_high_water)
        self._clock_high_water = now
        self._invalidate_locked(state, now)
        self._expire_reservations_locked(now)
        return now

    def _stop_reason_locked(self) -> str | None:
        if self._fail_closed or self._audit_unhealthy:
            return "audit-unhealthy"
        if self._killed:
            return "kill-switch"
        if self._session_ended:
            return "session-ended"
        return None

    def _revoke_locked(self, grant_id: str, reason: str, now: int) -> None:
        if grant_id in self._revocations:
            return
        if len(self._revocations) >= MAX_REVOCATIONS:
            self._fail_closed = True
            self._reservations.clear()
            self._generation += 1
            return
        self._sequence += 1
        self._generation += 1
        self._revocations[grant_id] = GrantRevocation(grant_id, reason, now, self._sequence)
        self._clear_grant_reservations_locked(grant_id)

    def _clear_grant_reservations_locked(self, grant_id: str) -> None:
        for reservation_id in tuple(self._reservations):
            if self._reservations[reservation_id].grant_id == grant_id:
                self._reservations.pop(reservation_id, None)

    def _expire_reservations_locked(self, now: int) -> None:
        for reservation_id, item in tuple(self._reservations.items()):
            if now >= item.expires_at_ms:
                self._reservations.pop(reservation_id, None)

    def _attestation_digest(self, grant: SessionGrant) -> str:
        return _sha({"approval_id": grant.approval_id, "approval_sequence": grant.approval_sequence, "challenge_digest": grant.challenge_digest, "contract": "HostApprovalAttestation.v5", "prompt_digest": grant.prompt_digest, "scope_digest": grant.scope_digest, "trust_root_id": self._services.trust_root_id})

    def _invalidate_locked(self, state: HostState, now: int) -> None:
        if self._fail_closed:
            return
        terminal: tuple[bool, str] | None = None
        if self._killed or state.kill_switch:
            self._killed = True
            terminal = True, "kill-switch"
        elif self._audit_unhealthy or not state.audit_healthy:
            self._audit_unhealthy = True
            terminal = True, "audit-unhealthy"
        elif self._session_ended or not state.session_active:
            self._session_ended = True
            terminal = True, "session-ended"
        if terminal:
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, terminal[1], now)
            self._reservations.clear()
            return
        fingerprint = state.fingerprint()
        for grant in tuple(self._grants.values()):
            if grant.grant_id in self._revocations:
                continue
            if now >= grant.scope.expires_at_ms:
                self._revoke_locked(grant.grant_id, "expired", now)
            elif not hmac.compare_digest(grant.scope.state_fingerprint, fingerprint) or not hmac.compare_digest(grant.attestation_digest, self._attestation_digest(grant)):
                self._revoke_locked(grant.grant_id, "semantic-state-changed", now)

    def _pre_snapshot(self) -> tuple[int, HostState, int, str]:
        with self._lock:
            if self._stop_reason_locked() is not None:
                raise GrantV5Denied("host session is not healthy")
        raw_now, state = self._snapshot_outside_lock()
        with self._lock:
            now = self._accept_snapshot_locked(raw_now, state)
            if self._stop_reason_locked() is not None:
                raise GrantV5Denied("host session is not healthy")
            return now, state, self._generation, state.fingerprint()

    def _post_snapshot(self, generation: int, fingerprint: str) -> tuple[int, HostState, int]:
        raw_now, state = self._snapshot_outside_lock()
        with self._lock:
            now = self._accept_snapshot_locked(raw_now, state)
            if self._stop_reason_locked() is not None or generation != self._generation or not hmac.compare_digest(fingerprint, state.fingerprint()):
                raise GrantV5Denied("host state changed during resolver callback")
            return now, state, self._generation

    @staticmethod
    def _scope_from_resolved(resolved: ResolvedGrantScope, state: HostState, trust_root_id: str, now: int) -> GrantScope:
        if resolved.mission_id is not None and resolved.mission_id not in state.mission_ids:
            raise GrantV5ContractError("grant mission is not host-authorized")
        policy = state.policy_for(resolved.capability, resolved.tool, resolved.operation)
        if policy.always_explicit or policy.risk in {"high", "critical"}:
            raise GrantV5Denied("always-explicit/high-risk action cannot be granted")
        if _DATA_CLASSES[resolved.data_class] > _DATA_CLASSES[policy.max_data_class]:
            raise GrantV5ContractError("grant data class exceeds host policy")
        expires = _checked_expiry(now, resolved.lifetime_ms)
        not_before = now + resolved.not_before_delay_ms
        return GrantScope(state.fingerprint(), trust_root_id, state.principal_id, state.session_id, state.workspace_id, resolved.mission_id, resolved.capability, resolved.tool, resolved.operation, resolved.bindings, resolved.account, resolved.path, resolved.effect, resolved.environment, resolved.data_class, policy.risk, resolved.reversible, resolved.verification_plan, resolved.rollback_plan, resolved.cost_currency, resolved.cost_unit, resolved.initial_binding_digest, resolved.initial_cost_micro, resolved.max_cost_per_action_micro, resolved.max_cost_aggregate_micro, resolved.max_uses, now, not_before, expires)

    @staticmethod
    def _human_summary(scope: GrantScope) -> str:
        pairs = "; ".join(f"target {item.target_display} identity {item.target_identity} + payload {item.payload_digest} ({item.payload_summary}; rule {item.payload_rule_id}; egress {item.egress}; idempotency {item.idempotency_key})" for item in scope.bindings)
        summary = f"Principal {scope.principal_id}; session {scope.session_id}; workspace {scope.workspace_id}; mission {scope.mission_id or 'none'}; action {scope.capability}/{scope.tool}/{scope.operation}; exact action pairs [{pairs}]; account {scope.account}; path {scope.path}; environment {scope.environment}; effect {scope.effect}; data {scope.data_class}; risk {scope.risk}; reversible {scope.reversible}; verification {scope.verification_plan}; rollback {scope.rollback_plan}; cost {scope.cost_currency} {scope.cost_unit}, initial {scope.initial_cost_micro}, per-action max {scope.max_cost_per_action_micro}, aggregate max {scope.max_cost_aggregate_micro}; uses {scope.max_uses}; valid {scope.not_before_ms} through {scope.expires_at_ms}."
        return _bounded_text(summary, "human_summary", MAX_PROMPT_LENGTH)

    def _cleanup_grant_capacity_locked(self) -> None:
        while len(self._grants) >= MAX_GRANTS:
            terminal = sorted((self._revocations[grant_id].sequence, grant.sequence, grant_id) for grant_id, grant in self._grants.items() if grant_id in self._revocations)
            if not terminal:
                raise GrantV5CapacityError("active grant capacity is exhausted")
            _rev_seq, _grant_seq, grant_id = terminal[0]
            grant = self._grants.pop(grant_id)
            self._revocations.pop(grant_id, None)
            self._uses.pop(grant_id, None)
            self._costs.pop(grant_id, None)
            self._approvals.discard(grant.approval_id)
        if len(self._approvals) >= MAX_APPROVALS:
            raise GrantV5CapacityError("approval capacity is exhausted")

    def request_session_grant(self, invocation_ref: str) -> str:
        reference = _safe_id(invocation_ref, "invocation_ref")
        if not grant_evaluator_enabled():
            raise GrantV5Disabled("grant evaluator is disabled")
        _first_now, _first_state, generation, fingerprint = self._pre_snapshot()
        resolved = self._copy_boundary(_copy_resolved_scope, self._call_resolver("resolve_grant", reference))
        assert isinstance(resolved, ResolvedGrantScope)
        now, state, generation = self._post_snapshot(generation, fingerprint)
        with self._lock:
            self._cleanup_grant_capacity_locked()
            scope = self._scope_from_resolved(resolved, state, self._services.trust_root_id, now)
            scope_digest = canonical_scope_digest(scope)
            challenge = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
            summary = self._human_summary(scope)
            prompt_digest = _prompt_digest(scope_digest, challenge, summary)
            prompt = ApprovalPrompt(scope, scope_digest, challenge, summary, prompt_digest)
            approval_generation = generation
            approval_fingerprint = state.fingerprint()
        try:
            response = _copy_approval(self._services.approve(prompt))
        except GrantV5ContractError:
            self._record_host_failure()
            raise
        except Exception as exc:
            self._record_host_failure()
            raise GrantV5ContractError("host approval callback failed") from exc
        raw_issue_now, issue_state = self._snapshot_outside_lock()
        with self._lock:
            issue_now = self._accept_snapshot_locked(raw_issue_now, issue_state)
            if self._stop_reason_locked() is not None or approval_generation != self._generation or not hmac.compare_digest(approval_fingerprint, issue_state.fingerprint()) or issue_now >= scope.expires_at_ms:
                raise GrantV5Denied("host state changed during approval")
            if not response.approved:
                raise GrantV5Denied("trusted host denied exact scope")
            if not all(hmac.compare_digest(left, right) for left, right in ((response.challenge_digest, challenge), (response.scope_digest, scope_digest), (response.prompt_digest, prompt_digest))):
                raise GrantV5Denied("approval response does not bind exact prompt")
            if not hmac.compare_digest(response.attestation_id, _expected_attestation_id(response.attestation_sequence, challenge)):
                raise GrantV5Denied("approval ID is not structurally bound")
            if response.attestation_sequence <= self._last_attestation_sequence or response.attestation_id in self._approvals:
                raise GrantV5Denied("approval attestation was consumed")
            self._cleanup_grant_capacity_locked()
            self._sequence += 1
            grant_id = f"grant-{self._sequence:08d}"
            attestation = _sha({"approval_id": response.attestation_id, "approval_sequence": response.attestation_sequence, "challenge_digest": challenge, "contract": "HostApprovalAttestation.v5", "prompt_digest": prompt_digest, "scope_digest": scope_digest, "trust_root_id": self._services.trust_root_id})
            self._grants[grant_id] = SessionGrant(grant_id, response.attestation_id, response.attestation_sequence, challenge, prompt_digest, attestation, scope, scope_digest, self._sequence)
            self._approvals.add(response.attestation_id)
            self._last_attestation_sequence = response.attestation_sequence
            self._uses[grant_id] = 0
            self._costs[grant_id] = 0
            return grant_id

    @staticmethod
    def _scope_matches(scope: GrantScope, action: ResolvedAction, state: HostState, now: int) -> bool:
        if not scope.not_before_ms <= now < scope.expires_at_ms or not hmac.compare_digest(scope.state_fingerprint, state.fingerprint()):
            return False
        policy = state.policy_for(action.capability, action.tool, action.operation)
        exact = ((scope.mission_id or "", action.mission_id or ""), (scope.capability, action.capability), (scope.tool, action.tool), (scope.operation, action.operation), (scope.account, action.account), (scope.path, action.path), (scope.effect, action.effect), (scope.environment, action.environment), (scope.data_class, action.data_class), (scope.risk, policy.risk), (scope.verification_plan, action.verification_plan), (scope.rollback_plan, action.rollback_plan), (scope.cost_currency, action.cost_currency), (scope.cost_unit, action.cost_unit))
        return all(hmac.compare_digest(a, b) for a, b in exact) and scope.reversible is action.reversible and sum(hmac.compare_digest(item.digest(), action.binding.digest()) for item in scope.bindings) == 1

    def _action_digest(self, reference: str, action: ResolvedAction, state: HostState, now: int, sequence: int, scope_digest: str) -> str:
        try:
            risk = state.policy_for(action.capability, action.tool, action.operation).risk
        except GrantV5ContractError:
            risk = "unknown"
        return _sha({"action_binding": action.binding.payload(), "action_sequence": sequence, "capability": action.capability, "contract": "ActionAudit.v5", "cost_currency": action.cost_currency, "cost_micro": action.cost_micro, "cost_unit": action.cost_unit, "data_class": action.data_class, "effect": action.effect, "environment": action.environment, "invocation_ref_sha256": hashlib.sha256(reference.encode()).hexdigest(), "mission_id": action.mission_id, "observed_at_ms": now, "operation": action.operation, "path": action.path, "reversible": action.reversible, "risk": risk, "rollback_plan": action.rollback_plan, "scope_digest": scope_digest, "state_fingerprint": state.fingerprint(), "tool": action.tool, "verification_plan": action.verification_plan})

    def _resolve_action(self, reference: str) -> tuple[ResolvedAction, int, HostState]:
        _first_now, _first_state, generation, fingerprint = self._pre_snapshot()
        action = self._copy_boundary(_copy_action, self._call_resolver("resolve_action", reference))
        assert isinstance(action, ResolvedAction)
        now, state, _generation = self._post_snapshot(generation, fingerprint)
        return action, now, state

    def _decision_locked(self, reference: str, action: ResolvedAction, now: int, state: HostState) -> tuple[ShadowGrantDecision, SessionGrant | None]:
        self._action_sequence += 1
        sequence = self._action_sequence
        zero = "0" * 64
        try:
            policy = state.policy_for(action.capability, action.tool, action.operation)
        except GrantV5ContractError:
            digest = self._action_digest(reference, action, state, now, sequence, zero)
            return ShadowGrantDecision("would-deny", "out-of-scope", None, zero, digest), None
        if policy.always_explicit or policy.risk in {"high", "critical"}:
            digest = self._action_digest(reference, action, state, now, sequence, zero)
            return ShadowGrantDecision("would-deny", "out-of-scope", None, zero, digest), None
        matches = tuple(grant for grant in self._grants.values() if grant.grant_id not in self._revocations and self._scope_matches(grant.scope, action, state, now))
        if len(matches) != 1:
            reason = "ambiguous-grant" if len(matches) > 1 else "no-exact-grant"
            digest = self._action_digest(reference, action, state, now, sequence, zero)
            return ShadowGrantDecision("would-deny", reason, None, zero, digest), None
        grant = matches[0]
        digest = self._action_digest(reference, action, state, now, sequence, grant.scope_digest)
        used = self._uses[grant.grant_id]
        spent = self._costs[grant.grant_id]
        if used >= grant.scope.max_uses:
            return ShadowGrantDecision("would-deny", "out-of-scope", grant.grant_id, grant.scope_digest, digest), grant
        if action.cost_micro > grant.scope.max_cost_per_action_micro:
            return ShadowGrantDecision("would-deny", "per-action-cost", grant.grant_id, grant.scope_digest, digest), grant
        if spent + action.cost_micro > grant.scope.max_cost_aggregate_micro:
            return ShadowGrantDecision("would-deny", "aggregate-cost", grant.grant_id, grant.scope_digest, digest), grant
        return ShadowGrantDecision("would-allow", "exact-session-grant", grant.grant_id, grant.scope_digest, digest), grant

    def evaluate(self, invocation_ref: str) -> ShadowGrantDecision:
        reference = _safe_id(invocation_ref, "invocation_ref")
        if not grant_evaluator_enabled():
            digest = _sha({"contract": "DisabledGrantEvaluation.v5", "invocation_ref": reference})
            return ShadowGrantDecision("disabled", "feature-flag-off", None, "0" * 64, digest)
        action, now, state = self._resolve_action(reference)
        with self._lock:
            stopped = self._stop_reason_locked()
            if stopped is not None:
                self._action_sequence += 1
                digest = _sha({"action_sequence": self._action_sequence, "contract": "StoppedGrantEvaluation.v5", "reason": stopped})
                return ShadowGrantDecision("would-deny", stopped, None, "0" * 64, digest)
            decision, _grant = self._decision_locked(reference, action, now, state)
            return decision

    def reserve(self, invocation_ref: str) -> str:
        reference = _safe_id(invocation_ref, "invocation_ref")
        if not grant_evaluator_enabled():
            raise GrantV5Disabled("grant evaluator is disabled")
        action, now, state = self._resolve_action(reference)
        with self._lock:
            if self._stop_reason_locked() is not None:
                raise GrantV5Denied("host session is not healthy")
            decision, grant = self._decision_locked(reference, action, now, state)
            if decision.outcome != "would-allow" or grant is None:
                raise GrantV5Denied(decision.reason)
            if len(self._reservations) >= MAX_RESERVATIONS:
                raise GrantV5CapacityError("reservation capacity is exhausted")
            pending = tuple(item for item in self._reservations.values() if item.grant_id == grant.grant_id)
            if self._uses[grant.grant_id] + len(pending) >= grant.scope.max_uses:
                raise GrantV5Denied("reserved use capacity is exhausted")
            if self._costs[grant.grant_id] + sum(item.cost_micro for item in pending) + action.cost_micro > grant.scope.max_cost_aggregate_micro:
                raise GrantV5Denied("reserved cost capacity is exhausted")
            lifetime = min(MAX_RESERVATION_LIFETIME_MS, grant.scope.expires_at_ms - now)
            expires = _checked_expiry(now, lifetime, "reservation expiry")
            self._sequence += 1
            reservation_id = f"reservation-{self._sequence:08d}"
            _safe_id(reservation_id, "reservation_id")
            self._reservations[reservation_id] = ActionReservation(reservation_id, grant.grant_id, action.binding.digest(), decision.action_audit_digest, action.cost_micro, state.fingerprint(), now, expires, self._sequence)
            return reservation_id

    def record_outcome(self, outcome_ref: str) -> ShadowCommitDecision:
        reference = _safe_id(outcome_ref, "outcome_ref")
        if not grant_evaluator_enabled():
            raise GrantV5Disabled("grant evaluator is disabled")
        _first_now, _first_state, generation, fingerprint = self._pre_snapshot()
        outcome = self._copy_boundary(_copy_outcome, self._call_resolver("resolve_outcome", reference))
        assert isinstance(outcome, ResolvedOutcome)
        now, state, _generation = self._post_snapshot(generation, fingerprint)
        with self._lock:
            reservation = self._reservations.get(outcome.reservation_id)
            if reservation is None:
                raise GrantV5Denied("unknown, expired, or cleared reservation")
            grant = self._grants.get(reservation.grant_id)
            if grant is None or grant.grant_id in self._revocations or not hmac.compare_digest(reservation.state_fingerprint, state.fingerprint()):
                self._reservations.pop(reservation.reservation_id, None)
                raise GrantV5Denied("reservation is no longer valid")
            self._reservations.pop(reservation.reservation_id, None)
            self._sequence += 1
            self._outcome_records[reservation.reservation_id] = OutcomeRecord(
                reservation.reservation_id,
                outcome.status,
                outcome.callback_approved,
                outcome.dispatched,
                outcome.receipt_verified,
                outcome.receipt_digest,
                self._sequence,
            )
            if len(self._outcome_records) > MAX_OUTCOMES:
                oldest_outcome = min(
                    self._outcome_records,
                    key=lambda item: self._outcome_records[item].sequence,
                )
                self._outcome_records.pop(oldest_outcome, None)
            if outcome.status != "verified":
                return ShadowCommitDecision(False, outcome.status, reservation.reservation_id, grant.grant_id, outcome.receipt_digest)
            used = self._uses[grant.grant_id]
            spent = self._costs[grant.grant_id]
            if used >= grant.scope.max_uses or spent + reservation.cost_micro > grant.scope.max_cost_aggregate_micro:
                raise GrantV5Denied("committed limit changed before receipt")
            used += 1
            spent += reservation.cost_micro
            self._uses[grant.grant_id] = used
            self._costs[grant.grant_id] = spent
            self._receipts[reservation.reservation_id] = self._sequence, outcome.receipt_digest
            if len(self._receipts) > MAX_RECEIPTS:
                oldest = min(self._receipts, key=lambda item: self._receipts[item][0])
                self._receipts.pop(oldest, None)
            if used >= grant.scope.max_uses:
                self._revoke_locked(grant.grant_id, "use-exhausted", now)
            elif grant.scope.max_cost_aggregate_micro > 0 and spent >= grant.scope.max_cost_aggregate_micro:
                self._revoke_locked(grant.grant_id, "aggregate-exhausted", now)
            return ShadowCommitDecision(True, "verified-commit", reservation.reservation_id, grant.grant_id, outcome.receipt_digest)

    def revoke(self, grant_id: str) -> None:
        identifier = _safe_id(grant_id, "grant_id")
        with self._lock:
            self._generation += 1
            if identifier not in self._grants:
                raise GrantV5ContractError("unknown grant_id")
            self._revoke_locked(identifier, "owner-revoke", self._clock_high_water)

    def kill(self) -> None:
        with self._lock:
            self._killed = True
            self._generation += 1
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "kill-switch", self._clock_high_water)
            self._reservations.clear()

    def mark_audit_unhealthy(self) -> None:
        with self._lock:
            self._audit_unhealthy = True
            self._generation += 1
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "audit-unhealthy", self._clock_high_water)
            self._reservations.clear()

    def end_session(self) -> None:
        with self._lock:
            self._session_ended = True
            self._generation += 1
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "session-ended", self._clock_high_water)
            self._reservations.clear()

    def snapshot_counts(self) -> dict[str, int]:
        with self._lock:
            return {"approvals": len(self._approvals), "grants": len(self._grants), "outcomes": len(self._outcome_records), "receipts": len(self._receipts), "reservations": len(self._reservations), "revocations": len(self._revocations)}


__all__ = [name for name in tuple(globals()) if name.startswith("MAX_")] + [
    "GRANT_EVALUATOR_FLAG", "GRANT_POLICY_VERSION", "GRANT_SCHEMA_VERSION",
    "ActionBinding", "ApprovalPrompt", "GrantV5CapacityError", "GrantV5ContractError",
    "GrantV5Denied", "GrantV5Disabled", "HostActionPolicy", "HostApprovalResponse",
    "HostServices", "HostState", "ResolvedAction", "ResolvedGrantScope", "ResolvedOutcome",
    "SessionGrantShadowStore", "ShadowCommitDecision", "ShadowGrantDecision",
    "canonical_scope_digest", "grant_evaluator_enabled",
]
