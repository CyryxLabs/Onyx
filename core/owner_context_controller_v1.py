"""Lazy live controller for the local owner-context profile."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Mapping

from core.owner_context_profile_v1 import (
    OwnerContextFieldV1,
    OwnerContextStoreV1,
)
from core.phase6_live_wiring_v1 import SESSION_ATTRIBUTE, LiveWiringSessionV1


HOST_CONTROLLER = "_owner_context_controller_v1"


class OwnerContextControllerError(RuntimeError):
    pass


class OwnerContextControllerDenied(PermissionError):
    pass


class OwnerContextControllerV1:
    def __init__(self, host: object) -> None:
        if host is None:
            raise OwnerContextControllerError("owner context host is required")
        self._host = host
        self._session: LiveWiringSessionV1 | None = None
        self._store: OwnerContextStoreV1 | None = None
        self._closed = False
        self._lock = threading.RLock()
        self.background_workers = 0
        self.polling_interval = None

    @property
    def closed(self) -> bool:
        return self._closed

    def _bind_current(self) -> tuple[LiveWiringSessionV1, OwnerContextStoreV1] | None:
        if self._closed:
            raise OwnerContextControllerDenied("owner context controller is closed")
        observed = getattr(self._host, SESSION_ATTRIBUTE, None)
        if observed is self._session and self._store is not None:
            if observed is not None and not observed.closed:
                return observed, self._store
        self._session = None
        self._store = None
        if observed is None:
            return None
        if type(observed) is not LiveWiringSessionV1 or observed.closed:
            raise OwnerContextControllerDenied("live Phase 6 session authority diverged")
        identity = observed.identity
        if not identity.profile_id or not identity.workspace_id:
            raise OwnerContextControllerDenied("live owner context identity is unavailable")
        root = Path(observed.state_path).resolve().parent / "owner-context-v1"
        store = OwnerContextStoreV1(root / "owner-context-v1.sqlite3")
        self._session = observed
        self._store = store
        return observed, store

    def execute(self, arguments: Mapping[str, object]) -> dict[str, object]:
        if not isinstance(arguments, Mapping):
            raise OwnerContextControllerDenied("owner context arguments are invalid")
        action = str(arguments.get("action", ""))
        if action not in {"status", "get", "set", "clear", "verify"}:
            raise OwnerContextControllerDenied("owner context action is unsupported")
        with self._lock:
            bound = self._bind_current()
            if bound is None:
                return {
                    "contract": "OnyxOwnerContextCommand.v1",
                    "status": "waiting_for_live_session",
                    "action": action,
                    "background_workers": 0,
                    "polling_interval": None,
                    "external_dispatch": False,
                }
            session, store = bound
            owner = session.identity.profile_id
            workspace = session.identity.workspace_id
            if action == "status":
                snapshot = store.snapshot(owner, workspace)
                return {
                    "contract": "OnyxOwnerContextCommand.v1",
                    "status": "available_local_context",
                    "action": action,
                    "revision": snapshot.revision,
                    "field_count": len(snapshot.fields),
                    "background_workers": 0,
                    "polling_interval": None,
                    "external_dispatch": False,
                }
            if action == "get":
                return {
                    "contract": "OnyxOwnerContextCommand.v1",
                    "status": "completed",
                    "action": action,
                    "snapshot": store.snapshot(owner, workspace).payload(),
                    "external_dispatch": False,
                }
            if action == "verify":
                return {
                    "contract": "OnyxOwnerContextCommand.v1",
                    "status": "verified",
                    "action": action,
                    "chain_valid": store.verify_chain(owner, workspace),
                    "external_dispatch": False,
                }
            if arguments.get("source") != "owner_statement":
                raise OwnerContextControllerDenied(
                    "owner context mutation requires an explicit owner statement"
                )
            selected = OwnerContextFieldV1(str(arguments.get("field", "")))
            if action == "set":
                value: object = (
                    arguments.get("values")
                    if selected in {
                        OwnerContextFieldV1.ROLES,
                        OwnerContextFieldV1.PRIORITIES,
                        OwnerContextFieldV1.PROJECTS,
                        OwnerContextFieldV1.INTERESTS,
                        OwnerContextFieldV1.TOOLS,
                        OwnerContextFieldV1.IMPORTANT_PEOPLE,
                        OwnerContextFieldV1.CONSTRAINTS,
                    }
                    else arguments.get("value")
                )
                snapshot = store.set_field(owner, workspace, selected, value)
            else:
                snapshot = store.clear_field(owner, workspace, selected)
            return {
                "contract": "OnyxOwnerContextCommand.v1",
                "status": "completed",
                "action": action,
                "field": selected.value,
                "revision": snapshot.revision,
                "snapshot": snapshot.payload(),
                "external_dispatch": False,
            }

    def prompt_projection(self) -> str:
        with self._lock:
            bound = self._bind_current()
            if bound is None:
                return ""
            session, store = bound
            return store.prompt_projection(
                session.identity.profile_id,
                session.identity.workspace_id,
            )

    def close(self) -> None:
        with self._lock:
            self._session = None
            self._store = None
            self._closed = True


__all__ = [
    "HOST_CONTROLLER",
    "OwnerContextControllerDenied",
    "OwnerContextControllerError",
    "OwnerContextControllerV1",
]
