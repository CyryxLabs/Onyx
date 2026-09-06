"""Lazy, closed Microsoft Graph port for ``GovernedCapabilityHostV1``.

Concrete Phase 8 sessions are injected.  This module deliberately owns no
credentials, HTTP client, authority identity, or startup provisioning.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from typing import Final

from core.governed_capability_host_v1 import HostBoundCapabilityPortV1


class GraphCapabilityPortV1ContractError(ValueError):
    pass


class GraphCapabilityPortV1Denied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class GraphOperationV1:
    factory: Callable[[], object]
    method: str
    effect: str
    scopes: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not callable(self.factory)
            or type(self.method) is not str
            or not self.method
            or self.effect not in {"provider-read", "external-mutation", "local-mutation"}
            or type(self.scopes) is not tuple
            or not self.scopes
            or any(type(scope) is not str or not scope for scope in self.scopes)
            or len(set(self.scopes)) != len(self.scopes)
        ):
            raise GraphCapabilityPortV1ContractError("invalid Graph operation")


GRAPH_OPERATIONS: Final = frozenset(
    {
        "daily_brief", "search_messages", "read_message",
        "list_drive_root", "list_drive_children", "get_drive_item",
        "send_mail", "create_event", "create_task", "disconnect_local",
    }
)
GRAPH_READ_SCOPES: Final = (
    "Calendars.Read", "Mail.Read", "User.Read", "offline_access",
)
GRAPH_DRIVE_SCOPES: Final = ("Files.Read", "User.Read", "offline_access")
GRAPH_MAIL_SCOPES: Final = (
    "Mail.ReadWrite", "Mail.Send", "User.Read", "offline_access",
)
GRAPH_CALENDAR_SCOPES: Final = (
    "Calendars.ReadWrite", "User.Read", "offline_access",
)
GRAPH_TASK_SCOPES: Final = ("Tasks.ReadWrite", "User.Read", "offline_access")
_FORBIDDEN = frozenset(
    {
        "principal", "principal_id", "workspace", "workspace_id", "account",
        "account_id", "token", "access_token", "refresh_token", "authorization",
        "credential", "credential_alias", "scopes", "operation", "provider",
    }
)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise GraphCapabilityPortV1ContractError("arguments are not canonical JSON") from exc


def _safe_arguments(arguments: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(arguments, Mapping):
        raise GraphCapabilityPortV1ContractError("arguments must be a mapping")
    copied = dict(arguments)
    if any(type(key) is not str for key in copied) or set(copied) & _FORBIDDEN:
        raise GraphCapabilityPortV1Denied("authority and credential fields are host-owned")
    _canonical(copied)
    return copied


def _shape(value: object) -> tuple[int, str]:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    count = len(value) if isinstance(value, (list, tuple)) else 1
    return count, hashlib.sha256(_canonical(value)).hexdigest()


class GraphCapabilityPortV1(HostBoundCapabilityPortV1):
    """Dispatch an exact, injected Graph method and expose only redacted proof."""

    def __init__(
        self, *, enabled: bool = False, operations: Mapping[str, GraphOperationV1]
    ) -> None:
        super().__init__()
        if type(enabled) is not bool or not isinstance(operations, Mapping):
            raise GraphCapabilityPortV1ContractError("invalid Graph port configuration")
        copied = dict(operations)
        if not copied or set(copied) - GRAPH_OPERATIONS or any(
            type(name) is not str or type(spec) is not GraphOperationV1
            for name, spec in copied.items()
        ):
            raise GraphCapabilityPortV1ContractError("Graph registry is not closed")
        self._enabled = enabled
        self._operations = copied
        self._resources: list[object] = []
        self._revoked: set[str] = set()
        self._killed = False
        self._lock = threading.RLock()

    @property
    def operations(self) -> frozenset[str]:
        return frozenset(self._operations)

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "schema": "OnyxGraphCapabilityPortStatus.v1",
                "enabled": self._enabled,
                "killed": self._killed,
                "operations": tuple(sorted(self._operations)),
                "provider_dispatch": False,
            }

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object]) -> object:
        if type(operation) is not str or operation not in self._operations:
            raise GraphCapabilityPortV1Denied("unknown Graph operation")
        copied = _safe_arguments(arguments)
        with self._lock:
            if self._killed:
                raise GraphCapabilityPortV1Denied("Graph capability is killed")
            if not self._enabled:
                raise GraphCapabilityPortV1Denied("Graph capability is disabled")
            spec = self._operations[operation]
        resource = spec.factory()
        method = getattr(resource, spec.method, None)
        if not callable(method):
            self._close(resource)
            raise GraphCapabilityPortV1ContractError("injected Graph method is unavailable")
        with self._lock:
            if self._killed:
                self._close(resource)
                raise GraphCapabilityPortV1Denied("Graph capability is killed")
            self._resources.append(resource)
        try:
            value = method(**copied)
            observed = getattr(value, "operation", operation)
            if observed != operation:
                raise GraphCapabilityPortV1Denied("provider receipt operation mismatch")
            item_count, digest = _shape(value)
            return {
                "schema": "OnyxGraphCapabilityReceipt.v1",
                "operation": operation,
                "effect": spec.effect,
                "scopes": spec.scopes,
                "status": "completed",
                "item_count": item_count,
                "result_digest": digest,
                "redacted": True,
            }
        finally:
            with self._lock:
                if resource in self._resources:
                    self._resources.remove(resource)
            self._close(resource)

    @staticmethod
    def _close(resource: object) -> None:
        close = getattr(resource, "close", None)
        if callable(close):
            close()

    def revoke(self, binding_id: str) -> object:
        with self._lock:
            self._revoked.add(binding_id)
        return None

    def kill(self) -> object:
        with self._lock:
            self._killed = True
            resources, self._resources = self._resources, []
        for resource in resources:
            self._close(resource)
        return True


__all__ = [
    "GRAPH_CALENDAR_SCOPES", "GRAPH_DRIVE_SCOPES", "GRAPH_MAIL_SCOPES",
    "GRAPH_OPERATIONS", "GRAPH_READ_SCOPES", "GRAPH_TASK_SCOPES",
    "GraphCapabilityPortV1", "GraphCapabilityPortV1ContractError",
    "GraphCapabilityPortV1Denied", "GraphOperationV1",
]
