"""Default-off authenticated ASGI receiver for the Onyx device mesh.

The receiver is intentionally not a remote executor.  It accepts only signed
health, capability-advertisement and receipt-ingestion envelopes, persists an
intent before consulting the central authority, and returns a replay-stable
acknowledgement.  A later deployable sidecar may mount this adapter on the
existing TLS dashboard; importing this module starts no listener or worker.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import concurrent.futures
import hashlib
import hmac
import json
import math
import os
import sqlite3
import stat
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Iterator, Mapping, Protocol

from core.device_mesh_v1 import (
    AuthenticatedDeviceMeshV1,
    AuthenticatedMeshRequestV1,
    DeviceMeshContractError,
    DeviceMeshDenied,
)
from core.phase6_agentic_core_v6 import normalized_sql_v6


FEATURE_FLAG = "ONYX_DEVICE_MESH_RECEIVER_V1"
CONTRACT_REQUEST = "OnyxDeviceMeshHttpsRequest.v1"
CONTRACT_ACK = "OnyxDeviceMeshHttpsAck.v1"
CAPABILITY_HEALTH = "mesh.health.read"
CAPABILITY_ADVERTISE = "mesh.capabilities.read"
CAPABILITY_RECEIPT = "mesh.receipt.ingest"
RECEIVER_RESOURCE = "device_mesh_receiver"
MAX_WIRE_BYTES = 96_000
MAX_RESPONSE_BYTES = 16_384
MAX_RECEIPT_PAYLOAD_BYTES = 8_192
MAX_CONCURRENCY = 8
MAX_REQUEST_SECONDS = 5.0
MAX_SOURCE_REQUESTS = 60
RATE_WINDOW_SECONDS = 60.0
MAX_BODY_CHUNKS = 128
_MAX_PROJECTION_ROW_BYTES = 262_144
_MAX_PROJECTION_FIELD_CHARS = 131_072
_ZERO_HASH = "0" * 64
_RECEIPT_STATUSES = frozenset(
    {"accepted", "succeeded", "denied", "failed", "reconciliation"}
)


class DeviceMeshReceiverError(RuntimeError):
    pass


class DeviceMeshReceiverContractError(ValueError):
    pass


class DeviceMeshReceiverDenied(PermissionError):
    pass


class DeviceMeshReceiverReplay(DeviceMeshReceiverDenied):
    pass


class _DigestWriter(Protocol):
    def update(self, data: bytes) -> object: ...


def _canonical(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise DeviceMeshReceiverContractError("value is not canonical JSON") from exc
    if len(encoded.encode("ascii")) > MAX_RESPONSE_BYTES:
        raise DeviceMeshReceiverContractError("value exceeds its byte budget")
    return encoded


def _projection_row_json(row: sqlite3.Row) -> bytes:
    values = list(row)
    if any(
        isinstance(value, str) and len(value) > _MAX_PROJECTION_FIELD_CHARS
        for value in values
    ):
        raise DeviceMeshReceiverError(
            "receiver projection row exceeds its storage budget"
        )
    encoded = json.dumps(
        values,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    if len(encoded) > _MAX_PROJECTION_ROW_BYTES:
        raise DeviceMeshReceiverError(
            "receiver projection row exceeds its storage budget"
        )
    return encoded


def _update_projection_rows(
    digest: _DigestWriter, connection: sqlite3.Connection, query: str
) -> None:
    digest.update(b"[")
    first = True
    for row in connection.execute(query):
        if not first:
            digest.update(b",")
        digest.update(_projection_row_json(row))
        first = False
    digest.update(b"]")


def _private_path(path: Path) -> None:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise DeviceMeshReceiverContractError(
            "an absolute receiver database is required"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or (path.exists() and path.is_symlink()):
        raise DeviceMeshReceiverDenied("linked receiver storage is forbidden")
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if getattr(path.parent.stat(), "st_file_attributes", 0) & reparse:
        raise DeviceMeshReceiverDenied("reparse-point receiver storage is forbidden")


@dataclass(frozen=True, slots=True)
class DeviceMeshReceiverFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise DeviceMeshReceiverContractError("enabled must be an exact boolean")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "DeviceMeshReceiverFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True, slots=True)
class ReceiverReceiptV1:
    request_id: str
    status: str
    http_status: int
    response: dict[str, object]
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class ReceiptClaimV1:
    origin_request_id: str
    owner_profile_id: str
    workspace_id: str
    target_device_id: str
    payload_digest: str
    receipt_status: str


@dataclass(frozen=True, slots=True)
class OutboundDispatchBindingV1:
    origin_request_id: str
    owner_profile_id: str
    workspace_id: str
    target_device_id: str
    payload_digest: str
    receipt_status: str


@dataclass(frozen=True, slots=True)
class _ReservationV1:
    fresh: bool
    receipt: ReceiverReceiptV1 | None


class DeviceMeshReceiverStoreV1:
    """Durable request intent and replay-stable receipt store."""

    _LEGACY_DDL = (
        """CREATE TABLE receiver_intents(
          request_id TEXT PRIMARY KEY,
          source_device_id TEXT NOT NULL,
          nonce TEXT NOT NULL,
          envelope_digest TEXT NOT NULL,
          payload_digest TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN
            ('intent','accepted','denied','reconciliation')),
          http_status INTEGER NOT NULL,
          response_json TEXT NOT NULL,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          UNIQUE(source_device_id,nonce)
        )""",
        """CREATE TABLE receiver_events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          request_id TEXT NOT NULL,
          occurred_at REAL NOT NULL,
          event TEXT NOT NULL,
          detail_json TEXT NOT NULL,
          prev_hash TEXT NOT NULL,
          event_hash TEXT NOT NULL UNIQUE
        )""",
        """CREATE INDEX idx_receiver_intents_status
          ON receiver_intents(status,updated_at)""",
        """CREATE TRIGGER receiver_events_no_update BEFORE UPDATE ON receiver_events
          BEGIN SELECT RAISE(ABORT,'receiver events are immutable'); END""",
        """CREATE TRIGGER receiver_events_no_delete BEFORE DELETE ON receiver_events
          BEGIN SELECT RAISE(ABORT,'receiver events are immutable'); END""",
    )
    _LEDGER_DDL = (
        """CREATE TABLE receiver_ledger_head(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1),
          event_count INTEGER NOT NULL CHECK(event_count>=0),
          tail_seq INTEGER NOT NULL CHECK(tail_seq>=0),
          tail_hash TEXT NOT NULL CHECK(length(tail_hash)=64 AND tail_hash NOT GLOB '*[^0-9a-f]*'),
          projection_digest TEXT NOT NULL CHECK(length(projection_digest)=64 AND projection_digest NOT GLOB '*[^0-9a-f]*'),
          anchor_hash TEXT NOT NULL CHECK(length(anchor_hash)=64 AND anchor_hash NOT GLOB '*[^0-9a-f]*')
        )""",
        """CREATE TRIGGER receiver_ledger_head_update_guard
          BEFORE UPDATE ON receiver_ledger_head
          WHEN NOT (
            OLD.singleton=1 AND NEW.singleton=1 AND
            NEW.event_count=OLD.event_count+1 AND
            NEW.tail_seq=OLD.tail_seq+1 AND
            NEW.event_count=(SELECT COUNT(*) FROM receiver_events) AND
            NEW.tail_seq=COALESCE((SELECT MAX(seq) FROM receiver_events),0) AND
            NEW.tail_hash=COALESCE((SELECT event_hash FROM receiver_events ORDER BY seq DESC LIMIT 1),printf('%064d',0))
          )
          BEGIN SELECT RAISE(ABORT,'receiver ledger head transition is invalid'); END""",
        """CREATE TRIGGER receiver_ledger_head_no_delete BEFORE DELETE ON receiver_ledger_head
          BEGIN SELECT RAISE(ABORT,'receiver ledger head is immutable'); END""",
        """CREATE TRIGGER receiver_ledger_head_no_insert BEFORE INSERT ON receiver_ledger_head
          WHEN (SELECT COUNT(*) FROM receiver_ledger_head)>0
          BEGIN SELECT RAISE(ABORT,'receiver ledger head already exists'); END""",
    )
    _DDL = _LEGACY_DDL + _LEDGER_DDL

    def __init__(
        self,
        path: Path | str,
        gate: DeviceMeshReceiverFeatureGateV1,
        *,
        ledger_auth_key: bytes | bytearray | None = None,
        trust_legacy_ledger: bool = False,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if type(gate) is not DeviceMeshReceiverFeatureGateV1 or not gate.enabled:
            raise DeviceMeshReceiverDenied("device mesh receiver is disabled")
        if (
            not isinstance(ledger_auth_key, (bytes, bytearray))
            or len(ledger_auth_key) != 32
        ):
            raise DeviceMeshReceiverDenied(
                "receiver ledger authentication key is unavailable"
            )
        if type(trust_legacy_ledger) is not bool:
            raise DeviceMeshReceiverContractError(
                "legacy ledger trust must be an exact boolean"
            )
        if not callable(clock):
            raise DeviceMeshReceiverContractError("clock is invalid")
        self.path = Path(path)
        _private_path(self.path)
        self._ledger_auth_key = bytes(ledger_auth_key)
        self._trust_legacy_ledger = trust_legacy_ledger
        self._clock = clock
        self._lock = threading.RLock()
        self._expected_signature = self._build_expected_signature()
        self._legacy_signature = self._build_signature(self._LEGACY_DDL)
        self._initialize()

    @staticmethod
    def _signature(connection: sqlite3.Connection) -> str:
        objects = []
        for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ):
            if row[3] is None:
                raise DeviceMeshReceiverError("receiver schema object has no SQL")
            objects.append((row[0], row[1], row[2], normalized_sql_v6(str(row[3]))))
        details: dict[str, object] = {}
        for table in sorted(row[1] for row in objects if row[0] == "table"):
            details[f"table_xinfo:{table}"] = [
                tuple(item)
                for item in connection.execute(f"PRAGMA table_xinfo('{table}')")
            ]
            details[f"foreign_key_list:{table}"] = [
                tuple(item)
                for item in connection.execute(f"PRAGMA foreign_key_list('{table}')")
            ]
        return hashlib.sha256(
            _canonical({"objects": objects, "details": details}).encode("ascii")
        ).hexdigest()

    @classmethod
    def _build_signature(cls, ddl: tuple[str, ...]) -> str:
        connection = sqlite3.connect(":memory:")
        try:
            for statement in ddl:
                connection.execute(statement)
            connection.execute("PRAGMA user_version=1")
            return cls._signature(connection)
        finally:
            connection.close()

    @classmethod
    def _build_expected_signature(cls) -> str:
        return cls._build_signature(cls._DDL)

    def _connect(self) -> sqlite3.Connection:
        _private_path(self.path)
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @contextmanager
    def _verified_transaction(self) -> Iterator[sqlite3.Connection]:
        """Lock, authenticate the current ledger projection, then do one operation."""

        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._validate_ledger_head(connection)
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    @staticmethod
    def _projection_digest(connection: sqlite3.Connection) -> str:
        digest = hashlib.sha256()
        _update_projection_rows(
            digest,
            connection,
            "SELECT * FROM receiver_intents ORDER BY request_id",
        )
        return digest.hexdigest()

    def _anchor_hash(
        self,
        event_count: int,
        tail_seq: int,
        tail_hash: str,
        projection_digest: str,
    ) -> str:
        return hmac.new(
            self._ledger_auth_key,
            _canonical(
                {
                    "event_count": event_count,
                    "tail_seq": tail_seq,
                    "tail_hash": tail_hash,
                    "projection_digest": projection_digest,
                }
            ).encode("ascii"),
            hashlib.sha256,
        ).hexdigest()

    def _initialize_ledger_head(self, connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT COUNT(*),COALESCE(MAX(seq),0) FROM receiver_events"
        ).fetchone()
        event_count, tail_seq = int(row[0]), int(row[1])
        tail = connection.execute(
            "SELECT event_hash FROM receiver_events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        tail_hash = _ZERO_HASH if tail is None else str(tail[0])
        projection_digest = self._projection_digest(connection)
        connection.execute(
            "INSERT INTO receiver_ledger_head VALUES(1,?,?,?,?,?)",
            (
                event_count,
                tail_seq,
                tail_hash,
                projection_digest,
                self._anchor_hash(event_count, tail_seq, tail_hash, projection_digest),
            ),
        )

    @classmethod
    def _validate_event_chain(
        cls, connection: sqlite3.Connection
    ) -> tuple[int, int, str]:
        previous_hash = _ZERO_HASH
        expected_sequence = 1
        for row in connection.execute(
            "SELECT seq,request_id,occurred_at,event,detail_json,prev_hash,event_hash "
            "FROM receiver_events ORDER BY seq"
        ):
            sequence = int(row[0])
            request_id = str(row[1])
            occurred_at = float(row[2])
            event = str(row[3])
            detail_json = str(row[4])
            prev_hash = str(row[5])
            event_hash = str(row[6])
            try:
                detail = json.loads(detail_json)
            except json.JSONDecodeError as exc:
                raise DeviceMeshReceiverError(
                    "receiver event chain is invalid"
                ) from exc
            if (
                sequence != expected_sequence
                or not request_id
                or not event
                or not math.isfinite(occurred_at)
                or occurred_at <= 0
                or type(detail) is not dict
                or _canonical(detail) != detail_json
                or prev_hash != previous_hash
            ):
                raise DeviceMeshReceiverError("receiver event chain is invalid")
            expected_hash = hashlib.sha256(
                _canonical(
                    {
                        "request_id": request_id,
                        "occurred_at": occurred_at,
                        "event": event,
                        "detail_json": detail_json,
                        "prev_hash": previous_hash,
                    }
                ).encode("ascii")
            ).hexdigest()
            if not hmac.compare_digest(expected_hash, event_hash):
                raise DeviceMeshReceiverError("receiver event chain is invalid")
            previous_hash = event_hash
            expected_sequence += 1
        return expected_sequence - 1, expected_sequence - 1, previous_hash

    def _validate_ledger_head(self, connection: sqlite3.Connection) -> None:
        event_count, tail_seq, tail_hash = self._validate_event_chain(connection)
        rows = connection.execute("SELECT * FROM receiver_ledger_head").fetchall()
        if len(rows) != 1:
            raise DeviceMeshReceiverError("receiver ledger anchor is invalid")
        row = rows[0]
        projection_digest = self._projection_digest(connection)
        expected_anchor = self._anchor_hash(
            event_count, tail_seq, tail_hash, projection_digest
        )
        if (
            int(row["singleton"]) != 1
            or int(row["event_count"]) != event_count
            or int(row["tail_seq"]) != tail_seq
            or not hmac.compare_digest(str(row["tail_hash"]), tail_hash)
            or not hmac.compare_digest(str(row["projection_digest"]), projection_digest)
            or not hmac.compare_digest(str(row["anchor_hash"]), expected_anchor)
        ):
            raise DeviceMeshReceiverError("receiver ledger anchor is invalid")

    def _advance_ledger_head(
        self, connection: sqlite3.Connection, sequence: int, tail_hash: str
    ) -> None:
        row = connection.execute("SELECT * FROM receiver_ledger_head").fetchone()
        if row is None:
            raise DeviceMeshReceiverError("receiver ledger anchor is unavailable")
        event_count = int(row["event_count"]) + 1
        projection_digest = self._projection_digest(connection)
        anchor_hash = self._anchor_hash(
            event_count, sequence, tail_hash, projection_digest
        )
        changed = connection.execute(
            "UPDATE receiver_ledger_head SET event_count=?,tail_seq=?,tail_hash=?,"
            "projection_digest=?,anchor_hash=? WHERE singleton=1",
            (event_count, sequence, tail_hash, projection_digest, anchor_hash),
        ).rowcount
        if changed != 1:
            raise DeviceMeshReceiverError("receiver ledger anchor update failed")

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
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
                connection.execute("PRAGMA user_version=1")
                self._initialize_ledger_head(connection)
                connection.execute("COMMIT")
            elif version == 1 and self._signature(connection) == self._legacy_signature:
                if not self._trust_legacy_ledger:
                    raise DeviceMeshReceiverDenied(
                        "legacy receiver ledger requires explicit trusted initialization"
                    )
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise DeviceMeshReceiverError(
                        "receiver storage authentication failed"
                    )
                self._validate_event_chain(connection)
                for statement in self._LEDGER_DDL:
                    connection.execute(statement)
                self._initialize_ledger_head(connection)
                connection.execute("COMMIT")
            connection.execute("BEGIN IMMEDIATE")
            if (
                int(connection.execute("PRAGMA user_version").fetchone()[0]) != 1
                or self._signature(connection) != self._expected_signature
                or connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            ):
                raise DeviceMeshReceiverError("receiver storage authentication failed")
            self._validate_ledger_head(connection)
            connection.execute("COMMIT")

    def _now(self) -> float:
        value = self._clock()
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0
        ):
            raise DeviceMeshReceiverContractError("clock is invalid")
        return float(value)

    def _event(
        self,
        connection: sqlite3.Connection,
        request_id: str,
        event: str,
        detail: Mapping[str, object],
        occurred_at: float,
    ) -> None:
        previous = connection.execute(
            "SELECT event_hash FROM receiver_events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev_hash = _ZERO_HASH if previous is None else str(previous[0])
        detail_json = _canonical(dict(detail))
        event_hash = hashlib.sha256(
            _canonical(
                {
                    "request_id": request_id,
                    "occurred_at": occurred_at,
                    "event": event,
                    "detail_json": detail_json,
                    "prev_hash": prev_hash,
                }
            ).encode("ascii")
        ).hexdigest()
        cursor = connection.execute(
            "INSERT INTO receiver_events VALUES(NULL,?,?,?,?,?,?)",
            (request_id, occurred_at, event, detail_json, prev_hash, event_hash),
        )
        sequence = int(cursor.lastrowid or 0)
        if sequence <= 0:
            raise DeviceMeshReceiverError("receiver event sequence is invalid")
        self._advance_ledger_head(connection, sequence, event_hash)

    @staticmethod
    def _envelope_digest(request: AuthenticatedMeshRequestV1) -> str:
        envelope = {**request.unsigned_claims(), "signature": request.signature}
        return hashlib.sha256(_canonical(envelope).encode("ascii")).hexdigest()

    @staticmethod
    def _row_receipt(row: sqlite3.Row, *, duplicate: bool) -> ReceiverReceiptV1:
        response = json.loads(str(row["response_json"]))
        if type(response) is not dict:
            raise DeviceMeshReceiverError("stored receiver response is invalid")
        return ReceiverReceiptV1(
            str(row["request_id"]),
            str(row["status"]),
            int(row["http_status"]),
            response,
            duplicate,
        )

    def existing(self, request: AuthenticatedMeshRequestV1) -> _ReservationV1:
        """Read an exact prior request without creating rows or events."""

        envelope_digest = self._envelope_digest(request)
        with self._verified_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM receiver_intents WHERE request_id=?",
                (request.request_id,),
            ).fetchone()
            if row is None:
                nonce = connection.execute(
                    "SELECT request_id FROM receiver_intents "
                    "WHERE source_device_id=? AND nonce=?",
                    (request.source_device_id, request.nonce),
                ).fetchone()
                if nonce is not None:
                    raise DeviceMeshReceiverReplay("source nonce was already observed")
                return _ReservationV1(True, None)
        if (
            str(row["source_device_id"]) != request.source_device_id
            or str(row["nonce"]) != request.nonce
            or str(row["envelope_digest"]) != envelope_digest
            or str(row["payload_digest"]) != request.payload_digest
        ):
            raise DeviceMeshReceiverReplay("request identifier was rebound")
        if str(row["status"]) == "intent":
            return _ReservationV1(False, None)
        return _ReservationV1(False, self._row_receipt(row, duplicate=True))

    def reserve(self, request: AuthenticatedMeshRequestV1) -> _ReservationV1:
        envelope_digest = self._envelope_digest(request)
        now = self._now()
        with self._verified_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM receiver_intents WHERE request_id=?",
                (request.request_id,),
            ).fetchone()
            if row is not None:
                if (
                    str(row["source_device_id"]) != request.source_device_id
                    or str(row["nonce"]) != request.nonce
                    or str(row["envelope_digest"]) != envelope_digest
                    or str(row["payload_digest"]) != request.payload_digest
                ):
                    raise DeviceMeshReceiverReplay("request identifier was rebound")
                if str(row["status"]) == "intent":
                    return _ReservationV1(False, None)
                return _ReservationV1(False, self._row_receipt(row, duplicate=True))
            nonce = connection.execute(
                "SELECT request_id FROM receiver_intents "
                "WHERE source_device_id=? AND nonce=?",
                (request.source_device_id, request.nonce),
            ).fetchone()
            if nonce is not None:
                raise DeviceMeshReceiverReplay("source nonce was already observed")
            connection.execute(
                "INSERT INTO receiver_intents VALUES(?,?,?,?,?,'intent',0,'',?,?)",
                (
                    request.request_id,
                    request.source_device_id,
                    request.nonce,
                    envelope_digest,
                    request.payload_digest,
                    now,
                    now,
                ),
            )
            self._event(
                connection,
                request.request_id,
                "receiver.intent.persisted",
                {
                    "source_device_id": request.source_device_id,
                    "capability": request.capability,
                    "payload_digest": request.payload_digest,
                },
                now,
            )
        return _ReservationV1(True, None)

    def complete(
        self,
        request_id: str,
        *,
        status: str,
        http_status: int,
        response: Mapping[str, object],
    ) -> ReceiverReceiptV1:
        if status not in {"accepted", "denied", "reconciliation"}:
            raise DeviceMeshReceiverContractError("receiver status is invalid")
        if type(http_status) is not int or not 200 <= http_status <= 599:
            raise DeviceMeshReceiverContractError("HTTP status is invalid")
        response_json = _canonical(dict(response))
        now = self._now()
        with self._verified_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM receiver_intents WHERE request_id=?", (request_id,)
            ).fetchone()
            if row is None:
                raise DeviceMeshReceiverError("receiver intent is unavailable")
            if str(row["status"]) != "intent":
                return self._row_receipt(row, duplicate=True)
            connection.execute(
                "UPDATE receiver_intents SET status=?,http_status=?,response_json=?,"
                "updated_at=? WHERE request_id=? AND status='intent'",
                (status, http_status, response_json, now, request_id),
            )
            self._event(
                connection,
                request_id,
                f"receiver.{status}",
                {"http_status": http_status},
                now,
            )
            row = connection.execute(
                "SELECT * FROM receiver_intents WHERE request_id=?", (request_id,)
            ).fetchone()
        assert row is not None
        return self._row_receipt(row, duplicate=False)

    def reconcile(self, request_id: str, detail: str) -> ReceiverReceiptV1 | None:
        response = {
            "contract": CONTRACT_ACK,
            "request_id": request_id,
            "status": "reconciliation",
            "result": {"detail": detail},
        }
        try:
            return self.complete(
                request_id,
                status="reconciliation",
                http_status=202,
                response=response,
            )
        except DeviceMeshReceiverError:
            return None

    def receipt(self, request_id: str) -> ReceiverReceiptV1:
        if type(request_id) is not str or not request_id:
            raise DeviceMeshReceiverContractError("request identifier is invalid")
        with self._verified_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM receiver_intents WHERE request_id=?", (request_id,)
            ).fetchone()
        if row is None or str(row["status"]) == "intent":
            raise DeviceMeshReceiverError("terminal receiver receipt is unavailable")
        return self._row_receipt(row, duplicate=False)

    def recover_uncertain(self) -> int:
        now = self._now()
        with self._verified_transaction() as connection:
            rows = connection.execute(
                "SELECT request_id FROM receiver_intents WHERE status='intent'"
            ).fetchall()
            for row in rows:
                request_id = str(row[0])
                response = _canonical(
                    {
                        "contract": CONTRACT_ACK,
                        "request_id": request_id,
                        "status": "reconciliation",
                        "result": {"detail": "restart_requires_reconciliation"},
                    }
                )
                connection.execute(
                    "UPDATE receiver_intents SET status='reconciliation',http_status=202,"
                    "response_json=?,updated_at=? WHERE request_id=? AND status='intent'",
                    (response, now, request_id),
                )
                self._event(
                    connection,
                    request_id,
                    "receiver.reconciliation",
                    {"http_status": 202},
                    now,
                )
        return len(rows)


class DeviceMeshReceiverV1:
    """Authenticates and records receiver requests; never executes a remote action."""

    def __init__(
        self,
        *,
        mesh: AuthenticatedDeviceMeshV1,
        store: DeviceMeshReceiverStoreV1,
        authority: Callable[[str, str, str, str, str], bool],
        outbound_dispatch_lookup: Callable[[str], OutboundDispatchBindingV1 | None]
        | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        max_source_requests: int = MAX_SOURCE_REQUESTS,
        rate_window_seconds: float = RATE_WINDOW_SECONDS,
    ) -> None:
        if type(mesh) is not AuthenticatedDeviceMeshV1:
            raise DeviceMeshReceiverContractError(
                "exact authenticated mesh is required"
            )
        if type(store) is not DeviceMeshReceiverStoreV1:
            raise DeviceMeshReceiverContractError("exact receiver store is required")
        if not callable(authority) or not callable(monotonic_clock):
            raise DeviceMeshReceiverContractError("receiver dependencies are invalid")
        if outbound_dispatch_lookup is not None and not callable(
            outbound_dispatch_lookup
        ):
            raise DeviceMeshReceiverContractError("outbound dispatch lookup is invalid")
        if (
            type(max_source_requests) is not int
            or not 1 <= max_source_requests <= 10_000
        ):
            raise DeviceMeshReceiverContractError("rate request budget is invalid")
        if (
            isinstance(rate_window_seconds, bool)
            or not isinstance(rate_window_seconds, (int, float))
            or not 1.0 <= float(rate_window_seconds) <= 3_600.0
        ):
            raise DeviceMeshReceiverContractError("rate window is invalid")
        self._mesh = mesh
        self.store = store
        self._authority = authority
        self._outbound_dispatch_lookup = outbound_dispatch_lookup
        self._monotonic = monotonic_clock
        self._max_source_requests = max_source_requests
        self._rate_window_seconds = float(rate_window_seconds)
        self._rate_lock = threading.Lock()
        self._source_rates: dict[str, deque[float]] = {}
        self.background_workers = 0
        self.polling_interval = None
        self.recovered_on_startup = self.store.recover_uncertain()

    def _source_rate_allowed(self, source_device_id: str) -> bool:
        now = float(self._monotonic())
        if not math.isfinite(now):
            raise DeviceMeshReceiverContractError("monotonic clock is invalid")
        cutoff = now - self._rate_window_seconds
        with self._rate_lock:
            stamps = self._source_rates.setdefault(source_device_id, deque())
            while stamps and stamps[0] <= cutoff:
                stamps.popleft()
            if len(stamps) >= self._max_source_requests:
                return False
            stamps.append(now)
            return True

    @staticmethod
    def _ack(
        request: AuthenticatedMeshRequestV1,
        status: str,
        result: Mapping[str, object],
    ) -> dict[str, object]:
        return {
            "contract": CONTRACT_ACK,
            "request_id": request.request_id,
            "status": status,
            "result": dict(result),
        }

    @staticmethod
    def _parse_operation(
        request: AuthenticatedMeshRequestV1, payload: bytes
    ) -> tuple[dict[str, object], ReceiptClaimV1 | None]:
        if request.capability in {CAPABILITY_HEALTH, CAPABILITY_ADVERTISE}:
            if request.resource != RECEIVER_RESOURCE or payload != b"{}":
                raise DeviceMeshReceiverDenied("receiver capability binding is invalid")
            if request.capability == CAPABILITY_HEALTH:
                return {"state": "ready", "remote_execution": False}, None
            return (
                {
                    "capabilities": [
                        CAPABILITY_HEALTH,
                        CAPABILITY_ADVERTISE,
                        CAPABILITY_RECEIPT,
                    ],
                    "remote_execution": False,
                },
                None,
            )
        if request.capability != CAPABILITY_RECEIPT:
            raise DeviceMeshReceiverDenied("remote action is unsupported")
        if len(payload) > MAX_RECEIPT_PAYLOAD_BYTES:
            raise DeviceMeshReceiverContractError("receipt exceeds its byte budget")
        try:
            receipt = json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DeviceMeshReceiverContractError("receipt payload is invalid") from exc
        if type(receipt) is not dict or set(receipt) != {
            "contract",
            "origin_request_id",
            "status",
            "payload_digest",
        }:
            raise DeviceMeshReceiverContractError("receipt contract is invalid")
        if receipt["contract"] != "OnyxDeviceMeshReceipt.v1":
            raise DeviceMeshReceiverContractError("receipt contract is invalid")
        origin = receipt["origin_request_id"]
        status = receipt["status"]
        digest = receipt["payload_digest"]
        if (
            type(origin) is not str
            or request.resource != origin
            or type(status) is not str
            or status not in _RECEIPT_STATUSES
            or type(digest) is not str
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            raise DeviceMeshReceiverDenied("receipt binding is invalid")
        claim = ReceiptClaimV1(
            origin,
            request.owner_profile_id,
            request.workspace_id,
            request.source_device_id,
            digest,
            status,
        )
        return (
            {
                "origin_request_id": origin,
                "receipt_status": status,
                "receipt_payload_digest": digest,
            },
            claim,
        )

    @staticmethod
    def _binding_matches(claim: ReceiptClaimV1, binding: object) -> bool:
        return type(binding) is OutboundDispatchBindingV1 and binding == (
            OutboundDispatchBindingV1(
                claim.origin_request_id,
                claim.owner_profile_id,
                claim.workspace_id,
                claim.target_device_id,
                claim.payload_digest,
                claim.receipt_status,
            )
        )

    def process(
        self, request: AuthenticatedMeshRequestV1, payload: bytes
    ) -> ReceiverReceiptV1:
        raw = self._mesh.authenticate(request, payload)
        observed = self.store.existing(request)
        if observed.receipt is not None:
            return observed.receipt
        if not observed.fresh:
            receipt = self.store.reconcile(
                request.request_id, "concurrent_or_interrupted_request"
            )
            if receipt is None:
                raise DeviceMeshReceiverError("receiver intent is unavailable")
            return receipt
        if not self._source_rate_allowed(request.source_device_id):
            return ReceiverReceiptV1(
                request.request_id,
                "denied",
                429,
                self._ack(request, "denied", {"reason": "rate_limited"}),
            )
        try:
            result, claim = self._parse_operation(request, raw)
        except (DeviceMeshReceiverContractError, DeviceMeshReceiverDenied) as exc:
            return ReceiverReceiptV1(
                request.request_id,
                "denied",
                403,
                self._ack(request, "denied", {"reason": type(exc).__name__}),
            )
        if claim is not None and self._outbound_dispatch_lookup is None:
            return ReceiverReceiptV1(
                request.request_id,
                "denied",
                503,
                self._ack(
                    request,
                    "denied",
                    {"reason": "outbound_dispatch_authority_unavailable"},
                ),
            )
        reservation = self.store.reserve(request)
        if reservation.receipt is not None:
            return reservation.receipt
        if not reservation.fresh:
            receipt = self.store.reconcile(
                request.request_id, "concurrent_or_interrupted_request"
            )
            if receipt is None:
                raise DeviceMeshReceiverError("receiver intent is unavailable")
            return receipt
        if claim is not None:
            assert self._outbound_dispatch_lookup is not None
            binding = self._outbound_dispatch_lookup(claim.origin_request_id)
            if not self._binding_matches(claim, binding):
                return self.store.complete(
                    request.request_id,
                    status="denied",
                    http_status=403,
                    response=self._ack(
                        request,
                        "denied",
                        {"reason": "outbound_dispatch_binding_denied"},
                    ),
                )
        allowed = self._authority(
            request.owner_profile_id,
            request.workspace_id,
            request.capability,
            request.resource,
            request.source_device_id,
        )
        if type(allowed) is not bool or not allowed:
            return self.store.complete(
                request.request_id,
                status="denied",
                http_status=403,
                response=self._ack(
                    request, "denied", {"reason": "central_authority_denied"}
                ),
            )
        return self.store.complete(
            request.request_id,
            status="accepted",
            http_status=202,
            response=self._ack(request, "accepted", result),
        )


def decode_https_request_v1(wire: bytes) -> tuple[AuthenticatedMeshRequestV1, bytes]:
    if type(wire) is not bytes or not wire or len(wire) > MAX_WIRE_BYTES:
        raise DeviceMeshReceiverContractError("wire request exceeds its byte budget")
    try:
        envelope = json.loads(wire.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeviceMeshReceiverContractError("wire request is invalid JSON") from exc
    if type(envelope) is not dict or set(envelope) != {
        "contract",
        "request",
        "payload_base64",
    }:
        raise DeviceMeshReceiverContractError("wire contract is invalid")
    if (
        envelope["contract"] != CONTRACT_REQUEST
        or type(envelope["request"]) is not dict
    ):
        raise DeviceMeshReceiverContractError("wire contract is invalid")
    fields = {
        "request_id",
        "source_device_id",
        "target_device_id",
        "owner_profile_id",
        "workspace_id",
        "issuer",
        "audience",
        "capability",
        "resource",
        "issued_at",
        "expires_at",
        "nonce",
        "payload_digest",
        "signature",
    }
    if (
        set(envelope["request"]) != fields
        or type(envelope["payload_base64"]) is not str
    ):
        raise DeviceMeshReceiverContractError("wire request fields are invalid")
    try:
        payload = base64.b64decode(envelope["payload_base64"], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise DeviceMeshReceiverContractError(
            "wire payload encoding is invalid"
        ) from exc
    try:
        request = AuthenticatedMeshRequestV1(**envelope["request"])
    except (TypeError, DeviceMeshContractError) as exc:
        raise DeviceMeshReceiverContractError(
            "wire request fields are invalid"
        ) from exc
    return request, payload


class DeviceMeshReceiverAsgiV1:
    """Bounded ASGI listener intended to inherit the dashboard TLS socket."""

    def __init__(
        self,
        receiver: DeviceMeshReceiverV1,
        gate: DeviceMeshReceiverFeatureGateV1,
        *,
        max_concurrency: int = MAX_CONCURRENCY,
        request_timeout_seconds: float = MAX_REQUEST_SECONDS,
    ) -> None:
        if type(receiver) is not DeviceMeshReceiverV1:
            raise DeviceMeshReceiverContractError("exact receiver is required")
        if type(gate) is not DeviceMeshReceiverFeatureGateV1 or not gate.enabled:
            raise DeviceMeshReceiverDenied("device mesh receiver is disabled")
        if type(max_concurrency) is not int or not 1 <= max_concurrency <= 64:
            raise DeviceMeshReceiverContractError("concurrency budget is invalid")
        if (
            isinstance(request_timeout_seconds, bool)
            or not isinstance(request_timeout_seconds, (int, float))
            or not 0.05 <= float(request_timeout_seconds) <= 30.0
        ):
            raise DeviceMeshReceiverContractError("request timeout is invalid")
        self.receiver = receiver
        self._max_concurrency = max_concurrency
        self._request_timeout = float(request_timeout_seconds)
        self._capacity = threading.BoundedSemaphore(max_concurrency)
        self._worker_lock = threading.Lock()
        self._active_workers = 0
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._accepting = True
        self.polling_interval = None

    @property
    def background_workers(self) -> int:
        """Report live on-demand jobs; there are no idle polling jobs."""

        return self.active_workers

    @property
    def execution_worker_capacity(self) -> int:
        return self._max_concurrency

    @property
    def active_workers(self) -> int:
        with self._worker_lock:
            return self._active_workers

    def _ensure_executor(self) -> concurrent.futures.ThreadPoolExecutor:
        with self._worker_lock:
            if self._executor is None:
                self._executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=self._max_concurrency,
                    thread_name_prefix="onyx-mesh-receiver-v1",
                )
            return self._executor

    def _job_done(self, _future: concurrent.futures.Future[object]) -> None:
        with self._worker_lock:
            self._active_workers -= 1
        self._capacity.release()

    def _submit(
        self, request: AuthenticatedMeshRequestV1, payload: bytes
    ) -> concurrent.futures.Future[ReceiverReceiptV1]:
        with self._worker_lock:
            if self._executor is None:
                self._executor = concurrent.futures.ThreadPoolExecutor(
                    max_workers=self._max_concurrency,
                    thread_name_prefix="onyx-mesh-receiver-v1",
                )
            self._active_workers += 1
            try:
                return self._executor.submit(self.receiver.process, request, payload)
            except BaseException:
                self._active_workers -= 1
                raise

    def shutdown(self) -> None:
        self._accepting = False
        with self._worker_lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=False)

    @staticmethod
    async def _response(
        send: Callable[[dict[str, object]], Awaitable[None]],
        status: int,
        payload: Mapping[str, object],
    ) -> None:
        body = _canonical(dict(payload)).encode("ascii")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def _read_body(
        self, receive: Callable[[], Awaitable[dict[str, object]]]
    ) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                raise DeviceMeshReceiverDenied("client disconnected")
            if message.get("type") != "http.request":
                raise DeviceMeshReceiverContractError("ASGI request is invalid")
            body = message.get("body", b"")
            if type(body) is not bytes:
                raise DeviceMeshReceiverContractError("ASGI body is invalid")
            total += len(body)
            if total > MAX_WIRE_BYTES or len(chunks) >= MAX_BODY_CHUNKS:
                raise DeviceMeshReceiverContractError(
                    "wire request exceeds its byte budget"
                )
            chunks.append(body)
            if not message.get("more_body", False):
                return b"".join(chunks)

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    self._accepting = True
                    self._ensure_executor()
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    self.shutdown()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
            return
        if scope.get("type") == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope.get("type") != "http":
            return
        path = str(scope.get("path", ""))
        root_path = str(scope.get("root_path", ""))
        mounted = root_path.rstrip("/").endswith("/onyx/mesh/v1")
        allowed_paths = {
            "/receive",
            "/health",
            "/capabilities",
            "/onyx/mesh/v1/receive",
            "/onyx/mesh/v1/health",
            "/onyx/mesh/v1/capabilities",
        }
        if path not in allowed_paths or (
            path in {"/receive", "/health", "/capabilities"} and not mounted
        ):
            await self._response(send, 404, {"error": "not_found"})
            return
        if not self._accepting:
            await self._response(send, 503, {"error": "receiver_stopping"})
            return
        if scope.get("scheme") != "https":
            await self._response(send, 426, {"error": "tls_required"})
            return
        if scope.get("method") != "POST" or scope.get("query_string", b"") != b"":
            await self._response(send, 405, {"error": "signed_post_required"})
            return
        if not self._capacity.acquire(blocking=False):
            await self._response(send, 429, {"error": "concurrency_limited"})
            return
        request: AuthenticatedMeshRequestV1 | None = None
        job: concurrent.futures.Future[ReceiverReceiptV1] | None = None
        deadline = asyncio.get_running_loop().time() + self._request_timeout
        try:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError
            wire = await asyncio.wait_for(self._read_body(receive), remaining)
            request, payload = decode_https_request_v1(wire)
            expected_capability = {
                "/receive": CAPABILITY_RECEIPT,
                "/health": CAPABILITY_HEALTH,
                "/capabilities": CAPABILITY_ADVERTISE,
                "/onyx/mesh/v1/receive": CAPABILITY_RECEIPT,
                "/onyx/mesh/v1/health": CAPABILITY_HEALTH,
                "/onyx/mesh/v1/capabilities": CAPABILITY_ADVERTISE,
            }[path]
            if request.capability != expected_capability:
                raise DeviceMeshReceiverDenied("path capability binding is invalid")
            job = self._submit(request, payload)
            job.add_done_callback(self._job_done)
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError
            receipt = await asyncio.wait_for(
                asyncio.shield(asyncio.wrap_future(job)), remaining
            )
            await self._response(send, receipt.http_status, receipt.response)
        except TimeoutError:
            if request is None:
                await self._response(send, 408, {"error": "request_timeout"})
            else:
                try:
                    receipt = self.receiver.store.reconcile(
                        request.request_id,
                        "request_timeout_requires_reconciliation",
                    )
                except Exception:
                    receipt = None
                if receipt is None:
                    await self._response(send, 408, {"error": "request_timeout"})
                else:
                    await self._response(send, receipt.http_status, receipt.response)
        except DeviceMeshReceiverReplay:
            await self._response(send, 409, {"error": "replay_denied"})
        except (DeviceMeshReceiverDenied, DeviceMeshDenied):
            await self._response(send, 403, {"error": "request_denied"})
        except (DeviceMeshReceiverContractError, DeviceMeshContractError):
            await self._response(send, 400, {"error": "invalid_request"})
        except Exception:
            receipt = None
            if request is not None:
                try:
                    receipt = self.receiver.store.reconcile(
                        request.request_id,
                        "receiver_failure_requires_reconciliation",
                    )
                except Exception:
                    receipt = None
            if receipt is None:
                await self._response(send, 503, {"error": "receiver_unavailable"})
            else:
                await self._response(send, receipt.http_status, receipt.response)
        finally:
            if job is None:
                self._capacity.release()


def mount_device_mesh_receiver_v1(
    app: object, adapter: DeviceMeshReceiverAsgiV1
) -> None:
    """Mount the receiver on an already-authenticated TLS dashboard app."""

    if type(adapter) is not DeviceMeshReceiverAsgiV1:
        raise DeviceMeshReceiverContractError("exact receiver adapter is required")
    mount = getattr(app, "mount", None)
    if not callable(mount):
        raise DeviceMeshReceiverContractError(
            "dashboard app cannot mount ASGI adapters"
        )
    mount("/onyx/mesh/v1", adapter, name="onyx-device-mesh-v1")


__all__ = [
    "FEATURE_FLAG",
    "CONTRACT_REQUEST",
    "CONTRACT_ACK",
    "CAPABILITY_HEALTH",
    "CAPABILITY_ADVERTISE",
    "CAPABILITY_RECEIPT",
    "RECEIVER_RESOURCE",
    "DeviceMeshReceiverError",
    "DeviceMeshReceiverContractError",
    "DeviceMeshReceiverDenied",
    "DeviceMeshReceiverReplay",
    "DeviceMeshReceiverFeatureGateV1",
    "ReceiverReceiptV1",
    "ReceiptClaimV1",
    "OutboundDispatchBindingV1",
    "DeviceMeshReceiverStoreV1",
    "DeviceMeshReceiverV1",
    "DeviceMeshReceiverAsgiV1",
    "decode_https_request_v1",
    "mount_device_mesh_receiver_v1",
]
