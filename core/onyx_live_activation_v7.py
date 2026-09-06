"""Onyx Live Activation V7: exact Phase 5 identity binding.

V7 is an additive launch-contract correction over the preserved V6 candidate.
It adds no runtime seam: V6 remains the authority for provider MIME handling,
reconnect containment, tool replay, circuit recovery, and Qt projection.
"""

from __future__ import annotations

import asyncio
import copy
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from types import ModuleType

from core import onyx_live_activation_v6 as v6
from core import phase5_integration_v3 as phase5


LIVE_MASTER_FLAG = "ONYX_LIVE_ACTIVATION_V7"
LIVE_ROLLBACK_FLAG = "ONYX_LIVE_ROLLBACK_V7"
OWNER_PROFILE_FLAG = v6.OWNER_PROFILE_FLAG
HUD_FLAG = v6.HUD_FLAG
PHASE5_FLAGS = v6.PHASE5_FLAGS
CHILD_FLAGS = (OWNER_PROFILE_FLAG, HUD_FLAG, *PHASE5_FLAGS)

PHASE5_PRINCIPAL_ID = phase5.PHASE5_PRINCIPAL_ID
PHASE5_WORKSPACE_ID = phase5.PHASE5_WORKSPACE_ID
PHASE5_ACCOUNT_ID = phase5.PHASE5_ACCOUNT_ID
PHASE5_PROFILE_ID = phase5.PHASE5_PROFILE_ID
PHASE5_IDENTITY_FLAGS = (
    PHASE5_PRINCIPAL_ID,
    PHASE5_WORKSPACE_ID,
    PHASE5_ACCOUNT_ID,
    PHASE5_PROFILE_ID,
)
CANONICAL_PHASE5_IDENTITY = {
    PHASE5_PRINCIPAL_ID: "onyx-owner",
    PHASE5_WORKSPACE_ID: "onyx-local-workspace",
    PHASE5_ACCOUNT_ID: "cyryx-local-account",
    PHASE5_PROFILE_ID: "onyx-owner-profile",
}

# Explicitly reject historical/generic spellings instead of silently treating
# them as an identity source.
PHASE5_IDENTITY_ALIASES = (
    "ONYX_PRINCIPAL_ID",
    "ONYX_WORKSPACE_ID",
    "ONYX_ACCOUNT_ID",
    "ONYX_PROFILE_ID",
    "PHASE5_PRINCIPAL_ID",
    "PHASE5_WORKSPACE_ID",
    "PHASE5_ACCOUNT_ID",
    "PHASE5_PROFILE_ID",
)
CONTROL_FLAGS = (
    LIVE_MASTER_FLAG,
    LIVE_ROLLBACK_FLAG,
    *CHILD_FLAGS,
    *PHASE5_IDENTITY_FLAGS,
    *PHASE5_IDENTITY_ALIASES,
)


class ActivationV7Error(RuntimeError):
    """The V7 launch identity or host contract was not exact."""


@dataclass(frozen=True, slots=True)
class ActivationFlagsV7:
    master: bool
    owner_profile: bool
    hud_v5: bool
    phase5: tuple[bool, ...]
    principal_id: str
    workspace_id: str
    account_id: str
    profile_id: str

    def __post_init__(self) -> None:
        if type(self.phase5) is not tuple or len(self.phase5) != len(PHASE5_FLAGS):
            raise ActivationV7Error("Phase 5 flag set is incomplete")
        booleans = (self.master, self.owner_profile, self.hud_v5, *self.phase5)
        if any(type(value) is not bool for value in booleans) or not all(booleans):
            raise ActivationV7Error("complete active V7 flags are required")
        observed = {
            PHASE5_PRINCIPAL_ID: self.principal_id,
            PHASE5_WORKSPACE_ID: self.workspace_id,
            PHASE5_ACCOUNT_ID: self.account_id,
            PHASE5_PROFILE_ID: self.profile_id,
        }
        if observed != CANONICAL_PHASE5_IDENTITY:
            raise ActivationV7Error("exact canonical Phase 5 identity is required")

    @classmethod
    def from_canonical_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ActivationFlagsV7":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV7Error("rollback is not an active configuration")
        if any(name in source for name in PHASE5_IDENTITY_ALIASES):
            raise ActivationV7Error("Phase 5 identity aliases are forbidden")
        for name in (LIVE_MASTER_FLAG, *CHILD_FLAGS):
            if source.get(name) != "1":
                raise ActivationV7Error("activation environment is not canonical")
        for name, expected in CANONICAL_PHASE5_IDENTITY.items():
            if source.get(name) != expected:
                raise ActivationV7Error("Phase 5 identity environment is not canonical")
        return cls(
            True,
            True,
            True,
            (True,) * len(PHASE5_FLAGS),
            CANONICAL_PHASE5_IDENTITY[PHASE5_PRINCIPAL_ID],
            CANONICAL_PHASE5_IDENTITY[PHASE5_WORKSPACE_ID],
            CANONICAL_PHASE5_IDENTITY[PHASE5_ACCOUNT_ID],
            CANONICAL_PHASE5_IDENTITY[PHASE5_PROFILE_ID],
        )


