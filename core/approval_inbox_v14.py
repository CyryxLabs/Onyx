"""Phase 5.2 V14 host-owned, read-only approval inbox projection.

V14 produces authenticated *review evidence*, never authority.  The host owns
the feature gate, epoch source and inbox source.  A future approval service
must resolve the current action again from host records; it must not execute
from a page, preview, proof or handoff produced here.

The module is deliberately absent from startup/runtime/UI imports.  It exposes
no approve, deny, approval-revoke, grant, dispatch, execute or persistence API.
"""

from __future__ import annotations

import base64
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
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum


APPROVAL_INBOX_V14_FLAG = "ONYX_APPROVAL_INBOX_V14"
INBOX_V14_SCHEMA_VERSION = 10
MAX_ITEMS = 128
MAX_PAGE_SIZE = 50
MAX_BATCH_ITEMS = 32
MAX_SNAPSHOTS = 8
MAX_VIEWS = 32
MAX_PROOF_BYTES = 4_096
MAX_TEXT = 1_024
MAX_SUMMARY = 2_048
MAX_SNAPSHOT_AGE_MS = 300_000
MAX_INTEGER = 9_223_372_036_854_775_807
MAX_COST_MICRO = 1_000_000_000_000_000
MAX_SOURCE_CALLBACKS = 1

_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]+\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")
_RISKS = frozenset({"low", "medium", "high", "critical"})
_DATA_CLASSES = frozenset({"public", "internal", "confidential", "restricted"})
_EGRESS = frozenset({"none", "local-only", "named-account", "public"})
_REVERSIBILITY = frozenset({"reversible", "compensating-action", "irreversible"})
_SORTS = frozenset({"created-desc", "expiry-asc", "item-id-asc", "risk-desc"})
_SECRET = re.compile(
    r"(?i)(?:api[-_ ]?key|authorization|bearer|client[-_ ]?secret|password|"
    r"private[-_ ]?key|refresh[-_ ]?token|secret|token)\s*[:=]\s*\S+"
)


class ApprovalInboxV14Error(RuntimeError):
    """Base V14 failure."""


class ApprovalInboxV14ContractError(ValueError):
    """Caller or host data violated the bounded V14 contract."""


class ApprovalInboxV14Unavailable(ApprovalInboxV14Error):
    """Projection cannot safely produce a result."""


class ApprovalInboxV14State(str, Enum):
    DISABLED = "DISABLED"
    READY = "READY"
    STALE = "STALE"
    REVOKED = "REVOKED"
    INTEGRITY_LATCHED = "INTEGRITY_LATCHED"


def _bounded_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ApprovalInboxV14ContractError(f"{label} is out of bounds")
    return value


def _bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ApprovalInboxV14ContractError(f"{label} is not boolean")
    return value


def _safe_text(value: object, label: str, maximum: int = MAX_TEXT) -> str:
    if (
        type(value) is not str
        or value != value.strip()
        or not value
        or len(value) > maximum
    ):
        raise ApprovalInboxV14ContractError(f"{label} is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ApprovalInboxV14ContractError(f"{label} contains control characters")
    if _SECRET.search(value):
        raise ApprovalInboxV14ContractError(f"{label} contains secret-like material")
    return value


def _safe_id(value: object, label: str) -> str:
    text = _safe_text(value, label, 64)
    if not _ID.fullmatch(text):
        raise ApprovalInboxV14ContractError(f"{label} is not canonical")
    return text


def _digest(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not _DIGEST.fullmatch(value)
        or value in {"0" * 64, "f" * 64}
    ):
        raise ApprovalInboxV14ContractError(f"{label} is not a canonical digest")
    return value


def _enum(value: object, allowed: frozenset[str], label: str) -> str:
    if type(value) is not str or value not in allowed:
        raise ApprovalInboxV14ContractError(f"{label} is invalid")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode()


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class ApprovalInboxFeatureGateV14:
    """Host-owned, bootstrap-only flag with a pinned monotonic flag epoch.

    ``epoch_reader`` is a host callback, not request input.  Any change from the
    bootstrap epoch permanently retires this gate instance.  Re-enabling needs
    a new gate and projection, so a revoked projection cannot resurrect.
    """

    __slots__ = ("_boot_epoch", "_enabled", "_epoch_reader", "_lock", "_revoked")

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        epoch_reader: Callable[[], int],
    ) -> None:
        if not callable(epoch_reader):
            raise ApprovalInboxV14ContractError("epoch_reader is required")
        source = os.environ if environ is None else environ
        raw = source.get(APPROVAL_INBOX_V14_FLAG, "")
        if type(raw) is not str:
            raise ApprovalInboxV14ContractError("feature flag is not text")
        self._enabled = raw.strip().casefold() in {"1", "true"}
        self._epoch_reader = epoch_reader
        self._lock = threading.RLock()
        self._revoked = False
        self._boot_epoch = self._read_epoch()

    def _read_epoch(self) -> int:
        try:
            value = self._epoch_reader()
        except BaseException:
            raise ApprovalInboxV14Unavailable("feature-epoch-unavailable") from None
        return _bounded_int(value, "feature_epoch", 0, MAX_INTEGER)

    @property
    def bootstrap_epoch(self) -> int:
        return self._boot_epoch

    @property
    def enabled_at_bootstrap(self) -> bool:
        return self._enabled

    def state(self) -> ApprovalInboxV14State:
        with self._lock:
            if self._revoked:
                return ApprovalInboxV14State.REVOKED
            if not self._enabled:
                return ApprovalInboxV14State.DISABLED
        current = self._read_epoch()
        with self._lock:
            # Another thread may have completed revocation while this thread's
            # host epoch callback was in flight.  Terminal state always wins,
            # even when this callback returns the old bootstrap epoch.
            if self._revoked:
                return ApprovalInboxV14State.REVOKED
            if current != self._boot_epoch:
                self._revoked = True
                return ApprovalInboxV14State.REVOKED
            return ApprovalInboxV14State.READY

    @contextmanager
    def _publication_barrier(self):
        """Linearize a READY publication against host epoch revocation."""

        with self._lock:
            if self._revoked:
                raise ApprovalInboxV14Unavailable("feature-epoch-revoked")
            if not self._enabled:
                raise ApprovalInboxV14Unavailable("disabled")
        current = self._read_epoch()
        with self._lock:
            # The post-callback terminal check is deliberately first.
            if self._revoked:
                raise ApprovalInboxV14Unavailable("feature-epoch-revoked")
            if current != self._boot_epoch:
                self._revoked = True
                raise ApprovalInboxV14Unavailable("feature-epoch-revoked")
            yield


