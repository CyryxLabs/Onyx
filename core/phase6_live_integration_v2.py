"""Phase 6 Live Integration V2 identity and operational-factory closure.

V2 composes the frozen V1 candidate without editing it.  The operational
factory owns construction of the exact current text invoker and exact
``TerminableProcessExecutorV4``; it exposes no callback or executor parameter.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from core import phase6_live_integration_v1 as live_v1
from core.phase5_integration_v3 import Phase5IntegrationV3
from core.phase6_agentic_core_v1 import (
    DataClassV1,
    DisabledExternalAgentAdapterV1,
    GoalV1,
    PlanProjectionV1,
    PlanStateV1,
)
from core.phase6_agentic_core_v4 import TerminableProcessExecutorV4
from core.phase6_agentic_core_v6 import AgenticCoreV6, AgenticStateStoreV6


FEATURE_FLAG = "ONYX_PHASE6_LIVE_INTEGRATION_V2"
SCHEMA_VERSION = 2
MAX_RECEIPT_BYTES = 65_536
_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_REASON = re.compile(r"[a-z][a-z0-9_-]{2,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CONSTRUCTION_KEY = object()
_OPERATIONAL_INVOKER = live_v1._current_llm_text_call


class Phase6LiveIntegrationV2Error(RuntimeError):
    """The V2 integration could not safely complete."""


class Phase6LiveIntegrationV2ContractError(ValueError):
    """A V2 input is not exact or canonical."""


class Phase6LiveIntegrationV2Denied(PermissionError):
    """V2 authority denied construction or invocation."""


def _id(value: object, label: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise Phase6LiveIntegrationV2ContractError(
            f"{label} must be a canonical host identifier"
        )
    return value


def _reason(value: object) -> str:
    if type(value) is not str or _REASON.fullmatch(value) is None:
        raise Phase6LiveIntegrationV2ContractError(
            "reason must be a canonical reason code"
        )
    return value


def _digest(value: object) -> str:
    if isinstance(value, bytes):
        payload = value
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        try:
            encoded = json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            )
        except (TypeError, ValueError) as exc:
            raise Phase6LiveIntegrationV2ContractError(
                "value is not canonical JSON"
            ) from exc
        if len(encoded.encode("utf-8")) > MAX_RECEIPT_BYTES:
            raise Phase6LiveIntegrationV2ContractError("canonical value is too large")
        payload = encoded.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _require_digest(value: object, label: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise Phase6LiveIntegrationV2ContractError(f"{label} must be SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class LiveIntegrationFeatureGateV2:
    enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise Phase6LiveIntegrationV2ContractError(
                "V2 gate must be an exact boolean"
            )

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "LiveIntegrationFeatureGateV2":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True, slots=True)
class HostIdentityBindingV2:
    """Exact Phase 6/Phase 5 principal and tenancy authority."""

    workspace_id: str
    account_id: str
    profile_id: str
    principal_id: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            _id(getattr(self, name), name)

    def payload(self) -> dict[str, str]:
        return {
            "workspace_id": self.workspace_id,
            "account_id": self.account_id,
            "profile_id": self.profile_id,
            "principal_id": self.principal_id,
        }

    @property
    def digest(self) -> str:
        return _digest({"schema": "OnyxPhase6HostIdentityBinding.v2", **self.payload()})

    def attest(self, agentic_core: AgenticCoreV6, phase5: Phase5IntegrationV3) -> None:
        if type(agentic_core) is not AgenticCoreV6:
            raise Phase6LiveIntegrationV2ContractError(
                "exact AgenticCoreV6 is required"
            )
        if type(phase5) is not Phase5IntegrationV3:
            raise Phase6LiveIntegrationV2ContractError(
                "exact Phase5IntegrationV3 is required"
            )
        workspace = getattr(agentic_core, "_workspace", None)
        if workspace is None or workspace.workspace_id != self.workspace_id:
            raise Phase6LiveIntegrationV2Denied(
                "Agentic Core workspace identity diverged"
            )
        binding = phase5.binding
        actual = (
            binding.workspace_id,
            binding.account_id,
            binding.profile_id,
            getattr(phase5, "_principal_id", None),
        )
        expected = (
            self.workspace_id,
            self.account_id,
            self.profile_id,
            self.principal_id,
        )
        if actual != expected:
            raise Phase6LiveIntegrationV2Denied("Phase 5 host identity diverged")


@dataclass(frozen=True, slots=True)
class TextProviderRequestV2:
    identity: HostIdentityBindingV2
    request: live_v1.TextProviderRequestV1

    def __post_init__(self) -> None:
        if type(self.identity) is not HostIdentityBindingV2:
            raise Phase6LiveIntegrationV2ContractError("exact V2 identity is required")
        if type(self.request) is not live_v1.TextProviderRequestV1:
            raise Phase6LiveIntegrationV2ContractError(
                "exact V1 text request is required"
            )
        if self.request.workspace_id != self.identity.workspace_id:
            raise Phase6LiveIntegrationV2Denied(
                "text request workspace diverges from V2 identity"
            )

    @property
    def digest(self) -> str:
        return _digest(
            {
                "schema": "OnyxPhase6TextRequest.v2",
                "identity": self.identity.payload(),
                "identity_digest": self.identity.digest,
                "v1_request_digest": self.request.digest,
            }
        )


@dataclass(frozen=True, slots=True)
class TextProviderResultV2:
    identity: HostIdentityBindingV2
    request_digest: str
    result: live_v1.TextProviderResultV1
    receipt_digest: str

    def __post_init__(self) -> None:
        if type(self.identity) is not HostIdentityBindingV2:
            raise Phase6LiveIntegrationV2ContractError("exact V2 identity is required")
        _require_digest(self.request_digest, "request_digest")
        if type(self.result) is not live_v1.TextProviderResultV1:
            raise Phase6LiveIntegrationV2ContractError(
                "exact V1 provider result is required"
            )
        _require_digest(self.receipt_digest, "receipt_digest")
        if self.receipt_digest != _digest(self.receipt_payload()):
            raise Phase6LiveIntegrationV2ContractError(
                "V2 text receipt digest mismatch"
            )

    def receipt_payload(self) -> dict[str, object]:
        return {
            "schema": "OnyxPhase6TextReceipt.v2",
            "identity": self.identity.payload(),
            "identity_digest": self.identity.digest,
            "request_digest": self.request_digest,
            "v1_receipt_digest": self.result.receipt_digest,
            "status": self.result.status,
            "adapter_id": "current_local_text_v2",
            "provider_config_digest": self.result.provider_config_digest,
            "content_digest": self.result.content_digest,
            "reserved_output_tokens": self.result.reserved_output_tokens,
            "provider_calls": self.result.provider_calls,
            "elapsed_millis": self.result.elapsed_millis,
            "reason": self.result.reason,
        }


class CurrentTextProviderAdapterV2:
    """Operational adapter whose invoker/executor cannot be supplied by callers."""

    adapter_id = "current_local_text_v2"

    def __init__(
        self,
        *,
        identity: HostIdentityBindingV2,
    ) -> None:
        if type(identity) is not HostIdentityBindingV2:
            raise Phase6LiveIntegrationV2ContractError("exact V2 identity is required")
        self._identity = identity
        self._delegate = live_v1.CurrentTextProviderAdapterV1(
            workspace_id=identity.workspace_id,
            config=live_v1._current_llm_config(),
            invoke=_OPERATIONAL_INVOKER,
            maximum_data_class=DataClassV1.CONFIDENTIAL,
            executor=TerminableProcessExecutorV4(),
        )
        self._attest_operational()

    @classmethod
    def operational(
        cls, identity: HostIdentityBindingV2
    ) -> "CurrentTextProviderAdapterV2":
        if type(identity) is not HostIdentityBindingV2:
            raise Phase6LiveIntegrationV2ContractError("exact V2 identity is required")
        return cls(identity=identity)

    def _attest_operational(self) -> None:
        if type(self._delegate) is not live_v1.CurrentTextProviderAdapterV1:
            raise Phase6LiveIntegrationV2Denied("V2 text delegate type diverged")
        if getattr(self._delegate, "_invoke", None) is not _OPERATIONAL_INVOKER:
            raise Phase6LiveIntegrationV2Denied(
                "V2 text invoker is not the frozen current-client seam"
            )
        if type(getattr(self._delegate, "_executor", None)) is not (
            TerminableProcessExecutorV4
        ):
            raise Phase6LiveIntegrationV2Denied(
                "V2 text executor is not exact TerminableProcessExecutorV4"
            )
        descriptor = self._delegate.descriptor
        if descriptor.workspace_allowlist != (self._identity.workspace_id,):
            raise Phase6LiveIntegrationV2Denied("V2 text descriptor workspace diverged")

    @property
    def descriptor(self):
        self._attest_operational()
        return self._delegate.descriptor

    @property
    def binding_digest(self) -> str:
        return self._identity.digest

    def invoke(
        self,
        request: TextProviderRequestV2,
        cancellation: live_v1.CancellationTokenV1 | None = None,
    ) -> TextProviderResultV2:
        self._attest_operational()
        if type(request) is not TextProviderRequestV2:
            raise Phase6LiveIntegrationV2ContractError(
                "exact TextProviderRequestV2 is required"
            )
        if request.identity != self._identity:
            raise Phase6LiveIntegrationV2Denied("text request identity diverged")
        result = self._delegate.invoke(request.request, cancellation)
        payload = {
            "schema": "OnyxPhase6TextReceipt.v2",
            "identity": self._identity.payload(),
            "identity_digest": self._identity.digest,
            "request_digest": request.digest,
            "v1_receipt_digest": result.receipt_digest,
            "status": result.status,
            "adapter_id": self.adapter_id,
            "provider_config_digest": result.provider_config_digest,
            "content_digest": result.content_digest,
            "reserved_output_tokens": result.reserved_output_tokens,
            "provider_calls": result.provider_calls,
            "elapsed_millis": result.elapsed_millis,
            "reason": result.reason,
        }
        return TextProviderResultV2(
            self._identity, request.digest, result, _digest(payload)
        )

    def close(self) -> None:
        self._attest_operational()
        self._delegate.close()


@dataclass(frozen=True, slots=True)
class CatalogReadRequestV2:
    identity: HostIdentityBindingV2
    request: live_v1.CatalogReadRequestV1

    def __post_init__(self) -> None:
        if type(self.identity) is not HostIdentityBindingV2:
            raise Phase6LiveIntegrationV2ContractError("exact V2 identity is required")
        if type(self.request) is not live_v1.CatalogReadRequestV1:
            raise Phase6LiveIntegrationV2ContractError(
                "exact V1 catalog request is required"
            )
        if self.request.workspace_id != self.identity.workspace_id:
            raise Phase6LiveIntegrationV2Denied("catalog request workspace diverges")

    @property
    def digest(self) -> str:
        return _digest(
            {
                "schema": "OnyxPhase6CatalogRequest.v2",
                "identity": self.identity.payload(),
                "identity_digest": self.identity.digest,
                "v1_request_digest": self.request.digest,
            }
        )


@dataclass(frozen=True, slots=True)
class CatalogReadReceiptV2:
    identity: HostIdentityBindingV2
    request_id: str
    request_digest: str
    v1_receipt_digest: str
    phase5_receipt_digest: str
    result_digest: str
    item_count: int
    next_cursor_digest: str | None
    cost_micro: int
    egress: str
    reason: str
    receipt_digest: str

    def __post_init__(self) -> None:
        if type(self.identity) is not HostIdentityBindingV2:
            raise Phase6LiveIntegrationV2ContractError("exact V2 identity is required")
        _id(self.request_id, "request_id")
        for value, label in (
            (self.request_digest, "request_digest"),
            (self.v1_receipt_digest, "v1_receipt_digest"),
            (self.phase5_receipt_digest, "phase5_receipt_digest"),
            (self.result_digest, "result_digest"),
            (self.receipt_digest, "receipt_digest"),
        ):
            _require_digest(value, label)
        if self.next_cursor_digest is not None:
            _require_digest(self.next_cursor_digest, "next_cursor_digest")
        if type(self.item_count) is not int or not 0 <= self.item_count <= 50:
            raise Phase6LiveIntegrationV2ContractError("catalog item count is invalid")
        if type(self.cost_micro) is not int or self.cost_micro != 0:
            raise Phase6LiveIntegrationV2ContractError("catalog cost must be zero")
        if self.egress != "none":
            raise Phase6LiveIntegrationV2ContractError("catalog egress must be none")
        _reason(self.reason)
        if self.receipt_digest != _digest(self.payload()):
            raise Phase6LiveIntegrationV2ContractError(
                "V2 catalog receipt digest mismatch"
            )

    def payload(self) -> dict[str, object]:
        return {
            "schema": "OnyxPhase6CatalogReceipt.v2",
            "identity": self.identity.payload(),
            "identity_digest": self.identity.digest,
            "request_id": self.request_id,
            "request_digest": self.request_digest,
            "v1_receipt_digest": self.v1_receipt_digest,
            "phase5_receipt_digest": self.phase5_receipt_digest,
            "result_digest": self.result_digest,
            "item_count": self.item_count,
            "next_cursor_digest": self.next_cursor_digest,
            "cost_micro": self.cost_micro,
            "egress": self.egress,
            "reason": self.reason,
        }

    def stored_payload(self) -> dict[str, object]:
        return self.payload() | {"receipt_digest": self.receipt_digest}

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "CatalogReadReceiptV2":
        value = dict(payload)
        if value.pop("schema", None) != "OnyxPhase6CatalogReceipt.v2":
            raise Phase6LiveIntegrationV2Error(
                "stored V2 catalog receipt schema is invalid"
            )
        identity_raw = value.pop("identity", None)
        if type(identity_raw) is not dict:
            raise Phase6LiveIntegrationV2Error("stored V2 identity is invalid")
        identity_digest = value.pop("identity_digest", None)
        identity = HostIdentityBindingV2(**identity_raw)
        if identity_digest != identity.digest:
            raise Phase6LiveIntegrationV2Error("stored V2 identity digest is invalid")
        return cls(identity=identity, **value)  # type: ignore[arg-type]


class IdentityReceiptStoreV2:
    """Authenticated append-only V2 catalog receipt store."""

    _DDL = (
        "CREATE TABLE metadata(schema_version INTEGER NOT NULL)",
        "CREATE TABLE catalog_receipts("
        "request_id TEXT PRIMARY KEY,"
        "request_digest TEXT NOT NULL,"
        "identity_digest TEXT NOT NULL,"
        "receipt_json TEXT NOT NULL,"
        "created_at REAL NOT NULL"
        ")",
        "CREATE TRIGGER catalog_receipts_no_update BEFORE UPDATE ON catalog_receipts "
        "BEGIN SELECT RAISE(ABORT,'phase6 v2 receipts are immutable'); END",
        "CREATE TRIGGER catalog_receipts_no_delete BEFORE DELETE ON catalog_receipts "
        "BEGIN SELECT RAISE(ABORT,'phase6 v2 receipts are immutable'); END",
    )

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        if not self._path.is_absolute() or self._path.name in {"", ".", ".."}:
            raise Phase6LiveIntegrationV2ContractError(
                "explicit absolute V2 receipt path is required"
            )
        self._lock = threading.RLock()
        self._expected = self._expected_inventory()
        self._initialize()

    @classmethod
    def _expected_inventory(cls) -> str:
        connection = sqlite3.connect(":memory:")
        try:
            for statement in cls._DDL:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO metadata(schema_version) VALUES(?)",
                (SCHEMA_VERSION,),
            )
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            return cls._inventory(connection)
        finally:
            connection.close()

    @staticmethod
    def _inventory(connection: sqlite3.Connection) -> str:
        objects = [
            tuple(row)
            for row in connection.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            )
        ]
        payload: dict[str, object] = {
            "objects": objects,
            "user_version": int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            ),
        }
        for table in [str(item[1]) for item in objects if item[0] == "table"]:
            payload[f"table_xinfo:{table}"] = [
                tuple(row)
                for row in connection.execute(f"PRAGMA table_xinfo('{table}')")
            ]
            payload[f"index_list:{table}"] = [
                tuple(row)
                for row in connection.execute(f"PRAGMA index_list('{table}')")
            ]
        return _digest(payload)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                ).fetchone()[0]
            )
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if count == 0 and version == 0:
                connection.execute("BEGIN IMMEDIATE")
                for statement in self._DDL:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO metadata(schema_version) VALUES(?)",
                    (SCHEMA_VERSION,),
                )
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                connection.execute("COMMIT")
            metadata = connection.execute(
                "SELECT schema_version FROM metadata"
            ).fetchall()
            if (
                self._inventory(connection) != self._expected
                or [tuple(row) for row in metadata] != [(SCHEMA_VERSION,)]
                or connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            ):
                raise Phase6LiveIntegrationV2Error(
                    "V2 receipt schema authentication failed"
                )
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def get(self, request_id: str) -> CatalogReadReceiptV2 | None:
        canonical = _id(request_id, "request_id")
        with self._lock:
            connection = self._connect()
            try:
                row = connection.execute(
                    "SELECT receipt_json FROM catalog_receipts WHERE request_id=?",
                    (canonical,),
                ).fetchone()
            finally:
                connection.close()
        if row is None:
            return None
        payload = json.loads(str(row["receipt_json"]))
        if type(payload) is not dict:
            raise Phase6LiveIntegrationV2Error("stored V2 receipt is malformed")
        return CatalogReadReceiptV2.from_payload(payload)

    def put(self, receipt: CatalogReadReceiptV2) -> tuple[CatalogReadReceiptV2, bool]:
        if type(receipt) is not CatalogReadReceiptV2:
            raise Phase6LiveIntegrationV2ContractError(
                "exact CatalogReadReceiptV2 is required"
            )
        encoded = json.dumps(
            receipt.stored_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT request_digest,identity_digest,receipt_json "
                    "FROM catalog_receipts WHERE request_id=?",
                    (receipt.request_id,),
                ).fetchone()
                if row is not None:
                    existing = CatalogReadReceiptV2.from_payload(
                        json.loads(str(row["receipt_json"]))
                    )
                    if (
                        str(row["request_digest"]) != receipt.request_digest
                        or str(row["identity_digest"]) != receipt.identity.digest
                        or existing != receipt
                    ):
                        raise Phase6LiveIntegrationV2Denied(
                            "V2 request ID is bound to another identity or input"
                        )
                    connection.execute("COMMIT")
                    return existing, False
                connection.execute(
                    "INSERT INTO catalog_receipts VALUES(?,?,?,?,?)",
                    (
                        receipt.request_id,
                        receipt.request_digest,
                        receipt.identity.digest,
                        encoded,
                        time.time(),
                    ),
                )
                connection.execute("COMMIT")
                return receipt, True
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()


class LocalCatalogReadBindingV2:
    """Identity-bound composition over the frozen V1 Phase 5 read binding."""

    def __init__(
        self,
        *,
        _key: object,
        identity: HostIdentityBindingV2,
        agentic_core: AgenticCoreV6,
        phase5: Phase5IntegrationV3,
        delegate: live_v1.LocalCatalogReadBindingV1,
        receipts: IdentityReceiptStoreV2,
    ) -> None:
        if _key is not _CONSTRUCTION_KEY:
            raise Phase6LiveIntegrationV2Denied(
                "V2 catalog binding requires the operational factory"
            )
        if type(delegate) is not live_v1.LocalCatalogReadBindingV1:
            raise Phase6LiveIntegrationV2ContractError(
                "exact frozen V1 catalog delegate is required"
            )
        if type(receipts) is not IdentityReceiptStoreV2:
            raise Phase6LiveIntegrationV2ContractError(
                "exact V2 receipt store is required"
            )
        self._identity = identity
        self._core = agentic_core
        self._phase5 = phase5
        self._delegate = delegate
        self._receipts = receipts
        self._lock = threading.RLock()
        self._attest()

    def _attest(self) -> None:
        self._identity.attest(self._core, self._phase5)
        if (
            type(self._delegate) is not live_v1.LocalCatalogReadBindingV1
            or getattr(self._delegate, "_phase5", None) is not self._phase5
            or self._delegate.workspace_id != self._identity.workspace_id
        ):
            raise Phase6LiveIntegrationV2Denied(
                "V2 catalog delegate authority diverged"
            )

    def execute(
        self,
        request: CatalogReadRequestV2,
        cancellation: live_v1.CancellationTokenV1 | None = None,
    ) -> tuple[dict[str, object], CatalogReadReceiptV2]:
        self._attest()
        if type(request) is not CatalogReadRequestV2:
            raise Phase6LiveIntegrationV2ContractError(
                "exact CatalogReadRequestV2 is required"
            )
        if request.identity != self._identity:
            raise Phase6LiveIntegrationV2Denied("catalog request identity diverged")
        with self._lock:
            prior = self._receipts.get(request.request.request_id)
            if prior is not None:
                if (
                    prior.request_digest != request.digest
                    or prior.identity != self._identity
                ):
                    raise Phase6LiveIntegrationV2Denied(
                        "catalog replay identity or input diverged"
                    )
                return {"replayed": True}, prior
            result, v1_receipt = self._delegate.execute(request.request, cancellation)
            payload = {
                "schema": "OnyxPhase6CatalogReceipt.v2",
                "identity": self._identity.payload(),
                "identity_digest": self._identity.digest,
                "request_id": request.request.request_id,
                "request_digest": request.digest,
                "v1_receipt_digest": v1_receipt.receipt_digest,
                "phase5_receipt_digest": v1_receipt.phase5_receipt_digest,
                "result_digest": v1_receipt.result_digest,
                "item_count": v1_receipt.item_count,
                "next_cursor_digest": v1_receipt.next_cursor_digest,
                "cost_micro": v1_receipt.cost_micro,
                "egress": v1_receipt.egress,
                "reason": v1_receipt.reason,
            }
            receipt = CatalogReadReceiptV2(
                identity=self._identity,
                request_id=request.request.request_id,
                request_digest=request.digest,
                v1_receipt_digest=v1_receipt.receipt_digest,
                phase5_receipt_digest=v1_receipt.phase5_receipt_digest,
                result_digest=v1_receipt.result_digest,
                item_count=v1_receipt.item_count,
                next_cursor_digest=v1_receipt.next_cursor_digest,
                cost_micro=v1_receipt.cost_micro,
                egress=v1_receipt.egress,
                reason=v1_receipt.reason,
                receipt_digest=_digest(payload),
            )
            stored, _ = self._receipts.put(receipt)
            return result, stored


@dataclass(frozen=True, slots=True)
class CatalogPlanResultV2:
    plan_id: str
    state: PlanStateV1
    result: dict[str, object] | None
    receipt: CatalogReadReceiptV2 | None
    reason: str


class Phase6LiveIntegrationV2:
    """Operational V2 facade; construction is factory-only."""

    def __init__(
        self,
        *,
        _key: object,
        identity: HostIdentityBindingV2,
        agentic_core: AgenticCoreV6,
        agentic_state: AgenticStateStoreV6,
        phase5: Phase5IntegrationV3,
        catalog: LocalCatalogReadBindingV2,
        text: CurrentTextProviderAdapterV2,
    ) -> None:
        if _key is not _CONSTRUCTION_KEY:
            raise Phase6LiveIntegrationV2Denied(
                "V2 facade requires the operational factory"
            )
        if type(agentic_state) is not AgenticStateStoreV6:
            raise Phase6LiveIntegrationV2ContractError(
                "exact AgenticStateStoreV6 is required"
            )
        if getattr(agentic_core, "_state", None) is not agentic_state:
            raise Phase6LiveIntegrationV2Denied("Agentic Core state authority diverged")
        if type(catalog) is not LocalCatalogReadBindingV2:
            raise Phase6LiveIntegrationV2ContractError(
                "exact V2 catalog binding is required"
            )
        if type(text) is not CurrentTextProviderAdapterV2:
            raise Phase6LiveIntegrationV2ContractError(
                "exact V2 text adapter is required"
            )
        self._identity = identity
        self._core = agentic_core
        self._state = agentic_state
        self._phase5 = phase5
        self._catalog = catalog
        self._text = text
        self._external = DisabledExternalAgentAdapterV1()
        self._closed = False
        self._attest()

    def _attest(self) -> None:
        self._identity.attest(self._core, self._phase5)
        self._text._attest_operational()
        self._catalog._attest()
        if self._text.binding_digest != self._identity.digest:
            raise Phase6LiveIntegrationV2Denied("text binding digest diverged")

    @property
    def identity(self) -> HostIdentityBindingV2:
        return self._identity

    @property
    def external_agent(self) -> DisabledExternalAgentAdapterV1:
        return self._external

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._attest()
        self._closed = True
        self._text.close()
        self._core.close()

    def submit(
        self,
        goal: GoalV1,
        request_key: str,
        proposed_steps: tuple[dict[str, object], ...] | list[dict[str, object]],
    ) -> PlanProjectionV1:
        if self._closed:
            raise Phase6LiveIntegrationV2Denied("V2 facade is closed")
        self._attest()
        if goal.workspace_id != self._identity.workspace_id:
            raise Phase6LiveIntegrationV2Denied(
                "goal workspace diverged from V2 identity"
            )
        return self._core.submit(goal, request_key, proposed_steps)

    def generate_text(
        self,
        request: TextProviderRequestV2,
        cancellation: live_v1.CancellationTokenV1 | None = None,
    ) -> TextProviderResultV2:
        if self._closed:
            raise Phase6LiveIntegrationV2Denied("V2 facade is closed")
        self._attest()
        return self._text.invoke(request, cancellation)

    def execute_local_catalog_plan(
        self,
        plan_id: str,
        request_id: str,
        cancellation: live_v1.CancellationTokenV1 | None = None,
    ) -> CatalogPlanResultV2:
        if self._closed:
            raise Phase6LiveIntegrationV2Denied("V2 facade is closed")
        self._attest()
        plan = self._state.get_plan(plan_id)
        ordered = plan.ordered_steps()
        if (
            plan.goal.workspace_id != self._identity.workspace_id
            or len(ordered) != 1
            or ordered[0].capability != "local_catalog_read"
        ):
            raise Phase6LiveIntegrationV2Denied(
                "V2 admits one identity-bound local_catalog_read step"
            )
        admission = self._core.materialize(plan_id)
        if admission.state is not PlanStateV1.WAITING_FOR_PHASE5:
            raise Phase6LiveIntegrationV2Denied(
                "plan did not enter the Phase 5 handoff state"
            )
        request = CatalogReadRequestV2(
            self._identity,
            live_v1.CatalogReadRequestV1(
                request_id,
                self._identity.workspace_id,
                plan.goal.data_class,
                ordered[0].arguments,
            ),
        )
        try:
            result, receipt = self._catalog.execute(request, cancellation)
        except live_v1.Phase6LiveIntegrationV1Denied:
            return CatalogPlanResultV2(
                plan_id,
                self._state.get_projection(plan_id).state,
                None,
                None,
                "catalog_cancelled_or_denied",
            )
        except live_v1.Phase6LiveIntegrationV1Unavailable:
            return CatalogPlanResultV2(
                plan_id,
                self._state.get_projection(plan_id).state,
                None,
                None,
                "catalog_unavailable_no_silent_fallback",
            )
        return CatalogPlanResultV2(
            plan_id,
            self._state.get_projection(plan_id).state,
            result,
            receipt,
            "phase5_identity_bound_read_receipted",
        )


def _derived_path(path: Path, marker: str) -> Path:
    suffix = path.suffix or ".sqlite3"
    return path.with_name(f"{path.stem}.{marker}{suffix}")


def create_phase6_live_integration_v2(
    *,
    gate: LiveIntegrationFeatureGateV2,
    identity: HostIdentityBindingV2 | None = None,
    agentic_core: AgenticCoreV6 | None = None,
    agentic_state: AgenticStateStoreV6 | None = None,
    phase5: Phase5IntegrationV3 | None = None,
    receipt_path: Path | str | None = None,
) -> Phase6LiveIntegrationV2 | None:
    """Build all operational seams internally after complete identity attestation."""

    if type(gate) is not LiveIntegrationFeatureGateV2:
        raise Phase6LiveIntegrationV2ContractError(
            "exact LiveIntegrationFeatureGateV2 is required"
        )
    if not gate.enabled:
        return None
    if (
        type(identity) is not HostIdentityBindingV2
        or type(agentic_core) is not AgenticCoreV6
        or type(agentic_state) is not AgenticStateStoreV6
        or type(phase5) is not Phase5IntegrationV3
        or receipt_path is None
    ):
        raise Phase6LiveIntegrationV2ContractError(
            "enabled V2 requires exact operational dependencies"
        )
    if getattr(agentic_core, "_state", None) is not agentic_state:
        raise Phase6LiveIntegrationV2Denied("Agentic Core state authority diverged")
    path = Path(receipt_path)
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise Phase6LiveIntegrationV2ContractError(
            "explicit absolute V2 receipt path is required"
        )
    # Full identity is attested before executor construction or filesystem writes.
    identity.attest(agentic_core, phase5)
    text = CurrentTextProviderAdapterV2.operational(identity)
    try:
        v1_receipts = live_v1.IntegrationReceiptStoreV1(_derived_path(path, "v1-base"))
        v2_receipts = IdentityReceiptStoreV2(path)
        v1_catalog = live_v1.LocalCatalogReadBindingV1(
            phase5=phase5,
            receipt_store=v1_receipts,
            maximum_data_class=DataClassV1.CONFIDENTIAL,
        )
        catalog = LocalCatalogReadBindingV2(
            _key=_CONSTRUCTION_KEY,
            identity=identity,
            agentic_core=agentic_core,
            phase5=phase5,
            delegate=v1_catalog,
            receipts=v2_receipts,
        )
        return Phase6LiveIntegrationV2(
            _key=_CONSTRUCTION_KEY,
            identity=identity,
            agentic_core=agentic_core,
            agentic_state=agentic_state,
            phase5=phase5,
            catalog=catalog,
            text=text,
        )
    except Exception:
        text.close()
        raise


__all__ = [
    "FEATURE_FLAG",
    "CatalogPlanResultV2",
    "CatalogReadReceiptV2",
    "CatalogReadRequestV2",
    "CurrentTextProviderAdapterV2",
    "HostIdentityBindingV2",
    "IdentityReceiptStoreV2",
    "LiveIntegrationFeatureGateV2",
    "LocalCatalogReadBindingV2",
    "Phase6LiveIntegrationV2",
    "Phase6LiveIntegrationV2ContractError",
    "Phase6LiveIntegrationV2Denied",
    "Phase6LiveIntegrationV2Error",
    "TextProviderRequestV2",
    "TextProviderResultV2",
    "create_phase6_live_integration_v2",
]
