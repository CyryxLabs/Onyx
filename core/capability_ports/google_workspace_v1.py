"""Lazy governed port for the existing Google Workspace live adapter."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping
from typing import Final

from core.google_workspace_connector_v1 import READ_SCOPES
from core.google_workspace_live_v1 import ACTIONS
from core.governed_capability_host_v1 import HostBoundCapabilityPortV1


class GoogleWorkspaceCapabilityPortV1ContractError(ValueError):
    pass


class GoogleWorkspaceCapabilityPortV1Denied(PermissionError):
    pass


GOOGLE_WORKSPACE_OPERATIONS: Final = frozenset(ACTIONS)
_FORBIDDEN = frozenset(
    {
        "principal", "principal_id", "workspace", "workspace_id", "account",
        "account_id", "token", "access_token", "refresh_token", "authorization",
        "credential", "credential_alias", "scopes", "provider",
    }
)


def _digest(value: object) -> str:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise GoogleWorkspaceCapabilityPortV1ContractError(
            "Google Workspace arguments are not canonical JSON"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


class GoogleWorkspaceCapabilityPortV1(HostBoundCapabilityPortV1):
    def __init__(
        self, *, adapter_factory: Callable[[], object], enabled: bool = False,
        trace_factory: Callable[[], str],
    ) -> None:
        super().__init__()
        if not callable(adapter_factory) or not callable(trace_factory) or type(enabled) is not bool:
            raise GoogleWorkspaceCapabilityPortV1ContractError("invalid Google port configuration")
        self._adapter_factory = adapter_factory
        self._trace_factory = trace_factory
        self._enabled = enabled
        self._resources: list[object] = []
        self._killed = False
        self._lock = threading.RLock()

    @property
    def operations(self) -> frozenset[str]:
        return GOOGLE_WORKSPACE_OPERATIONS

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object]) -> object:
        if type(operation) is not str or operation not in GOOGLE_WORKSPACE_OPERATIONS:
            raise GoogleWorkspaceCapabilityPortV1Denied("unknown Google Workspace operation")
        if not isinstance(arguments, Mapping):
            raise GoogleWorkspaceCapabilityPortV1ContractError("arguments must be a mapping")
        copied = dict(arguments)
        if any(type(key) is not str for key in copied) or set(copied) & _FORBIDDEN:
            raise GoogleWorkspaceCapabilityPortV1Denied("authority and credential fields are host-owned")
        if "action" in copied and copied["action"] != operation:
            raise GoogleWorkspaceCapabilityPortV1Denied("Google Workspace operation mismatch")
        copied["action"] = operation
        argument_digest = _digest(copied)
        with self._lock:
            if self._killed:
                raise GoogleWorkspaceCapabilityPortV1Denied(
                    "Google Workspace capability is killed"
                )
            if not self._enabled:
                raise GoogleWorkspaceCapabilityPortV1Denied("Google Workspace capability is disabled")
        if operation == "status":
            return {
                "schema": "OnyxGoogleWorkspaceCapabilityStatus.v1",
                "enabled": True,
                "connected": "unknown",
                "scopes": READ_SCOPES,
                "provider_dispatch": False,
                "redacted": True,
            }
        adapter = self._adapter_factory()
        execute = getattr(adapter, "execute", None)
        if not callable(execute):
            self._close(adapter)
            raise GoogleWorkspaceCapabilityPortV1ContractError("injected Google adapter is invalid")
        with self._lock:
            if self._killed:
                self._close(adapter)
                raise GoogleWorkspaceCapabilityPortV1Denied("Google Workspace capability is killed")
            self._resources.append(adapter)
        try:
            response = execute(copied, trace_id=self._trace_factory())
            if type(response) is not dict or response.get("action") != operation:
                raise GoogleWorkspaceCapabilityPortV1Denied("provider receipt operation mismatch")
            receipt = response.get("receipt")
            receipt_digest = receipt.get("receipt_digest") if type(receipt) is dict else None
            if receipt_digest is not None and (
                type(receipt_digest) is not str or len(receipt_digest) != 64
            ):
                raise GoogleWorkspaceCapabilityPortV1Denied("provider receipt digest mismatch")
            return {
                "schema": "OnyxGoogleWorkspaceCapabilityReceipt.v1",
                "operation": operation,
                "effect": "provider-read" if operation.startswith("list_") else "external-mutation",
                "scopes": READ_SCOPES,
                "status": "completed",
                "argument_digest": argument_digest,
                "result_digest": _digest(response),
                "receipt_digest": receipt_digest or "0" * 64,
                "redacted": True,
            }
        finally:
            with self._lock:
                if adapter in self._resources:
                    self._resources.remove(adapter)
            self._close(adapter)

    @staticmethod
    def _close(resource: object) -> None:
        close = getattr(resource, "close", None)
        if callable(close):
            close()

    def revoke(self, binding_id: str) -> object:
        # Host revocation is local authority invalidation. Provider revocation is
        # exclusively the explicit, consequential ``disconnect`` operation.
        return None

    def kill(self) -> object:
        with self._lock:
            self._killed = True
            resources, self._resources = self._resources, []
        for resource in resources:
            self._close(resource)
        return True


__all__ = [
    "GOOGLE_WORKSPACE_OPERATIONS", "GoogleWorkspaceCapabilityPortV1",
    "GoogleWorkspaceCapabilityPortV1ContractError",
    "GoogleWorkspaceCapabilityPortV1Denied",
]
