"""Event-only operational analytics for Onyx.

This default-off module is a read/projection boundary, never an executor or a
success authority.  A trusted host explicitly submits already-accepted,
metadata-only events.  Reports are derived deterministically from those events;
completion counters advance only when a separately pinned receipt verifier
attests the receipt digest.

There are no timers, workers, pollers, providers, or ambient collectors here.
In particular, this module cannot inspect screens, clipboards, processes,
files, network traffic, prompts, email bodies, or message content.
"""

from __future__ import annotations

import hashlib
import heapq
import hmac
import json
import math
import os
import re
import sqlite3
import stat
import threading
import time
import uuid
from base64 import b64decode, urlsafe_b64encode
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final


FEATURE_FLAG: Final = "ONYX_EVENT_ANALYTICS_V1"
SCHEMA_VERSION: Final = 1
MAX_WINDOW_SECONDS: Final = 90 * 24 * 60 * 60
MAX_TIMELINE_ITEMS: Final = 200
MAX_METADATA_FIELDS: Final = 8
MAX_STORED_EVENTS: Final = 100_000
MAX_STORED_REPORTS: Final = 10_000
MAX_PAGE_ITEMS: Final = 200
SCAN_PAGE_ITEMS: Final = 500

_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,191}")
_EVENT_ID = re.compile(r"event_[0-9a-f]{32}")
_REPORT_ID = re.compile(r"report_[0-9a-f]{32}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SOURCE_KINDS: Final = frozenset({"goal", "workflow", "mission", "audit"})
_EVENT_TYPES: Final = frozenset(
    {
        "goal.created",
        "goal.activated",
        "goal.paused",
        "goal.completed",
        "goal.failed",
        "goal.cancelled",
        "workflow.created",
        "workflow.started",
        "workflow.waiting",
        "workflow.completed",
        "workflow.failed",
        "workflow.cancelled",
        "mission.created",
        "mission.started",
        "mission.waiting",
        "mission.completed",
        "mission.failed",
        "mission.cancelled",
        "audit.allowed",
        "audit.denied",
        "audit.receipt_verified",
        "audit.reconciled",
    }
)
_OUTCOMES: Final = frozenset(
    {"created", "active", "waiting", "paused", "completed", "failed", "cancelled", "allowed", "denied", "verified", "reconciled"}
)
_COMPLETION_EVENTS: Final = frozenset(
    {"goal.completed", "workflow.completed", "mission.completed"}
)
_EXPECTED_OUTCOME: Final = {
    "goal.created": "created", "goal.activated": "active", "goal.paused": "paused",
    "goal.completed": "completed", "goal.failed": "failed", "goal.cancelled": "cancelled",
    "workflow.created": "created", "workflow.started": "active",
    "workflow.waiting": "waiting", "workflow.completed": "completed",
    "workflow.failed": "failed", "workflow.cancelled": "cancelled",
    "mission.created": "created", "mission.started": "active",
    "mission.waiting": "waiting", "mission.completed": "completed",
    "mission.failed": "failed", "mission.cancelled": "cancelled",
    "audit.allowed": "allowed", "audit.denied": "denied",
    "audit.receipt_verified": "verified", "audit.reconciled": "reconciled",
}
_BUCKETS: Final = frozenset({3_600, 86_400, 604_800})
_INTEGER_METADATA: Final = {
    "revision": 1_000_000_000,
    "duration_ms": 86_400_000,
    "step_count": 10_000,
    "attempt_count": 10_000,
}
_ENUM_METADATA: Final = {
    "risk_level": frozenset({"low", "medium", "high", "critical"}),
    "verification_state": frozenset({"verified", "unverified", "not_applicable"}),
    "trigger_kind": frozenset({"manual", "scheduled", "event"}),
}
_SENSITIVE_TERMS: Final = frozenset(
    {
        "prompt",
        "content",
        "body",
        "message",
        "email",
        "subject",
        "text",
        "token",
        "secret",
        "password",
        "authorization",
        "cookie",
        "clipboard",
        "screen",
        "file",
        "process",
        "network",
    }
)


class EventAnalyticsError(RuntimeError):
    """The durable analytics projection is unhealthy or inconsistent."""


class EventAnalyticsContractError(ValueError):
    """An input is outside the exact bounded analytics contract."""


class EventAnalyticsDenied(PermissionError):
    """The requested operation is disabled, untrusted, or out of scope."""


class EventAnalyticsReplayDenied(EventAnalyticsDenied):
    """An event ID or semantic event fingerprint was already accepted."""


def _canonical(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise EventAnalyticsContractError("value is not canonical JSON") from exc


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise EventAnalyticsContractError(f"{label} is invalid")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise EventAnalyticsContractError(f"{label} is invalid")
    return value


def _timestamp(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EventAnalyticsContractError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise EventAnalyticsContractError(f"{label} is invalid")
    return result


def _positive_int(value: object, label: str, maximum: int) -> int:
    if type(value) is not int or isinstance(value, bool) or not 1 <= value <= maximum:
        raise EventAnalyticsContractError(f"{label} is invalid")
    return value


def _metadata(value: object) -> tuple[tuple[str, str], ...]:
    if type(value) is not dict or len(value) > MAX_METADATA_FIELDS:
        raise EventAnalyticsContractError("metadata shape is invalid")
    result: list[tuple[str, str]] = []
    for key, item in value.items():
        if type(key) is not str:
            raise EventAnalyticsContractError("metadata key is invalid")
        lowered = key.lower()
        if any(term in lowered for term in _SENSITIVE_TERMS):
            raise EventAnalyticsDenied("raw or sensitive content is forbidden")
        if key in _INTEGER_METADATA:
            if type(item) is not int or isinstance(item, bool) or not 0 <= item <= _INTEGER_METADATA[key]:
                raise EventAnalyticsContractError("metadata integer is invalid")
        elif key in _ENUM_METADATA:
            if type(item) is not str or item not in _ENUM_METADATA[key]:
                raise EventAnalyticsContractError("metadata enum is invalid")
        else:
            raise EventAnalyticsContractError("metadata key is not allowlisted")
        result.append((key, _canonical(item)))
    return tuple(sorted(result))


def _private_path(path: Path) -> None:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise EventAnalyticsContractError("an absolute analytics path is required")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or (path.exists() and path.is_symlink()):
        raise EventAnalyticsDenied("linked analytics storage is forbidden")
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if getattr(path.parent.stat(), "st_file_attributes", 0) & reparse:
        raise EventAnalyticsDenied("reparse-point analytics storage is forbidden")
    if os.name != "nt":
        os.chmod(path.parent, 0o700)


@dataclass(frozen=True, slots=True)
class AnalyticsEventV1:
    event_id: str
    owner_profile_id: str
    workspace_id: str
    source_kind: str
    entity_ref: str
    event_type: str
    outcome: str
    occurred_at: float
    metadata: tuple[tuple[str, str], ...]
    receipt_digest: str | None
    source_digest: str

    @classmethod
    def create(
        cls,
        *,
        owner_profile_id: str,
        workspace_id: str,
        source_kind: str,
        entity_ref: str,
        event_type: str,
        outcome: str,
        occurred_at: float,
        metadata: Mapping[str, object] | None = None,
        receipt_digest: str | None = None,
        event_id: str | None = None,
    ) -> "AnalyticsEventV1":
        event_key = "event_" + uuid.uuid4().hex if event_id is None else event_id
        values = {
            "event_id": event_key,
            "owner_profile_id": owner_profile_id,
            "workspace_id": workspace_id,
            "source_kind": source_kind,
            "entity_ref": entity_ref,
            "event_type": event_type,
            "outcome": outcome,
            "occurred_at": occurred_at,
            "metadata": _metadata({} if metadata is None else dict(metadata)),
            "receipt_digest": receipt_digest,
        }
        cls._validate_values(values)
        digest = _sha(cls._digest_payload(values))
        return cls(source_digest=digest, **values)

    @staticmethod
    def _digest_payload(values: Mapping[str, object]) -> dict[str, object]:
        metadata = values["metadata"]
        if type(metadata) is not tuple:
            raise EventAnalyticsContractError("metadata is invalid")
        return {
            "event_id": values["event_id"],
            "owner_profile_id": values["owner_profile_id"],
            "workspace_id": values["workspace_id"],
            "source_kind": values["source_kind"],
            "entity_ref": values["entity_ref"],
            "event_type": values["event_type"],
            "outcome": values["outcome"],
            "occurred_at": values["occurred_at"],
            "metadata": [[key, encoded] for key, encoded in metadata],
            "receipt_digest": values["receipt_digest"],
        }

    @staticmethod
    def _validate_values(values: Mapping[str, object]) -> None:
        if type(values["event_id"]) is not str or _EVENT_ID.fullmatch(values["event_id"]) is None:
            raise EventAnalyticsContractError("event_id is invalid")
        _identifier(values["owner_profile_id"], "owner_profile_id")
        _identifier(values["workspace_id"], "workspace_id")
        if values["source_kind"] not in _SOURCE_KINDS:
            raise EventAnalyticsContractError("source_kind is invalid")
        _digest(values["entity_ref"], "entity_ref")
        if values["event_type"] not in _EVENT_TYPES:
            raise EventAnalyticsContractError("event_type is invalid")
        if values["outcome"] not in _OUTCOMES:
            raise EventAnalyticsContractError("outcome is invalid")
        _timestamp(values["occurred_at"], "occurred_at")
        metadata = values["metadata"]
        if type(metadata) is not tuple or len(metadata) > MAX_METADATA_FIELDS:
            raise EventAnalyticsContractError("metadata is invalid")
        decoded: dict[str, object] = {}
        for entry in metadata:
            if type(entry) is not tuple or len(entry) != 2 or type(entry[0]) is not str or type(entry[1]) is not str:
                raise EventAnalyticsContractError("metadata entry is invalid")
            try:
                decoded[entry[0]] = json.loads(entry[1])
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise EventAnalyticsContractError("metadata encoding is invalid") from exc
        if _metadata(decoded) != metadata:
            raise EventAnalyticsContractError("metadata is not canonical")
        receipt = values["receipt_digest"]
        if receipt is not None:
            _digest(receipt, "receipt_digest")
        event_type = values["event_type"]
        outcome = values["outcome"]
        source_kind = values["source_kind"]
        if not str(event_type).startswith(str(source_kind) + "."):
            raise EventAnalyticsContractError("source and event type are inconsistent")
        if outcome != _EXPECTED_OUTCOME[event_type]:
            raise EventAnalyticsContractError("event outcome is inconsistent")

    def validate(self) -> None:
        values = {
            "event_id": self.event_id,
            "owner_profile_id": self.owner_profile_id,
            "workspace_id": self.workspace_id,
            "source_kind": self.source_kind,
            "entity_ref": self.entity_ref,
            "event_type": self.event_type,
            "outcome": self.outcome,
            "occurred_at": self.occurred_at,
            "metadata": self.metadata,
            "receipt_digest": self.receipt_digest,
        }
        self._validate_values(values)
        if _digest(self.source_digest, "source_digest") != _sha(self._digest_payload(values)):
            raise EventAnalyticsDenied("source event digest diverged")

    def snapshot(self) -> "AnalyticsEventSnapshotV1":
        self.validate()
        return AnalyticsEventSnapshotV1(
            self.event_id, self.owner_profile_id, self.workspace_id,
            self.source_kind, self.entity_ref, self.event_type, self.outcome,
            self.occurred_at, tuple(self.metadata), self.receipt_digest,
            self.source_digest,
        )

    def snapshot_digest(self) -> str:
        return _snapshot_digest(self.snapshot())


@dataclass(frozen=True, slots=True)
class AnalyticsEventSnapshotV1:
    event_id: str
    owner_profile_id: str
    workspace_id: str
    source_kind: str
    entity_ref: str
    event_type: str
    outcome: str
    occurred_at: float
    metadata: tuple[tuple[str, str], ...]
    receipt_digest: str | None
    source_digest: str

    def canonical_digest(self) -> str:
        return _snapshot_digest(self)


def _snapshot_digest(snapshot: AnalyticsEventSnapshotV1) -> str:
    if type(snapshot) is not AnalyticsEventSnapshotV1:
        raise EventAnalyticsContractError("exact analytics snapshot is required")
    values = {
        "event_id": snapshot.event_id,
        "owner_profile_id": snapshot.owner_profile_id,
        "workspace_id": snapshot.workspace_id,
        "source_kind": snapshot.source_kind,
        "entity_ref": snapshot.entity_ref,
        "event_type": snapshot.event_type,
        "outcome": snapshot.outcome,
        "occurred_at": snapshot.occurred_at,
        "metadata": snapshot.metadata,
        "receipt_digest": snapshot.receipt_digest,
    }
    AnalyticsEventV1._validate_values(values)
    observed = _digest(snapshot.source_digest, "source_digest")
    expected = _sha(AnalyticsEventV1._digest_payload(values))
    if observed != expected:
        raise EventAnalyticsDenied("snapshot digest diverged")
    return expected


@dataclass(frozen=True, slots=True)
class AnalyticsSourceAttestationV1:
    source_digest: str
    accepted: bool

    def __post_init__(self) -> None:
        _digest(self.source_digest, "source attestation digest")
        if type(self.accepted) is not bool:
            raise EventAnalyticsContractError("source attestation decision is invalid")


@dataclass(frozen=True, slots=True)
class AnalyticsReceiptAttestationV1:
    source_digest: str
    receipt_digest: str
    verified: bool

    def __post_init__(self) -> None:
        _digest(self.source_digest, "receipt source digest")
        _digest(self.receipt_digest, "receipt attestation digest")
        if type(self.verified) is not bool:
            raise EventAnalyticsContractError("receipt attestation decision is invalid")


@dataclass(frozen=True, slots=True)
class AnalyticsIngestReceiptV1:
    event_id: str
    event_hash: str
    accepted: bool
    completion_verified: bool
    source_content_captured: bool = False
    background_workers: int = 0


@dataclass(frozen=True, slots=True)
class AnalyticsReportV1:
    report_id: str
    owner_profile_id: str
    workspace_id: str
    start_at: float
    end_at: float
    bucket_seconds: int
    timeline_limit: int
    source_high_water: int
    generated_at: float
    provenance_digest: str
    projection_digest: str
    payload_json: str

    def payload(self) -> dict[str, object]:
        value = json.loads(self.payload_json)
        if type(value) is not dict:
            raise EventAnalyticsError("report payload is invalid")
        return value


@dataclass(frozen=True, slots=True)
class AnalyticsEventViewV1:
    sequence: int
    event_id: str
    source_kind: str
    entity_ref: str
    event_type: str
    outcome: str
    occurred_at: float
    completion_verified: bool
    event_hash: str


@dataclass(frozen=True, slots=True)
class AnalyticsEventPageV1:
    items: tuple[AnalyticsEventViewV1, ...]
    next_cursor: str | None
    high_water: int


@dataclass(frozen=True, slots=True)
class AnalyticsReportSummaryV1:
    sequence: int
    report_id: str
    start_at: float
    end_at: float
    generated_at: float
    source_high_water: int
    provenance_digest: str
    projection_digest: str


@dataclass(frozen=True, slots=True)
class AnalyticsReportPageV1:
    items: tuple[AnalyticsReportSummaryV1, ...]
    next_cursor: str | None
    high_water: int


@dataclass(frozen=True, slots=True)
class AnalyticsIntegrityReceiptV1:
    event_count: int
    event_tail_hash: str
    report_count: int
    report_tail_hash: str
    full_rows_verified: int
    integrity_digest: str


class EventAnalyticsProjectionV1:
    """Bounded, append-only analytics over explicit accepted metadata events."""

    _DDL = (
        """CREATE TABLE binding(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version INTEGER NOT NULL,
          owner_profile_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
          binding_digest TEXT NOT NULL
        )""",
        """CREATE TABLE analytics_events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
          source_kind TEXT NOT NULL, entity_ref TEXT NOT NULL, event_type TEXT NOT NULL,
          outcome TEXT NOT NULL, occurred_at REAL NOT NULL, metadata_json TEXT NOT NULL,
          receipt_digest TEXT, completion_verified INTEGER NOT NULL CHECK(completion_verified IN (0,1)),
          source_digest TEXT NOT NULL, event_fingerprint TEXT NOT NULL UNIQUE,
          prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE
        )""",
        """CREATE INDEX idx_analytics_time ON analytics_events(occurred_at,event_id)""",
        """CREATE TABLE analytics_reports(
          seq INTEGER PRIMARY KEY AUTOINCREMENT, report_id TEXT NOT NULL UNIQUE,
          start_at REAL NOT NULL, end_at REAL NOT NULL, bucket_seconds INTEGER NOT NULL,
          timeline_limit INTEGER NOT NULL, source_high_water INTEGER NOT NULL,
          generated_at REAL NOT NULL, provenance_digest TEXT NOT NULL,
          projection_digest TEXT NOT NULL, payload_json TEXT NOT NULL,
          prev_hash TEXT NOT NULL, report_hash TEXT NOT NULL UNIQUE
        )""",
        """CREATE TABLE analytics_heads(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1),
          event_count INTEGER NOT NULL, event_tail_seq INTEGER NOT NULL,
          event_tail_hash TEXT NOT NULL, event_projection_digest TEXT NOT NULL,
          report_count INTEGER NOT NULL, report_tail_seq INTEGER NOT NULL,
          report_tail_hash TEXT NOT NULL, report_projection_digest TEXT NOT NULL,
          head_mac TEXT NOT NULL
        )""",
        """CREATE TRIGGER analytics_events_no_update BEFORE UPDATE ON analytics_events
          BEGIN SELECT RAISE(ABORT,'analytics events are immutable'); END""",
        """CREATE TRIGGER analytics_events_no_delete BEFORE DELETE ON analytics_events
          BEGIN SELECT RAISE(ABORT,'analytics events are immutable'); END""",
        """CREATE TRIGGER analytics_reports_no_update BEFORE UPDATE ON analytics_reports
          BEGIN SELECT RAISE(ABORT,'analytics reports are immutable'); END""",
        """CREATE TRIGGER analytics_reports_no_delete BEFORE DELETE ON analytics_reports
          BEGIN SELECT RAISE(ABORT,'analytics reports are immutable'); END""",
        """CREATE TRIGGER binding_no_update BEFORE UPDATE ON binding
          BEGIN SELECT RAISE(ABORT,'analytics binding is immutable'); END""",
        """CREATE TRIGGER binding_no_delete BEFORE DELETE ON binding
          BEGIN SELECT RAISE(ABORT,'analytics binding is immutable'); END""",
        """CREATE TRIGGER analytics_heads_no_delete BEFORE DELETE ON analytics_heads
          BEGIN SELECT RAISE(ABORT,'analytics heads cannot be deleted'); END""",
    )
    _EXPECTED_COLUMNS = {
        "binding": ("singleton", "schema_version", "owner_profile_id", "workspace_id", "binding_digest"),
        "analytics_events": (
            "seq", "event_id", "source_kind", "entity_ref", "event_type", "outcome",
            "occurred_at", "metadata_json", "receipt_digest", "completion_verified",
            "source_digest", "event_fingerprint", "prev_hash", "event_hash",
        ),
        "analytics_reports": (
            "seq", "report_id", "start_at", "end_at", "bucket_seconds",
            "timeline_limit", "source_high_water", "generated_at", "provenance_digest",
            "projection_digest", "payload_json", "prev_hash", "report_hash",
        ),
        "analytics_heads": (
            "singleton", "event_count", "event_tail_seq", "event_tail_hash",
            "event_projection_digest", "report_count", "report_tail_seq",
            "report_tail_hash", "report_projection_digest", "head_mac",
        ),
    }
    _EXPECTED_TRIGGERS = frozenset(
        {
            "analytics_events_no_update", "analytics_events_no_delete",
            "analytics_reports_no_update", "analytics_reports_no_delete",
            "binding_no_update", "binding_no_delete",
            "analytics_heads_no_delete",
        }
    )

    def __init__(
        self,
        path: Path | str,
        *,
        owner_profile_id: str,
        workspace_id: str,
        source_acceptor: Callable[[AnalyticsEventSnapshotV1], AnalyticsSourceAttestationV1],
        receipt_verifier: Callable[[AnalyticsEventSnapshotV1], AnalyticsReceiptAttestationV1],
        integrity_key: bytes,
        enabled: bool = False,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if type(enabled) is not bool or not enabled:
            raise EventAnalyticsDenied("event analytics is disabled")
        self.owner_profile_id = _identifier(owner_profile_id, "owner_profile_id")
        self.workspace_id = _identifier(workspace_id, "workspace_id")
        if not callable(source_acceptor) or not callable(receipt_verifier) or not callable(clock):
            raise EventAnalyticsContractError("pinned analytics dependencies are invalid")
        if type(integrity_key) is not bytes or len(integrity_key) < 32:
            raise EventAnalyticsContractError("integrity_key is invalid")
        self.path = Path(path)
        _private_path(self.path)
        self._source_acceptor = source_acceptor
        self._receipt_verifier = receipt_verifier
        self._clock = clock
        self._integrity_key = integrity_key
        self._lock = threading.RLock()
        self._failed = False
        self.background_workers = 0
        self.polling_interval = None
        self.network_calls = 0
        self.content_captured = False
        self.full_audits = 0
        self.full_audit_rows = 0
        self.incremental_checks = 0
        self._binding_digest = self._mac(
            {
                "contract": "OnyxEventAnalyticsBinding.v1",
                "owner_profile_id": self.owner_profile_id,
                "workspace_id": self.workspace_id,
            }
        )
        self._initialize()

    def _mac(self, value: object) -> str:
        return hmac.new(
            self._integrity_key,
            _canonical(value).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _normalize_sql(value: str) -> str:
        return " ".join(value.lower().split())

    @classmethod
    def _expected_schema(cls) -> dict[tuple[str, str], str]:
        result: dict[tuple[str, str], str] = {}
        pattern = re.compile(r"create (table|index|trigger) ([a-z0-9_]+)", re.I)
        for statement in cls._DDL:
            match = pattern.match(statement.strip())
            if match is None:
                raise EventAnalyticsError("analytics DDL declaration is invalid")
            result[(match.group(1).lower(), match.group(2).lower())] = cls._normalize_sql(
                statement
            )
        return result

    def _initial_head(self) -> dict[str, object]:
        values: dict[str, object] = {
            "singleton": 1,
            "event_count": 0,
            "event_tail_seq": 0,
            "event_tail_hash": "0" * 64,
            "event_projection_digest": self._mac(
                {"kind": "event_projection_anchor", "binding": self._binding_digest}
            ),
            "report_count": 0,
            "report_tail_seq": 0,
            "report_tail_hash": "0" * 64,
            "report_projection_digest": self._mac(
                {"kind": "report_projection_anchor", "binding": self._binding_digest}
            ),
        }
        values["head_mac"] = self._head_mac(values)
        return values

    def _head_mac(self, values: Mapping[str, object]) -> str:
        return self._mac(
            {
                "kind": "analytics_heads",
                "binding": self._binding_digest,
                "event_count": values["event_count"],
                "event_tail_seq": values["event_tail_seq"],
                "event_tail_hash": values["event_tail_hash"],
                "event_projection_digest": values["event_projection_digest"],
                "report_count": values["report_count"],
                "report_tail_seq": values["report_tail_seq"],
                "report_tail_hash": values["report_tail_hash"],
                "report_projection_digest": values["report_projection_digest"],
            }
        )

    def _read_head(self, connection: sqlite3.Connection) -> dict[str, object]:
        row = connection.execute(
            "SELECT * FROM analytics_heads WHERE singleton=1"
        ).fetchone()
        if row is None:
            self._latch("analytics persistent head is missing")
        values = dict(row)
        if (
            values.get("singleton") != 1
            or type(values.get("event_count")) is not int
            or type(values.get("event_tail_seq")) is not int
            or type(values.get("report_count")) is not int
            or type(values.get("report_tail_seq")) is not int
        ):
            self._latch("analytics persistent head shape diverged")
        for name in (
            "event_tail_hash", "event_projection_digest", "report_tail_hash",
            "report_projection_digest", "head_mac",
        ):
            try:
                _digest(values.get(name), name)
            except EventAnalyticsContractError as exc:
                self._latch("analytics persistent head digest diverged", exc)
        if (
            not 0 <= int(values["event_count"]) <= MAX_STORED_EVENTS
            or not 0 <= int(values["report_count"]) <= MAX_STORED_REPORTS
            or int(values["event_tail_seq"]) < 0
            or int(values["report_tail_seq"]) < 0
            or not hmac.compare_digest(str(values["head_mac"]), self._head_mac(values))
        ):
            self._latch("analytics persistent head authentication failed")
        return values

    def _write_head(
        self, connection: sqlite3.Connection, values: dict[str, object]
    ) -> None:
        values["head_mac"] = self._head_mac(values)
        changed = connection.execute(
            """UPDATE analytics_heads SET
            event_count=?,event_tail_seq=?,event_tail_hash=?,event_projection_digest=?,
            report_count=?,report_tail_seq=?,report_tail_hash=?,report_projection_digest=?,
            head_mac=? WHERE singleton=1""",
            (
                values["event_count"], values["event_tail_seq"],
                values["event_tail_hash"], values["event_projection_digest"],
                values["report_count"], values["report_tail_seq"],
                values["report_tail_hash"], values["report_projection_digest"],
                values["head_mac"],
            ),
        ).rowcount
        if changed != 1:
            self._latch("analytics persistent head update failed")

    def _connect(self) -> sqlite3.Connection:
        _private_path(self.path)
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            objects = int(connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchone()[0])
            if version == 0 and objects == 0:
                connection.execute("BEGIN IMMEDIATE")
                for statement in self._DDL:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO binding VALUES(1,?,?,?,?)",
                    (SCHEMA_VERSION, self.owner_profile_id, self.workspace_id, self._binding_digest),
                )
                head = self._initial_head()
                connection.execute(
                    "INSERT INTO analytics_heads VALUES(?,?,?,?,?,?,?,?,?,?)",
                    tuple(head[name] for name in self._EXPECTED_COLUMNS["analytics_heads"]),
                )
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                connection.execute("COMMIT")
            self._verify_full(connection)
        if os.name != "nt":
            os.chmod(self.path, 0o600)

    def _latch(self, message: str, error: Exception | None = None) -> None:
        self._failed = True
        if error is None:
            raise EventAnalyticsError(message)
        raise EventAnalyticsError(message) from error

    def _guard(self) -> None:
        if self._failed:
            raise EventAnalyticsError("event analytics integrity is latched failed")

    def _verify_schema(
        self, connection: sqlite3.Connection, *, database_integrity: bool
    ) -> None:
        if int(connection.execute("PRAGMA user_version").fetchone()[0]) != SCHEMA_VERSION:
            self._latch("analytics schema version diverged")
        if (
            database_integrity
            and connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
        ):
            self._latch("analytics database integrity failed")
        observed_schema = {
            (str(row[0]).lower(), str(row[1]).lower()): self._normalize_sql(str(row[2]))
            for row in connection.execute(
                """SELECT type,name,sql FROM sqlite_master
                WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"""
            )
        }
        if observed_schema != self._expected_schema():
            self._latch("analytics exact schema definition diverged")
        binding = connection.execute("SELECT * FROM binding WHERE singleton=1").fetchone()
        if binding is None or tuple(binding) != (
            1, SCHEMA_VERSION, self.owner_profile_id, self.workspace_id, self._binding_digest
        ):
            self._latch("analytics scope binding diverged")

    def _event_hash(self, row: sqlite3.Row, previous: str) -> str:
        return self._mac(
            {
                "event_id": row["event_id"], "source_kind": row["source_kind"],
                "entity_ref": row["entity_ref"], "event_type": row["event_type"],
                "outcome": row["outcome"], "occurred_at": row["occurred_at"],
                "metadata_json": row["metadata_json"], "receipt_digest": row["receipt_digest"],
                "completion_verified": row["completion_verified"],
                "source_digest": row["source_digest"],
                "event_fingerprint": row["event_fingerprint"], "prev_hash": previous,
            }
        )

    def _report_hash(self, row: sqlite3.Row, previous: str) -> str:
        return self._mac(
            {
                "report_id": row["report_id"], "start_at": row["start_at"],
                "end_at": row["end_at"], "bucket_seconds": row["bucket_seconds"],
                "timeline_limit": row["timeline_limit"],
                "source_high_water": row["source_high_water"],
                "generated_at": row["generated_at"],
                "provenance_digest": row["provenance_digest"],
                "projection_digest": row["projection_digest"],
                "payload_json": row["payload_json"], "prev_hash": previous,
            }
        )

    def _authenticate_event_row(self, row: sqlite3.Row) -> None:
        if row["event_hash"] != self._event_hash(row, str(row["prev_hash"])):
            self._latch("analytics event record authentication failed")

    def _authenticate_report_row(self, row: sqlite3.Row) -> None:
        if row["report_hash"] != self._report_hash(row, str(row["prev_hash"])):
            self._latch("analytics report record authentication failed")

    def _verify_event_boundary(
        self, connection: sqlite3.Connection, row: sqlite3.Row,
        previous_selected_hash: str | None,
    ) -> str:
        self._authenticate_event_row(row)
        if previous_selected_hash is not None and row["prev_hash"] == previous_selected_hash:
            return str(row["event_hash"])
        predecessor = connection.execute(
            "SELECT * FROM analytics_events WHERE seq<? ORDER BY seq DESC LIMIT 1",
            (int(row["seq"]),),
        ).fetchone()
        expected = "0" * 64
        if predecessor is not None:
            self._authenticate_event_row(predecessor)
            expected = str(predecessor["event_hash"])
        if row["prev_hash"] != expected:
            self._latch("analytics event range continuity diverged")
        return str(row["event_hash"])

    def _verify_report_boundary(
        self, connection: sqlite3.Connection, row: sqlite3.Row,
        previous_selected_hash: str | None,
    ) -> str:
        self._authenticate_report_row(row)
        if previous_selected_hash is not None and row["prev_hash"] == previous_selected_hash:
            return str(row["report_hash"])
        predecessor = connection.execute(
            "SELECT * FROM analytics_reports WHERE seq<? ORDER BY seq DESC LIMIT 1",
            (int(row["seq"]),),
        ).fetchone()
        expected = "0" * 64
        if predecessor is not None:
            self._authenticate_report_row(predecessor)
            expected = str(predecessor["report_hash"])
        if row["prev_hash"] != expected:
            self._latch("analytics report range continuity diverged")
        return str(row["report_hash"])

    def _verify_chains(self, connection: sqlite3.Connection) -> None:
        head = self._read_head(connection)
        previous = "0" * 64
        event_projection = str(self._initial_head()["event_projection_digest"])
        event_count = 0
        event_tail_seq = 0
        for row in connection.execute("SELECT * FROM analytics_events ORDER BY seq"):
            try:
                metadata_entries = json.loads(str(row["metadata_json"]))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                self._latch("analytics source metadata diverged", exc)
            if type(metadata_entries) is not list or any(
                type(item) is not list or len(item) != 2 for item in metadata_entries
            ):
                self._latch("analytics source metadata diverged")
            source_payload = {
                "event_id": row["event_id"],
                "owner_profile_id": self.owner_profile_id,
                "workspace_id": self.workspace_id,
                "source_kind": row["source_kind"],
                "entity_ref": row["entity_ref"],
                "event_type": row["event_type"],
                "outcome": row["outcome"],
                "occurred_at": row["occurred_at"],
                "metadata": metadata_entries,
                "receipt_digest": row["receipt_digest"],
            }
            if row["source_digest"] != _sha(source_payload):
                self._latch("analytics source digest diverged")
            self._authenticate_event_row(row)
            if row["prev_hash"] != previous:
                self._latch("analytics source chain diverged")
            previous = str(row["event_hash"])
            event_count += 1
            event_tail_seq = int(row["seq"])
            event_projection = self._mac(
                {
                    "kind": "event_projection_advance", "previous": event_projection,
                    "count": event_count, "sequence": event_tail_seq,
                    "record_hash": previous,
                }
            )
        previous = "0" * 64
        report_projection = str(self._initial_head()["report_projection_digest"])
        report_count = 0
        report_tail_seq = 0
        for row in connection.execute("SELECT * FROM analytics_reports ORDER BY seq"):
            self._authenticate_report_row(row)
            if row["prev_hash"] != previous:
                self._latch("analytics report chain diverged")
            previous = str(row["report_hash"])
            report_count += 1
            report_tail_seq = int(row["seq"])
            report_projection = self._mac(
                {
                    "kind": "report_projection_advance", "previous": report_projection,
                    "count": report_count, "sequence": report_tail_seq,
                    "record_hash": previous,
                }
            )
        if (
            event_count != head["event_count"]
            or event_tail_seq != head["event_tail_seq"]
            or previous != head["report_tail_hash"]
            or report_count != head["report_count"]
            or report_tail_seq != head["report_tail_seq"]
            or event_projection != head["event_projection_digest"]
            or report_projection != head["report_projection_digest"]
        ):
            self._latch("analytics persistent head does not reconcile")
        event_tail_hash = "0" * 64 if event_count == 0 else str(
            connection.execute(
                "SELECT event_hash FROM analytics_events WHERE seq=?", (event_tail_seq,)
            ).fetchone()[0]
        )
        if event_tail_hash != head["event_tail_hash"]:
            self._latch("analytics event tail does not reconcile")
        self.full_audit_rows += event_count + report_count

    def _verify_incremental(self, connection: sqlite3.Connection) -> dict[str, object]:
        self._guard()
        try:
            self._verify_schema(connection, database_integrity=False)
            head = self._read_head(connection)
            actual_event_count = int(connection.execute(
                "SELECT COUNT(*) FROM analytics_events"
            ).fetchone()[0])
            actual_report_count = int(connection.execute(
                "SELECT COUNT(*) FROM analytics_reports"
            ).fetchone()[0])
            if actual_event_count != head["event_count"]:
                self._latch("analytics event count diverged from authenticated head")
            if actual_report_count != head["report_count"]:
                self._latch("analytics report count diverged from authenticated head")
            event_tail = connection.execute(
                "SELECT * FROM analytics_events ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            report_tail = connection.execute(
                "SELECT * FROM analytics_reports ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            expected_event = None if head["event_count"] == 0 else (
                head["event_tail_seq"], head["event_tail_hash"]
            )
            expected_report = None if head["report_count"] == 0 else (
                head["report_tail_seq"], head["report_tail_hash"]
            )
            observed_event = None if event_tail is None else (
                event_tail["seq"], event_tail["event_hash"]
            )
            observed_report = None if report_tail is None else (
                report_tail["seq"], report_tail["report_hash"]
            )
            if observed_event != expected_event:
                self._latch("analytics event tail diverged")
            if event_tail is not None:
                self._authenticate_event_row(event_tail)
            if observed_report != expected_report:
                self._latch("analytics report tail diverged")
            if report_tail is not None:
                self._authenticate_report_row(report_tail)
            self.incremental_checks += 1
            return head
        except EventAnalyticsError:
            raise
        except (sqlite3.Error, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            self._latch("analytics integrity verification failed", exc)

    def _verify_full(self, connection: sqlite3.Connection) -> None:
        self._guard()
        try:
            self._verify_schema(connection, database_integrity=True)
            self._verify_chains(connection)
            self.full_audits += 1
        except EventAnalyticsError:
            raise
        except (sqlite3.Error, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            self._latch("analytics full integrity verification failed", exc)

    def ingest(self, event: AnalyticsEventV1) -> AnalyticsIngestReceiptV1:
        if type(event) is not AnalyticsEventV1:
            raise EventAnalyticsContractError("exact analytics event is required")
        original = event.snapshot()
        internal = AnalyticsEventSnapshotV1(
            original.event_id, original.owner_profile_id, original.workspace_id,
            original.source_kind, original.entity_ref, original.event_type,
            original.outcome, original.occurred_at, tuple(original.metadata),
            original.receipt_digest, original.source_digest,
        )
        internal_digest = internal.canonical_digest()
        if (internal.owner_profile_id, internal.workspace_id) != (
            self.owner_profile_id, self.workspace_id
        ):
            raise EventAnalyticsDenied("analytics event is outside the bound scope")
        now = _timestamp(self._clock(), "clock")
        if internal.occurred_at > now + 300:
            raise EventAnalyticsDenied("future analytics event is forbidden")
        with self._lock, self._connect() as connection:
            self._verify_incremental(connection)
        source_request = AnalyticsEventSnapshotV1(
            internal.event_id, internal.owner_profile_id, internal.workspace_id,
            internal.source_kind, internal.entity_ref, internal.event_type,
            internal.outcome, internal.occurred_at, tuple(internal.metadata),
            internal.receipt_digest, internal.source_digest,
        )
        attestation = self._source_acceptor(source_request)
        if (
            type(attestation) is not AnalyticsSourceAttestationV1
            or not attestation.accepted
            or not hmac.compare_digest(attestation.source_digest, internal_digest)
        ):
            raise EventAnalyticsDenied("source authority did not accept the event")
        if source_request != internal or source_request.canonical_digest() != internal_digest:
            raise EventAnalyticsDenied("source attestation request was mutated")
        completion = internal.event_type in _COMPLETION_EVENTS
        completion_verified = False
        if completion and internal.receipt_digest is not None:
            receipt_request = AnalyticsEventSnapshotV1(
                internal.event_id, internal.owner_profile_id, internal.workspace_id,
                internal.source_kind, internal.entity_ref, internal.event_type,
                internal.outcome, internal.occurred_at, tuple(internal.metadata),
                internal.receipt_digest, internal.source_digest,
            )
            receipt_attestation = self._receipt_verifier(receipt_request)
            if (
                type(receipt_attestation) is not AnalyticsReceiptAttestationV1
                or not hmac.compare_digest(
                    receipt_attestation.source_digest, internal_digest
                )
                or not hmac.compare_digest(
                    receipt_attestation.receipt_digest, internal.receipt_digest
                )
            ):
                raise EventAnalyticsDenied("receipt attestation binding diverged")
            if receipt_request != internal or receipt_request.canonical_digest() != internal_digest:
                raise EventAnalyticsDenied("receipt attestation request was mutated")
            completion_verified = receipt_attestation.verified
        try:
            if event.snapshot() != original or original.canonical_digest() != internal_digest:
                raise EventAnalyticsDenied("source event changed during attestation")
        except (EventAnalyticsContractError, EventAnalyticsDenied) as exc:
            raise EventAnalyticsDenied("source event changed during attestation") from exc
        metadata_json = _canonical([[key, encoded] for key, encoded in internal.metadata])
        fingerprint = self._mac(
            {
                "binding": self._binding_digest, "source_kind": internal.source_kind,
                "entity_ref": internal.entity_ref, "event_type": internal.event_type,
                "outcome": internal.outcome, "occurred_at": internal.occurred_at,
                "metadata_json": metadata_json, "receipt_digest": internal.receipt_digest,
            }
        )
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            head = self._verify_incremental(connection)
            event_count = int(head["event_count"])
            if event_count >= MAX_STORED_EVENTS:
                raise EventAnalyticsDenied("analytics event storage budget is exhausted")
            prev_hash = str(head["event_tail_hash"])
            values = {
                "event_id": internal.event_id, "source_kind": internal.source_kind,
                "entity_ref": internal.entity_ref, "event_type": internal.event_type,
                "outcome": internal.outcome, "occurred_at": internal.occurred_at,
                "metadata_json": metadata_json, "receipt_digest": internal.receipt_digest,
                "completion_verified": int(completion_verified),
                "source_digest": internal.source_digest, "event_fingerprint": fingerprint,
                "prev_hash": prev_hash,
            }
            event_hash = self._mac(values)
            try:
                inserted = connection.execute(
                    """INSERT INTO analytics_events(
                    event_id,source_kind,entity_ref,event_type,outcome,occurred_at,
                    metadata_json,receipt_digest,completion_verified,source_digest,
                    event_fingerprint,prev_hash,event_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        internal.event_id, internal.source_kind, internal.entity_ref,
                        internal.event_type, internal.outcome, internal.occurred_at,
                        metadata_json, internal.receipt_digest, int(completion_verified),
                        internal.source_digest, fingerprint, prev_hash,
                        event_hash,
                    ),
                )
                sequence = int(inserted.lastrowid)
                head["event_count"] = event_count + 1
                head["event_tail_seq"] = sequence
                head["event_tail_hash"] = event_hash
                head["event_projection_digest"] = self._mac(
                    {
                        "kind": "event_projection_advance",
                        "previous": head["event_projection_digest"],
                        "count": head["event_count"], "sequence": sequence,
                        "record_hash": event_hash,
                    }
                )
                self._write_head(connection, head)
                connection.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                connection.execute("ROLLBACK")
                raise EventAnalyticsReplayDenied("duplicate or replayed analytics event") from exc
        return AnalyticsIngestReceiptV1(
            internal.event_id, event_hash, True, completion_verified
        )

    @staticmethod
    def _query(
        start_at: object, end_at: object, bucket_seconds: object, timeline_limit: object
    ) -> tuple[float, float, int, int]:
        start = _timestamp(start_at, "start_at")
        end = _timestamp(end_at, "end_at")
        if end < start or end - start > MAX_WINDOW_SECONDS:
            raise EventAnalyticsContractError("analytics window is invalid")
        if type(bucket_seconds) is not int or bucket_seconds not in _BUCKETS:
            raise EventAnalyticsContractError("bucket_seconds is invalid")
        limit = _positive_int(timeline_limit, "timeline_limit", MAX_TIMELINE_ITEMS)
        bucket_count = int((end - start) // bucket_seconds) + 1
        if bucket_count > 2_200:
            raise EventAnalyticsContractError("analytics bucket cardinality is invalid")
        return start, end, bucket_seconds, limit

    def _derive(
        self, connection: sqlite3.Connection, *, start: float, end: float,
        bucket_seconds: int, timeline_limit: int, high_water: int,
    ) -> tuple[str, str]:
        query = {
            "binding": self._binding_digest, "start_at": start, "end_at": end,
            "bucket_seconds": bucket_seconds, "timeline_limit": timeline_limit,
            "source_high_water": high_water,
        }
        provenance = hmac.new(
            self._integrity_key,
            _canonical({"kind": "report_provenance", "query": query}).encode("utf-8"),
            hashlib.sha256,
        )
        by_source = {key: 0 for key in sorted(_SOURCE_KINDS)}
        by_outcome = {key: 0 for key in sorted(_OUTCOMES)}
        verified_completions = 0
        unverified_completion_claims = 0
        failures = 0
        denials = 0
        event_count = 0
        buckets: dict[int, dict[str, int]] = {}
        timeline: list[tuple[float, str, dict[str, object]]] = []
        previous_selected_hash: str | None = None
        cursor = connection.execute(
            """SELECT * FROM analytics_events
            WHERE seq<=? AND occurred_at>=? AND occurred_at<=?
            ORDER BY seq""",
            (high_water, start, end),
        )
        while True:
            page = cursor.fetchmany(SCAN_PAGE_ITEMS)
            if not page:
                break
            for row in page:
                previous_selected_hash = self._verify_event_boundary(
                    connection, row, previous_selected_hash
                )
                event_count += 1
                provenance.update(b"\0" + str(row["event_hash"]).encode("ascii"))
                by_source[str(row["source_kind"])] += 1
                by_outcome[str(row["outcome"])] += 1
                completion = str(row["event_type"]) in _COMPLETION_EVENTS
                verified = bool(row["completion_verified"])
                verified_completions += int(completion and verified)
                unverified_completion_claims += int(completion and not verified)
                failures += int(row["outcome"] == "failed")
                denials += int(row["outcome"] == "denied")
                index = int((float(row["occurred_at"]) - start) // bucket_seconds)
                bucket = buckets.setdefault(
                    index, {"events": 0, "verified_completions": 0, "failures": 0}
                )
                bucket["events"] += 1
                bucket["verified_completions"] += int(completion and verified)
                bucket["failures"] += int(row["outcome"] == "failed")
                item = {
                    "occurred_at": float(row["occurred_at"]),
                    "source_kind": str(row["source_kind"]),
                    "entity_ref": str(row["entity_ref"]),
                    "event_type": str(row["event_type"]),
                    "outcome": str(row["outcome"]),
                    "completion_verified": bool(row["completion_verified"]),
                    "event_hash": str(row["event_hash"]),
                }
                entry = (float(row["occurred_at"]), str(row["event_id"]), item)
                if len(timeline) < timeline_limit:
                    heapq.heappush(timeline, entry)
                elif entry[:2] > timeline[0][:2]:
                    heapq.heapreplace(timeline, entry)
        payload = {
            "contract": "OnyxEventAnalyticsReport.v1",
            "window": {"start_at": start, "end_at": end, "bucket_seconds": bucket_seconds},
            "totals": {
                "events": event_count, "verified_completions": verified_completions,
                "unverified_completion_claims": unverified_completion_claims,
                "failures": failures, "denials": denials,
            },
            "by_source": by_source,
            "by_outcome": by_outcome,
            "trends": [
                {
                    "bucket_start": start + index * bucket_seconds,
                    "events": value["events"],
                    "verified_completions": value["verified_completions"],
                    "failures": value["failures"],
                }
                for index, value in sorted(buckets.items())
            ],
            "timeline": [item for _timestamp_value, _event_id, item in sorted(timeline)],
            "timeline_truncated": event_count > timeline_limit,
            "content_captured": False,
            "authoritative": False,
            "background_workers": 0,
        }
        return _canonical(payload), provenance.hexdigest()

    def create_report(
        self,
        *,
        start_at: float,
        end_at: float,
        bucket_seconds: int = 86_400,
        timeline_limit: int = 100,
    ) -> AnalyticsReportV1:
        start, end, bucket, limit = self._query(
            start_at, end_at, bucket_seconds, timeline_limit
        )
        if end > _timestamp(self._clock(), "clock") + 300:
            raise EventAnalyticsDenied("future analytics window is forbidden")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            head = self._verify_incremental(connection)
            high_water = int(head["event_tail_seq"])
            payload_json, provenance = self._derive(
                connection, start=start, end=end, bucket_seconds=bucket,
                timeline_limit=limit, high_water=high_water,
            )
            projection_digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
            report_id = "report_" + uuid.uuid4().hex
            generated_at = _timestamp(self._clock(), "clock")
            report_count = int(head["report_count"])
            if report_count >= MAX_STORED_REPORTS:
                raise EventAnalyticsDenied("analytics report storage budget is exhausted")
            prev_hash = str(head["report_tail_hash"])
            values = {
                "report_id": report_id, "start_at": start, "end_at": end,
                "bucket_seconds": bucket, "timeline_limit": limit,
                "source_high_water": high_water, "generated_at": generated_at,
                "provenance_digest": provenance, "projection_digest": projection_digest,
                "payload_json": payload_json, "prev_hash": prev_hash,
            }
            report_hash = self._mac(values)
            inserted = connection.execute(
                """INSERT INTO analytics_reports(
                report_id,start_at,end_at,bucket_seconds,timeline_limit,
                source_high_water,generated_at,provenance_digest,projection_digest,
                payload_json,prev_hash,report_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    report_id, start, end, bucket, limit, high_water, generated_at,
                    provenance, projection_digest, payload_json, prev_hash, report_hash,
                ),
            )
            sequence = int(inserted.lastrowid)
            head["report_count"] = report_count + 1
            head["report_tail_seq"] = sequence
            head["report_tail_hash"] = report_hash
            head["report_projection_digest"] = self._mac(
                {
                    "kind": "report_projection_advance",
                    "previous": head["report_projection_digest"],
                    "count": head["report_count"], "sequence": sequence,
                    "record_hash": report_hash,
                }
            )
            self._write_head(connection, head)
            connection.execute("COMMIT")
        return self.read_report(
            report_id,
            owner_profile_id=self.owner_profile_id,
            workspace_id=self.workspace_id,
        )

    def read_report(
        self, report_id: str, *, owner_profile_id: str, workspace_id: str
    ) -> AnalyticsReportV1:
        if type(report_id) is not str or _REPORT_ID.fullmatch(report_id) is None:
            raise EventAnalyticsContractError("report_id is invalid")
        if (
            _identifier(owner_profile_id, "owner_profile_id"),
            _identifier(workspace_id, "workspace_id"),
        ) != (self.owner_profile_id, self.workspace_id):
            raise EventAnalyticsDenied("analytics report is outside the bound scope")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN")
            self._verify_incremental(connection)
            row = connection.execute(
                "SELECT * FROM analytics_reports WHERE report_id=?", (report_id,)
            ).fetchone()
            if row is None:
                raise EventAnalyticsDenied("analytics report is unavailable")
            self._verify_report_boundary(connection, row, None)
            expected_payload, expected_provenance = self._derive(
                connection, start=float(row["start_at"]), end=float(row["end_at"]),
                bucket_seconds=int(row["bucket_seconds"]),
                timeline_limit=int(row["timeline_limit"]),
                high_water=int(row["source_high_water"]),
            )
            if (
                row["provenance_digest"] != expected_provenance
                or row["payload_json"] != expected_payload
                or row["projection_digest"]
                != hashlib.sha256(expected_payload.encode("utf-8")).hexdigest()
            ):
                self._latch("analytics report provenance diverged")
            report = AnalyticsReportV1(
                str(row["report_id"]), self.owner_profile_id, self.workspace_id,
                float(row["start_at"]), float(row["end_at"]),
                int(row["bucket_seconds"]), int(row["timeline_limit"]),
                int(row["source_high_water"]), float(row["generated_at"]),
                str(row["provenance_digest"]), str(row["projection_digest"]),
                str(row["payload_json"]),
            )
            connection.execute("COMMIT")
            return report

    def _scope(self, owner_profile_id: str, workspace_id: str) -> None:
        if (
            _identifier(owner_profile_id, "owner_profile_id"),
            _identifier(workspace_id, "workspace_id"),
        ) != (self.owner_profile_id, self.workspace_id):
            raise EventAnalyticsDenied("analytics page is outside the bound scope")

    def _encode_cursor(self, *, kind: str, after: int, high_water: int) -> str:
        payload = {
            "contract": "OnyxEventAnalyticsCursor.v1",
            "binding": self._binding_digest,
            "kind": kind,
            "after": after,
            "high_water": high_water,
        }
        envelope = {"payload": payload, "mac": self._mac(payload)}
        return urlsafe_b64encode(_canonical(envelope).encode("utf-8")).decode("ascii")

    def _decode_cursor(
        self, token: str, *, kind: str, current_high_water: int
    ) -> tuple[int, int]:
        if type(token) is not str or not token or len(token) > 2_048:
            raise EventAnalyticsContractError("analytics cursor is invalid")
        try:
            raw = b64decode(token.encode("ascii"), altchars=b"-_", validate=True)
            envelope = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
            raise EventAnalyticsDenied("analytics cursor authentication failed") from exc
        if type(envelope) is not dict or set(envelope) != {"payload", "mac"}:
            raise EventAnalyticsDenied("analytics cursor shape diverged")
        payload = envelope["payload"]
        if type(payload) is not dict or set(payload) != {
            "contract", "binding", "kind", "after", "high_water"
        }:
            raise EventAnalyticsDenied("analytics cursor payload diverged")
        if (
            payload["contract"] != "OnyxEventAnalyticsCursor.v1"
            or payload["binding"] != self._binding_digest
            or payload["kind"] != kind
            or type(payload["after"]) is not int
            or type(payload["high_water"]) is not int
            or not 0 <= payload["after"] <= payload["high_water"] <= current_high_water
            or type(envelope["mac"]) is not str
            or not hmac.compare_digest(envelope["mac"], self._mac(payload))
        ):
            raise EventAnalyticsDenied("analytics cursor authentication failed")
        return int(payload["after"]), int(payload["high_water"])

    def list_event_page(
        self, *, owner_profile_id: str, workspace_id: str, limit: int = 100,
        cursor: str | None = None,
    ) -> AnalyticsEventPageV1:
        self._scope(owner_profile_id, workspace_id)
        page_limit = _positive_int(limit, "limit", MAX_PAGE_ITEMS)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN")
            head = self._verify_incremental(connection)
            current = int(head["event_tail_seq"])
            after, high_water = (0, current) if cursor is None else self._decode_cursor(
                cursor, kind="events", current_high_water=current
            )
            rows = list(connection.execute(
                """SELECT * FROM analytics_events WHERE seq>? AND seq<=?
                ORDER BY seq LIMIT ?""",
                (after, high_water, page_limit + 1),
            ))
            has_more = len(rows) > page_limit
            rows = rows[:page_limit]
            previous_selected_hash: str | None = None
            for row in rows:
                previous_selected_hash = self._verify_event_boundary(
                    connection, row, previous_selected_hash
                )
            items = tuple(
                AnalyticsEventViewV1(
                    int(row["seq"]), str(row["event_id"]), str(row["source_kind"]),
                    str(row["entity_ref"]), str(row["event_type"]), str(row["outcome"]),
                    float(row["occurred_at"]), bool(row["completion_verified"]),
                    str(row["event_hash"]),
                )
                for row in rows
            )
            next_cursor = None
            if has_more and items:
                next_cursor = self._encode_cursor(
                    kind="events", after=items[-1].sequence, high_water=high_water
                )
            connection.execute("COMMIT")
            return AnalyticsEventPageV1(items, next_cursor, high_water)

    def list_report_page(
        self, *, owner_profile_id: str, workspace_id: str, limit: int = 50,
        cursor: str | None = None,
    ) -> AnalyticsReportPageV1:
        self._scope(owner_profile_id, workspace_id)
        page_limit = _positive_int(limit, "limit", MAX_PAGE_ITEMS)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN")
            head = self._verify_incremental(connection)
            current = int(head["report_tail_seq"])
            after, high_water = (0, current) if cursor is None else self._decode_cursor(
                cursor, kind="reports", current_high_water=current
            )
            rows = list(connection.execute(
                """SELECT * FROM analytics_reports WHERE seq>? AND seq<=?
                ORDER BY seq LIMIT ?""",
                (after, high_water, page_limit + 1),
            ))
            has_more = len(rows) > page_limit
            rows = rows[:page_limit]
            previous_selected_hash = None
            for row in rows:
                previous_selected_hash = self._verify_report_boundary(
                    connection, row, previous_selected_hash
                )
            items = tuple(
                AnalyticsReportSummaryV1(
                    int(row["seq"]), str(row["report_id"]), float(row["start_at"]),
                    float(row["end_at"]), float(row["generated_at"]),
                    int(row["source_high_water"]), str(row["provenance_digest"]),
                    str(row["projection_digest"]),
                )
                for row in rows
            )
            next_cursor = None
            if has_more and items:
                next_cursor = self._encode_cursor(
                    kind="reports", after=items[-1].sequence, high_water=high_water
                )
            connection.execute("COMMIT")
            return AnalyticsReportPageV1(items, next_cursor, high_water)

    def verify_integrity(self) -> AnalyticsIntegrityReceiptV1:
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN")
            before = self.full_audit_rows
            self._verify_full(connection)
            head = self._read_head(connection)
            rows = self.full_audit_rows - before
            receipt = AnalyticsIntegrityReceiptV1(
                int(head["event_count"]), str(head["event_tail_hash"]),
                int(head["report_count"]), str(head["report_tail_hash"]), rows,
                self._mac({"kind": "manual_integrity", "head_mac": head["head_mac"]}),
            )
            connection.execute("COMMIT")
            return receipt


__all__ = [
    "FEATURE_FLAG", "SCHEMA_VERSION", "MAX_WINDOW_SECONDS",
    "MAX_TIMELINE_ITEMS", "MAX_STORED_EVENTS", "MAX_STORED_REPORTS",
    "MAX_PAGE_ITEMS", "AnalyticsEventV1", "AnalyticsEventSnapshotV1",
    "AnalyticsSourceAttestationV1", "AnalyticsReceiptAttestationV1",
    "AnalyticsIngestReceiptV1", "AnalyticsReportV1", "AnalyticsEventViewV1",
    "AnalyticsEventPageV1", "AnalyticsReportSummaryV1", "AnalyticsReportPageV1",
    "AnalyticsIntegrityReceiptV1", "EventAnalyticsProjectionV1",
    "EventAnalyticsError", "EventAnalyticsContractError", "EventAnalyticsDenied",
    "EventAnalyticsReplayDenied",
]