class MonotonicInboxClockV14:
    __slots__ = ("_failed", "_high_water", "_lock")

    def __init__(self) -> None:
        self._failed = False
        self._high_water = time.monotonic_ns() // 1_000_000
        self._lock = threading.RLock()

    def now_ms(self) -> int:
        current = time.monotonic_ns() // 1_000_000
        with self._lock:
            if self._failed or current < self._high_water:
                self._failed = True
                raise ApprovalInboxV14Unavailable("monotonic-clock-rollback")
            self._high_water = current
            return current


class DeterministicInboxClockV14:
    __slots__ = ("_current", "_failed", "_high_water", "_lock")

    def __init__(self, initial_ms: int = 1) -> None:
        value = _bounded_int(initial_ms, "initial_ms", 0, MAX_INTEGER)
        self._current = value
        self._failed = False
        self._high_water = value
        self._lock = threading.RLock()

    def now_ms(self) -> int:
        with self._lock:
            if self._failed or self._current < self._high_water:
                self._failed = True
                raise ApprovalInboxV14Unavailable("monotonic-clock-rollback")
            self._high_water = self._current
            return self._current

    def advance(self, milliseconds: int) -> None:
        delta = _bounded_int(milliseconds, "milliseconds", 0, MAX_INTEGER)
        with self._lock:
            if self._current > MAX_INTEGER - delta:
                raise ApprovalInboxV14ContractError("clock overflow")
            self._current += delta

    def set_for_test(self, milliseconds: int) -> None:
        value = _bounded_int(milliseconds, "milliseconds", 0, MAX_INTEGER)
        with self._lock:
            self._current = value


@dataclass(frozen=True, slots=True)
class HostInboxItemV14:
    """Exact host output. Every meaningful action/context field is explicit."""

    item_id: object
    action_request_id: object
    principal_id: object
    session_id: object
    workspace_id: object
    workspace_display: object
    mission_id: object
    mission_display: object
    account_id: object
    account_display: object
    connector_id: object
    connector_version: object
    tool_id: object
    operation: object
    environment: object
    reason: object
    target_display: object
    target_digest: object
    payload_summary: object
    payload_digest: object
    attachment_set_digest: object
    policy_version: object
    action_schema_version: object
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
class HostInboxSnapshotV14:
    source_epoch: object
    captured_at_ms: object
    items: object


class HostInboxSourceV14:
    """Pinned identity and bounded single-flight host capture callback."""

    __slots__ = ("_capture_callback", "_principal_id", "_semaphore", "_session_id")

    def __init__(
        self,
        *,
        principal_id: str,
        session_id: str,
        capture_callback: Callable[[], HostInboxSnapshotV14],
    ) -> None:
        self._principal_id = _safe_id(principal_id, "principal_id")
        self._session_id = _safe_id(session_id, "session_id")
        if not callable(capture_callback):
            raise ApprovalInboxV14ContractError("capture_callback is required")
        self._capture_callback = capture_callback
        self._semaphore = threading.BoundedSemaphore(MAX_SOURCE_CALLBACKS)

    @property
    def principal_id(self) -> str:
        return self._principal_id

    @property
    def session_id(self) -> str:
        return self._session_id

    def capture(self) -> HostInboxSnapshotV14:
        if not self._semaphore.acquire(blocking=False):
            raise ApprovalInboxV14Unavailable("source-single-flight-busy")
        try:
            failed = False
            try:
                result = self._capture_callback()
            except BaseException:
                failed = True
                result = None
            # Leave the handler before raising so the raw host exception is
            # not retained as a public cause or context.
            if failed:
                raise ApprovalInboxV14Unavailable("source-callback-failed")
            if type(result) is not HostInboxSnapshotV14:
                raise ApprovalInboxV14ContractError(
                    "source returned wrong snapshot type"
                )
            return result
        finally:
            self._semaphore.release()


@dataclass(frozen=True, slots=True)
class InboxQueryV14:
    workspace_id: str | None = None
    mission_id: str | None = None
    risks: tuple[str, ...] = ()
    data_classes: tuple[str, ...] = ()
    batch_only: bool = False
    sort: str = "created-desc"

    def canonical(self) -> dict[str, object]:
        workspace = (
            None
            if self.workspace_id is None
            else _safe_id(self.workspace_id, "workspace_id")
        )
        mission = (
            None if self.mission_id is None else _safe_id(self.mission_id, "mission_id")
        )
        if type(self.risks) is not tuple or len(self.risks) > len(_RISKS):
            raise ApprovalInboxV14ContractError("risks is invalid")
        risks = tuple(_enum(value, _RISKS, "risk") for value in self.risks)
        if len(set(risks)) != len(risks):
            raise ApprovalInboxV14ContractError("risks contains duplicates")
        if type(self.data_classes) is not tuple or len(self.data_classes) > len(
            _DATA_CLASSES
        ):
            raise ApprovalInboxV14ContractError("data_classes is invalid")
        data_classes = tuple(
            _enum(value, _DATA_CLASSES, "data_class") for value in self.data_classes
        )
        if len(set(data_classes)) != len(data_classes):
            raise ApprovalInboxV14ContractError("data_classes contains duplicates")
        return {
            "batch_only": _bool(self.batch_only, "batch_only"),
            "data_classes": sorted(data_classes),
            "mission_id": mission,
            "risks": sorted(risks),
            "sort": _enum(self.sort, _SORTS, "sort"),
            "workspace_id": workspace,
        }


