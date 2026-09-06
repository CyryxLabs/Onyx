"""Provider-free production composition root for governed capabilities."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from threading import RLock

from core.capability_ports.argos_v1 import OPERATIONS as ARGOS_OPERATIONS
from core.capability_ports.budget_v1 import OPERATIONS as BUDGET_OPERATIONS
from core.capability_ports.command_center_v1 import OPERATIONS as COMMAND_CENTER_OPERATIONS
from core.capability_ports.google_workspace_v1 import GOOGLE_WORKSPACE_OPERATIONS
from core.capability_ports.guild_v1 import OPERATIONS as GUILD_OPERATIONS
from core.capability_ports.graph_v1 import GRAPH_OPERATIONS
from core.capability_ports.intelligence_v1 import OPERATIONS as INTELLIGENCE_OPERATIONS
from core.capability_ports.knowledge_refinery_v1 import (
    OPERATIONS as KNOWLEDGE_REFINERY_OPERATIONS,
)
from core.capability_ports.evidence_v1 import OPERATIONS as EVIDENCE_OPERATIONS
from core.capability_ports.mission_context_v1 import OPERATIONS as MISSION_CONTEXT_OPERATIONS
from core.capability_ports.model_router_v1 import OPERATIONS as MODEL_ROUTER_OPERATIONS
from core.capability_ports.nexus_v1 import OPERATIONS as NEXUS_OPERATIONS
from core.capability_ports.plugin_v1 import OPERATIONS as PLUGIN_OPERATIONS
from core.capability_ports.project_execution_v1 import (
    OPERATIONS as PROJECT_EXECUTION_OPERATIONS,
)
from core.capability_ports.social_v1 import OPERATIONS as SOCIAL_OPERATIONS
from core.capability_ports.strategy_v1 import OPERATIONS as STRATEGY_OPERATIONS
from core.capability_ports.unified_router_v1 import GovernedRoutePlanV1, UnifiedRouterV1
from core.capability_ports.workspace_v1 import OPERATIONS as WORKSPACE_OPERATIONS
from core.governance_nucleus_v1 import (
    GovernanceNucleusV1,
    GovernanceV1ContractError,
    GovernanceV1Denied,
    SessionCapabilityV1,
)
from core.governed_capability_host_v1 import (
    CapabilityPort,
    CapabilityReceipt,
    GovernedCapabilityHostV1,
    HostBoundCapabilityPortV1,
    KillReceipt,
)

SCHEMA_VERSION = "OnyxCapabilityComposition.v1"
CAPABILITY_OPERATIONS = {
    "argos": ARGOS_OPERATIONS,
    "budget": BUDGET_OPERATIONS,
    "command_center": COMMAND_CENTER_OPERATIONS,
    "evidence": EVIDENCE_OPERATIONS,
    "google_workspace": GOOGLE_WORKSPACE_OPERATIONS,
    "guild": GUILD_OPERATIONS,
    "graph": GRAPH_OPERATIONS,
    "intelligence": INTELLIGENCE_OPERATIONS,
    "knowledge_refinery": KNOWLEDGE_REFINERY_OPERATIONS,
    "mission_context": MISSION_CONTEXT_OPERATIONS,
    "model_router": MODEL_ROUTER_OPERATIONS,
    "nexus": NEXUS_OPERATIONS,
    "plugin": PLUGIN_OPERATIONS,
    "project_execution": PROJECT_EXECUTION_OPERATIONS,
    "social": SOCIAL_OPERATIONS,
    "strategy": STRATEGY_OPERATIONS,
    "workspace": WORKSPACE_OPERATIONS,
}


def _canonical_operation(operation: str) -> str:
    return operation.replace(".", "-").replace("_", "-")


def _canonical_capability(capability: str) -> str:
    return capability.replace("_", "-")


class _UnavailableCapabilityPortV1(HostBoundCapabilityPortV1):
    """Closed placeholder that proves startup cannot reach a concrete provider."""

    def __init__(self, capability: str) -> None:
        super().__init__()
        self._capability = capability
        self._killed = False
        self._lock = RLock()

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object]) -> object:
        del operation, arguments
        with self._lock:
            if self._killed:
                raise GovernanceV1Denied("capability kill is latched")
        raise GovernanceV1Denied("concrete capability factory is not enabled")

    def revoke(self, binding_id: str) -> object:
        del binding_id
        return None

    def kill(self) -> object:
        with self._lock:
            self._killed = True
        return True


class _CanonicalOperationPortV1(HostBoundCapabilityPortV1):
    """Translate host-safe identifiers only after governance authorization."""

    def __init__(self, port: CapabilityPort, aliases: Mapping[str, str]) -> None:
        super().__init__()
        self._port = port
        self._aliases = dict(aliases)

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object]) -> object:
        native = self._aliases.get(operation)
        if native is None:
            raise GovernanceV1Denied("unknown canonical capability operation")
        dispatch = getattr(self._port, "_dispatch_authorized", None)
        if not callable(dispatch):
            raise GovernanceV1Denied("concrete capability port is not host-bound")
        return dispatch(native, arguments)

    def revoke(self, binding_id: str) -> object:
        return self._port.revoke(binding_id)

    def kill(self) -> object:
        return self._port.kill()


@dataclass(frozen=True, slots=True)
class CapabilityCompositionStatusV1:
    schema: str
    killed: bool
    capabilities: tuple[dict[str, object], ...]
    provider_dispatch: bool = False
    redacted: bool = True


class CapabilityCompositionV1:
    """Own the closed host, plan-only router, and single revoke/kill surface."""

    def __init__(
        self,
        *,
        nucleus: GovernanceNucleusV1,
        port_factories: Mapping[str, Callable[[], CapabilityPort]] | None = None,
    ) -> None:
        if type(nucleus) is not GovernanceNucleusV1:
            raise GovernanceV1ContractError("exact GovernanceNucleusV1 is required")
        factories = dict(port_factories or {})
        if set(factories) - set(CAPABILITY_OPERATIONS):
            raise GovernanceV1ContractError("unknown capability factory")
        if any(not callable(factory) for factory in factories.values()):
            raise GovernanceV1ContractError("capability factories must be callable")

        registry: dict[str, tuple[CapabilityPort, frozenset[str]]] = {}
        injected: set[str] = set()
        for capability, operations in sorted(CAPABILITY_OPERATIONS.items()):
            factory = factories.get(capability)
            port: CapabilityPort
            if factory is None:
                port = _UnavailableCapabilityPortV1(capability)
            else:
                port = factory()
                injected.add(capability)
            registry[capability] = (port, frozenset(operations))

        self._injected = frozenset(injected)
        canonical_registry = {
            _canonical_capability(capability): (
                _CanonicalOperationPortV1(
                    port,
                    {_canonical_operation(operation): operation for operation in operations},
                ),
                frozenset(_canonical_operation(operation) for operation in operations),
            )
            for capability, (port, operations) in registry.items()
        }
        self.host = GovernedCapabilityHostV1(
            nucleus=nucleus, registry=canonical_registry
        )
        self.router = UnifiedRouterV1(self.host)

    def status(self) -> CapabilityCompositionStatusV1:
        capabilities = tuple(
            {
                "capability": capability,
                "readiness": "injected" if capability in self._injected else "default-off",
                "operations": tuple(sorted(operations)),
            }
            for capability, operations in sorted(CAPABILITY_OPERATIONS.items())
        )
        return CapabilityCompositionStatusV1(
            SCHEMA_VERSION, self.host.killed, capabilities
        )

    def list_capabilities(self) -> dict[str, object]:
        return asdict(self.status())

    def dispatch(
        self,
        session: SessionCapabilityV1,
        capability: str,
        operation: str,
        arguments: Mapping[str, object],
    ) -> CapabilityReceipt:
        plan = self.plan(session, capability, operation, arguments)
        if not self.router.attest(plan):
            raise GovernanceV1Denied("capability route attestation failed")
        return self.host.dispatch(plan.binding, arguments)

    def plan(
        self,
        session: SessionCapabilityV1,
        capability: str,
        operation: str,
        arguments: Mapping[str, object],
    ) -> GovernedRoutePlanV1:
        if operation not in CAPABILITY_OPERATIONS.get(capability, frozenset()):
            raise GovernanceV1Denied("unknown capability or operation")
        return self.router.plan(
            session,
            _canonical_capability(capability),
            _canonical_operation(operation),
            arguments,
        )

    def terminate(self, operation: str, *, binding_id: str | None = None) -> KillReceipt | None:
        if operation == "kill" and binding_id is None:
            return self.host.kill()
        if operation == "revoke" and type(binding_id) is str and binding_id:
            self.host.revoke(binding_id)
            return None
        raise GovernanceV1ContractError("terminate requires kill or one binding revoke")

    def kill(self) -> KillReceipt:
        receipt = self.terminate("kill")
        assert type(receipt) is KillReceipt
        return receipt

    def shutdown(self) -> KillReceipt:
        """Stop process-local capability ports without latching owner kill."""

        return self.host.shutdown()


def create_capability_composition_v1(
    *,
    nucleus: GovernanceNucleusV1,
    port_factories: Mapping[str, Callable[[], CapabilityPort]] | None = None,
) -> CapabilityCompositionV1:
    return CapabilityCompositionV1(
        nucleus=nucleus,
        port_factories=port_factories,
    )


__all__ = [
    "CAPABILITY_OPERATIONS",
    "SCHEMA_VERSION",
    "CapabilityCompositionStatusV1",
    "CapabilityCompositionV1",
    "create_capability_composition_v1",
]
