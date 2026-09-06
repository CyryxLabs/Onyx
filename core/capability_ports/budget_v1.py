"""Atomic provider-free budget policy ledger for governed capabilities."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from threading import RLock
from typing import Protocol

from core.governance_nucleus_v1 import GovernanceV1ContractError, GovernanceV1Denied
from core.governed_capability_host_v1 import HostBoundCapabilityPortV1

OPERATIONS = frozenset({"reserve", "commit", "release", "status"})
MAX_AMOUNT_MICRO = 1_000_000_000_000_000


class BudgetStateStoreV1(Protocol):
    """Injected persistence boundary; save must replace one complete byte value atomically."""

    def load_bytes(self) -> bytes | None: ...
    def save_bytes(self, value: bytes) -> None: ...


class BudgetCapabilityPortV1(HostBoundCapabilityPortV1):
    """Hard-quota accounting. A positive result is policy, never permission."""

    def __init__(self, *, principal_id: str, workspace_id: str, quota_micro: int,
                 store: BudgetStateStoreV1 | None = None) -> None:
        super().__init__()
        if type(principal_id) is not str or not principal_id or type(workspace_id) is not str or not workspace_id:
            raise GovernanceV1ContractError("budget principal and workspace binding are required")
        if type(quota_micro) is not int or isinstance(quota_micro, bool) or not 1 <= quota_micro <= MAX_AMOUNT_MICRO:
            raise GovernanceV1ContractError("budget quota is out of bounds")
        if store is not None and (not callable(getattr(store, "load_bytes", None)) or
                                  not callable(getattr(store, "save_bytes", None))):
            raise GovernanceV1ContractError("budget store contract violation")
        self._principal_id = principal_id
        self._workspace_id = workspace_id
        self._quota = quota_micro
        self._store = store
        self._lock = RLock()
        self._killed = False
        self._reservations: dict[str, dict[str, object]] = {}
        self._idempotency: dict[str, dict[str, object]] = {}
        self._transaction_backup: tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]] | None = None
        if store is not None:
            raw = store.load_bytes()  # Read only: construction never creates or mutates storage.
            if raw is not None:
                self._restore(raw)

    def _restore(self, raw: bytes) -> None:
        try:
            state = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise GovernanceV1ContractError("budget store state is malformed") from exc
        if type(state) is not dict or set(state) != {"schema", "principal_id", "workspace_id", "quota_micro", "reservations", "idempotency"}:
            raise GovernanceV1ContractError("budget store state contract violation")
        if (state["schema"] != "OnyxBudgetLedger.v1" or state["principal_id"] != self._principal_id or
                state["workspace_id"] != self._workspace_id or state["quota_micro"] != self._quota or
                type(state["reservations"]) is not dict or type(state["idempotency"]) is not dict):
            raise GovernanceV1Denied("budget store binding mismatch")
        self._reservations = state["reservations"]
        self._idempotency = state["idempotency"]
        self._validate_loaded_state()

    def _validate_loaded_state(self) -> None:
        total = 0
        for reservation_id, item in self._reservations.items():
            if (type(reservation_id) is not str or type(item) is not dict or
                    set(item) != {"amount_micro", "state"} or
                    type(item["amount_micro"]) is not int or
                    item["state"] not in {"reserved", "committed", "released", "uncertain"}):
                raise GovernanceV1ContractError("budget reservation state is malformed")
            if item["state"] != "released":
                total += item["amount_micro"]
        if total > self._quota:
            raise GovernanceV1Denied("persisted budget exceeds quota")

    def _encoded(self) -> bytes:
        return json.dumps({"schema": "OnyxBudgetLedger.v1", "principal_id": self._principal_id,
                           "workspace_id": self._workspace_id, "quota_micro": self._quota,
                           "reservations": self._reservations, "idempotency": self._idempotency},
                          sort_keys=True, separators=(",", ":")).encode()

    def _save(self) -> None:
        if self._store is not None:
            self._store.save_bytes(self._encoded())

    def _scope(self, arguments: Mapping[str, object], extra: set[str]) -> None:
        if type(arguments) is not dict or set(arguments) != {"principal_id", "workspace_id", "idempotency_key"} | extra:
            raise GovernanceV1ContractError("budget operation arguments contract violation")
        if arguments["principal_id"] != self._principal_id or arguments["workspace_id"] != self._workspace_id:
            raise GovernanceV1Denied("budget principal or workspace binding mismatch")
        key = arguments["idempotency_key"]
        if type(key) is not str or not key or len(key.encode()) > 256:
            raise GovernanceV1ContractError("budget idempotency key is malformed")

    def _used(self) -> int:
        return sum(int(item["amount_micro"]) for item in self._reservations.values() if item["state"] != "released")

    def _idempotent(self, operation: str, arguments: Mapping[str, object]) -> dict[str, object] | None:
        key = str(arguments["idempotency_key"])
        fingerprint = hashlib.sha256(json.dumps({"operation": operation, "arguments": arguments}, sort_keys=True,
                                                separators=(",", ":")).encode()).hexdigest()
        previous = self._idempotency.get(key)
        if previous is None:
            return None
        if previous.get("fingerprint") != fingerprint:
            raise GovernanceV1Denied("budget idempotency key reuse mismatch")
        return dict(previous["result"])

    def _record(self, operation: str, arguments: Mapping[str, object], result: dict[str, object]) -> dict[str, object]:
        key = str(arguments["idempotency_key"])
        fingerprint = hashlib.sha256(json.dumps({"operation": operation, "arguments": arguments}, sort_keys=True,
                                                separators=(",", ":")).encode()).hexdigest()
        self._idempotency[key] = {"fingerprint": fingerprint, "result": result}
        try:
            self._save()
        except Exception:
            if self._transaction_backup is not None:
                self._reservations, self._idempotency = self._transaction_backup
            raise
        finally:
            self._transaction_backup = None
        return result

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object]) -> object:
        extras = {"amount_micro"} if operation == "reserve" else ({"reservation_id", "uncertain"} if operation == "commit" else ({"reservation_id"} if operation == "release" else set()))
        self._scope(arguments, extras)
        with self._lock:
            if self._killed:
                raise GovernanceV1Denied("budget capability kill is latched")
            prior = self._idempotent(operation, arguments)
            if prior is not None:
                return prior
            self._transaction_backup = (
                {key: dict(value) for key, value in self._reservations.items()},
                {key: {"fingerprint": value["fingerprint"], "result": dict(value["result"])}
                 for key, value in self._idempotency.items()},
            )
            if operation == "status":
                return self._record(operation, arguments, self._status())
            if operation == "reserve":
                amount = arguments["amount_micro"]
                if type(amount) is not int or isinstance(amount, bool) or not 1 <= amount <= MAX_AMOUNT_MICRO:
                    raise GovernanceV1ContractError("budget amount is out of bounds")
                if self._used() + amount > self._quota:
                    raise GovernanceV1Denied("hard budget quota exhausted")
                reservation_id = "budget-" + hashlib.sha256((self._principal_id + "\0" + self._workspace_id + "\0" + str(arguments["idempotency_key"])).encode()).hexdigest()[:32]
                self._reservations[reservation_id] = {"amount_micro": amount, "state": "reserved"}
                return self._record(operation, arguments, {"reservation_id": reservation_id, "state": "reserved", "policy_only": True, "permission_granted": False})
            reservation_id = arguments["reservation_id"]
            if type(reservation_id) is not str or reservation_id not in self._reservations:
                raise GovernanceV1ContractError("unknown budget reservation")
            item = self._reservations[reservation_id]
            if operation == "commit":
                uncertain = arguments["uncertain"]
                if type(uncertain) is not bool:
                    raise GovernanceV1ContractError("uncertain must be exact bool")
                if item["state"] == "released":
                    raise GovernanceV1Denied("released budget cannot be committed")
                if item["state"] == "reserved":
                    item["state"] = "uncertain" if uncertain else "committed"
                elif uncertain and item["state"] == "committed":
                    item["state"] = "uncertain"
                return self._record(operation, arguments, {"reservation_id": reservation_id, "state": item["state"], "policy_only": True, "permission_granted": False})
            if item["state"] != "reserved":
                raise GovernanceV1Denied("committed or uncertain budget cannot be released")
            item["state"] = "released"
            return self._record(operation, arguments, {"reservation_id": reservation_id, "state": "released", "policy_only": True, "permission_granted": False})

    def _status(self) -> dict[str, object]:
        used = self._used()
        return {"quota_micro": self._quota, "used_micro": used, "remaining_micro": self._quota - used,
                "policy_only": True, "permission_granted": False}

    def revoke(self, binding_id: str) -> None:
        del binding_id

    def kill(self) -> bool:
        with self._lock:
            self._killed = True
        return True


__all__ = ["BudgetCapabilityPortV1", "BudgetStateStoreV1", "MAX_AMOUNT_MICRO", "OPERATIONS"]
