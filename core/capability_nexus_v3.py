"""Phase 5.3 Capability Nexus V3: isolated, default-off contracts.

V3 supersedes the rejected V1 and V2 candidates without importing them. The module has
no live/startup wiring and exposes no authorization or dispatch operation.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field, replace
from enum import Enum
import hashlib
import hmac
import json
import math
import re
import threading
import time
from types import MappingProxyType
from typing import Callable, Mapping, Sequence
import unicodedata
from urllib.parse import quote, unquote, unquote_to_bytes


CAPABILITY_SCHEMA_VERSION_V3 = "onyx.capability.v3"
NEXUS_CONTRACT_VERSION_V3 = "onyx.capability-nexus.v3"
CATALOG_CONTRACT_VERSION_V3 = "onyx.local-catalog.v3"
LOCK_ORDER_V3 = ("gate_immutable_state", "registry_lock", "adapter_lock")


class CapabilityV3ContractError(ValueError):
    pass


class CapabilityV3DeniedError(PermissionError):
    pass


class OperationKindV3(str, Enum):
    READ = "read"
    DRAFT = "draft"
    MUTATE = "mutate"
    VERIFY = "verify"
    RECONCILE = "reconcile"


class CapabilityStatusV3(str, Enum):
    DISABLED = "disabled"
    AVAILABLE_READ_ONLY = "available_read_only"
    DEGRADED = "degraded"
    BLOCKED_BY_ACCESS = "blocked_by_access"
    BLOCKED_BY_SCOPE = "blocked_by_scope"
    BLOCKED_BY_PLATFORM = "blocked_by_platform"
    BLOCKED_BY_LICENSE = "blocked_by_license"


class TransportKindV3(str, Enum):
    LEGACY = "legacy"
    LOCAL = "local"
    API = "api"
    CLI = "cli"
    SDK = "sdk"
    MCP = "mcp"
    BROWSER = "browser"


class ReadStateV3(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    UNCERTAIN = "uncertain"
    CANCELLED_BEFORE_HOOK = "cancelled_before_hook"
    TIMEOUT_BEFORE_HOOK = "timeout_before_hook"
    DENIED = "denied"
    RATE_LIMITED = "rate_limited"
    EXPIRED_UNCERTAIN = "expired_uncertain"
    UNKNOWN_CORRELATION = "unknown_correlation"


class ReadFailureClassV3(str, Enum):
    NONE = "none"
    AUTH = "auth"
    SCOPE = "scope"
    DISABLED = "disabled"
    KILL = "kill"
    REVOKED = "revoked"
    RATE_LIMIT = "rate_limit"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    HOOK_EXCEPTION = "hook_exception"
    LEDGER_CAPACITY = "ledger_capacity"
    QUOTA = "quota"
    EXPIRED_PENDING = "expired_pending"
    UNCERTAIN_EXPIRED = "uncertain_expired"
    UNKNOWN = "unknown"


_SLUG = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_ALIAS = re.compile(r"^alias:[a-z0-9][a-z0-9._/-]{0,95}$")
_DOMAIN = re.compile(r"^(?:\*\.)?[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_PEM = re.compile(r"-----BEGIN [A-Z0-9 ]*(?:PRIVATE|SECRET|TOKEN|KEY)[A-Z0-9 ]*-----")
_SECRET_ASSIGN = re.compile(
    r"(?i)(?:api[_.-]?key|token|access[_.-]?token|refresh[_.-]?token|password|secret|authorization|cookie|private[_.-]?key|bearer)\s*[:=]\s*[^\s,;]{4,}"
)
_SECRET_NAMES = frozenset(
    {"apikey", "token", "accesstoken", "refreshtoken", "password", "secret", "authorization", "cookie", "privatekey"}
)
_SAFE_METADATA_KEYS = frozenset(
    {"data_source", "declaration_sha256", "dispatch_path", "fallback_class", "policy_source"}
)
_MAX_METADATA_DECODE_DEPTH = 6
_MAX_METADATA_REPRESENTATIONS = 16
_MAX_METADATA_TOTAL_BYTES = 16_384
_MAX_METADATA_VALUE_BYTES = 4_096
_PERCENT = re.compile(r"%(?:[0-9A-Fa-f]{2})")
_RESIDUAL_UNICODE_ESCAPE = re.compile(r"\\u[0-9A-Fa-f]{4}|\\x[0-9A-Fa-f]{2}")


def _normalized_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", unquote(value).casefold())


def _secret_canary(value: str) -> bool:
    candidates = {value, unquote(value)}
    for candidate in tuple(candidates):
        compact = re.sub(r"\s+", "", candidate)
        if 8 <= len(compact) <= 4096 and len(compact) % 4 == 0 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", compact):
            try:
                padded = compact.replace("-", "+").replace("_", "/") + "=" * (-len(compact) % 4)
                decoded = base64.b64decode(padded, validate=False).decode("utf-8")
            except (ValueError, UnicodeError):
                continue
            candidates.add(decoded)
    return any(_SECRET_ASSIGN.search(item) or _JWT.search(item) or _PEM.search(item) for item in candidates)


def _scan_metadata_representation(value: str) -> None:
    normalized = unicodedata.normalize("NFKC", value)
    if any(unicodedata.category(ch) in {"Cc", "Cf", "Cs"} for ch in normalized):
        raise CapabilityV3ContractError("metadata contains control/format characters")
    folded = normalized.casefold()
    if _SECRET_ASSIGN.search(folded) or _JWT.search(normalized) or _PEM.search(normalized.upper()):
        raise CapabilityV3ContractError("metadata representation contains secret material")
    if _RESIDUAL_UNICODE_ESCAPE.search(normalized):
        raise CapabilityV3ContractError("metadata contains residual character encoding")


def _canonical_percent_decode(value: str) -> str | None:
    if "%" not in value:
        return None
    if _PERCENT.sub("", value).find("%") >= 0:
        raise CapabilityV3ContractError("metadata contains malformed percent encoding")
    try:
        decoded = unquote_to_bytes(value).decode("utf-8", errors="strict")
    except (UnicodeDecodeError, ValueError) as exc:
        raise CapabilityV3ContractError("metadata percent encoding is invalid") from exc
    canonical = quote(decoded, safe="-._~/:@")
    normalize_hex = lambda text: re.sub(  # noqa: E731
        r"%[0-9A-Fa-f]{2}", lambda match: match.group(0).upper(), text
    )
    if normalize_hex(canonical) != normalize_hex(value):
        raise CapabilityV3ContractError("metadata percent encoding is noncanonical")
    return decoded if decoded != value else None


def _canonical_base64_decode(value: str) -> str | None:
    compact = value
    if not 8 <= len(compact) <= _MAX_METADATA_VALUE_BYTES or any(ch.isspace() for ch in compact):
        return None
    if ("+" in compact or "/" in compact) and ("-" in compact or "_" in compact):
        raise CapabilityV3ContractError("metadata Base64 alphabet is ambiguous")
    standard = re.fullmatch(r"[A-Za-z0-9+/]*={0,2}", compact) is not None
    urlsafe = re.fullmatch(r"[A-Za-z0-9_-]*={0,2}", compact) is not None
    if not standard and not urlsafe:
        return None
    if len(compact.rstrip("=")) % 4 == 1:
        return None
    padded = compact.rstrip("=") + "=" * (-len(compact.rstrip("=")) % 4)
    try:
        if urlsafe and not standard:
            raw = base64.b64decode(padded, altchars=b"-_", validate=True)
            canonical = base64.urlsafe_b64encode(raw).decode("ascii")
        else:
            raw = base64.b64decode(padded, validate=True)
            canonical = base64.b64encode(raw).decode("ascii")
        decoded = raw.decode("utf-8", errors="strict")
    except (ValueError, UnicodeDecodeError):
        return None
    if canonical.rstrip("=") != compact.rstrip("="):
        raise CapabilityV3ContractError("metadata Base64 encoding is noncanonical")
    if not decoded or any(unicodedata.category(ch) in {"Cc", "Cf", "Cs"} for ch in decoded):
        return None
    return decoded if decoded != value else None


def _validate_metadata_decoding_closure(value: str) -> None:
    encoded_size = len(value.encode("utf-8"))
    if encoded_size > _MAX_METADATA_VALUE_BYTES:
        raise CapabilityV3ContractError("metadata value exceeds decoding byte budget")
    queue: list[tuple[str, int, tuple[str, ...]]] = [(value, 0, ())]
    seen: set[str] = set()
    total_bytes = 0
    while queue:
        current, depth, ancestors = queue.pop(0)
        if current in seen:
            continue
        if current in ancestors:
            raise CapabilityV3ContractError("metadata decoding cycle detected")
        seen.add(current)
        if len(seen) > _MAX_METADATA_REPRESENTATIONS:
            raise CapabilityV3ContractError("metadata decoding representation budget exceeded")
        total_bytes += len(current.encode("utf-8"))
        if total_bytes > _MAX_METADATA_TOTAL_BYTES:
            raise CapabilityV3ContractError("metadata decoding expansion budget exceeded")
        _scan_metadata_representation(current)
        normalized = unicodedata.normalize("NFKC", current)
        candidates: list[str] = []
        if normalized != current:
            candidates.append(normalized)
        percent = _canonical_percent_decode(current)
        if percent is not None:
            candidates.append(percent)
        decoded64 = _canonical_base64_decode(current)
        if decoded64 is not None:
            candidates.append(decoded64)
        if depth >= _MAX_METADATA_DECODE_DEPTH and candidates:
            raise CapabilityV3ContractError("metadata decoding depth exceeded")
        for candidate in candidates:
            if candidate in ancestors:
                raise CapabilityV3ContractError("metadata decoding cycle detected")
            queue.append((candidate, depth + 1, ancestors + (current,)))


def _text(value: object, label: str, maximum: int, *, empty: bool = False) -> str:
    if type(value) is not str or value != value.strip() or (not value and not empty):
        raise CapabilityV3ContractError(f"{label} must be a canonical exact string")
    if len(value) > maximum or any(
        (ord(ch) < 32 and ch not in {"\t", "\n", "\r"}) or ord(ch) == 127 for ch in value
    ):
        raise CapabilityV3ContractError(f"{label} is out of bounds")
    if _secret_canary(value):
        raise CapabilityV3ContractError(f"{label} resembles secret material")
    return value


def _slug(value: object, label: str) -> str:
    result = _text(value, label, 128)
    if not _SLUG.fullmatch(result):
        raise CapabilityV3ContractError(f"{label} is not a canonical slug")
    return result


def _identifier(value: object, label: str) -> str:
    result = _text(value, label, 128)
    if not _IDENT.fullmatch(result):
        raise CapabilityV3ContractError(f"{label} is not a canonical identifier")
    return result


def _strings(value: object, label: str, *, count: int = 32, size: int = 128, required: bool = False) -> tuple[str, ...]:
    if type(value) not in {tuple, list} or len(value) > count or (required and not value):
        raise CapabilityV3ContractError(f"{label} cardinality is invalid")
    result = tuple(_text(item, f"{label} item", size) for item in value)
    if len(set(result)) != len(result):
        raise CapabilityV3ContractError(f"{label} contains duplicates")
    return tuple(sorted(result))


def _reject_json_secrets(value: object, label: str) -> None:
    if isinstance(value, Mapping):
        if len(value) > 512:
            raise CapabilityV3ContractError(f"{label} is too large")
        for key, item in value.items():
            key = _text(key, f"{label} key", 128)
            if _normalized_name(key) in _SECRET_NAMES:
                raise CapabilityV3ContractError(f"{label} contains a secret-name field")
            _reject_json_secrets(item, f"{label}.{key}")
    elif isinstance(value, (tuple, list)):
        if len(value) > 512:
            raise CapabilityV3ContractError(f"{label} is too large")
        for item in value:
            _reject_json_secrets(item, label)
    elif isinstance(value, str):
        _text(value, label, 32768, empty=True)
    elif value is not None:
        if type(value) not in {bool, int, float}:
            raise CapabilityV3ContractError(f"{label} contains an unsupported value")
        if type(value) is float and not math.isfinite(value):
            raise CapabilityV3ContractError(f"{label} contains a non-finite number")
        if type(value) is int and not -(2**63) <= value <= 2**63 - 1:
            raise CapabilityV3ContractError(f"{label} integer is out of bounds")


def _json(value: object, label: str, maximum: int = 65536) -> str:
    _reject_json_secrets(value, label)
    try:
        result = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CapabilityV3ContractError(f"{label} is not canonical JSON") from exc
    if len(result.encode("utf-8")) > maximum:
        raise CapabilityV3ContractError(f"{label} exceeds its byte budget")
    return result


def _sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _safe_metadata(value: object) -> tuple[tuple[str, str], ...]:
    if type(value) not in {tuple, list} or len(value) > len(_SAFE_METADATA_KEYS):
        raise CapabilityV3ContractError("metadata must be bounded key/value pairs")
    result: list[tuple[str, str]] = []
    for pair in value:
        if type(pair) not in {tuple, list} or len(pair) != 2:
            raise CapabilityV3ContractError("metadata entry is invalid")
        key = _text(pair[0], "metadata key", 64)
        if _normalized_name(key) in _SECRET_NAMES or key not in _SAFE_METADATA_KEYS:
            raise CapabilityV3ContractError("metadata key is not declared safe")
        item = _text(pair[1], f"metadata {key}", 512)
        _validate_metadata_decoding_closure(item)
        if key == "declaration_sha256" and not _HEX64.fullmatch(item):
            raise CapabilityV3ContractError("declaration_sha256 is invalid")
        result.append((key, item))
    if len({key for key, _ in result}) != len(result):
        raise CapabilityV3ContractError("metadata key is duplicated")
    return tuple(sorted(result))


@dataclass(frozen=True, slots=True)
class OperationDescriptorV3:
    operation_id: str
    kind: OperationKindV3
    description: str
    parameter_schema_json: str
    required_scopes: tuple[str, ...]
    data_classes: tuple[str, ...]
    risk_class: str
    approval_class: str
    allowed_targets: tuple[str, ...] = ()
    allowed_domains: tuple[str, ...] = ()
    pagination: str = "unsupported"
    rate_limit: str = "host_policy"
    cancellation: str = "bounded"
    timeout: str = "bounded"
    idempotency: str = "correlation_only"
    receipt: str = "read_observation"
    reconciliation: str = "read_state_only"
    quota: str = "unknown"
    cost: str = "unknown"
    dry_run: str = "unsupported"
    test_account: str = "required_before_activation"
    host_policy: str = "always_confirm"

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", _slug(self.operation_id, "operation_id"))
        if type(self.kind) is not OperationKindV3:
            raise CapabilityV3ContractError("operation kind must be exact")
        object.__setattr__(self, "description", _text(self.description, "description", 4096))
        if type(self.parameter_schema_json) is not str:
            raise CapabilityV3ContractError("parameter schema must be exact string")
        try:
            parsed = json.loads(self.parameter_schema_json)
        except json.JSONDecodeError as exc:
            raise CapabilityV3ContractError("parameter schema is invalid") from exc
        if _json(parsed, "parameter schema") != self.parameter_schema_json:
            raise CapabilityV3ContractError("parameter schema is noncanonical")
        object.__setattr__(self, "required_scopes", _strings(self.required_scopes, "required_scopes"))
        object.__setattr__(self, "data_classes", _strings(self.data_classes, "data_classes", required=True))
        object.__setattr__(self, "allowed_targets", _strings(self.allowed_targets, "allowed_targets"))
        domains = _strings(self.allowed_domains, "allowed_domains", size=253)
        if any(not _DOMAIN.fullmatch(item) or ".." in item for item in domains):
            raise CapabilityV3ContractError("allowed domain is invalid")
        object.__setattr__(self, "allowed_domains", domains)
        for name in (
            "risk_class", "approval_class", "pagination", "rate_limit", "cancellation", "timeout",
            "idempotency", "receipt", "reconciliation", "quota", "cost", "dry_run", "test_account", "host_policy",
        ):
            object.__setattr__(self, name, _slug(getattr(self, name), name))

    def payload(self) -> dict[str, object]:
        return {name: (getattr(self, name).value if isinstance(getattr(self, name), Enum) else list(getattr(self, name)) if isinstance(getattr(self, name), tuple) else getattr(self, name)) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class CapabilityDescriptorV3:
    capability_id: str
    capability_version: str
    provider: str
    transport: TransportKindV3
    api_name: str
    api_version: str
    workspace_id: str
    account_id: str
    profile_id: str
    credential_alias: str | None
    operations: tuple[OperationDescriptorV3, ...]
    status: CapabilityStatusV3 = CapabilityStatusV3.DISABLED
    status_reason: str = "candidate_not_activated"
    limitations: tuple[str, ...] = ()
    license_review: str = "not_required_local_only"
    metadata: tuple[tuple[str, str], ...] = ()
    schema_version: str = CAPABILITY_SCHEMA_VERSION_V3

    def __post_init__(self) -> None:
        if self.schema_version != CAPABILITY_SCHEMA_VERSION_V3:
            raise CapabilityV3ContractError("unknown descriptor schema")
        for name in ("capability_id", "capability_version", "provider", "api_name", "api_version"):
            object.__setattr__(self, name, _slug(getattr(self, name), name))
        if type(self.transport) is not TransportKindV3 or type(self.status) is not CapabilityStatusV3:
            raise CapabilityV3ContractError("descriptor enum type is invalid")
        for name in ("workspace_id", "account_id", "profile_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.credential_alias is not None and (
            type(self.credential_alias) is not str or not _ALIAS.fullmatch(self.credential_alias)
        ):
            raise CapabilityV3ContractError("credential_alias must be opaque")
        if type(self.operations) not in {tuple, list} or not self.operations or len(self.operations) > 64:
            raise CapabilityV3ContractError("operation cardinality is invalid")
        operations = tuple(self.operations)
        if any(type(item) is not OperationDescriptorV3 for item in operations):
            raise CapabilityV3ContractError("operation descriptor type is invalid")
        if len({item.operation_id for item in operations}) != len(operations):
            raise CapabilityV3ContractError("duplicate operation")
        object.__setattr__(self, "operations", tuple(sorted(operations, key=lambda item: item.operation_id)))
        object.__setattr__(self, "status_reason", _slug(self.status_reason, "status_reason"))
        object.__setattr__(self, "limitations", _strings(self.limitations, "limitations", size=256))
        object.__setattr__(self, "license_review", _slug(self.license_review, "license_review"))
        object.__setattr__(self, "metadata", _safe_metadata(self.metadata))
        if self.status is CapabilityStatusV3.DEGRADED and self.status_reason == "healthy":
            raise CapabilityV3ContractError("degraded descriptor requires a reason")
        if self.transport is TransportKindV3.BROWSER and dict(self.metadata).get("fallback_class") != "explicit_browser_fallback":
            raise CapabilityV3ContractError("browser fallback is not explicit")

    def payload(self) -> dict[str, object]:
        return {
            "account_id": self.account_id, "api_name": self.api_name, "api_version": self.api_version,
            "capability_id": self.capability_id, "capability_version": self.capability_version,
            "credential_alias": self.credential_alias, "license_review": self.license_review,
            "limitations": list(self.limitations), "metadata": [list(item) for item in self.metadata],
            "operations": [item.payload() for item in self.operations], "profile_id": self.profile_id,
            "provider": self.provider, "schema_version": self.schema_version, "status": self.status.value,
            "status_reason": self.status_reason, "transport": self.transport.value, "workspace_id": self.workspace_id,
        }

    @property
    def digest(self) -> str:
        return _sha(self.payload())


@dataclass(frozen=True, slots=True)
class NexusFeatureGateV3:
    nexus_enabled: bool = False
    shadow_mode: bool = True
    dispatch_enabled: bool = False
    contract_version: str = NEXUS_CONTRACT_VERSION_V3

    def __post_init__(self) -> None:
        if type(self.nexus_enabled) is not bool or type(self.shadow_mode) is not bool or type(self.dispatch_enabled) is not bool:
            raise CapabilityV3ContractError("gate values must be exact booleans")
        if self.contract_version != NEXUS_CONTRACT_VERSION_V3:
            raise CapabilityV3ContractError("gate contract version is invalid")
        if self.nexus_enabled or not self.shadow_mode or self.dispatch_enabled:
            raise CapabilityV3ContractError("V3 is strictly default-off and shadow-only")


@dataclass(frozen=True, slots=True)
class CapabilityProjectionV3:
    descriptor: CapabilityDescriptorV3
    descriptor_digest: str
    workspace_id: str
    account_id: str
    profile_id: str
    projection_status: CapabilityStatusV3
    projection_reason: str
    runtime_available: bool = False
    authority_granted: bool = False

    def __post_init__(self) -> None:
        if type(self.descriptor) is not CapabilityDescriptorV3 or self.descriptor_digest != self.descriptor.digest:
            raise CapabilityV3ContractError("projection descriptor binding drift")
        if (
            self.workspace_id != self.descriptor.workspace_id
            or self.account_id != self.descriptor.account_id
            or self.profile_id != self.descriptor.profile_id
        ):
            raise CapabilityV3ContractError("projection identity binding drift")
        if type(self.projection_status) is not CapabilityStatusV3:
            raise CapabilityV3ContractError("projection status is invalid")
        object.__setattr__(self, "projection_reason", _slug(self.projection_reason, "projection_reason"))
        if type(self.runtime_available) is not bool or type(self.authority_granted) is not bool:
            raise CapabilityV3ContractError("projection booleans must be exact")
        if self.runtime_available or self.authority_granted:
            raise CapabilityV3ContractError("V3 projections cannot convey authority")

    def digest_payload(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "descriptor_digest": self.descriptor_digest,
            "profile_id": self.profile_id,
            "projection_reason": self.projection_reason,
            "projection_status": self.projection_status.value,
            "workspace_id": self.workspace_id,
        }


@dataclass(frozen=True, slots=True)
class CapabilitySnapshotV3:
    workspace_id: str
    account_id: str
    profile_id: str
    entries: tuple[CapabilityProjectionV3, ...]
    snapshot_digest: str
    contract_version: str = NEXUS_CONTRACT_VERSION_V3

    def __post_init__(self) -> None:
        if self.contract_version != NEXUS_CONTRACT_VERSION_V3:
            raise CapabilityV3ContractError("snapshot contract version is invalid")
        for name in ("workspace_id", "account_id", "profile_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if type(self.entries) is not tuple or any(type(item) is not CapabilityProjectionV3 for item in self.entries):
            raise CapabilityV3ContractError("snapshot entries are invalid")
        if any(
            item.workspace_id != self.workspace_id
            or item.account_id != self.account_id
            or item.profile_id != self.profile_id
            for item in self.entries
        ):
            raise CapabilityV3ContractError("snapshot contains a cross-profile projection")
        expected = _sha(
            {
                "account_id": self.account_id,
                "contract_version": self.contract_version,
                "entries": [item.digest_payload() for item in self.entries],
                "profile_id": self.profile_id,
                "workspace_id": self.workspace_id,
            }
        )
        if self.snapshot_digest != expected:
            raise CapabilityV3ContractError("snapshot digest is invalid")


class CapabilityNexusV3:
    """Descriptor-only registry; lock order is gate immutable -> registry."""

    def __init__(self, gate: NexusFeatureGateV3 | None = None) -> None:
        if gate is None:
            gate = NexusFeatureGateV3()
        if type(gate) is not NexusFeatureGateV3:
            raise CapabilityV3ContractError("registry requires the exact concrete V3 gate")
        self._gate = gate
        self._descriptors: dict[str, CapabilityDescriptorV3] = {}
        self._revoked_aliases: set[str] = set()
        self._kill = False
        self._lock = threading.RLock()

    @property
    def gate(self) -> NexusFeatureGateV3:
        return self._gate

    @property
    def lock_order(self) -> tuple[str, ...]:
        return LOCK_ORDER_V3

    def register(self, descriptor: CapabilityDescriptorV3) -> str:
        if type(descriptor) is not CapabilityDescriptorV3:
            raise CapabilityV3ContractError("registry descriptor type is invalid")
        with self._lock:
            if descriptor.capability_id in self._descriptors:
                raise CapabilityV3ContractError("duplicate capability")
            self._descriptors[descriptor.capability_id] = descriptor
            return descriptor.digest

    def revoke_alias(self, alias: str) -> None:
        if type(alias) is not str or not _ALIAS.fullmatch(alias):
            raise CapabilityV3ContractError("credential alias is invalid")
        with self._lock:
            self._revoked_aliases.add(alias)

    def set_kill(self, active: bool) -> None:
        if type(active) is not bool:
            raise CapabilityV3ContractError("kill state must be exact boolean")
        with self._lock:
            self._kill = active

    def discover(
        self,
        capability_id: str,
        *,
        workspace_id: str,
        account_id: str,
        profile_id: str,
        expected_version: str,
        expected_digest: str,
    ) -> CapabilityProjectionV3:
        capability_id = _slug(capability_id, "capability_id")
        workspace_id = _identifier(workspace_id, "workspace_id")
        account_id = _identifier(account_id, "account_id")
        profile_id = _identifier(profile_id, "profile_id")
        expected_version = _slug(expected_version, "expected_version")
        expected_digest = _text(expected_digest, "expected_digest", 64)
        if not _HEX64.fullmatch(expected_digest):
            raise CapabilityV3ContractError("expected digest is invalid")
        with self._lock:
            descriptor = self._descriptors.get(capability_id)
            if descriptor is None:
                raise CapabilityV3DeniedError("unknown capability")
            if (
                descriptor.workspace_id != workspace_id
                or descriptor.account_id != account_id
                or descriptor.profile_id != profile_id
            ):
                raise CapabilityV3DeniedError("workspace/account/profile mismatch")
            if descriptor.capability_version != expected_version or descriptor.digest != expected_digest:
                raise CapabilityV3DeniedError("version or descriptor drift")
            status, reason = self._status(descriptor)
            return CapabilityProjectionV3(
                descriptor, descriptor.digest, workspace_id, account_id, profile_id, status, reason
            )

    def health_projection(self, *args: object, **kwargs: object) -> CapabilityProjectionV3:
        return self.discover(*args, **kwargs)

    def snapshot(self, *, workspace_id: str, account_id: str, profile_id: str) -> CapabilitySnapshotV3:
        workspace_id = _identifier(workspace_id, "workspace_id")
        account_id = _identifier(account_id, "account_id")
        profile_id = _identifier(profile_id, "profile_id")
        with self._lock:
            entries = tuple(
                CapabilityProjectionV3(
                    descriptor,
                    descriptor.digest,
                    workspace_id,
                    account_id,
                    profile_id,
                    *self._status(descriptor),
                )
                for descriptor in sorted(self._descriptors.values(), key=lambda item: item.capability_id)
                if descriptor.workspace_id == workspace_id
                and descriptor.account_id == account_id
                and descriptor.profile_id == profile_id
            )
        payload = {
            "account_id": account_id,
            "contract_version": NEXUS_CONTRACT_VERSION_V3,
            "entries": [item.digest_payload() for item in entries],
            "profile_id": profile_id,
            "workspace_id": workspace_id,
        }
        return CapabilitySnapshotV3(workspace_id, account_id, profile_id, entries, _sha(payload))

    def _status(self, descriptor: CapabilityDescriptorV3) -> tuple[CapabilityStatusV3, str]:
        if self._kill:
            return CapabilityStatusV3.DISABLED, "global_kill_active"
        if descriptor.credential_alias is not None and descriptor.credential_alias in self._revoked_aliases:
            return CapabilityStatusV3.BLOCKED_BY_ACCESS, "credential_alias_revoked"
        if descriptor.status is CapabilityStatusV3.AVAILABLE_READ_ONLY:
            return CapabilityStatusV3.DISABLED, "nexus_default_off_shadow_only"
        return descriptor.status, descriptor.status_reason


@dataclass(frozen=True, slots=True)
class LegacyParityRecordV3:
    tool_name: str
    host_policy: str
    declaration_json: str
    declaration_digest: str


@dataclass(frozen=True, slots=True)
class LegacyDescriptorSetV3:
    descriptors: tuple[CapabilityDescriptorV3, ...]
    parity_records: tuple[LegacyParityRecordV3, ...]
    snapshot_digest: str

    def declarations(self) -> tuple[dict[str, object], ...]:
        return tuple(json.loads(item.declaration_json) for item in self.parity_records)

    def policy_mapping(self) -> Mapping[str, str]:
        return MappingProxyType({item.tool_name: item.host_policy for item in self.parity_records})


def build_legacy_descriptors_v3(
    tool_declarations: Sequence[Mapping[str, object]],
    policy_mapping: Mapping[str, str],
    *,
    workspace_id: str,
    account_id: str,
    profile_id: str,
    operation_kinds: Mapping[str, OperationKindV3] | None = None,
) -> LegacyDescriptorSetV3:
    if type(tool_declarations) not in {tuple, list} or not tool_declarations or len(tool_declarations) > 128:
        raise CapabilityV3ContractError("legacy declarations are invalid")
    if not isinstance(policy_mapping, Mapping):
        raise CapabilityV3ContractError("legacy policy mapping is invalid")
    workspace_id = _identifier(workspace_id, "workspace_id")
    account_id = _identifier(account_id, "account_id")
    profile_id = _identifier(profile_id, "profile_id")
    parsed: list[tuple[str, Mapping[str, object], str]] = []
    seen: set[str] = set()
    for raw in tool_declarations:
        if not isinstance(raw, Mapping) or set(raw) != {"name", "description", "parameters"}:
            raise CapabilityV3ContractError("legacy declaration shape drift")
        name = _slug(raw.get("name"), "tool name")
        if name in seen:
            raise CapabilityV3ContractError("duplicate legacy declaration")
        seen.add(name)
        _text(raw.get("description"), "legacy description", 4096)
        if not isinstance(raw.get("parameters"), Mapping):
            raise CapabilityV3ContractError("legacy parameter schema is invalid")
        encoded = _json(dict(raw), "legacy declaration")
        parsed.append((name, raw, encoded))
    if set(policy_mapping) != seen:
        raise CapabilityV3ContractError("legacy policy coverage is not exact")
    if operation_kinds is not None and set(operation_kinds) != seen:
        raise CapabilityV3ContractError("legacy operation coverage is not exact")
    descriptors: list[CapabilityDescriptorV3] = []
    records: list[LegacyParityRecordV3] = []
    for name, raw, encoded in parsed:
        policy = _slug(policy_mapping[name], "host policy")
        kind = OperationKindV3.MUTATE if operation_kinds is None else operation_kinds[name]
        if type(kind) is not OperationKindV3:
            raise CapabilityV3ContractError("legacy operation kind is invalid")
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        operation = OperationDescriptorV3(
            name,
            kind,
            str(raw["description"]),
            _json(raw["parameters"], "parameter schema"),
            (),
            ("legacy_unclassified",),
            "legacy_host_policy",
            policy,
            pagination="legacy_unchanged",
            rate_limit="legacy_unchanged",
            cancellation="legacy_unchanged",
            timeout="legacy_unchanged",
            idempotency="legacy_unchanged",
            receipt="legacy_unchanged",
            reconciliation="legacy_unchanged",
            quota="legacy_unknown",
            cost="legacy_unknown",
            dry_run="legacy_unchanged",
            test_account="legacy_unchanged",
            host_policy=policy,
        )
        descriptors.append(
            CapabilityDescriptorV3(
                f"legacy.{name}", "v3", "onyx_legacy", TransportKindV3.LEGACY,
                "legacy_dispatcher", "unchanged", workspace_id, account_id, profile_id, None,
                (operation,), CapabilityStatusV3.DISABLED, "shadow_descriptor_only",
                ("legacy_behavior_unchanged", "no_authority", "no_dispatch"),
                "existing_runtime_not_relicensed",
                (("declaration_sha256", digest), ("dispatch_path", "legacy_unchanged"), ("policy_source", "trusted_host_mapping")),
            )
        )
        records.append(LegacyParityRecordV3(name, policy, encoded, digest))
    descriptors.sort(key=lambda item: item.capability_id)
    records.sort(key=lambda item: item.tool_name)
    payload = {
        "descriptors": [item.payload() for item in descriptors],
        "records": [
            {"declaration_digest": item.declaration_digest, "declaration_json": item.declaration_json,
             "host_policy": item.host_policy, "tool_name": item.tool_name}
            for item in records
        ],
    }
    return LegacyDescriptorSetV3(tuple(descriptors), tuple(records), _sha(payload))


@dataclass(frozen=True, slots=True)
class CatalogItemV3:
    item_id: str
    label: str
    category: str
    item_version: str
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _identifier(self.item_id, "item_id"))
        object.__setattr__(self, "label", _text(self.label, "label", 160))
        object.__setattr__(self, "category", _slug(self.category, "category"))
        object.__setattr__(self, "item_version", _slug(self.item_version, "item_version"))
        object.__setattr__(self, "tags", _strings(self.tags, "tags", count=16, size=48))

    def payload(self) -> dict[str, object]:
        return {"category": self.category, "item_id": self.item_id, "item_version": self.item_version,
                "label": self.label, "tags": list(self.tags)}


@dataclass(frozen=True, slots=True)
class CancellationTokenV3:
    _event: threading.Event = field(default_factory=threading.Event, init=False, repr=False, compare=False)

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True, slots=True)
class CatalogReadRequestV3:
    workspace_id: str
    account_id: str
    profile_id: str
    target: str
    correlation_id: str
    page_size: int = 25
    cursor: str | None = None
    timeout_ms: int = 1000
    cancellation: CancellationTokenV3 | None = None

    def __post_init__(self) -> None:
        for name in ("workspace_id", "account_id", "profile_id", "target", "correlation_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if type(self.page_size) is not int or not 1 <= self.page_size <= 100:
            raise CapabilityV3ContractError("page_size is invalid")
        if self.cursor is not None:
            object.__setattr__(self, "cursor", _text(self.cursor, "cursor", 2048))
        if type(self.timeout_ms) is not int or not 1 <= self.timeout_ms <= 30_000:
            raise CapabilityV3ContractError("timeout_ms is invalid")
        if self.cancellation is not None and type(self.cancellation) is not CancellationTokenV3:
            raise CapabilityV3ContractError("cancellation token type is invalid")


@dataclass(frozen=True, slots=True)
class ConnectorHealthV3:
    status: CapabilityStatusV3
    reason: str
    workspace_id: str
    account_id: str
    profile_id: str
    api_version: str
    required_scopes: tuple[str, ...]
    granted_scopes: tuple[str, ...]
    quota_remaining: int
    ledger_entries: int
    pending_entries: int
    uncertain_entries: int
    cost_micros: int = 0
    authority_granted: bool = False


@dataclass(frozen=True, slots=True)
class CatalogReadProjectionV3:
    state: ReadStateV3
    failure_class: ReadFailureClassV3
    correlation_id: str
    request_digest: str
    workspace_id: str
    account_id: str
    profile_id: str
    items: tuple[CatalogItemV3, ...]
    next_cursor: str | None
    receipt_digest: str | None
    quota_remaining: int
    retry_after_ms: int | None = None
    authority_granted: bool = False

    def __post_init__(self) -> None:
        if type(self.state) is not ReadStateV3 or type(self.failure_class) is not ReadFailureClassV3:
            raise CapabilityV3ContractError("read projection enum is invalid")
        if self.authority_granted or type(self.authority_granted) is not bool:
            raise CapabilityV3ContractError("read projection cannot grant authority")
        if self.state is not ReadStateV3.COMPLETED and self.items:
            raise CapabilityV3ContractError("non-completed projection cannot expose items")
        if self.state is ReadStateV3.COMPLETED and (
            self.failure_class is not ReadFailureClassV3.NONE or self.receipt_digest is None
        ):
            raise CapabilityV3ContractError("completed projection is incomplete")


@dataclass(frozen=True, slots=True)
class _ReadLedgerEntryV3:
    request_digest: str
    workspace_id: str
    account_id: str
    profile_id: str
    state: ReadStateV3
    failure_class: ReadFailureClassV3
    items: tuple[CatalogItemV3, ...]
    next_cursor: str | None
    receipt_digest: str | None
    reserved_quota: int
    reservation_window: int | None
    created_at: float
    expires_at: float
    hook_started: bool
    retry_after_ms: int | None = None


class LocalCatalogReadAdapterV3:
    """In-memory read-only contract with a no-replay reservation ledger.

    Lock order is adapter lock only.  The hook is always called after releasing
    that lock; this adapter never acquires a registry lock.
    """

    CAPABILITY_ID = "local.catalog"
    REQUIRED_SCOPE = "catalog.metadata.read"
    TARGET = "local_catalog"

    def __init__(
        self,
        items: Sequence[CatalogItemV3],
        *,
        workspace_id: str,
        account_id: str,
        profile_id: str,
        cursor_signing_key: bytes,
        read_hook: Callable[[], None],
        credential_alias: str | None = None,
        auth_available: bool = True,
        granted_scopes: Sequence[str] = (REQUIRED_SCOPE,),
        status: CapabilityStatusV3 = CapabilityStatusV3.DISABLED,
        status_reason: str = "candidate_not_activated",
        quota_limit: int = 100,
        rate_limit: int = 10,
        ledger_capacity: int = 128,
        pending_capacity: int = 16,
        uncertain_capacity: int = 32,
        pending_ttl_seconds: float = 30.0,
        uncertain_ttl_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(items) not in {tuple, list} or len(items) > 1000:
            raise CapabilityV3ContractError("catalog items are invalid")
        copied = tuple(items)
        if any(type(item) is not CatalogItemV3 for item in copied) or len({item.item_id for item in copied}) != len(copied):
            raise CapabilityV3ContractError("catalog items must be exact and unique")
        self._items = tuple(sorted(copied, key=lambda item: item.item_id))
        self._workspace_id = _identifier(workspace_id, "workspace_id")
        self._account_id = _identifier(account_id, "account_id")
        self._profile_id = _identifier(profile_id, "profile_id")
        if type(cursor_signing_key) is not bytes or not 32 <= len(cursor_signing_key) <= 128:
            raise CapabilityV3ContractError("cursor signing key is invalid")
        self._cursor_key = bytes(cursor_signing_key)
        if not callable(read_hook) or not callable(clock):
            raise CapabilityV3ContractError("hook/clock must be callable")
        self._read_hook = read_hook
        self._clock = clock
        if credential_alias is not None and (type(credential_alias) is not str or not _ALIAS.fullmatch(credential_alias)):
            raise CapabilityV3ContractError("credential alias is invalid")
        self._credential_alias = credential_alias
        if type(auth_available) is not bool:
            raise CapabilityV3ContractError("auth state must be exact boolean")
        self._auth = auth_available
        self._scopes = frozenset(_strings(granted_scopes, "granted_scopes"))
        if type(status) is not CapabilityStatusV3 or status not in {
            CapabilityStatusV3.DISABLED, CapabilityStatusV3.AVAILABLE_READ_ONLY, CapabilityStatusV3.DEGRADED
        }:
            raise CapabilityV3ContractError("adapter status is invalid")
        self._status = status
        self._status_reason = _slug(status_reason, "status_reason")
        if status is CapabilityStatusV3.DEGRADED and status_reason == "healthy":
            raise CapabilityV3ContractError("degraded status requires reason")
        for name, value, lower, upper in (
            ("quota_limit", quota_limit, 1, 1_000_000), ("rate_limit", rate_limit, 1, 10000),
            ("ledger_capacity", ledger_capacity, 1, 4096),
            ("pending_capacity", pending_capacity, 1, 1024),
            ("uncertain_capacity", uncertain_capacity, 1, 1024),
        ):
            if type(value) is not int or not lower <= value <= upper:
                raise CapabilityV3ContractError(f"{name} is invalid")
        for name, value in (("pending_ttl_seconds", pending_ttl_seconds), ("uncertain_ttl_seconds", uncertain_ttl_seconds)):
            if type(value) not in {int, float} or not math.isfinite(value) or not 0.001 <= value <= 86_400:
                raise CapabilityV3ContractError(f"{name} is invalid")
        self._quota_limit = quota_limit
        self._rate_limit = rate_limit
        self._capacity = ledger_capacity
        if pending_capacity > uncertain_capacity or uncertain_capacity > ledger_capacity:
            raise CapabilityV3ContractError("pending/uncertain capacities exceed their parent bound")
        self._pending_capacity = pending_capacity
        self._uncertain_capacity = uncertain_capacity
        self._pending_ttl = float(pending_ttl_seconds)
        self._uncertain_ttl = float(uncertain_ttl_seconds)
        self._quota_used = 0
        self._window_second: int | None = None
        self._window_used = 0
        self._ledger: dict[str, _ReadLedgerEntryV3] = {}
        self._kill = False
        self._revoked = False
        self._lock = threading.RLock()
        self._snapshot_digest = _sha([item.payload() for item in self._items])

    @property
    def lock_order(self) -> tuple[str, ...]:
        return LOCK_ORDER_V3

    @property
    def descriptor(self) -> CapabilityDescriptorV3:
        operation = OperationDescriptorV3(
            "catalog_read", OperationKindV3.READ, "Read allowlisted provider-free catalog metadata.",
            _json({"properties": {"cursor": {"type": "STRING"}, "page_size": {"type": "INTEGER"}}, "type": "OBJECT"}, "catalog schema"),
            (self.REQUIRED_SCOPE,), ("allowlisted_metadata",), "low", "host_policy_required",
            (self.TARGET,), (), "signed_profile_bound_cursor", "fixed_window_reserved",
            "before_and_after_hook", "before_and_after_hook", "correlation_reservation_no_replay",
            "deterministic_completed_receipt", "pending_uncertain_completed", "exact_reserved_counter",
            "zero_local_micros", "read_only_not_applicable", "provider_free_fixture", "always_confirm",
        )
        return CapabilityDescriptorV3(
            self.CAPABILITY_ID, "v3", "onyx_local", TransportKindV3.LOCAL, "local_catalog",
            CATALOG_CONTRACT_VERSION_V3, self._workspace_id, self._account_id, self._profile_id,
            self._credential_alias, (operation,), self._status, self._status_reason,
            ("metadata_only", "no_live_wiring", "no_mutation", "provider_free"),
            metadata=(("data_source", "constructor_allowlist"),),
        )

    def set_kill(self, active: bool) -> None:
        if type(active) is not bool:
            raise CapabilityV3ContractError("kill state must be exact boolean")
        with self._lock:
            self._kill = active

    def revoke(self) -> None:
        with self._lock:
            self._revoked = True

    def health(self) -> ConnectorHealthV3:
        now = self._clock()
        with self._lock:
            self._expire_pending(now)
            status, reason, _ = self._effective_status()
            pending = sum(item.state is ReadStateV3.PENDING for item in self._ledger.values())
            uncertain = sum(item.state is ReadStateV3.UNCERTAIN for item in self._ledger.values())
            return ConnectorHealthV3(
                status, reason, self._workspace_id, self._account_id, self._profile_id,
                CATALOG_CONTRACT_VERSION_V3, (self.REQUIRED_SCOPE,), tuple(sorted(self._scopes)),
                max(0, self._quota_limit - self._quota_used), len(self._ledger), pending, uncertain,
            )

    def read_page(self, request: CatalogReadRequestV3) -> CatalogReadProjectionV3:
        if type(request) is not CatalogReadRequestV3:
            raise CapabilityV3ContractError("read request type is invalid")
        self._validate_binding(request)
        digest = self._request_digest(request)
        started = self._clock()
        with self._lock:
            self._expire_pending(started)
            prior = self._ledger.get(request.correlation_id)
            if prior is not None:
                if prior.request_digest != digest:
                    raise CapabilityV3DeniedError("correlation request drift")
                return self._projection(request.correlation_id, prior)
            if len(self._ledger) >= self._capacity:
                raise CapabilityV3DeniedError("correlation ledger capacity exhausted")
            if request.cancellation is not None and request.cancellation.cancelled:
                entry = self._terminal_without_reservation(
                    request, digest, ReadStateV3.CANCELLED_BEFORE_HOOK, ReadFailureClassV3.CANCELLED, started
                )
                self._ledger[request.correlation_id] = entry
                return self._projection(request.correlation_id, entry)
            status, reason, failure = self._effective_status()
            if status not in {CapabilityStatusV3.AVAILABLE_READ_ONLY, CapabilityStatusV3.DEGRADED}:
                entry = self._terminal_without_reservation(request, digest, ReadStateV3.DENIED, failure, started)
                self._ledger[request.correlation_id] = entry
                return self._projection(request.correlation_id, entry)
            window = int(started)
            if self._window_second != window:
                self._window_second, self._window_used = window, 0
            if self._window_used >= self._rate_limit:
                entry = self._terminal_without_reservation(
                    request, digest, ReadStateV3.RATE_LIMITED, ReadFailureClassV3.RATE_LIMIT, started, retry_after_ms=1000
                )
                self._ledger[request.correlation_id] = entry
                return self._projection(request.correlation_id, entry)
            if self._quota_used >= self._quota_limit:
                entry = self._terminal_without_reservation(
                    request, digest, ReadStateV3.DENIED, ReadFailureClassV3.QUOTA, started
                )
                self._ledger[request.correlation_id] = entry
                return self._projection(request.correlation_id, entry)
            pending_count = sum(item.state is ReadStateV3.PENDING for item in self._ledger.values())
            uncertain_count = sum(item.state is ReadStateV3.UNCERTAIN for item in self._ledger.values())
            if pending_count >= self._pending_capacity or pending_count + uncertain_count >= self._uncertain_capacity:
                raise CapabilityV3DeniedError("pending/uncertain ledger capacity exhausted")
            offset = self._decode_cursor(request.cursor) if request.cursor else 0
            page = self._items[offset : offset + request.page_size]
            next_offset = offset + len(page)
            next_cursor = self._encode_cursor(next_offset) if next_offset < len(self._items) else None
            self._quota_used += 1
            self._window_used += 1
            entry = _ReadLedgerEntryV3(
                digest, self._workspace_id, self._account_id, self._profile_id,
                ReadStateV3.PENDING, ReadFailureClassV3.NONE, page, next_cursor, None, 1,
                window, started, started + self._pending_ttl, False,
            )
            self._ledger[request.correlation_id] = entry

        # No adapter, registry, or gate lock is held beyond this point.
        pre_hook_now = self._clock()
        if request.cancellation is not None and request.cancellation.cancelled:
            return self._finish_before_hook(
                request, digest, ReadStateV3.CANCELLED_BEFORE_HOOK, ReadFailureClassV3.CANCELLED, pre_hook_now
            )
        if (pre_hook_now - started) * 1000 >= request.timeout_ms:
            return self._finish_before_hook(
                request, digest, ReadStateV3.TIMEOUT_BEFORE_HOOK, ReadFailureClassV3.TIMEOUT, pre_hook_now
            )
        with self._lock:
            current = self._ledger[request.correlation_id]
            status, _, failure = self._effective_status()
            if status not in {CapabilityStatusV3.AVAILABLE_READ_ONLY, CapabilityStatusV3.DEGRADED}:
                return self._finish_before_hook_locked(
                    request.correlation_id, current, ReadStateV3.DENIED, failure, pre_hook_now
                )
            current = replace(current, hook_started=True)
            self._ledger[request.correlation_id] = current
        try:
            self._read_hook()
        except Exception:
            failed_at = self._clock()
            with self._lock:
                current = self._ledger[request.correlation_id]
                if current.state is not ReadStateV3.PENDING:
                    return self._projection(request.correlation_id, current)
                uncertain = replace(
                    current, state=ReadStateV3.UNCERTAIN, failure_class=ReadFailureClassV3.HOOK_EXCEPTION,
                    items=(), next_cursor=None, expires_at=failed_at + self._uncertain_ttl,
                )
                self._ledger[request.correlation_id] = uncertain
                return self._projection(request.correlation_id, uncertain)
        finished = self._clock()
        with self._lock:
            current = self._ledger[request.correlation_id]
            if current.state is not ReadStateV3.PENDING:
                return self._projection(request.correlation_id, current)
            status, _, failure = self._effective_status()
            if request.cancellation is not None and request.cancellation.cancelled:
                return self._finish_uncertain_locked(request.correlation_id, current, ReadFailureClassV3.CANCELLED, finished)
            if (finished - started) * 1000 >= request.timeout_ms:
                return self._finish_uncertain_locked(request.correlation_id, current, ReadFailureClassV3.TIMEOUT, finished)
            if status not in {CapabilityStatusV3.AVAILABLE_READ_ONLY, CapabilityStatusV3.DEGRADED}:
                return self._finish_uncertain_locked(request.correlation_id, current, failure, finished)
            receipt = _sha(
                {"account_id": current.account_id, "correlation_id": request.correlation_id,
                 "item_ids": [item.item_id for item in current.items], "next_cursor": current.next_cursor,
                 "profile_id": current.profile_id, "request_digest": current.request_digest,
                 "state": ReadStateV3.COMPLETED.value, "workspace_id": current.workspace_id}
            )
            completed = replace(
                current, state=ReadStateV3.COMPLETED, failure_class=ReadFailureClassV3.NONE,
                receipt_digest=receipt, expires_at=finished + self._uncertain_ttl,
            )
            self._ledger[request.correlation_id] = completed
            return self._projection(request.correlation_id, completed)

    def reconcile(self, request: CatalogReadRequestV3) -> CatalogReadProjectionV3:
        if type(request) is not CatalogReadRequestV3:
            raise CapabilityV3ContractError("reconcile request type is invalid")
        self._validate_binding(request)
        digest = self._request_digest(request)
        now = self._clock()
        with self._lock:
            self._expire_pending(now)
            entry = self._ledger.get(request.correlation_id)
            if entry is None:
                return CatalogReadProjectionV3(
                    ReadStateV3.UNKNOWN_CORRELATION, ReadFailureClassV3.UNKNOWN,
                    request.correlation_id, digest, self._workspace_id, self._account_id, self._profile_id,
                    (), None, None, max(0, self._quota_limit - self._quota_used),
                )
            if entry.request_digest != digest:
                raise CapabilityV3DeniedError("correlation request drift")
            return self._projection(request.correlation_id, entry)

    def draft(self, *_args: object, **_kwargs: object) -> None:
        raise CapabilityV3DeniedError("catalog adapter has no draft operation")

    def mutate(self, *_args: object, **_kwargs: object) -> None:
        raise CapabilityV3DeniedError("catalog adapter has no mutation operation")

    def _validate_binding(self, request: CatalogReadRequestV3) -> None:
        if (
            request.workspace_id != self._workspace_id or request.account_id != self._account_id
            or request.profile_id != self._profile_id
        ):
            raise CapabilityV3DeniedError("workspace/account/profile mismatch")
        if request.target != self.TARGET:
            raise CapabilityV3DeniedError("target is not allowlisted")

    def _effective_status(self) -> tuple[CapabilityStatusV3, str, ReadFailureClassV3]:
        if self._kill:
            return CapabilityStatusV3.DISABLED, "global_kill_active", ReadFailureClassV3.KILL
        if self._revoked:
            return CapabilityStatusV3.BLOCKED_BY_ACCESS, "credential_alias_revoked", ReadFailureClassV3.REVOKED
        if not self._auth:
            return CapabilityStatusV3.BLOCKED_BY_ACCESS, "authentication_unavailable", ReadFailureClassV3.AUTH
        if self.REQUIRED_SCOPE not in self._scopes:
            return CapabilityStatusV3.BLOCKED_BY_SCOPE, "required_scope_missing", ReadFailureClassV3.SCOPE
        if self._status is CapabilityStatusV3.DISABLED:
            return self._status, self._status_reason, ReadFailureClassV3.DISABLED
        return self._status, self._status_reason, ReadFailureClassV3.NONE

    def _request_digest(self, request: CatalogReadRequestV3) -> str:
        return _sha(
            {"account_id": request.account_id, "correlation_id": request.correlation_id,
             "cursor": request.cursor, "page_size": request.page_size, "profile_id": request.profile_id,
             "target": request.target, "timeout_ms": request.timeout_ms, "workspace_id": request.workspace_id}
        )

    def _encode_cursor(self, offset: int) -> str:
        payload = {"account_id": self._account_id, "capability_id": self.CAPABILITY_ID,
                   "contract_version": CATALOG_CONTRACT_VERSION_V3, "offset": offset,
                   "profile_id": self._profile_id, "snapshot_digest": self._snapshot_digest,
                   "workspace_id": self._workspace_id}
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return body.hex() + "." + hmac.new(self._cursor_key, body, hashlib.sha256).hexdigest()

    def _decode_cursor(self, cursor: str) -> int:
        try:
            body_hex, signature = cursor.split(".", 1)
            body = bytes.fromhex(body_hex)
            expected = hmac.new(self._cursor_key, body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise CapabilityV3DeniedError("cursor integrity failure")
            payload = json.loads(body)
        except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise CapabilityV3DeniedError("cursor integrity failure") from exc
        expected_payload = {"account_id": self._account_id, "capability_id": self.CAPABILITY_ID,
                            "contract_version": CATALOG_CONTRACT_VERSION_V3,
                            "profile_id": self._profile_id, "snapshot_digest": self._snapshot_digest,
                            "workspace_id": self._workspace_id}
        if set(payload) != set(expected_payload) | {"offset"} or any(payload.get(k) != v for k, v in expected_payload.items()):
            raise CapabilityV3DeniedError("cursor profile/snapshot binding drift")
        offset = payload.get("offset")
        if type(offset) is not int or not 0 <= offset < len(self._items):
            raise CapabilityV3DeniedError("cursor offset is invalid")
        return offset

    def _terminal_without_reservation(
        self, request: CatalogReadRequestV3, digest: str, state: ReadStateV3,
        failure: ReadFailureClassV3, now: float, *, retry_after_ms: int | None = None,
    ) -> _ReadLedgerEntryV3:
        return _ReadLedgerEntryV3(
            digest, request.workspace_id, request.account_id, request.profile_id, state, failure,
            (), None, None, 0, None, now, now + self._uncertain_ttl, False, retry_after_ms,
        )

    def _finish_before_hook(
        self, request: CatalogReadRequestV3, digest: str, state: ReadStateV3, failure: ReadFailureClassV3,
        now: float,
    ) -> CatalogReadProjectionV3:
        with self._lock:
            current = self._ledger[request.correlation_id]
            if current.request_digest != digest:
                raise CapabilityV3DeniedError("correlation request drift")
            return self._finish_before_hook_locked(request.correlation_id, current, state, failure, now)

    def _finish_before_hook_locked(
        self, correlation_id: str, current: _ReadLedgerEntryV3, state: ReadStateV3,
        failure: ReadFailureClassV3, now: float,
    ) -> CatalogReadProjectionV3:
        if current.hook_started:
            return self._finish_uncertain_locked(correlation_id, current, failure, now)
        self._release_reservation(current)
        terminal = replace(
            current, state=state, failure_class=failure, items=(), next_cursor=None,
            reserved_quota=0, reservation_window=None, expires_at=now + self._uncertain_ttl,
        )
        self._ledger[correlation_id] = terminal
        return self._projection(correlation_id, terminal)

    def _finish_uncertain_locked(
        self, correlation_id: str, current: _ReadLedgerEntryV3,
        failure: ReadFailureClassV3, now: float,
    ) -> CatalogReadProjectionV3:
        uncertain = replace(
            current, state=ReadStateV3.UNCERTAIN, failure_class=failure,
            items=(), next_cursor=None, expires_at=now + self._uncertain_ttl,
        )
        self._ledger[correlation_id] = uncertain
        return self._projection(correlation_id, uncertain)

    def _release_reservation(self, entry: _ReadLedgerEntryV3) -> None:
        if entry.reserved_quota:
            self._quota_used = max(0, self._quota_used - entry.reserved_quota)
        if entry.reservation_window == self._window_second and self._window_used:
            self._window_used -= 1

    def _expire_pending(self, now: float) -> None:
        for correlation_id, entry in tuple(self._ledger.items()):
            if entry.state is ReadStateV3.PENDING and now >= entry.expires_at:
                uncertain = replace(
                    entry, state=ReadStateV3.UNCERTAIN,
                    failure_class=ReadFailureClassV3.EXPIRED_PENDING,
                    items=(), next_cursor=None, expires_at=now + self._uncertain_ttl,
                )
                self._ledger[correlation_id] = uncertain
            elif entry.state is ReadStateV3.UNCERTAIN and now >= entry.expires_at:
                self._ledger[correlation_id] = replace(
                    entry, state=ReadStateV3.EXPIRED_UNCERTAIN,
                    failure_class=ReadFailureClassV3.UNCERTAIN_EXPIRED,
                    items=(), next_cursor=None, expires_at=now,
                )

    def _projection(self, correlation_id: str, entry: _ReadLedgerEntryV3) -> CatalogReadProjectionV3:
        return CatalogReadProjectionV3(
            entry.state, entry.failure_class, correlation_id, entry.request_digest,
            entry.workspace_id, entry.account_id, entry.profile_id,
            entry.items if entry.state is ReadStateV3.COMPLETED else (),
            entry.next_cursor if entry.state is ReadStateV3.COMPLETED else None,
            entry.receipt_digest if entry.state is ReadStateV3.COMPLETED else None,
            max(0, self._quota_limit - self._quota_used), entry.retry_after_ms,
        )