def exact_activation_environment() -> dict[str, str]:
    result = v6.exact_activation_environment()
    result.pop(v6.LIVE_MASTER_FLAG, None)
    result[LIVE_MASTER_FLAG] = "1"
    result.update(CANONICAL_PHASE5_IDENTITY)
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


@dataclass(frozen=True, slots=True)
class Phase5BridgeProbeV7:
    bridge_type: str
    catalog_entries: int
    local_catalog_declarations: int
    principal_id: str
    workspace_id: str
    account_id: str
    profile_id: str


@dataclass(frozen=True, slots=True)
class Phase5AuthorizationDiagnosticV7:
    state: str
    reason_code: str
    local_catalog_enabled: bool


@dataclass(frozen=True, slots=True)
class HostContractV7:
    module: ModuleType
    base: v6.HostContractV6
    phase5_probe: Phase5BridgeProbeV7


def _main_catalog(module: ModuleType) -> tuple[phase5.CatalogSeedV3, ...]:
    declarations = getattr(module, "TOOL_DECLARATIONS", None)
    if type(declarations) is not list:
        raise ActivationV7Error("main tool catalog is unavailable")
    catalog = tuple(
        phase5.CatalogSeedV3(
            item_id=str(item["name"]),
            label=str(item["name"]).replace("_", " ").title(),
        )
        for item in declarations
        if isinstance(item, dict) and type(item.get("name")) is str
    )
    if not catalog or len(catalog) != len(declarations):
        raise ActivationV7Error("main tool catalog is not an exact named catalog")
    return catalog


def preflight_host(
    module: ModuleType, environ: Mapping[str, str] | None = None
) -> HostContractV7:
    """Validate V6 and materialize one real, provider-free Phase 5 bridge."""

    source = os.environ if environ is None else environ
    flags = ActivationFlagsV7.from_canonical_environ(source)
    base = v6.preflight_host(module)
    catalog = _main_catalog(module)
    bridge = phase5.create_phase5_integration_v3(
        session_id="session-v7-preflight",
        trace_id="trace-v7-preflight",
        catalog=catalog,
        environ=source,
    )
    if type(bridge) is not phase5.Phase5IntegrationV3:
        raise ActivationV7Error("Phase 5 V3 factory did not return the real bridge")
    try:
        declarations = bridge.tool_declarations()
        if (
            not bridge.local_catalog_enabled
            or len(declarations) != 1
            or declarations[0].get("name") != phase5.LOCAL_CATALOG_TOOL
        ):
            raise ActivationV7Error("Phase 5 local catalog bridge is not ready")
        binding = bridge.binding
        probe = Phase5BridgeProbeV7(
            bridge_type=f"{type(bridge).__module__}.{type(bridge).__qualname__}",
            catalog_entries=len(catalog),
            local_catalog_declarations=len(declarations),
            principal_id=flags.principal_id,
            workspace_id=binding.workspace_id,
            account_id=binding.account_id,
            profile_id=binding.profile_id,
        )
    finally:
        bridge.terminate("rollback")
    if (
        probe.workspace_id != flags.workspace_id
        or probe.account_id != flags.account_id
        or probe.profile_id != flags.profile_id
    ):
        raise ActivationV7Error("Phase 5 factory changed the canonical identity")
    return HostContractV7(module=module, base=base, phase5_probe=probe)


