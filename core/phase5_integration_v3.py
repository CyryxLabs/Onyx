"""Independent default-off V3 host integration for accepted Phase 5 components.

This module is the only bridge between the accepted, immutable Phase 5
candidates and the live host.  It owns no UI, provider, remote approval or
legacy dispatch authority.  The sole executable extension is the exact
provider-free ``local.catalog/catalog_read`` contract.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from core import approval_inbox_v15 as inbox_v15
from core import capability_nexus_v32 as nexus_v32
from core import phase5_component_adapters_v3 as adapters_v3
from core import phase5_runtime_v10 as runtime_v10
from core import session_grants_v11 as grants_v11
from core.tool_audit import append_tool_audit


PHASE5_INTEGRATION_FLAG = "ONYX_PHASE5_INTEGRATION_V3"
PHASE5_RUNTIME_FLAG = "ONYX_PHASE5_RUNTIME_V3"
PHASE5_GRANT_SHADOW_FLAG = "ONYX_PHASE5_GRANT_SHADOW_V3"
PHASE5_APPROVAL_INBOX_FLAG = "ONYX_PHASE5_APPROVAL_INBOX_V3"
PHASE5_LOW_RISK_FLAG = "ONYX_PHASE5_LOW_RISK_V3"
PHASE5_NEXUS_PROJECTION_FLAG = "ONYX_PHASE5_NEXUS_PROJECTION_V3"
PHASE5_LOCAL_CATALOG_READ_FLAG = "ONYX_PHASE5_LOCAL_CATALOG_READ_V3"
PHASE5_DASHBOARD_PROJECTION_FLAG = "ONYX_PHASE5_DASHBOARD_PROJECTION_V3"

PHASE5_PRINCIPAL_ID = "ONYX_PHASE5_PRINCIPAL_ID"
PHASE5_WORKSPACE_ID = "ONYX_PHASE5_WORKSPACE_ID"
PHASE5_ACCOUNT_ID = "ONYX_PHASE5_ACCOUNT_ID"
PHASE5_PROFILE_ID = "ONYX_PHASE5_PROFILE_ID"

LOCAL_CATALOG_TOOL = "local_catalog_read"
LOCAL_CATALOG_DECLARATION = {
    "name": LOCAL_CATALOG_TOOL,
    "description": (
        "Reads only allowlisted metadata from Onyx's provider-free local "
        "capability catalog. It cannot read file contents or mutate anything."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "page_size": {
                "type": "INTEGER",
                "description": "Number of metadata entries, from 1 through 50.",
            },
            "cursor": {
                "type": "STRING",
                "description": "Opaque cursor returned by the prior page.",
            },
        },
    },
}

_TRUE = frozenset({"1", "true"})
_MAX_PREPARED = 64
_MAX_SEALS = 256
_PERMISSION_KEYS = frozenset({"page_size", "cursor", "_phase5_invocation_ref"})
_DISPATCH_KEYS = frozenset({"page_size", "cursor"})
_HOST_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")


class Phase5IntegrationV3Error(RuntimeError):
    """The live host bridge could not safely complete an operation."""


class Phase5IntegrationV3ContractError(ValueError):
    """A host input violated the closed integration contract."""


def _enabled(value: object) -> bool:
    return type(value) is str and value.strip().casefold() in _TRUE


def phase5_requested(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return _enabled(source.get(PHASE5_INTEGRATION_FLAG, "")) and _enabled(
        source.get(PHASE5_RUNTIME_FLAG, "")
    )


def phase5_dashboard_requested(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return phase5_requested(source) and _enabled(
        source.get(PHASE5_DASHBOARD_PROJECTION_FLAG, "")
    )


@dataclass(frozen=True, slots=True)
class IntegrationFlagsV3:
    integration: bool = False
    runtime: bool = False
    grant_shadow: bool = False
    approval_inbox: bool = False
    low_risk: bool = False
    nexus_projection: bool = False
    local_catalog_read: bool = False
    dashboard_projection: bool = False

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if type(getattr(self, name)) is not bool:
                raise Phase5IntegrationV3ContractError(f"{name} must be exact bool")
        children = (
            self.grant_shadow,
            self.approval_inbox,
            self.low_risk,
            self.nexus_projection,
            self.local_catalog_read,
            self.dashboard_projection,
        )
        if (self.runtime or any(children)) and not self.integration:
            raise Phase5IntegrationV3ContractError(
                "Phase 5 features require the integration master flag"
            )
        if any(children) and not self.runtime:
            raise Phase5IntegrationV3ContractError(
                "Phase 5 child features require the runtime flag"
            )
        if self.local_catalog_read and not self.low_risk:
            raise Phase5IntegrationV3ContractError(
                "local catalog read requires exact low-risk enablement"
            )

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "IntegrationFlagsV3":
        source = os.environ if environ is None else environ
        return cls(
            integration=_enabled(source.get(PHASE5_INTEGRATION_FLAG, "")),
            runtime=_enabled(source.get(PHASE5_RUNTIME_FLAG, "")),
            grant_shadow=_enabled(source.get(PHASE5_GRANT_SHADOW_FLAG, "")),
            approval_inbox=_enabled(source.get(PHASE5_APPROVAL_INBOX_FLAG, "")),
            low_risk=_enabled(source.get(PHASE5_LOW_RISK_FLAG, "")),
            nexus_projection=_enabled(
                source.get(PHASE5_NEXUS_PROJECTION_FLAG, "")
            ),
            local_catalog_read=_enabled(
                source.get(PHASE5_LOCAL_CATALOG_READ_FLAG, "")
            ),
            dashboard_projection=_enabled(
                source.get(PHASE5_DASHBOARD_PROJECTION_FLAG, "")
            ),
        )

    def runtime_flags(self) -> runtime_v10.RuntimeFlagsV10:
        return runtime_v10.RuntimeFlagsV10(
            runtime=self.runtime,
            grant_shadow=self.grant_shadow,
            approval_inbox=self.approval_inbox,
            low_risk=self.low_risk,
            nexus_projection=self.nexus_projection,
            local_catalog_read=self.local_catalog_read,
            dashboard_projection=self.dashboard_projection,
        )


@dataclass(frozen=True, slots=True)
class IntegrationIdentityV3:
    principal_id: str
    workspace_id: str
    account_id: str
    profile_id: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not str or _HOST_ID.fullmatch(value) is None:
                raise Phase5IntegrationV3ContractError(
                    f"{name} must be an explicit canonical host identifier"
                )

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "IntegrationIdentityV3":
        source = os.environ if environ is None else environ
        values = {
            "principal_id": source.get(PHASE5_PRINCIPAL_ID, ""),
            "workspace_id": source.get(PHASE5_WORKSPACE_ID, ""),
            "account_id": source.get(PHASE5_ACCOUNT_ID, ""),
            "profile_id": source.get(PHASE5_PROFILE_ID, ""),
        }
        missing = tuple(name for name, value in values.items() if not value)
        if missing:
            raise Phase5IntegrationV3ContractError(
                "explicit Phase 5 identity is required: " + ",".join(missing)
            )
        return cls(**values)


@dataclass(frozen=True, slots=True)
class CatalogSeedV3:
    item_id: str
    label: str
    category: str = "tool"
    item_version: str = "current"
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NormalizedCatalogDispatchV3:
    """Closed, immutable representation of every material catalog argument."""

    page_size: int
    cursor: str | None

    @classmethod
    def from_arguments(
        cls, arguments: Mapping[str, object], *, permission_stage: bool
    ) -> "NormalizedCatalogDispatchV3":
        if not isinstance(arguments, Mapping):
            raise Phase5IntegrationV3ContractError(
                "catalog arguments must be a mapping"
            )
        allowed = _PERMISSION_KEYS if permission_stage else _DISPATCH_KEYS
        if set(arguments) - allowed:
            raise Phase5IntegrationV3ContractError(
                "catalog arguments contain fields outside the closed contract"
            )
        page_size = arguments.get("page_size", 25)
        cursor = arguments.get("cursor")
        if type(page_size) is not int or not 1 <= page_size <= 50:
            raise Phase5IntegrationV3ContractError(
                "catalog page_size must be an exact integer from 1 through 50"
            )
        if cursor is not None and (type(cursor) is not str or len(cursor) > 2048):
            raise Phase5IntegrationV3ContractError("catalog cursor is invalid")
        return cls(page_size=page_size, cursor=cursor)

    def payload(self) -> dict[str, object]:
        return {"cursor": self.cursor, "page_size": self.page_size}

    def digest(self) -> str:
        return _sha(self.payload())


@dataclass(frozen=True, slots=True)
class _InvocationSealV3:
    state: str
    expected_digest: str


@dataclass(frozen=True, slots=True)
class _PreparedCatalogReadV3:
    reference: str
    action: runtime_v10.ActionRequestV10
    decision: runtime_v10.RuntimeDecisionV10
    dispatch: NormalizedCatalogDispatchV3
    dispatch_digest: str


@dataclass(frozen=True, slots=True)
class _HostRuntimeComponentsV3:
    grant_evaluator: Callable[[str], object] | None = None
    nexus_projector: Callable[[object], object] | None = None
    inbox_factory: Callable[[object], object] | None = None
    grant_terminator: Callable[[str], None] | None = None
    nexus_terminator: Callable[[str], None] | None = None
    inbox_terminator: Callable[[str], None] | None = None


def _host_components_factory_v3(**components: object) -> _HostRuntimeComponentsV3:
    return _HostRuntimeComponentsV3(**components)  # type: ignore[arg-type]


class _GrantMaterializerV3:
    def __init__(self, owner: "Phase5IntegrationV3") -> None:
        self._owner = owner

    def __call__(self, reference: str) -> runtime_v10.ActionRequestV10:
        return self._owner._materialize_runtime_action(reference)


def _sha(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _plain(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


class Phase5IntegrationV3:
    """One session-scoped, fail-closed host bridge."""

    def __init__(
        self,
        *,
        binding: runtime_v10.RuntimeBindingV10,
        principal_id: str,
        flags: IntegrationFlagsV3,
        catalog: Sequence[CatalogSeedV3],
    ) -> None:
        if type(binding) is not runtime_v10.RuntimeBindingV10:
            raise Phase5IntegrationV3ContractError("exact RuntimeBindingV10 required")
        if type(principal_id) is not str or _HOST_ID.fullmatch(principal_id) is None:
            raise Phase5IntegrationV3ContractError(
                "principal_id must be an explicit canonical host identifier"
            )
        if type(flags) is not IntegrationFlagsV3 or not flags.integration or not flags.runtime:
            raise Phase5IntegrationV3ContractError("active integration flags required")
        if type(catalog) not in {tuple, list} or len(catalog) > 128:
            raise Phase5IntegrationV3ContractError("catalog seed is invalid")
        self._binding = binding
        self._principal_id = principal_id
        self._flags = flags
        self._lock = threading.RLock()
        self._closed = False
        self._prepared: OrderedDict[str, _PreparedCatalogReadV3] = OrderedDict()
        self._seals: OrderedDict[str, _InvocationSealV3] = OrderedDict()
        self._runtime_actions: OrderedDict[str, runtime_v10.ActionRequestV10] = (
            OrderedDict()
        )
        self._grant_actions: OrderedDict[str, grants_v11.ResolvedAction] = OrderedDict()
        self._inbox_epoch = 1

        items = tuple(
            nexus_v32.CatalogItemV32(
                seed.item_id,
                seed.label,
                seed.category,
                seed.item_version,
                seed.tags,
            )
            for seed in catalog
            if type(seed) is CatalogSeedV3
        )
        if len(items) != len(catalog):
            raise Phase5IntegrationV3ContractError("catalog entries must be exact")
        available = flags.low_risk and flags.local_catalog_read
        self._catalog = nexus_v32.LocalCatalogReadAdapterV32(
            items,
            workspace_id=binding.workspace_id,
            account_id=binding.account_id,
            profile_id=binding.profile_id,
            cursor_signing_key=secrets.token_bytes(32),
            read_hook=lambda: None,
            credential_alias=None,
            auth_available=True,
            status=(
                nexus_v32.CapabilityStatusV32.AVAILABLE_READ_ONLY
                if available
                else nexus_v32.CapabilityStatusV32.DISABLED
            ),
            status_reason="healthy" if available else "candidate_not_activated",
            quota_limit=1_000,
            rate_limit=1_000,
        )
        self._nexus = nexus_v32.CapabilityNexusV32()
        self._nexus.register(self._catalog.descriptor)

        self._grant_gate = grants_v11.MonotonicFeatureGate(
            enabled=flags.grant_shadow
        )
        self._grant_store = grants_v11.SessionGrantShadowStore(
            grants_v11.HostServices(
                "onyx-phase5-host-v3",
                self._grant_gate,
                self._unsupported_grant_scope,
                self._resolve_grant_action,
                self._unsupported_outcome,
                self._unsupported_approval,
                self._unsupported_receipt,
                self._unsupported_reconciliation,
                self._grant_state,
                self._monotonic_ms,
            )
        )

        authority = adapters_v3.HostAttestationAuthorityV3(secrets.token_bytes(32))
        grant_materializer = _GrantMaterializerV3(self)
        adapter_flags = adapters_v3.AdapterFlagsV3(
            adapters=any(
                (flags.grant_shadow, flags.nexus_projection, flags.approval_inbox)
            ),
            grant_shadow=flags.grant_shadow,
            nexus_projection=flags.nexus_projection,
            approval_inbox=flags.approval_inbox,
        )
        acceptance = adapters_v3.AcceptedComponentsV3(
            grants=(adapters_v3.GRANTS_ACCEPTANCE_V3 if flags.grant_shadow else None),
            nexus=(adapters_v3.NEXUS_ACCEPTANCE_V3 if flags.nexus_projection else None),
            inbox=(adapters_v3.INBOX_ACCEPTANCE_V3 if flags.approval_inbox else None),
        )
        attestations: dict[str, adapters_v3.ComponentAttestationV3] = {}
        if adapter_flags.adapters:
            component_values: dict[str, object] = {
                "batch_factory": runtime_v10.ProjectionBatchV10,
                "components_factory": _host_components_factory_v3,
            }
            if flags.grant_shadow:
                component_values.update(
                    grant_store=self._grant_store,
                    grant_materializer=grant_materializer,
                    action_request_type=runtime_v10.ActionRequestV10,
                )
            if flags.nexus_projection:
                component_values["nexus"] = self._nexus
            attestations = {
                role: authority.issue_component(value, role=role, generation=0)
                for role, value in component_values.items()
            }
        inbox_construction = (
            adapters_v3.InboxConstructionInputsV3(
                principal_id,
                self._capture_inbox,
                self._read_inbox_epoch,
                inbox_v15.MonotonicInboxClockV15(),
            )
            if flags.approval_inbox
            else None
        )
        self._bundle = adapters_v3.build_component_adapters_v3(
            flags=adapter_flags,
            acceptance=acceptance,
            binding=binding,
            binding_attestor=lambda: self._binding,
            authority=authority,
            attestations=attestations,
            batch_factory=runtime_v10.ProjectionBatchV10,
            components_factory=_host_components_factory_v3,
            action_request_type=(runtime_v10.ActionRequestV10 if flags.grant_shadow else None),
            grant_store=(self._grant_store if flags.grant_shadow else None),
            materialize_grant_request=(
                grant_materializer if flags.grant_shadow else None
            ),
            nexus=(self._nexus if flags.nexus_projection else None),
            inbox_construction=inbox_construction,
        )
        host_components = self._bundle.runtime_components
        components = runtime_v10.RuntimeComponentsV10(
            grant_evaluator=getattr(host_components, "grant_evaluator", None),
            nexus_projector=getattr(host_components, "nexus_projector", None),
            inbox_factory=getattr(host_components, "inbox_factory", None),
            termination_actions=("grant", "nexus", "inbox", "rollback"),
        )
        self._runtime = runtime_v10.Phase5RuntimeV10(
            binding=binding,
            flags=flags.runtime_flags(),
            components=components,
        )
        for component, enabled in (
            ("grant_shadow", flags.grant_shadow),
            ("nexus", flags.nexus_projection),
            ("inbox", flags.approval_inbox),
        ):
            if enabled:
                self._runtime.recover_component(component)

    @property
    def binding(self) -> runtime_v10.RuntimeBindingV10:
        return self._runtime.binding

    @property
    def local_catalog_enabled(self) -> bool:
        with self._lock:
            return (
                not self._closed
                and self._flags.low_risk
                and self._flags.local_catalog_read
            )

    @property
    def dashboard_enabled(self) -> bool:
        with self._lock:
            return not self._closed and self._flags.dashboard_projection

    def tool_declarations(self) -> tuple[dict[str, object], ...]:
        return (json.loads(json.dumps(LOCAL_CATALOG_DECLARATION)),) if self.local_catalog_enabled else ()

    def _monotonic_ms(self) -> int:
        return time.monotonic_ns() // 1_000_000

    def _grant_state(self) -> grants_v11.HostState:
        policy = grants_v11.HostActionPolicy(
            "local-catalog", "local-catalog", "catalog-read", "low", False, "internal"
        )
        return grants_v11.HostState(
            grants_v11.GRANT_SCHEMA_VERSION,
            grants_v11.GRANT_POLICY_VERSION,
            self._principal_id,
            self._binding.session_id,
            self._binding.workspace_id,
            (),
            (policy,),
            _sha("phase5-host-audit-head"),
            0,
            0,
        )

    @staticmethod
    def _unsupported_grant_scope(_reference: str) -> object:
        raise Phase5IntegrationV3Error("grant creation is unavailable")

    @staticmethod
    def _unsupported_outcome(_reference: str) -> object:
        raise Phase5IntegrationV3Error("mutation outcome is unavailable")

    @staticmethod
    def _unsupported_approval(_prompt: object) -> object:
        raise Phase5IntegrationV3Error("approval is unavailable")

    @staticmethod
    def _unsupported_receipt(_request: object) -> object:
        raise Phase5IntegrationV3Error("mutation receipt is unavailable")

    @staticmethod
    def _unsupported_reconciliation(_request: object) -> object:
        raise Phase5IntegrationV3Error("mutation reconciliation is unavailable")

    def _materialize_runtime_action(self, reference: str) -> runtime_v10.ActionRequestV10:
        with self._lock:
            action = self._runtime_actions.get(reference)
        if action is None:
            action, grant_action = self._make_actions(reference, {})
            with self._lock:
                self._remember_action(reference, action, grant_action)
        return action

    def _resolve_grant_action(self, reference: str) -> grants_v11.ResolvedAction:
        with self._lock:
            action = self._grant_actions.get(reference)
        if action is None:
            runtime_action, action = self._make_actions(reference, {})
            with self._lock:
                self._remember_action(reference, runtime_action, action)
        return action

    def _make_actions(
        self, reference: str, arguments: Mapping[str, object]
    ) -> tuple[runtime_v10.ActionRequestV10, grants_v11.ResolvedAction]:
        payload_digest = _sha(
            {
                "cursor": arguments.get("cursor"),
                "page_size": arguments.get("page_size", 25),
            }
        )
        runtime_action = runtime_v10.ActionRequestV10(
            invocation_ref=reference,
            binding=self._binding,
            capability="local.catalog",
            operation="catalog_read",
            provider_free=True,
            read_only=True,
            effect="none",
            egress="none",
            metadata_allowlisted=True,
            cost_micro=0,
            risk="low",
            reversible=True,
            uses_credentials=False,
            privileged=False,
            irreversible=False,
            action_classes=(),
        )
        binding = grants_v11.ActionBinding(
            "onyx-local",
            "local-catalog",
            _sha("local_catalog"),
            "local-catalog",
            payload_digest,
            "Read allowlisted local capability metadata",
            "catalog-metadata-v3",
            "none",
            f"catalog-{reference}",
        )
        grant_action = grants_v11.ResolvedAction(
            None,
            "local-catalog",
            "local-catalog",
            "catalog-read",
            binding,
            self._binding.account_id,
            "local-catalog",
            "none",
            "local",
            "internal",
            True,
            "Verify the signed completed read receipt",
            "No mutation; discard the local projection",
            "USD",
            "local-micro",
            0,
        )
        return runtime_action, grant_action

    def _remember_action(
        self,
        reference: str,
        runtime_action: runtime_v10.ActionRequestV10,
        grant_action: grants_v11.ResolvedAction,
    ) -> None:
        self._runtime_actions[reference] = runtime_action
        self._grant_actions[reference] = grant_action
        while len(self._runtime_actions) > _MAX_PREPARED:
            old, _ = self._runtime_actions.popitem(last=False)
            self._grant_actions.pop(old, None)

    @staticmethod
    def _seal_key(reference: str) -> str:
        return hashlib.sha256(reference.encode()).hexdigest()

    def _purge_reference(self, seal_key: str, reference: str) -> None:
        self._prepared.pop(seal_key, None)
        self._runtime_actions.pop(reference, None)
        self._grant_actions.pop(reference, None)

    def _remember_seal(
        self, seal_key: str, *, state: str, expected_digest: str
    ) -> None:
        self._seals[seal_key] = _InvocationSealV3(state, expected_digest)
        self._seals.move_to_end(seal_key)
        while len(self._seals) > _MAX_SEALS:
            old_key, _ = self._seals.popitem(last=False)
            prepared = self._prepared.pop(old_key, None)
            if prepared is not None:
                self._runtime.consume_decision(prepared.decision, prepared.action)
                self._runtime_actions.pop(prepared.reference, None)
                self._grant_actions.pop(prepared.reference, None)

    @staticmethod
    def _observed_permission_digest(arguments: Mapping[str, object]) -> str:
        try:
            return NormalizedCatalogDispatchV3.from_arguments(
                arguments, permission_stage=True
            ).digest()
        except (Phase5IntegrationV3ContractError, TypeError, ValueError):
            try:
                shape = sorted(
                    (str(key), type(value).__name__)
                    for key, value in arguments.items()
                    if key != "_phase5_invocation_ref"
                )
            except BaseException:
                shape = [("unavailable", "invalid-mapping")]
            return _sha({"invalid_argument_shape": shape})

    def _audit_guard(
        self,
        *,
        reference: str,
        reason: str,
        expected_digest: str,
        observed_digest: str,
    ) -> None:
        try:
            append_tool_audit(
                profile="runtime",
                tool=LOCAL_CATALOG_TOOL,
                action="catalog_read",
                decision="deny",
                reason=reason,
                arguments={
                    "invocation_digest": self._seal_key(reference),
                    "expected_digest": expected_digest,
                    "observed_digest": observed_digest,
                },
                outcome="rejected",
                trace_id=self._binding.trace_id,
                error_type="Phase5V3AuthorizationSealBurned",
            )
        except BaseException:
            return

    def permission_hook(
        self, tool_name: str, arguments: Mapping[str, object]
    ) -> tuple[bool, str] | None:
        if tool_name != LOCAL_CATALOG_TOOL:
            return None
        reference = arguments.get("_phase5_invocation_ref")
        if type(reference) is not str:
            return False, "Permission denied: missing host invocation binding."
        seal_key = self._seal_key(reference)
        collision: tuple[str, str] | None = None
        with self._lock:
            existing_seal = self._seals.get(seal_key)
            if existing_seal is not None:
                prepared = self._prepared.pop(seal_key, None)
                if prepared is not None:
                    self._runtime.consume_decision(
                        prepared.decision, prepared.action
                    )
                    self._purge_reference(seal_key, prepared.reference)
                else:
                    self._runtime_actions.pop(reference, None)
                    self._grant_actions.pop(reference, None)
                observed_digest = self._observed_permission_digest(arguments)
                self._remember_seal(
                    seal_key,
                    state="burned-collision",
                    expected_digest=existing_seal.expected_digest,
                )
                collision = (existing_seal.expected_digest, observed_digest)
            else:
                self._remember_seal(
                    seal_key, state="observed", expected_digest=_sha("unvalidated")
                )
        if collision is not None:
            self._audit_guard(
                reference=reference,
                reason="phase5-v3-invocation-collision-burned",
                expected_digest=collision[0],
                observed_digest=collision[1],
            )
            return False, "Permission denied: invocation collision burned authorization."

        try:
            normalized = NormalizedCatalogDispatchV3.from_arguments(
                arguments, permission_stage=True
            )
        except Phase5IntegrationV3ContractError as exc:
            with self._lock:
                self._remember_seal(
                    seal_key,
                    state="burned-invalid",
                    expected_digest=self._observed_permission_digest(arguments),
                )
            return False, f"Permission denied: {exc}."

        with self._lock:
            current_seal = self._seals.get(seal_key)
            if current_seal is None or current_seal.state != "observed":
                expected = (
                    current_seal.expected_digest
                    if current_seal is not None
                    else _sha("missing-seal")
                )
                self._remember_seal(
                    seal_key,
                    state="burned-concurrent-collision",
                    expected_digest=expected,
                )
                self._audit_guard(
                    reference=reference,
                    reason="phase5-v3-concurrent-collision-burned",
                    expected_digest=expected,
                    observed_digest=normalized.digest(),
                )
                return False, (
                    "Permission denied: concurrent invocation collision burned "
                    "authorization."
                )
            if self._closed or not self.local_catalog_enabled:
                self._remember_seal(
                    seal_key,
                    state="burned-disabled",
                    expected_digest=normalized.digest(),
                )
                return False, "Permission denied: local catalog is disabled."
            self._remember_seal(
                seal_key, state="prepared", expected_digest=normalized.digest()
            )
            action, grant_action = self._make_actions(
                reference, normalized.payload()
            )
            self._remember_action(reference, action, grant_action)
            decision = self._runtime.evaluate(action)
            if (
                decision.disposition
                is not runtime_v10.RuntimeDispositionV10.ALLOW_LOCAL_CATALOG_READ
            ):
                self._purge_reference(seal_key, reference)
                self._remember_seal(
                    seal_key,
                    state="burned-runtime-denial",
                    expected_digest=normalized.digest(),
                )
                return False, f"Permission denied: {decision.reason}."
            self._prepared[seal_key] = _PreparedCatalogReadV3(
                reference=reference,
                action=action,
                decision=decision,
                dispatch=normalized,
                dispatch_digest=normalized.digest(),
            )
            while len(self._prepared) > _MAX_PREPARED:
                old_key, evicted = self._prepared.popitem(last=False)
                self._runtime.consume_decision(evicted.decision, evicted.action)
                self._runtime_actions.pop(evicted.reference, None)
                self._grant_actions.pop(evicted.reference, None)
                self._remember_seal(
                    old_key,
                    state="burned-capacity",
                    expected_digest=evicted.dispatch_digest,
                )
        return True, f"phase5-local-catalog-v3:{reference}"

    def catalog_read(
        self, invocation_ref: str, arguments: Mapping[str, object]
    ) -> dict[str, object]:
        seal_key = self._seal_key(invocation_ref)
        observed: NormalizedCatalogDispatchV3 | None = None
        observed_digest = _sha("invalid-dispatch")
        normalization_error = ""
        try:
            observed = NormalizedCatalogDispatchV3.from_arguments(
                arguments, permission_stage=False
            )
            observed_digest = observed.digest()
        except Phase5IntegrationV3ContractError as exc:
            normalization_error = str(exc)

        failure_reason = ""
        expected_digest = _sha("unavailable")
        projection = None
        with self._lock:
            prepared = self._prepared.pop(seal_key, None)
            if self._closed or prepared is None:
                self._runtime_actions.pop(invocation_ref, None)
                self._grant_actions.pop(invocation_ref, None)
                raise Phase5IntegrationV3Error(
                    "catalog authorization is unavailable"
                )
            expected_digest = prepared.dispatch_digest
            exact = (
                observed is not None
                and observed == prepared.dispatch
                and hmac.compare_digest(observed_digest, prepared.dispatch_digest)
            )
            if not exact:
                self._runtime.consume_decision(prepared.decision, prepared.action)
                self._purge_reference(seal_key, prepared.reference)
                self._remember_seal(
                    seal_key,
                    state="burned-dispatch-mismatch",
                    expected_digest=prepared.dispatch_digest,
                )
                failure_reason = (
                    "phase5-v3-invalid-dispatch"
                    if normalization_error
                    else "phase5-v3-dispatch-binding-mismatch"
                )
            else:
                consumed = self._runtime.consume_decision(
                    prepared.decision, prepared.action
                )
                self._runtime_actions.pop(prepared.reference, None)
                self._grant_actions.pop(prepared.reference, None)
                if not consumed:
                    self._remember_seal(
                        seal_key,
                        state="burned-stale",
                        expected_digest=prepared.dispatch_digest,
                    )
                    failure_reason = "phase5-v3-stale-decision"
                else:
                    self._remember_seal(
                        seal_key,
                        state="consumed",
                        expected_digest=prepared.dispatch_digest,
                    )
                    assert observed is not None
                    request = nexus_v32.CatalogReadRequestV32(
                        self._binding.workspace_id,
                        self._binding.account_id,
                        self._binding.profile_id,
                        nexus_v32.LocalCatalogReadAdapterV32.TARGET,
                        invocation_ref,
                        page_size=observed.page_size,
                        cursor=observed.cursor,
                    )
                    projection = self._catalog.read_page(request)

        if failure_reason:
            self._audit_guard(
                reference=invocation_ref,
                reason=failure_reason,
                expected_digest=expected_digest,
                observed_digest=observed_digest,
            )
            if failure_reason == "phase5-v3-stale-decision":
                raise Phase5IntegrationV3Error("catalog authorization is stale")
            raise Phase5IntegrationV3Error(
                "catalog dispatch does not match its immutable authorization"
            )

        assert projection is not None
        if projection.state is not nexus_v32.ReadStateV32.COMPLETED:
            raise Phase5IntegrationV3Error(
                f"catalog read did not complete: {projection.failure_class.value}"
            )
        return {
            "capability": "local.catalog",
            "operation": "catalog_read",
            "state": projection.state.value,
            "items": [item.payload() for item in projection.items],
            "next_cursor": projection.next_cursor,
            "receipt_digest": projection.receipt_digest,
            "cost_micro": 0,
            "egress": "none",
        }

    def _capture_inbox(self) -> inbox_v15.HostInboxSnapshotV15:
        return inbox_v15.HostInboxSnapshotV15(
            self._inbox_epoch, self._monotonic_ms(), ()
        )

    def _read_inbox_epoch(self) -> int:
        with self._lock:
            return self._inbox_epoch

    def dashboard_read(
        self, surface: str, *, offset: int = 0, page_size: int = 50
    ) -> dict[str, object]:
        if not self.dashboard_enabled:
            raise Phase5IntegrationV3Error("dashboard projection is disabled")
        value = self._runtime.dashboard_read(
            surface, offset=offset, page_size=page_size
        )
        return {"surface": surface, "data": _plain(value)}

    def status_payload(self) -> dict[str, object]:
        return {"surface": "status", "data": _plain(self._runtime.status())}

    def _close_host_action(self, action: str, reason: str) -> None:
        if action == "grant":
            terminator = getattr(self._bundle.runtime_components, "grant_terminator", None)
            if terminator is not None:
                terminator(reason)
            return
        if action == "nexus":
            self._catalog.set_kill(True)
            self._catalog.revoke()
            self._nexus.set_kill(True)
            terminator = getattr(self._bundle.runtime_components, "nexus_terminator", None)
            if terminator is not None:
                terminator(reason)
            return
        if action == "inbox":
            with self._lock:
                self._inbox_epoch += 1
            terminator = getattr(self._bundle.runtime_components, "inbox_terminator", None)
            if terminator is not None:
                terminator(reason)
            return
        if action == "rollback":
            with self._lock:
                self._prepared.clear()
                self._runtime_actions.clear()
                self._grant_actions.clear()
            return
        raise Phase5IntegrationV3ContractError("unknown host termination action")

    def terminate(self, reason: str) -> dict[str, object]:
        methods = {
            "kill": self._runtime.kill,
            "revoke": self._runtime.revoke,
            "rollback": self._runtime.rollback,
            "end_session": self._runtime.end_session,
            "reconnect": self._runtime.reconnect,
            "shutdown": self._runtime.shutdown,
        }
        method = methods.get(reason)
        if method is None:
            raise Phase5IntegrationV3ContractError("terminal reason is invalid")
        with self._lock:
            already_closed = self._closed
            self._closed = True
        status = method()
        if not already_closed:
            for item in self._runtime.pending_termination_actions():
                try:
                    self._close_host_action(item.action, reason)
                except BaseException as exc:
                    status = self._runtime.ack_termination_action(
                        item.token,
                        success=False,
                        error=type(exc).__name__,
                    )
                else:
                    status = self._runtime.ack_termination_action(
                        item.token, success=True
                    )
            status = self._runtime.await_termination(0)
        return {"surface": "status", "data": _plain(status)}

    def kill(self) -> dict[str, object]:
        return self.terminate("kill")

    def revoke(self) -> dict[str, object]:
        return self.terminate("revoke")

    def rollback(self) -> dict[str, object]:
        return self.terminate("rollback")

    def end_session(self) -> dict[str, object]:
        return self.terminate("end_session")

    def reconnect(self) -> dict[str, object]:
        return self.terminate("reconnect")

    def shutdown(self) -> dict[str, object]:
        return self.terminate("shutdown")


def create_phase5_integration_v3(
    *,
    session_id: str,
    trace_id: str,
    catalog: Sequence[CatalogSeedV3],
    environ: Mapping[str, str] | None = None,
) -> Phase5IntegrationV3 | None:
    flags = IntegrationFlagsV3.from_environ(environ)
    if not flags.integration and not flags.runtime:
        return None
    if not flags.integration or not flags.runtime:
        raise Phase5IntegrationV3ContractError(
            "integration and runtime flags must be enabled together"
        )
    identity = IntegrationIdentityV3.from_environ(environ)
    binding = runtime_v10.RuntimeBindingV10(
        trace_id,
        session_id,
        identity.workspace_id,
        identity.account_id,
        identity.profile_id,
    )
    return Phase5IntegrationV3(
        binding=binding,
        principal_id=identity.principal_id,
        flags=flags,
        catalog=catalog,
    )


__all__ = [
    "PHASE5_INTEGRATION_FLAG",
    "PHASE5_RUNTIME_FLAG",
    "PHASE5_GRANT_SHADOW_FLAG",
    "PHASE5_APPROVAL_INBOX_FLAG",
    "PHASE5_LOW_RISK_FLAG",
    "PHASE5_NEXUS_PROJECTION_FLAG",
    "PHASE5_LOCAL_CATALOG_READ_FLAG",
    "PHASE5_DASHBOARD_PROJECTION_FLAG",
    "LOCAL_CATALOG_TOOL",
    "CatalogSeedV3",
    "IntegrationFlagsV3",
    "IntegrationIdentityV3",
    "Phase5IntegrationV3",
    "Phase5IntegrationV3ContractError",
    "Phase5IntegrationV3Error",
    "create_phase5_integration_v3",
    "phase5_dashboard_requested",
    "phase5_requested",
]
