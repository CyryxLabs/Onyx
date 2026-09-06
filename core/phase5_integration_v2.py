"""Versioned Phase 5 host bridge with immutable catalog dispatch binding.

V2 deliberately leaves the rejected V1 candidate byte-for-byte intact.  It
reuses only its already accepted component assembly and replaces the complete
authorization-to-dispatch boundary with a closed, canonical contract.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from core import capability_nexus_v32 as nexus_v32
from core import phase5_integration_v1 as legacy_v1
from core import phase5_runtime_v10 as runtime_v10
from core.tool_audit import append_tool_audit


PHASE5_INTEGRATION_FLAG = "ONYX_PHASE5_INTEGRATION_V2"
PHASE5_RUNTIME_FLAG = "ONYX_PHASE5_RUNTIME_V2"
PHASE5_GRANT_SHADOW_FLAG = "ONYX_PHASE5_GRANT_SHADOW_V2"
PHASE5_APPROVAL_INBOX_FLAG = "ONYX_PHASE5_APPROVAL_INBOX_V2"
PHASE5_LOW_RISK_FLAG = "ONYX_PHASE5_LOW_RISK_V2"
PHASE5_NEXUS_PROJECTION_FLAG = "ONYX_PHASE5_NEXUS_PROJECTION_V2"
PHASE5_LOCAL_CATALOG_READ_FLAG = "ONYX_PHASE5_LOCAL_CATALOG_READ_V2"
PHASE5_DASHBOARD_PROJECTION_FLAG = "ONYX_PHASE5_DASHBOARD_PROJECTION_V2"

PHASE5_PRINCIPAL_ID = legacy_v1.PHASE5_PRINCIPAL_ID
PHASE5_WORKSPACE_ID = legacy_v1.PHASE5_WORKSPACE_ID
PHASE5_ACCOUNT_ID = legacy_v1.PHASE5_ACCOUNT_ID
PHASE5_PROFILE_ID = legacy_v1.PHASE5_PROFILE_ID

LOCAL_CATALOG_TOOL = legacy_v1.LOCAL_CATALOG_TOOL
LOCAL_CATALOG_DECLARATION = legacy_v1.LOCAL_CATALOG_DECLARATION

_TRUE = frozenset({"1", "true"})
_MAX_PREPARED = 64
_MAX_SEEN_REFERENCES = 256
_PERMISSION_KEYS = frozenset({"page_size", "cursor", "_phase5_invocation_ref"})
_DISPATCH_KEYS = frozenset({"page_size", "cursor"})


class Phase5IntegrationV2Error(RuntimeError):
    """The V2 host bridge could not safely complete an operation."""


class Phase5IntegrationV2ContractError(ValueError):
    """A host input violated the closed V2 integration contract."""


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
class IntegrationFlagsV2:
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
                raise Phase5IntegrationV2ContractError(f"{name} must be exact bool")
        children = (
            self.grant_shadow,
            self.approval_inbox,
            self.low_risk,
            self.nexus_projection,
            self.local_catalog_read,
            self.dashboard_projection,
        )
        if (self.runtime or any(children)) and not self.integration:
            raise Phase5IntegrationV2ContractError(
                "Phase 5 features require the integration master flag"
            )
        if any(children) and not self.runtime:
            raise Phase5IntegrationV2ContractError(
                "Phase 5 child features require the runtime flag"
            )
        if self.local_catalog_read and not self.low_risk:
            raise Phase5IntegrationV2ContractError(
                "local catalog read requires exact low-risk enablement"
            )

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "IntegrationFlagsV2":
        source = os.environ if environ is None else environ
        return cls(
            integration=_enabled(source.get(PHASE5_INTEGRATION_FLAG, "")),
            runtime=_enabled(source.get(PHASE5_RUNTIME_FLAG, "")),
            grant_shadow=_enabled(source.get(PHASE5_GRANT_SHADOW_FLAG, "")),
            approval_inbox=_enabled(source.get(PHASE5_APPROVAL_INBOX_FLAG, "")),
            low_risk=_enabled(source.get(PHASE5_LOW_RISK_FLAG, "")),
            nexus_projection=_enabled(source.get(PHASE5_NEXUS_PROJECTION_FLAG, "")),
            local_catalog_read=_enabled(
                source.get(PHASE5_LOCAL_CATALOG_READ_FLAG, "")
            ),
            dashboard_projection=_enabled(
                source.get(PHASE5_DASHBOARD_PROJECTION_FLAG, "")
            ),
        )

    def legacy_flags(self) -> legacy_v1.IntegrationFlagsV1:
        return legacy_v1.IntegrationFlagsV1(
            integration=self.integration,
            runtime=self.runtime,
            grant_shadow=self.grant_shadow,
            approval_inbox=self.approval_inbox,
            low_risk=self.low_risk,
            nexus_projection=self.nexus_projection,
            local_catalog_read=self.local_catalog_read,
            dashboard_projection=self.dashboard_projection,
        )


@dataclass(frozen=True, slots=True)
class IntegrationIdentityV2:
    principal_id: str
    workspace_id: str
    account_id: str
    profile_id: str

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "IntegrationIdentityV2":
        try:
            identity = legacy_v1.IntegrationIdentityV1.from_environ(environ)
        except legacy_v1.Phase5IntegrationV1ContractError as exc:
            raise Phase5IntegrationV2ContractError(str(exc)) from exc
        return cls(
            identity.principal_id,
            identity.workspace_id,
            identity.account_id,
            identity.profile_id,
        )


@dataclass(frozen=True, slots=True)
class CatalogSeedV2:
    item_id: str
    label: str
    category: str = "tool"
    item_version: str = "current"
    tags: tuple[str, ...] = ()

    def legacy_seed(self) -> legacy_v1.CatalogSeedV1:
        return legacy_v1.CatalogSeedV1(
            self.item_id, self.label, self.category, self.item_version, self.tags
        )


@dataclass(frozen=True, slots=True)
class NormalizedCatalogDispatchV2:
    """Every material read argument in immutable canonical form."""

    page_size: int
    cursor: str | None

    @classmethod
    def from_arguments(
        cls, arguments: Mapping[str, object], *, permission_stage: bool
    ) -> "NormalizedCatalogDispatchV2":
        if not isinstance(arguments, Mapping):
            raise Phase5IntegrationV2ContractError("catalog arguments must be a mapping")
        allowed = _PERMISSION_KEYS if permission_stage else _DISPATCH_KEYS
        unknown = set(arguments) - allowed
        if unknown:
            raise Phase5IntegrationV2ContractError(
                "catalog arguments contain fields outside the closed contract"
            )
        page_size = arguments.get("page_size", 25)
        cursor = arguments.get("cursor")
        if type(page_size) is not int or not 1 <= page_size <= 50:
            raise Phase5IntegrationV2ContractError(
                "catalog page_size must be an exact integer from 1 through 50"
            )
        if cursor is not None and (type(cursor) is not str or len(cursor) > 2048):
            raise Phase5IntegrationV2ContractError("catalog cursor is invalid")
        return cls(page_size=page_size, cursor=cursor)

    def payload(self) -> dict[str, object]:
        return {"cursor": self.cursor, "page_size": self.page_size}

    def digest(self) -> str:
        encoded = json.dumps(
            self.payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class _PreparedCatalogReadV2:
    action: runtime_v10.ActionRequestV10
    decision: runtime_v10.RuntimeDecisionV10
    dispatch: NormalizedCatalogDispatchV2
    dispatch_digest: str


class Phase5IntegrationV2(legacy_v1.Phase5IntegrationV1):
    """V2 bridge whose authorization is inseparable from exact dispatch args."""

    def __init__(
        self,
        *,
        binding: runtime_v10.RuntimeBindingV10,
        principal_id: str,
        flags: IntegrationFlagsV2,
        catalog: Sequence[CatalogSeedV2],
    ) -> None:
        if type(flags) is not IntegrationFlagsV2:
            raise Phase5IntegrationV2ContractError("exact IntegrationFlagsV2 required")
        if type(catalog) not in {tuple, list} or any(
            type(seed) is not CatalogSeedV2 for seed in catalog
        ):
            raise Phase5IntegrationV2ContractError("catalog entries must be exact")
        try:
            super().__init__(
                binding=binding,
                principal_id=principal_id,
                flags=flags.legacy_flags(),
                catalog=tuple(seed.legacy_seed() for seed in catalog),
            )
        except legacy_v1.Phase5IntegrationV1ContractError as exc:
            raise Phase5IntegrationV2ContractError(str(exc)) from exc
        self._v2_flags = flags
        self._prepared: OrderedDict[str, _PreparedCatalogReadV2] = OrderedDict()
        self._seen_references: OrderedDict[str, None] = OrderedDict()

    def _purge_reference(self, reference: str) -> None:
        self._prepared.pop(reference, None)
        self._runtime_actions.pop(reference, None)
        self._grant_actions.pop(reference, None)

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
                    "invocation_digest": hashlib.sha256(reference.encode()).hexdigest(),
                    "expected_digest": expected_digest,
                    "observed_digest": observed_digest,
                },
                outcome="rejected",
                trace_id=self._binding.trace_id,
                error_type="Phase5DispatchBindingMismatch",
            )
        except BaseException:
            # Audit availability must never turn a denial into authorization.
            return

    def permission_hook(
        self, tool_name: str, arguments: Mapping[str, object]
    ) -> tuple[bool, str] | None:
        if tool_name != LOCAL_CATALOG_TOOL:
            return None
        reference = arguments.get("_phase5_invocation_ref")
        if type(reference) is not str:
            return False, "Permission denied: missing host invocation binding."
        try:
            normalized = NormalizedCatalogDispatchV2.from_arguments(
                arguments, permission_stage=True
            )
        except Phase5IntegrationV2ContractError as exc:
            return False, f"Permission denied: {exc}."
        collision = False
        collision_expected_digest = ""
        with self._lock:
            if self._closed or not self.local_catalog_enabled:
                return False, "Permission denied: local catalog is disabled."
            if reference in self._seen_references:
                collision = True
                existing = self._prepared.get(reference)
                collision_expected_digest = (
                    existing.dispatch_digest
                    if existing is not None
                    else hashlib.sha256(b"consumed-reference").hexdigest()
                )
            else:
                self._seen_references[reference] = None
                while len(self._seen_references) > _MAX_SEEN_REFERENCES:
                    self._seen_references.popitem(last=False)
                action, grant_action = self._make_actions(
                    reference, normalized.payload()
                )
                self._remember_action(reference, action, grant_action)
                decision = self._runtime.evaluate(action)
                if (
                    decision.disposition
                    is not runtime_v10.RuntimeDispositionV10.ALLOW_LOCAL_CATALOG_READ
                ):
                    self._purge_reference(reference)
                    return False, f"Permission denied: {decision.reason}."
                self._prepared[reference] = _PreparedCatalogReadV2(
                    action=action,
                    decision=decision,
                    dispatch=normalized,
                    dispatch_digest=normalized.digest(),
                )
                while len(self._prepared) > _MAX_PREPARED:
                    old, evicted = self._prepared.popitem(last=False)
                    self._runtime.consume_decision(evicted.decision, evicted.action)
                    self._runtime_actions.pop(old, None)
                    self._grant_actions.pop(old, None)
        if collision:
            self._audit_guard(
                reference=reference,
                reason="phase5-v2-invocation-reference-replay",
                expected_digest=collision_expected_digest,
                observed_digest=normalized.digest(),
            )
            return False, "Permission denied: invocation reference was already used."
        return True, f"phase5-local-catalog-v2:{reference}"

    def catalog_read(
        self, invocation_ref: str, arguments: Mapping[str, object]
    ) -> dict[str, object]:
        observed: NormalizedCatalogDispatchV2 | None = None
        observed_digest = "invalid"
        normalization_error = ""
        try:
            observed = NormalizedCatalogDispatchV2.from_arguments(
                arguments, permission_stage=False
            )
            observed_digest = observed.digest()
        except Phase5IntegrationV2ContractError as exc:
            normalization_error = str(exc)

        failure_reason = ""
        expected_digest = ""
        projection = None
        with self._lock:
            prepared = self._prepared.pop(invocation_ref, None)
            if self._closed or prepared is None:
                self._purge_reference(invocation_ref)
                raise Phase5IntegrationV2Error("catalog authorization is unavailable")
            expected_digest = prepared.dispatch_digest
            exact = (
                observed is not None
                and observed == prepared.dispatch
                and hmac.compare_digest(observed_digest, prepared.dispatch_digest)
            )
            if not exact:
                self._runtime.consume_decision(prepared.decision, prepared.action)
                self._purge_reference(invocation_ref)
                failure_reason = (
                    "phase5-v2-invalid-dispatch"
                    if normalization_error
                    else "phase5-v2-dispatch-binding-mismatch"
                )
            else:
                consumed = self._runtime.consume_decision(
                    prepared.decision, prepared.action
                )
                self._runtime_actions.pop(invocation_ref, None)
                self._grant_actions.pop(invocation_ref, None)
                if not consumed:
                    failure_reason = "phase5-v2-stale-decision"
                else:
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
                    # Keep the session lock through the provider-free adapter
                    # boundary so the same invocation cannot be re-authorized
                    # between exact comparison, consume, and dispatch.
                    projection = self._catalog.read_page(request)

        if failure_reason:
            self._audit_guard(
                reference=invocation_ref,
                reason=failure_reason,
                expected_digest=expected_digest,
                observed_digest=observed_digest,
            )
            if failure_reason == "phase5-v2-stale-decision":
                raise Phase5IntegrationV2Error("catalog authorization is stale")
            raise Phase5IntegrationV2Error(
                "catalog dispatch does not match its immutable authorization"
            )

        assert projection is not None
        if projection.state is not nexus_v32.ReadStateV32.COMPLETED:
            raise Phase5IntegrationV2Error(
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


def create_phase5_integration_v2(
    *,
    session_id: str,
    trace_id: str,
    catalog: Sequence[CatalogSeedV2],
    environ: Mapping[str, str] | None = None,
) -> Phase5IntegrationV2 | None:
    flags = IntegrationFlagsV2.from_environ(environ)
    if not flags.integration and not flags.runtime:
        return None
    if not flags.integration or not flags.runtime:
        raise Phase5IntegrationV2ContractError(
            "integration and runtime flags must be enabled together"
        )
    identity = IntegrationIdentityV2.from_environ(environ)
    binding = runtime_v10.RuntimeBindingV10(
        trace_id,
        session_id,
        identity.workspace_id,
        identity.account_id,
        identity.profile_id,
    )
    return Phase5IntegrationV2(
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
    "CatalogSeedV2",
    "IntegrationFlagsV2",
    "IntegrationIdentityV2",
    "NormalizedCatalogDispatchV2",
    "Phase5IntegrationV2",
    "Phase5IntegrationV2ContractError",
    "Phase5IntegrationV2Error",
    "create_phase5_integration_v2",
    "phase5_dashboard_requested",
    "phase5_requested",
]
