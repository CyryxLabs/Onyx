"""Default-off Phase 6 V6 integration facade.

This module is deliberately additive.  It does not replace the live Gemini
path, the standalone text call sites, MissionStore, or the accepted Phase 5
bridge.  When its feature gate is off the factory returns ``None`` before
validating or constructing any dependency, leaving the current host path
untouched.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
import sqlite3
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from core.phase5_integration_v3 import (
    LOCAL_CATALOG_TOOL,
    Phase5IntegrationV3,
    Phase5IntegrationV3ContractError,
    Phase5IntegrationV3Error,
)
from core.phase6_agentic_core_v1 import (
    AdapterStatusV1,
    DataClassV1,
    DisabledExternalAgentAdapterV1,
    GoalV1,
    ModelDescriptorV1,
    ModelRouterV1,
    PlanProjectionV1,
    PlanStateV1,
    RouteRequestV1,
)
from core.phase6_agentic_core_v4 import (
    ProcessCallTimeoutV4,
    RemoteCallFailedV4,
    TerminableProcessExecutorV4,
)
from core.phase6_agentic_core_v6 import AgenticCoreV6, AgenticStateStoreV6


FEATURE_FLAG = "ONYX_PHASE6_LIVE_INTEGRATION_V1"
SCHEMA_VERSION = 1
TEXT_OUTPUT_RESERVATION = 600
MAX_RECEIPT_BYTES = 32_768
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{2,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DATA_RANK = {
    DataClassV1.PUBLIC: 0,
    DataClassV1.INTERNAL: 1,
    DataClassV1.CONFIDENTIAL: 2,
    DataClassV1.RESTRICTED: 3,
}


class Phase6LiveIntegrationV1Error(RuntimeError):
    """The isolated integration could not safely complete an operation."""


class Phase6LiveIntegrationV1ContractError(ValueError):
    """A caller supplied a non-canonical integration contract."""


class Phase6LiveIntegrationV1Denied(PermissionError):
    """Host policy denied an integration request."""


class Phase6LiveIntegrationV1Unavailable(Phase6LiveIntegrationV1Error):
    """An explicitly selected dependency was unavailable."""


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise Phase6LiveIntegrationV1ContractError(
            f"{label} must be a canonical identifier"
        )
    return value


def _text(value: object, label: str, maximum: int, *, empty: bool = False) -> str:
    if type(value) is not str or len(value.encode("utf-8")) > maximum:
        raise Phase6LiveIntegrationV1ContractError(f"{label} is invalid")
    if not empty and not value.strip():
        raise Phase6LiveIntegrationV1ContractError(f"{label} must not be empty")
    if "\x00" in value:
        raise Phase6LiveIntegrationV1ContractError(f"{label} contains NUL")
    return value


def _finite_positive(value: object, label: str, maximum: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 < float(value) <= maximum
    ):
        raise Phase6LiveIntegrationV1ContractError(f"{label} is invalid")
    return float(value)


def _canonical_json(value: object) -> str:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
    except (TypeError, ValueError) as exc:
        raise Phase6LiveIntegrationV1ContractError(
            "value is not canonical JSON"
        ) from exc
    if len(encoded.encode("utf-8")) > MAX_RECEIPT_BYTES:
        raise Phase6LiveIntegrationV1ContractError("canonical value is too large")
    return encoded


def _sha(value: object) -> str:
    if isinstance(value, bytes):
        payload = value
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = _canonical_json(value).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _exact_mapping(value: object, label: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise Phase6LiveIntegrationV1ContractError(
            f"{label} must be a plain string-keyed mapping"
        )
    return dict(value)


def _local_endpoint(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.hostname is None
        ):
            return False
        host = parsed.hostname.rstrip(".").lower()
        if host == "localhost":
            return True
        return ipaddress.ip_address(host).is_loopback
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True, slots=True)
class LiveIntegrationFeatureGateV1:
    enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise Phase6LiveIntegrationV1ContractError(
                "integration gate must be an exact boolean"
            )

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "LiveIntegrationFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


class CancellationTokenV1:
    """Thread-safe host cancellation latch."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True, slots=True)
class TextProviderConfigV1:
    provider: str
    base_url: str
    model: str

    def __post_init__(self) -> None:
        if self.provider not in {"ollama", "openai"}:
            raise Phase6LiveIntegrationV1ContractError(
                "text provider must be ollama or openai"
            )
        _text(self.base_url, "base_url", 2_048)
        _text(self.model, "model", 512)

    @property
    def local_private(self) -> bool:
        return _local_endpoint(self.base_url)

    @property
    def digest(self) -> str:
        return _sha(
            {
                "provider": self.provider,
                "base_url": self.base_url.rstrip("/"),
                "model": self.model,
            }
        )