@dataclass(frozen=True, slots=True)
class ApprovalReviewItemV14:
    item_id: str
    action_request_id: str
    action_fingerprint: str
    workspace_id: str
    workspace_display: str
    mission_id: str
    mission_display: str
    account_display: str
    connector_display: str
    action_display: str
    environment: str
    reason: str
    target_display: str
    target_digest: str
    payload_summary: str
    payload_digest: str
    attachment_set_digest: str
    policy_version: str
    action_schema_version: str
    data_class: str
    egress: str
    effect_summary: str
    reversibility: str
    idempotency_summary: str
    idempotency_identity: str
    verification_plan: str
    rollback_plan: str
    cost_micro: int
    currency: str
    risk: str
    created_at_ms: int
    expires_at_ms: int
    always_explicit: bool
    batch_eligible: bool
    review_proof: str
    authority_granted: bool = field(default=False, init=False)
    approval_action_available: bool = field(default=False, init=False)
    execution_available: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class InboxPageV14:
    state: ApprovalInboxV14State
    snapshot_id: str
    snapshot_digest: str
    view_digest: str
    page_digest: str
    created_monotonic_ms: int
    deadline_monotonic_ms: int
    total_items: int
    page_size: int
    offset: int
    items: tuple[ApprovalReviewItemV14, ...]
    next_cursor: str | None
    authority_granted: bool = field(default=False, init=False)
    approval_action_available: bool = field(default=False, init=False)
    execution_available: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class CalmBatchPreviewV14:
    snapshot_id: str
    view_digest: str
    preview_digest: str
    item_count: int
    items: tuple[ApprovalReviewItemV14, ...]
    revalidation_required: bool = field(default=True, init=False)
    authority_granted: bool = field(default=False, init=False)
    approval_action_available: bool = field(default=False, init=False)
    execution_available: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class ReviewSelectionHandoffV14:
    """Non-authoritative identifiers for a future host-side re-resolution."""

    snapshot_id: str
    view_digest: str
    handoff_digest: str
    item_ids: tuple[str, ...]
    action_request_ids: tuple[str, ...]
    action_fingerprints: tuple[str, ...]
    review_proof_digests: tuple[str, ...]
    instruction: str = field(
        default="future-approval-must-re-resolve-all-host-action-fields",
        init=False,
    )
    revalidation_required: bool = field(default=True, init=False)
    authority_granted: bool = field(default=False, init=False)
    approval_action_available: bool = field(default=False, init=False)
    execution_available: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class _SnapshotRecord:
    snapshot_id: str
    source_epoch: int
    semantic_digest: str
    created_ms: int
    deadline_ms: int
    items: tuple[dict[str, object], ...]
    generation: int


@dataclass(slots=True)
class _ViewRecord:
    snapshot_id: str
    view_digest: str
    query: dict[str, object]
    page_size: int
    item_ids: tuple[str, ...]
    returned_proofs: dict[str, str]


