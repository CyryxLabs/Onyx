"""Host-owned adapters from accepted Phase 5 components to a runtime protocol.

This module is deliberately isolated from every live/startup surface and from
every versioned ``phase5_runtime_*`` candidate.  Runtime value constructors are
injected by the host, which keeps this adapter usable by a later compatible
runtime without importing or blessing that runtime here.

The adapters are projections only.  They cannot approve, grant, dispatch,
execute, persist, poll, or start worker threads.  Any missing, malformed,
cross-boundary, stale, or unhealthy dependency fails closed.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


ADAPTER_CONTRACT_V1 = "onyx.phase5-component-adapters.v1"
GRANTS_ACCEPTANCE_V1 = "VE-P51-GRANTS-R11-E6-001"
NEXUS_ACCEPTANCE_V1 = "VE-P53-CAPABILITY-NEXUS-V32-E6-001"
INBOX_ACCEPTANCE_V1 = "VE-P52-APPROVAL-INBOX-V15-E6-001"

MAX_ITEMS_V1 = 128
MAX_PAGE_SIZE_V1 = 50
MAX_CURSOR_BYTES_V1 = 128
MAX_ADVISORY_BYTES_V1 = 512
MAX_CURSOR_SEQUENCE_V1 = 9_999_999

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_RISKS = frozenset({"low", "medium", "high", "critical"})
_NEXUS_STATUS = {
    "available_read_only": "available",
    "degraded": "degraded",
    "blocked_by_access": "blocked",
    "blocked_by_scope": "blocked",
    "blocked_by_platform": "blocked",
    "blocked_by_license": "blocked",
    "disabled": "disabled",
}
_TERMINAL_REASONS = frozenset(
    {"kill", "revoke", "rollback", "end_session", "reconnect", "shutdown"}
)
_CATALOG_LIMITATION = (
    "metadata_allowlisted;read_only;provider_free;effect_none;egress_none;"
    "cost_micro_0;dispatch_unavailable"
)


class Phase5ComponentAdapterV1Error(RuntimeError):
    """An adapter cannot safely project its accepted component."""


class Phase5ComponentAdapterV1ContractError(ValueError):
    """Host input violated the closed adapter contract."""


class RuntimeBatchFactoryV1(Protocol):
    def __call__(
        self,
        items: tuple[Mapping[str, object], ...],
        *,
        replace: bool,
        source_cursor: str | None,
        next_cursor: str | None,
    ) -> object: ...


class RuntimeComponentsFactoryV1(Protocol):
    def __call__(self, **components: object) -> object: ...


def _bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise Phase5ComponentAdapterV1ContractError(f"{label} must be an exact boolean")
    return value


def _safe_id(value: object, label: str) -> str:
    if type(value) is not str or not _SAFE_ID.fullmatch(value):
        raise Phase5ComponentAdapterV1ContractError(f"{label} is invalid")
    return value


def _text(value: object, label: str, maximum: int) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > maximum
    ):
        raise Phase5ComponentAdapterV1ContractError(f"{label} is invalid")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise Phase5ComponentAdapterV1ContractError(f"{label} is invalid")
    return value


def _enum_value(value: object, label: str) -> str:
    raw = getattr(value, "value", value)
    if type(raw) is not str or not raw:
        raise Phase5ComponentAdapterV1ContractError(f"{label} is invalid")
    return raw


def _callable_member(value: object, name: str) -> Callable[..., object]:
    member = getattr(value, name, None)
    if not callable(member):
        raise Phase5ComponentAdapterV1ContractError(f"component lacks callable {name}")
    return member


@dataclass(frozen=True, slots=True)
class AdapterFlagsV1:
    adapters: bool = False
    grant_shadow: bool = False
    nexus_projection: bool = False
    approval_inbox: bool = False

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            _bool(getattr(self, name), name)
        if not self.adapters and any(
            (self.grant_shadow, self.nexus_projection, self.approval_inbox)
        ):
            raise Phase5ComponentAdapterV1ContractError(
                "component flags require the adapter master flag"
            )


@dataclass(frozen=True, slots=True)
class AcceptedComponentsV1:
    grants: str | None = None
    nexus: str | None = None
    inbox: str | None = None

    def require(self, name: str) -> None:
        expected = {
            "grants": GRANTS_ACCEPTANCE_V1,
            "nexus": NEXUS_ACCEPTANCE_V1,
            "inbox": INBOX_ACCEPTANCE_V1,
        }[name]
        if getattr(self, name) != expected:
            raise Phase5ComponentAdapterV1ContractError(
                f"{name} component lacks the exact accepted checkpoint"
            )


@dataclass(frozen=True, slots=True)
class AdapterBindingV1:
    trace_id: str
    session_id: str
    workspace_id: str
    account_id: str
    profile_id: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _safe_id(getattr(self, name), name))

    @classmethod
    def from_runtime(cls, value: object) -> AdapterBindingV1:
        try:
            return cls(
                getattr(value, "trace_id"),
                getattr(value, "session_id"),
                getattr(value, "workspace_id"),
                getattr(value, "account_id"),
                getattr(value, "profile_id"),
            )
        except (AttributeError, TypeError) as exc:
            raise Phase5ComponentAdapterV1ContractError(
                "runtime binding is malformed"
            ) from exc


class _BindingGuardV1:
    __slots__ = ("_attestor", "_binding")

    def __init__(self, binding: AdapterBindingV1, attestor: Callable[[], object]) -> None:
        if not callable(attestor):
            raise Phase5ComponentAdapterV1ContractError("binding_attestor is required")
        self._binding = binding
        self._attestor = attestor

    @property
    def binding(self) -> AdapterBindingV1:
        return self._binding

    def validate_runtime(self, value: object) -> None:
        if AdapterBindingV1.from_runtime(value) != self._binding:
            raise Phase5ComponentAdapterV1ContractError("runtime binding mismatch")

    def attest(self) -> None:
        try:
            current = self._attestor()
        except BaseException as exc:
            raise Phase5ComponentAdapterV1Error("binding attestation failed") from exc
        if AdapterBindingV1.from_runtime(current) != self._binding:
            raise Phase5ComponentAdapterV1Error("binding attestation mismatch")


class GrantShadowAdapterV1:
    """Materialize one exact host request before observing R11 shadow state."""

    __slots__ = ("_closed", "_guard", "_lock", "_materialize", "_store")

    def __init__(
        self,
        *,
        binding: AdapterBindingV1,
        binding_attestor: Callable[[], object],
        materialize_request: Callable[[str], object],
        store: object,
    ) -> None:
        self._guard = _BindingGuardV1(binding, binding_attestor)
        if not callable(materialize_request):
            raise Phase5ComponentAdapterV1ContractError(
                "grant materializer is required"
            )
        _callable_member(store, "evaluate")
        _callable_member(store, "end_session")
        _callable_member(store, "kill")
        self._materialize = materialize_request
        self._store = store
        self._lock = threading.RLock()
        self._closed = False

    def _materialized(self, invocation_ref: str) -> object:
        reference = _safe_id(invocation_ref, "invocation_ref")
        try:
            request = self._materialize(reference)
        except BaseException as exc:
            raise Phase5ComponentAdapterV1Error("grant materialization failed") from exc
        try:
            if getattr(request, "invocation_ref") != reference:
                raise Phase5ComponentAdapterV1ContractError(
                    "materialized invocation binding mismatch"
                )
            self._guard.validate_runtime(getattr(request, "binding"))
            exact = (
                getattr(request, "capability") == "local.catalog"
                and getattr(request, "operation") == "catalog_read"
                and type(getattr(request, "provider_free")) is bool
                and getattr(request, "provider_free")
                and type(getattr(request, "read_only")) is bool
                and getattr(request, "read_only")
                and getattr(request, "effect") == "none"
                and getattr(request, "egress") == "none"
                and type(getattr(request, "metadata_allowlisted")) is bool
                and getattr(request, "metadata_allowlisted")
                and type(getattr(request, "cost_micro")) is int
                and getattr(request, "cost_micro") == 0
                and getattr(request, "risk") == "low"
                and type(getattr(request, "reversible")) is bool
                and getattr(request, "reversible")
                and type(getattr(request, "uses_credentials")) is bool
                and not getattr(request, "uses_credentials")
                and type(getattr(request, "privileged")) is bool
                and not getattr(request, "privileged")
                and type(getattr(request, "irreversible")) is bool
                and not getattr(request, "irreversible")
                and type(getattr(request, "action_classes")) is tuple
                and not getattr(request, "action_classes")
            )
        except AttributeError as exc:
            raise Phase5ComponentAdapterV1ContractError(
                "materialized grant request is incomplete"
            ) from exc
        if not exact:
            raise Phase5ComponentAdapterV1ContractError(
                "grant request is not the exact local catalog action"
            )
        return request

    def evaluate(self, invocation_ref: str) -> dict[str, object]:
        with self._lock:
            if self._closed:
                raise Phase5ComponentAdapterV1Error("grant adapter is closed")
        self._guard.attest()
        request = self._materialized(invocation_ref)
        try:
            decision = _callable_member(self._store, "evaluate")(
                getattr(request, "invocation_ref")
            )
        except BaseException as exc:
            raise Phase5ComponentAdapterV1Error("grant evaluator failed") from exc
        self._guard.attest()
        with self._lock:
            if self._closed:
                raise Phase5ComponentAdapterV1Error(
                    "grant adapter closed during evaluation"
                )
        try:
            outcome = _text(getattr(decision, "outcome"), "outcome", 32)
            reason = _safe_id(getattr(decision, "reason"), "reason")
            grant_id = getattr(decision, "grant_id")
            if grant_id is not None:
                grant_id = _safe_id(grant_id, "grant_id")
            scope = _digest(getattr(decision, "scope_digest"), "scope_digest")
            action = _digest(
                getattr(decision, "action_audit_digest"), "action_audit_digest"
            )
            if outcome not in {"disabled", "would-allow", "would-deny"}:
                raise Phase5ComponentAdapterV1ContractError(
                    "grant outcome is outside the accepted R11 contract"
                )
            if (
                type(getattr(decision, "authority_granted")) is not bool
                or getattr(decision, "authority_granted")
                or type(getattr(decision, "callback_required")) is not bool
                or not getattr(decision, "callback_required")
            ):
                raise Phase5ComponentAdapterV1ContractError(
                    "grant decision attempted to convey authority"
                )
        except AttributeError as exc:
            raise Phase5ComponentAdapterV1ContractError(
                "grant evaluator returned an incomplete decision"
            ) from exc
        advisory: dict[str, object] = {
            "outcome": outcome,
            "reason": reason,
            "scope_digest": scope,
            "action_digest": action,
        }
        if grant_id is not None:
            advisory["grant_id"] = grant_id
        if len(json.dumps(advisory, separators=(",", ":"), sort_keys=True).encode()) > MAX_ADVISORY_BYTES_V1:
            raise Phase5ComponentAdapterV1ContractError("grant advisory is too large")
        return advisory

    def close(self, reason: str) -> None:
        reason = _safe_id(reason, "terminal_reason")
        if reason not in _TERMINAL_REASONS:
            raise Phase5ComponentAdapterV1ContractError("terminal reason is invalid")
        with self._lock:
            if self._closed:
                return
            self._closed = True
        callback = "kill" if reason == "kill" else "end_session"
        try:
            _callable_member(self._store, callback)()
        except BaseException as exc:
            raise Phase5ComponentAdapterV1Error(
                f"grant {callback} failed after local close"
            ) from exc


class CapabilityNexusAdapterV1:
    """Expose only the accepted, non-authoritative local.catalog descriptor."""

    __slots__ = ("_batch_factory", "_closed", "_guard", "_lock", "_nexus")

    def __init__(
        self,
        *,
        binding: AdapterBindingV1,
        binding_attestor: Callable[[], object],
        nexus: object,
        batch_factory: RuntimeBatchFactoryV1,
    ) -> None:
        self._guard = _BindingGuardV1(binding, binding_attestor)
        _callable_member(nexus, "snapshot")
        if not callable(batch_factory):
            raise Phase5ComponentAdapterV1ContractError("batch_factory is required")
        self._nexus = nexus
        self._batch_factory = batch_factory
        self._lock = threading.RLock()
        self._closed = False

    @staticmethod
    def _project(entry: object, binding: AdapterBindingV1) -> dict[str, object]:
        try:
            descriptor = getattr(entry, "descriptor")
            if any(
                getattr(entry, name) != getattr(binding, name)
                for name in ("workspace_id", "account_id", "profile_id")
            ):
                raise Phase5ComponentAdapterV1ContractError(
                    "nexus projection binding mismatch"
                )
            if (
                type(getattr(entry, "runtime_available")) is not bool
                or getattr(entry, "runtime_available")
                or type(getattr(entry, "authority_granted")) is not bool
                or getattr(entry, "authority_granted")
            ):
                raise Phase5ComponentAdapterV1ContractError(
                    "nexus projection attempted to convey authority"
                )
            if getattr(descriptor, "capability_id") != "local.catalog":
                raise Phase5ComponentAdapterV1ContractError(
                    "unexpected capability reached the local catalog projector"
                )
            if any(
                getattr(descriptor, name) != getattr(binding, name)
                for name in ("workspace_id", "account_id", "profile_id")
            ):
                raise Phase5ComponentAdapterV1ContractError(
                    "nexus descriptor binding mismatch"
                )
            operations = getattr(descriptor, "operations")
            if type(operations) is not tuple or len(operations) != 1:
                raise Phase5ComponentAdapterV1ContractError(
                    "local catalog operation set is not exact"
                )
            operation = operations[0]
            exact = (
                getattr(descriptor, "provider") == "onyx_local"
                and _enum_value(getattr(descriptor, "transport"), "transport") == "local"
                and getattr(descriptor, "api_name") == "local_catalog"
                and getattr(descriptor, "credential_alias") is None
                and getattr(operation, "operation_id") == "catalog_read"
                and _enum_value(getattr(operation, "kind"), "operation kind") == "read"
                and getattr(operation, "required_scopes") == ("catalog.metadata.read",)
                and getattr(operation, "data_classes") == ("allowlisted_metadata",)
                and getattr(operation, "risk_class") == "low"
                and getattr(operation, "allowed_targets") == ("local_catalog",)
                and getattr(operation, "allowed_domains") == ()
                and getattr(operation, "cost") == "zero_local_micros"
                and getattr(operation, "host_policy") == "always_confirm"
            )
            if not exact:
                raise Phase5ComponentAdapterV1ContractError(
                    "local catalog descriptor is not the accepted read-only contract"
                )
            status = _NEXUS_STATUS.get(
                _enum_value(getattr(entry, "projection_status"), "projection_status")
            )
            if status is None:
                raise Phase5ComponentAdapterV1ContractError(
                    "nexus capability status is unknown"
                )
            return {
                "capability_id": "local.catalog",
                "display_name": "Local catalog metadata",
                "provider": "onyx_local",
                "version": _safe_id(
                    getattr(descriptor, "capability_version"), "capability_version"
                ),
                "status": status,
                "operations": ("catalog_read",),
                "limitation": _CATALOG_LIMITATION,
            }
        except AttributeError as exc:
            raise Phase5ComponentAdapterV1ContractError(
                "nexus projection is incomplete"
            ) from exc

    def project(self, runtime_binding: object) -> object:
        self._guard.validate_runtime(runtime_binding)
        with self._lock:
            if self._closed:
                raise Phase5ComponentAdapterV1Error("nexus adapter is closed")
        self._guard.attest()
        binding = self._guard.binding
        try:
            snapshot = _callable_member(self._nexus, "snapshot")(
                workspace_id=binding.workspace_id,
                account_id=binding.account_id,
                profile_id=binding.profile_id,
            )
        except BaseException as exc:
            raise Phase5ComponentAdapterV1Error("nexus snapshot failed") from exc
        self._guard.attest()
        with self._lock:
            if self._closed:
                raise Phase5ComponentAdapterV1Error(
                    "nexus adapter closed during projection"
                )
        try:
            if any(
                getattr(snapshot, name) != getattr(binding, name)
                for name in ("workspace_id", "account_id", "profile_id")
            ):
                raise Phase5ComponentAdapterV1ContractError(
                    "nexus snapshot binding mismatch"
                )
            entries = getattr(snapshot, "entries")
            source_cursor = _digest(
                getattr(snapshot, "snapshot_digest"), "snapshot_digest"
            )
        except AttributeError as exc:
            raise Phase5ComponentAdapterV1ContractError(
                "nexus snapshot is incomplete"
            ) from exc
        if type(entries) is not tuple or len(entries) > MAX_ITEMS_V1:
            raise Phase5ComponentAdapterV1ContractError(
                "nexus snapshot cardinality is invalid"
            )
        local = tuple(
            entry
            for entry in entries
            if getattr(getattr(entry, "descriptor", None), "capability_id", None)
            == "local.catalog"
        )
        if len(local) != 1:
            raise Phase5ComponentAdapterV1Error(
                "accepted local.catalog capability is absent or duplicated"
            )
        item = self._project(local[0], binding)
        return _make_batch(
            self._batch_factory,
            (item,),
            replace=True,
            source_cursor=source_cursor,
            next_cursor=None,
        )

    def close(self, reason: str) -> None:
        reason = _safe_id(reason, "terminal_reason")
        if reason not in _TERMINAL_REASONS:
            raise Phase5ComponentAdapterV1ContractError("terminal reason is invalid")
        with self._lock:
            self._closed = True


@dataclass(frozen=True, slots=True)
class _CursorRecordV1:
    generation: int
    source_cursor: str
    page_size: int
    expected_offset: int
    total_items: int
    snapshot_id: str
    view_digest: str


class ApprovalInboxAdapterV1:
    """Translate authenticated V15 pages to bounded read-only runtime rows."""

    __slots__ = (
        "_batch_factory",
        "_closed",
        "_counter",
        "_cursors",
        "_generation",
        "_guard",
        "_lock",
        "_projection",
    )

    def __init__(
        self,
        *,
        binding: AdapterBindingV1,
        binding_attestor: Callable[[], object],
        projection: object,
        batch_factory: RuntimeBatchFactoryV1,
    ) -> None:
        self._guard = _BindingGuardV1(binding, binding_attestor)
        _callable_member(projection, "open_page")
        _callable_member(projection, "continue_page")
        if not callable(batch_factory):
            raise Phase5ComponentAdapterV1ContractError("batch_factory is required")
        self._projection = projection
        self._batch_factory = batch_factory
        self._lock = threading.RLock()
        self._cursors: dict[str, _CursorRecordV1] = {}
        self._counter = 0
        self._generation = 0
        self._closed = False

    def factory(self, runtime_binding: object) -> ApprovalInboxAdapterV1:
        self._guard.validate_runtime(runtime_binding)
        with self._lock:
            if self._closed:
                raise Phase5ComponentAdapterV1Error("inbox adapter is closed")
        return self

    @staticmethod
    def _created_at(milliseconds: object) -> str:
        if type(milliseconds) is not int or milliseconds < 0:
            raise Phase5ComponentAdapterV1ContractError("created_at_ms is invalid")
        try:
            instant = datetime.fromtimestamp(milliseconds / 1000, UTC)
        except (OverflowError, OSError, ValueError) as exc:
            raise Phase5ComponentAdapterV1ContractError(
                "created_at_ms is outside the supported range"
            ) from exc
        rendered = instant.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return rendered

    @classmethod
    def _item(cls, value: object, binding: AdapterBindingV1) -> dict[str, object]:
        try:
            if getattr(value, "workspace_id") != binding.workspace_id:
                raise Phase5ComponentAdapterV1ContractError(
                    "inbox item workspace mismatch"
                )
            if any(
                type(getattr(value, name)) is not bool or getattr(value, name)
                for name in (
                    "authority_granted",
                    "approval_action_available",
                    "execution_available",
                )
            ):
                raise Phase5ComponentAdapterV1ContractError(
                    "inbox item attempted to convey authority"
                )
            action_display = _text(
                getattr(value, "action_display"), "action_display", 128
            )
            if "." not in action_display:
                raise Phase5ComponentAdapterV1ContractError(
                    "inbox action display has no operation"
                )
            _tool, operation = action_display.rsplit(".", 1)
            operation = _safe_id(operation, "operation")
            capability = _text(
                getattr(value, "connector_display"), "connector_display", 128
            )
            risk = _text(getattr(value, "risk"), "risk", 16)
            if risk not in _RISKS:
                raise Phase5ComponentAdapterV1ContractError("inbox risk is invalid")
            return {
                "item_id": _safe_id(getattr(value, "item_id"), "item_id"),
                "request_ref": _safe_id(
                    getattr(value, "action_request_id"), "action_request_id"
                ),
                "capability": capability,
                "operation": operation,
                "risk": risk,
                "state": "pending",
                "summary": _text(getattr(value, "reason"), "reason", 512),
                "created_at": cls._created_at(getattr(value, "created_at_ms")),
            }
        except AttributeError as exc:
            raise Phase5ComponentAdapterV1ContractError(
                "inbox item is incomplete"
            ) from exc

    def _new_cursor(self, actual: str, record: _CursorRecordV1) -> str:
        if type(actual) is not str or not actual:
            raise Phase5ComponentAdapterV1ContractError(
                "V15 continuation cursor is invalid"
            )
        if self._counter >= MAX_CURSOR_SEQUENCE_V1:
            raise Phase5ComponentAdapterV1Error("inbox cursor sequence exhausted")
        self._counter += 1
        # The token is an index, not authority or evidence.  A high-entropy
        # digest would correctly trip the runtime DLP scanner, so the actual
        # authenticated V15 cursor remains private in ``_cursors`` and the
        # runtime sees only this bounded one-shot ordinal.
        token = f"ibx-{record.generation}-{self._counter}"
        if len(token.encode()) > MAX_CURSOR_BYTES_V1 or not _SAFE_ID.fullmatch(token):
            raise Phase5ComponentAdapterV1ContractError("short cursor is invalid")
        if token in self._cursors:
            raise Phase5ComponentAdapterV1Error("short cursor collision")
        return token

    def read_page(
        self,
        *,
        binding: object,
        page_size: int,
        cursor: str | None,
    ) -> object:
        self._guard.validate_runtime(binding)
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE_V1:
            raise Phase5ComponentAdapterV1ContractError("page_size is invalid")
        if cursor is not None:
            cursor = _safe_id(cursor, "cursor")
        with self._lock:
            if self._closed:
                raise Phase5ComponentAdapterV1Error("inbox adapter is closed")
            if cursor is None:
                if self._generation >= MAX_CURSOR_SEQUENCE_V1:
                    raise Phase5ComponentAdapterV1Error(
                        "inbox journey sequence exhausted"
                    )
                self._generation += 1
                generation = self._generation
                self._cursors.clear()
                source: _CursorRecordV1 | None = None
            else:
                source = self._cursors.pop(cursor, None)
                if source is None or source.generation != self._generation:
                    raise Phase5ComponentAdapterV1Error(
                        "inbox continuation cursor is unavailable"
                    )
                if source.page_size != page_size:
                    raise Phase5ComponentAdapterV1ContractError(
                        "inbox continuation page_size drift"
                    )
                generation = source.generation
        self._guard.attest()
        try:
            if source is None:
                page = _callable_member(self._projection, "open_page")(
                    page_size=page_size
                )
            else:
                page = _callable_member(self._projection, "continue_page")(
                    source.source_cursor
                )
        except BaseException as exc:
            raise Phase5ComponentAdapterV1Error("approval inbox read failed") from exc
        self._guard.attest()
        with self._lock:
            if self._closed or generation != self._generation:
                raise Phase5ComponentAdapterV1Error(
                    "inbox adapter changed during page read"
                )
        try:
            if _enum_value(getattr(page, "state"), "inbox state") != "READY":
                raise Phase5ComponentAdapterV1Error("approval inbox is not ready")
            for name in (
                "authority_granted",
                "approval_action_available",
                "execution_available",
            ):
                if type(getattr(page, name)) is not bool or getattr(page, name):
                    raise Phase5ComponentAdapterV1ContractError(
                        "inbox page attempted to convey authority"
                    )
            items = getattr(page, "items")
            if type(items) is not tuple or len(items) > page_size:
                raise Phase5ComponentAdapterV1ContractError(
                    "inbox page cardinality is invalid"
                )
            total = getattr(page, "total_items")
            offset = getattr(page, "offset")
            if (
                type(total) is not int
                or not 0 <= total <= MAX_ITEMS_V1
                or type(offset) is not int
                or not 0 <= offset <= total
                or offset + len(items) > total
            ):
                raise Phase5ComponentAdapterV1ContractError(
                    "inbox page bounds are invalid"
                )
            snapshot_id = _digest(getattr(page, "snapshot_id"), "snapshot_id")
            view_digest = _digest(getattr(page, "view_digest"), "view_digest")
            actual_next = getattr(page, "next_cursor")
            if actual_next is not None and (type(actual_next) is not str or not actual_next):
                raise Phase5ComponentAdapterV1ContractError(
                    "inbox next cursor is invalid"
                )
            if not items and actual_next is not None:
                raise Phase5ComponentAdapterV1ContractError(
                    "empty inbox page cannot continue"
                )
        except AttributeError as exc:
            raise Phase5ComponentAdapterV1ContractError(
                "approval inbox page is incomplete"
            ) from exc
        if source is None:
            if offset != 0:
                raise Phase5ComponentAdapterV1ContractError(
                    "first inbox page offset is not zero"
                )
        elif (
            offset != source.expected_offset
            or total != source.total_items
            or snapshot_id != source.snapshot_id
            or view_digest != source.view_digest
        ):
            raise Phase5ComponentAdapterV1ContractError(
                "inbox continuation relation drift"
            )
        projected = tuple(self._item(item, self._guard.binding) for item in items)
        next_cursor: str | None = None
        if actual_next is not None:
            record = _CursorRecordV1(
                generation,
                actual_next,
                page_size,
                offset + len(items),
                total,
                snapshot_id,
                view_digest,
            )
            with self._lock:
                if self._closed or generation != self._generation:
                    raise Phase5ComponentAdapterV1Error(
                        "inbox adapter changed before cursor publication"
                    )
                if len(self._cursors) >= MAX_ITEMS_V1:
                    raise Phase5ComponentAdapterV1Error(
                        "inbox cursor capacity exhausted"
                    )
                next_cursor = self._new_cursor(actual_next, record)
                self._cursors[next_cursor] = record
        return _make_batch(
            self._batch_factory,
            projected,
            replace=cursor is None,
            source_cursor=cursor,
            next_cursor=next_cursor,
        )

    def close(self, reason: str) -> None:
        reason = _safe_id(reason, "terminal_reason")
        if reason not in _TERMINAL_REASONS:
            raise Phase5ComponentAdapterV1ContractError("terminal reason is invalid")
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._generation += 1
            self._cursors.clear()


def _make_batch(
    factory: RuntimeBatchFactoryV1,
    items: tuple[Mapping[str, object], ...],
    *,
    replace: bool,
    source_cursor: str | None,
    next_cursor: str | None,
) -> object:
    try:
        result = factory(
            items,
            replace=replace,
            source_cursor=source_cursor,
            next_cursor=next_cursor,
        )
    except BaseException as exc:
        raise Phase5ComponentAdapterV1Error("runtime batch construction failed") from exc
    try:
        if (
            getattr(result, "items") != items
            or getattr(result, "replace") is not replace
            or getattr(result, "source_cursor") != source_cursor
            or getattr(result, "next_cursor") != next_cursor
        ):
            raise Phase5ComponentAdapterV1ContractError(
                "runtime batch factory changed the projection"
            )
    except AttributeError as exc:
        raise Phase5ComponentAdapterV1ContractError(
            "runtime batch factory returned an incompatible value"
        ) from exc
    return result


@dataclass(frozen=True, slots=True)
class ComponentAdapterBundleV1:
    runtime_components: object
    grant: GrantShadowAdapterV1 | None
    nexus: CapabilityNexusAdapterV1 | None
    inbox: ApprovalInboxAdapterV1 | None


def build_component_adapters_v1(
    *,
    flags: AdapterFlagsV1,
    acceptance: AcceptedComponentsV1,
    binding: object,
    binding_attestor: Callable[[], object],
    batch_factory: RuntimeBatchFactoryV1,
    components_factory: RuntimeComponentsFactoryV1,
    grant_store: object | None = None,
    materialize_grant_request: Callable[[str], object] | None = None,
    nexus: object | None = None,
    inbox_projection: object | None = None,
) -> ComponentAdapterBundleV1:
    """Build an explicit default-off runtime component bundle.

    Supplying a component while its flag is off is rejected.  This prevents a
    future integration call site from accidentally retaining a hidden live
    dependency during rollback.
    """

    if type(flags) is not AdapterFlagsV1:
        raise Phase5ComponentAdapterV1ContractError("exact adapter flags are required")
    if type(acceptance) is not AcceptedComponentsV1:
        raise Phase5ComponentAdapterV1ContractError(
            "exact accepted-component declaration is required"
        )
    if not callable(batch_factory) or not callable(components_factory):
        raise Phase5ComponentAdapterV1ContractError(
            "runtime factories must be callable"
        )
    normalized_binding = AdapterBindingV1.from_runtime(binding)
    supplied = {
        "grant_shadow": grant_store is not None or materialize_grant_request is not None,
        "nexus_projection": nexus is not None,
        "approval_inbox": inbox_projection is not None,
    }
    for name, present in supplied.items():
        if present and not getattr(flags, name):
            raise Phase5ComponentAdapterV1ContractError(
                f"{name} component was supplied while its flag is off"
            )
    if not flags.adapters:
        try:
            components = components_factory()
        except BaseException as exc:
            raise Phase5ComponentAdapterV1Error(
                "disabled runtime component construction failed"
            ) from exc
        return ComponentAdapterBundleV1(components, None, None, None)

    grant_adapter: GrantShadowAdapterV1 | None = None
    nexus_adapter: CapabilityNexusAdapterV1 | None = None
    inbox_adapter: ApprovalInboxAdapterV1 | None = None
    runtime_args: dict[str, object] = {}

    if flags.grant_shadow:
        acceptance.require("grants")
        if grant_store is None or materialize_grant_request is None:
            raise Phase5ComponentAdapterV1ContractError(
                "enabled grant adapter requires store and materializer"
            )
        grant_adapter = GrantShadowAdapterV1(
            binding=normalized_binding,
            binding_attestor=binding_attestor,
            materialize_request=materialize_grant_request,
            store=grant_store,
        )
        runtime_args["grant_evaluator"] = grant_adapter.evaluate
        runtime_args["grant_terminator"] = grant_adapter.close

    if flags.nexus_projection:
        acceptance.require("nexus")
        if nexus is None:
            raise Phase5ComponentAdapterV1ContractError(
                "enabled nexus adapter requires the accepted registry"
            )
        nexus_adapter = CapabilityNexusAdapterV1(
            binding=normalized_binding,
            binding_attestor=binding_attestor,
            nexus=nexus,
            batch_factory=batch_factory,
        )
        runtime_args["nexus_projector"] = nexus_adapter.project
        runtime_args["nexus_terminator"] = nexus_adapter.close

    if flags.approval_inbox:
        acceptance.require("inbox")
        if inbox_projection is None:
            raise Phase5ComponentAdapterV1ContractError(
                "enabled inbox adapter requires the accepted projection"
            )
        inbox_adapter = ApprovalInboxAdapterV1(
            binding=normalized_binding,
            binding_attestor=binding_attestor,
            projection=inbox_projection,
            batch_factory=batch_factory,
        )
        runtime_args["inbox_factory"] = inbox_adapter.factory
        runtime_args["inbox_terminator"] = inbox_adapter.close

    try:
        components = components_factory(**runtime_args)
    except BaseException as exc:
        raise Phase5ComponentAdapterV1Error("runtime component construction failed") from exc
    for name, expected in runtime_args.items():
        try:
            actual = getattr(components, name)
        except AttributeError as exc:
            raise Phase5ComponentAdapterV1ContractError(
                "runtime components factory returned an incompatible value"
            ) from exc
        if actual != expected:
            raise Phase5ComponentAdapterV1ContractError(
                f"runtime components factory changed {name}"
            )
    return ComponentAdapterBundleV1(
        components, grant_adapter, nexus_adapter, inbox_adapter
    )


__all__ = [
    "ADAPTER_CONTRACT_V1",
    "GRANTS_ACCEPTANCE_V1",
    "NEXUS_ACCEPTANCE_V1",
    "INBOX_ACCEPTANCE_V1",
    "AdapterBindingV1",
    "AdapterFlagsV1",
    "AcceptedComponentsV1",
    "ApprovalInboxAdapterV1",
    "CapabilityNexusAdapterV1",
    "ComponentAdapterBundleV1",
    "GrantShadowAdapterV1",
    "Phase5ComponentAdapterV1ContractError",
    "Phase5ComponentAdapterV1Error",
    "build_component_adapters_v1",
]
