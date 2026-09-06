"""Isolated disabled External-Agent Descriptor V1.

This slice publishes only immutable, authenticated metadata stating that no
external-agent adapter is installed or authorized.  It cannot dispatch,
execute, authenticate, open a process, contact a provider, or reach live code.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Mapping

import core.capability_nexus_v32 as nexus_v32
import core.phase6_provider_registry_v1 as provider_v1
from core.capability_nexus_v32 import (
    CapabilityDescriptorV32,
    CapabilityStatusV32,
    OperationDescriptorV32,
    OperationKindV32,
    TransportKindV32,
)
from core.phase6_agentic_core_v1 import (
    AdapterStatusV1,
    DataClassV1,
    ModelDescriptorV1,
)
from core.phase6_provider_registry_v1 import ProviderRecordV1


FEATURE_FLAG: Final = "ONYX_PHASE6_DISABLED_EXTERNAL_AGENT_DESCRIPTOR_V1"
CANDIDATE: Final = "phase6-disabled-external-agent-descriptor-candidate-001"
DESCRIPTOR_VERSION: Final = "v1"
ACCESS_REASON: Final = "no_accepted_installed_authenticated_adapter"
ZERO_DIGEST: Final = "0" * 64
_CONSTRUCTION_KEY = object()
_KEY_BYTES: Final = 32
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_VERSION = re.compile(r"v[1-9][0-9]{0,5}\Z")
_SENSITIVE = re.compile(
    r"(?:secret|token|password|credential|private|confidential|restricted|"
    r"authorization|bearer|cookie|api-key|access-key)",
    re.IGNORECASE,
)
_RAW_SECRET_PREFIX = re.compile(
    r"(?:sk-|ghp-|github-pat-|xox[baprs]-|akia|asia|aiza)",
    re.IGNORECASE,
)
_MAX_TIME: Final = 9_223_372_036_854_775_807
_CAPABILITY_TYPE = CapabilityDescriptorV32
_CAPABILITY_STATUS_TYPE = CapabilityStatusV32
_OPERATION_TYPE = OperationDescriptorV32
_PROVIDER_RECORD_TYPE = ProviderRecordV1
_MODEL_DESCRIPTOR_TYPE = ModelDescriptorV1
_RLOCK_TYPE = type(threading.RLock())

COMPONENT_ACCEPTANCE_ROOTS: Final = (
    (
        "capability_nexus_v32",
        (
            "docs/onyx/checkpoints/phase5-capability-nexus-v32/"
            "phase5-capability-nexus-v32.bundle.json"
        ),
        "84ffc850a14782ae3f4182973acc50a2765df7f6143977a81daf5423c6706c6f",
    ),
    (
        "capability_nexus_v32",
        "docs/onyx/acceptance/VE-P53-CAPABILITY-NEXUS-V32-E6-001.md",
        "b75ccb2b4bc58a4c4d72445d46eb66e550636cbb0deb02ecef304c8327f9d1dc",
    ),
    (
        "provider_registry_v1",
        "docs/onyx/checkpoints/phase6-provider-registry-v1/manifest.json",
        "7a3191607037f6210ae145b5477bbaeff5bfdaa7c756257d4775c1f30c0a10c6",
    ),
    (
        "provider_registry_v1",
        "docs/onyx/acceptance/VE-P6-PROVIDER-REGISTRY-V1-E6-001.md",
        "ca7f0760723c4f6ad5d2a8716248c75c695e58cdb3e9b6917a3d027443aefabd",
    ),
    (
        "provider_registry_v1",
        "docs/onyx/acceptance/VE-P6-PROVIDER-REGISTRY-V1-E6-001.manifest.json",
        "4a2c69076a1e6b07f606d30733b357f7c50c08193ff90a250d351637f0c0d070",
    ),
)


class DisabledExternalAgentDescriptorV1Error(RuntimeError):
    """Descriptor publication failed without exposing caller metadata."""


class DisabledExternalAgentDescriptorV1ContractError(ValueError):
    """A non-canonical descriptor contract was supplied."""


class DisabledExternalAgentDescriptorV1Denied(PermissionError):
    """Descriptor access was denied fail-closed."""


class DisabledExternalAgentDescriptorV1Conflict(
    DisabledExternalAgentDescriptorV1Denied
):
    """A request identifier was rebound to different metadata."""


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise DisabledExternalAgentDescriptorV1ContractError(
            "descriptor metadata is not canonical"
        ) from exc


def _digest(value: object) -> str:
    raw = value if type(value) is bytes else _canonical(value)
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _identifier(value: object, label: str) -> str:
    if (
        type(value) is not str
        or _ID.fullmatch(value) is None
        or _SENSITIVE.search(value) is not None
        or _RAW_SECRET_PREFIX.search(value) is not None
    ):
        raise DisabledExternalAgentDescriptorV1ContractError(
            f"{label} is not safe canonical metadata"
        )
    return value


def _digest_value(value: object, label: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise DisabledExternalAgentDescriptorV1ContractError(
            f"{label} must be SHA-256"
        )
    return value


def _key(value: object) -> bytes:
    if type(value) is not bytes or len(value) != _KEY_BYTES:
        raise DisabledExternalAgentDescriptorV1ContractError(
            "receipt authentication key must be exactly 32 bytes"
        )
    return value


def _component_root_digest() -> str:
    return _digest(
        {
            "schema": "OnyxDisabledExternalAgentComponentRoots.v1",
            "roots": [
                {"component": component, "path": path, "sha256": sha256}
                for component, path, sha256 in COMPONENT_ACCEPTANCE_ROOTS
            ],
        }
    )


def _verify_component_roots(project_root: Path) -> str:
    seen: set[str] = set()
    for _component, relative, expected in COMPONENT_ACCEPTANCE_ROOTS:
        path_value = Path(relative)
        if (
            relative in seen
            or path_value.is_absolute()
            or ".." in path_value.parts
            or _SHA256.fullmatch(expected) is None
        ):
            raise DisabledExternalAgentDescriptorV1Denied(
                "component root contract drift denied"
            )
        seen.add(relative)
        try:
            path = (project_root / path_value).resolve(strict=True)
            path.relative_to(project_root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise DisabledExternalAgentDescriptorV1Denied(
                "component root is unavailable"
            ) from exc
        if not path.is_file() or path.is_symlink():
            raise DisabledExternalAgentDescriptorV1Denied(
                "component root is not a regular file"
            )
        if not hmac.compare_digest(_sha_file(path), expected):
            raise DisabledExternalAgentDescriptorV1Denied(
                "component acceptance drift denied"
            )
    return _component_root_digest()


class ExternalAgentAuthenticationStateV1(StrEnum):
    ABSENT = "absent"


class ExternalAgentCancellationSemanticsV1(StrEnum):
    NO_SESSION_CANCEL_IS_FINAL = "no_session_cancel_is_final"


class ExternalAgentReceiptSemanticsV1(StrEnum):
    AUTHENTICATED_BLOCKED_PROJECTION = "authenticated_blocked_projection"


@dataclass(frozen=True, slots=True)
class DisabledExternalAgentFeatureGateV1:
    enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise DisabledExternalAgentDescriptorV1ContractError(
                "feature gate must be an exact boolean"
            )

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "DisabledExternalAgentFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True, slots=True)
class ExternalAgentDescriptorIdentityV1:
    adapter_id: str
    provider_id: str
    workspace_id: str
    account_id: str
    profile_id: str
    principal_id: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            _identifier(getattr(self, name), name)

    def payload(self) -> dict[str, str]:
        return {
            "adapter_id": self.adapter_id,
            "provider_id": self.provider_id,
            "workspace_id": self.workspace_id,
            "account_id": self.account_id,
            "profile_id": self.profile_id,
            "principal_id": self.principal_id,
        }

    @property
    def digest(self) -> str:
        return _digest(
            {"schema": "OnyxExternalAgentDescriptorIdentity.v1", **self.payload()}
        )


class DisabledExternalAgentDescriptorV1:
    """Immutable exact Capability Nexus + Provider Registry blocked descriptor."""

    __slots__ = (
        "_sealed",
        "_identity",
        "_descriptor_version",
        "_health",
        "_access_reason",
        "_required_scopes",
        "_granted_scopes",
        "_authentication",
        "_cancellation_semantics",
        "_receipt_semantics",
        "_capability_contract",
        "_provider_contract",
        "_digest",
    )

    def __init__(
        self,
        *,
        _construction_key: object,
        identity: ExternalAgentDescriptorIdentityV1,
        capability_contract: CapabilityDescriptorV32,
        provider_contract: ProviderRecordV1,
    ) -> None:
        if _construction_key is not _CONSTRUCTION_KEY:
            raise DisabledExternalAgentDescriptorV1Denied(
                "descriptor construction is factory-only"
            )
        if (
            type(identity) is not ExternalAgentDescriptorIdentityV1
            or type(capability_contract) is not _CAPABILITY_TYPE
            or type(provider_contract) is not _PROVIDER_RECORD_TYPE
        ):
            raise DisabledExternalAgentDescriptorV1ContractError(
                "exact identity and inherited contracts are required"
            )
        self._identity = identity
        self._descriptor_version = DESCRIPTOR_VERSION
        self._health = CapabilityStatusV32.BLOCKED_BY_ACCESS
        self._access_reason = ACCESS_REASON
        self._required_scopes: tuple[str, ...] = ()
        self._granted_scopes: tuple[str, ...] = ()
        self._authentication = ExternalAgentAuthenticationStateV1.ABSENT
        self._cancellation_semantics = (
            ExternalAgentCancellationSemanticsV1.NO_SESSION_CANCEL_IS_FINAL
        )
        self._receipt_semantics = (
            ExternalAgentReceiptSemanticsV1.AUTHENTICATED_BLOCKED_PROJECTION
        )
        self._capability_contract = capability_contract
        self._provider_contract = provider_contract
        self._digest = _digest(self.payload())
        self.attest()
        self._sealed = True

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("disabled external-agent descriptor is immutable")
        object.__setattr__(self, name, value)

    @property
    def identity(self) -> ExternalAgentDescriptorIdentityV1:
        return self._identity

    @property
    def descriptor_version(self) -> str:
        return self._descriptor_version

    @property
    def health(self) -> CapabilityStatusV32:
        return self._health

    @property
    def access_reason(self) -> str:
        return self._access_reason

    @property
    def required_scopes(self) -> tuple[str, ...]:
        return self._required_scopes

    @property
    def granted_scopes(self) -> tuple[str, ...]:
        return self._granted_scopes

    @property
    def authentication(self) -> ExternalAgentAuthenticationStateV1:
        return self._authentication

    @property
    def cancellation_semantics(self) -> ExternalAgentCancellationSemanticsV1:
        return self._cancellation_semantics

    @property
    def receipt_semantics(self) -> ExternalAgentReceiptSemanticsV1:
        return self._receipt_semantics

    @property
    def capability_contract(self) -> CapabilityDescriptorV32:
        return self._capability_contract

    @property
    def provider_contract(self) -> ProviderRecordV1:
        return self._provider_contract

    @property
    def digest(self) -> str:
        self.attest()
        return self._digest

    def payload(self) -> dict[str, object]:
        return {
            "schema": "OnyxDisabledExternalAgentDescriptor.v1",
            "identity_digest": self._identity.digest,
            "descriptor_version": self._descriptor_version,
            "health": self._health.value,
            "access_reason": self._access_reason,
            "required_scopes": self._required_scopes,
            "granted_scopes": self._granted_scopes,
            "authentication": self._authentication.value,
            "cancellation_semantics": self._cancellation_semantics.value,
            "receipt_semantics": self._receipt_semantics.value,
            "capability_contract_digest": self._capability_contract.digest,
            "provider_contract_digest": self._provider_contract.digest,
        }

    def attest(self) -> None:
        operation = self._capability_contract.operations
        descriptor = self._provider_contract.descriptor
        if (
            nexus_v32.CapabilityDescriptorV32 is not _CAPABILITY_TYPE
            or nexus_v32.OperationDescriptorV32 is not _OPERATION_TYPE
            or provider_v1.ProviderRecordV1 is not _PROVIDER_RECORD_TYPE
            or type(self._identity) is not ExternalAgentDescriptorIdentityV1
            or self._descriptor_version != DESCRIPTOR_VERSION
            or self._health is not CapabilityStatusV32.BLOCKED_BY_ACCESS
            or self._access_reason != ACCESS_REASON
            or self._required_scopes != ()
            or self._granted_scopes != ()
            or self._authentication is not ExternalAgentAuthenticationStateV1.ABSENT
            or self._cancellation_semantics
            is not ExternalAgentCancellationSemanticsV1.NO_SESSION_CANCEL_IS_FINAL
            or self._receipt_semantics
            is not ExternalAgentReceiptSemanticsV1.AUTHENTICATED_BLOCKED_PROJECTION
            or type(self._capability_contract) is not _CAPABILITY_TYPE
            or self._capability_contract.status
            is not CapabilityStatusV32.BLOCKED_BY_ACCESS
            or self._capability_contract.status_reason != ACCESS_REASON
            or self._capability_contract.credential_alias is not None
            or self._capability_contract.metadata != ()
            or len(operation) != 1
            or type(operation[0]) is not _OPERATION_TYPE
            or operation[0].required_scopes != ()
            or type(self._provider_contract) is not _PROVIDER_RECORD_TYPE
            or type(descriptor) is not _MODEL_DESCRIPTOR_TYPE
            or descriptor.status is not AdapterStatusV1.BLOCKED_BY_ACCESS
            or descriptor.workspace_allowlist != (self._identity.workspace_id,)
            or descriptor.modalities != ("external_agent",)
            or self._provider_contract.provider_id != self._identity.provider_id
            or self._provider_contract.adapter_id != self._identity.adapter_id
            or not hmac.compare_digest(_digest(self.payload()), self._digest)
        ):
            raise DisabledExternalAgentDescriptorV1Denied(
                "disabled descriptor authority drift denied"
            )


@dataclass(frozen=True, slots=True)
class ExternalAgentDescriptorQueryV1:
    request_id: str
    identity: ExternalAgentDescriptorIdentityV1
    expected_version: str
    expected_descriptor_digest: str
    cancelled: bool = False

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        if type(self.identity) is not ExternalAgentDescriptorIdentityV1:
            raise DisabledExternalAgentDescriptorV1ContractError(
                "exact descriptor identity is required"
            )
        if type(self.expected_version) is not str or _VERSION.fullmatch(
            self.expected_version
        ) is None:
            raise DisabledExternalAgentDescriptorV1ContractError(
                "expected version is invalid"
            )
        _digest_value(
            self.expected_descriptor_digest,
            "expected_descriptor_digest",
        )
        if type(self.cancelled) is not bool:
            raise DisabledExternalAgentDescriptorV1ContractError(
                "cancelled must be an exact boolean"
            )

    @property
    def digest(self) -> str:
        return _digest(
            {
                "schema": "OnyxExternalAgentDescriptorQuery.v1",
                "request_id": self.request_id,
                "identity_digest": self.identity.digest,
                "expected_version": self.expected_version,
                "expected_descriptor_digest": self.expected_descriptor_digest,
                "cancelled": self.cancelled,
            }
        )


@dataclass(frozen=True, slots=True)
class DisabledExternalAgentProjectionV1:
    request_id: str
    identity_digest: str
    descriptor: DisabledExternalAgentDescriptorV1
    descriptor_digest: str
    health: CapabilityStatusV32
    access_reason: str
    required_scopes: tuple[str, ...]
    granted_scopes: tuple[str, ...]
    authentication: ExternalAgentAuthenticationStateV1
    runtime_available: bool = False
    authority_granted: bool = False
    provider_calls: int = 0
    process_calls: int = 0
    network_calls: int = 0
    live_calls: int = 0

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        _digest_value(self.identity_digest, "identity_digest")
        _digest_value(self.descriptor_digest, "descriptor_digest")
        if (
            type(self.descriptor) is not DisabledExternalAgentDescriptorV1
            or self.descriptor.digest != self.descriptor_digest
            or self.identity_digest != self.descriptor.identity.digest
            or type(self.health) is not _CAPABILITY_STATUS_TYPE
            or self.health is not CapabilityStatusV32.BLOCKED_BY_ACCESS
            or self.access_reason != ACCESS_REASON
            or self.required_scopes != ()
            or self.granted_scopes != ()
            or self.authentication is not ExternalAgentAuthenticationStateV1.ABSENT
            or self.runtime_available
            or self.authority_granted
            or (
                self.provider_calls,
                self.process_calls,
                self.network_calls,
                self.live_calls,
            )
            != (0, 0, 0, 0)
        ):
            raise DisabledExternalAgentDescriptorV1Denied(
                "blocked projection contract drift denied"
            )

    @property
    def digest(self) -> str:
        return _digest(
            {
                "schema": "OnyxDisabledExternalAgentProjection.v1",
                "request_id": self.request_id,
                "identity_digest": self.identity_digest,
                "descriptor_digest": self.descriptor_digest,
                "health": self.health.value,
                "access_reason": self.access_reason,
                "required_scopes": self.required_scopes,
                "granted_scopes": self.granted_scopes,
                "authentication": self.authentication.value,
                "runtime_available": self.runtime_available,
                "authority_granted": self.authority_granted,
                "provider_calls": self.provider_calls,
                "process_calls": self.process_calls,
                "network_calls": self.network_calls,
                "live_calls": self.live_calls,
            }
        )


@dataclass(frozen=True, slots=True)
class DisabledExternalAgentReceiptV1:
    request_id: str
    identity_digest: str
    query_digest: str
    projection_digest: str
    descriptor_digest: str
    health: CapabilityStatusV32
    access_reason: str
    component_root_digest: str
    authentication_tag: str

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        for value, label in (
            (self.identity_digest, "identity_digest"),
            (self.query_digest, "query_digest"),
            (self.projection_digest, "projection_digest"),
            (self.descriptor_digest, "descriptor_digest"),
            (self.component_root_digest, "component_root_digest"),
            (self.authentication_tag, "authentication_tag"),
        ):
            _digest_value(value, label)
        if (
            type(self.health) is not _CAPABILITY_STATUS_TYPE
            or self.health is not CapabilityStatusV32.BLOCKED_BY_ACCESS
            or self.access_reason != ACCESS_REASON
        ):
            raise DisabledExternalAgentDescriptorV1Denied(
                "receipt status contract drift denied"
            )

    def unsigned_payload(self) -> dict[str, str]:
        return {
            "schema": "OnyxDisabledExternalAgentReceipt.v1",
            "request_id": self.request_id,
            "identity_digest": self.identity_digest,
            "query_digest": self.query_digest,
            "projection_digest": self.projection_digest,
            "descriptor_digest": self.descriptor_digest,
            "health": self.health.value,
            "access_reason": self.access_reason,
            "component_root_digest": self.component_root_digest,
        }

    @property
    def digest(self) -> str:
        return _digest(
            {
                "schema": "OnyxAuthenticatedDisabledExternalAgentReceipt.v1",
                "unsigned_digest": _digest(self.unsigned_payload()),
                "authentication_tag": self.authentication_tag,
            }
        )


class DisabledExternalAgentDescriptorCatalogV1:
    """Single-descriptor, authenticated, replay-safe metadata projection."""

    __slots__ = (
        "_descriptor",
        "_project_root",
        "_component_root_digest",
        "_receipt_key",
        "_receipt_key_digest",
        "_replays",
        "_lock",
    )

    def __init__(
        self,
        *,
        _construction_key: object,
        descriptor: DisabledExternalAgentDescriptorV1,
        project_root: Path,
        receipt_authentication_key: bytes,
    ) -> None:
        if _construction_key is not _CONSTRUCTION_KEY:
            raise DisabledExternalAgentDescriptorV1Denied(
                "descriptor catalog construction is factory-only"
            )
        if type(descriptor) is not DisabledExternalAgentDescriptorV1:
            raise DisabledExternalAgentDescriptorV1ContractError(
                "exact disabled descriptor is required"
            )
        self._descriptor = descriptor
        self._project_root = project_root
        self._component_root_digest = _verify_component_roots(project_root)
        self._receipt_key = _key(receipt_authentication_key)
        self._receipt_key_digest = _digest(self._receipt_key)
        self._replays: dict[
            str,
            tuple[
                str,
                DisabledExternalAgentProjectionV1,
                DisabledExternalAgentReceiptV1,
            ],
        ] = {}
        self._lock = threading.RLock()
        self._attest()

    @property
    def descriptor(self) -> DisabledExternalAgentDescriptorV1:
        self._attest()
        return self._descriptor

    def _attest(self) -> None:
        self._descriptor.attest()
        if (
            type(self._descriptor) is not DisabledExternalAgentDescriptorV1
            or type(self._receipt_key) is not bytes
            or len(self._receipt_key) != _KEY_BYTES
            or not hmac.compare_digest(
                _digest(self._receipt_key),
                self._receipt_key_digest,
            )
            or type(self._replays) is not dict
            or type(self._lock) is not _RLOCK_TYPE
            or not hmac.compare_digest(
                _verify_component_roots(self._project_root),
                self._component_root_digest,
            )
        ):
            raise DisabledExternalAgentDescriptorV1Denied(
                "descriptor catalog authority drift denied"
            )

    def _receipt(
        self,
        query: ExternalAgentDescriptorQueryV1,
        projection: DisabledExternalAgentProjectionV1,
    ) -> DisabledExternalAgentReceiptV1:
        unsigned = {
            "schema": "OnyxDisabledExternalAgentReceipt.v1",
            "request_id": query.request_id,
            "identity_digest": query.identity.digest,
            "query_digest": query.digest,
            "projection_digest": projection.digest,
            "descriptor_digest": self._descriptor.digest,
            "health": CapabilityStatusV32.BLOCKED_BY_ACCESS.value,
            "access_reason": ACCESS_REASON,
            "component_root_digest": self._component_root_digest,
        }
        tag = hmac.new(
            self._receipt_key,
            _canonical(unsigned),
            hashlib.sha256,
        ).hexdigest()
        return DisabledExternalAgentReceiptV1(
            request_id=query.request_id,
            identity_digest=query.identity.digest,
            query_digest=query.digest,
            projection_digest=projection.digest,
            descriptor_digest=self._descriptor.digest,
            health=CapabilityStatusV32.BLOCKED_BY_ACCESS,
            access_reason=ACCESS_REASON,
            component_root_digest=self._component_root_digest,
            authentication_tag=tag,
        )

    def attest_receipt(
        self,
        projection: DisabledExternalAgentProjectionV1,
        receipt: DisabledExternalAgentReceiptV1,
    ) -> None:
        self._attest()
        if (
            type(projection) is not DisabledExternalAgentProjectionV1
            or type(receipt) is not DisabledExternalAgentReceiptV1
        ):
            raise DisabledExternalAgentDescriptorV1ContractError(
                "exact projection and receipt are required"
            )
        expected = (
            receipt.request_id == projection.request_id
            and receipt.identity_digest == projection.identity_digest
            and receipt.projection_digest == projection.digest
            and receipt.descriptor_digest == projection.descriptor_digest
            and receipt.health is projection.health
            and receipt.access_reason == projection.access_reason
            and receipt.component_root_digest == self._component_root_digest
        )
        tag = hmac.new(
            self._receipt_key,
            _canonical(receipt.unsigned_payload()),
            hashlib.sha256,
        ).hexdigest()
        if not expected or not hmac.compare_digest(
            receipt.authentication_tag,
            tag,
        ):
            raise DisabledExternalAgentDescriptorV1Denied(
                "forged disabled descriptor receipt denied"
            )

    def describe(
        self,
        query: ExternalAgentDescriptorQueryV1,
    ) -> tuple[
        DisabledExternalAgentProjectionV1,
        DisabledExternalAgentReceiptV1,
    ]:
        if type(query) is not ExternalAgentDescriptorQueryV1:
            raise DisabledExternalAgentDescriptorV1ContractError(
                "exact descriptor query is required"
            )
        with self._lock:
            if query.cancelled:
                raise DisabledExternalAgentDescriptorV1Denied(
                    "descriptor query cancellation is final"
                )
            self._attest()
            prior = self._replays.get(query.request_id)
            if prior is not None:
                if not hmac.compare_digest(prior[0], query.digest):
                    raise DisabledExternalAgentDescriptorV1Conflict(
                        "descriptor request conflicts with prior input"
                    )
                self.attest_receipt(prior[1], prior[2])
                return prior[1], prior[2]
            if query.identity != self._descriptor.identity:
                raise DisabledExternalAgentDescriptorV1Denied(
                    "descriptor query identity denied"
                )
            if (
                query.expected_version != self._descriptor.descriptor_version
                or not hmac.compare_digest(
                    query.expected_descriptor_digest,
                    self._descriptor.digest,
                )
            ):
                raise DisabledExternalAgentDescriptorV1Denied(
                    "descriptor version or digest drift denied"
                )
            projection = DisabledExternalAgentProjectionV1(
                request_id=query.request_id,
                identity_digest=query.identity.digest,
                descriptor=self._descriptor,
                descriptor_digest=self._descriptor.digest,
                health=CapabilityStatusV32.BLOCKED_BY_ACCESS,
                access_reason=ACCESS_REASON,
                required_scopes=(),
                granted_scopes=(),
                authentication=ExternalAgentAuthenticationStateV1.ABSENT,
            )
            receipt = self._receipt(query, projection)
            self.attest_receipt(projection, receipt)
            self._replays[query.request_id] = (
                query.digest,
                projection,
                receipt,
            )
            return projection, receipt


def _build_descriptor(
    identity: ExternalAgentDescriptorIdentityV1,
) -> DisabledExternalAgentDescriptorV1:
    operation = OperationDescriptorV32(
        operation_id="external_agent_availability",
        kind=OperationKindV32.VERIFY,
        description="Project disabled external-agent availability metadata.",
        parameter_schema_json='{"additionalProperties":false,"properties":{},"type":"OBJECT"}',
        required_scopes=(),
        data_classes=("metadata_only",),
        risk_class="blocked",
        approval_class="not_applicable",
        cancellation="no_session_cancel_is_final",
        timeout="not_applicable",
        idempotency="request_digest_replay",
        receipt="authenticated_blocked_projection",
        reconciliation="descriptor_digest_only",
        quota="not_applicable",
        cost="zero",
        dry_run="not_applicable",
        test_account="not_applicable",
        host_policy="access_required_before_activation",
    )
    capability = CapabilityDescriptorV32(
        capability_id="external_agent_disabled",
        capability_version=DESCRIPTOR_VERSION,
        provider=identity.provider_id,
        transport=TransportKindV32.LEGACY,
        api_name="external_agent",
        api_version=DESCRIPTOR_VERSION,
        workspace_id=identity.workspace_id,
        account_id=identity.account_id,
        profile_id=identity.profile_id,
        credential_alias=None,
        operations=(operation,),
        status=CapabilityStatusV32.BLOCKED_BY_ACCESS,
        status_reason=ACCESS_REASON,
        limitations=(
            "authentication_absent",
            "no_dispatch",
            "no_live_wiring",
            "no_provider_session",
        ),
        metadata=(),
    )
    model = ModelDescriptorV1(
        adapter_id=identity.adapter_id,
        status=AdapterStatusV1.BLOCKED_BY_ACCESS,
        modalities=("external_agent",),
        maximum_data_class=DataClassV1.PUBLIC,
        workspace_allowlist=(identity.workspace_id,),
        local_private=False,
        network_required=True,
        structured_output=True,
        reliability_milli=0,
        latency_millis=3_600_000,
        cost_micro_per_call=1_000_000_000,
    )
    provider = ProviderRecordV1(
        provider_id=identity.provider_id,
        api_version=DESCRIPTOR_VERSION,
        model_id="models/disabled-external-agent",
        record_version=1,
        prompt_metadata_digest=_digest(
            b"disabled-external-agent-no-prompt-authority"
        ),
        evaluation_metadata_digest=_digest(
            b"disabled-external-agent-blocked-by-access"
        ),
        descriptor=model,
    )
    return DisabledExternalAgentDescriptorV1(
        _construction_key=_CONSTRUCTION_KEY,
        identity=identity,
        capability_contract=capability,
        provider_contract=provider,
    )


def create_disabled_external_agent_descriptor_v1(
    *,
    gate: DisabledExternalAgentFeatureGateV1,
    identity: ExternalAgentDescriptorIdentityV1 | None = None,
    project_root: Path | str | None = None,
    receipt_authentication_key: bytes = b"",
) -> DisabledExternalAgentDescriptorCatalogV1 | None:
    if type(gate) is not DisabledExternalAgentFeatureGateV1:
        raise DisabledExternalAgentDescriptorV1ContractError(
            "exact feature gate is required"
        )
    if not gate.enabled:
        return None
    if type(identity) is not ExternalAgentDescriptorIdentityV1:
        raise DisabledExternalAgentDescriptorV1ContractError(
            "enabled descriptor requires exact identity"
        )
    if project_root is None:
        raise DisabledExternalAgentDescriptorV1ContractError(
            "explicit absolute project root is required"
        )
    root = Path(project_root)
    if not root.is_absolute():
        raise DisabledExternalAgentDescriptorV1ContractError(
            "explicit absolute project root is required"
        )
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise DisabledExternalAgentDescriptorV1ContractError(
            "project root is unavailable"
        ) from exc
    if not root.is_dir() or root.is_symlink():
        raise DisabledExternalAgentDescriptorV1ContractError(
            "project root must be a regular directory"
        )
    return DisabledExternalAgentDescriptorCatalogV1(
        _construction_key=_CONSTRUCTION_KEY,
        descriptor=_build_descriptor(identity),
        project_root=root,
        receipt_authentication_key=receipt_authentication_key,
    )


__all__ = [
    "ACCESS_REASON",
    "CANDIDATE",
    "COMPONENT_ACCEPTANCE_ROOTS",
    "DESCRIPTOR_VERSION",
    "FEATURE_FLAG",
    "DisabledExternalAgentDescriptorCatalogV1",
    "DisabledExternalAgentDescriptorV1",
    "DisabledExternalAgentDescriptorV1Conflict",
    "DisabledExternalAgentDescriptorV1ContractError",
    "DisabledExternalAgentDescriptorV1Denied",
    "DisabledExternalAgentDescriptorV1Error",
    "DisabledExternalAgentFeatureGateV1",
    "DisabledExternalAgentProjectionV1",
    "DisabledExternalAgentReceiptV1",
    "ExternalAgentAuthenticationStateV1",
    "ExternalAgentCancellationSemanticsV1",
    "ExternalAgentDescriptorIdentityV1",
    "ExternalAgentDescriptorQueryV1",
    "ExternalAgentReceiptSemanticsV1",
    "create_disabled_external_agent_descriptor_v1",
]
