"""Phase 5.2 default-off, read-only approval-inbox projection.

The module is intentionally absent from application startup.  It materializes
only host-sanitized display records, keeps snapshots in memory, and exposes no
approve, deny, revoke, dispatch, or persistence operation.  A snapshot or calm
batch is a review preview, never execution authority.
"""

from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from memory.store import contains_secret


APPROVAL_INBOX_FLAG = "ONYX_APPROVAL_INBOX_V1"
INBOX_SCHEMA_VERSION = 1
SNAPSHOT_SCHEMA_VERSION = 1
CURSOR_SCHEMA_VERSION = 1
MAX_ITEMS = 128
MAX_SNAPSHOTS = 8
MAX_PAGE_SIZE = 50
MAX_BATCH_ITEMS = 32
MAX_TEXT = 512
MAX_SUMMARY = 1_024
MAX_CURSOR = 2_048
MAX_MONOTONIC_MS = 9_223_372_036_854_775_807
MAX_ITEM_LIFETIME_MS = 86_400_000
MAX_SNAPSHOT_LIFETIME_MS = 900_000

GRANT_INSPECTOR_STATUS = "omitted-phase5-2b-no-r11-import"

_WORKSPACE_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_SAFE_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_REVISION = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")
_RISKS = frozenset({"low", "medium", "high", "critical"})
_DATA_CLASSES = frozenset({"public", "internal", "confidential", "restricted"})
_EGRESS = frozenset({"none", "local-only", "named-account", "public"})
_REVERSIBILITY = frozenset({"reversible", "compensating-action", "irreversible"})
_SORTS = frozenset(
    {"created-desc", "expiry-asc", "item-id-asc", "risk-desc", "workspace-asc"}
)
_RESERVED_DIGESTS = frozenset({"0" * 64, "f" * 64})
_SECRET_ID_PREFIXES = (
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
_ITEM_FIELDS = frozenset(
    {
        "item_id",
        "workspace_id",
        "workspace_display",
        "account_display",
        "mission_id",
        "mission_display",
        "reason",
        "action",
        "target_display",
        "target_digest",
        "payload_summary",
        "payload_digest",
        "data_class",
        "egress",
        "effect_summary",
        "reversibility",
        "idempotency_summary",
        "idempotency_key",
        "verification_plan",
        "rollback_plan",
        "cost_micro",
        "currency",
        "risk",
        "created_at_ms",
        "expires_at_ms",
        "always_explicit",
        "batch_eligible",
    }
)
_SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version",
        "source_revision",
        "source_epoch",
        "principal_id",
        "session_id",
        "captured_at_ms",
        "valid_until_ms",
        "audit_healthy",
        "session_active",
        "kill_switch",
        "items",
    }
)
_SOURCE_SEAL = object()
_ITEM_SEAL = object()


class ApprovalInboxError(RuntimeError):
    """Base exception for the read-only projection."""


class ApprovalInboxContractError(ValueError):
    """Trusted source or read request violated the bounded contract."""


class ApprovalInboxDisabled(ApprovalInboxError):
    """Raised only by operations that require an enabled read projection."""


class ApprovalInboxStale(ApprovalInboxError):
    """A cursor/token no longer identifies the current exact source snapshot."""


class ApprovalInboxUnavailable(ApprovalInboxError):
    """Host session, audit, or kill state prevents a safe projection."""


def approval_inbox_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """Accept only explicit opt-in values; all other values are disabled."""
    source = os.environ if environ is None else environ
    raw = source.get(APPROVAL_INBOX_FLAG, "")
    return type(raw) is str and raw.strip().casefold() in {"1", "true"}


def _bounded_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ApprovalInboxContractError(f"{label} is out of bounds")
    return value


def _safe_id(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not _SAFE_ID.fullmatch(value)
        or value.startswith(_SECRET_ID_PREFIXES)
        or contains_secret(value)
    ):
        raise ApprovalInboxContractError(f"{label} is invalid")
    return value


def _workspace_id(value: object) -> str:
    if (
        type(value) is not str
        or not _WORKSPACE_ID.fullmatch(value)
        or value.startswith(_SECRET_ID_PREFIXES)
        or contains_secret(value)
    ):
        raise ApprovalInboxContractError("workspace_id is invalid")
    return value


