"""Phase 5.2 V3 default-off, non-authoritative approval review projection.

The trust boundary is explicit and intentionally modest: a host composes one
``HostInboxSource`` and one concrete monotonic clock into a projection. Python
same-process callers can build a separate inert projection with their own data,
but that creates no runtime wiring, approval, permission, or execution
authority. Existing projections pin their source, clock, and token key. Python
same-process reflection into underscore-prefixed implementation details is
outside this boundary and still conveys no authority.

Only this projection can create authenticated snapshot/cursor tokens. Tokens
and display results are review artifacts; no consumer can execute from them and
this module exposes no approve, deny, revoke, dispatch, persistence, or write
operation.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from memory.store import contains_secret


APPROVAL_INBOX_FLAG = "ONYX_APPROVAL_INBOX_V3"
INBOX_SCHEMA_VERSION = 3
SNAPSHOT_SCHEMA_VERSION = 3
TOKEN_SCHEMA_VERSION = 3
MAX_ITEMS = 128
MAX_SNAPSHOTS = 8
MAX_VIEWS = 16
MAX_PAGE_SIZE = 50
MAX_BATCH_ITEMS = 32
MAX_TEXT = 512
MAX_SUMMARY = 1_024
MAX_TOKEN = 2_048
MAX_SOURCE_CALLBACKS = 1
MAX_SNAPSHOT_AGE_MS = 300_000
MAX_INTEGER = 9_223_372_036_854_775_807
MAX_COST_MICRO = 1_000_000_000_000_000
GRANT_INSPECTOR_STATUS = "omitted-phase5-2b-no-r11-import"

_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_WORKSPACE_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SIGNATURE = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN_BODY = re.compile(r"[A-Za-z0-9_-]+\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")
_RISKS = frozenset({"low", "medium", "high", "critical"})
_DATA_CLASSES = frozenset({"public", "internal", "confidential", "restricted"})
_EGRESS = frozenset({"none", "local-only", "named-account", "public"})
_REVERSIBILITY = frozenset({"reversible", "compensating-action", "irreversible"})
_SORTS = frozenset(
    {"created-desc", "expiry-asc", "item-id-asc", "risk-desc", "workspace-asc"}
)
_RESERVED_DIGESTS = frozenset({"0" * 64, "f" * 64})
_SECRET_PREFIXES = (
    "api-key-",
    "bearer-",
    "gho-",
    "ghp-",
    "github-pat-",
    "glpat-",
    "oauth-",
    "secret-",
    "sk-",
    "token-",
)
class ApprovalInboxV3Error(RuntimeError):
    pass


class ApprovalInboxV3ContractError(ValueError):
    pass


class ApprovalInboxV3Disabled(ApprovalInboxV3Error):
    pass


class ApprovalInboxV3Stale(ApprovalInboxV3Error):
    pass


class ApprovalInboxV3Unavailable(ApprovalInboxV3Error):
    pass


def approval_inbox_enabled(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    raw = source.get(APPROVAL_INBOX_FLAG, "")
    return type(raw) is str and raw.strip().casefold() in {"1", "true"}


def _bounded_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ApprovalInboxV3ContractError(f"{label} is out of bounds")
    return value


def _safe_id(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not _ID.fullmatch(value)
        or value.startswith(_SECRET_PREFIXES)
        or contains_secret(value)
    ):
        raise ApprovalInboxV3ContractError(f"{label} is invalid")
    return value


def _workspace(value: object) -> str:
    if (
        type(value) is not str
        or not _WORKSPACE_ID.fullmatch(value)
        or value.startswith(_SECRET_PREFIXES)
        or contains_secret(value)
    ):
        raise ApprovalInboxV3ContractError("workspace_id is invalid")
    return value


def _digest(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not _SHA256.fullmatch(value)
        or value in _RESERVED_DIGESTS
    ):
        raise ApprovalInboxV3ContractError(f"{label} is not a canonical digest")
    return value


def _text(value: object, label: str, maximum: int = MAX_TEXT) -> str:
    if type(value) is not str or value != value.strip() or not value or len(value) > maximum:
        raise ApprovalInboxV3ContractError(f"{label} is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ApprovalInboxV3ContractError(f"{label} contains control characters")
    if contains_secret(value):
        raise ApprovalInboxV3ContractError(f"{label} contains secret-like material")
    return value


def _enum(value: object, allowed: frozenset[str], label: str) -> str:
    if type(value) is not str or value not in allowed:
        raise ApprovalInboxV3ContractError(f"{label} is invalid")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class MonotonicInboxClock:
    """Concrete production clock with permanent rollback detection."""

    __slots__ = ("_failed", "_high_water", "_lock")

    def __init__(self) -> None:
        object.__setattr__(self, "_high_water", 0)
        object.__setattr__(self, "_failed", False)
        object.__setattr__(self, "_lock", threading.RLock())

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("monotonic inbox clock composition is immutable")

    def now_ms(self) -> int:
        current = time.monotonic_ns() // 1_000_000
        with self._lock:
            if self._failed or current < self._high_water:
                object.__setattr__(self, "_failed", True)
                raise ApprovalInboxV3Unavailable("local-monotonic-clock-rollback")
            object.__setattr__(self, "_high_water", current)
            return current


class DeterministicInboxClock:
    """Exact concrete deterministic clock for tests; never selected implicitly."""

    __slots__ = ("_current", "_failed", "_high_water", "_lock")

    def __init__(self, initial_ms: int = 1) -> None:
        initial = _bounded_int(initial_ms, "initial_ms", 0, MAX_INTEGER)
        self._current = initial
        self._failed = False
        self._high_water = initial
        self._lock = threading.RLock()

    def now_ms(self) -> int:
        with self._lock:
            if self._failed or self._current < self._high_water:
                self._failed = True
                raise ApprovalInboxV3Unavailable("local-monotonic-clock-rollback")
            self._high_water = self._current
            return self._current

    def advance(self, milliseconds: int) -> None:
        delta = _bounded_int(milliseconds, "milliseconds", 0, MAX_INTEGER)
        with self._lock:
            if self._current > MAX_INTEGER - delta:
                raise ApprovalInboxV3ContractError("clock advance overflows")
            self._current += delta

    def set_for_test(self, milliseconds: int) -> None:
        value = _bounded_int(milliseconds, "milliseconds", 0, MAX_INTEGER)
        with self._lock:
            self._current = value


@dataclass(frozen=True, slots=True)
class HostInboxItem:
    """Exact host output type. Fields are proposals until projection validation."""

    item_id: object
    workspace_id: object
    workspace_display: object
    account_display: object
    mission_id: object
    mission_display: object
    reason: object
    action: object
    target_display: object
    target_digest: object
    payload_summary: object
    payload_digest: object
    data_class: object
    egress: object
    effect_summary: object
    reversibility: object
    idempotency_summary: object
    idempotency_key: object
    verification_plan: object
    rollback_plan: object
    cost_micro: object
    currency: object
    risk: object
    created_at_ms: object
    expires_at_ms: object
    always_explicit: object
    batch_eligible: object


@dataclass(frozen=True, slots=True)
class HostInboxSnapshot:
    """Exact host callback output. Source times are display metadata only."""

    schema_version: object
    source_revision: object
    source_epoch: object
    principal_id: object
    session_id: object
    captured_at_ms: object
    valid_until_ms: object
    audit_healthy: object
    session_active: object
    kill_switch: object
    items: object


class HostInboxSource:
    """Pinned callback composition with a one-call nonblocking concurrency cap."""

    __slots__ = (
        "_callback",
        "_principal_id",
        "_semaphore",
        "_session_id",
    )

    def __init__(
        self,
        callback: Callable[[], HostInboxSnapshot],
        principal_id: str,
        session_id: str,
    ) -> None:
        if not callable(callback):
            raise ApprovalInboxV3ContractError("host source callback is invalid")
        object.__setattr__(self, "_callback", callback)
        object.__setattr__(self, "_principal_id", _safe_id(principal_id, "principal_id"))
        object.__setattr__(self, "_session_id", _safe_id(session_id, "session_id"))
        object.__setattr__(
            self, "_semaphore", threading.BoundedSemaphore(MAX_SOURCE_CALLBACKS)
        )

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("host inbox source composition is immutable")

    def __init_subclass__(cls, **_kwargs: object) -> None:
        raise TypeError("host inbox source cannot be subclassed")

    def __copy__(self) -> object:
        raise TypeError("host inbox source is not copyable")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("host inbox source is not copyable")

    def __reduce__(self) -> object:
        raise TypeError("host inbox source is not serializable")

    @property
    def principal_id(self) -> str:
        return self._principal_id

    @property
    def session_id(self) -> str:
        return self._session_id

    def capture(self) -> HostInboxSnapshot:
        if not self._semaphore.acquire(blocking=False):
            raise ApprovalInboxV3Unavailable("host-source-busy") from None
        failed = False
        result: object = None
        try:
            try:
                result = self._callback()
            except Exception:
                failed = True
        finally:
            self._semaphore.release()
        if failed:
            raise ApprovalInboxV3Unavailable("host-source-failed") from None
        if type(result) is not HostInboxSnapshot:
            raise ApprovalInboxV3ContractError("host snapshot concrete type is invalid")
        items = result.items
        if type(items) is not tuple:
            raise ApprovalInboxV3ContractError("host items must be an exact tuple")
        if len(items) > MAX_ITEMS:
            raise ApprovalInboxV3ContractError("host item collection exceeds its bound")
        if any(type(item) is not HostInboxItem for item in items):
            raise ApprovalInboxV3ContractError("host item concrete type is invalid")
        return result


@dataclass(frozen=True, slots=True)
class InboxQuery:
    workspace_id: str | None = None
    mission_id: str | None = None
    risks: tuple[str, ...] = ()
    batch_eligible: bool | None = None
    sort: str = "created-desc"

    def __post_init__(self) -> None:
        if self.workspace_id is not None:
            _workspace(self.workspace_id)
        if self.mission_id is not None:
            _safe_id(self.mission_id, "mission_id")
        if type(self.risks) is not tuple or len(self.risks) > len(_RISKS):
            raise ApprovalInboxV3ContractError("risk filter is invalid")
        risks = tuple(sorted(_enum(value, _RISKS, "risk") for value in self.risks))
        if len(set(risks)) != len(risks):
            raise ApprovalInboxV3ContractError("risk filter contains duplicates")
        object.__setattr__(self, "risks", risks)
        if self.batch_eligible is not None and type(self.batch_eligible) is not bool:
            raise ApprovalInboxV3ContractError("batch filter is invalid")
        _enum(self.sort, _SORTS, "sort")

    def payload(self) -> dict[str, object]:
        return {
            "batch_eligible": self.batch_eligible,
            "mission_id": self.mission_id,
            "risks": list(self.risks),
            "sort": self.sort,
            "workspace_id": self.workspace_id,
        }


@dataclass(frozen=True, slots=True, init=False)
class ApprovalDisplayItem:
    item_id: str
    workspace_id: str
    workspace_display: str
    account_display: str
    mission_id: str | None
    mission_display: str
    reason: str
    action: str
    target_display: str
    target_digest: str
    payload_summary: str
    payload_digest: str
    data_class: str
    egress: str
    effect_summary: str
    reversibility: str
    idempotency_summary: str
    idempotency_key: str
    verification_plan: str
    rollback_plan: str
    cost_micro: int
    currency: str
    risk: str
    created_at_ms: int
    expires_at_ms: int
    always_explicit: bool
    batch_eligible: bool
    item_digest: str
    authority_granted: bool = field(init=False, default=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("display items are created by the projection")

    def _initialize(self, source: HostInboxItem) -> None:
        if type(source) is not HostInboxItem:
            raise TypeError("display items are created by the projection")
        mission_id = None if source.mission_id is None else _safe_id(source.mission_id, "mission_id")
        risk = _enum(source.risk, _RISKS, "risk")
        created = _bounded_int(source.created_at_ms, "created_at_ms", 0, MAX_INTEGER)
        expires = _bounded_int(source.expires_at_ms, "expires_at_ms", 1, MAX_INTEGER)
        if created >= expires:
            raise ApprovalInboxV3ContractError("source display timestamps are invalid")
        if type(source.always_explicit) is not bool or type(source.batch_eligible) is not bool:
            raise ApprovalInboxV3ContractError("host item booleans are invalid")
        if source.batch_eligible and (
            source.always_explicit or risk in {"high", "critical"}
        ):
            raise ApprovalInboxV3ContractError(
                "always-explicit/high-risk item cannot be batch eligible"
            )
        currency = source.currency
        if type(currency) is not str or not _CURRENCY.fullmatch(currency):
            raise ApprovalInboxV3ContractError("currency is invalid")
        values: dict[str, object] = {
            "item_id": _safe_id(source.item_id, "item_id"),
            "workspace_id": _workspace(source.workspace_id),
            "workspace_display": _text(source.workspace_display, "workspace_display"),
            "account_display": _text(source.account_display, "account_display"),
            "mission_id": mission_id,
            "mission_display": _text(source.mission_display, "mission_display"),
            "reason": _text(source.reason, "reason", MAX_SUMMARY),
            "action": _text(source.action, "action"),
            "target_display": _text(source.target_display, "target_display"),
            "target_digest": _digest(source.target_digest, "target_digest"),
            "payload_summary": _text(source.payload_summary, "payload_summary", MAX_SUMMARY),
            "payload_digest": _digest(source.payload_digest, "payload_digest"),
            "data_class": _enum(source.data_class, _DATA_CLASSES, "data_class"),
            "egress": _enum(source.egress, _EGRESS, "egress"),
            "effect_summary": _text(source.effect_summary, "effect_summary", MAX_SUMMARY),
            "reversibility": _enum(
                source.reversibility, _REVERSIBILITY, "reversibility"
            ),
            "idempotency_summary": _text(
                source.idempotency_summary, "idempotency_summary"
            ),
            "idempotency_key": _digest(source.idempotency_key, "idempotency_key"),
            "verification_plan": _text(
                source.verification_plan, "verification_plan", MAX_SUMMARY
            ),
            "rollback_plan": _text(source.rollback_plan, "rollback_plan", MAX_SUMMARY),
            "cost_micro": _bounded_int(
                source.cost_micro, "cost_micro", 0, MAX_COST_MICRO
            ),
            "currency": currency,
            "risk": risk,
            "created_at_ms": created,
            "expires_at_ms": expires,
            "always_explicit": source.always_explicit,
            "batch_eligible": source.batch_eligible,
        }
        payload = {
            "contract": "ApprovalDisplayItem.v3",
            "schema_version": INBOX_SCHEMA_VERSION,
            "fields": values,
        }
        for name, value in values.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "item_digest", _sha(payload))
        object.__setattr__(self, "authority_granted", False)

    def payload(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name not in {"item_digest", "authority_granted"}
        }


@dataclass(frozen=True, slots=True)
class _Snapshot:
    source_revision: str
    source_epoch: int
    principal_id: str
    session_id: str
    captured_at_ms: int
    valid_until_ms: int
    items: tuple[ApprovalDisplayItem, ...]
    source_digest: str
    snapshot_digest: str
    local_created_ms: int
    local_deadline_ms: int


@dataclass(frozen=True, slots=True)
class _View:
    snapshot_digest: str
    view_digest: str
    query: InboxQuery
    page_size: int
    allowed_item_ids: tuple[str, ...]
    local_deadline_ms: int


@dataclass(frozen=True, slots=True, init=False)
class InboxPage:
    status: str
    snapshot_version: int
    snapshot_digest: str | None
    view_digest: str | None
    page_digest: str | None
    snapshot_token: str | None
    query: InboxQuery | None
    items: tuple[ApprovalDisplayItem, ...]
    total_items: int
    page_size: int
    offset: int
    next_cursor: str | None
    read_only: bool = field(init=False, default=True)
    authority_granted: bool = field(init=False, default=False)
    execution_available: bool = field(init=False, default=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("inbox pages are created by the projection")


@dataclass(frozen=True, slots=True, init=False)
class BatchPreviewItem:
    item_id: str
    item_digest: str
    idempotency_key: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("batch items are created by the projection")


@dataclass(frozen=True, slots=True, init=False)
class CalmBatchPreview:
    snapshot_version: int
    snapshot_digest: str
    view_digest: str
    query: InboxQuery
    items: tuple[BatchPreviewItem, ...]
    manifest_digest: str
    read_only: bool = field(init=False, default=True)
    approval_action_available: bool = field(init=False, default=False)
    authority_granted: bool = field(init=False, default=False)
    execution_available: bool = field(init=False, default=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("batch previews are created by the projection")


def _canonical_view_digest(snapshot: _Snapshot, view: _View) -> str:
    return _sha(
        {
            "contract": "ApprovalInboxView.v3",
            "snapshot_digest": snapshot.snapshot_digest,
            "query": view.query.payload(),
            "page_size": view.page_size,
            "ordered_item_ids": list(view.allowed_item_ids),
        }
    )


def _token_digest(token: str | None) -> str | None:
    if token is None:
        return None
    return hashlib.sha256(token.encode("ascii", "strict")).hexdigest()


def _build_result_factories() -> tuple[Callable[..., object], ...]:
    authority = object()

    def populate(seal: object, instance: object, values: Mapping[str, object]) -> None:
        if seal is not authority:
            raise TypeError("result construction authority is internal")
        for name, value in values.items():
            object.__setattr__(instance, name, value)

    def make_display_item(source: HostInboxItem) -> ApprovalDisplayItem:
        item = object.__new__(ApprovalDisplayItem)
        item._initialize(source)
        return item

    def make_page(
        projection: ApprovalInboxProjection,
        *,
        status: str,
        snapshot: _Snapshot | None = None,
        view: _View | None = None,
        items: tuple[ApprovalDisplayItem, ...] = (),
        offset: int = 0,
        snapshot_token: str | None = None,
        next_cursor: str | None = None,
    ) -> InboxPage:
        if type(projection) is not ApprovalInboxProjection:
            raise TypeError("inbox pages are created by the projection")
        if status == "disabled":
            if any((snapshot, view, items, offset, snapshot_token, next_cursor)):
                raise ApprovalInboxV3ContractError("disabled page is contradictory")
            values: dict[str, object] = {
                "status": "disabled",
                "snapshot_version": 0,
                "snapshot_digest": None,
                "view_digest": None,
                "page_digest": None,
                "snapshot_token": None,
                "query": None,
                "items": (),
                "total_items": 0,
                "page_size": 0,
                "offset": 0,
                "next_cursor": None,
            }
        elif status == "ready":
            if type(snapshot) is not _Snapshot or type(view) is not _View:
                raise ApprovalInboxV3ContractError("ready page lacks exact snapshot/view")
            if view.snapshot_digest != snapshot.snapshot_digest or type(view.query) is not InboxQuery:
                raise ApprovalInboxV3ContractError("ready page snapshot/view relation is invalid")
            if (
                not 1 <= view.page_size <= MAX_PAGE_SIZE
                or len(view.allowed_item_ids) > MAX_ITEMS
                or len(set(view.allowed_item_ids)) != len(view.allowed_item_ids)
            ):
                raise ApprovalInboxV3ContractError("ready page view bounds/set is invalid")
            derived_view_digest = _canonical_view_digest(snapshot, view)
            if not hmac.compare_digest(view.view_digest, derived_view_digest):
                raise ApprovalInboxV3ContractError("ready page view digest is not canonical")
            if type(items) is not tuple or any(type(item) is not ApprovalDisplayItem for item in items):
                raise ApprovalInboxV3ContractError("ready page items are invalid")
            total = len(view.allowed_item_ids)
            _bounded_int(offset, "offset", 0, total)
            if not len(items) <= view.page_size or offset + len(items) > total:
                raise ApprovalInboxV3ContractError("page bounds are contradictory")
            expected_ids = view.allowed_item_ids[offset : offset + len(items)]
            if tuple(item.item_id for item in items) != expected_ids:
                raise ApprovalInboxV3ContractError("page items do not match the bound view")
            snapshot_items = {item.item_id: item.item_digest for item in snapshot.items}
            if any(item_id not in snapshot_items for item_id in view.allowed_item_ids) or any(
                not hmac.compare_digest(item.item_digest, snapshot_items[item.item_id])
                for item in items
            ):
                raise ApprovalInboxV3ContractError("page item digests do not match the snapshot")
            if type(snapshot_token) is not str or not snapshot_token:
                raise ApprovalInboxV3ContractError("ready page lacks an authenticated token")
            expected_snapshot_payload = {
                "d": snapshot.snapshot_digest,
                "k": "snapshot",
                "q": view.query.payload(),
                "v": TOKEN_SCHEMA_VERSION,
                "vd": derived_view_digest,
                "z": view.page_size,
            }
            if projection._decode(snapshot_token, "snapshot") != expected_snapshot_payload:
                raise ApprovalInboxV3ContractError("ready page snapshot token is contradictory")
            next_offset = offset + len(items)
            has_remaining = next_offset < total
            if has_remaining:
                if type(next_cursor) is not str or not next_cursor:
                    raise ApprovalInboxV3ContractError("ready page lacks its next cursor")
                expected_cursor_payload = expected_snapshot_payload | {
                    "k": "cursor",
                    "o": next_offset,
                }
                if projection._decode(next_cursor, "cursor") != expected_cursor_payload:
                    raise ApprovalInboxV3ContractError("ready page cursor is contradictory")
            elif next_cursor is not None:
                raise ApprovalInboxV3ContractError("terminal page exposes a cursor")
            page_payload = {
                "contract": "ApprovalInboxPage.v3",
                "snapshot_digest": snapshot.snapshot_digest,
                "view_digest": derived_view_digest,
                "query": view.query.payload(),
                "page_size": view.page_size,
                "offset": offset,
                "total_items": total,
                "item_digests": [item.item_digest for item in items],
                "has_next": has_remaining,
                "snapshot_token_digest": _token_digest(snapshot_token),
                "next_cursor_digest": _token_digest(next_cursor),
            }
            values = {
                "status": "ready",
                "snapshot_version": SNAPSHOT_SCHEMA_VERSION,
                "snapshot_digest": snapshot.snapshot_digest,
                "view_digest": derived_view_digest,
                "page_digest": _sha(page_payload),
                "snapshot_token": snapshot_token,
                "query": view.query,
                "items": items,
                "total_items": total,
                "page_size": view.page_size,
                "offset": offset,
                "next_cursor": next_cursor,
            }
        else:
            raise ApprovalInboxV3ContractError("page status is invalid")
        page = object.__new__(InboxPage)
        populate(
            authority,
            page,
            values
            | {
                "read_only": True,
                "authority_granted": False,
                "execution_available": False,
            },
        )
        return page

    def make_batch_preview(
        projection: ApprovalInboxProjection,
        snapshot: _Snapshot,
        view: _View,
        items: tuple[ApprovalDisplayItem, ...],
        snapshot_token: str,
    ) -> CalmBatchPreview:
        if type(projection) is not ApprovalInboxProjection:
            raise TypeError("batch previews are created by the projection")
        if type(snapshot) is not _Snapshot or type(view) is not _View:
            raise ApprovalInboxV3ContractError("batch preview lacks exact snapshot/view")
        if view.snapshot_digest != snapshot.snapshot_digest or type(view.query) is not InboxQuery:
            raise ApprovalInboxV3ContractError("batch snapshot/view relation is invalid")
        derived_view_digest = _canonical_view_digest(snapshot, view)
        if not hmac.compare_digest(view.view_digest, derived_view_digest):
            raise ApprovalInboxV3ContractError("batch view digest is not canonical")
        expected_snapshot_payload = {
            "d": snapshot.snapshot_digest,
            "k": "snapshot",
            "q": view.query.payload(),
            "v": TOKEN_SCHEMA_VERSION,
            "vd": derived_view_digest,
            "z": view.page_size,
        }
        if projection._decode(snapshot_token, "snapshot") != expected_snapshot_payload:
            raise ApprovalInboxV3ContractError("batch snapshot token is contradictory")
        if type(items) is not tuple or not 1 <= len(items) <= MAX_BATCH_ITEMS:
            raise ApprovalInboxV3ContractError("batch preview item count is invalid")
        if any(type(item) is not ApprovalDisplayItem for item in items):
            raise ApprovalInboxV3ContractError("batch preview items are invalid")
        ordered = tuple(sorted(items, key=lambda item: item.item_id))
        if ordered != items or len({item.item_id for item in items}) != len(items):
            raise ApprovalInboxV3ContractError("batch preview ordering/set is invalid")
        allowed = set(view.allowed_item_ids)
        snapshot_items = {item.item_id: item.item_digest for item in snapshot.items}
        preview_items: list[BatchPreviewItem] = []
        for item in items:
            if item.item_id not in allowed:
                raise ApprovalInboxV3ContractError("batch item is hidden from the bound view")
            if item.item_id not in snapshot_items or not hmac.compare_digest(
                item.item_digest, snapshot_items[item.item_id]
            ):
                raise ApprovalInboxV3ContractError("batch item digest is not in the snapshot")
            if not item.batch_eligible or item.always_explicit or item.risk in {"high", "critical"}:
                raise ApprovalInboxV3ContractError("batch item is ineligible")
            preview_item = object.__new__(BatchPreviewItem)
            populate(
                authority,
                preview_item,
                {
                    "item_id": item.item_id,
                    "item_digest": item.item_digest,
                    "idempotency_key": item.idempotency_key,
                },
            )
            preview_items.append(preview_item)
        exact_preview_items = tuple(preview_items)
        manifest = _sha(
            {
                "contract": "CalmBatchPreview.v3",
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "snapshot_digest": snapshot.snapshot_digest,
                "view_digest": derived_view_digest,
                "query": view.query.payload(),
                "snapshot_token_digest": _token_digest(snapshot_token),
                "selected_visible_item_digests": [
                    {"item_id": item.item_id, "item_digest": item.item_digest}
                    for item in exact_preview_items
                ],
                "items": [
                    {
                        "item_id": item.item_id,
                        "item_digest": item.item_digest,
                        "idempotency_key": item.idempotency_key,
                    }
                    for item in exact_preview_items
                ],
            }
        )
        preview = object.__new__(CalmBatchPreview)
        populate(
            authority,
            preview,
            {
                "snapshot_version": SNAPSHOT_SCHEMA_VERSION,
                "snapshot_digest": snapshot.snapshot_digest,
                "view_digest": derived_view_digest,
                "query": view.query,
                "items": exact_preview_items,
                "manifest_digest": manifest,
                "read_only": True,
                "approval_action_available": False,
                "authority_granted": False,
                "execution_available": False,
            },
        )
        return preview

    return make_display_item, make_page, make_batch_preview


_make_display_item, _make_page_result, _make_batch_result = _build_result_factories()
del _build_result_factories


class ApprovalInboxProjection:
    """Session-only projection with pinned composition and bounded caches."""

    _PINNED = frozenset(
        {
            "_clock",
            "_integrity_failed",
            "_source",
            "_source_digest_at_high_water",
            "_source_epoch_high_water",
            "_token_key",
        }
    )

    def __init__(
        self,
        source: HostInboxSource,
        clock: MonotonicInboxClock | DeterministicInboxClock,
    ) -> None:
        if type(source) is not HostInboxSource:
            raise ApprovalInboxV3ContractError("exact HostInboxSource is required")
        if type(clock) not in {MonotonicInboxClock, DeterministicInboxClock}:
            raise ApprovalInboxV3ContractError("exact concrete inbox clock is required")
        self._source = source
        self._clock = clock
        self._token_key = secrets.token_bytes(32)
        self._snapshots: OrderedDict[str, _Snapshot] = OrderedDict()
        self._views: OrderedDict[str, _View] = OrderedDict()
        self._source_epoch_high_water = 0
        self._source_digest_at_high_water: str | None = None
        self._integrity_failed = False
        self._lock = threading.RLock()

    def __setattr__(self, name: str, value: object) -> None:
        if name in self._PINNED and hasattr(self, name):
            raise AttributeError("approval inbox host composition is pinned")
        object.__setattr__(self, name, value)

    def _disabled_page(self) -> InboxPage:
        return _make_page_result(self, status="disabled")

    def _assert_integrity(self) -> None:
        with self._lock:
            if self._integrity_failed:
                raise ApprovalInboxV3Unavailable("projection-integrity-failed")

    def _latch_integrity(self, reason: str) -> None:
        object.__setattr__(self, "_integrity_failed", True)
        self._snapshots.clear()
        self._views.clear()
        raise ApprovalInboxV3Stale(reason)

    def _observe_source_integrity(self, snapshot: _Snapshot) -> None:
        with self._lock:
            if self._integrity_failed:
                raise ApprovalInboxV3Unavailable("projection-integrity-failed")
            if snapshot.source_epoch < self._source_epoch_high_water:
                self._latch_integrity("host-source-epoch-rollback")
            if (
                snapshot.source_epoch == self._source_epoch_high_water
                and self._source_digest_at_high_water is not None
                and not hmac.compare_digest(
                    snapshot.source_digest, self._source_digest_at_high_water
                )
            ):
                self._latch_integrity("host-source-changed-without-epoch")
            if snapshot.source_epoch > self._source_epoch_high_water:
                object.__setattr__(
                    self, "_source_epoch_high_water", snapshot.source_epoch
                )
                object.__setattr__(
                    self, "_source_digest_at_high_water", snapshot.source_digest
                )

    def _materialize(self, source: HostInboxSnapshot, local_now: int) -> _Snapshot:
        if type(source.schema_version) is not int or source.schema_version != INBOX_SCHEMA_VERSION:
            raise ApprovalInboxV3ContractError("unknown host snapshot schema")
        revision = _safe_id(source.source_revision, "source_revision")
        epoch = _bounded_int(source.source_epoch, "source_epoch", 1, MAX_INTEGER)
        principal = _safe_id(source.principal_id, "principal_id")
        session = _safe_id(source.session_id, "session_id")
        if principal != self._source.principal_id or session != self._source.session_id:
            raise ApprovalInboxV3Unavailable("host-principal-session-drift")
        captured = _bounded_int(source.captured_at_ms, "captured_at_ms", 0, MAX_INTEGER)
        valid_until = _bounded_int(source.valid_until_ms, "valid_until_ms", 1, MAX_INTEGER)
        if captured >= valid_until:
            raise ApprovalInboxV3ContractError("source display timestamps are invalid")
        if any(
            type(value) is not bool
            for value in (source.audit_healthy, source.session_active, source.kill_switch)
        ):
            raise ApprovalInboxV3ContractError("host safety values are invalid")
        if not source.audit_healthy:
            raise ApprovalInboxV3Unavailable("host-audit-unhealthy")
        if not source.session_active:
            raise ApprovalInboxV3Unavailable("host-session-inactive")
        if source.kill_switch:
            raise ApprovalInboxV3Unavailable("host-kill-active")
        items = tuple(_make_display_item(item) for item in source.items)
        items = tuple(sorted(items, key=lambda item: item.item_id))
        if len({item.item_id for item in items}) != len(items):
            raise ApprovalInboxV3ContractError("host item IDs are duplicated")
        if len({item.item_digest for item in items}) != len(items):
            raise ApprovalInboxV3ContractError("host item digests are duplicated")
        if len({item.idempotency_key for item in items}) != len(items):
            raise ApprovalInboxV3ContractError("host idempotency keys are duplicated")
        semantic = {
            "contract": "ApprovalInboxSnapshot.v3",
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "source_revision": revision,
            "source_epoch": epoch,
            "principal_id": principal,
            "session_id": session,
            "captured_at_ms": captured,
            "valid_until_ms": valid_until,
            "items": [item.payload() | {"item_digest": item.item_digest} for item in items],
        }
        if local_now > MAX_INTEGER - MAX_SNAPSHOT_AGE_MS:
            raise ApprovalInboxV3Unavailable("local-monotonic-deadline-overflow")
        source_digest = _sha(semantic)
        deadline = local_now + MAX_SNAPSHOT_AGE_MS
        snapshot_digest = _sha(
            {
                "contract": "LocalApprovalReviewSnapshot.v3",
                "source_digest": source_digest,
                "local_created_ms": local_now,
                "local_deadline_ms": deadline,
            }
        )
        return _Snapshot(
            revision,
            epoch,
            principal,
            session,
            captured,
            valid_until,
            items,
            source_digest,
            snapshot_digest,
            local_now,
            deadline,
        )

    def _register_snapshot(self, snapshot: _Snapshot) -> None:
        self._observe_source_integrity(snapshot)
        with self._lock:
            if self._integrity_failed:
                raise ApprovalInboxV3Unavailable("projection-integrity-failed")
            self._snapshots[snapshot.snapshot_digest] = snapshot
            self._snapshots.move_to_end(snapshot.snapshot_digest)
            while len(self._snapshots) > MAX_SNAPSHOTS:
                removed, _snapshot = self._snapshots.popitem(last=False)
                for view_digest in tuple(self._views):
                    if self._views[view_digest].snapshot_digest == removed:
                        del self._views[view_digest]

    @staticmethod
    def _ordered_items(snapshot: _Snapshot, query: InboxQuery) -> tuple[ApprovalDisplayItem, ...]:
        items = tuple(
            item
            for item in snapshot.items
            if (query.workspace_id is None or item.workspace_id == query.workspace_id)
            and (query.mission_id is None or item.mission_id == query.mission_id)
            and (not query.risks or item.risk in query.risks)
            and (query.batch_eligible is None or item.batch_eligible == query.batch_eligible)
        )
        risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        keys: dict[str, Callable[[ApprovalDisplayItem], object]] = {
            "created-desc": lambda item: (-item.created_at_ms, item.item_id),
            "expiry-asc": lambda item: (item.expires_at_ms, item.item_id),
            "item-id-asc": lambda item: item.item_id,
            "risk-desc": lambda item: (risk_order[item.risk], item.item_id),
            "workspace-asc": lambda item: (item.workspace_id, item.item_id),
        }
        return tuple(sorted(items, key=keys[query.sort]))

    def _register_view(self, snapshot: _Snapshot, query: InboxQuery, page_size: int) -> _View:
        ordered = self._ordered_items(snapshot, query)
        allowed = tuple(item.item_id for item in ordered)
        provisional = _View(
            snapshot.snapshot_digest,
            "0" * 64,
            query,
            page_size,
            allowed,
            snapshot.local_deadline_ms,
        )
        digest = _canonical_view_digest(snapshot, provisional)
        view = _View(
            snapshot.snapshot_digest,
            digest,
            query,
            page_size,
            allowed,
            snapshot.local_deadline_ms,
        )
        with self._lock:
            if self._integrity_failed:
                raise ApprovalInboxV3Unavailable("projection-integrity-failed")
            self._views[digest] = view
            self._views.move_to_end(digest)
            while len(self._views) > MAX_VIEWS:
                self._views.popitem(last=False)
        return view

    @staticmethod
    def _query_from_payload(value: object) -> InboxQuery:
        if type(value) is not dict or frozenset(value) != {
            "batch_eligible",
            "mission_id",
            "risks",
            "sort",
            "workspace_id",
        }:
            raise ApprovalInboxV3ContractError("token query shape is invalid")
        risks = value["risks"]
        if type(risks) is not list:
            raise ApprovalInboxV3ContractError("token risk filter is invalid")
        return InboxQuery(
            workspace_id=value["workspace_id"],
            mission_id=value["mission_id"],
            risks=tuple(risks),
            batch_eligible=value["batch_eligible"],
            sort=value["sort"],
        )

    @classmethod
    def _validate_token_payload(cls, value: object, kind: str) -> dict[str, object]:
        expected = {"d", "k", "q", "v", "vd", "z"}
        if kind == "cursor":
            expected.add("o")
        if type(value) is not dict or set(value) != expected:
            raise ApprovalInboxV3ContractError("token payload shape is invalid")
        if value["v"] != TOKEN_SCHEMA_VERSION or value["k"] != kind:
            raise ApprovalInboxV3ContractError("token payload schema is invalid")
        _digest(value["d"], "snapshot_digest")
        _digest(value["vd"], "view_digest")
        _bounded_int(value["z"], "page_size", 1, MAX_PAGE_SIZE)
        if kind == "cursor":
            _bounded_int(value["o"], "offset", 1, MAX_ITEMS)
        query = cls._query_from_payload(value["q"])
        if query.payload() != value["q"]:
            raise ApprovalInboxV3ContractError("token query is noncanonical")
        return value

    def _encode(self, payload: dict[str, object], kind: str) -> str:
        self._validate_token_payload(payload, kind)
        body = base64.urlsafe_b64encode(_canonical(payload)).decode("ascii").rstrip("=")
        if not body or not _TOKEN_BODY.fullmatch(body):
            raise ApprovalInboxV3ContractError("token body encoding is invalid")
        signature = hmac.new(self._token_key, body.encode("ascii"), hashlib.sha256).hexdigest()
        token = f"{body}.{signature}"
        if len(token) > MAX_TOKEN:
            raise ApprovalInboxV3ContractError("token exceeds its bound")
        return token

    def _decode(self, token: object, kind: str) -> dict[str, object]:
        failed = False
        payload: object = None
        try:
            if type(token) is not str or not token or len(token) > MAX_TOKEN:
                raise ValueError
            token.encode("ascii", "strict")
            if token.count(".") != 1:
                raise ValueError
            body, signature = token.split(".", 1)
            if not _TOKEN_BODY.fullmatch(body) or not _SIGNATURE.fullmatch(signature):
                raise ValueError
            expected = hmac.new(
                self._token_key, body.encode("ascii"), hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            padding = "=" * (-len(body) % 4)
            raw = base64.b64decode(
                (body + padding).encode("ascii"), altchars=b"-_", validate=True
            )
            payload = json.loads(raw.decode("utf-8"))
            if _canonical(payload) != raw:
                raise ValueError
            self._validate_token_payload(payload, kind)
        except (
            ApprovalInboxV3ContractError,
            UnicodeError,
            ValueError,
            TypeError,
            binascii.Error,
            json.JSONDecodeError,
        ):
            failed = True
        if failed or type(payload) is not dict:
            raise ApprovalInboxV3Stale("invalid-authenticated-review-token") from None
        return payload

    def _lookup(self, payload: dict[str, object], local_now: int) -> tuple[_Snapshot, _View]:
        digest = payload["d"]
        view_digest = payload["vd"]
        with self._lock:
            if self._integrity_failed:
                raise ApprovalInboxV3Unavailable("projection-integrity-failed")
            snapshot = self._snapshots.get(digest)
            view = self._views.get(view_digest)
        if type(snapshot) is not _Snapshot or type(view) is not _View:
            raise ApprovalInboxV3Stale("review-snapshot-or-view-not-available")
        if view.snapshot_digest != snapshot.snapshot_digest:
            raise ApprovalInboxV3Stale("review-view-snapshot-mismatch")
        if view.page_size != payload["z"] or view.query.payload() != payload["q"]:
            raise ApprovalInboxV3Stale("review-token-view-mismatch")
        if local_now >= snapshot.local_deadline_ms or local_now >= view.local_deadline_ms:
            raise ApprovalInboxV3Stale("local-review-deadline-expired")
        return snapshot, view

    def _refresh_exact(self, pinned: _Snapshot, local_now: int) -> None:
        current_source = self._source.capture()
        after = self._clock.now_ms()
        if after < local_now:
            raise ApprovalInboxV3Unavailable("local-monotonic-clock-rollback")
        if after >= pinned.local_deadline_ms:
            raise ApprovalInboxV3Stale("local-review-deadline-expired")
        current = self._materialize(current_source, after)
        self._observe_source_integrity(current)
        if (
            current.source_epoch != pinned.source_epoch
            or current.source_revision != pinned.source_revision
            or not hmac.compare_digest(current.source_digest, pinned.source_digest)
        ):
            raise ApprovalInboxV3Stale("host-source-drifted-from-review-snapshot")

    def _snapshot_token(self, snapshot: _Snapshot, view: _View) -> str:
        return self._encode(
            {
                "d": snapshot.snapshot_digest,
                "k": "snapshot",
                "q": view.query.payload(),
                "v": TOKEN_SCHEMA_VERSION,
                "vd": view.view_digest,
                "z": view.page_size,
            },
            "snapshot",
        )

    def _cursor(self, snapshot: _Snapshot, view: _View, offset: int) -> str:
        return self._encode(
            {
                "d": snapshot.snapshot_digest,
                "k": "cursor",
                "o": offset,
                "q": view.query.payload(),
                "v": TOKEN_SCHEMA_VERSION,
                "vd": view.view_digest,
                "z": view.page_size,
            },
            "cursor",
        )

    @staticmethod
    def _items_for_view(snapshot: _Snapshot, view: _View) -> tuple[ApprovalDisplayItem, ...]:
        by_id = {item.item_id: item for item in snapshot.items}
        if any(item_id not in by_id for item_id in view.allowed_item_ids):
            raise ApprovalInboxV3Stale("review-view-item-set-drifted")
        return tuple(by_id[item_id] for item_id in view.allowed_item_ids)

    def _page(self, snapshot: _Snapshot, view: _View, offset: int) -> InboxPage:
        with self._lock:
            if self._integrity_failed:
                raise ApprovalInboxV3Unavailable("projection-integrity-failed")
            ordered = self._items_for_view(snapshot, view)
            page_items = ordered[offset : offset + view.page_size]
            next_offset = offset + len(page_items)
            next_cursor = (
                self._cursor(snapshot, view, next_offset)
                if next_offset < len(ordered)
                else None
            )
            return _make_page_result(
                self,
                status="ready",
                snapshot=snapshot,
                view=view,
                items=page_items,
                offset=offset,
                snapshot_token=self._snapshot_token(snapshot, view),
                next_cursor=next_cursor,
            )

    def open_page(
        self,
        *,
        query: InboxQuery | None = None,
        page_size: int = 20,
        environ: Mapping[str, str] | None = None,
    ) -> InboxPage:
        if not approval_inbox_enabled(environ):
            return self._disabled_page()
        self._assert_integrity()
        if query is None:
            query = InboxQuery()
        if type(query) is not InboxQuery:
            raise ApprovalInboxV3ContractError("exact InboxQuery is required")
        _bounded_int(page_size, "page_size", 1, MAX_PAGE_SIZE)
        before = self._clock.now_ms()
        source = self._source.capture()  # never under projection lock
        after = self._clock.now_ms()
        if after < before:
            raise ApprovalInboxV3Unavailable("local-monotonic-clock-rollback")
        snapshot = self._materialize(source, after)
        self._register_snapshot(snapshot)
        view = self._register_view(snapshot, query, page_size)
        return self._page(snapshot, view, 0)

    def continue_page(
        self,
        cursor: object,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> InboxPage:
        if not approval_inbox_enabled(environ):
            return self._disabled_page()
        self._assert_integrity()
        payload = self._decode(cursor, "cursor")
        local_now = self._clock.now_ms()
        snapshot, view = self._lookup(payload, local_now)
        self._refresh_exact(snapshot, local_now)
        return self._page(snapshot, view, payload["o"])

    def preview_calm_batch(
        self,
        snapshot_token: object,
        selected_item_ids: Sequence[str],
        *,
        environ: Mapping[str, str] | None = None,
    ) -> CalmBatchPreview:
        if not approval_inbox_enabled(environ):
            raise ApprovalInboxV3Disabled(f"{APPROVAL_INBOX_FLAG} is disabled")
        self._assert_integrity()
        payload = self._decode(snapshot_token, "snapshot")
        if type(selected_item_ids) not in {tuple, list}:
            raise ApprovalInboxV3ContractError("batch selection must be an exact finite sequence")
        if not 1 <= len(selected_item_ids) <= MAX_BATCH_ITEMS:
            raise ApprovalInboxV3ContractError("batch selection exceeds its bound")
        selected = tuple(_safe_id(item_id, "item_id") for item_id in selected_item_ids)
        if len(set(selected)) != len(selected):
            raise ApprovalInboxV3ContractError("batch selection contains duplicates")
        local_now = self._clock.now_ms()
        snapshot, view = self._lookup(payload, local_now)
        self._refresh_exact(snapshot, local_now)
        allowed = set(view.allowed_item_ids)
        if set(selected) - allowed:
            raise ApprovalInboxV3ContractError("batch selection is outside the bound view")
        by_id = {item.item_id: item for item in snapshot.items}
        chosen = tuple(sorted((by_id[item_id] for item_id in selected), key=lambda item: item.item_id))
        with self._lock:
            if self._integrity_failed:
                raise ApprovalInboxV3Unavailable("projection-integrity-failed")
            return _make_batch_result(self, snapshot, view, chosen, snapshot_token)


__all__ = [
    "APPROVAL_INBOX_FLAG",
    "GRANT_INSPECTOR_STATUS",
    "ApprovalDisplayItem",
    "ApprovalInboxProjection",
    "ApprovalInboxV3ContractError",
    "ApprovalInboxV3Disabled",
    "ApprovalInboxV3Error",
    "ApprovalInboxV3Stale",
    "ApprovalInboxV3Unavailable",
    "BatchPreviewItem",
    "CalmBatchPreview",
    "DeterministicInboxClock",
    "HostInboxItem",
    "HostInboxSnapshot",
    "HostInboxSource",
    "InboxPage",
    "InboxQuery",
    "MonotonicInboxClock",
    "approval_inbox_enabled",
]