@dataclass(frozen=True, slots=True)
class TextProviderBudgetV1:
    wall_seconds: float
    max_api_calls: int = 1
    max_output_tokens: int = TEXT_OUTPUT_RESERVATION
    max_cost_micro: int = 0

    def __post_init__(self) -> None:
        _finite_positive(self.wall_seconds, "wall_seconds", 3_600.0)
        if type(self.max_api_calls) is not int or self.max_api_calls != 1:
            raise Phase6LiveIntegrationV1ContractError(
                "V1 text adapter admits exactly one provider call"
            )
        if (
            type(self.max_output_tokens) is not int
            or self.max_output_tokens < TEXT_OUTPUT_RESERVATION
            or self.max_output_tokens > 10_000_000
        ):
            raise Phase6LiveIntegrationV1ContractError(
                "text budget must reserve the current client's 600-token ceiling"
            )
        if type(self.max_cost_micro) is not int or self.max_cost_micro != 0:
            raise Phase6LiveIntegrationV1ContractError(
                "V1 text adapter admits only zero-cost local routes"
            )


@dataclass(frozen=True, slots=True)
class TextProviderRequestV1:
    request_id: str
    workspace_id: str
    data_class: DataClassV1
    prompt: str
    system: str | None
    budget: TextProviderBudgetV1

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        _identifier(self.workspace_id, "workspace_id")
        if type(self.data_class) is not DataClassV1:
            raise Phase6LiveIntegrationV1ContractError(
                "data_class must be exact DataClassV1"
            )
        _text(self.prompt, "prompt", 64_000)
        if self.system is not None:
            _text(self.system, "system", 64_000)
        if type(self.budget) is not TextProviderBudgetV1:
            raise Phase6LiveIntegrationV1ContractError(
                "budget must be exact TextProviderBudgetV1"
            )

    @property
    def digest(self) -> str:
        return _sha(
            {
                "request_id": self.request_id,
                "workspace_id": self.workspace_id,
                "data_class": self.data_class.value,
                "prompt_digest": _sha(self.prompt),
                "system_digest": None if self.system is None else _sha(self.system),
                "budget": {
                    "wall_seconds": self.budget.wall_seconds,
                    "max_api_calls": self.budget.max_api_calls,
                    "max_output_tokens": self.budget.max_output_tokens,
                    "max_cost_micro": self.budget.max_cost_micro,
                },
            }
        )


@dataclass(frozen=True, slots=True)
class TextProviderResultV1:
    request_id: str
    status: str
    content: str
    adapter_id: str
    provider_config_digest: str
    request_digest: str
    content_digest: str
    reserved_output_tokens: int
    provider_calls: int
    elapsed_millis: int
    reason: str
    receipt_digest: str

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        if self.status not in {
            "completed",
            "cancelled",
            "timed_out",
            "unavailable",
            "blocked",
        }:
            raise Phase6LiveIntegrationV1ContractError("text result status is invalid")
        _text(self.content, "content", 256_000, empty=True)
        _identifier(self.adapter_id, "adapter_id")
        for digest in (
            self.provider_config_digest,
            self.request_digest,
            self.content_digest,
            self.receipt_digest,
        ):
            if type(digest) is not str or _SHA256.fullmatch(digest) is None:
                raise Phase6LiveIntegrationV1ContractError(
                    "text result digest is invalid"
                )
        if (
            type(self.reserved_output_tokens) is not int
            or self.reserved_output_tokens not in {0, TEXT_OUTPUT_RESERVATION}
            or type(self.provider_calls) is not int
            or self.provider_calls not in {0, 1}
            or type(self.elapsed_millis) is not int
            or self.elapsed_millis < 0
        ):
            raise Phase6LiveIntegrationV1ContractError(
                "text result accounting is invalid"
            )
        _identifier(self.reason, "reason")

    def receipt_payload(self) -> dict[str, object]:
        """Return provenance without prompt, system, content, URL, model, or errors."""

        return {
            "schema": "OnyxPhase6TextReceipt.v1",
            "request_id": self.request_id,
            "status": self.status,
            "adapter_id": self.adapter_id,
            "provider_config_digest": self.provider_config_digest,
            "request_digest": self.request_digest,
            "content_digest": self.content_digest,
            "reserved_output_tokens": self.reserved_output_tokens,
            "provider_calls": self.provider_calls,
            "elapsed_millis": self.elapsed_millis,
            "reason": self.reason,
        }


class TextCallV1(Protocol):
    def __call__(
        self,
        prompt: str,
        system: str | None,
        model: str,
        timeout: int,
        provider: str,
        base_url: str,
    ) -> str: ...