def _digest(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not _SHA256.fullmatch(value)
        or value in _RESERVED_DIGESTS
    ):
        raise ApprovalInboxContractError(f"{label} is not a canonical digest")
    return value


def _text(value: object, label: str, maximum: int = MAX_TEXT) -> str:
    if type(value) is not str or value != value.strip() or not value or len(value) > maximum:
        raise ApprovalInboxContractError(f"{label} is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ApprovalInboxContractError(f"{label} contains control characters")
    if contains_secret(value):
        raise ApprovalInboxContractError(f"{label} contains secret-like material")
    return value


def _optional_id(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _safe_id(value, label)


def _enum(value: object, allowed: frozenset[str], label: str) -> str:
    if type(value) is not str or value not in allowed:
        raise ApprovalInboxContractError(f"{label} is invalid")
    return value


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


class ApprovalInboxItem:
    """Immutable host-materialized display record with no raw target/payload."""

    __slots__ = tuple(sorted(_ITEM_FIELDS | {"item_digest", "_sealed"}))

    def __init__(self, seal: object, values: Mapping[str, object]) -> None:
        if seal is not _ITEM_SEAL or type(values) is not dict:
            raise TypeError("approval inbox items are host-materialized")
        if frozenset(values) != _ITEM_FIELDS:
            raise ApprovalInboxContractError("approval item fields are not exact")

        item_id = _safe_id(values["item_id"], "item_id")
        workspace_id = _workspace_id(values["workspace_id"])
        mission_id = _optional_id(values["mission_id"], "mission_id")
        risk = _enum(values["risk"], _RISKS, "risk")
        data_class = _enum(values["data_class"], _DATA_CLASSES, "data_class")
        egress = _enum(values["egress"], _EGRESS, "egress")
        reversibility = _enum(
            values["reversibility"], _REVERSIBILITY, "reversibility"
        )
        created = _bounded_int(
            values["created_at_ms"], "created_at_ms", 0, MAX_MONOTONIC_MS
        )
        expires = _bounded_int(
            values["expires_at_ms"], "expires_at_ms", 1, MAX_MONOTONIC_MS
        )
        if created >= expires or expires - created > MAX_ITEM_LIFETIME_MS:
            raise ApprovalInboxContractError("approval item lifetime is invalid")
        cost = _bounded_int(values["cost_micro"], "cost_micro", 0, 10**15)
        currency = values["currency"]
        if type(currency) is not str or not _CURRENCY.fullmatch(currency):
            raise ApprovalInboxContractError("currency is invalid")
        always_explicit = values["always_explicit"]
        batch_eligible = values["batch_eligible"]
        if type(always_explicit) is not bool or type(batch_eligible) is not bool:
            raise ApprovalInboxContractError("approval item booleans are invalid")
        if batch_eligible and (always_explicit or risk in {"high", "critical"}):
            raise ApprovalInboxContractError(
                "always-explicit/high-risk item cannot be batch eligible"
            )

        normalized: dict[str, object] = {
            "item_id": item_id,
            "workspace_id": workspace_id,
            "workspace_display": _text(values["workspace_display"], "workspace_display"),
            "account_display": _text(values["account_display"], "account_display"),
            "mission_id": mission_id,
            "mission_display": _text(values["mission_display"], "mission_display"),
            "reason": _text(values["reason"], "reason", MAX_SUMMARY),
            "action": _text(values["action"], "action"),
            "target_display": _text(values["target_display"], "target_display"),
            "target_digest": _digest(values["target_digest"], "target_digest"),
            "payload_summary": _text(
                values["payload_summary"], "payload_summary", MAX_SUMMARY
            ),
            "payload_digest": _digest(values["payload_digest"], "payload_digest"),
            "data_class": data_class,
            "egress": egress,
            "effect_summary": _text(
                values["effect_summary"], "effect_summary", MAX_SUMMARY
            ),
            "reversibility": reversibility,
            "idempotency_summary": _text(
                values["idempotency_summary"], "idempotency_summary"
            ),
            "idempotency_key": _digest(
                values["idempotency_key"], "idempotency_key"
            ),
            "verification_plan": _text(
                values["verification_plan"], "verification_plan", MAX_SUMMARY
            ),
            "rollback_plan": _text(
                values["rollback_plan"], "rollback_plan", MAX_SUMMARY
            ),
            "cost_micro": cost,
            "currency": currency,
            "risk": risk,
            "created_at_ms": created,
            "expires_at_ms": expires,
            "always_explicit": always_explicit,
            "batch_eligible": batch_eligible,
        }
        for name, value in normalized.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "item_digest", _sha(self.canonical_payload()))
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("approval inbox items are immutable")

    def __copy__(self) -> ApprovalInboxItem:
        return self

    def __deepcopy__(self, _memo: object) -> ApprovalInboxItem:
        return self

    def __reduce__(self) -> object:
        raise TypeError("approval inbox items are not serializable")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "contract": "ApprovalInboxItem.v1",
            "schema_version": INBOX_SCHEMA_VERSION,
            "fields": {name: getattr(self, name) for name in sorted(_ITEM_FIELDS)},
        }


