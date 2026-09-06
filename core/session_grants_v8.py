"""Phase 5.1 R8: exact-action, two-phase session-grant shadow evaluator.

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
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath, PureWindowsPath
from urllib.parse import quote, urlsplit, urlunsplit

from memory.store import contains_secret


GRANT_EVALUATOR_FLAG = "ONYX_GRANT_EVALUATOR"
GRANT_SCHEMA_VERSION = 7
GRANT_POLICY_VERSION = "onyx-approval-v8"
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
MAX_LEDGER_IDENTITIES = 2_048
MAX_UNCERTAIN_RECORDS = 2_048
MAX_RECONCILIATIONS = 1_024

_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_SLUG = re.compile(r"[a-z][a-z0-9-]{1,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_NUMERIC_HOST = re.compile(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*\Z", re.I)
_PERCENT = re.compile(r"%[0-9A-Fa-f]{2}")
_UNRESERVED = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_RESERVED_DIGESTS = frozenset({"0" * 64, "f" * 64})
_WINDOWS_DEVICE = re.compile(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?\Z", re.I)
_TOKEN_LIKE = re.compile(r"[A-Za-z0-9]{32,}\Z")
_HEX_LIKE = re.compile(r"[0-9a-fA-F]{16,}\Z")
_RISKS = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_DATA_CLASSES = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
_EGRESS = frozenset({"none", "local-only", "named-account", "public"})
_OUTCOMES = frozenset({"verified-effect", "dispatch-attempted", "definitive-no-effect", "cancelled-before-dispatch"})
_LEDGER_STATES = frozenset({"pending_before_dispatch", "uncertain_needs_reconciliation", "consumed_verified", "definitive_no_effect", "cancelled_before_dispatch"})
_RECONCILIATION_OUTCOMES = frozenset({"confirmed-effect", "confirmed-no-effect", "still-uncertain"})
_DECISION_REASONS = frozenset(
    {
        "aggregate-cost", "ambiguous-grant", "audit-unhealthy", "exact-session-grant",
        "feature-flag-off", "kill-switch", "no-exact-grant", "out-of-scope",
        "idempotency-action-mismatch", "idempotency-consumed", "idempotency-pending", "idempotency-uncertain", "per-action-cost",
        "reservation-capacity", "session-ended",
    }
)
_COMMIT_REASONS = frozenset({"cancelled-before-dispatch", "definitive-no-effect", "uncertain-needs-reconciliation", "verified-commit"})
_REVOCATION_REASONS = frozenset(
    {"aggregate-exhausted", "audit-unhealthy", "expired", "kill-switch", "owner-revoke", "semantic-state-changed", "session-ended", "use-exhausted"}
)


class GrantV8Error(RuntimeError):
    pass


class GrantV8ContractError(ValueError):
    pass


class GrantV8Disabled(GrantV8Error):
    pass


class GrantV8Denied(GrantV8Error):
    pass


class GrantV8CapacityError(GrantV8Error):
    pass


def grant_evaluator_enabled(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return source.get(GRANT_EVALUATOR_FLAG, "").strip().casefold() in {"1", "true"}


def _secret_free(value: str, label: str) -> str:
    if contains_secret(value):
        raise GrantV8ContractError(f"{label} contains secret-shaped material")
    return value


def _safe_id(value: object, label: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise GrantV8ContractError(f"{label} is invalid")
    if len(value) >= 32 or _TOKEN_LIKE.fullmatch(value) or _HEX_LIKE.fullmatch(value):
        raise GrantV8ContractError(f"{label} is token-like")
    return _secret_free(value, label)


def _slug(value: object, label: str) -> str:
    if type(value) is not str or not _SLUG.fullmatch(value):
        raise GrantV8ContractError(f"{label} is invalid")
    if len(value) >= 32 or _TOKEN_LIKE.fullmatch(value) or _HEX_LIKE.fullmatch(value):
        raise GrantV8ContractError(f"{label} is token-like")
    return _secret_free(value, label)


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise GrantV8ContractError(f"{label} must be lowercase SHA-256")
    if value in _RESERVED_DIGESTS:
        raise GrantV8ContractError(f"{label} uses a reserved digest")
    return _secret_free(value, label)


def _sentinel_digest(value: object, label: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise GrantV8ContractError(f"{label} must be lowercase SHA-256")
    return value


def _enum(value: object, allowed: set[str] | frozenset[str], label: str) -> str:
    if type(value) is not str or value not in allowed:
        raise GrantV8ContractError(f"{label} is invalid")
    return _secret_free(value, label)


def _bounded_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise GrantV8ContractError(f"{label} is out of bounds")
    return value


def _bounded_text(value: object, label: str, maximum: int) -> str:
    if type(value) is not str:
        raise GrantV8ContractError(f"{label} is invalid")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        raise GrantV8ContractError(f"{label} is invalid")
    return _secret_free(normalized, label)


def _checked_expiry(now_ms: int, lifetime_ms: int, label: str = "expiry") -> int:
    now = _bounded_int(now_ms, "monotonic_ms", 0, MAX_MONOTONIC_MS)
    lifetime = _bounded_int(lifetime_ms, "lifetime_ms", 1, MAX_SESSION_LIFETIME_MS)
    if now > MAX_MONOTONIC_MS - lifetime:
        raise GrantV8ContractError(f"{label} overflows monotonic domain")
    return now + lifetime


def _canonical(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _sha(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _expected_attestation_id(sequence: int, challenge: str) -> str:
    _bounded_int(sequence, "attestation_sequence", 1, MAX_MONOTONIC_MS)
    _digest(challenge, "challenge_digest")
    return f"att-{sequence:016x}-{challenge[:8]}"


def _expected_receipt_id(sequence: int, challenge: str) -> str:
    _bounded_int(sequence, "receipt_sequence", 1, MAX_MONOTONIC_MS)
    _digest(challenge, "receipt_challenge")
    return f"receipt-{sequence:016x}-{challenge[:8]}"


def _expected_provider_receipt_id(sequence: int, result_digest: str) -> str:
    _bounded_int(sequence, "receipt_sequence", 1, MAX_MONOTONIC_MS)
    _digest(result_digest, "result_digest")
    return f"provider-{sequence:016x}-{result_digest[:8]}"


def _expected_reconciliation_id(sequence: int, challenge: str) -> str:
    _bounded_int(sequence, "reconciliation_sequence", 1, MAX_MONOTONIC_MS)
    _digest(challenge, "reconciliation_challenge")
    return f"reconcile-{sequence:016x}-{challenge[:8]}"


def _canonical_percent_path(path: str, label: str) -> str:
    pieces: list[str] = []
    index = 0
    while index < len(path):
        if path[index] != "%":
            pieces.append(path[index])
            index += 1
            continue
        token = path[index : index + 3]
        if not _PERCENT.fullmatch(token):
            raise GrantV8ContractError(f"{label} URI percent encoding is invalid")
        octet = int(token[1:], 16)
        if octet in {0x2E, 0x2F, 0x5C}:
            raise GrantV8ContractError(f"{label} URI encoded separator/dot is forbidden")
        if octet in _UNRESERVED:
            raise GrantV8ContractError(f"{label} URI encoded unreserved character is forbidden")
        pieces.append(f"%{octet:02X}")
        index += 3
    return "".join(pieces)


def _canonical_host(parsed: object, raw_authority: str, label: str) -> str:
    try:
        hostname = getattr(parsed, "hostname")
        port = getattr(parsed, "port")
    except (ValueError, UnicodeError) as exc:
        raise GrantV8ContractError(f"{label} URI authority is invalid") from exc
    if not hostname or "%" in raw_authority or "@" in raw_authority:
        raise GrantV8ContractError(f"{label} URI authority is invalid")
    if ":" in hostname:
        if not raw_authority.startswith("[") or "]" not in raw_authority or "%" in hostname:
            raise GrantV8ContractError(f"{label} IPv6 authority is invalid")
        try:
            canonical = ipaddress.IPv6Address(hostname).compressed
        except ValueError as exc:
            raise GrantV8ContractError(f"{label} IPv6 authority is invalid") from exc
        if hostname != canonical:
            raise GrantV8ContractError(f"{label} IPv6 authority is noncanonical")
        host = f"[{canonical}]"
    elif _NUMERIC_HOST.fullmatch(hostname):
        pieces = hostname.split(".")
        if len(pieces) != 4 or any(not piece.isdecimal() or (len(piece) > 1 and piece.startswith("0")) for piece in pieces):
            raise GrantV8ContractError(f"{label} alternate IPv4 form is forbidden")
        try:
            canonical = str(ipaddress.IPv4Address(hostname))
        except ValueError as exc:
            raise GrantV8ContractError(f"{label} IPv4 authority is invalid") from exc
        if hostname != canonical:
            raise GrantV8ContractError(f"{label} IPv4 authority is noncanonical")
        host = canonical
    else:
        if not hostname.isascii() or hostname != hostname.casefold() or hostname.endswith("."):
            raise GrantV8ContractError(f"{label} DNS authority is noncanonical")
        labels = hostname.split(".")
        if any(not _DNS_LABEL.fullmatch(part) for part in labels) or len(hostname) > 253:
            raise GrantV8ContractError(f"{label} DNS authority is invalid")
        host = hostname
    scheme = getattr(parsed, "scheme").casefold()
    if port is not None and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        host = f"{host}:{port}"
    return host


def _canonical_windows(raw: str, label: str) -> str:
    if raw.startswith(("\\\\", "//", "\\\\?\\", "\\\\.\\")):
        raise GrantV8ContractError(f"{label} UNC/device path is forbidden")
    path = PureWindowsPath(raw)
    if not path.is_absolute() or len(path.drive) != 2:
        raise GrantV8ContractError(f"{label} Windows path is invalid")
    parts = raw.replace("/", "\\").split("\\")
    for index, part in enumerate(parts):
        if not part:
            raise GrantV8ContractError(f"{label} Windows separator alias is forbidden")
        if index == 0 and re.fullmatch(r"[A-Za-z]:", part):
            continue
        if part in {".", ".."} or ":" in part or part.endswith((".", " ")) or _WINDOWS_DEVICE.fullmatch(part):
            raise GrantV8ContractError(f"{label} Windows alias/device/ADS is forbidden")
    drive = path.drive[0].casefold() + ":"
    return drive + "/" + "/".join(parts[1:])


def _canonical_target_display(value: object, label: str = "target_display") -> str:
    try:
        if type(value) is not str:
            raise GrantV8ContractError(f"{label} is invalid")
        raw = value.strip()
        if not raw or len(raw) > MAX_TARGET_DISPLAY_LENGTH or any(ord(char) < 32 for char in raw):
            raise GrantV8ContractError(f"{label} is invalid")
        _secret_free(raw, label)
        if re.match(r"^[A-Za-z]:[\\/]", raw):
            return _secret_free(_canonical_windows(raw, label), label)
        if PurePosixPath(raw).is_absolute():
            if raw.startswith("//") or "\\" in raw or any(part in {".", ".."} for part in raw.split("/")):
                raise GrantV8ContractError(f"{label} POSIX alias is forbidden")
            if posixpath.normpath(raw) != raw:
                raise GrantV8ContractError(f"{label} POSIX path is noncanonical")
            return _secret_free(raw, label)
        if "\\" in raw:
            raise GrantV8ContractError(f"{label} raw URI backslash is forbidden")
        parsed = urlsplit(raw)
        if parsed.scheme:
            if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise GrantV8ContractError(f"{label} URI is invalid")
            if not raw.isascii():
                raise GrantV8ContractError(f"{label} URI must be ASCII canonical")
            host = _canonical_host(parsed, parsed.netloc, label)
            path = _canonical_percent_path(parsed.path or "/", label)
            if any(part in {".", ".."} for part in path.split("/")):
                raise GrantV8ContractError(f"{label} URI dot segment is forbidden")
            normalized = posixpath.normpath(path)
            if path.endswith("/") and normalized != "/":
                normalized += "/"
            if normalized != path:
                raise GrantV8ContractError(f"{label} URI path is noncanonical")
            canonical = urlunsplit((parsed.scheme, host, quote(path, safe="/%-._~"), "", ""))
            if canonical != raw:
                raise GrantV8ContractError(f"{label} URI is noncanonical")
            return _secret_free(canonical, label)
        return _safe_id(raw, label)
    except GrantV8ContractError:
        raise
    except (KeyError, OSError, TypeError, ValueError, UnicodeError) as exc:
        raise GrantV8ContractError(f"{label} is invalid") from exc


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
            raise GrantV8ContractError("always_explicit must be boolean")

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
            raise GrantV8ContractError("unknown grant schema/policy version")
        _safe_id(self.principal_id, "principal_id")
        _safe_id(self.session_id, "session_id")
        _safe_id(self.workspace_id, "workspace_id")
        if type(self.mission_ids) is not tuple or len(self.mission_ids) > MAX_MISSIONS:
            raise GrantV8ContractError("mission collection exceeds its bound")
        missions = tuple(sorted(_safe_id(item, "mission_id") for item in self.mission_ids))
        if len(set(missions)) != len(missions):
            raise GrantV8ContractError("mission IDs are duplicated")
        object.__setattr__(self, "mission_ids", missions)
        if type(self.policies) is not tuple or not 1 <= len(self.policies) <= MAX_POLICIES or any(type(item) is not HostActionPolicy for item in self.policies):
            raise GrantV8ContractError("policy collection is invalid")
        policies = tuple(sorted(self.policies, key=lambda item: item.key))
        if len({item.key for item in policies}) != len(policies):
            raise GrantV8ContractError("host policies are duplicated")
        object.__setattr__(self, "policies", policies)
        _digest(self.audit_head, "audit_head")
        _bounded_int(self.credential_epoch, "credential_epoch", 0, MAX_MONOTONIC_MS)
        _bounded_int(self.vault_generation, "vault_generation", 0, MAX_MONOTONIC_MS)
        if any(type(getattr(self, name)) is not bool for name in ("audit_healthy", "session_active", "kill_switch")):
            raise GrantV8ContractError("host state booleans are invalid")

    def policy_for(self, capability: str, tool: str, operation: str) -> HostActionPolicy:
        values = tuple(item for item in self.policies if item.key == (capability, tool, operation))
        if len(values) != 1:
            raise GrantV8ContractError("unknown or ambiguous host policy")
        return values[0]

    def fingerprint(self) -> str:
        return _sha({"audit_head": self.audit_head, "contract": "HostSemanticState.v8", "credential_epoch": self.credential_epoch, "mission_ids": list(self.mission_ids), "policies": [item.payload() for item in self.policies], "policy_version": self.policy_version, "principal_id": self.principal_id, "schema_version": self.schema_version, "session_id": self.session_id, "vault_generation": self.vault_generation, "workspace_id": self.workspace_id})


def _copy_policy(value: object) -> HostActionPolicy:
    if type(value) is not HostActionPolicy:
        raise GrantV8ContractError("host policy concrete type is invalid")
    return HostActionPolicy(value.capability, value.tool, value.operation, value.risk, value.always_explicit, value.max_data_class)


def _copy_state(value: object) -> HostState:
    if type(value) is not HostState:
        raise GrantV8ContractError("host state concrete type is invalid")
    return HostState(value.schema_version, value.policy_version, value.principal_id, value.session_id, value.workspace_id, tuple(value.mission_ids), tuple(_copy_policy(item) for item in value.policies), value.audit_head, value.credential_epoch, value.vault_generation, value.audit_healthy, value.session_active, value.kill_switch)


@dataclass(frozen=True, slots=True)
class ActionBinding:
    provider: str
    provider_namespace: str
    target_identity: str
    target_display: str
    payload_digest: str
    payload_summary: str
    payload_rule_id: str
    egress: str
    idempotency_key: str

    def __post_init__(self) -> None:
        _slug(self.provider, "provider")
        _safe_id(self.provider_namespace, "provider_namespace")
        _digest(self.target_identity, "target_identity")
        object.__setattr__(self, "target_display", _canonical_target_display(self.target_display))
        _digest(self.payload_digest, "payload_digest")
        object.__setattr__(self, "payload_summary", _bounded_text(self.payload_summary, "payload_summary", MAX_PAYLOAD_SUMMARY_LENGTH))
        _safe_id(self.payload_rule_id, "payload_rule_id")
        _enum(self.egress, _EGRESS, "egress")
        _safe_id(self.idempotency_key, "idempotency_key")

    def payload(self) -> dict[str, str]:
        return {"egress": self.egress, "idempotency_key": self.idempotency_key, "payload_digest": self.payload_digest, "payload_rule_id": self.payload_rule_id, "payload_summary": self.payload_summary, "provider": self.provider, "provider_namespace": self.provider_namespace, "target_display": self.target_display, "target_identity": self.target_identity}

    def digest(self) -> str:
        return _sha({"binding": self.payload(), "contract": "ExactActionBinding.v8"})


def _copy_binding(value: object) -> ActionBinding:
    if type(value) is not ActionBinding:
        raise GrantV8ContractError("action binding concrete type is invalid")
    return ActionBinding(value.provider, value.provider_namespace, value.target_identity, value.target_display, value.payload_digest, value.payload_summary, value.payload_rule_id, value.egress, value.idempotency_key)


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
            raise GrantV8ContractError("action binding collection is invalid")
        if any(type(item) is not ActionBinding for item in self.bindings):
            raise GrantV8ContractError("action binding concrete type is invalid")
        bindings = tuple(sorted((_copy_binding(item) for item in self.bindings), key=lambda item: item.digest()))
        if len({item.digest() for item in bindings}) != len(bindings):
            raise GrantV8ContractError("action bindings are duplicated")
        if sum(len(item.target_display) for item in bindings) > MAX_TOTAL_TARGET_DISPLAY_CHARS or sum(len(item.payload_summary) for item in bindings) > MAX_TOTAL_PAYLOAD_SUMMARY_CHARS:
            raise GrantV8ContractError("action binding display/summary total exceeds bound")
        object.__setattr__(self, "bindings", bindings)
        _safe_id(self.account, "account")
        object.__setattr__(self, "path", _canonical_target_display(self.path, "path"))
        object.__setattr__(self, "effect", _bounded_text(self.effect, "effect", MAX_EFFECT_LENGTH))
        _safe_id(self.environment, "environment")
        _enum(self.data_class, set(_DATA_CLASSES), "data_class")
        if type(self.reversible) is not bool:
            raise GrantV8ContractError("reversible is invalid")
        object.__setattr__(self, "verification_plan", _bounded_text(self.verification_plan, "verification_plan", MAX_PLAN_LENGTH))
        object.__setattr__(self, "rollback_plan", _bounded_text(self.rollback_plan, "rollback_plan", MAX_PLAN_LENGTH))
        if type(self.cost_currency) is not str or not _CURRENCY.fullmatch(self.cost_currency):
            raise GrantV8ContractError("cost_currency is invalid")
        _secret_free(self.cost_currency, "cost_currency")
        _slug(self.cost_unit, "cost_unit")
        _digest(self.initial_binding_digest, "initial_binding_digest")
        if self.initial_binding_digest not in {item.digest() for item in bindings}:
            raise GrantV8ContractError("initial binding is outside finite exact set")
        initial = _bounded_int(self.initial_cost_micro, "initial_cost_micro", 0, MAX_COST_MICRO)
        per_action = _bounded_int(self.max_cost_per_action_micro, "max_cost_per_action_micro", 0, MAX_COST_MICRO)
        aggregate = _bounded_int(self.max_cost_aggregate_micro, "max_cost_aggregate_micro", 0, MAX_COST_MICRO)
        if aggregate < per_action or initial > per_action or initial > aggregate:
            raise GrantV8ContractError("cost bounds are contradictory")
        _bounded_int(self.max_uses, "max_uses", 1, MAX_USES)
        delay = _bounded_int(self.not_before_delay_ms, "not_before_delay_ms", 0, MAX_SESSION_LIFETIME_MS - 1)
        lifetime = _bounded_int(self.lifetime_ms, "lifetime_ms", 1, MAX_SESSION_LIFETIME_MS)
        if delay >= lifetime:
            raise GrantV8ContractError("time bounds are contradictory")


def _copy_resolved_scope(value: object) -> ResolvedGrantScope:
    if type(value) is not ResolvedGrantScope:
        raise GrantV8ContractError("grant resolver concrete type is invalid")
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
            raise GrantV8ContractError("action binding concrete type is invalid")
        object.__setattr__(self, "binding", _copy_binding(self.binding))
        _safe_id(self.account, "account")
        object.__setattr__(self, "path", _canonical_target_display(self.path, "path"))
        object.__setattr__(self, "effect", _bounded_text(self.effect, "effect", MAX_EFFECT_LENGTH))
        _safe_id(self.environment, "environment")
        _enum(self.data_class, set(_DATA_CLASSES), "data_class")
        if type(self.reversible) is not bool:
            raise GrantV8ContractError("reversible is invalid")
        object.__setattr__(self, "verification_plan", _bounded_text(self.verification_plan, "verification_plan", MAX_PLAN_LENGTH))
        object.__setattr__(self, "rollback_plan", _bounded_text(self.rollback_plan, "rollback_plan", MAX_PLAN_LENGTH))
        if type(self.cost_currency) is not str or not _CURRENCY.fullmatch(self.cost_currency):
            raise GrantV8ContractError("cost_currency is invalid")
        _secret_free(self.cost_currency, "cost_currency")
        _slug(self.cost_unit, "cost_unit")
        _bounded_int(self.cost_micro, "cost_micro", 0, MAX_COST_MICRO)


def _copy_action(value: object) -> ResolvedAction:
    if type(value) is not ResolvedAction:
        raise GrantV8ContractError("action resolver concrete type is invalid")
    return ResolvedAction(value.mission_id, value.capability, value.tool, value.operation, _copy_binding(value.binding), value.account, value.path, value.effect, value.environment, value.data_class, value.reversible, value.verification_plan, value.rollback_plan, value.cost_currency, value.cost_unit, value.cost_micro)


@dataclass(frozen=True, slots=True)
class ResolvedOutcome:
    reservation_id: str
    status: str
    result_digest: str | None
    provider_receipt_id: str | None
    receipt_digest: str | None

    def __post_init__(self) -> None:
        _safe_id(self.reservation_id, "reservation_id")
        _enum(self.status, _OUTCOMES, "outcome_status")
        values = self.result_digest, self.provider_receipt_id, self.receipt_digest
        if self.status == "verified-effect":
            _digest(self.result_digest, "result_digest")
            if type(self.provider_receipt_id) is not str or not re.fullmatch(r"provider-[0-9a-f]{16}-[0-9a-f]{8}", self.provider_receipt_id):
                raise GrantV8ContractError("provider_receipt_id is not structurally bound")
            _digest(self.receipt_digest, "receipt_digest")
        elif self.status == "dispatch-attempted" and any(value is not None for value in values):
            if any(value is None for value in values):
                raise GrantV8ContractError("partial dispatch receipt claims are forbidden")
            _digest(self.result_digest, "result_digest")
            if type(self.provider_receipt_id) is not str or not re.fullmatch(r"provider-[0-9a-f]{16}-[0-9a-f]{8}", self.provider_receipt_id):
                raise GrantV8ContractError("provider_receipt_id is not structurally bound")
            _digest(self.receipt_digest, "receipt_digest")
        elif any(value is not None for value in values):
            raise GrantV8ContractError("nonverified outcome cannot carry receipt claims")


def _copy_outcome(value: object) -> ResolvedOutcome:
    if type(value) is not ResolvedOutcome:
        raise GrantV8ContractError("outcome resolver concrete type is invalid")
    return ResolvedOutcome(value.reservation_id, value.status, value.result_digest, value.provider_receipt_id, value.receipt_digest)


@dataclass(frozen=True, slots=True)
class ReceiptVerificationRequest:
    receipt_challenge: str
    session_id: str
    workspace_id: str
    provider: str
    provider_namespace: str
    account: str
    tool: str
    operation: str
    reservation_id: str
    grant_id: str
    scope_digest: str
    binding_digest: str
    action_audit_digest: str
    idempotency_key: str
    idempotency_identity_digest: str
    action_fingerprint: str
    provider_receipt_id: str
    result_digest: str
    receipt_digest: str

    def __post_init__(self) -> None:
        _digest(self.receipt_challenge, "receipt_challenge")
        _safe_id(self.session_id, "session_id")
        _safe_id(self.workspace_id, "workspace_id")
        _slug(self.provider, "provider")
        _safe_id(self.provider_namespace, "provider_namespace")
        _safe_id(self.account, "account")
        _slug(self.tool, "tool")
        _slug(self.operation, "operation")
        _safe_id(self.reservation_id, "reservation_id")
        _safe_id(self.grant_id, "grant_id")
        _digest(self.scope_digest, "scope_digest")
        _digest(self.binding_digest, "binding_digest")
        _digest(self.action_audit_digest, "action_audit_digest")
        _safe_id(self.idempotency_key, "idempotency_key")
        _digest(self.idempotency_identity_digest, "idempotency_identity_digest")
        _digest(self.action_fingerprint, "action_fingerprint")
        if not re.fullmatch(r"provider-[0-9a-f]{16}-[0-9a-f]{8}", self.provider_receipt_id):
            raise GrantV8ContractError("provider_receipt_id is not structurally bound")
        _digest(self.result_digest, "result_digest")
        _digest(self.receipt_digest, "receipt_digest")

    def payload(self) -> dict[str, str]:
        return {
            "action_audit_digest": self.action_audit_digest,
            "account": self.account,
            "binding_digest": self.binding_digest,
            "grant_id": self.grant_id,
            "idempotency_key": self.idempotency_key,
            "idempotency_identity_digest": self.idempotency_identity_digest,
            "action_fingerprint": self.action_fingerprint,
            "operation": self.operation,
            "provider": self.provider,
            "provider_namespace": self.provider_namespace,
            "provider_receipt_id": self.provider_receipt_id,
            "receipt_challenge": self.receipt_challenge,
            "receipt_digest": self.receipt_digest,
            "reservation_id": self.reservation_id,
            "result_digest": self.result_digest,
            "session_id": self.session_id,
            "scope_digest": self.scope_digest,
            "tool": self.tool,
            "workspace_id": self.workspace_id,
        }


def canonical_receipt_digest(request: ReceiptVerificationRequest, receipt_sequence: int, receipt_id: str) -> str:
    _bounded_int(receipt_sequence, "receipt_sequence", 1, MAX_MONOTONIC_MS)
    if not hmac.compare_digest(receipt_id, _expected_receipt_id(receipt_sequence, request.receipt_challenge)):
        raise GrantV8ContractError("receipt_id is not structurally bound")
    payload = request.payload()
    payload.pop("receipt_digest")
    return _sha({"contract": "VerifiedExecutionReceipt.v8", "receipt_id": receipt_id, "receipt_sequence": receipt_sequence, **payload})


@dataclass(frozen=True, slots=True)
class HostReceiptVerification:
    verified: bool
    receipt_sequence: int
    receipt_id: str
    receipt_challenge: str
    session_id: str
    workspace_id: str
    provider: str
    provider_namespace: str
    account: str
    tool: str
    operation: str
    reservation_id: str
    grant_id: str
    scope_digest: str
    binding_digest: str
    action_audit_digest: str
    idempotency_key: str
    idempotency_identity_digest: str
    action_fingerprint: str
    provider_receipt_id: str
    result_digest: str
    receipt_digest: str
    verification_digest: str

    def __post_init__(self) -> None:
        if type(self.verified) is not bool:
            raise GrantV8ContractError("receipt verification decision is invalid")
        _bounded_int(self.receipt_sequence, "receipt_sequence", 1, MAX_MONOTONIC_MS)
        if not re.fullmatch(r"receipt-[0-9a-f]{16}-[0-9a-f]{8}", self.receipt_id):
            raise GrantV8ContractError("receipt_id is not structurally bound")
        request = ReceiptVerificationRequest(
            self.receipt_challenge,
            self.session_id,
            self.workspace_id,
            self.provider,
            self.provider_namespace,
            self.account,
            self.tool,
            self.operation,
            self.reservation_id,
            self.grant_id,
            self.scope_digest,
            self.binding_digest,
            self.action_audit_digest,
            self.idempotency_key,
            self.idempotency_identity_digest,
            self.action_fingerprint,
            self.provider_receipt_id,
            self.result_digest,
            self.receipt_digest,
        )
        canonical_receipt_digest(request, self.receipt_sequence, self.receipt_id)
        _digest(self.verification_digest, "verification_digest")

    def payload(self) -> dict[str, object]:
        return {
            "action_audit_digest": self.action_audit_digest,
            "account": self.account,
            "binding_digest": self.binding_digest,
            "grant_id": self.grant_id,
            "idempotency_key": self.idempotency_key,
            "idempotency_identity_digest": self.idempotency_identity_digest,
            "action_fingerprint": self.action_fingerprint,
            "operation": self.operation,
            "provider": self.provider,
            "provider_namespace": self.provider_namespace,
            "provider_receipt_id": self.provider_receipt_id,
            "receipt_challenge": self.receipt_challenge,
            "receipt_digest": self.receipt_digest,
            "receipt_id": self.receipt_id,
            "receipt_sequence": self.receipt_sequence,
            "reservation_id": self.reservation_id,
            "result_digest": self.result_digest,
            "session_id": self.session_id,
            "scope_digest": self.scope_digest,
            "tool": self.tool,
            "verified": self.verified,
            "workspace_id": self.workspace_id,
        }


def canonical_verification_digest(value: HostReceiptVerification) -> str:
    return _sha({"contract": "HostReceiptVerification.v8", **value.payload()})


def _copy_receipt_verification(value: object) -> HostReceiptVerification:
    if type(value) is not HostReceiptVerification:
        raise GrantV8ContractError("receipt verifier concrete type is invalid")
    return HostReceiptVerification(
        value.verified,
        value.receipt_sequence,
        value.receipt_id,
        value.receipt_challenge,
        value.session_id,
        value.workspace_id,
        value.provider,
        value.provider_namespace,
        value.account,
        value.tool,
        value.operation,
        value.reservation_id,
        value.grant_id,
        value.scope_digest,
        value.binding_digest,
        value.action_audit_digest,
        value.idempotency_key,
        value.idempotency_identity_digest,
        value.action_fingerprint,
        value.provider_receipt_id,
        value.result_digest,
        value.receipt_digest,
        value.verification_digest,
    )


@dataclass(frozen=True, slots=True)
class ReconciliationRequest:
    reconciliation_challenge: str
    identity_digest: str
    uncertain_sequence: int
    session_id: str
    workspace_id: str
    provider: str
    provider_namespace: str
    account: str
    tool: str
    operation: str
    idempotency_key: str
    action_fingerprint: str
    grant_id: str
    scope_digest: str
    binding_digest: str
    action_audit_digest: str
    receipt_challenge: str
    known_provider_receipt_id: str | None
    known_result_digest: str | None
    known_receipt_digest: str | None
    request_digest: str

    def __post_init__(self) -> None:
        _digest(self.reconciliation_challenge, "reconciliation_challenge")
        _digest(self.identity_digest, "identity_digest")
        _bounded_int(self.uncertain_sequence, "uncertain_sequence", 1, MAX_MONOTONIC_MS)
        _safe_id(self.session_id, "session_id")
        _safe_id(self.workspace_id, "workspace_id")
        _slug(self.provider, "provider")
        _safe_id(self.provider_namespace, "provider_namespace")
        _safe_id(self.account, "account")
        _slug(self.tool, "tool")
        _slug(self.operation, "operation")
        _safe_id(self.idempotency_key, "idempotency_key")
        _digest(self.action_fingerprint, "action_fingerprint")
        _safe_id(self.grant_id, "grant_id")
        _digest(self.scope_digest, "scope_digest")
        _digest(self.binding_digest, "binding_digest")
        _digest(self.action_audit_digest, "action_audit_digest")
        _digest(self.receipt_challenge, "receipt_challenge")
        known = self.known_provider_receipt_id, self.known_result_digest, self.known_receipt_digest
        if any(value is not None for value in known):
            if any(value is None for value in known):
                raise GrantV8ContractError("partial uncertain receipt evidence is forbidden")
            if type(self.known_provider_receipt_id) is not str or not re.fullmatch(r"provider-[0-9a-f]{16}-[0-9a-f]{8}", self.known_provider_receipt_id):
                raise GrantV8ContractError("known provider receipt ID is invalid")
            _digest(self.known_result_digest, "known_result_digest")
            _digest(self.known_receipt_digest, "known_receipt_digest")
        _digest(self.request_digest, "request_digest")

    def payload(self, *, include_digest: bool = True) -> dict[str, object]:
        payload = {
            "account": self.account,
            "action_audit_digest": self.action_audit_digest,
            "binding_digest": self.binding_digest,
            "grant_id": self.grant_id,
            "identity_digest": self.identity_digest,
            "idempotency_key": self.idempotency_key,
            "action_fingerprint": self.action_fingerprint,
            "known_provider_receipt_id": self.known_provider_receipt_id,
            "known_receipt_digest": self.known_receipt_digest,
            "known_result_digest": self.known_result_digest,
            "operation": self.operation,
            "provider": self.provider,
            "provider_namespace": self.provider_namespace,
            "receipt_challenge": self.receipt_challenge,
            "reconciliation_challenge": self.reconciliation_challenge,
            "scope_digest": self.scope_digest,
            "session_id": self.session_id,
            "tool": self.tool,
            "uncertain_sequence": self.uncertain_sequence,
            "workspace_id": self.workspace_id,
        }
        if include_digest:
            payload["request_digest"] = self.request_digest
        return payload


def canonical_reconciliation_request_digest(request: ReconciliationRequest) -> str:
    return _sha({"contract": "ReconciliationRequest.v8", **request.payload(include_digest=False)})


def _copy_reconciliation_request(value: object) -> ReconciliationRequest:
    if type(value) is not ReconciliationRequest:
        raise GrantV8ContractError("reconciliation request concrete type is invalid")
    return ReconciliationRequest(**{field_name: getattr(value, field_name) for field_name in ReconciliationRequest.__dataclass_fields__})


@dataclass(frozen=True, slots=True)
class HostReconciliation:
    outcome: str
    reconciliation_sequence: int
    reconciliation_id: str
    request: ReconciliationRequest
    receipt_verification: HostReceiptVerification | None
    reconciliation_digest: str

    def __post_init__(self) -> None:
        _enum(self.outcome, _RECONCILIATION_OUTCOMES, "reconciliation_outcome")
        _bounded_int(self.reconciliation_sequence, "reconciliation_sequence", 1, MAX_MONOTONIC_MS)
        if type(self.request) is not ReconciliationRequest:
            raise GrantV8ContractError("reconciliation request concrete type is invalid")
        object.__setattr__(self, "request", _copy_reconciliation_request(self.request))
        if not hmac.compare_digest(self.reconciliation_id, _expected_reconciliation_id(self.reconciliation_sequence, self.request.reconciliation_challenge)):
            raise GrantV8ContractError("reconciliation ID is not structurally bound")
        if self.outcome == "confirmed-effect":
            if type(self.receipt_verification) is not HostReceiptVerification or not self.receipt_verification.verified:
                raise GrantV8ContractError("confirmed effect requires exact verified receipt")
            object.__setattr__(self, "receipt_verification", _copy_receipt_verification(self.receipt_verification))
        elif self.receipt_verification is not None:
            raise GrantV8ContractError("non-effect reconciliation cannot carry a receipt")
        _digest(self.reconciliation_digest, "reconciliation_digest")

    def payload(self) -> dict[str, object]:
        receipt = None if self.receipt_verification is None else self.receipt_verification.payload()
        return {
            "outcome": self.outcome,
            "receipt_verification": receipt,
            "reconciliation_id": self.reconciliation_id,
            "reconciliation_sequence": self.reconciliation_sequence,
            "request": self.request.payload(),
        }


def canonical_reconciliation_digest(value: HostReconciliation) -> str:
    return _sha({"contract": "HostReconciliation.v8", **value.payload()})


def _empty_reconciliation_history(identity_digest: str) -> str:
    return _sha({"contract": "ReconciliationHistory.v8", "identity_digest": identity_digest, "state": "empty"})


def _roll_reconciliation_history(previous_root: str, response: HostReconciliation, revision: int) -> str:
    return _sha(
        {
            "contract": "ReconciliationHistory.v8",
            "previous_root": previous_root,
            "reconciliation_digest": response.reconciliation_digest,
            "reconciliation_id": response.reconciliation_id,
            "reconciliation_sequence": response.reconciliation_sequence,
            "request_digest": response.request.request_digest,
            "revision": revision,
        }
    )


def _copy_reconciliation(value: object) -> HostReconciliation:
    if type(value) is not HostReconciliation:
        raise GrantV8ContractError("reconciliation response concrete type is invalid")
    return HostReconciliation(
        value.outcome,
        value.reconciliation_sequence,
        value.reconciliation_id,
        _copy_reconciliation_request(value.request),
        None if value.receipt_verification is None else _copy_receipt_verification(value.receipt_verification),
        value.reconciliation_digest,
    )


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
            raise GrantV8ContractError("approval decision is invalid")
        _safe_id(self.attestation_id, "attestation_id")
        _bounded_int(self.attestation_sequence, "attestation_sequence", 1, MAX_MONOTONIC_MS)
        _digest(self.challenge_digest, "challenge_digest")
        _digest(self.scope_digest, "scope_digest")
        _digest(self.prompt_digest, "prompt_digest")


def _copy_approval(value: object) -> HostApprovalResponse:
    if type(value) is not HostApprovalResponse:
        raise GrantV8ContractError("approval response concrete type is invalid")
    return HostApprovalResponse(value.approved, value.attestation_id, value.attestation_sequence, value.challenge_digest, value.scope_digest, value.prompt_digest)


@dataclass(frozen=True, slots=True)
class HostServices:
    trust_root_id: str
    resolve_grant: Callable[[str], ResolvedGrantScope]
    resolve_action: Callable[[str], ResolvedAction]
    resolve_outcome: Callable[[str], ResolvedOutcome]
    approve: Callable[["ApprovalPrompt"], HostApprovalResponse]
    verify_receipt: Callable[[ReceiptVerificationRequest], HostReceiptVerification]
    reconcile: Callable[[ReconciliationRequest], HostReconciliation]
    state: Callable[[], HostState]
    monotonic_ms: Callable[[], int]

    def __post_init__(self) -> None:
        _safe_id(self.trust_root_id, "trust_root_id")
        for name in ("resolve_grant", "resolve_action", "resolve_outcome", "approve", "verify_receipt", "reconcile", "state", "monotonic_ms"):
            if not callable(getattr(self, name)):
                raise GrantV8ContractError(f"host service {name} is not callable")


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
    return {"account": scope.account, "bindings": [item.payload() for item in scope.bindings], "capability": scope.capability, "contract": "SessionGrantScope.v8", "cost_currency": scope.cost_currency, "cost_unit": scope.cost_unit, "data_class": scope.data_class, "effect": scope.effect, "environment": scope.environment, "expires_at_ms": scope.expires_at_ms, "initial_binding_digest": scope.initial_binding_digest, "initial_cost_micro": scope.initial_cost_micro, "issued_at_ms": scope.issued_at_ms, "max_cost_aggregate_micro": scope.max_cost_aggregate_micro, "max_cost_per_action_micro": scope.max_cost_per_action_micro, "max_uses": scope.max_uses, "mission_id": scope.mission_id, "not_before_ms": scope.not_before_ms, "operation": scope.operation, "path": scope.path, "principal_id": scope.principal_id, "reversible": scope.reversible, "risk": scope.risk, "rollback_plan": scope.rollback_plan, "session_id": scope.session_id, "state_fingerprint": scope.state_fingerprint, "tool": scope.tool, "trust_root_id": scope.trust_root_id, "verification_plan": scope.verification_plan, "workspace_id": scope.workspace_id}


def canonical_scope_digest(scope: GrantScope) -> str:
    return _sha(_scope_payload(scope))


def canonical_idempotency_identity(scope: GrantScope, binding: ActionBinding) -> str:
    return _sha(
        {
            "account": scope.account,
            "contract": "ExternalMutationIdentity.v8",
            "idempotency_key": binding.idempotency_key,
            "operation": scope.operation,
            "provider": binding.provider,
            "provider_namespace": binding.provider_namespace,
            "session_id": scope.session_id,
            "tool": scope.tool,
            "workspace_id": scope.workspace_id,
        }
    )


def canonical_external_action_fingerprint(scope: GrantScope, binding: ActionBinding, cost_micro: int) -> str:
    """Bind one idempotency identity to one immutable external action contract."""
    exact_cost = _bounded_int(cost_micro, "cost_micro", 0, MAX_COST_MICRO)
    action_contract_digest = _sha(
        {
            "account": scope.account,
            "capability": scope.capability,
            "contract": "StableExternalActionContract.v8",
            "cost_currency": scope.cost_currency,
            "cost_micro": exact_cost,
            "cost_unit": scope.cost_unit,
            "data_class": scope.data_class,
            "effect": scope.effect,
            "environment": scope.environment,
            "operation": scope.operation,
            "path": scope.path,
            "reversible": scope.reversible,
            "rollback_plan": scope.rollback_plan,
            "tool": scope.tool,
            "verification_plan": scope.verification_plan,
        }
    )
    return _sha(
        {
            "account": scope.account,
            "action_contract_digest": action_contract_digest,
            "binding_digest": binding.digest(),
            "contract": "ImmutableExternalActionFingerprint.v8",
            "operation": scope.operation,
            "payload_digest": binding.payload_digest,
            "provider": binding.provider,
            "provider_namespace": binding.provider_namespace,
            "target_identity": binding.target_identity,
            "tool": scope.tool,
        }
    )


def _prompt_digest(scope_digest: str, challenge: str, summary: str) -> str:
    return _sha({"challenge_digest": challenge, "contract": "ApprovalPrompt.v8", "human_summary": summary, "scope_digest": scope_digest})


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
    session_id: str
    workspace_id: str
    provider: str
    provider_namespace: str
    account: str
    tool: str
    operation: str
    scope_digest: str
    binding_digest: str
    action_audit_digest: str
    idempotency_key: str
    idempotency_identity_digest: str
    action_fingerprint: str
    receipt_challenge: str
    cost_micro: int
    state_fingerprint: str
    created_at_ms: int
    expires_at_ms: int
    grant_generation: int
    sequence: int


@dataclass(frozen=True, slots=True)
class MutationLedgerEntry:
    identity_digest: str
    session_id: str
    workspace_id: str
    provider: str
    provider_namespace: str
    account: str
    tool: str
    operation: str
    idempotency_key: str
    action_fingerprint: str
    state: str
    reservation_id: str | None
    created_at_ms: int
    updated_at_ms: int
    reconciliation_count: int
    reconciliation_history_root: str
    latest_reconciliation_sequence: int
    sequence: int


@dataclass(frozen=True, slots=True)
class OutcomeRecord:
    reservation_id: str
    status: str
    result_digest: str | None
    provider_receipt_id: str | None
    receipt_digest: str | None
    receipt_id: str | None
    identity_digest: str
    action_fingerprint: str
    sequence: int


@dataclass(frozen=True, slots=True)
class ReceiptRecord:
    status: str
    receipt_sequence: int
    receipt_id: str
    reservation_id: str
    grant_id: str
    session_id: str
    workspace_id: str
    provider: str
    provider_namespace: str
    account: str
    tool: str
    operation: str
    scope_digest: str
    binding_digest: str
    action_audit_digest: str
    idempotency_key: str
    idempotency_identity_digest: str
    action_fingerprint: str
    receipt_challenge: str
    provider_receipt_id: str
    receipt_digest: str
    result_digest: str
    verification_digest: str
    cost_micro: int
    reservation_created_at_ms: int
    reconciliation_count: int
    reconciliation_history_root: str
    latest_reconciliation_sequence: int
    committed_at_ms: int


@dataclass(frozen=True, slots=True)
class UncertainRecord:
    uncertain_sequence: int
    status: str
    reason: str
    reservation_id: str
    grant_id: str
    session_id: str
    workspace_id: str
    provider: str
    provider_namespace: str
    account: str
    tool: str
    operation: str
    scope_digest: str
    binding_digest: str
    action_audit_digest: str
    idempotency_key: str
    idempotency_identity_digest: str
    action_fingerprint: str
    receipt_challenge: str
    provider_receipt_id: str | None
    result_digest: str | None
    receipt_digest: str | None
    verification_digest: str | None
    cost_micro: int
    state_fingerprint: str
    expires_at_ms: int
    grant_generation: int
    reservation_created_at_ms: int
    dispatched_at_ms: int
    updated_at_ms: int
    revision: int
    reconciliation_count: int
    reconciliation_history_root: str
    latest_reconciliation_sequence: int


@dataclass(frozen=True, slots=True)
class ReconciliationRecord:
    revision: int
    reconciliation_sequence: int
    reconciliation_id: str
    identity_digest: str
    outcome: str
    challenge: str
    request_digest: str
    response_digest: str
    history_count: int
    history_root: str
    reconciled_at_ms: int


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
        _sentinel_digest(self.scope_digest, "scope_digest")
        _sentinel_digest(self.action_audit_digest, "action_audit_digest")


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
            raise GrantV8ContractError("commit result is invalid")
        _enum(self.reason, _COMMIT_REASONS, "commit_reason")
        _safe_id(self.reservation_id, "reservation_id")
        _safe_id(self.grant_id, "grant_id")
        _sentinel_digest(self.receipt_digest, "receipt_digest")


@dataclass(frozen=True, slots=True)
class ShadowReconciliationDecision:
    outcome: str
    identity_digest: str
    receipt_digest: str
    callback_required: bool = field(init=False, default=True)
    authority_granted: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        _enum(self.outcome, _RECONCILIATION_OUTCOMES, "reconciliation_outcome")
        _digest(self.identity_digest, "identity_digest")
        _sentinel_digest(self.receipt_digest, "receipt_digest")


@dataclass(frozen=True, slots=True)
class ShadowDispatchDecision:
    reservation_id: str
    identity_digest: str
    state: str = field(init=False, default="uncertain_needs_reconciliation")
    callback_required: bool = field(init=False, default=True)
    authority_granted: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        _safe_id(self.reservation_id, "reservation_id")
        _digest(self.identity_digest, "identity_digest")


class SessionGrantShadowStore:
    def __init__(self, services: HostServices) -> None:
        if type(services) is not HostServices:
            raise GrantV8ContractError("HostServices concrete type is required")
        self._services = services
        self._grants: dict[str, SessionGrant] = {}
        self._approvals: set[str] = set()
        self._revocations: dict[str, GrantRevocation] = {}
        self._reservations: dict[str, ActionReservation] = {}
        self._uses: dict[str, int] = {}
        self._costs: dict[str, int] = {}
        self._receipts: dict[str, ReceiptRecord] = {}
        self._receipt_digests: dict[str, int] = {}
        self._provider_receipt_ids: dict[str, int] = {}
        self._outcome_records: dict[str, OutcomeRecord] = {}
        self._mutation_ledger: dict[str, MutationLedgerEntry] = {}
        self._uncertain_records: dict[str, UncertainRecord] = {}
        self._reconciliations: dict[str, ReconciliationRecord] = {}
        self._sequence = 0
        self._action_sequence = 0
        self._global_generation = 0
        self._grant_generations: dict[str, int] = {}
        self._clock_high_water = 0
        self._last_attestation_sequence = 0
        self._last_receipt_sequence = 0
        self._last_reconciliation_sequence = 0
        self._killed = False
        self._audit_unhealthy = False
        self._session_ended = False
        self._fail_closed = False
        self._lock = threading.RLock()

    def _record_host_failure(self, *, post_dispatch_ambiguity: bool = False) -> None:
        with self._lock:
            if post_dispatch_ambiguity:
                for reservation_id in tuple(self._reservations):
                    self._quarantine_reservation_locked(reservation_id, "post-dispatch-callback-failed", self._clock_high_water)
            else:
                self._clear_all_reservations_locked("cancelled_before_dispatch")
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "semantic-state-changed", self._clock_high_water)
            self._fail_closed = True
            self._global_generation += 1

    def _snapshot_outside_lock(self) -> tuple[int, HostState]:
        try:
            raw_now = self._services.monotonic_ms()
            now = _bounded_int(raw_now, "monotonic_ms", 0, MAX_MONOTONIC_MS)
            state = _copy_state(self._services.state())
            return now, state
        except GrantV8ContractError:
            self._record_host_failure()
            raise
        except Exception as exc:
            self._record_host_failure()
            raise GrantV8ContractError("host snapshot callback failed") from exc

    def _call_resolver(self, name: str, reference: str) -> object:
        try:
            return getattr(self._services, name)(reference)
        except GrantV8ContractError:
            self._record_host_failure()
            raise
        except Exception as exc:
            self._record_host_failure()
            raise GrantV8ContractError(f"host {name} callback failed") from exc

    def _call_outcome_resolver(self, reference: str) -> object:
        try:
            value = self._services.resolve_outcome(reference)
            return _copy_outcome(value)
        except GrantV8ContractError:
            self._record_host_failure(post_dispatch_ambiguity=True)
            raise
        except Exception as exc:
            self._record_host_failure(post_dispatch_ambiguity=True)
            raise GrantV8ContractError("host resolve_outcome callback failed") from exc

    def _call_receipt_verifier(self, request: ReceiptVerificationRequest) -> object:
        try:
            return self._services.verify_receipt(request)
        except GrantV8ContractError:
            self._record_host_failure()
            raise
        except Exception as exc:
            self._record_host_failure()
            raise GrantV8ContractError("host receipt verifier callback failed") from exc

    def _call_reconciliation(self, request: ReconciliationRequest) -> object:
        try:
            return self._services.reconcile(request)
        except GrantV8ContractError:
            raise
        except Exception as exc:
            raise GrantV8ContractError("host reconciliation callback failed") from exc

    def _copy_boundary(self, copier: Callable[[object], object], value: object) -> object:
        try:
            return copier(value)
        except GrantV8ContractError:
            self._record_host_failure()
            raise
        except Exception as exc:
            self._record_host_failure()
            raise GrantV8ContractError("host boundary copy failed") from exc

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
        _enum(reason, _REVOCATION_REASONS, "revocation_reason")
        if grant_id in self._revocations:
            return
        if len(self._revocations) >= MAX_REVOCATIONS:
            self._fail_closed = True
            self._clear_all_reservations_locked("cancelled_before_dispatch")
            self._global_generation += 1
            return
        self._sequence += 1
        self._grant_generations[grant_id] = self._grant_generations.get(grant_id, 0) + 1
        self._revocations[grant_id] = GrantRevocation(grant_id, reason, now, self._sequence)
        self._clear_grant_reservations_locked(grant_id)

    def _clear_grant_reservations_locked(self, grant_id: str) -> None:
        for reservation_id in tuple(self._reservations):
            if self._reservations[reservation_id].grant_id == grant_id:
                self._release_reservation_locked(reservation_id, "cancelled_before_dispatch")

    def _set_ledger_state_locked(self, reservation: ActionReservation, state: str, now: int) -> None:
        _enum(state, _LEDGER_STATES, "ledger_state")
        previous = self._mutation_ledger.get(reservation.idempotency_identity_digest)
        if previous is not None and not hmac.compare_digest(previous.action_fingerprint, reservation.action_fingerprint):
            self._fail_closed = True
            self._global_generation += 1
            raise GrantV8ContractError("external mutation identity action fingerprint is immutable")
        self._sequence += 1
        self._mutation_ledger[reservation.idempotency_identity_digest] = MutationLedgerEntry(
            reservation.idempotency_identity_digest,
            reservation.session_id,
            reservation.workspace_id,
            reservation.provider,
            reservation.provider_namespace,
            reservation.account,
            reservation.tool,
            reservation.operation,
            reservation.idempotency_key,
            reservation.action_fingerprint,
            state,
            reservation.reservation_id if state == "pending_before_dispatch" else None,
            reservation.created_at_ms if previous is None else previous.created_at_ms,
            now,
            0 if previous is None else previous.reconciliation_count,
            _empty_reconciliation_history(reservation.idempotency_identity_digest) if previous is None else previous.reconciliation_history_root,
            0 if previous is None else previous.latest_reconciliation_sequence,
            self._sequence,
        )

    def _set_uncertain_ledger_state_locked(self, record: UncertainRecord, state: str, now: int) -> None:
        _enum(state, _LEDGER_STATES, "ledger_state")
        previous = self._mutation_ledger.get(record.idempotency_identity_digest)
        if previous is None:
            raise GrantV8ContractError("uncertain mutation ledger entry is missing")
        if not hmac.compare_digest(previous.action_fingerprint, record.action_fingerprint):
            self._fail_closed = True
            self._global_generation += 1
            raise GrantV8ContractError("external mutation identity action fingerprint is immutable")
        self._sequence += 1
        self._mutation_ledger[record.idempotency_identity_digest] = MutationLedgerEntry(
            record.idempotency_identity_digest,
            record.session_id,
            record.workspace_id,
            record.provider,
            record.provider_namespace,
            record.account,
            record.tool,
            record.operation,
            record.idempotency_key,
            record.action_fingerprint,
            state,
            None,
            previous.created_at_ms,
            now,
            record.reconciliation_count,
            record.reconciliation_history_root,
            record.latest_reconciliation_sequence,
            self._sequence,
        )

    def _release_reservation_locked(self, reservation_id: str, state: str) -> ActionReservation | None:
        reservation = self._reservations.pop(reservation_id, None)
        if reservation is not None:
            self._set_ledger_state_locked(reservation, state, self._clock_high_water)
        return reservation

    def _clear_all_reservations_locked(self, state: str) -> None:
        for reservation_id in tuple(self._reservations):
            self._release_reservation_locked(reservation_id, state)

    def _quarantine_reservation_locked(
        self,
        reservation_id: str,
        reason: str,
        now: int,
        outcome: ResolvedOutcome | None = None,
        verification_digest: str | None = None,
    ) -> UncertainRecord | None:
        reservation = self._reservations.pop(reservation_id, None)
        if reservation is None:
            return next((value for value in self._uncertain_records.values() if value.reservation_id == reservation_id), None)
        if (
            reservation.idempotency_identity_digest not in self._uncertain_records
            and len(self._uncertain_records) >= MAX_UNCERTAIN_RECORDS
        ):
            self._fail_closed = True
            self._global_generation += 1
            raise GrantV8CapacityError("uncertain mutation capacity is exhausted")
        self._set_ledger_state_locked(reservation, "uncertain_needs_reconciliation", now)
        self._sequence += 1
        record = UncertainRecord(
            self._sequence,
            "uncertain_needs_reconciliation",
            reason,
            reservation.reservation_id,
            reservation.grant_id,
            reservation.session_id,
            reservation.workspace_id,
            reservation.provider,
            reservation.provider_namespace,
            reservation.account,
            reservation.tool,
            reservation.operation,
            reservation.scope_digest,
            reservation.binding_digest,
            reservation.action_audit_digest,
            reservation.idempotency_key,
            reservation.idempotency_identity_digest,
            reservation.action_fingerprint,
            reservation.receipt_challenge,
            None if outcome is None else outcome.provider_receipt_id,
            None if outcome is None else outcome.result_digest,
            None if outcome is None else outcome.receipt_digest,
            verification_digest,
            reservation.cost_micro,
            reservation.state_fingerprint,
            reservation.expires_at_ms,
            reservation.grant_generation,
            reservation.created_at_ms,
            now,
            now,
            1,
            0,
            _empty_reconciliation_history(reservation.idempotency_identity_digest),
            0,
        )
        self._uncertain_records[reservation.idempotency_identity_digest] = record
        return record

    def _expire_reservations_locked(self, now: int) -> None:
        for reservation_id, item in tuple(self._reservations.items()):
            if now >= item.expires_at_ms:
                self._release_reservation_locked(reservation_id, "cancelled_before_dispatch")

    def _attestation_digest(self, grant: SessionGrant) -> str:
        return _sha({"approval_id": grant.approval_id, "approval_sequence": grant.approval_sequence, "challenge_digest": grant.challenge_digest, "contract": "HostApprovalAttestation.v8", "prompt_digest": grant.prompt_digest, "scope_digest": grant.scope_digest, "trust_root_id": self._services.trust_root_id})

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
            self._global_generation += 1
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, terminal[1], now)
            self._clear_all_reservations_locked("cancelled_before_dispatch")
            return
        fingerprint = state.fingerprint()
        semantic_drift = any(
            grant.grant_id not in self._revocations
            and not hmac.compare_digest(grant.scope.state_fingerprint, fingerprint)
            for grant in self._grants.values()
        )
        if semantic_drift:
            self._global_generation += 1
        for grant in tuple(self._grants.values()):
            if grant.grant_id in self._revocations:
                continue
            if now >= grant.scope.expires_at_ms:
                self._revoke_locked(grant.grant_id, "expired", now)
            elif not hmac.compare_digest(grant.scope.state_fingerprint, fingerprint) or not hmac.compare_digest(grant.attestation_digest, self._attestation_digest(grant)):
                self._revoke_locked(grant.grant_id, "semantic-state-changed", now)

    def _pre_snapshot(self) -> tuple[int, HostState, int, str]:
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator is disabled")
        with self._lock:
            if self._stop_reason_locked() is not None:
                raise GrantV8Denied("host session is not healthy")
        raw_now, state = self._snapshot_outside_lock()
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator was disabled during host snapshot")
        with self._lock:
            now = self._accept_snapshot_locked(raw_now, state)
            if self._stop_reason_locked() is not None:
                raise GrantV8Denied("host session is not healthy")
            return now, state, self._global_generation, state.fingerprint()

    def _post_snapshot(self, generation: int, fingerprint: str) -> tuple[int, HostState, int]:
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator was disabled before host snapshot")
        raw_now, state = self._snapshot_outside_lock()
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator was disabled during host snapshot")
        with self._lock:
            now = self._accept_snapshot_locked(raw_now, state)
            if self._stop_reason_locked() is not None or generation != self._global_generation or not hmac.compare_digest(fingerprint, state.fingerprint()):
                raise GrantV8Denied("host state changed during resolver callback")
            return now, state, self._global_generation

    @staticmethod
    def _scope_from_resolved(resolved: ResolvedGrantScope, state: HostState, trust_root_id: str, now: int) -> GrantScope:
        if resolved.mission_id is not None and resolved.mission_id not in state.mission_ids:
            raise GrantV8ContractError("grant mission is not host-authorized")
        policy = state.policy_for(resolved.capability, resolved.tool, resolved.operation)
        if policy.always_explicit or policy.risk in {"high", "critical"}:
            raise GrantV8Denied("always-explicit/high-risk action cannot be granted")
        if _DATA_CLASSES[resolved.data_class] > _DATA_CLASSES[policy.max_data_class]:
            raise GrantV8ContractError("grant data class exceeds host policy")
        expires = _checked_expiry(now, resolved.lifetime_ms)
        not_before = now + resolved.not_before_delay_ms
        return GrantScope(state.fingerprint(), trust_root_id, state.principal_id, state.session_id, state.workspace_id, resolved.mission_id, resolved.capability, resolved.tool, resolved.operation, resolved.bindings, resolved.account, resolved.path, resolved.effect, resolved.environment, resolved.data_class, policy.risk, resolved.reversible, resolved.verification_plan, resolved.rollback_plan, resolved.cost_currency, resolved.cost_unit, resolved.initial_binding_digest, resolved.initial_cost_micro, resolved.max_cost_per_action_micro, resolved.max_cost_aggregate_micro, resolved.max_uses, now, not_before, expires)

    @staticmethod
    def _human_summary(scope: GrantScope) -> str:
        pairs = "; ".join(f"provider {item.provider}/{item.provider_namespace}; target {item.target_display} identity {item.target_identity} + payload {item.payload_digest} ({item.payload_summary}; rule {item.payload_rule_id}; egress {item.egress}; idempotency {item.idempotency_key})" for item in scope.bindings)
        summary = f"Principal {scope.principal_id}; session {scope.session_id}; workspace {scope.workspace_id}; mission {scope.mission_id or 'none'}; action {scope.capability}/{scope.tool}/{scope.operation}; exact action pairs [{pairs}]; account {scope.account}; path {scope.path}; environment {scope.environment}; effect {scope.effect}; data {scope.data_class}; risk {scope.risk}; reversible {scope.reversible}; verification {scope.verification_plan}; rollback {scope.rollback_plan}; cost {scope.cost_currency} {scope.cost_unit}, initial {scope.initial_cost_micro}, per-action max {scope.max_cost_per_action_micro}, aggregate max {scope.max_cost_aggregate_micro}; uses {scope.max_uses}; valid {scope.not_before_ms} through {scope.expires_at_ms}."
        return _bounded_text(summary, "human_summary", MAX_PROMPT_LENGTH)

    def _cleanup_grant_capacity_locked(self) -> None:
        while len(self._grants) >= MAX_GRANTS:
            terminal = sorted((self._revocations[grant_id].sequence, grant.sequence, grant_id) for grant_id, grant in self._grants.items() if grant_id in self._revocations)
            if not terminal:
                raise GrantV8CapacityError("active grant capacity is exhausted")
            _rev_seq, _grant_seq, grant_id = terminal[0]
            grant = self._grants.pop(grant_id)
            self._revocations.pop(grant_id, None)
            self._uses.pop(grant_id, None)
            self._costs.pop(grant_id, None)
            self._approvals.discard(grant.approval_id)
            self._grant_generations.pop(grant_id, None)
        if len(self._approvals) >= MAX_APPROVALS:
            raise GrantV8CapacityError("approval capacity is exhausted")

    def request_session_grant(self, invocation_ref: str) -> str:
        reference = _safe_id(invocation_ref, "invocation_ref")
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator is disabled")
        _first_now, _first_state, generation, fingerprint = self._pre_snapshot()
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator was disabled before grant resolution")
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
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator was disabled before approval")
        try:
            response = _copy_approval(self._services.approve(prompt))
        except GrantV8ContractError:
            self._record_host_failure()
            raise
        except Exception as exc:
            self._record_host_failure()
            raise GrantV8ContractError("host approval callback failed") from exc
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator was disabled after approval")
        raw_issue_now, issue_state = self._snapshot_outside_lock()
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator was disabled during approval snapshot")
        with self._lock:
            issue_now = self._accept_snapshot_locked(raw_issue_now, issue_state)
            if self._stop_reason_locked() is not None or approval_generation != self._global_generation or not hmac.compare_digest(approval_fingerprint, issue_state.fingerprint()) or issue_now >= scope.expires_at_ms:
                raise GrantV8Denied("host state changed during approval")
            if not response.approved:
                raise GrantV8Denied("trusted host denied exact scope")
            if not all(hmac.compare_digest(left, right) for left, right in ((response.challenge_digest, challenge), (response.scope_digest, scope_digest), (response.prompt_digest, prompt_digest))):
                raise GrantV8Denied("approval response does not bind exact prompt")
            if not hmac.compare_digest(response.attestation_id, _expected_attestation_id(response.attestation_sequence, challenge)):
                raise GrantV8Denied("approval ID is not structurally bound")
            if response.attestation_sequence <= self._last_attestation_sequence or response.attestation_id in self._approvals:
                raise GrantV8Denied("approval attestation was consumed")
            self._cleanup_grant_capacity_locked()
            self._sequence += 1
            grant_id = f"grant-{self._sequence:08d}"
            attestation = _sha({"approval_id": response.attestation_id, "approval_sequence": response.attestation_sequence, "challenge_digest": challenge, "contract": "HostApprovalAttestation.v8", "prompt_digest": prompt_digest, "scope_digest": scope_digest, "trust_root_id": self._services.trust_root_id})
            self._grants[grant_id] = SessionGrant(grant_id, response.attestation_id, response.attestation_sequence, challenge, prompt_digest, attestation, scope, scope_digest, self._sequence)
            self._grant_generations[grant_id] = 0
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
        except GrantV8ContractError:
            risk = "unknown"
        return _sha({"action_binding": action.binding.payload(), "action_sequence": sequence, "capability": action.capability, "contract": "ActionAudit.v8", "cost_currency": action.cost_currency, "cost_micro": action.cost_micro, "cost_unit": action.cost_unit, "data_class": action.data_class, "effect": action.effect, "environment": action.environment, "invocation_ref_sha256": hashlib.sha256(reference.encode()).hexdigest(), "mission_id": action.mission_id, "observed_at_ms": now, "operation": action.operation, "path": action.path, "reversible": action.reversible, "risk": risk, "rollback_plan": action.rollback_plan, "scope_digest": scope_digest, "state_fingerprint": state.fingerprint(), "tool": action.tool, "verification_plan": action.verification_plan})

    def _resolve_action(self, reference: str) -> tuple[ResolvedAction, int, HostState]:
        _first_now, _first_state, generation, fingerprint = self._pre_snapshot()
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator was disabled before action resolution")
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
        except GrantV8ContractError:
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
        identity = canonical_idempotency_identity(grant.scope, action.binding)
        action_fingerprint = canonical_external_action_fingerprint(grant.scope, action.binding, action.cost_micro)
        ledger = self._mutation_ledger.get(identity)
        if ledger is not None and not hmac.compare_digest(ledger.action_fingerprint, action_fingerprint):
            return ShadowGrantDecision("would-deny", "idempotency-action-mismatch", grant.grant_id, grant.scope_digest, digest), grant
        if ledger is not None and ledger.state == "consumed_verified":
            return ShadowGrantDecision("would-deny", "idempotency-consumed", grant.grant_id, grant.scope_digest, digest), grant
        if ledger is not None and ledger.state == "uncertain_needs_reconciliation":
            return ShadowGrantDecision("would-deny", "idempotency-uncertain", grant.grant_id, grant.scope_digest, digest), grant
        if ledger is not None and ledger.state == "pending_before_dispatch":
            return ShadowGrantDecision("would-deny", "idempotency-pending", grant.grant_id, grant.scope_digest, digest), grant
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
            digest = _sha({"contract": "DisabledGrantEvaluation.v8", "invocation_ref": reference})
            return ShadowGrantDecision("disabled", "feature-flag-off", None, "0" * 64, digest)
        action, now, state = self._resolve_action(reference)
        with self._lock:
            stopped = self._stop_reason_locked()
            if stopped is not None:
                self._action_sequence += 1
                digest = _sha({"action_sequence": self._action_sequence, "contract": "StoppedGrantEvaluation.v8", "reason": stopped})
                return ShadowGrantDecision("would-deny", stopped, None, "0" * 64, digest)
            decision, _grant = self._decision_locked(reference, action, now, state)
            return decision

    def reserve(self, invocation_ref: str) -> str:
        reference = _safe_id(invocation_ref, "invocation_ref")
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator is disabled")
        action, now, state = self._resolve_action(reference)
        with self._lock:
            if self._stop_reason_locked() is not None:
                raise GrantV8Denied("host session is not healthy")
            decision, grant = self._decision_locked(reference, action, now, state)
            if decision.outcome != "would-allow" or grant is None:
                raise GrantV8Denied(decision.reason)
            if len(self._reservations) >= MAX_RESERVATIONS:
                raise GrantV8CapacityError("reservation capacity is exhausted")
            pending = tuple(item for item in self._reservations.values() if item.grant_id == grant.grant_id)
            if self._uses[grant.grant_id] + len(pending) >= grant.scope.max_uses:
                raise GrantV8Denied("reserved use capacity is exhausted")
            if self._costs[grant.grant_id] + sum(item.cost_micro for item in pending) + action.cost_micro > grant.scope.max_cost_aggregate_micro:
                raise GrantV8Denied("reserved cost capacity is exhausted")
            if len(self._uncertain_records) + len(self._reservations) >= MAX_UNCERTAIN_RECORDS:
                self._fail_closed = True
                self._global_generation += 1
                raise GrantV8CapacityError("uncertain mutation capacity is exhausted")
            lifetime = min(MAX_RESERVATION_LIFETIME_MS, grant.scope.expires_at_ms - now)
            expires = _checked_expiry(now, lifetime, "reservation expiry")
            self._sequence += 1
            reservation_id = f"reservation-{self._sequence:08d}"
            _safe_id(reservation_id, "reservation_id")
            binding_digest = action.binding.digest()
            identity = canonical_idempotency_identity(grant.scope, action.binding)
            action_fingerprint = canonical_external_action_fingerprint(grant.scope, action.binding, action.cost_micro)
            ledger = self._mutation_ledger.get(identity)
            if ledger is not None and not hmac.compare_digest(ledger.action_fingerprint, action_fingerprint):
                raise GrantV8Denied("idempotency key is permanently bound to a different external action")
            if ledger is not None and ledger.state not in {"definitive_no_effect", "cancelled_before_dispatch"}:
                raise GrantV8Denied("idempotency key is unavailable")
            if ledger is None and len(self._mutation_ledger) >= MAX_LEDGER_IDENTITIES:
                self._fail_closed = True
                self._global_generation += 1
                self._clear_all_reservations_locked("cancelled_before_dispatch")
                raise GrantV8CapacityError("external mutation ledger capacity is exhausted")
            receipt_challenge = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
            reservation = ActionReservation(
                reservation_id,
                grant.grant_id,
                grant.scope.session_id,
                grant.scope.workspace_id,
                action.binding.provider,
                action.binding.provider_namespace,
                grant.scope.account,
                grant.scope.tool,
                grant.scope.operation,
                grant.scope_digest,
                binding_digest,
                decision.action_audit_digest,
                action.binding.idempotency_key,
                identity,
                action_fingerprint,
                receipt_challenge,
                action.cost_micro,
                state.fingerprint(),
                now,
                expires,
                self._grant_generations.get(grant.grant_id, 0),
                self._sequence,
            )
            self._reservations[reservation_id] = reservation
            self._set_ledger_state_locked(reservation, "pending_before_dispatch", now)
            return reservation_id

    def mark_dispatch_attempted(self, reservation_id: str) -> ShadowDispatchDecision:
        identifier = _safe_id(reservation_id, "reservation_id")
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator is disabled")
        now, state, _generation, _fingerprint = self._pre_snapshot()
        with self._lock:
            reservation = self._reservations.get(identifier)
            if reservation is None:
                raise GrantV8Denied("unknown, expired, cleared, or already dispatched reservation")
            grant = self._grants.get(reservation.grant_id)
            if (
                grant is None
                or grant.grant_id in self._revocations
                or self._grant_generations.get(grant.grant_id, 0) != reservation.grant_generation
                or not hmac.compare_digest(reservation.state_fingerprint, state.fingerprint())
            ):
                self._release_reservation_locked(identifier, "cancelled_before_dispatch")
                raise GrantV8Denied("reservation is no longer valid")
            record = self._quarantine_reservation_locked(identifier, "dispatch-marked-before-attempt", now)
            if record is None:
                raise GrantV8Denied("reservation could not enter dispatch quarantine")
            return ShadowDispatchDecision(identifier, record.idempotency_identity_digest)

    def _record_outcome_locked(
        self,
        reservation: ActionReservation,
        status: str,
        outcome: ResolvedOutcome,
        receipt_id: str | None,
    ) -> None:
        self._sequence += 1
        self._outcome_records[reservation.reservation_id] = OutcomeRecord(
            reservation.reservation_id,
            status,
            outcome.result_digest,
            outcome.provider_receipt_id,
            outcome.receipt_digest,
            receipt_id,
            reservation.idempotency_identity_digest,
            reservation.action_fingerprint,
            self._sequence,
        )
        if len(self._outcome_records) > MAX_OUTCOMES:
            oldest = min(self._outcome_records, key=lambda item: self._outcome_records[item].sequence)
            self._outcome_records.pop(oldest, None)

    def _trim_receipts_locked(self) -> None:
        while len(self._receipts) > MAX_RECEIPTS:
            oldest_id = min(self._receipts, key=lambda item: self._receipts[item].receipt_sequence)
            oldest = self._receipts.pop(oldest_id)
            if self._receipt_digests.get(oldest.receipt_digest) == oldest.receipt_sequence:
                self._receipt_digests.pop(oldest.receipt_digest, None)
            if self._provider_receipt_ids.get(oldest.provider_receipt_id) == oldest.receipt_sequence:
                self._provider_receipt_ids.pop(oldest.provider_receipt_id, None)

    @staticmethod
    def _receipt_request(
        reservation: ActionReservation,
        outcome: ResolvedOutcome,
        *,
        challenge: str | None = None,
    ) -> ReceiptVerificationRequest:
        if outcome.result_digest is None or outcome.provider_receipt_id is None or outcome.receipt_digest is None:
            raise GrantV8ContractError("effect receipt claims are incomplete")
        return ReceiptVerificationRequest(
            reservation.receipt_challenge if challenge is None else challenge,
            reservation.session_id,
            reservation.workspace_id,
            reservation.provider,
            reservation.provider_namespace,
            reservation.account,
            reservation.tool,
            reservation.operation,
            reservation.reservation_id,
            reservation.grant_id,
            reservation.scope_digest,
            reservation.binding_digest,
            reservation.action_audit_digest,
            reservation.idempotency_key,
            reservation.idempotency_identity_digest,
            reservation.action_fingerprint,
            outcome.provider_receipt_id,
            outcome.result_digest,
            outcome.receipt_digest,
        )

    @staticmethod
    def _verification_is_exact(request: ReceiptVerificationRequest, verification: HostReceiptVerification) -> bool:
        echoes = (
            (verification.receipt_challenge, request.receipt_challenge),
            (verification.session_id, request.session_id),
            (verification.workspace_id, request.workspace_id),
            (verification.provider, request.provider),
            (verification.provider_namespace, request.provider_namespace),
            (verification.account, request.account),
            (verification.tool, request.tool),
            (verification.operation, request.operation),
            (verification.reservation_id, request.reservation_id),
            (verification.grant_id, request.grant_id),
            (verification.scope_digest, request.scope_digest),
            (verification.binding_digest, request.binding_digest),
            (verification.action_audit_digest, request.action_audit_digest),
            (verification.idempotency_key, request.idempotency_key),
            (verification.idempotency_identity_digest, request.idempotency_identity_digest),
            (verification.action_fingerprint, request.action_fingerprint),
            (verification.provider_receipt_id, request.provider_receipt_id),
            (verification.result_digest, request.result_digest),
            (verification.receipt_digest, request.receipt_digest),
        )
        expected_receipt_id = _expected_receipt_id(verification.receipt_sequence, request.receipt_challenge)
        expected_provider_id = _expected_provider_receipt_id(verification.receipt_sequence, request.result_digest)
        expected_receipt_digest = canonical_receipt_digest(request, verification.receipt_sequence, verification.receipt_id)
        return (
            all(hmac.compare_digest(left, right) for left, right in echoes)
            and hmac.compare_digest(verification.receipt_id, expected_receipt_id)
            and hmac.compare_digest(request.provider_receipt_id, expected_provider_id)
            and hmac.compare_digest(request.receipt_digest, expected_receipt_digest)
            and hmac.compare_digest(verification.verification_digest, canonical_verification_digest(verification))
        )

    def _receipt_replayed_locked(self, request: ReceiptVerificationRequest, verification: HostReceiptVerification) -> bool:
        return (
            verification.receipt_sequence <= self._last_receipt_sequence
            or verification.receipt_id in self._receipts
            or request.receipt_digest in self._receipt_digests
            or request.provider_receipt_id in self._provider_receipt_ids
        )

    def _store_receipt_locked(
        self,
        reservation: ActionReservation,
        request: ReceiptVerificationRequest,
        verification: HostReceiptVerification,
        now: int,
        reconciliation: UncertainRecord | None = None,
    ) -> None:
        ledger = self._mutation_ledger.get(reservation.idempotency_identity_digest)
        history_count = reconciliation.reconciliation_count if reconciliation is not None else (0 if ledger is None else ledger.reconciliation_count)
        history_root = reconciliation.reconciliation_history_root if reconciliation is not None else (_empty_reconciliation_history(reservation.idempotency_identity_digest) if ledger is None else ledger.reconciliation_history_root)
        latest_reconciliation_sequence = reconciliation.latest_reconciliation_sequence if reconciliation is not None else (0 if ledger is None else ledger.latest_reconciliation_sequence)
        self._receipts[verification.receipt_id] = ReceiptRecord(
            "consumed_verified",
            verification.receipt_sequence,
            verification.receipt_id,
            reservation.reservation_id,
            reservation.grant_id,
            reservation.session_id,
            reservation.workspace_id,
            reservation.provider,
            reservation.provider_namespace,
            reservation.account,
            reservation.tool,
            reservation.operation,
            reservation.scope_digest,
            reservation.binding_digest,
            reservation.action_audit_digest,
            reservation.idempotency_key,
            reservation.idempotency_identity_digest,
            reservation.action_fingerprint,
            request.receipt_challenge,
            request.provider_receipt_id,
            request.receipt_digest,
            request.result_digest,
            verification.verification_digest,
            reservation.cost_micro,
            reservation.created_at_ms,
            history_count,
            history_root,
            latest_reconciliation_sequence,
            now,
        )
        self._receipt_digests[request.receipt_digest] = verification.receipt_sequence
        self._provider_receipt_ids[request.provider_receipt_id] = verification.receipt_sequence
        self._last_receipt_sequence = verification.receipt_sequence
        self._trim_receipts_locked()

    def _update_uncertain_locked(self, identity: str, reason: str, now: int, verification_digest: str | None = None) -> None:
        current = self._uncertain_records.get(identity)
        if current is not None:
            self._uncertain_records[identity] = replace(
                current,
                reason=reason,
                verification_digest=current.verification_digest if verification_digest is None else verification_digest,
                updated_at_ms=now,
            )

    def _merge_uncertain_outcome_locked(self, identity: str, outcome: ResolvedOutcome, now: int) -> None:
        current = self._uncertain_records.get(identity)
        if current is None:
            return
        evidence = outcome.provider_receipt_id, outcome.result_digest, outcome.receipt_digest
        known = current.provider_receipt_id, current.result_digest, current.receipt_digest
        if any(value is not None for value in known) and known != evidence:
            raise GrantV8ContractError("outcome changed quarantined receipt evidence")
        if any(value is not None for value in evidence):
            self._uncertain_records[identity] = replace(
                current,
                provider_receipt_id=outcome.provider_receipt_id,
                result_digest=outcome.result_digest,
                receipt_digest=outcome.receipt_digest,
                updated_at_ms=now,
            )

    def record_outcome(self, outcome_ref: str) -> ShadowCommitDecision:
        reference = _safe_id(outcome_ref, "outcome_ref")
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator is disabled")
        _first_now, _first_state, generation, fingerprint = self._pre_snapshot()
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator was disabled before outcome resolution")
        outcome = self._call_outcome_resolver(reference)
        assert isinstance(outcome, ResolvedOutcome)
        with self._lock:
            pending = self._reservations.get(outcome.reservation_id)
            existing_uncertain = next((item for item in self._uncertain_records.values() if item.reservation_id == outcome.reservation_id), None)
            if pending is None and existing_uncertain is None:
                raise GrantV8Denied("unknown, expired, or cleared reservation")
            if outcome.status in {"dispatch-attempted", "verified-effect"}:
                if pending is not None:
                    self._quarantine_reservation_locked(
                        pending.reservation_id,
                        "outcome-material-captured-before-post-snapshot",
                        self._clock_high_water,
                        outcome,
                    )
                else:
                    assert existing_uncertain is not None
                    self._merge_uncertain_outcome_locked(existing_uncertain.idempotency_identity_digest, outcome, self._clock_high_water)
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator was disabled after outcome capture")
        raw_now, state = self._snapshot_outside_lock()
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator was disabled during post-outcome snapshot")
        with self._lock:
            reservation = self._reservations.get(outcome.reservation_id)
            prior_uncertain = next((item for item in self._uncertain_records.values() if item.reservation_id == outcome.reservation_id), None)
            already_dispatched = reservation is None and prior_uncertain is not None
            if reservation is None and prior_uncertain is not None:
                reservation = self._reservation_from_uncertain(prior_uncertain)
            if reservation is None:
                raise GrantV8Denied("unknown, expired, or cleared reservation")
            grant = self._grants.get(reservation.grant_id)
            dispatched = already_dispatched or outcome.status in {"dispatch-attempted", "verified-effect"}
            if not already_dispatched and dispatched:
                self._quarantine_reservation_locked(
                    reservation.reservation_id,
                    "dispatch-attempted",
                    max(raw_now, self._clock_high_water),
                    outcome,
                )
            elif already_dispatched:
                self._merge_uncertain_outcome_locked(reservation.idempotency_identity_digest, outcome, max(raw_now, self._clock_high_water))
            now = self._accept_snapshot_locked(raw_now, state)
            generation_changed = generation != self._global_generation
            grant_changed = self._grant_generations.get(reservation.grant_id, 0) != reservation.grant_generation
            fingerprint_changed = not hmac.compare_digest(fingerprint, state.fingerprint())
            invalid = (
                self._stop_reason_locked() is not None
                or generation_changed
                or grant_changed
                or fingerprint_changed
                or grant is None
                or grant.grant_id in self._revocations
                or not hmac.compare_digest(reservation.state_fingerprint, state.fingerprint())
            )
            if dispatched and invalid:
                self._update_uncertain_locked(reservation.idempotency_identity_digest, "relevant-state-drift-after-dispatch", now)
                self._record_outcome_locked(reservation, "uncertain_needs_reconciliation", outcome, None)
                return ShadowCommitDecision(False, "uncertain-needs-reconciliation", reservation.reservation_id, reservation.grant_id, outcome.receipt_digest or "0" * 64)
            if invalid:
                self._release_reservation_locked(reservation.reservation_id, "cancelled_before_dispatch")
                raise GrantV8Denied("reservation is no longer valid")
            if already_dispatched and outcome.status == "cancelled-before-dispatch":
                self._update_uncertain_locked(reservation.idempotency_identity_digest, "cancelled-claim-after-dispatch", now)
                self._record_outcome_locked(reservation, "uncertain_needs_reconciliation", outcome, None)
                return ShadowCommitDecision(False, "uncertain-needs-reconciliation", reservation.reservation_id, reservation.grant_id, "0" * 64)
            if outcome.status in {"cancelled-before-dispatch", "definitive-no-effect"}:
                ledger_state = "cancelled_before_dispatch" if outcome.status == "cancelled-before-dispatch" else "definitive_no_effect"
                if already_dispatched:
                    assert prior_uncertain is not None
                    self._set_uncertain_ledger_state_locked(prior_uncertain, ledger_state, now)
                    self._uncertain_records.pop(reservation.idempotency_identity_digest, None)
                else:
                    self._release_reservation_locked(reservation.reservation_id, ledger_state)
                self._record_outcome_locked(reservation, outcome.status, outcome, None)
                return ShadowCommitDecision(False, outcome.status, reservation.reservation_id, grant.grant_id, "0" * 64)
            if outcome.status == "dispatch-attempted":
                self._record_outcome_locked(reservation, "uncertain_needs_reconciliation", outcome, None)
                return ShadowCommitDecision(False, "uncertain-needs-reconciliation", reservation.reservation_id, grant.grant_id, outcome.receipt_digest or "0" * 64)
            request = self._receipt_request(reservation, outcome)
            receipt_generation = self._global_generation
            receipt_grant_generation = self._grant_generations.get(reservation.grant_id, 0)
            receipt_fingerprint = state.fingerprint()
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator was disabled before receipt verification")
        verification = self._copy_boundary(_copy_receipt_verification, self._call_receipt_verifier(request))
        assert isinstance(verification, HostReceiptVerification)
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator was disabled after receipt verification")
        raw_commit_now, commit_state = self._snapshot_outside_lock()
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator was disabled during commit snapshot")
        with self._lock:
            commit_now = self._accept_snapshot_locked(raw_commit_now, commit_state)
            current = self._uncertain_records.get(reservation.idempotency_identity_digest)
            if (
                self._stop_reason_locked() is not None
                or receipt_generation != self._global_generation
                or receipt_grant_generation != self._grant_generations.get(reservation.grant_id, 0)
                or not hmac.compare_digest(receipt_fingerprint, commit_state.fingerprint())
                or current is None
                or current.reservation_id != reservation.reservation_id
            ):
                self._update_uncertain_locked(reservation.idempotency_identity_digest, "relevant-state-drift-after-dispatch", commit_now)
                self._record_outcome_locked(reservation, "uncertain_needs_reconciliation", outcome, verification.receipt_id)
                return ShadowCommitDecision(False, "uncertain-needs-reconciliation", reservation.reservation_id, reservation.grant_id, request.receipt_digest)
            try:
                valid_binding = self._verification_is_exact(request, verification)
            except GrantV8ContractError as exc:
                self._update_uncertain_locked(reservation.idempotency_identity_digest, "invalid-receipt-verification", commit_now)
                self._record_host_failure()
                raise GrantV8ContractError("receipt verification is not bound to the exact action") from exc
            if not valid_binding:
                self._update_uncertain_locked(reservation.idempotency_identity_digest, "invalid-receipt-verification", commit_now)
                self._record_host_failure()
                raise GrantV8ContractError("receipt verification is not bound to the exact action")
            if not verification.verified:
                self._update_uncertain_locked(reservation.idempotency_identity_digest, "receipt-unverified", commit_now, verification.verification_digest)
                self._record_outcome_locked(reservation, "uncertain_needs_reconciliation", outcome, verification.receipt_id)
                return ShadowCommitDecision(False, "uncertain-needs-reconciliation", reservation.reservation_id, grant.grant_id, request.receipt_digest)
            if self._receipt_replayed_locked(request, verification):
                self._update_uncertain_locked(reservation.idempotency_identity_digest, "receipt-replay", commit_now, verification.verification_digest)
                raise GrantV8Denied("receipt replay was rejected; mutation remains uncertain")
            used = self._uses[grant.grant_id]
            spent = self._costs[grant.grant_id]
            if used >= grant.scope.max_uses or spent + reservation.cost_micro > grant.scope.max_cost_aggregate_micro:
                self._update_uncertain_locked(reservation.idempotency_identity_digest, "grant-limit-drift-after-dispatch", commit_now, verification.verification_digest)
                raise GrantV8Denied("committed limit changed; mutation remains uncertain")
            self._set_ledger_state_locked(reservation, "consumed_verified", commit_now)
            self._uncertain_records.pop(reservation.idempotency_identity_digest, None)
            self._uses[grant.grant_id] = used + 1
            self._costs[grant.grant_id] = spent + reservation.cost_micro
            self._store_receipt_locked(reservation, request, verification, commit_now)
            self._record_outcome_locked(reservation, "consumed_verified", outcome, verification.receipt_id)
            if self._uses[grant.grant_id] >= grant.scope.max_uses:
                self._revoke_locked(grant.grant_id, "use-exhausted", commit_now)
            elif grant.scope.max_cost_aggregate_micro > 0 and self._costs[grant.grant_id] >= grant.scope.max_cost_aggregate_micro:
                self._revoke_locked(grant.grant_id, "aggregate-exhausted", commit_now)
            return ShadowCommitDecision(True, "verified-commit", reservation.reservation_id, grant.grant_id, request.receipt_digest)

    @staticmethod
    def _reservation_from_uncertain(record: UncertainRecord) -> ActionReservation:
        return ActionReservation(
            record.reservation_id,
            record.grant_id,
            record.session_id,
            record.workspace_id,
            record.provider,
            record.provider_namespace,
            record.account,
            record.tool,
            record.operation,
            record.scope_digest,
            record.binding_digest,
            record.action_audit_digest,
            record.idempotency_key,
            record.idempotency_identity_digest,
            record.action_fingerprint,
            record.receipt_challenge,
            record.cost_micro,
            record.state_fingerprint,
            record.reservation_created_at_ms,
            record.expires_at_ms,
            record.grant_generation,
            record.uncertain_sequence,
        )

    @staticmethod
    def _reconciliation_request(record: UncertainRecord, challenge: str) -> ReconciliationRequest:
        placeholder_digest = _sha(
            {
                "contract": "ReconciliationRequestPlaceholder.v8",
                "identity_digest": record.idempotency_identity_digest,
                "reconciliation_challenge": challenge,
            }
        )
        initial = ReconciliationRequest(
            challenge,
            record.idempotency_identity_digest,
            record.uncertain_sequence,
            record.session_id,
            record.workspace_id,
            record.provider,
            record.provider_namespace,
            record.account,
            record.tool,
            record.operation,
            record.idempotency_key,
            record.action_fingerprint,
            record.grant_id,
            record.scope_digest,
            record.binding_digest,
            record.action_audit_digest,
            record.receipt_challenge,
            record.provider_receipt_id,
            record.result_digest,
            record.receipt_digest,
            placeholder_digest,
        )
        return replace(initial, request_digest=canonical_reconciliation_request_digest(initial))

    def _advance_reconciliation_locked(
        self,
        record: UncertainRecord,
        response: HostReconciliation,
        now: int,
    ) -> UncertainRecord:
        revision = record.revision + 1
        history_count = record.reconciliation_count + 1
        history_root = _roll_reconciliation_history(record.reconciliation_history_root, response, revision)
        self._sequence += 1
        updated = replace(
            record,
            uncertain_sequence=self._sequence,
            reason=f"reconciliation-{response.outcome}",
            updated_at_ms=now,
            revision=revision,
            reconciliation_count=history_count,
            reconciliation_history_root=history_root,
            latest_reconciliation_sequence=response.reconciliation_sequence,
        )
        self._uncertain_records[record.idempotency_identity_digest] = updated
        self._reconciliations[record.idempotency_identity_digest] = ReconciliationRecord(
            revision,
            response.reconciliation_sequence,
            response.reconciliation_id,
            record.idempotency_identity_digest,
            response.outcome,
            response.request.reconciliation_challenge,
            response.request.request_digest,
            response.reconciliation_digest,
            history_count,
            history_root,
            now,
        )
        self._last_reconciliation_sequence = response.reconciliation_sequence
        return updated

    def reconcile_uncertain(self, identity_digest: str) -> ShadowReconciliationDecision:
        identity = _digest(identity_digest, "identity_digest")
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator is disabled")
        with self._lock:
            record = self._uncertain_records.get(identity)
            if record is None:
                raise GrantV8Denied("unknown or already reconciled mutation identity")
            revision_token = record.revision
            challenge = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
            request = self._reconciliation_request(record, challenge)
        try:
            response = _copy_reconciliation(self._call_reconciliation(request))
        except GrantV8ContractError:
            self._record_host_failure()
            raise
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator was disabled during reconciliation")
        try:
            raw_now = _bounded_int(self._services.monotonic_ms(), "monotonic_ms", 0, MAX_MONOTONIC_MS)
        except GrantV8ContractError:
            self._record_host_failure()
            raise
        except Exception as exc:
            self._record_host_failure()
            raise GrantV8ContractError("host reconciliation clock callback failed") from exc
        with self._lock:
            if not grant_evaluator_enabled():
                raise GrantV8Disabled("grant evaluator was disabled during reconciliation")
            now = max(raw_now, self._clock_high_water)
            self._clock_high_water = now
            current = self._uncertain_records.get(identity)
            if current != record or current is None or current.revision != revision_token:
                raise GrantV8Denied("uncertain mutation changed during reconciliation")
            if response.request != request:
                raise GrantV8ContractError("reconciliation did not echo the exact fresh request")
            if not hmac.compare_digest(request.request_digest, canonical_reconciliation_request_digest(request)):
                raise GrantV8ContractError("reconciliation request digest is invalid")
            if (
                response.reconciliation_sequence <= self._last_reconciliation_sequence
                or any(item.reconciliation_id == response.reconciliation_id for item in self._reconciliations.values())
                or not hmac.compare_digest(response.reconciliation_digest, canonical_reconciliation_digest(response))
            ):
                raise GrantV8Denied("reconciliation replay was rejected")
            receipt_digest = "0" * 64
            reservation: ActionReservation | None = None
            receipt_request: ReceiptVerificationRequest | None = None
            verification: HostReceiptVerification | None = None
            if response.outcome == "confirmed-effect":
                verification = response.receipt_verification
                if verification is None:
                    raise GrantV8ContractError("confirmed effect omitted receipt verification")
                reservation = self._reservation_from_uncertain(record)
                outcome = ResolvedOutcome(
                    reservation.reservation_id,
                    "verified-effect",
                    verification.result_digest,
                    verification.provider_receipt_id,
                    verification.receipt_digest,
                )
                receipt_request = self._receipt_request(reservation, outcome)
                known = record.provider_receipt_id, record.result_digest, record.receipt_digest
                discovered = verification.provider_receipt_id, verification.result_digest, verification.receipt_digest
                if any(value is not None for value in known) and known != discovered:
                    raise GrantV8ContractError("reconciliation changed known receipt evidence")
                try:
                    exact = self._verification_is_exact(receipt_request, verification)
                except GrantV8ContractError as exc:
                    raise GrantV8ContractError("reconciled receipt is not bound to the exact mutation") from exc
                if not exact:
                    raise GrantV8ContractError("reconciled receipt is not bound to the exact mutation")
                if self._receipt_replayed_locked(receipt_request, verification):
                    raise GrantV8Denied("reconciled receipt replay was rejected")
            updated = self._advance_reconciliation_locked(record, response, now)
            if response.outcome == "still-uncertain":
                self._set_uncertain_ledger_state_locked(updated, "uncertain_needs_reconciliation", now)
            elif response.outcome == "confirmed-no-effect":
                self._set_uncertain_ledger_state_locked(updated, "definitive_no_effect", now)
                self._uncertain_records.pop(identity, None)
            else:
                assert reservation is not None and receipt_request is not None and verification is not None
                self._set_uncertain_ledger_state_locked(updated, "consumed_verified", now)
                self._uncertain_records.pop(identity, None)
                self._store_receipt_locked(reservation, receipt_request, verification, now, updated)
                grant = self._grants.get(record.grant_id)
                if grant is not None:
                    self._uses[record.grant_id] = self._uses.get(record.grant_id, 0) + 1
                    self._costs[record.grant_id] = self._costs.get(record.grant_id, 0) + record.cost_micro
                    if record.grant_id not in self._revocations:
                        if self._uses[record.grant_id] >= grant.scope.max_uses:
                            self._revoke_locked(record.grant_id, "use-exhausted", now)
                        elif grant.scope.max_cost_aggregate_micro > 0 and self._costs[record.grant_id] >= grant.scope.max_cost_aggregate_micro:
                            self._revoke_locked(record.grant_id, "aggregate-exhausted", now)
                receipt_digest = receipt_request.receipt_digest
            return ShadowReconciliationDecision(response.outcome, identity, receipt_digest)

    def revoke(self, grant_id: str) -> None:
        identifier = _safe_id(grant_id, "grant_id")
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator is disabled")
        with self._lock:
            if identifier not in self._grants:
                raise GrantV8ContractError("unknown grant_id")
            self._revoke_locked(identifier, "owner-revoke", self._clock_high_water)

    def kill(self) -> None:
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator is disabled")
        with self._lock:
            self._killed = True
            self._global_generation += 1
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "kill-switch", self._clock_high_water)
            self._clear_all_reservations_locked("cancelled_before_dispatch")

    def mark_audit_unhealthy(self) -> None:
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator is disabled")
        with self._lock:
            self._audit_unhealthy = True
            self._global_generation += 1
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "audit-unhealthy", self._clock_high_water)
            self._clear_all_reservations_locked("cancelled_before_dispatch")

    def end_session(self) -> None:
        if not grant_evaluator_enabled():
            raise GrantV8Disabled("grant evaluator is disabled")
        with self._lock:
            self._session_ended = True
            self._global_generation += 1
            for grant_id in tuple(self._grants):
                self._revoke_locked(grant_id, "session-ended", self._clock_high_water)
            self._clear_all_reservations_locked("cancelled_before_dispatch")

    def snapshot_counts(self) -> dict[str, int]:
        with self._lock:
            return {
                "approvals": len(self._approvals),
                "grants": len(self._grants),
                "ledger": len(self._mutation_ledger),
                "outcomes": len(self._outcome_records),
                "receipts": len(self._receipts),
                "reconciliations": len(self._reconciliations),
                "reservations": len(self._reservations),
                "revocations": len(self._revocations),
                "uncertain": len(self._uncertain_records),
            }


__all__ = [name for name in tuple(globals()) if name.startswith("MAX_")] + [
    "GRANT_EVALUATOR_FLAG", "GRANT_POLICY_VERSION", "GRANT_SCHEMA_VERSION",
    "ActionBinding", "ApprovalPrompt", "GrantV8CapacityError", "GrantV8ContractError",
    "GrantV8Denied", "GrantV8Disabled", "HostActionPolicy", "HostApprovalResponse",
    "HostReceiptVerification", "HostReconciliation", "HostServices", "HostState",
    "ReceiptVerificationRequest", "ReconciliationRequest",
    "ResolvedAction", "ResolvedGrantScope", "ResolvedOutcome",
    "SessionGrantShadowStore", "ShadowCommitDecision", "ShadowDispatchDecision", "ShadowGrantDecision", "ShadowReconciliationDecision",
    "canonical_external_action_fingerprint", "canonical_idempotency_identity", "canonical_receipt_digest", "canonical_reconciliation_digest",
    "canonical_reconciliation_request_digest", "canonical_scope_digest", "canonical_verification_digest",
    "grant_evaluator_enabled",
]