def _current_llm_text_call(
    prompt: str,
    system: str | None,
    model: str,
    timeout: int,
    provider: str,
    base_url: str,
) -> str:
    # The dedicated child pins the characterized configuration so a later
    # config-file change cannot cross an already-authorized route.
    from core import llm_client
    from core.llm_client import call_llm_text

    original_provider = llm_client.get_llm_provider
    original_settings = llm_client.get_llm_settings
    llm_client.get_llm_provider = lambda: provider
    llm_client.get_llm_settings = lambda: (base_url, model)
    try:
        return call_llm_text(prompt, system=system, model=model, timeout=timeout)
    finally:
        llm_client.get_llm_provider = original_provider
        llm_client.get_llm_settings = original_settings


def _current_llm_config() -> TextProviderConfigV1:
    # Lazy import prevents default-off construction from touching config or network.
    from core.llm_client import get_llm_provider, get_llm_settings

    base_url, model = get_llm_settings()
    return TextProviderConfigV1(get_llm_provider(), base_url, model)


class CurrentTextProviderAdapterV1:
    """Process-bounded adapter over the unchanged ``core.llm_client`` text seam."""

    adapter_id = "current_local_text_v1"

    def __init__(
        self,
        *,
        workspace_id: str,
        config: TextProviderConfigV1,
        invoke: TextCallV1 = _current_llm_text_call,
        maximum_data_class: DataClassV1 = DataClassV1.CONFIDENTIAL,
        reliability_milli: int = 900,
        latency_millis: int = 120_000,
        executor: TerminableProcessExecutorV4 | None = None,
    ) -> None:
        self._workspace_id = _identifier(workspace_id, "workspace_id")
        if type(config) is not TextProviderConfigV1:
            raise Phase6LiveIntegrationV1ContractError(
                "config must be exact TextProviderConfigV1"
            )
        if not callable(invoke):
            raise Phase6LiveIntegrationV1ContractError("text invoker is invalid")
        if type(maximum_data_class) is not DataClassV1:
            raise Phase6LiveIntegrationV1ContractError(
                "maximum_data_class must be exact"
            )
        if (
            type(reliability_milli) is not int
            or not 0 <= reliability_milli <= 1_000
            or type(latency_millis) is not int
            or not 0 <= latency_millis <= 3_600_000
        ):
            raise Phase6LiveIntegrationV1ContractError(
                "descriptor measurements are invalid"
            )
        self._config = config
        self._invoke = invoke
        self._maximum_data_class = maximum_data_class
        self._executor = executor or TerminableProcessExecutorV4()
        self._closed = False
        self._lock = threading.Lock()
        status = (
            AdapterStatusV1.AVAILABLE_LOCAL
            if config.local_private
            else AdapterStatusV1.BLOCKED_BY_POLICY
        )
        self._descriptor = ModelDescriptorV1(
            self.adapter_id,
            status,
            ("text",),
            maximum_data_class,
            (self._workspace_id,),
            config.local_private,
            not config.local_private,
            False,
            reliability_milli,
            latency_millis,
            0,
        )

    @classmethod
    def from_current_client(
        cls,
        *,
        workspace_id: str,
        maximum_data_class: DataClassV1 = DataClassV1.CONFIDENTIAL,
    ) -> "CurrentTextProviderAdapterV1":
        return cls(
            workspace_id=workspace_id,
            config=_current_llm_config(),
            maximum_data_class=maximum_data_class,
        )

    @property
    def descriptor(self) -> ModelDescriptorV1:
        return self._descriptor

    @property
    def config_digest(self) -> str:
        return self._config.digest

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._executor.close()

    def _result(
        self,
        request: TextProviderRequestV1,
        *,
        status: str,
        content: str = "",
        provider_calls: int = 0,
        elapsed_millis: int = 0,
        reason: str,
    ) -> TextProviderResultV1:
        content_digest = _sha(content)
        receipt = {
            "schema": "OnyxPhase6TextReceipt.v1",
            "request_id": request.request_id,
            "status": status,
            "adapter_id": self.adapter_id,
            "provider_config_digest": self.config_digest,
            "request_digest": request.digest,
            "content_digest": content_digest,
            "reserved_output_tokens": (
                TEXT_OUTPUT_RESERVATION if provider_calls else 0
            ),
            "provider_calls": provider_calls,
            "elapsed_millis": elapsed_millis,
            "reason": reason,
        }
        return TextProviderResultV1(
            request.request_id,
            status,
            content,
            self.adapter_id,
            self.config_digest,
            request.digest,
            content_digest,
            TEXT_OUTPUT_RESERVATION if provider_calls else 0,
            provider_calls,
            elapsed_millis,
            reason,
            _sha(receipt),
        )

    def invoke(
        self,
        request: TextProviderRequestV1,
        cancellation: CancellationTokenV1 | None = None,
    ) -> TextProviderResultV1:
        if type(request) is not TextProviderRequestV1:
            raise Phase6LiveIntegrationV1ContractError(
                "request must be exact TextProviderRequestV1"
            )
        if cancellation is not None and type(cancellation) is not CancellationTokenV1:
            raise Phase6LiveIntegrationV1ContractError("cancellation token is invalid")
        if self._closed:
            return self._result(request, status="unavailable", reason="adapter_closed")
        if request.workspace_id != self._workspace_id:
            return self._result(
                request, status="blocked", reason="workspace_policy_denied"
            )
        if _DATA_RANK[request.data_class] > _DATA_RANK[self._maximum_data_class]:
            return self._result(
                request, status="blocked", reason="privacy_class_denied"
            )
        if self._descriptor.status is not AdapterStatusV1.AVAILABLE_LOCAL:
            return self._result(
                request, status="blocked", reason="nonlocal_provider_denied"
            )
        if cancellation is not None and cancellation.cancelled:
            return self._result(
                request, status="cancelled", reason="cancelled_before_dispatch"
            )
        router = ModelRouterV1((self._descriptor,))
        decision = router.route(
            RouteRequestV1(
                request.workspace_id,
                request.data_class,
                "text",
                True,
                False,
                min(3_600_000, int(request.budget.wall_seconds * 1_000)),
                request.budget.max_cost_micro,
                0,
            )
        )
        if decision.adapter_id != self.adapter_id:
            return self._result(
                request, status="blocked", reason="privacy_hard_route_blocked"
            )
        started = time.monotonic()
        timeout = max(1, int(math.ceil(request.budget.wall_seconds)))
        try:
            content = self._executor.invoke(
                self._invoke,
                request.budget.wall_seconds,
                request.prompt,
                request.system,
                self._config.model,
                timeout,
                self._config.provider,
                self._config.base_url,
            )
            if type(content) is not str:
                raise Phase6LiveIntegrationV1Unavailable(
                    "provider returned non-text content"
                )
            _text(content, "provider content", 256_000, empty=True)
        except ProcessCallTimeoutV4:
            elapsed = max(0, int((time.monotonic() - started) * 1_000))
            return self._result(
                request,
                status="timed_out",
                provider_calls=1,
                elapsed_millis=elapsed,
                reason="provider_deadline_exhausted",
            )
        except (RemoteCallFailedV4, Phase6LiveIntegrationV1Unavailable):
            elapsed = max(0, int((time.monotonic() - started) * 1_000))
            return self._result(
                request,
                status="unavailable",
                provider_calls=1,
                elapsed_millis=elapsed,
                reason="provider_call_unavailable",
            )
        except Exception:
            elapsed = max(0, int((time.monotonic() - started) * 1_000))
            return self._result(
                request,
                status="unavailable",
                provider_calls=1,
                elapsed_millis=elapsed,
                reason="provider_call_unavailable",
            )
        elapsed = max(0, int((time.monotonic() - started) * 1_000))
        # A completed provider call is authoritative even if cancellation raced it.
        reason = (
            "completed_after_cancel_observed"
            if cancellation is not None and cancellation.cancelled
            else "completed"
        )
        return self._result(
            request,
            status="completed",
            content=content,
            provider_calls=1,
            elapsed_millis=elapsed,
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class CatalogReadRequestV1:
    request_id: str
    workspace_id: str
    data_class: DataClassV1
    arguments: dict[str, object]

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        _identifier(self.workspace_id, "workspace_id")
        if type(self.data_class) is not DataClassV1:
            raise Phase6LiveIntegrationV1ContractError(
                "data_class must be exact DataClassV1"
            )
        arguments = _exact_mapping(self.arguments, "catalog arguments")
        if set(arguments) - {"page_size", "cursor"}:
            raise Phase6LiveIntegrationV1ContractError(
                "catalog arguments exceed the exact read-only schema"
            )
        page_size = arguments.get("page_size", 25)
        cursor = arguments.get("cursor")
        if type(page_size) is not int or not 1 <= page_size <= 50:
            raise Phase6LiveIntegrationV1ContractError(
                "catalog page_size must be 1 through 50"
            )
        if cursor is not None and (type(cursor) is not str or len(cursor) > 2_048):
            raise Phase6LiveIntegrationV1ContractError("catalog cursor is invalid")

    @property
    def normalized_arguments(self) -> dict[str, object]:
        return {
            "cursor": self.arguments.get("cursor"),
            "page_size": self.arguments.get("page_size", 25),
        }

    @property
    def digest(self) -> str:
        return _sha(
            {
                "request_id": self.request_id,
                "workspace_id": self.workspace_id,
                "data_class": self.data_class.value,
                "arguments": self.normalized_arguments,
            }
        )


@dataclass(frozen=True, slots=True)
class CatalogReadReceiptV1:
    request_id: str
    request_digest: str
    workspace_id: str
    status: str
    phase5_receipt_digest: str
    result_digest: str
    item_count: int
    next_cursor_digest: str | None
    cost_micro: int
    egress: str
    reason: str
    receipt_digest: str

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        _identifier(self.workspace_id, "workspace_id")
        if self.status != "completed":
            raise Phase6LiveIntegrationV1ContractError(
                "only completed catalog receipts are durable"
            )
        for digest in (
            self.request_digest,
            self.phase5_receipt_digest,
            self.result_digest,
            self.receipt_digest,
        ):
            if type(digest) is not str or _SHA256.fullmatch(digest) is None:
                raise Phase6LiveIntegrationV1ContractError(
                    "catalog receipt digest is invalid"
                )
        if self.next_cursor_digest is not None and (
            type(self.next_cursor_digest) is not str
            or _SHA256.fullmatch(self.next_cursor_digest) is None
        ):
            raise Phase6LiveIntegrationV1ContractError("next cursor digest is invalid")
        if type(self.item_count) is not int or not 0 <= self.item_count <= 50:
            raise Phase6LiveIntegrationV1ContractError("catalog item count is invalid")
        if type(self.cost_micro) is not int or self.cost_micro != 0:
            raise Phase6LiveIntegrationV1ContractError(
                "catalog receipt cost must be zero"
            )
        if self.egress != "none":
            raise Phase6LiveIntegrationV1ContractError(
                "catalog receipt egress must be none"
            )
        _identifier(self.reason, "reason")

    def payload(self) -> dict[str, object]:
        return {
            "schema": "OnyxPhase6CatalogReceipt.v1",
            "request_id": self.request_id,
            "request_digest": self.request_digest,
            "workspace_id": self.workspace_id,
            "status": self.status,
            "phase5_receipt_digest": self.phase5_receipt_digest,
            "result_digest": self.result_digest,
            "item_count": self.item_count,
            "next_cursor_digest": self.next_cursor_digest,
            "cost_micro": self.cost_micro,
            "egress": self.egress,
            "reason": self.reason,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "CatalogReadReceiptV1":
        data = dict(payload)
        if data.pop("schema", None) != "OnyxPhase6CatalogReceipt.v1":
            raise Phase6LiveIntegrationV1Error("catalog receipt schema is invalid")
        receipt_digest = data.pop("receipt_digest", None)
        candidate = cls(receipt_digest=str(receipt_digest), **data)  # type: ignore[arg-type]
        if candidate.receipt_digest != _sha(candidate.payload()):
            raise Phase6LiveIntegrationV1Error("catalog receipt digest mismatch")
        return candidate


class IntegrationReceiptStoreV1:
    """Minimal additive store for Phase 5 execution receipts only."""

    _DDL = (
        "CREATE TABLE metadata(schema_version INTEGER NOT NULL)",
        "CREATE TABLE catalog_receipts("
        "request_id TEXT PRIMARY KEY,"
        "request_digest TEXT NOT NULL,"
        "receipt_json TEXT NOT NULL,"
        "created_at REAL NOT NULL"
        ")",
        "CREATE TRIGGER catalog_receipts_no_update BEFORE UPDATE ON catalog_receipts "
        "BEGIN SELECT RAISE(ABORT,'phase6 integration receipts are immutable'); END",
        "CREATE TRIGGER catalog_receipts_no_delete BEFORE DELETE ON catalog_receipts "
        "BEGIN SELECT RAISE(ABORT,'phase6 integration receipts are immutable'); END",
    )

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        if not self._path.is_absolute() or self._path.name in {"", ".", ".."}:
            raise Phase6LiveIntegrationV1ContractError(
                "an explicit absolute receipt-store path is required"
            )
        self._lock = threading.RLock()
        self._expected = self._expected_inventory()
        self._initialize()

    @property
    def path(self) -> Path:
        return self._path

    @classmethod
    def _expected_inventory(cls) -> str:
        connection = sqlite3.connect(":memory:")
        try:
            for statement in cls._DDL:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO metadata(schema_version) VALUES(?)", (SCHEMA_VERSION,)
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
        tables = [str(row[1]) for row in objects if row[0] == "table"]
        payload: dict[str, object] = {
            "objects": objects,
            "user_version": int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            ),
        }
        for table in tables:
            payload[f"table_xinfo:{table}"] = [
                tuple(row)
                for row in connection.execute(f"PRAGMA table_xinfo('{table}')")
            ]
            payload[f"index_list:{table}"] = [
                tuple(row)
                for row in connection.execute(f"PRAGMA index_list('{table}')")
            ]
        return _sha(payload)

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
                raise Phase6LiveIntegrationV1Error(
                    "integration receipt schema authentication failed"
                )
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def get(self, request_id: str) -> CatalogReadReceiptV1 | None:
        canonical = _identifier(request_id, "request_id")
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
            raise Phase6LiveIntegrationV1Error("stored receipt is malformed")
        return CatalogReadReceiptV1.from_payload(payload)

    def put(self, receipt: CatalogReadReceiptV1) -> tuple[CatalogReadReceiptV1, bool]:
        if type(receipt) is not CatalogReadReceiptV1:
            raise Phase6LiveIntegrationV1ContractError(
                "receipt must be exact CatalogReadReceiptV1"
            )
        payload = receipt.payload() | {"receipt_digest": receipt.receipt_digest}
        encoded = _canonical_json(payload)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT request_digest,receipt_json FROM catalog_receipts "
                    "WHERE request_id=?",
                    (receipt.request_id,),
                ).fetchone()
                if row is not None:
                    existing_payload = json.loads(str(row["receipt_json"]))
                    existing = CatalogReadReceiptV1.from_payload(existing_payload)
                    if (
                        str(row["request_digest"]) != receipt.request_digest
                        or existing != receipt
                    ):
                        raise Phase6LiveIntegrationV1Denied(
                            "request_id is already bound to another immutable receipt"
                        )
                    connection.execute("COMMIT")
                    return existing, False
                connection.execute(
                    "INSERT INTO catalog_receipts VALUES(?,?,?,?)",
                    (
                        receipt.request_id,
                        receipt.request_digest,
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


class LocalCatalogReadBindingV1:
    """Exact read-only Phase 5 binding; no generic executor exists here."""

    def __init__(
        self,
        *,
        phase5: Phase5IntegrationV3,
        receipt_store: IntegrationReceiptStoreV1,
        maximum_data_class: DataClassV1 = DataClassV1.CONFIDENTIAL,
    ) -> None:
        if type(phase5) is not Phase5IntegrationV3:
            raise Phase6LiveIntegrationV1ContractError(
                "exact accepted Phase5IntegrationV3 is required"
            )
        if type(receipt_store) is not IntegrationReceiptStoreV1:
            raise Phase6LiveIntegrationV1ContractError(
                "exact IntegrationReceiptStoreV1 is required"
            )
        if type(maximum_data_class) is not DataClassV1:
            raise Phase6LiveIntegrationV1ContractError(
                "maximum_data_class must be exact"
            )
        self._phase5 = phase5
        self._receipts = receipt_store
        self._maximum_data_class = maximum_data_class
        self._lock = threading.RLock()

    @property
    def workspace_id(self) -> str:
        return self._phase5.binding.workspace_id

    def execute(
        self,
        request: CatalogReadRequestV1,
        cancellation: CancellationTokenV1 | None = None,
    ) -> tuple[dict[str, object], CatalogReadReceiptV1]:
        if type(request) is not CatalogReadRequestV1:
            raise Phase6LiveIntegrationV1ContractError(
                "request must be exact CatalogReadRequestV1"
            )
        if cancellation is not None and type(cancellation) is not CancellationTokenV1:
            raise Phase6LiveIntegrationV1ContractError("cancellation token is invalid")
        if request.workspace_id != self.workspace_id:
            raise Phase6LiveIntegrationV1Denied("catalog workspace policy denied")
        if _DATA_RANK[request.data_class] > _DATA_RANK[self._maximum_data_class]:
            raise Phase6LiveIntegrationV1Denied("catalog privacy class policy denied")
        if cancellation is not None and cancellation.cancelled:
            raise Phase6LiveIntegrationV1Denied(
                "catalog request cancelled before authorization"
            )
        with self._lock:
            prior = self._receipts.get(request.request_id)
            if prior is not None:
                if prior.request_digest != request.digest:
                    raise Phase6LiveIntegrationV1Denied(
                        "catalog request_id replay changed immutable input"
                    )
                return {"replayed": True}, prior
            if not self._phase5.local_catalog_enabled:
                raise Phase6LiveIntegrationV1Unavailable(
                    "accepted Phase 5 local catalog is unavailable"
                )
            invocation_ref = f"p6-{request.digest[:16]}"
            permission_arguments = request.normalized_arguments | {
                "_phase5_invocation_ref": invocation_ref
            }
            decision = self._phase5.permission_hook(
                LOCAL_CATALOG_TOOL, permission_arguments
            )
            if decision is None or not decision[0]:
                raise Phase6LiveIntegrationV1Denied(
                    "Phase 5 catalog authorization denied"
                )
            # Once authorized, dispatch is completed and receipted even if cancel races.
            try:
                result = self._phase5.catalog_read(
                    invocation_ref, request.normalized_arguments
                )
            except (Phase5IntegrationV3Error, Phase5IntegrationV3ContractError) as exc:
                raise Phase6LiveIntegrationV1Unavailable(
                    "Phase 5 catalog dispatch unavailable"
                ) from exc
            if (
                result.get("capability") != "local.catalog"
                or result.get("operation") != "catalog_read"
                or result.get("state") != "completed"
                or result.get("cost_micro") != 0
                or result.get("egress") != "none"
                or type(result.get("items")) is not list
                or type(result.get("receipt_digest")) is not str
                or _SHA256.fullmatch(str(result["receipt_digest"])) is None
            ):
                raise Phase6LiveIntegrationV1Unavailable(
                    "Phase 5 catalog result failed the exact receipt schema"
                )
            next_cursor = result.get("next_cursor")
            if next_cursor is not None and type(next_cursor) is not str:
                raise Phase6LiveIntegrationV1Unavailable(
                    "Phase 5 catalog cursor schema is invalid"
                )
            receipt_payload = {
                "schema": "OnyxPhase6CatalogReceipt.v1",
                "request_id": request.request_id,
                "request_digest": request.digest,
                "workspace_id": request.workspace_id,
                "status": "completed",
                "phase5_receipt_digest": str(result["receipt_digest"]),
                "result_digest": _sha(result),
                "item_count": len(result["items"]),
                "next_cursor_digest": (
                    None if next_cursor is None else _sha(next_cursor)
                ),
                "cost_micro": 0,
                "egress": "none",
                "reason": (
                    "completed_after_cancel_observed"
                    if cancellation is not None and cancellation.cancelled
                    else "completed"
                ),
            }
            receipt = CatalogReadReceiptV1(
                request_id=request.request_id,
                request_digest=request.digest,
                workspace_id=request.workspace_id,
                status="completed",
                phase5_receipt_digest=str(result["receipt_digest"]),
                result_digest=str(receipt_payload["result_digest"]),
                item_count=int(receipt_payload["item_count"]),
                next_cursor_digest=receipt_payload["next_cursor_digest"],  # type: ignore[arg-type]
                cost_micro=0,
                egress="none",
                reason=str(receipt_payload["reason"]),
                receipt_digest=_sha(receipt_payload),
            )
            stored, _ = self._receipts.put(receipt)
            return dict(result), stored


@dataclass(frozen=True, slots=True)
class CatalogPlanResultV1:
    plan_id: str
    state: PlanStateV1
    result: dict[str, object] | None
    receipt: CatalogReadReceiptV1 | None
    reason: str


class Phase6LiveIntegrationV1:
    """Facade joining accepted V6 planning to one accepted Phase 5 read seam."""

    def __init__(
        self,
        *,
        agentic_core: AgenticCoreV6,
        agentic_state: AgenticStateStoreV6,
        catalog: LocalCatalogReadBindingV1,
        text: CurrentTextProviderAdapterV1,
    ) -> None:
        if type(agentic_core) is not AgenticCoreV6:
            raise Phase6LiveIntegrationV1ContractError(
                "exact accepted AgenticCoreV6 is required"
            )
        if type(agentic_state) is not AgenticStateStoreV6:
            raise Phase6LiveIntegrationV1ContractError(
                "exact accepted AgenticStateStoreV6 is required"
            )
        if getattr(agentic_core, "_state", None) is not agentic_state:
            raise Phase6LiveIntegrationV1ContractError(
                "agentic core and state authority do not match"
            )
        if type(catalog) is not LocalCatalogReadBindingV1:
            raise Phase6LiveIntegrationV1ContractError(
                "exact local catalog binding is required"
            )
        if type(text) is not CurrentTextProviderAdapterV1:
            raise Phase6LiveIntegrationV1ContractError(
                "exact current text adapter is required"
            )
        if (
            getattr(agentic_core, "_workspace", None).workspace_id
            != catalog.workspace_id
        ):
            raise Phase6LiveIntegrationV1ContractError(
                "Phase 6 and Phase 5 workspace authorities differ"
            )
        if text.descriptor.workspace_allowlist != (catalog.workspace_id,):
            raise Phase6LiveIntegrationV1ContractError(
                "text and catalog workspace authorities differ"
            )
        self._core = agentic_core
        self._state = agentic_state
        self._catalog = catalog
        self._text = text
        self._external_agent = DisabledExternalAgentAdapterV1()
        self._closed = False

    @property
    def external_agent(self) -> DisabledExternalAgentAdapterV1:
        return self._external_agent

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._text.close()
        self._core.close()

    def generate_text(
        self,
        request: TextProviderRequestV1,
        cancellation: CancellationTokenV1 | None = None,
    ) -> TextProviderResultV1:
        if self._closed:
            raise Phase6LiveIntegrationV1Denied("integration is closed")
        return self._text.invoke(request, cancellation)

    def submit(
        self,
        goal: GoalV1,
        request_key: str,
        proposed_steps: tuple[dict[str, object], ...] | list[dict[str, object]],
    ) -> PlanProjectionV1:
        if self._closed:
            raise Phase6LiveIntegrationV1Denied("integration is closed")
        return self._core.submit(goal, request_key, proposed_steps)

    def execute_local_catalog_plan(
        self,
        plan_id: str,
        request_id: str,
        cancellation: CancellationTokenV1 | None = None,
    ) -> CatalogPlanResultV1:
        if self._closed:
            raise Phase6LiveIntegrationV1Denied("integration is closed")
        plan = self._state.get_plan(plan_id)
        ordered = plan.ordered_steps()
        if len(ordered) != 1 or ordered[0].capability != "local_catalog_read":
            raise Phase6LiveIntegrationV1Denied(
                "V1 live binding admits exactly one local_catalog_read step"
            )
        admission = self._core.materialize(plan_id)
        if admission.state is not PlanStateV1.WAITING_FOR_PHASE5:
            raise Phase6LiveIntegrationV1Denied(
                "plan did not enter the accepted Phase 5 handoff state"
            )
        request = CatalogReadRequestV1(
            request_id,
            plan.goal.workspace_id,
            plan.goal.data_class,
            ordered[0].arguments,
        )
        try:
            result, receipt = self._catalog.execute(request, cancellation)
        except Phase6LiveIntegrationV1Denied:
            projection = self._state.get_projection(plan_id)
            return CatalogPlanResultV1(
                plan_id,
                projection.state,
                None,
                None,
                "catalog_cancelled_or_denied",
            )
        except Phase6LiveIntegrationV1Unavailable:
            projection = self._state.get_projection(plan_id)
            return CatalogPlanResultV1(
                plan_id,
                projection.state,
                None,
                None,
                "catalog_unavailable_no_silent_fallback",
            )
        projection = self._state.get_projection(plan_id)
        return CatalogPlanResultV1(
            plan_id,
            projection.state,
            result,
            receipt,
            "phase5_authoritative_read_receipted",
        )


def create_phase6_live_integration_v1(
    *,
    gate: LiveIntegrationFeatureGateV1,
    agentic_core: AgenticCoreV6 | None = None,
    agentic_state: AgenticStateStoreV6 | None = None,
    catalog: LocalCatalogReadBindingV1 | None = None,
    text: CurrentTextProviderAdapterV1 | None = None,
) -> Phase6LiveIntegrationV1 | None:
    """Return ``None`` without dependency work when the extension is disabled."""

    if type(gate) is not LiveIntegrationFeatureGateV1:
        raise Phase6LiveIntegrationV1ContractError(
            "gate must be exact LiveIntegrationFeatureGateV1"
        )
    if not gate.enabled:
        return None
    if agentic_core is None or agentic_state is None or catalog is None or text is None:
        raise Phase6LiveIntegrationV1ContractError(
            "enabled integration requires all exact dependencies"
        )
    return Phase6LiveIntegrationV1(
        agentic_core=agentic_core,
        agentic_state=agentic_state,
        catalog=catalog,
        text=text,
    )


__all__ = [
    "FEATURE_FLAG",
    "CancellationTokenV1",
    "CatalogPlanResultV1",
    "CatalogReadReceiptV1",
    "CatalogReadRequestV1",
    "CurrentTextProviderAdapterV1",
    "IntegrationReceiptStoreV1",
    "LiveIntegrationFeatureGateV1",
    "LocalCatalogReadBindingV1",
    "Phase6LiveIntegrationV1",
    "Phase6LiveIntegrationV1ContractError",
    "Phase6LiveIntegrationV1Denied",
    "Phase6LiveIntegrationV1Error",
    "Phase6LiveIntegrationV1Unavailable",
    "TextProviderBudgetV1",
    "TextProviderConfigV1",
    "TextProviderRequestV1",
    "TextProviderResultV1",
    "create_phase6_live_integration_v1",
]