@dataclass(frozen=True, slots=True)
class _MaterializedSnapshot:
    schema_version: int
    source_revision: str
    source_epoch: int
    principal_id: str
    session_id: str
    captured_at_ms: int
    valid_until_ms: int
    items: tuple[ApprovalInboxItem, ...]
    snapshot_digest: str


class HostApprovalSource:
    """Opaque pinned host callback; construction is reserved to host composition."""

    __slots__ = ("_callback", "_principal_id", "_sealed", "_session_id")

    def __init__(
        self,
        seal: object,
        callback: Callable[[], Mapping[str, object]],
        principal_id: str,
        session_id: str,
    ) -> None:
        if seal is not _SOURCE_SEAL:
            raise TypeError("approval source must be bound by the trusted host")
        if not callable(callback):
            raise ApprovalInboxContractError("approval source callback is invalid")
        object.__setattr__(self, "_callback", callback)
        object.__setattr__(self, "_principal_id", _safe_id(principal_id, "principal_id"))
        object.__setattr__(self, "_session_id", _safe_id(session_id, "session_id"))
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("host approval source binding is immutable")

    def __init_subclass__(cls, **_kwargs: object) -> None:
        raise TypeError("host approval source cannot be subclassed")

    def __reduce__(self) -> object:
        raise TypeError("host approval sources are not serializable")

    def __copy__(self) -> object:
        raise TypeError("host approval sources are not copyable")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("host approval sources are not copyable")

    def capture(self) -> _MaterializedSnapshot:
        """Run the pinned host callback and copy/validate its complete result."""
        try:
            raw = copy.deepcopy(self._callback())
        except Exception as exc:
            raise ApprovalInboxUnavailable("host approval source failed") from exc
        if type(raw) is not dict or frozenset(raw) != _SNAPSHOT_FIELDS:
            raise ApprovalInboxContractError("host approval snapshot fields are not exact")
        if raw["schema_version"] != INBOX_SCHEMA_VERSION:
            raise ApprovalInboxContractError("unknown approval inbox schema")
        revision = _safe_id(raw["source_revision"], "source_revision")
        source_epoch = _bounded_int(
            raw["source_epoch"], "source_epoch", 1, MAX_MONOTONIC_MS
        )
        principal_id = _safe_id(raw["principal_id"], "principal_id")
        session_id = _safe_id(raw["session_id"], "session_id")
        if principal_id != self._principal_id or session_id != self._session_id:
            raise ApprovalInboxUnavailable("host principal/session binding drifted")
        captured = _bounded_int(
            raw["captured_at_ms"], "captured_at_ms", 0, MAX_MONOTONIC_MS
        )
        valid_until = _bounded_int(
            raw["valid_until_ms"], "valid_until_ms", 1, MAX_MONOTONIC_MS
        )
        if (
            captured >= valid_until
            or valid_until - captured > MAX_SNAPSHOT_LIFETIME_MS
        ):
            raise ApprovalInboxContractError("host snapshot lifetime is invalid")
        for name in ("audit_healthy", "session_active", "kill_switch"):
            if type(raw[name]) is not bool:
                raise ApprovalInboxContractError(f"{name} is invalid")
        if not raw["audit_healthy"]:
            raise ApprovalInboxUnavailable("approval audit is unhealthy")
        if not raw["session_active"]:
            raise ApprovalInboxUnavailable("approval session is inactive")
        if raw["kill_switch"]:
            raise ApprovalInboxUnavailable("approval kill switch is active")
        raw_items = raw["items"]
        if type(raw_items) not in {tuple, list} or len(raw_items) > MAX_ITEMS:
            raise ApprovalInboxContractError("approval item collection exceeds its bound")
        items: list[ApprovalInboxItem] = []
        for raw_item in raw_items:
            if type(raw_item) is not dict:
                raise ApprovalInboxContractError("approval item must be an exact mapping")
            item = ApprovalInboxItem(_ITEM_SEAL, dict(raw_item))
            if item.created_at_ms > captured or item.expires_at_ms <= captured:
                raise ApprovalInboxStale("host supplied an expired/future approval item")
            items.append(item)
        items.sort(key=lambda item: item.item_id)
        if len({item.item_id for item in items}) != len(items):
            raise ApprovalInboxContractError("approval item IDs are duplicated")
        if len({item.item_digest for item in items}) != len(items):
            raise ApprovalInboxContractError("approval item digests are duplicated")
        if len({item.idempotency_key for item in items}) != len(items):
            raise ApprovalInboxContractError("approval idempotency keys are duplicated")
        if items:
            valid_until = min(valid_until, *(item.expires_at_ms for item in items))
        payload = {
            "contract": "ApprovalInboxSnapshot.v1",
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "source_revision": revision,
            "source_epoch": source_epoch,
            "principal_id": principal_id,
            "session_id": session_id,
            "captured_at_ms": captured,
            "valid_until_ms": valid_until,
            "items": [item.canonical_payload() | {"item_digest": item.item_digest} for item in items],
        }
        return _MaterializedSnapshot(
            SNAPSHOT_SCHEMA_VERSION,
            revision,
            source_epoch,
            principal_id,
            session_id,
            captured,
            valid_until,
            tuple(items),
            _sha(payload),
        )