class ApprovalInboxProjectionV14:
    """Bounded, fail-closed read projection with terminal invalidation latches."""

    __slots__ = (
        "_clock",
        "_gate",
        "_hmac_key",
        "_highest_source_epoch",
        "_current_integrity_digest",
        "_lock",
        "_snapshots",
        "_source",
        "_source_generation",
        "_state",
        "_views",
    )

    def __init__(
        self,
        *,
        gate: ApprovalInboxFeatureGateV14,
        source: HostInboxSourceV14,
        clock: MonotonicInboxClockV14 | DeterministicInboxClockV14,
    ) -> None:
        if type(gate) is not ApprovalInboxFeatureGateV14:
            raise ApprovalInboxV14ContractError("exact feature gate required")
        if type(source) is not HostInboxSourceV14:
            raise ApprovalInboxV14ContractError("exact source required")
        if type(clock) not in {MonotonicInboxClockV14, DeterministicInboxClockV14}:
            raise ApprovalInboxV14ContractError("exact monotonic clock required")
        self._gate = gate
        self._source = source
        self._clock = clock
        self._hmac_key = secrets.token_bytes(32)
        self._lock = threading.RLock()
        self._snapshots: OrderedDict[str, _SnapshotRecord] = OrderedDict()
        self._views: OrderedDict[str, _ViewRecord] = OrderedDict()
        self._highest_source_epoch = -1
        self._source_generation = 0
        # The highest accepted source epoch and its semantic digest are the
        # complete rollback/equivocation guard.  Older digests are neither
        # needed nor retained, so monotonically increasing host epochs cannot
        # grow projection memory.
        self._current_integrity_digest: str | None = None
        self._state = gate.state()

    @property
    def state(self) -> ApprovalInboxV14State:
        with self._lock:
            if self._state in {
                ApprovalInboxV14State.STALE,
                ApprovalInboxV14State.REVOKED,
                ApprovalInboxV14State.INTEGRITY_LATCHED,
            }:
                return self._state
        try:
            with self._gate._publication_barrier():
                with self._lock:
                    if self._state in {
                        ApprovalInboxV14State.STALE,
                        ApprovalInboxV14State.REVOKED,
                        ApprovalInboxV14State.INTEGRITY_LATCHED,
                    }:
                        return self._state
                    try:
                        self._clock.now_ms()
                    except ApprovalInboxV14Error:
                        self._state = ApprovalInboxV14State.INTEGRITY_LATCHED
                        self._source_generation += 1
                        self._snapshots.clear()
                        self._views.clear()
                        return self._state
                    self._state = ApprovalInboxV14State.READY
                    return self._state
        except ApprovalInboxV14Unavailable as error:
            with self._lock:
                if str(error) == "disabled":
                    self._state = ApprovalInboxV14State.DISABLED
                elif self._state not in {
                    ApprovalInboxV14State.STALE,
                    ApprovalInboxV14State.REVOKED,
                    ApprovalInboxV14State.INTEGRITY_LATCHED,
                }:
                    self._state = ApprovalInboxV14State.REVOKED
                    self._source_generation += 1
                self._snapshots.clear()
                self._views.clear()
                return self._state

    def _terminal(self, state: ApprovalInboxV14State, code: str) -> None:
        with self._lock:
            self._state = state
            self._source_generation += 1
            self._snapshots.clear()
            self._views.clear()
        raise ApprovalInboxV14Unavailable(code)

    @contextmanager
    def _publication(
        self,
        record: _SnapshotRecord | None = None,
        view: _ViewRecord | None = None,
    ):
        """Hold both invalidation locks through the output linearization point."""

        try:
            with self._gate._publication_barrier():
                with self._lock:
                    if self._state in {
                        ApprovalInboxV14State.STALE,
                        ApprovalInboxV14State.REVOKED,
                        ApprovalInboxV14State.INTEGRITY_LATCHED,
                    }:
                        raise ApprovalInboxV14Unavailable(self._state.value.casefold())
                    try:
                        now = self._clock.now_ms()
                    except ApprovalInboxV14Error:
                        self._terminal(
                            ApprovalInboxV14State.INTEGRITY_LATCHED,
                            "clock-integrity-latched",
                        )
                    if record is not None:
                        if (
                            record.generation != self._source_generation
                            or record.source_epoch != self._highest_source_epoch
                            or self._snapshots.get(record.snapshot_id) is not record
                        ):
                            raise ApprovalInboxV14Unavailable("source-epoch-superseded")
                        if now > record.deadline_ms:
                            self._terminal(
                                ApprovalInboxV14State.STALE, "snapshot-stale"
                            )
                    if view is not None and (
                        self._views.get(view.view_digest) is not view
                        or record is None
                        or view.snapshot_id != record.snapshot_id
                    ):
                        raise ApprovalInboxV14Unavailable("view-state-unavailable")
                    self._state = ApprovalInboxV14State.READY
                    yield now
        except ApprovalInboxV14Unavailable as error:
            code = str(error)
            if code in {"disabled", "feature-epoch-revoked"}:
                with self._lock:
                    if code == "disabled":
                        self._state = ApprovalInboxV14State.DISABLED
                    elif self._state not in {
                        ApprovalInboxV14State.STALE,
                        ApprovalInboxV14State.REVOKED,
                        ApprovalInboxV14State.INTEGRITY_LATCHED,
                    }:
                        self._state = ApprovalInboxV14State.REVOKED
                        self._source_generation += 1
                    self._snapshots.clear()
                    self._views.clear()
            raise

    def _guard(self) -> int:
        with self._publication() as now:
            return now

    def _normalize_item(self, raw: HostInboxItemV14) -> dict[str, object]:
        if type(raw) is not HostInboxItemV14:
            raise ApprovalInboxV14ContractError("source item has wrong type")
        principal_id = _safe_id(raw.principal_id, "principal_id")
        session_id = _safe_id(raw.session_id, "session_id")
        if (
            principal_id != self._source.principal_id
            or session_id != self._source.session_id
        ):
            raise ApprovalInboxV14ContractError("source identity mismatch")
        cost = _bounded_int(raw.cost_micro, "cost_micro", 0, MAX_COST_MICRO)
        currency = _safe_text(raw.currency, "currency", 3)
        if not _CURRENCY.fullmatch(currency):
            raise ApprovalInboxV14ContractError("currency is invalid")
        created = _bounded_int(raw.created_at_ms, "created_at_ms", 0, MAX_INTEGER)
        expires = _bounded_int(raw.expires_at_ms, "expires_at_ms", 1, MAX_INTEGER)
        if expires <= created:
            raise ApprovalInboxV14ContractError("item expiry is not after creation")
        item: dict[str, object] = {
            "item_id": _safe_id(raw.item_id, "item_id"),
            "action_request_id": _safe_id(raw.action_request_id, "action_request_id"),
            "principal_id": principal_id,
            "session_id": session_id,
            "workspace_id": _safe_id(raw.workspace_id, "workspace_id"),
            "workspace_display": _safe_text(raw.workspace_display, "workspace_display"),
            "mission_id": _safe_id(raw.mission_id, "mission_id"),
            "mission_display": _safe_text(raw.mission_display, "mission_display"),
            "account_id": _safe_id(raw.account_id, "account_id"),
            "account_display": _safe_text(raw.account_display, "account_display"),
            "connector_id": _safe_id(raw.connector_id, "connector_id"),
            "connector_version": _safe_text(
                raw.connector_version, "connector_version", 64
            ),
            "tool_id": _safe_id(raw.tool_id, "tool_id"),
            "operation": _safe_id(raw.operation, "operation"),
            "environment": _safe_text(raw.environment, "environment", 64),
            "reason": _safe_text(raw.reason, "reason", MAX_SUMMARY),
            "target_display": _safe_text(
                raw.target_display, "target_display", MAX_SUMMARY
            ),
            "target_digest": _digest(raw.target_digest, "target_digest"),
            "payload_summary": _safe_text(
                raw.payload_summary, "payload_summary", MAX_SUMMARY
            ),
            "payload_digest": _digest(raw.payload_digest, "payload_digest"),
            "attachment_set_digest": _digest(
                raw.attachment_set_digest, "attachment_set_digest"
            ),
            "policy_version": _safe_text(raw.policy_version, "policy_version", 64),
            "action_schema_version": _safe_text(
                raw.action_schema_version, "action_schema_version", 64
            ),
            "data_class": _enum(raw.data_class, _DATA_CLASSES, "data_class"),
            "egress": _enum(raw.egress, _EGRESS, "egress"),
            "effect_summary": _safe_text(
                raw.effect_summary, "effect_summary", MAX_SUMMARY
            ),
            "reversibility": _enum(raw.reversibility, _REVERSIBILITY, "reversibility"),
            "idempotency_summary": _safe_text(
                raw.idempotency_summary, "idempotency_summary"
            ),
            "idempotency_key": _digest(raw.idempotency_key, "idempotency_key"),
            "verification_plan": _safe_text(
                raw.verification_plan, "verification_plan", MAX_SUMMARY
            ),
            "rollback_plan": _safe_text(
                raw.rollback_plan, "rollback_plan", MAX_SUMMARY
            ),
            "cost_micro": cost,
            "currency": currency,
            "risk": _enum(raw.risk, _RISKS, "risk"),
            "created_at_ms": created,
            "expires_at_ms": expires,
            "always_explicit": _bool(raw.always_explicit, "always_explicit"),
            "batch_eligible": _bool(raw.batch_eligible, "batch_eligible"),
        }
        # Review/display identifiers and timestamps are intentionally excluded:
        # two inbox rows for the same meaningful action must collide and be
        # rejected by calm-batch selection rather than evade duplicate checks.
        item["action_fingerprint"] = _sha(
            {
                "contract": "OnyxActionBinding.v14",
                "principal_id": item["principal_id"],
                "session_id": item["session_id"],
                "workspace_id": item["workspace_id"],
                "mission_id": item["mission_id"],
                "account_id": item["account_id"],
                "connector_id": item["connector_id"],
                "connector_version": item["connector_version"],
                "tool_id": item["tool_id"],
                "operation": item["operation"],
                "environment": item["environment"],
                "target_digest": item["target_digest"],
                "payload_digest": item["payload_digest"],
                "attachment_set_digest": item["attachment_set_digest"],
                "policy_version": item["policy_version"],
                "action_schema_version": item["action_schema_version"],
                "data_class": item["data_class"],
                "egress": item["egress"],
                "reversibility": item["reversibility"],
                "idempotency_key": item["idempotency_key"],
                "cost_micro": item["cost_micro"],
                "currency": item["currency"],
                "risk": item["risk"],
                "expires_at_ms": item["expires_at_ms"],
                "always_explicit": item["always_explicit"],
                "batch_eligible": item["batch_eligible"],
            }
        )
        return item

    def _capture(self, now: int) -> _SnapshotRecord:
        # Deliberately outside the projection lock.
        raw = self._source.capture()
        epoch = _bounded_int(raw.source_epoch, "source_epoch", 0, MAX_INTEGER)
        _bounded_int(raw.captured_at_ms, "captured_at_ms", 0, MAX_INTEGER)
        if type(raw.items) is not tuple or len(raw.items) > MAX_ITEMS:
            raise ApprovalInboxV14ContractError("snapshot items are invalid")
        items = tuple(self._normalize_item(item) for item in raw.items)
        ids = [str(item["item_id"]) for item in items]
        if len(ids) != len(set(ids)):
            raise ApprovalInboxV14ContractError("duplicate item_id")
        semantic = _sha({"contract": "HostInboxSemantic.v14", "items": items})
        # Re-enter the host epoch and terminal-state barrier after the callback.
        # The yielded time is authoritative for cache creation.
        with self._publication() as published_now:
            now = published_now
            if epoch < self._highest_source_epoch:
                self._state = ApprovalInboxV14State.INTEGRITY_LATCHED
            elif epoch == self._highest_source_epoch and (
                self._current_integrity_digest is None
                or not hmac.compare_digest(self._current_integrity_digest, semantic)
            ):
                self._state = ApprovalInboxV14State.INTEGRITY_LATCHED
            if self._state is ApprovalInboxV14State.INTEGRITY_LATCHED:
                self._snapshots.clear()
                self._views.clear()
                raise ApprovalInboxV14Unavailable("source-integrity-latched")
            if epoch > self._highest_source_epoch and self._highest_source_epoch >= 0:
                # A new authoritative source epoch invalidates every prior
                # cursor/review proof immediately.  Installing the new digest
                # under this lock replaces (and therefore discards) the prior
                # epoch digest atomically with the new high-water epoch.
                self._source_generation += 1
                self._snapshots.clear()
                self._views.clear()
            elif self._highest_source_epoch < 0:
                self._source_generation += 1
            if epoch > self._highest_source_epoch:
                self._highest_source_epoch = epoch
                self._current_integrity_digest = semantic
            # Exact semantic reuse keeps the original creation/deadline/proofs.
            for record in self._snapshots.values():
                if record.source_epoch == epoch and hmac.compare_digest(
                    record.semantic_digest, semantic
                ):
                    if now > record.deadline_ms:
                        self._state = ApprovalInboxV14State.STALE
                        self._snapshots.clear()
                        self._views.clear()
                        raise ApprovalInboxV14Unavailable("snapshot-stale")
                    return record
            if now > MAX_INTEGER - MAX_SNAPSHOT_AGE_MS:
                self._state = ApprovalInboxV14State.INTEGRITY_LATCHED
                raise ApprovalInboxV14Unavailable("deadline-overflow")
            snapshot_id = _sha(
                {
                    "contract": "ApprovalInboxSnapshot.v14",
                    "epoch": epoch,
                    "semantic_digest": semantic,
                    "created_ms": now,
                    "flag_epoch": self._gate.bootstrap_epoch,
                }
            )
            record = _SnapshotRecord(
                snapshot_id=snapshot_id,
                source_epoch=epoch,
                semantic_digest=semantic,
                created_ms=now,
                deadline_ms=now + MAX_SNAPSHOT_AGE_MS,
                items=items,
                generation=self._source_generation,
            )
            self._snapshots[snapshot_id] = record
            while len(self._snapshots) > MAX_SNAPSHOTS:
                removed, _ = self._snapshots.popitem(last=False)
                for key in [
                    key
                    for key, view in self._views.items()
                    if view.snapshot_id == removed
                ]:
                    del self._views[key]
            return record

    def _token(self, kind: str, payload: dict[str, object]) -> str:
        body = _canonical({"kind": kind, "schema": INBOX_V14_SCHEMA_VERSION, **payload})
        encoded = base64.urlsafe_b64encode(body).rstrip(b"=").decode()
        mac = hmac.new(self._hmac_key, body, hashlib.sha256).hexdigest()
        return f"{encoded}.{mac}"

    def _untoken(self, token: object, kind: str) -> dict[str, object]:
        if (
            type(token) is not str
            or not token
            or len(token) > MAX_PROOF_BYTES
            or token.count(".") != 1
        ):
            raise ApprovalInboxV14ContractError("token is malformed")
        encoded, mac = token.split(".")
        if not _TOKEN.fullmatch(encoded) or not _DIGEST.fullmatch(mac):
            raise ApprovalInboxV14ContractError("token is malformed")
        try:
            body = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            decoded = json.loads(body)
        except (ValueError, UnicodeError, json.JSONDecodeError):
            raise ApprovalInboxV14ContractError("token is malformed") from None
        expected = hmac.new(self._hmac_key, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            raise ApprovalInboxV14ContractError("token authentication failed")
        if (
            type(decoded) is not dict
            or decoded.get("kind") != kind
            or decoded.get("schema") != 10
        ):
            raise ApprovalInboxV14ContractError("token relation is invalid")
        return decoded

    @staticmethod
    def _filter_sort(
        items: tuple[dict[str, object], ...], query: dict[str, object]
    ) -> tuple[dict[str, object], ...]:
        visible = [
            item
            for item in items
            if (
                query["workspace_id"] is None
                or item["workspace_id"] == query["workspace_id"]
            )
            and (
                query["mission_id"] is None or item["mission_id"] == query["mission_id"]
            )
            and (not query["risks"] or item["risk"] in query["risks"])
            and (
                not query["data_classes"] or item["data_class"] in query["data_classes"]
            )
            and (
                not query["batch_only"]
                or (
                    item["batch_eligible"]
                    and not item["always_explicit"]
                    and item["risk"] in {"low", "medium"}
                )
            )
        ]
        sort = query["sort"]
        if sort == "created-desc":
            visible.sort(
                key=lambda item: (-int(item["created_at_ms"]), str(item["item_id"]))
            )
        elif sort == "expiry-asc":
            visible.sort(
                key=lambda item: (int(item["expires_at_ms"]), str(item["item_id"]))
            )
        elif sort == "risk-desc":
            rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
            visible.sort(
                key=lambda item: (-rank[str(item["risk"])], str(item["item_id"]))
            )
        else:
            visible.sort(key=lambda item: str(item["item_id"]))
        return tuple(visible)

    def _review_item(
        self, record: _SnapshotRecord, view: _ViewRecord, item: dict[str, object]
    ) -> ApprovalReviewItemV14:
        item_id = str(item["item_id"])
        proof_payload = {
            "snapshot_id": record.snapshot_id,
            "snapshot_digest": record.semantic_digest,
            "view_digest": view.view_digest,
            "item_id": item_id,
            "action_fingerprint": item["action_fingerprint"],
            "review_fields_digest": _sha(item),
            "deadline_ms": record.deadline_ms,
        }
        proof = self._token("review", proof_payload)
        prior = view.returned_proofs.get(item_id)
        if prior is not None and not hmac.compare_digest(prior, proof):
            self._terminal(
                ApprovalInboxV14State.INTEGRITY_LATCHED, "review-proof-equivocation"
            )
        view.returned_proofs[item_id] = proof
        return ApprovalReviewItemV14(
            item_id=item_id,
            action_request_id=str(item["action_request_id"]),
            action_fingerprint=str(item["action_fingerprint"]),
            workspace_id=str(item["workspace_id"]),
            workspace_display=str(item["workspace_display"]),
            mission_id=str(item["mission_id"]),
            mission_display=str(item["mission_display"]),
            account_display=str(item["account_display"]),
            connector_display=f"{item['connector_id']}@{item['connector_version']}",
            action_display=f"{item['tool_id']}.{item['operation']}",
            environment=str(item["environment"]),
            reason=str(item["reason"]),
            target_display=str(item["target_display"]),
            target_digest=str(item["target_digest"]),
            payload_summary=str(item["payload_summary"]),
            payload_digest=str(item["payload_digest"]),
            attachment_set_digest=str(item["attachment_set_digest"]),
            policy_version=str(item["policy_version"]),
            action_schema_version=str(item["action_schema_version"]),
            data_class=str(item["data_class"]),
            egress=str(item["egress"]),
            effect_summary=str(item["effect_summary"]),
            reversibility=str(item["reversibility"]),
            idempotency_summary=str(item["idempotency_summary"]),
            idempotency_identity=str(item["idempotency_key"]),
            verification_plan=str(item["verification_plan"]),
            rollback_plan=str(item["rollback_plan"]),
            cost_micro=int(item["cost_micro"]),
            currency=str(item["currency"]),
            risk=str(item["risk"]),
            created_at_ms=int(item["created_at_ms"]),
            expires_at_ms=int(item["expires_at_ms"]),
            always_explicit=bool(item["always_explicit"]),
            batch_eligible=bool(item["batch_eligible"]),
            review_proof=proof,
        )

    def _page(
        self, record: _SnapshotRecord, view: _ViewRecord, offset: int, _now: int
    ) -> InboxPageV14:
        # This is the final pre-output gate.  Locks remain held through object
        # construction so a completed revocation or newer source generation
        # always linearizes before (and suppresses) stale publication.
        with self._publication(record, view):
            visible_by_id = {str(item["item_id"]): item for item in record.items}
            ordered = tuple(visible_by_id[item_id] for item_id in view.item_ids)
            if not 0 <= offset <= len(ordered) or (offset and offset % view.page_size):
                raise ApprovalInboxV14ContractError("cursor offset is invalid")
            selected = ordered[offset : offset + view.page_size]
            reviews = tuple(self._review_item(record, view, item) for item in selected)
            next_offset = offset + len(reviews)
            next_cursor = None
            if next_offset < len(ordered):
                next_cursor = self._token(
                    "cursor",
                    {
                        "snapshot_id": record.snapshot_id,
                        "view_digest": view.view_digest,
                        "offset": next_offset,
                        "page_size": view.page_size,
                        "item_ids_digest": _sha(view.item_ids),
                        "deadline_ms": record.deadline_ms,
                    },
                )
            page_payload = {
                "snapshot_id": record.snapshot_id,
                "snapshot_digest": record.semantic_digest,
                "view_digest": view.view_digest,
                "offset": offset,
                "page_size": view.page_size,
                "total_items": len(ordered),
                "item_review_proofs": [review.review_proof for review in reviews],
                "next_cursor_digest": None
                if next_cursor is None
                else hashlib.sha256(next_cursor.encode()).hexdigest(),
                "deadline_ms": record.deadline_ms,
            }
            return InboxPageV14(
                state=ApprovalInboxV14State.READY,
                snapshot_id=record.snapshot_id,
                snapshot_digest=record.semantic_digest,
                view_digest=view.view_digest,
                page_digest=_sha(page_payload),
                created_monotonic_ms=record.created_ms,
                deadline_monotonic_ms=record.deadline_ms,
                total_items=len(ordered),
                page_size=view.page_size,
                offset=offset,
                items=reviews,
                next_cursor=next_cursor,
            )

    def open_page(
        self, *, query: InboxQueryV14 | None = None, page_size: int = 20
    ) -> InboxPageV14:
        now = self._guard()
        size = _bounded_int(page_size, "page_size", 1, MAX_PAGE_SIZE)
        if query is None:
            query = InboxQueryV14()
        if type(query) is not InboxQueryV14:
            raise ApprovalInboxV14ContractError("exact query type required")
        canonical_query = query.canonical()
        record = self._capture(now)
        visible = self._filter_sort(record.items, canonical_query)
        item_ids = tuple(str(item["item_id"]) for item in visible)
        view_digest = _sha(
            {
                "contract": "ApprovalInboxView.v14",
                "snapshot_id": record.snapshot_id,
                "query": canonical_query,
                "page_size": size,
                "item_ids": item_ids,
            }
        )
        with self._publication(record) as now:
            view = self._views.get(view_digest)
            if view is None:
                view = _ViewRecord(
                    record.snapshot_id, view_digest, canonical_query, size, item_ids, {}
                )
                self._views[view_digest] = view
                while len(self._views) > MAX_VIEWS:
                    self._views.popitem(last=False)
            elif (
                view.snapshot_id != record.snapshot_id
                or view.query != canonical_query
                or view.page_size != size
                or view.item_ids != item_ids
            ):
                self._terminal(
                    ApprovalInboxV14State.INTEGRITY_LATCHED, "view-digest-collision"
                )
        return self._page(record, view, 0, now)

    def continue_page(self, cursor: object) -> InboxPageV14:
        now = self._guard()
        decoded = self._untoken(cursor, "cursor")
        snapshot_id = decoded.get("snapshot_id")
        view_digest = decoded.get("view_digest")
        if type(snapshot_id) is not str or type(view_digest) is not str:
            raise ApprovalInboxV14ContractError("cursor relation is invalid")
        with self._lock:
            record = self._snapshots.get(snapshot_id)
            view = self._views.get(view_digest)
            if record is None or view is None or view.snapshot_id != snapshot_id:
                raise ApprovalInboxV14Unavailable("cursor-state-unavailable")
            if decoded.get("page_size") != view.page_size:
                raise ApprovalInboxV14ContractError("cursor page size mismatch")
            if decoded.get("item_ids_digest") != _sha(view.item_ids):
                raise ApprovalInboxV14ContractError("cursor item set mismatch")
            if decoded.get("deadline_ms") != record.deadline_ms:
                raise ApprovalInboxV14ContractError("cursor deadline mismatch")
            offset = _bounded_int(
                decoded.get("offset"), "offset", 0, len(view.item_ids)
            )
        return self._page(record, view, offset, now)

    def _resolve_selections(
        self,
        snapshot_id: object,
        view_digest: object,
        selections: Sequence[tuple[str, str]],
        now: int,
    ) -> tuple[_SnapshotRecord, _ViewRecord, tuple[ApprovalReviewItemV14, ...]]:
        snapshot_key = _digest(snapshot_id, "snapshot_id")
        view_key = _digest(view_digest, "view_digest")
        if (
            type(selections) not in {tuple, list}
            or not 1 <= len(selections) <= MAX_BATCH_ITEMS
        ):
            raise ApprovalInboxV14ContractError("selections are invalid")
        normalized: list[tuple[str, str]] = []
        for selection in selections:
            if type(selection) is not tuple or len(selection) != 2:
                raise ApprovalInboxV14ContractError("selection is invalid")
            item_id = _safe_id(selection[0], "item_id")
            proof = selection[1]
            if type(proof) is not str or len(proof) > MAX_PROOF_BYTES:
                raise ApprovalInboxV14ContractError("review_proof is invalid")
            normalized.append((item_id, proof))
        if len({item_id for item_id, _ in normalized}) != len(normalized):
            raise ApprovalInboxV14ContractError("duplicate selected item")
        with self._lock:
            record = self._snapshots.get(snapshot_key)
            view = self._views.get(view_key)
        if record is None or view is None or view.snapshot_id != snapshot_key:
            raise ApprovalInboxV14Unavailable("selection-state-unavailable")
        with self._publication(record, view):
            item_by_id = {str(item["item_id"]): item for item in record.items}
            resolved: list[ApprovalReviewItemV14] = []
            for item_id, proof in normalized:
                registered = view.returned_proofs.get(item_id)
                if registered is None or not hmac.compare_digest(registered, proof):
                    raise ApprovalInboxV14ContractError(
                        "item was not reviewed in this view"
                    )
                decoded = self._untoken(proof, "review")
                item = item_by_id.get(item_id)
                if item is None or item_id not in view.item_ids:
                    raise ApprovalInboxV14ContractError("selected item is unavailable")
                if (
                    decoded.get("snapshot_id") != snapshot_key
                    or decoded.get("view_digest") != view_key
                    or decoded.get("item_id") != item_id
                    or decoded.get("action_fingerprint") != item["action_fingerprint"]
                    or decoded.get("review_fields_digest") != _sha(item)
                    or decoded.get("deadline_ms") != record.deadline_ms
                ):
                    raise ApprovalInboxV14ContractError(
                        "review proof relation is invalid"
                    )
                if (
                    item["risk"] not in {"low", "medium"}
                    or item["always_explicit"]
                    or not item["batch_eligible"]
                ):
                    raise ApprovalInboxV14ContractError(
                        "item is not calm-batch eligible"
                    )
                resolved.append(self._review_item(record, view, item))
        # Order-independent canonicalization and collision checks.
        resolved.sort(key=lambda item: item.item_id)
        for label, values in {
            "action_request_id": [item.action_request_id for item in resolved],
            "action_fingerprint": [item.action_fingerprint for item in resolved],
            "idempotency_identity": [item.idempotency_identity for item in resolved],
        }.items():
            if len(values) != len(set(values)):
                raise ApprovalInboxV14ContractError(f"duplicate {label}")
        return record, view, tuple(resolved)

    def preview_calm_batch(
        self,
        snapshot_id: object,
        view_digest: object,
        selections: Sequence[tuple[str, str]],
    ) -> CalmBatchPreviewV14:
        now = self._guard()
        record, view, items = self._resolve_selections(
            snapshot_id, view_digest, selections, now
        )
        payload = {
            "contract": "CalmBatchReviewPreview.v14",
            "snapshot_id": record.snapshot_id,
            "view_digest": view.view_digest,
            "action_fingerprints": [item.action_fingerprint for item in items],
            "review_proof_digests": [
                hashlib.sha256(item.review_proof.encode()).hexdigest() for item in items
            ],
            "deadline_ms": record.deadline_ms,
            "authority_granted": False,
        }
        with self._publication(record, view):
            return CalmBatchPreviewV14(
                snapshot_id=record.snapshot_id,
                view_digest=view.view_digest,
                preview_digest=_sha(payload),
                item_count=len(items),
                items=items,
            )

    def handoff_calm_batch(
        self,
        snapshot_id: object,
        view_digest: object,
        selections: Sequence[tuple[str, str]],
    ) -> ReviewSelectionHandoffV14:
        now = self._guard()
        record, view, items = self._resolve_selections(
            snapshot_id, view_digest, selections, now
        )
        item_ids = tuple(item.item_id for item in items)
        request_ids = tuple(item.action_request_id for item in items)
        fingerprints = tuple(item.action_fingerprint for item in items)
        proof_digests = tuple(
            hashlib.sha256(item.review_proof.encode()).hexdigest() for item in items
        )
        payload = {
            "contract": "ReviewSelectionHandoff.v14",
            "snapshot_id": record.snapshot_id,
            "view_digest": view.view_digest,
            "item_ids": item_ids,
            "action_request_ids": request_ids,
            "action_fingerprints": fingerprints,
            "review_proof_digests": proof_digests,
            "instruction": "future-approval-must-re-resolve-all-host-action-fields",
            "authority_granted": False,
        }
        with self._publication(record, view):
            return ReviewSelectionHandoffV14(
                snapshot_id=record.snapshot_id,
                view_digest=view.view_digest,
                handoff_digest=_sha(payload),
                item_ids=item_ids,
                action_request_ids=request_ids,
                action_fingerprints=fingerprints,
                review_proof_digests=proof_digests,
            )


__all__ = [
    "APPROVAL_INBOX_V14_FLAG",
    "ApprovalInboxFeatureGateV14",
    "ApprovalInboxProjectionV14",
    "ApprovalInboxV14ContractError",
    "ApprovalInboxV14Error",
    "ApprovalInboxV14State",
    "ApprovalInboxV14Unavailable",
    "ApprovalReviewItemV14",
    "CalmBatchPreviewV14",
    "DeterministicInboxClockV14",
    "HostInboxItemV14",
    "HostInboxSnapshotV14",
    "HostInboxSourceV14",
    "InboxPageV14",
    "InboxQueryV14",
    "MonotonicInboxClockV14",
    "ReviewSelectionHandoffV14",
]
