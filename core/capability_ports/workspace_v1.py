"""Read-only shadow adapter for the historical workspace registry."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence

from core.governance_nucleus_v1 import GovernanceV1ContractError, GovernanceV1Denied
from core.governed_capability_host_v1 import HostBoundCapabilityPortV1

OPERATIONS = frozenset({"read.list", "read.get"})


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class WorkspaceShadowPortV1(HostBoundCapabilityPortV1):
    """Compare two read-only projections without accepting path/link authority."""

    def __init__(
        self,
        *,
        workspace_id: str,
        primary_reader: Callable[[], Sequence[Mapping[str, object]]],
        shadow_reader: Callable[[], Sequence[Mapping[str, object]]],
    ) -> None:
        super().__init__()
        if not workspace_id or not callable(primary_reader) or not callable(shadow_reader):
            raise GovernanceV1ContractError("workspace shadow adapter configuration is invalid")
        self._workspace_id = workspace_id
        self._primary_reader = primary_reader
        self._shadow_reader = shadow_reader
        self._killed = False

    def _rows(self) -> tuple[dict[str, object], ...]:
        if self._killed:
            raise GovernanceV1Denied("workspace adapter kill is latched")
        primary = tuple(dict(row) for row in self._primary_reader())
        shadow = tuple(dict(row) for row in self._shadow_reader())
        for row in primary + shadow:
            if row.get("workspace_id") != self._workspace_id:
                raise GovernanceV1Denied("cross-workspace registry projection denied")
            if row.get("is_link") is True or row.get("linked_workspace_id") is not None:
                raise GovernanceV1Denied("linked workspace projection denied")
        if _digest(primary) != _digest(shadow):
            raise GovernanceV1Denied("workspace shadow parity mismatch")
        return primary

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object]) -> object:
        rows = self._rows()
        if operation == "read.list":
            return {"count": len(rows), "parity": "matched"}
        if operation == "read.get":
            requested = arguments.get("workspace_id")
            if requested != self._workspace_id:
                raise GovernanceV1Denied("cross-workspace registry read denied")
            return {"found": any(row.get("workspace_id") == requested for row in rows), "parity": "matched"}
        raise GovernanceV1Denied("unknown workspace operation")

    def revoke(self, binding_id: str) -> None:
        del binding_id

    def kill(self) -> bool:
        self._killed = True
        return True