def _host_source_for_testing(
    callback: Callable[[], Mapping[str, object]], principal_id: str, session_id: str
) -> HostApprovalSource:
    """Test seam only; production host binding is intentionally not wired in Phase 5.2."""
    return HostApprovalSource(_SOURCE_SEAL, callback, principal_id, session_id)


@dataclass(frozen=True, slots=True)
class InboxQuery:
    workspace_id: str | None = None
    mission_id: str | None = None
    risks: tuple[str, ...] = ()
    batch_eligible: bool | None = None
    sort: str = "created-desc"

    def __post_init__(self) -> None:
        if self.workspace_id is not None:
            _workspace_id(self.workspace_id)
        if self.mission_id is not None:
            _safe_id(self.mission_id, "mission_id")
        if type(self.risks) is not tuple or len(self.risks) > len(_RISKS):
            raise ApprovalInboxContractError("risk filter is invalid")
        risks = tuple(sorted(_enum(value, _RISKS, "risk") for value in self.risks))
        if len(set(risks)) != len(risks):
            raise ApprovalInboxContractError("risk filter contains duplicates")
        object.__setattr__(self, "risks", risks)
        if self.batch_eligible is not None and type(self.batch_eligible) is not bool:
            raise ApprovalInboxContractError("batch eligibility filter is invalid")
        _enum(self.sort, _SORTS, "sort")

    def payload(self) -> dict[str, object]:
        return {
            "batch_eligible": self.batch_eligible,
            "mission_id": self.mission_id,
            "risks": list(self.risks),
            "sort": self.sort,
            "workspace_id": self.workspace_id,
        }


@dataclass(frozen=True, slots=True)
class InboxPage:
    status: str
    snapshot_version: int
    snapshot_digest: str | None
    snapshot_token: str | None
    items: tuple[ApprovalInboxItem, ...]
    total_items: int
    next_cursor: str | None
    read_only: bool = field(init=False, default=True)
    authority_granted: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        if self.status not in {"disabled", "ready"}:
            raise ApprovalInboxContractError("page status is invalid")
        if self.status == "disabled":
            if any(
                (
                    self.snapshot_version,
                    self.snapshot_digest,
                    self.snapshot_token,
                    self.items,
                    self.total_items,
                    self.next_cursor,
                )
            ):
                raise ApprovalInboxContractError("disabled page must be empty")
            return
        if self.snapshot_version != SNAPSHOT_SCHEMA_VERSION:
            raise ApprovalInboxContractError("page snapshot version is invalid")
        _digest(self.snapshot_digest, "snapshot_digest")
        if type(self.snapshot_token) is not str or not self.snapshot_token:
            raise ApprovalInboxContractError("snapshot token is missing")
        if type(self.items) is not tuple or any(type(item) is not ApprovalInboxItem for item in self.items):
            raise ApprovalInboxContractError("page items are invalid")
        _bounded_int(self.total_items, "total_items", 0, MAX_ITEMS)


