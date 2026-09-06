"""Non-migrating read adapter for an owner-supplied mission context store."""

from __future__ import annotations

from collections.abc import Mapping

from core.governance_nucleus_v1 import GovernanceV1ContractError, GovernanceV1Denied
from core.governed_capability_host_v1 import HostBoundCapabilityPortV1

OPERATIONS = frozenset({"read.context", "read.events"})


class MissionContextReadPortV1(HostBoundCapabilityPortV1):
    def __init__(self, *, workspace_id: str, store: object) -> None:
        super().__init__()
        if not workspace_id or not callable(getattr(store, "get_context", None)) or not callable(getattr(store, "list_events", None)):
            raise GovernanceV1ContractError("mission context read store is invalid")
        self._workspace_id = workspace_id
        self._store = store
        self._killed = False

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object]) -> object:
        if self._killed:
            raise GovernanceV1Denied("mission context adapter kill is latched")
        if arguments.get("workspace_id") != self._workspace_id:
            raise GovernanceV1Denied("cross-workspace mission context read denied")
        mission_id = arguments.get("mission_id")
        if not isinstance(mission_id, str) or not mission_id:
            raise GovernanceV1ContractError("mission_id is required")
        if operation == "read.context":
            record = self._store.get_context(self._workspace_id, mission_id)
            return {"found": record is not None, "revision": getattr(record, "revision", None)}
        if operation == "read.events":
            events = self._store.list_events(self._workspace_id, mission_id)
            return {"count": len(events)}
        raise GovernanceV1Denied("unknown mission context operation")

    def revoke(self, binding_id: str) -> None:
        del binding_id

    def kill(self) -> bool:
        self._killed = True
        return True

