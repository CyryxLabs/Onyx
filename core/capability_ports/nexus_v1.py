"""Descriptor projection adapter; deliberately has no dispatch plane."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from core.governance_nucleus_v1 import GovernanceV1ContractError, GovernanceV1Denied
from core.governed_capability_host_v1 import HostBoundCapabilityPortV1

OPERATIONS = frozenset({"read.list", "read.descriptor"})


class NexusProjectionPortV1(HostBoundCapabilityPortV1):
    def __init__(self, *, workspace_id: str, descriptors: Sequence[Mapping[str, object]]) -> None:
        super().__init__()
        self._workspace_id = workspace_id
        projected: dict[str, dict[str, object]] = {}
        for raw in descriptors:
            descriptor = dict(raw)
            capability_id = descriptor.get("capability_id")
            if not isinstance(capability_id, str) or not capability_id:
                raise GovernanceV1ContractError("nexus capability descriptor is invalid")
            if capability_id in projected:
                raise GovernanceV1ContractError("duplicate capability")
            if descriptor.get("workspace_id") != workspace_id:
                raise GovernanceV1Denied("cross-workspace nexus descriptor denied")
            if descriptor.get("dispatch") is not None or descriptor.get("authority_granted") is True:
                raise GovernanceV1Denied("nexus descriptor cannot convey dispatch authority")
            projected[capability_id] = descriptor
        self._descriptors = projected
        self._killed = False

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object]) -> object:
        if self._killed:
            raise GovernanceV1Denied("nexus adapter kill is latched")
        if operation == "read.list":
            return {"capabilities": tuple(sorted(self._descriptors)), "authority_granted": False}
        if operation == "read.descriptor":
            capability_id = arguments.get("capability_id")
            if capability_id not in self._descriptors:
                raise GovernanceV1Denied("unknown capability")
            return {"capability_id": capability_id, "authority_granted": False}
        raise GovernanceV1Denied("direct nexus dispatch denied")

    def revoke(self, binding_id: str) -> None:
        del binding_id

    def kill(self) -> bool:
        self._killed = True
        return True