@dataclass(frozen=True, slots=True)
class BatchPreviewItem:
    item_id: str
    item_digest: str
    idempotency_key: str

    def __post_init__(self) -> None:
        _safe_id(self.item_id, "item_id")
        _digest(self.item_digest, "item_digest")
        _digest(self.idempotency_key, "idempotency_key")


@dataclass(frozen=True, slots=True)
class CalmBatchPreview:
    snapshot_version: int
    snapshot_digest: str
    items: tuple[BatchPreviewItem, ...]
    manifest_digest: str
    read_only: bool = field(init=False, default=True)
    approval_action_available: bool = field(init=False, default=False)
    authority_granted: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        if self.snapshot_version != SNAPSHOT_SCHEMA_VERSION:
            raise ApprovalInboxContractError("batch snapshot version is invalid")
        _digest(self.snapshot_digest, "snapshot_digest")
        if type(self.items) is not tuple or not 1 <= len(self.items) <= MAX_BATCH_ITEMS:
            raise ApprovalInboxContractError("batch items are invalid")
        if tuple(sorted(self.items, key=lambda item: item.item_id)) != self.items:
            raise ApprovalInboxContractError("batch items are not canonical")
        if len({item.item_id for item in self.items}) != len(self.items):
            raise ApprovalInboxContractError("batch item IDs are duplicated")
        _digest(self.manifest_digest, "manifest_digest")


