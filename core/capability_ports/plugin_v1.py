"""Governed adapter around the accepted PluginHost V1 lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from threading import Event, RLock

from core.governance_nucleus_v1 import GovernanceV1ContractError, GovernanceV1Denied
from core.plugin_runtime_v1 import PluginHostV1
from core.governed_capability_host_v1 import HostBoundCapabilityPortV1

OPERATIONS = frozenset({
    "lifecycle.install", "lifecycle.enable", "lifecycle.disable",
    "lifecycle.inspect", "lifecycle.list", "lifecycle.remove", "execute.test.echo",
})


class PluginCapabilityPortV1(HostBoundCapabilityPortV1):
    """Keep lifecycle administration distinct from the sole executable test op."""

    def __init__(self, plugin_host: PluginHostV1) -> None:
        super().__init__()
        if type(plugin_host) is not PluginHostV1:
            raise GovernanceV1ContractError("exact PluginHostV1 is required")
        self._host = plugin_host
        self._lock = RLock()
        self._revoked: set[str] = set()
        self._disconnected = False
        self._closed = False
        self._killed = False
        self._active: dict[str, Event] = {}

    def _dispatch_bound(self, operation, arguments, binding_id):
        if type(binding_id) is not str or not binding_id:
            raise GovernanceV1Denied("authenticated plugin binding is required")
        cancellation = Event()
        with self._lock:
            if binding_id in self._revoked or self._killed or self._closed or self._disconnected:
                raise GovernanceV1Denied("plugin binding is unavailable")
            self._active[binding_id] = cancellation
        try:
            return self._dispatch_authorized(operation, arguments, cancellation=cancellation)
        finally:
            with self._lock:
                self._active.pop(binding_id, None)

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object], *, cancellation: Event | None = None) -> object:
        with self._lock:
            if self._killed:
                raise GovernanceV1Denied("plugin port kill is latched")
            if self._closed or self._disconnected:
                raise GovernanceV1Denied("plugin port is unavailable")
        if operation == "lifecycle.list" and not arguments:
            return self._host.list()
        if operation == "lifecycle.inspect" and set(arguments) == {"plugin_id"}:
            return self._host.inspect(self._text(arguments["plugin_id"]))
        if operation in {"lifecycle.enable", "lifecycle.disable", "lifecycle.remove"} and set(arguments) == {"plugin_id"}:
            method = getattr(self._host, operation.removeprefix("lifecycle."))
            return method(self._text(arguments["plugin_id"]))
        if operation == "lifecycle.install" and set(arguments) == {"manifest_path", "approved_capabilities"}:
            approved = arguments["approved_capabilities"]
            if type(approved) is not tuple or any(type(item) is not str for item in approved):
                raise GovernanceV1ContractError("approved_capabilities must be a tuple")
            return self._host.install(
                self._text(arguments["manifest_path"]), approved_capabilities=approved
            )
        if operation == "execute.test.echo" and set(arguments) == {"plugin_id", "payload"}:
            options = {"cancellation": cancellation} if cancellation is not None else {}
            return self._host.execute(
                self._text(arguments["plugin_id"]), "test.echo", arguments["payload"], **options
            )
        raise GovernanceV1Denied("unknown plugin lifecycle or execution operation")

    @staticmethod
    def _text(value: object) -> str:
        if type(value) is not str or not value or "\x00" in value:
            raise GovernanceV1ContractError("plugin identifier/path is invalid")
        return value

    def revoke(self, binding_id: str) -> dict[str, object]:
        with self._lock:
            self._revoked.add(binding_id)
            signal = self._active.get(binding_id)
            if signal is not None:
                signal.set()
        return {"status": "binding-revoked", "binding_id": binding_id}

    def disconnect(self) -> dict[str, object]:
        with self._lock:
            self._disconnected = True
        self._host.cancel()
        return {"status": "disconnected", "closed": False, "killed": False}

    def close(self) -> dict[str, object]:
        with self._lock:
            self._closed = True
        self._host.cancel()
        return {"status": "closed", "killed": False}

    def kill(self) -> dict[str, object]:
        with self._lock:
            self._killed = True
        self._host.cancel()
        return {"status": "kill-latched"}


__all__ = ["OPERATIONS", "PluginCapabilityPortV1"]
