"""Durable, receipt-bound projection for governed content operations.

This module owns lifecycle metadata only.  It cannot publish, access a network,
read credentials, start a worker or retain content bodies.  Existing provider
adapters perform effects after a durable reservation and feed an exact receipt
back into this projection.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import stat
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final, Mapping


FEATURE_FLAG: Final = "ONYX_CONTENT_LIFECYCLE_PROJECTION_V1"
MAX_CONTENT_CHARACTERS: Final = 200_000
MAX_LIST_ITEMS: Final = 200
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,191}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_STATES: Final = (
    "scheduled", "reserved", "publishing", "published", "failed",
    "reconciliation", "cancelled",
)
_TRANSITIONS: Final = {
    "scheduled": frozenset(("reserved", "cancelled")),
    "reserved": frozenset(("publishing", "cancelled")),
    "publishing": frozenset(("published", "failed", "reconciliation")),
    "reconciliation": frozenset(("published", "failed")),
    "failed": frozenset(("reserved", "cancelled")),
    "published": frozenset(),
    "cancelled": frozenset(),
}


class ContentLifecycleError(RuntimeError):
    pass


class ContentLifecycleContractError(ValueError):
    pass


class ContentLifecycleDenied(PermissionError):
    pass


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ContentLifecycleContractError(f"{label} is invalid")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ContentLifecycleContractError(f"{label} is invalid")
    return value


def _timestamp(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContentLifecycleContractError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ContentLifecycleContractError(f"{label} is invalid")
    return result


def _content_digest(value: object) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise ContentLifecycleContractError("content is invalid")
    if len(value) > MAX_CONTENT_CHARACTERS:
        raise ContentLifecycleContractError("content exceeds lifecycle limit")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise ContentLifecycleContractError("value is not canonical JSON") from exc


def _private_path(path: Path) -> None:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise ContentLifecycleContractError("an absolute projection path is required")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or (path.exists() and path.is_symlink()):
        raise ContentLifecycleDenied("linked lifecycle storage is forbidden")
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if getattr(path.parent.stat(), "st_file_attributes", 0) & reparse:
        raise ContentLifecycleDenied("reparse-point lifecycle storage is forbidden")


@dataclass(frozen=True, slots=True)
class ContentProjectionV1:
    content_id: str
    owner_profile_id: str
    workspace_id: str
    provider: str
    account_id: str
    destination_id: str
    content_digest: str
    status: str
    scheduled_for: float
    reservation_id: str | None
    provider_item_id: str | None
    detail: str
    updated_at: float


@dataclass(frozen=True, slots=True)
class ContentProviderReceiptV1:
    content_id: str
    reservation_id: str
    provider: str
    account_id: str
    destination_id: str
    provider_item_id: str
    content_digest: str
    idempotency_key: str
    verified_at: float

    def __post_init__(self) -> None:
        for value, label in (
            (self.content_id, "content_id"), (self.reservation_id, "reservation_id"),
            (self.provider, "provider"), (self.account_id, "account_id"),
            (self.destination_id, "destination_id"),
            (self.provider_item_id, "provider_item_id"),
            (self.idempotency_key, "idempotency_key"),
        ):
            _identifier(value, label)
        _digest(self.content_digest, "content_digest")
        _timestamp(self.verified_at, "verified_at")


class ContentLifecycleProjectionV1:
    """Hash-audited content lifecycle with zero autonomous work."""

    _DDL = (
        """CREATE TABLE content_items(
          content_id TEXT PRIMARY KEY, owner_profile_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL, provider TEXT NOT NULL, account_id TEXT NOT NULL,
          destination_id TEXT NOT NULL, content_digest TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN
          ('scheduled','reserved','publishing','published','failed','reconciliation','cancelled')),
          scheduled_for REAL NOT NULL, reservation_id TEXT UNIQUE,
          idempotency_key TEXT UNIQUE, provider_item_id TEXT,
          detail TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
        )""",
        """CREATE INDEX idx_content_scope
          ON content_items(owner_profile_id,workspace_id,updated_at DESC)""",
        """CREATE TABLE content_events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT, content_id TEXT NOT NULL,
          occurred_at REAL NOT NULL, event TEXT NOT NULL, detail_json TEXT NOT NULL,
          prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE
        )""",
        """CREATE TRIGGER content_events_no_update BEFORE UPDATE ON content_events
          BEGIN SELECT RAISE(ABORT,'content events are immutable'); END""",
        """CREATE TRIGGER content_events_no_delete BEFORE DELETE ON content_events
          BEGIN SELECT RAISE(ABORT,'content events are immutable'); END""",
    )

    def __init__(
        self, path: Path | str, *, enabled: bool,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if type(enabled) is not bool or not enabled:
            raise ContentLifecycleDenied("content lifecycle is disabled")
        if not callable(clock):
            raise ContentLifecycleContractError("clock is invalid")
        self.path = Path(path)
        _private_path(self.path)
        self._clock = clock
        self._lock = threading.RLock()
        self.background_workers = 0
        self.polling_interval = None
        self.network_calls = 0
        self.provider_calls = 0
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        _private_path(self.path)
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            count = int(connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchone()[0])
            if version == 0 and count == 0:
                connection.execute("BEGIN IMMEDIATE")
                for statement in self._DDL:
                    connection.execute(statement)
                connection.execute("PRAGMA user_version=1")
                connection.execute("COMMIT")
            if int(connection.execute("PRAGMA user_version").fetchone()[0]) != 1:
                raise ContentLifecycleError("content lifecycle schema version is invalid")
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ContentLifecycleError("content lifecycle integrity failed")

    @staticmethod
    def _event(
        connection: sqlite3.Connection, content_id: str, event: str,
        detail: Mapping[str, object], now: float,
    ) -> None:
        previous = connection.execute(
            "SELECT event_hash FROM content_events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev_hash = "0" * 64 if previous is None else str(previous[0])
        detail_json = _canonical(dict(detail))
        event_hash = hashlib.sha256(_canonical({
            "content_id": content_id, "occurred_at": now, "event": event,
            "detail_json": detail_json, "prev_hash": prev_hash,
        }).encode("utf-8")).hexdigest()
        connection.execute(
            "INSERT INTO content_events(content_id,occurred_at,event,detail_json,prev_hash,event_hash) VALUES(?,?,?,?,?,?)",
            (content_id, now, event, detail_json, prev_hash, event_hash),
        )

    @staticmethod
    def _row(row: sqlite3.Row) -> ContentProjectionV1:
        return ContentProjectionV1(
            str(row["content_id"]), str(row["owner_profile_id"]),
            str(row["workspace_id"]), str(row["provider"]), str(row["account_id"]),
            str(row["destination_id"]), str(row["content_digest"]), str(row["status"]),
            float(row["scheduled_for"]),
            None if row["reservation_id"] is None else str(row["reservation_id"]),
            None if row["provider_item_id"] is None else str(row["provider_item_id"]),
            str(row["detail"]), float(row["updated_at"]),
        )

    def schedule(
        self, *, owner_profile_id: str, workspace_id: str, provider: str,
        account_id: str, destination_id: str, content: str,
        scheduled_for: float,
    ) -> ContentProjectionV1:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        provider_value = _identifier(provider, "provider")
        account = _identifier(account_id, "account_id")
        destination = _identifier(destination_id, "destination_id")
        digest = _content_digest(content)
        due = _timestamp(scheduled_for, "scheduled_for")
        content_id = "content_" + uuid.uuid4().hex
        now = _timestamp(self._clock(), "clock")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO content_items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (content_id, owner, workspace, provider_value, account, destination,
                 digest, "scheduled", due, None, None, None,
                 "body_digest_registered", now, now),
            )
            self._event(connection, content_id, "content.scheduled", {
                "provider": provider_value, "account_id": account,
                "destination_id": destination, "content_digest": digest,
                "scheduled_for": due,
            }, now)
            connection.execute("COMMIT")
        return self.get(content_id, owner_profile_id=owner, workspace_id=workspace)

    def _transition(
        self, content_id: str, *, owner_profile_id: str, workspace_id: str,
        target: str, detail: str, event_detail: Mapping[str, object] | None = None,
        expected_reservation_id: str | None = None,
        provider_item_id: str | None = None,
    ) -> ContentProjectionV1:
        key = _identifier(content_id, "content_id")
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        if target not in _STATES:
            raise ContentLifecycleContractError("target state is invalid")
        now = _timestamp(self._clock(), "clock")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM content_items WHERE content_id=? AND owner_profile_id=? AND workspace_id=?",
                (key, owner, workspace),
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise ContentLifecycleDenied("content item is unavailable")
            current = str(row["status"])
            if target not in _TRANSITIONS[current]:
                connection.execute("ROLLBACK")
                raise ContentLifecycleDenied(f"transition {current} to {target} is forbidden")
            if expected_reservation_id is not None and str(row["reservation_id"]) != expected_reservation_id:
                connection.execute("ROLLBACK")
                raise ContentLifecycleDenied("reservation binding diverged")
            reservation_id = row["reservation_id"]
            idempotency_key = row["idempotency_key"]
            if target == "reserved":
                reservation_id = "reservation_" + uuid.uuid4().hex
                idempotency_key = "publish_" + uuid.uuid4().hex
            connection.execute(
                "UPDATE content_items SET status=?,reservation_id=?,idempotency_key=?,provider_item_id=COALESCE(?,provider_item_id),detail=?,updated_at=? WHERE content_id=?",
                (target, reservation_id, idempotency_key, provider_item_id, detail, now, key),
            )
            event = dict(event_detail or {})
            if reservation_id is not None:
                event["reservation_id"] = str(reservation_id)
            if idempotency_key is not None:
                event["idempotency_key"] = str(idempotency_key)
            self._event(connection, key, f"content.{target}", event, now)
            connection.execute("COMMIT")
        return self.get(key, owner_profile_id=owner, workspace_id=workspace)

    def reserve(
        self, content_id: str, *, owner_profile_id: str, workspace_id: str,
        authority: Callable[[str, str, str, str, str], bool],
    ) -> ContentProjectionV1:
        if not callable(authority):
            raise ContentLifecycleContractError("authority is invalid")
        current = self.get(content_id, owner_profile_id=owner_profile_id, workspace_id=workspace_id)
        decision = authority(
            current.owner_profile_id, current.workspace_id, "content.publish.reserve",
            current.account_id, current.destination_id,
        )
        if type(decision) is not bool or not decision:
            raise ContentLifecycleDenied("central authority denied content reservation")
        return self._transition(
            content_id, owner_profile_id=owner_profile_id, workspace_id=workspace_id,
            target="reserved", detail="reserved_before_provider_effect",
        )

    def begin_publish(
        self, content_id: str, *, owner_profile_id: str, workspace_id: str,
        reservation_id: str,
    ) -> ContentProjectionV1:
        reservation = _identifier(reservation_id, "reservation_id")
        return self._transition(
            content_id, owner_profile_id=owner_profile_id, workspace_id=workspace_id,
            target="publishing", detail="provider_effect_may_begin",
            expected_reservation_id=reservation,
        )

    def record_receipt(
        self, receipt: ContentProviderReceiptV1, *, owner_profile_id: str,
        workspace_id: str,
    ) -> ContentProjectionV1:
        if type(receipt) is not ContentProviderReceiptV1:
            raise ContentLifecycleContractError("exact provider receipt is required")
        current = self.get(
            receipt.content_id, owner_profile_id=owner_profile_id, workspace_id=workspace_id
        )
        expected = (
            current.content_id, current.reservation_id, current.provider,
            current.account_id, current.destination_id, current.content_digest,
        )
        observed = (
            receipt.content_id, receipt.reservation_id, receipt.provider,
            receipt.account_id, receipt.destination_id, receipt.content_digest,
        )
        if observed != expected:
            raise ContentLifecycleDenied("provider receipt binding diverged")
        with self._connect() as connection:
            key = connection.execute(
                "SELECT idempotency_key FROM content_items WHERE content_id=?",
                (current.content_id,),
            ).fetchone()
        if key is None or str(key[0]) != receipt.idempotency_key:
            raise ContentLifecycleDenied("provider receipt idempotency diverged")
        return self._transition(
            current.content_id, owner_profile_id=owner_profile_id,
            workspace_id=workspace_id, target="published",
            detail="provider_receipt_verified",
            event_detail={"provider_item_id": receipt.provider_item_id,
                          "content_digest": receipt.content_digest},
            expected_reservation_id=receipt.reservation_id,
            provider_item_id=receipt.provider_item_id,
        )

    def mark_uncertain(
        self, content_id: str, *, owner_profile_id: str, workspace_id: str,
        reservation_id: str,
    ) -> ContentProjectionV1:
        return self._transition(
            content_id, owner_profile_id=owner_profile_id, workspace_id=workspace_id,
            target="reconciliation", detail="provider_outcome_unknown_no_retry",
            expected_reservation_id=_identifier(reservation_id, "reservation_id"),
        )

    def mark_failed(
        self, content_id: str, *, owner_profile_id: str, workspace_id: str,
        reservation_id: str,
    ) -> ContentProjectionV1:
        return self._transition(
            content_id, owner_profile_id=owner_profile_id, workspace_id=workspace_id,
            target="failed", detail="provider_failure_verified",
            expected_reservation_id=_identifier(reservation_id, "reservation_id"),
        )

    def cancel(
        self, content_id: str, *, owner_profile_id: str, workspace_id: str,
    ) -> ContentProjectionV1:
        return self._transition(
            content_id, owner_profile_id=owner_profile_id, workspace_id=workspace_id,
            target="cancelled", detail="cancelled_before_provider_effect",
        )

    def get(
        self, content_id: str, *, owner_profile_id: str, workspace_id: str,
    ) -> ContentProjectionV1:
        key = _identifier(content_id, "content_id")
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM content_items WHERE content_id=? AND owner_profile_id=? AND workspace_id=?",
                (key, owner, workspace),
            ).fetchone()
        if row is None:
            raise ContentLifecycleDenied("content item is unavailable")
        return self._row(row)

    def list_items(
        self, *, owner_profile_id: str, workspace_id: str, limit: int = 50,
    ) -> tuple[ContentProjectionV1, ...]:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        if type(limit) is not int or isinstance(limit, bool) or not 1 <= limit <= MAX_LIST_ITEMS:
            raise ContentLifecycleContractError("limit is invalid")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM content_items WHERE owner_profile_id=? AND workspace_id=? ORDER BY updated_at DESC,content_id DESC LIMIT ?",
                (owner, workspace, limit),
            ).fetchall()
        return tuple(self._row(row) for row in rows)


__all__ = [
    "FEATURE_FLAG", "ContentProjectionV1", "ContentProviderReceiptV1",
    "ContentLifecycleProjectionV1", "ContentLifecycleError",
    "ContentLifecycleContractError", "ContentLifecycleDenied",
]
