"""Default-off Capability Nexus contracts for the Phase 5.3 V1 candidate.

This module is deliberately isolated from the live dispatcher.  It describes
and projects capabilities, and supplies one provider-free read-only contract
fixture.  Nothing here authorizes or dispatches a legacy/model tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import hmac
import json
import math
import re
import threading
import time
from types import MappingProxyType
from typing import Callable, Iterable, Mapping, Sequence


CAPABILITY_SCHEMA_VERSION = "onyx.capability.v1"
NEXUS_CONTRACT_VERSION = "onyx.capability-nexus.v1"
CATALOG_CONTRACT_VERSION = "onyx.local-catalog.v1"


class CapabilityContractError(ValueError):
    """Raised when trusted-host metadata violates the V1 contract."""


class CapabilityDeniedError(PermissionError):
    """Fail-closed result for unavailable or mismatched capability access."""


class OperationKind(str, Enum):
    READ = "read"
    DRAFT = "draft"
    MUTATE = "mutate"
    VERIFY = "verify"
    RECONCILE = "reconcile"


class CapabilityStatus(str, Enum):
    DISABLED = "disabled"
    AVAILABLE_READ_ONLY = "available_read_only"
    DEGRADED = "degraded"
    BLOCKED_BY_ACCESS = "blocked_by_access"
    BLOCKED_BY_SCOPE = "blocked_by_scope"
    BLOCKED_BY_PLATFORM = "blocked_by_platform"
    BLOCKED_BY_LICENSE = "blocked_by_license"


class TransportKind(str, Enum):
    LEGACY = "legacy"
    LOCAL = "local"
    API = "api"
    CLI = "cli"
    SDK = "sdk"
    MCP = "mcp"
    BROWSER = "browser"


class ReconcileState(str, Enum):
    OBSERVED_READ = "observed_read"
    VERIFIED_NO_EXTERNAL_EFFECT = "verified_no_external_effect"
    UNKNOWN_CORRELATION = "unknown_correlation"


_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_IDENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_ALIAS_RE = re.compile(r"^alias:[a-z0-9][a-z0-9._/-]{0,95}$")
_DOMAIN_RE = re.compile(r"^(?:\*\.)?[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|cookie|authorization|bearer)\s*[:=]\s*[^\s,;]{8,}"
)
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}\b")


def _text(value: object, label: str, *, maximum: int, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise CapabilityContractError(f"{label} must be an exact string")
    if value != value.strip() or (not value and not allow_empty):
        raise CapabilityContractError(f"{label} is empty or not canonical")
    if len(value) > maximum or any(
        (ord(ch) < 32 and ch not in {"\t", "\n", "\r"}) or ord(ch) == 127 for ch in value
    ):
        raise CapabilityContractError(f"{label} is out of bounds")
    if "-----BEGIN " in value or _SECRET_ASSIGNMENT_RE.search(value) or _JWT_RE.search(value):
        raise CapabilityContractError(f"{label} resembles secret material")
    return value


def _slug(value: object, label: str) -> str:
    value = _text(value, label, maximum=128)
    if not _SLUG_RE.fullmatch(value):
        raise CapabilityContractError(f"{label} is not a canonical slug")
    return value


def _identifier(value: object, label: str) -> str:
    value = _text(value, label, maximum=128)
    if not _IDENT_RE.fullmatch(value):
        raise CapabilityContractError(f"{label} is not a canonical identifier")
    return value


def _string_tuple(
    value: object,
    label: str,
    *,
    maximum_items: int = 32,
    maximum_text: int = 128,
    require_nonempty: bool = False,
) -> tuple[str, ...]:
    if type(value) not in {tuple, list}:
        raise CapabilityContractError(f"{label} must be a bounded sequence")
    if len(value) > maximum_items or (require_nonempty and not value):
        raise CapabilityContractError(f"{label} cardinality is invalid")
    result = tuple(_text(item, f"{label} item", maximum=maximum_text) for item in value)
    if len(set(result)) != len(result):
        raise CapabilityContractError(f"{label} contains duplicates")
    return tuple(sorted(result))


def _canonical_json(value: object, label: str, *, maximum: int = 32768) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        decoded = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CapabilityContractError(f"{label} is not canonical JSON") from exc
    _reject_secret_shapes(decoded, label)
    if len(encoded.encode("utf-8")) > maximum:
        raise CapabilityContractError(f"{label} exceeds its byte budget")
    return encoded


def _reject_secret_shapes(value: object, label: str) -> None:
    if isinstance(value, str):
        _text(value, label, maximum=32768, allow_empty=True)
    elif isinstance(value, Mapping):
        if len(value) > 512:
            raise CapabilityContractError(f"{label} mapping is too large")
        for key, item in value.items():
            key_text = _text(key, f"{label} key", maximum=128)
            normalized_key = re.sub(r"[^a-z0-9]", "", key_text.lower())
            if normalized_key in {
                "password", "secret", "token", "accesstoken", "refreshtoken",
                "apikey", "cookie", "authorization", "privatekey",
            }:
                raise CapabilityContractError(f"{label} contains a secret-bearing field")
            _reject_secret_shapes(item, f"{label}.{key_text}")
    elif isinstance(value, (tuple, list)):
        if len(value) > 512:
            raise CapabilityContractError(f"{label} sequence is too large")
        for item in value:
            _reject_secret_shapes(item, label)
    elif value is not None:
        if type(value) not in {bool, int, float}:
            raise CapabilityContractError(f"{label} contains an unsupported value")
        if type(value) is float and not math.isfinite(value):
            raise CapabilityContractError(f"{label} contains a non-finite number")
        if type(value) is int and not -(2**63) <= value <= 2**63 - 1:
            raise CapabilityContractError(f"{label} contains an out-of-range integer")


def _sha(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class OperationDescriptor:
    """A single explicitly classified operation; it carries no authority."""

    operation_id: str
    kind: OperationKind
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
    cancellation: str = "pre_and_post_read"
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
        if type(self.kind) is not OperationKind:
            raise CapabilityContractError("operation kind must be an exact OperationKind")
        object.__setattr__(self, "description", _text(self.description, "description", maximum=2048))
        if type(self.parameter_schema_json) is not str:
            raise CapabilityContractError("parameter_schema_json must be an exact string")
        try:
            parsed = json.loads(self.parameter_schema_json)
        except json.JSONDecodeError as exc:
            raise CapabilityContractError("parameter schema is invalid") from exc
        canonical = _canonical_json(parsed, "parameter schema")
        if canonical != self.parameter_schema_json:
            raise CapabilityContractError("parameter schema is not canonical")
        object.__setattr__(self, "required_scopes", _string_tuple(self.required_scopes, "required_scopes"))
        object.__setattr__(
            self, "data_classes", _string_tuple(self.data_classes, "data_classes", require_nonempty=True)
        )
        object.__setattr__(self, "allowed_targets", _string_tuple(self.allowed_targets, "allowed_targets"))
        domains = _string_tuple(self.allowed_domains, "allowed_domains", maximum_text=253)
        if any(not _DOMAIN_RE.fullmatch(domain) or ".." in domain for domain in domains):
            raise CapabilityContractError("allowed_domains contains an invalid domain")
        object.__setattr__(self, "allowed_domains", domains)
        for name in (
            "risk_class", "approval_class", "pagination", "rate_limit", "cancellation",
            "timeout", "idempotency", "receipt", "reconciliation", "quota", "cost",
            "dry_run", "test_account", "host_policy",
        ):
            object.__setattr__(self, name, _slug(getattr(self, name), name))
        if self.kind is OperationKind.MUTATE and self.receipt == "unsupported":
            raise CapabilityContractError("mutation operations must declare receipt semantics")
        if self.kind is OperationKind.MUTATE and self.reconciliation == "unsupported":
            raise CapabilityContractError("mutation operations must declare reconciliation semantics")

    def payload(self) -> dict[str, object]:
        return {
            "allowed_domains": list(self.allowed_domains),
            "allowed_targets": list(self.allowed_targets),
            "approval_class": self.approval_class,
            "cancellation": self.cancellation,
            "cost": self.cost,
            "data_classes": list(self.data_classes),
            "description": self.description,
            "dry_run": self.dry_run,
            "host_policy": self.host_policy,
            "idempotency": self.idempotency,
            "kind": self.kind.value,
            "operation_id": self.operation_id,
            "pagination": self.pagination,
            "parameter_schema_json": self.parameter_schema_json,
            "quota": self.quota,
            "rate_limit": self.rate_limit,
            "receipt": self.receipt,
            "reconciliation": self.reconciliation,
            "required_scopes": list(self.required_scopes),
            "risk_class": self.risk_class,
            "test_account": self.test_account,
            "timeout": self.timeout,
        }


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """Immutable, versioned metadata for one capability implementation."""

    capability_id: str
    capability_version: str
    provider: str
    transport: TransportKind
    api_name: str
    api_version: str
    workspace_id: str
    account_id: str
    profile_id: str
    credential_alias: str | None
    operations: tuple[OperationDescriptor, ...]
    status: CapabilityStatus = CapabilityStatus.DISABLED
    status_reason: str = "candidate_not_activated"
    limitations: tuple[str, ...] = ()
    license_review: str = "not_required_local_only"
    metadata: tuple[tuple[str, str], ...] = ()
    schema_version: str = CAPABILITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CAPABILITY_SCHEMA_VERSION:
            raise CapabilityContractError("unknown capability schema version")
        object.__setattr__(self, "capability_id", _slug(self.capability_id, "capability_id"))
        object.__setattr__(self, "capability_version", _slug(self.capability_version, "capability_version"))
        object.__setattr__(self, "provider", _slug(self.provider, "provider"))
        if type(self.transport) is not TransportKind:
            raise CapabilityContractError("transport must be an exact TransportKind")
        object.__setattr__(self, "api_name", _slug(self.api_name, "api_name"))
        object.__setattr__(self, "api_version", _slug(self.api_version, "api_version"))
        for name in ("workspace_id", "account_id", "profile_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.credential_alias is not None:
            if type(self.credential_alias) is not str or not _ALIAS_RE.fullmatch(self.credential_alias):
                raise CapabilityContractError("credential_alias must be an opaque alias")
        if type(self.operations) not in {tuple, list} or not self.operations or len(self.operations) > 64:
            raise CapabilityContractError("operations cardinality is invalid")
        operations = tuple(self.operations)
        if any(type(item) is not OperationDescriptor for item in operations):
            raise CapabilityContractError("operations must contain exact descriptors")
        operation_ids = [item.operation_id for item in operations]
        if len(set(operation_ids)) != len(operation_ids):
            raise CapabilityContractError("duplicate operation descriptor")
        object.__setattr__(self, "operations", tuple(sorted(operations, key=lambda item: item.operation_id)))
        if type(self.status) is not CapabilityStatus:
            raise CapabilityContractError("status must be an exact CapabilityStatus")
        object.__setattr__(self, "status_reason", _slug(self.status_reason, "status_reason"))
        object.__setattr__(
            self, "limitations", _string_tuple(self.limitations, "limitations", maximum_items=32, maximum_text=256)
        )
        object.__setattr__(self, "license_review", _slug(self.license_review, "license_review"))
        if type(self.metadata) not in {tuple, list} or len(self.metadata) > 32:
            raise CapabilityContractError("metadata must be bounded key/value pairs")
        metadata: list[tuple[str, str]] = []
        for pair in self.metadata:
            if type(pair) not in {tuple, list} or len(pair) != 2:
                raise CapabilityContractError("metadata entry is invalid")
            key = _slug(pair[0], "metadata key")
            value = _text(pair[1], "metadata value", maximum=512)
            metadata.append((key, value))
        if len({key for key, _ in metadata}) != len(metadata):
            raise CapabilityContractError("duplicate metadata key")
        object.__setattr__(self, "metadata", tuple(sorted(metadata)))
        if self.status is CapabilityStatus.DEGRADED and self.status_reason == "healthy":
            raise CapabilityContractError("degraded capability requires a truthful reason")
        if self.transport is TransportKind.BROWSER and not self.allowed_browser_fallback_declared:
            raise CapabilityContractError("browser transport must be explicitly labeled")

    @property
    def allowed_browser_fallback_declared(self) -> bool:
        return dict(self.metadata).get("fallback_class") == "explicit_browser_fallback"

    def payload(self) -> dict[str, object]:
        return {
            "account_id": self.account_id,
            "api_name": self.api_name,
            "api_version": self.api_version,
            "capability_id": self.capability_id,
            "capability_version": self.capability_version,
            "credential_alias": self.credential_alias,
            "license_review": self.license_review,
            "limitations": list(self.limitations),
            "metadata": [list(pair) for pair in self.metadata],
            "operations": [item.payload() for item in self.operations],
            "profile_id": self.profile_id,
            "provider": self.provider,
            "schema_version": self.schema_version,
            "status": self.status.value,
            "status_reason": self.status_reason,
            "transport": self.transport.value,
            "workspace_id": self.workspace_id,
        }

    @property
    def digest(self) -> str:
        return _sha(self.payload())


@dataclass(frozen=True, slots=True)
class NexusFeatureGateV1:
    nexus_enabled: bool = False
    shadow_mode: bool = True
    dispatch_enabled: bool = False
    contract_version: str = NEXUS_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.nexus_enabled) is not bool
            or type(self.shadow_mode) is not bool
            or type(self.dispatch_enabled) is not bool
        ):
            raise CapabilityContractError("feature-gate values must be exact booleans")
        if self.contract_version != NEXUS_CONTRACT_VERSION:
            raise CapabilityContractError("unknown nexus contract version")
        if self.nexus_enabled or not self.shadow_mode or self.dispatch_enabled:
            raise CapabilityContractError("Capability Nexus V1 is strictly default-off and shadow-only")


@dataclass(frozen=True, slots=True)
class CapabilityProjection:
    descriptor: CapabilityDescriptor
    descriptor_digest: str
    runtime_available: bool
    authority_granted: bool
    projection_status: CapabilityStatus
    projection_reason: str

    def __post_init__(self) -> None:
        if type(self.descriptor) is not CapabilityDescriptor:
            raise CapabilityContractError("projection descriptor is invalid")
        if self.descriptor_digest != self.descriptor.digest:
            raise CapabilityContractError("projection descriptor digest drift")
        if self.runtime_available or self.authority_granted:
            raise CapabilityContractError("V1 projections cannot grant runtime authority")
        if type(self.runtime_available) is not bool or type(self.authority_granted) is not bool:
            raise CapabilityContractError("projection booleans must be exact")
        if type(self.projection_status) is not CapabilityStatus:
            raise CapabilityContractError("projection status is invalid")
        object.__setattr__(self, "projection_reason", _slug(self.projection_reason, "projection_reason"))


@dataclass(frozen=True, slots=True)
class CapabilitySnapshot:
    contract_version: str
    workspace_id: str
    account_id: str
    entries: tuple[CapabilityProjection, ...]
    snapshot_digest: str


class CapabilityNexusV1:
    """Thread-safe descriptor registry with no adapter-dispatch surface."""

    def __init__(self, gate: NexusFeatureGateV1 | None = None) -> None:
        self._gate = gate or NexusFeatureGateV1()
        self._descriptors: dict[str, CapabilityDescriptor] = {}
        self._revoked_aliases: set[str] = set()
        self._kill_active = False
        self._lock = threading.RLock()

    @property
    def gate(self) -> NexusFeatureGateV1:
        return self._gate

    def register(self, descriptor: CapabilityDescriptor) -> str:
        if type(descriptor) is not CapabilityDescriptor:
            raise CapabilityContractError("registry requires an exact CapabilityDescriptor")
        with self._lock:
            if descriptor.capability_id in self._descriptors:
                raise CapabilityContractError("duplicate capability registration")
            self._descriptors[descriptor.capability_id] = descriptor
            return descriptor.digest

    def revoke_alias(self, credential_alias: str) -> None:
        if type(credential_alias) is not str or not _ALIAS_RE.fullmatch(credential_alias):
            raise CapabilityContractError("credential alias is invalid")
        with self._lock:
            self._revoked_aliases.add(credential_alias)

    def set_kill(self, active: bool) -> None:
        if type(active) is not bool:
            raise CapabilityContractError("kill state must be an exact boolean")
        with self._lock:
            self._kill_active = active

    def discover(
        self,
        capability_id: str,
        *,
        workspace_id: str,
        account_id: str,
        expected_version: str,
        expected_digest: str,
    ) -> CapabilityProjection:
        capability_id = _slug(capability_id, "capability_id")
        workspace_id = _identifier(workspace_id, "workspace_id")
        account_id = _identifier(account_id, "account_id")
        expected_version = _slug(expected_version, "expected_version")
        expected_digest = _text(expected_digest, "expected_digest", maximum=64)
        with self._lock:
            descriptor = self._descriptors.get(capability_id)
            if descriptor is None:
                raise CapabilityDeniedError("unknown capability")
            if descriptor.workspace_id != workspace_id or descriptor.account_id != account_id:
                raise CapabilityDeniedError("workspace/account binding mismatch")
            if descriptor.capability_version != expected_version or descriptor.digest != expected_digest:
                raise CapabilityDeniedError("capability version or descriptor drift")
            status, reason = self._project_status(descriptor)
            return CapabilityProjection(descriptor, descriptor.digest, False, False, status, reason)

    def health_projection(
        self,
        capability_id: str,
        *,
        workspace_id: str,
        account_id: str,
        expected_version: str,
        expected_digest: str,
    ) -> CapabilityProjection:
        """Return the same non-authoritative truth projection as discovery."""

        return self.discover(
            capability_id,
            workspace_id=workspace_id,
            account_id=account_id,
            expected_version=expected_version,
            expected_digest=expected_digest,
        )

    def snapshot(self, *, workspace_id: str, account_id: str) -> CapabilitySnapshot:
        workspace_id = _identifier(workspace_id, "workspace_id")
        account_id = _identifier(account_id, "account_id")
        with self._lock:
            entries = tuple(
                CapabilityProjection(
                    descriptor,
                    descriptor.digest,
                    False,
                    False,
                    *self._project_status(descriptor),
                )
                for descriptor in sorted(self._descriptors.values(), key=lambda item: item.capability_id)
                if descriptor.workspace_id == workspace_id and descriptor.account_id == account_id
            )
        payload = {
            "account_id": account_id,
            "contract_version": NEXUS_CONTRACT_VERSION,
            "entries": [
                {
                    "descriptor_digest": item.descriptor_digest,
                    "projection_reason": item.projection_reason,
                    "projection_status": item.projection_status.value,
                }
                for item in entries
            ],
            "workspace_id": workspace_id,
        }
        return CapabilitySnapshot(
            NEXUS_CONTRACT_VERSION, workspace_id, account_id, entries, _sha(payload)
        )

    def _project_status(self, descriptor: CapabilityDescriptor) -> tuple[CapabilityStatus, str]:
        if self._kill_active:
            return CapabilityStatus.DISABLED, "global_kill_active"
        if descriptor.credential_alias in self._revoked_aliases:
            return CapabilityStatus.BLOCKED_BY_ACCESS, "credential_alias_revoked"
        if descriptor.status is CapabilityStatus.AVAILABLE_READ_ONLY:
            return CapabilityStatus.DISABLED, "nexus_default_off_shadow_only"
        return descriptor.status, descriptor.status_reason


@dataclass(frozen=True, slots=True)
class LegacyParityRecord:
    tool_name: str
    host_policy: str
    declaration_json: str
    declaration_digest: str


@dataclass(frozen=True, slots=True)
class LegacyDescriptorSet:
    descriptors: tuple[CapabilityDescriptor, ...]
    parity_records: tuple[LegacyParityRecord, ...]
    snapshot_digest: str

    def policy_mapping(self) -> Mapping[str, str]:
        return MappingProxyType({item.tool_name: item.host_policy for item in self.parity_records})

    def declarations(self) -> tuple[dict[str, object], ...]:
        return tuple(json.loads(item.declaration_json) for item in self.parity_records)


def build_legacy_descriptors(
    tool_declarations: Sequence[Mapping[str, object]],
    policy_mapping: Mapping[str, str],
    *,
    workspace_id: str,
    account_id: str,
    profile_id: str,
    operation_kinds: Mapping[str, OperationKind] | None = None,
) -> LegacyDescriptorSet:
    """Purely describe trusted legacy declarations without importing live code.

    A missing or extra host policy is rejected.  When the trusted host does not
    supply a semantic operation classification, V1 conservatively classifies
    the legacy operation as ``mutate``; this never broadens authority and is
    explicitly recorded as a limitation.
    """

    if type(tool_declarations) not in {tuple, list} or not tool_declarations:
        raise CapabilityContractError("tool declarations must be a non-empty bounded sequence")
    if len(tool_declarations) > 128 or not isinstance(policy_mapping, Mapping):
        raise CapabilityContractError("legacy input is invalid")
    workspace_id = _identifier(workspace_id, "workspace_id")
    account_id = _identifier(account_id, "account_id")
    profile_id = _identifier(profile_id, "profile_id")
    declarations: list[tuple[str, Mapping[str, object], str]] = []
    seen: set[str] = set()
    for raw in tool_declarations:
        if not isinstance(raw, Mapping):
            raise CapabilityContractError("legacy declaration is not a mapping")
        if set(raw) != {"name", "description", "parameters"}:
            raise CapabilityContractError("legacy declaration keys drifted")
        name = _slug(raw.get("name"), "legacy tool name")
        if name in seen:
            raise CapabilityContractError("duplicate legacy tool declaration")
        seen.add(name)
        _text(raw.get("description"), "legacy description", maximum=4096)
        if not isinstance(raw.get("parameters"), Mapping):
            raise CapabilityContractError("legacy parameters must be a mapping")
        encoded = _canonical_json(dict(raw), "legacy declaration", maximum=65536)
        declarations.append((name, raw, encoded))
    if set(policy_mapping) != seen:
        raise CapabilityContractError("legacy policy mapping must exactly cover declarations")
    if operation_kinds is not None and set(operation_kinds) != seen:
        raise CapabilityContractError("legacy operation mapping must exactly cover declarations")

    descriptors: list[CapabilityDescriptor] = []
    records: list[LegacyParityRecord] = []
    for name, raw, declaration_json in declarations:
        policy = _slug(policy_mapping[name], "legacy host policy")
        kind = OperationKind.MUTATE if operation_kinds is None else operation_kinds[name]
        if type(kind) is not OperationKind:
            raise CapabilityContractError("legacy operation mapping contains an invalid kind")
        parameter_schema_json = _canonical_json(raw["parameters"], "legacy parameter schema")
        operation = OperationDescriptor(
            operation_id=name,
            kind=kind,
            description=str(raw["description"]),
            parameter_schema_json=parameter_schema_json,
            required_scopes=(),
            data_classes=("legacy_unclassified",),
            risk_class="legacy_host_policy",
            approval_class=policy,
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
        declaration_digest = hashlib.sha256(declaration_json.encode("utf-8")).hexdigest()
        descriptor = CapabilityDescriptor(
            capability_id=f"legacy.{name}",
            capability_version="v1",
            provider="onyx_legacy",
            transport=TransportKind.LEGACY,
            api_name="legacy_dispatcher",
            api_version="unchanged",
            workspace_id=workspace_id,
            account_id=account_id,
            profile_id=profile_id,
            credential_alias=None,
            operations=(operation,),
            status=CapabilityStatus.DISABLED,
            status_reason="shadow_descriptor_only",
            limitations=("no_dispatch", "no_authority", "legacy_behavior_unchanged"),
            license_review="existing_runtime_not_relicensed",
            metadata=(
                ("declaration_sha256", declaration_digest),
                ("dispatch_path", "legacy_unchanged"),
                ("policy_source", "trusted_host_mapping"),
            ),
        )
        descriptors.append(descriptor)
        records.append(LegacyParityRecord(name, policy, declaration_json, declaration_digest))
    descriptors.sort(key=lambda item: item.capability_id)
    records.sort(key=lambda item: item.tool_name)
    payload = {
        "descriptors": [item.payload() for item in descriptors],
        "parity": [
            {
                "declaration_digest": item.declaration_digest,
                "declaration_json": item.declaration_json,
                "host_policy": item.host_policy,
                "tool_name": item.tool_name,
            }
            for item in records
        ],
    }
    return LegacyDescriptorSet(tuple(descriptors), tuple(records), _sha(payload))


@dataclass(frozen=True, slots=True)
class CatalogItem:
    item_id: str
    label: str
    category: str
    item_version: str
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "item_id", _identifier(self.item_id, "catalog item_id"))
        object.__setattr__(self, "label", _text(self.label, "catalog label", maximum=160))
        object.__setattr__(self, "category", _slug(self.category, "catalog category"))
        object.__setattr__(self, "item_version", _slug(self.item_version, "catalog item_version"))
        object.__setattr__(self, "tags", _string_tuple(self.tags, "catalog tags", maximum_items=16, maximum_text=48))

    def payload(self) -> dict[str, object]:
        return {
            "category": self.category,
            "item_id": self.item_id,
            "item_version": self.item_version,
            "label": self.label,
            "tags": list(self.tags),
        }


@dataclass(frozen=True, slots=True)
class CancellationTokenV1:
    _event: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True, slots=True)
class CatalogReadRequest:
    workspace_id: str
    account_id: str
    profile_id: str
    target: str
    correlation_id: str
    page_size: int = 25
    cursor: str | None = None
    timeout_ms: int = 1000
    cancellation: CancellationTokenV1 | None = None

    def __post_init__(self) -> None:
        for name in ("workspace_id", "account_id", "profile_id", "target", "correlation_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if type(self.page_size) is not int or not 1 <= self.page_size <= 100:
            raise CapabilityContractError("page_size must be in [1, 100]")
        if self.cursor is not None:
            object.__setattr__(self, "cursor", _text(self.cursor, "cursor", maximum=2048))
        if type(self.timeout_ms) is not int or not 1 <= self.timeout_ms <= 30_000:
            raise CapabilityContractError("timeout_ms must be in [1, 30000]")
        if self.cancellation is not None and type(self.cancellation) is not CancellationTokenV1:
            raise CapabilityContractError("cancellation token type is invalid")


@dataclass(frozen=True, slots=True)
class ConnectorHealth:
    capability_id: str
    status: CapabilityStatus
    reason: str
    workspace_id: str
    account_id: str
    profile_id: str
    api_version: str
    required_scopes: tuple[str, ...]
    granted_scopes: tuple[str, ...]
    quota_remaining: int
    cost_micros: int
    read_only: bool = True
    authority_granted: bool = False


@dataclass(frozen=True, slots=True)
class CatalogReadResult:
    outcome: str
    correlation_id: str
    request_digest: str
    items: tuple[CatalogItem, ...]
    next_cursor: str | None
    observed_count: int
    cost_micros: int
    quota_remaining: int
    reconciliation: ReconcileState
    receipt_digest: str
    retry_after_ms: int | None = None


class LocalReadOnlyCatalogAdapterV1:
    """Provider-free in-memory adapter used only to prove the read contract."""

    CAPABILITY_ID = "local.catalog"
    REQUIRED_SCOPE = "catalog.metadata.read"
    TARGET = "local_catalog"

    def __init__(
        self,
        items: Sequence[CatalogItem],
        *,
        workspace_id: str,
        account_id: str,
        profile_id: str,
        cursor_signing_key: bytes,
        auth_available: bool = True,
        granted_scopes: Sequence[str] = (REQUIRED_SCOPE,),
        status: CapabilityStatus = CapabilityStatus.DISABLED,
        status_reason: str = "candidate_not_activated",
        quota_limit: int = 100,
        rate_limit: int = 10,
        clock: Callable[[], float] = time.monotonic,
        read_hook: Callable[[], None] | None = None,
    ) -> None:
        if type(items) not in {tuple, list} or len(items) > 1000:
            raise CapabilityContractError("catalog items must be bounded")
        copied = tuple(items)
        if any(type(item) is not CatalogItem for item in copied):
            raise CapabilityContractError("catalog contains an invalid item")
        if len({item.item_id for item in copied}) != len(copied):
            raise CapabilityContractError("catalog item IDs must be unique")
        self._items = tuple(sorted(copied, key=lambda item: item.item_id))
        self._workspace_id = _identifier(workspace_id, "workspace_id")
        self._account_id = _identifier(account_id, "account_id")
        self._profile_id = _identifier(profile_id, "profile_id")
        if type(cursor_signing_key) is not bytes or not 32 <= len(cursor_signing_key) <= 128:
            raise CapabilityContractError("cursor signing key must be 32-128 bytes")
        self._cursor_key = bytes(cursor_signing_key)
        if type(auth_available) is not bool:
            raise CapabilityContractError("auth_available must be an exact boolean")
        self._auth_available = auth_available
        self._granted_scopes = frozenset(_string_tuple(granted_scopes, "granted_scopes"))
        if type(status) is not CapabilityStatus:
            raise CapabilityContractError("catalog status type is invalid")
        if status not in {CapabilityStatus.AVAILABLE_READ_ONLY, CapabilityStatus.DEGRADED, CapabilityStatus.DISABLED}:
            raise CapabilityContractError("catalog status is not valid for the local adapter")
        self._status = status
        self._status_reason = _slug(status_reason, "status_reason")
        if status is CapabilityStatus.DEGRADED and status_reason == "healthy":
            raise CapabilityContractError("degraded mode requires a reason")
        if type(quota_limit) is not int or not 1 <= quota_limit <= 1_000_000:
            raise CapabilityContractError("quota_limit is invalid")
        if type(rate_limit) is not int or not 1 <= rate_limit <= 10_000:
            raise CapabilityContractError("rate_limit is invalid")
        if not callable(clock) or (read_hook is not None and not callable(read_hook)):
            raise CapabilityContractError("clock/read hook is invalid")
        self._quota_limit = quota_limit
        self._rate_limit = rate_limit
        self._clock = clock
        self._read_hook = read_hook
        self._used = 0
        self._window_second: int | None = None
        self._window_used = 0
        self._results: dict[str, tuple[str, CatalogReadResult]] = {}
        self._kill_active = False
        self._lock = threading.RLock()
        self._snapshot_digest = _sha([item.payload() for item in self._items])

    @property
    def descriptor(self) -> CapabilityDescriptor:
        operation = OperationDescriptor(
            operation_id="catalog_read",
            kind=OperationKind.READ,
            description="Read allowlisted provider-free local catalog metadata.",
            parameter_schema_json=_canonical_json(
                {"type": "OBJECT", "properties": {"page_size": {"type": "INTEGER"}, "cursor": {"type": "STRING"}}},
                "catalog schema",
            ),
            required_scopes=(self.REQUIRED_SCOPE,),
            data_classes=("allowlisted_metadata",),
            risk_class="low",
            approval_class="host_policy_required",
            allowed_targets=(self.TARGET,),
            pagination="signed_bounded_cursor",
            rate_limit="fixed_window_fail_closed",
            cancellation="before_and_after_read",
            timeout="before_and_after_read",
            idempotency="exact_correlation_request_binding",
            receipt="immutable_read_receipt",
            reconciliation="read_state_only",
            quota="exact_local_counter",
            cost="zero_local_micros",
            dry_run="read_only_not_applicable",
            test_account="provider_free_fixture",
            host_policy="always_confirm",
        )
        return CapabilityDescriptor(
            capability_id=self.CAPABILITY_ID,
            capability_version="v1",
            provider="onyx_local",
            transport=TransportKind.LOCAL,
            api_name="local_catalog",
            api_version=CATALOG_CONTRACT_VERSION,
            workspace_id=self._workspace_id,
            account_id=self._account_id,
            profile_id=self._profile_id,
            credential_alias=None,
            operations=(operation,),
            status=self._status,
            status_reason=self._status_reason,
            limitations=("metadata_only", "provider_free", "no_mutation", "no_live_wiring"),
            metadata=(("data_source", "constructor_allowlist"),),
        )

    def set_kill(self, active: bool) -> None:
        if type(active) is not bool:
            raise CapabilityContractError("kill state must be an exact boolean")
        with self._lock:
            self._kill_active = active

    def health(self) -> ConnectorHealth:
        with self._lock:
            status, reason = self._effective_status()
            return ConnectorHealth(
                self.CAPABILITY_ID, status, reason, self._workspace_id, self._account_id,
                self._profile_id, CATALOG_CONTRACT_VERSION, (self.REQUIRED_SCOPE,),
                tuple(sorted(self._granted_scopes)), max(0, self._quota_limit - self._used), 0,
            )

    def read_page(self, request: CatalogReadRequest) -> CatalogReadResult:
        if type(request) is not CatalogReadRequest:
            raise CapabilityContractError("read request type is invalid")
        request_digest = self._request_digest(request)
        started = self._clock()
        with self._lock:
            prior = self._results.get(request.correlation_id)
            if prior is not None:
                if prior[0] != request_digest:
                    raise CapabilityDeniedError("correlation ID request drift")
                return prior[1]
            self._validate_binding(request)
            status, reason = self._effective_status()
            if status not in {CapabilityStatus.AVAILABLE_READ_ONLY, CapabilityStatus.DEGRADED}:
                raise CapabilityDeniedError(reason)
            if self._used >= self._quota_limit:
                raise CapabilityDeniedError("quota_exhausted")
            now_second = int(started)
            if self._window_second != now_second:
                self._window_second, self._window_used = now_second, 0
            if self._window_used >= self._rate_limit:
                result = self._result(
                    "rate_limited", request, request_digest, (), None,
                    ReconcileState.VERIFIED_NO_EXTERNAL_EFFECT, retry_after_ms=1000,
                )
                self._results[request.correlation_id] = (request_digest, result)
                return result
            if request.cancellation is not None and request.cancellation.cancelled:
                result = self._result(
                    "cancelled_before_read", request, request_digest, (), None,
                    ReconcileState.VERIFIED_NO_EXTERNAL_EFFECT,
                )
                self._results[request.correlation_id] = (request_digest, result)
                return result
            if (self._clock() - started) * 1000 >= request.timeout_ms:
                result = self._result(
                    "timeout_before_read", request, request_digest, (), None,
                    ReconcileState.VERIFIED_NO_EXTERNAL_EFFECT,
                )
                self._results[request.correlation_id] = (request_digest, result)
                return result
            offset = self._decode_cursor(request.cursor) if request.cursor else 0
            self._window_used += 1
            self._used += 1
            page = self._items[offset : offset + request.page_size]
            next_offset = offset + len(page)
            next_cursor = self._encode_cursor(next_offset) if next_offset < len(self._items) else None
            if self._read_hook is not None:
                self._read_hook()
            if request.cancellation is not None and request.cancellation.cancelled:
                outcome = "cancelled_after_read"
            elif (self._clock() - started) * 1000 >= request.timeout_ms:
                outcome = "timeout_after_read"
            else:
                outcome = "degraded_success" if status is CapabilityStatus.DEGRADED else "succeeded"
            result = self._result(
                outcome, request, request_digest, page, next_cursor,
                ReconcileState.OBSERVED_READ,
            )
            self._results[request.correlation_id] = (request_digest, result)
            return result

    def reconcile(self, correlation_id: str) -> ReconcileState:
        correlation_id = _identifier(correlation_id, "correlation_id")
        with self._lock:
            prior = self._results.get(correlation_id)
            return prior[1].reconciliation if prior is not None else ReconcileState.UNKNOWN_CORRELATION

    def draft(self, *_args: object, **_kwargs: object) -> None:
        raise CapabilityDeniedError("local catalog has no draft operation")

    def mutate(self, *_args: object, **_kwargs: object) -> None:
        raise CapabilityDeniedError("local catalog has no mutation operation")

    def _effective_status(self) -> tuple[CapabilityStatus, str]:
        if self._kill_active:
            return CapabilityStatus.DISABLED, "global_kill_active"
        if not self._auth_available:
            return CapabilityStatus.BLOCKED_BY_ACCESS, "authentication_unavailable"
        if self.REQUIRED_SCOPE not in self._granted_scopes:
            return CapabilityStatus.BLOCKED_BY_SCOPE, "required_scope_missing"
        return self._status, self._status_reason

    def _validate_binding(self, request: CatalogReadRequest) -> None:
        if (
            request.workspace_id != self._workspace_id
            or request.account_id != self._account_id
            or request.profile_id != self._profile_id
        ):
            raise CapabilityDeniedError("workspace/account/profile binding mismatch")
        if request.target != self.TARGET:
            raise CapabilityDeniedError("target is not allowlisted")

    def _request_digest(self, request: CatalogReadRequest) -> str:
        return _sha({
            "account_id": request.account_id,
            "correlation_id": request.correlation_id,
            "cursor": request.cursor,
            "page_size": request.page_size,
            "profile_id": request.profile_id,
            "target": request.target,
            "timeout_ms": request.timeout_ms,
            "workspace_id": request.workspace_id,
        })

    def _encode_cursor(self, offset: int) -> str:
        payload = {
            "account_id": self._account_id,
            "capability_id": self.CAPABILITY_ID,
            "contract_version": CATALOG_CONTRACT_VERSION,
            "offset": offset,
            "profile_id": self._profile_id,
            "snapshot_digest": self._snapshot_digest,
            "workspace_id": self._workspace_id,
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return body.hex() + "." + hmac.new(self._cursor_key, body, hashlib.sha256).hexdigest()

    def _decode_cursor(self, cursor: str) -> int:
        try:
            body_hex, signature = cursor.split(".", 1)
            body = bytes.fromhex(body_hex)
            expected = hmac.new(self._cursor_key, body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise CapabilityDeniedError("cursor integrity failure")
            payload = json.loads(body)
        except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise CapabilityDeniedError("cursor integrity failure") from exc
        expected_payload = {
            "account_id": self._account_id,
            "capability_id": self.CAPABILITY_ID,
            "contract_version": CATALOG_CONTRACT_VERSION,
            "profile_id": self._profile_id,
            "snapshot_digest": self._snapshot_digest,
            "workspace_id": self._workspace_id,
        }
        for key, value in expected_payload.items():
            if payload.get(key) != value:
                raise CapabilityDeniedError("cursor binding drift")
        if set(payload) != set(expected_payload) | {"offset"}:
            raise CapabilityDeniedError("cursor schema drift")
        offset = payload.get("offset")
        if type(offset) is not int or not 0 <= offset < len(self._items):
            raise CapabilityDeniedError("cursor offset is invalid")
        return offset

    def _result(
        self,
        outcome: str,
        request: CatalogReadRequest,
        request_digest: str,
        items: Iterable[CatalogItem],
        next_cursor: str | None,
        reconciliation: ReconcileState,
        *,
        retry_after_ms: int | None = None,
    ) -> CatalogReadResult:
        copied = tuple(items)
        receipt_payload = {
            "correlation_id": request.correlation_id,
            "item_ids": [item.item_id for item in copied],
            "next_cursor": next_cursor,
            "outcome": outcome,
            "request_digest": request_digest,
        }
        return CatalogReadResult(
            outcome, request.correlation_id, request_digest, copied, next_cursor,
            len(copied), 0, max(0, self._quota_limit - self._used), reconciliation,
            _sha(receipt_payload), retry_after_ms,
        )