class OnyxLiveActivationV7:
    """Identity-bound façade over the accepted V6 runtime transition."""

    BASE_SEAM_COUNT = v6.OnyxLiveActivationV6.TOTAL_SEAM_COUNT
    V7_SEAM_COUNT = 1
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V7_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV7,
        contract: HostContractV7,
        **v6_options: object,
    ) -> None:
        if type(flags) is not ActivationFlagsV7 or type(contract) is not HostContractV7:
            raise ActivationV7Error("exact V7 flags and host contract are required")
        self.flags = flags
        self.contract = contract
        self._base = v6.OnyxLiveActivationV6(
            v6.ActivationFlagsV6(
                True, True, True, (True,) * len(v6.PHASE5_FLAGS)
            ),
            contract.base,
            **v6_options,
        )
        self._installation_original: object | None = None
        self._reference_counter = 0
        self._reference_lock = threading.Lock()

    @property
    def state(self) -> v6.ActivationV6State:
        return self._base.state

    @property
    def failure_type(self) -> str | None:
        return self._base.failure_type

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._base, name)

    def _next_catalog_reference(self) -> str:
        with self._reference_lock:
            self._reference_counter += 1
            return f"catalog-p{os.getpid()}-n{self._reference_counter}"

    @staticmethod
    def _phase5_diagnostic(
        bridge: object | None, denial: str
    ) -> Phase5AuthorizationDiagnosticV7:
        enabled = bool(getattr(bridge, "local_catalog_enabled", False))
        state = "ABSENT"
        if bridge is not None:
            try:
                payload = bridge.status_payload()
                observed = payload.get("data", {}).get("state", "UNKNOWN")
                if type(observed) is str and observed in {
                    "READY",
                    "DEGRADED",
                    "TERMINATING",
                    "TERMINATED",
                }:
                    state = observed
                else:
                    state = "UNKNOWN"
            except Exception:
                state = "UNAVAILABLE"
        folded = denial.casefold()
        reason_code = "phase5-denied"
        for marker, code in (
            ("missing host invocation binding", "missing-binding"),
            ("invocation collision", "invocation-collision"),
            ("concurrent invocation collision", "concurrent-collision"),
            ("local catalog is disabled", "bridge-disabled"),
            ("integration is disabled", "bridge-disabled"),
            ("grant_shadow_failure", "grant-shadow-failure"),
            ("invalid phase 5 authorization result", "invalid-hook-result"),
            ("audit failed before action", "audit-failure"),
            ("page_size", "invalid-request"),
            ("cursor", "invalid-request"),
        ):
            if marker in folded:
                reason_code = code
                break
        return Phase5AuthorizationDiagnosticV7(state, reason_code, enabled)

    async def _execute_local_catalog(
        self, instance: object, fc: object, provider_arguments: Mapping[str, object]
    ) -> object:
        module = self.contract.module
        name = phase5.LOCAL_CATALOG_TOOL
        arguments = copy.deepcopy(dict(provider_arguments))
        trace_id = self._next_catalog_reference()
        arguments["_phase5_invocation_ref"] = trace_id

        def finish(
            response: dict[str, object],
            outcome: str = "completed",
            error_type: str = "",
        ) -> object:
            try:
                module.append_tool_audit(
                    profile="runtime",
                    tool=name,
                    action="catalog_read",
                    decision="dispatch",
                    reason=error_type or outcome,
                    arguments=arguments,
                    outcome=outcome,
                    trace_id=trace_id,
                    error_type=error_type,
                )
            except Exception:
                module.mark_audit_unhealthy()
                instance.ui.write_log(
                    "ERR: Tool audit unhealthy; future autonomous actions disabled."
                )
            return module.types.FunctionResponse(
                id=fc.id, name=name, response=response
            )

        instance.ui.set_state("THINKING")
        token = module.set_audit_trace_id(trace_id)
        try:
            approved, denial = await asyncio.to_thread(
                module.authorize_model_tool, name, copy.deepcopy(arguments)
            )
        finally:
            module.reset_audit_trace_id(token)
        bridge = getattr(instance, "_phase5", None)
        if not approved:
            diagnostic = self._phase5_diagnostic(bridge, denial)
            instance._onyx_v7_phase5_last_diagnostic = diagnostic
            instance.ui.write_log(
                "ERR: Phase 5 local authorization denied "
                f"(state={diagnostic.state}, reason={diagnostic.reason_code}, "
                "catalog="
                f"{'enabled' if diagnostic.local_catalog_enabled else 'disabled'})."
            )
            if not instance.ui.muted:
                instance.ui.set_state("LISTENING")
            return finish(
                {"result": "Local catalog authorization was refused."},
                "denied",
                diagnostic.reason_code,
            )
        public_arguments = copy.deepcopy(arguments)
        public_arguments.pop("_phase5_invocation_ref", None)
        if type(bridge) is not phase5.Phase5IntegrationV3:
            diagnostic = self._phase5_diagnostic(bridge, "integration is disabled")
            instance._onyx_v7_phase5_last_diagnostic = diagnostic
            return finish(
                {"result": "Local catalog integration is unavailable."},
                "rejected",
                diagnostic.reason_code,
            )
        try:
            result = await asyncio.to_thread(
                bridge.catalog_read, trace_id, public_arguments
            )
        except Exception as exc:
            diagnostic = self._phase5_diagnostic(bridge, "dispatch failed")
            instance._onyx_v7_phase5_last_diagnostic = diagnostic
            return finish(
                {"result": "Local catalog read failed safely."},
                "failed",
                type(exc).__name__,
            )
        diagnostic = Phase5AuthorizationDiagnosticV7("READY", "allowed", True)
        instance._onyx_v7_phase5_last_diagnostic = diagnostic
        if not instance.ui.muted:
            instance.ui.set_state("LISTENING")
        return finish({"result": result}, "completed")

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and not (1 <= fail_after <= self.TOTAL_SEAM_COUNT):
            raise ActivationV7Error("seam failpoint is outside V7 installation")
        base_failpoint = fail_after if fail_after and fail_after <= self.BASE_SEAM_COUNT else None
        self._base.install(fail_after=base_failpoint)
        host_type = self.contract.base.onyx_live
        original = host_type._execute_tool
        controller = self

        async def execute_tool(instance: object, fc: object) -> object:
            if getattr(fc, "name", None) != phase5.LOCAL_CATALOG_TOOL:
                return await original(instance, fc)
            try:
                arguments = copy.deepcopy(dict(getattr(fc, "args", None) or {}))
                registry = controller._base._tool_registry(
                    instance, controller._base._registry_factory
                )
                return await registry.execute(
                    call_id=getattr(fc, "id", None),
                    name=getattr(fc, "name", None),
                    arguments=arguments,
                    runner=lambda: controller._execute_local_catalog(
                        instance, fc, arguments
                    ),
                )
            except v6.ActivationV6Error as exc:
                instance.ui.write_log(
                    "ERR: Provider tool call refused without execution "
                    f"({type(exc).__name__})."
                )
                return controller.contract.module.types.FunctionResponse(
                    id=str(getattr(fc, "id", "") or ""),
                    name=str(getattr(fc, "name", "") or ""),
                    response={
                        "result": "tool call refused",
                        "error": type(exc).__name__,
                    },
                )

        try:
            host_type._execute_tool = execute_tool
            if fail_after == self.TOTAL_SEAM_COUNT:
                raise ActivationV7Error("injected V7 seam installation failure")
        except Exception:
            host_type._execute_tool = original
            self._base.rollback_installation()
            raise
        self._installation_original = original

    def start(self) -> v6.ActivationV6State:
        return self._base.start()

    def rollback_installation(self) -> None:
        if self._installation_original is not None:
            self.contract.base.onyx_live._execute_tool = self._installation_original
            self._installation_original = None
        self._base.rollback_installation()


def activate_main(
    module: ModuleType, environ: Mapping[str, str] | None = None
) -> OnyxLiveActivationV7:
    source = os.environ if environ is None else environ
    flags = ActivationFlagsV7.from_canonical_environ(source)
    controller = OnyxLiveActivationV7(flags, preflight_host(module, source))
    controller.install()
    controller.start()
    module._onyx_live_activation_v7 = controller
    return controller


__all__ = [
    "ActivationFlagsV7",
    "ActivationV7Error",
    "CANONICAL_PHASE5_IDENTITY",
    "CHILD_FLAGS",
    "CONTROL_FLAGS",
    "HostContractV7",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OnyxLiveActivationV7",
    "PHASE5_IDENTITY_ALIASES",
    "PHASE5_IDENTITY_FLAGS",
    "Phase5BridgeProbeV7",
    "Phase5AuthorizationDiagnosticV7",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
]
