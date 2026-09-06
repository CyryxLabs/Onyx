"""Governed, read-only capability port for the local Argos V1 registry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from threading import RLock

from core.argos_v1 import ArgosRegistryV1
from core.governance_nucleus_v1 import GovernanceV1ContractError, GovernanceV1Denied
from core.governed_capability_host_v1 import HostBoundCapabilityPortV1

OPERATIONS = frozenset({"read.brief", "read.category", "read.status"})


class ArgosCapabilityPortV1(HostBoundCapabilityPortV1):
    """Expose only bounded local Argos reads; returned content is untrusted."""

    def __init__(self, registry: ArgosRegistryV1) -> None:
        super().__init__()
        if type(registry) is not ArgosRegistryV1:
            raise GovernanceV1ContractError("exact ArgosRegistryV1 is required")
        self._registry = registry
        self._lock = RLock()
        self._revoked: set[str] = set()
        self._closed = False
        self._killed = False

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object]) -> object:
        with self._lock:
            if self._killed:
                raise GovernanceV1Denied("Argos port kill is latched")
            if self._closed:
                raise GovernanceV1Denied("Argos port is closed")
        if operation == "read.status":
            if arguments:
                raise GovernanceV1ContractError("read.status accepts no arguments")
            return self._envelope(())
        if operation == "read.brief" and set(arguments) == {"limit"}:
            return self._envelope(self._registry.brief(arguments["limit"]))
        if operation == "read.category" and set(arguments) == {"category"}:
            return self._envelope(self._registry.signals_for(arguments["category"]))
        raise GovernanceV1Denied("Argos operation is not a governed local read")

    @staticmethod
    def _envelope(signals: object) -> dict[str, object]:
        values = tuple(signals)  # type: ignore[arg-type]
        return {
            "schema": "onyx.argos-capability-port.v1",
            "trust": "untrusted-content",
            "actionable": False,
            "source": "local-state-only",
            "signals": [asdict(signal) for signal in values],
        }

    def revoke(self, binding_id: str) -> dict[str, object]:
        with self._lock:
            self._revoked.add(binding_id)
        return {"status": "binding-revoked", "binding_id": binding_id}

    def close(self) -> dict[str, object]:
        with self._lock:
            self._closed = True
        return {"status": "closed", "killed": False}

    def kill(self) -> dict[str, object]:
        with self._lock:
            self._killed = True
        return {"status": "kill-latched"}


__all__ = ["ArgosCapabilityPortV1", "OPERATIONS"]