class ApprovalInbox:
    """Thread-safe session-only snapshot/cache facade with no mutation authority."""

    def __init__(self, source: HostApprovalSource) -> None:
        if type(source) is not HostApprovalSource:
            raise ApprovalInboxContractError("a concrete host approval source is required")
        self._source = source
        self._cursor_key = secrets.token_bytes(32)
        self._snapshots: OrderedDict[str, _MaterializedSnapshot] = OrderedDict()
        self._source_epoch_high_water = 0
        self._source_digest_at_high_water: str | None = None
        self._captured_at_high_water = 0
        self._lock = threading.RLock()

    @staticmethod
    def _disabled_page() -> InboxPage:
        return InboxPage("disabled", 0, None, None, (), 0, None)

    def _encode(self, payload: Mapping[str, object]) -> str:
        body = base64.urlsafe_b64encode(_canonical_json(dict(payload))).decode("ascii").rstrip("=")
        signature = hmac.new(self._cursor_key, body.encode("ascii"), hashlib.sha256).hexdigest()
        token = f"{body}.{signature}"
        if len(token) > MAX_CURSOR:
            raise ApprovalInboxContractError("cursor exceeds its bound")
        return token

    def _decode(self, token: object, expected_kind: str) -> dict[str, object]:
        if type(token) is not str or not token or len(token) > MAX_CURSOR or token.count(".") != 1:
            raise ApprovalInboxStale("snapshot token is invalid")
        body, signature = token.split(".", 1)
        expected = hmac.new(self._cursor_key, body.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ApprovalInboxStale("snapshot token is invalid")
        try:
            padding = "=" * (-len(body) % 4)
            payload = json.loads(base64.urlsafe_b64decode(body + padding).decode("utf-8"))
        except (binascii.Error, UnicodeError, ValueError, json.JSONDecodeError) as exc:
            raise ApprovalInboxStale("snapshot token is invalid") from exc
        if type(payload) is not dict or payload.get("v") != CURSOR_SCHEMA_VERSION or payload.get("k") != expected_kind:
            raise ApprovalInboxStale("snapshot token schema is invalid")
        return payload

    def _record_snapshot(self, snapshot: _MaterializedSnapshot) -> None:
        with self._lock:
            if snapshot.source_epoch < self._source_epoch_high_water:
                raise ApprovalInboxStale("host source epoch moved backwards")
            if snapshot.captured_at_ms < self._captured_at_high_water:
                raise ApprovalInboxStale("host source clock moved backwards")
            if (
                snapshot.source_epoch == self._source_epoch_high_water
                and self._source_digest_at_high_water is not None
                and not hmac.compare_digest(
                    snapshot.snapshot_digest, self._source_digest_at_high_water
                )
            ):
                raise ApprovalInboxStale("host source changed without advancing its epoch")
            self._source_epoch_high_water = snapshot.source_epoch
            self._source_digest_at_high_water = snapshot.snapshot_digest
            self._captured_at_high_water = snapshot.captured_at_ms
            self._snapshots[snapshot.snapshot_digest] = snapshot
            self._snapshots.move_to_end(snapshot.snapshot_digest)
            while len(self._snapshots) > MAX_SNAPSHOTS:
                self._snapshots.popitem(last=False)

    @staticmethod
    def _assert_current(
        pinned: _MaterializedSnapshot, current: _MaterializedSnapshot
    ) -> None:
        if (
            current.source_epoch != pinned.source_epoch
            or current.source_revision != pinned.source_revision
            or not hmac.compare_digest(current.snapshot_digest, pinned.snapshot_digest)
        ):
            raise ApprovalInboxStale("host source drifted from the pinned snapshot")
        if current.captured_at_ms >= pinned.valid_until_ms:
            raise ApprovalInboxStale("pinned approval snapshot expired")

    @staticmethod
    def _view(snapshot: _MaterializedSnapshot, query: InboxQuery) -> tuple[ApprovalInboxItem, ...]:
        items = tuple(
            item
            for item in snapshot.items
            if (query.workspace_id is None or item.workspace_id == query.workspace_id)
            and (query.mission_id is None or item.mission_id == query.mission_id)
            and (not query.risks or item.risk in query.risks)
            and (query.batch_eligible is None or item.batch_eligible == query.batch_eligible)
        )
        risk_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        keys: dict[str, Callable[[ApprovalInboxItem], object]] = {
            "created-desc": lambda item: (-item.created_at_ms, item.item_id),
            "expiry-asc": lambda item: (item.expires_at_ms, item.item_id),
            "item-id-asc": lambda item: item.item_id,
            "risk-desc": lambda item: (risk_order[item.risk], item.item_id),
            "workspace-asc": lambda item: (item.workspace_id, item.item_id),
        }
        return tuple(sorted(items, key=keys[query.sort]))

    def _page(
        self,
        snapshot: _MaterializedSnapshot,
        query: InboxQuery,
        offset: int,
        page_size: int,
    ) -> InboxPage:
        view = self._view(snapshot, query)
        if offset > len(view):
            raise ApprovalInboxStale("cursor offset exceeds the pinned view")
        page_items = view[offset : offset + page_size]
        token = self._encode(
            {
                "d": snapshot.snapshot_digest,
                "e": snapshot.source_epoch,
                "k": "snapshot",
                "v": CURSOR_SCHEMA_VERSION,
            }
        )
        next_offset = offset + len(page_items)
        cursor = None
        if next_offset < len(view):
            cursor = self._encode(
                {
                    "d": snapshot.snapshot_digest,
                    "e": snapshot.source_epoch,
                    "k": "cursor",
                    "o": next_offset,
                    "q": query.payload(),
                    "z": page_size,
                    "v": CURSOR_SCHEMA_VERSION,
                }
            )
        return InboxPage(
            "ready",
            SNAPSHOT_SCHEMA_VERSION,
            snapshot.snapshot_digest,
            token,
            page_items,
            len(view),
            cursor,
        )

    def open_page(
        self,
        *,
        query: InboxQuery | None = None,
        page_size: int = 20,
        environ: Mapping[str, str] | None = None,
    ) -> InboxPage:
        """Capture one trusted snapshot. Disabled mode never calls the source."""
        if not approval_inbox_enabled(environ):
            return self._disabled_page()
        if query is None:
            query = InboxQuery()
        if type(query) is not InboxQuery:
            raise ApprovalInboxContractError("query concrete type is required")
        _bounded_int(page_size, "page_size", 1, MAX_PAGE_SIZE)
        snapshot = self._source.capture()  # host callback outside internal lock
        self._record_snapshot(snapshot)
        return self._page(snapshot, query, 0, page_size)

    def continue_page(
        self,
        cursor: str,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> InboxPage:
        """Continue the exact pinned view, rejecting any host source drift."""
        if not approval_inbox_enabled(environ):
            return self._disabled_page()
        payload = self._decode(cursor, "cursor")
        digest = _digest(payload.get("d"), "snapshot_digest")
        epoch = _bounded_int(payload.get("e"), "source_epoch", 1, MAX_MONOTONIC_MS)
        offset = _bounded_int(payload.get("o"), "cursor offset", 1, MAX_ITEMS)
        page_size = _bounded_int(payload.get("z"), "page_size", 1, MAX_PAGE_SIZE)
        query_raw = payload.get("q")
        if type(query_raw) is not dict or frozenset(query_raw) != frozenset(InboxQuery().payload()):
            raise ApprovalInboxStale("cursor query is invalid")
        try:
            query = InboxQuery(
                workspace_id=query_raw["workspace_id"],
                mission_id=query_raw["mission_id"],
                risks=tuple(query_raw["risks"]),
                batch_eligible=query_raw["batch_eligible"],
                sort=query_raw["sort"],
            )
        except (KeyError, TypeError, ApprovalInboxContractError) as exc:
            raise ApprovalInboxStale("cursor query is invalid") from exc
        with self._lock:
            pinned = self._snapshots.get(digest)
        if pinned is None or pinned.source_epoch != epoch:
            raise ApprovalInboxStale("cursor snapshot is no longer available")
        current = self._source.capture()  # host callback outside internal lock
        self._record_snapshot(current)
        self._assert_current(pinned, current)
        return self._page(pinned, query, offset, page_size)

    def preview_calm_batch(
        self,
        snapshot_token: str,
        selected_item_ids: Sequence[str],
        *,
        environ: Mapping[str, str] | None = None,
    ) -> CalmBatchPreview:
        """Build a canonical review manifest. It cannot approve or dispatch."""
        if not approval_inbox_enabled(environ):
            raise ApprovalInboxDisabled(f"{APPROVAL_INBOX_FLAG} is disabled")
        token = self._decode(snapshot_token, "snapshot")
        digest = _digest(token.get("d"), "snapshot_digest")
        epoch = _bounded_int(token.get("e"), "source_epoch", 1, MAX_MONOTONIC_MS)
        if type(selected_item_ids) not in {tuple, list}:
            raise ApprovalInboxContractError("batch selection must be finite")
        if not 1 <= len(selected_item_ids) <= MAX_BATCH_ITEMS:
            raise ApprovalInboxContractError("batch selection exceeds its bound")
        selected = tuple(_safe_id(value, "item_id") for value in selected_item_ids)
        if len(set(selected)) != len(selected):
            raise ApprovalInboxContractError("batch selection contains duplicates")
        with self._lock:
            pinned = self._snapshots.get(digest)
        if pinned is None or pinned.source_epoch != epoch:
            raise ApprovalInboxStale("batch snapshot is no longer available")
        current = self._source.capture()  # host callback outside internal lock
        self._record_snapshot(current)
        self._assert_current(pinned, current)
        by_id = {item.item_id: item for item in pinned.items}
        if set(selected) - set(by_id):
            raise ApprovalInboxStale("batch selection contains an unknown exact item")
        chosen = tuple(sorted((by_id[item_id] for item_id in selected), key=lambda item: item.item_id))
        for item in chosen:
            if not item.batch_eligible or item.always_explicit or item.risk in {"high", "critical"}:
                raise ApprovalInboxContractError("batch selection contains an ineligible item")
        preview_items = tuple(
            BatchPreviewItem(item.item_id, item.item_digest, item.idempotency_key)
            for item in chosen
        )
        manifest_payload = {
            "contract": "CalmBatchPreview.v1",
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "snapshot_digest": pinned.snapshot_digest,
            "items": [
                {
                    "idempotency_key": item.idempotency_key,
                    "item_digest": item.item_digest,
                    "item_id": item.item_id,
                }
                for item in preview_items
            ],
        }
        return CalmBatchPreview(
            SNAPSHOT_SCHEMA_VERSION,
            pinned.snapshot_digest,
            preview_items,
            _sha(manifest_payload),
        )


__all__ = [
    "APPROVAL_INBOX_FLAG",
    "GRANT_INSPECTOR_STATUS",
    "ApprovalInbox",
    "ApprovalInboxContractError",
    "ApprovalInboxDisabled",
    "ApprovalInboxError",
    "ApprovalInboxItem",
    "ApprovalInboxStale",
    "ApprovalInboxUnavailable",
    "BatchPreviewItem",
    "CalmBatchPreview",
    "HostApprovalSource",
    "InboxPage",
    "InboxQuery",
    "approval_inbox_enabled",
]
