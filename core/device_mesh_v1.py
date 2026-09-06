"""Authenticated, authority-bound device mesh foundation for Onyx.

This module deliberately owns no socket, listener, discovery daemon or retry
worker.  Platform adapters may carry a signed request, but the request is
registered durably before transport and every receiver re-enters one central
authority callback before invoking a handler.  Secret material is referenced
from the operating-system vault and is never written to the mesh database.
"""

from __future__ import annotations

import hashlib
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
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping, Protocol

from core.native_vault import SecretReference
from core.phase6_agentic_core_v6 import normalized_sql_v6


SCHEMA_VERSION = 1
FEATURE_FLAG = "ONYX_DEVICE_MESH_V1"
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,191}")
_CAPABILITY = re.compile(r"[a-z][a-z0-9_.:-]{2,127}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_MAX_PAYLOAD_BYTES = 65_536
_MAX_TOKEN_LIFETIME_SECONDS = 300.0
_MAX_CLOCK_SKEW_SECONDS = 30.0
_MAX_PROJECTION_ROW_BYTES = 262_144
_MAX_PROJECTION_FIELD_CHARS = 131_072


class DeviceMeshError(RuntimeError):
    pass


class DeviceMeshContractError(ValueError):
    pass


class DeviceMeshDenied(PermissionError):
    pass


class DeviceMeshReplay(DeviceMeshDenied):
    pass


class DeviceMeshTransport(Protocol):
    def send(self, request: "AuthenticatedMeshRequestV1", payload: bytes) -> str: ...


class _DigestWriter(Protocol):
    def update(self, data: bytes) -> object: ...


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise DeviceMeshContractError(f"{label} is invalid")
    return value


def _capability(value: object) -> str:
    if type(value) is not str or _CAPABILITY.fullmatch(value) is None:
        raise DeviceMeshContractError("capability is invalid")
    return value


def _finite_time(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise DeviceMeshContractError(f"{label} is invalid")
    return float(value)


def _payload(value: bytes | bytearray) -> bytes:
    if not isinstance(value, (bytes, bytearray)):
        raise DeviceMeshContractError("payload must be bytes")
    raw = bytes(value)
    if len(raw) > _MAX_PAYLOAD_BYTES:
        raise DeviceMeshContractError("payload exceeds its byte budget")
    return raw


def _canonical_json(value: object) -> str:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise DeviceMeshContractError("value is not canonical JSON") from exc
    if len(encoded.encode("utf-8")) > 32_768:
        raise DeviceMeshContractError("value exceeds its byte budget")
    return encoded


def _projection_row_json(row: sqlite3.Row) -> bytes:
    values = list(row)
    if any(
        isinstance(value, str) and len(value) > _MAX_PROJECTION_FIELD_CHARS
        for value in values
    ):
        raise DeviceMeshError("device-mesh projection row exceeds its storage budget")
    encoded = json.dumps(
        values, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > _MAX_PROJECTION_ROW_BYTES:
        raise DeviceMeshError("device-mesh projection row exceeds its storage budget")
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
        raise DeviceMeshContractError("an explicit absolute database path is required")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise DeviceMeshDenied("linked mesh directory is forbidden")
    attributes = getattr(path.parent.stat(), "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if attributes & reparse:
        raise DeviceMeshDenied("reparse-point mesh directory is forbidden")
    if path.exists() and path.is_symlink():
        raise DeviceMeshDenied("linked mesh database is forbidden")


def _secret(
    reference: SecretReference, reader: Callable[[SecretReference], bytes | None]
) -> bytes:
    if type(reference) is not SecretReference:
        raise DeviceMeshContractError("exact SecretReference is required")
    value = reader(reference)
    if not isinstance(value, bytes) or not 32 <= len(value) <= 256:
        raise DeviceMeshDenied("device credential is unavailable")
    return value


@dataclass(frozen=True)
class DeviceMeshFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise DeviceMeshContractError("enabled must be an exact boolean")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "DeviceMeshFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True)
class EnrolledDeviceV1:
    device_id: str
    owner_profile_id: str
    workspace_id: str
    issuer: str
    secret_reference: SecretReference
    enabled: bool


@dataclass(frozen=True)
class AuthenticatedMeshRequestV1:
    request_id: str
    source_device_id: str
    target_device_id: str
    owner_profile_id: str
    workspace_id: str
    issuer: str
    audience: str
    capability: str
    resource: str
    issued_at: float
    expires_at: float
    nonce: str
    payload_digest: str
    signature: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.request_id, "request_id"),
            (self.source_device_id, "source_device_id"),
            (self.target_device_id, "target_device_id"),
            (self.owner_profile_id, "owner_profile_id"),
            (self.workspace_id, "workspace_id"),
            (self.issuer, "issuer"),
            (self.audience, "audience"),
            (self.resource, "resource"),
            (self.nonce, "nonce"),
        ):
            _identifier(value, label)
        _capability(self.capability)
        _finite_time(self.issued_at, "issued_at")
        _finite_time(self.expires_at, "expires_at")
        if self.expires_at <= self.issued_at:
            raise DeviceMeshContractError("request expiry is invalid")
        if _DIGEST.fullmatch(self.payload_digest) is None:
            raise DeviceMeshContractError("payload_digest is invalid")
        if _DIGEST.fullmatch(self.signature) is None:
            raise DeviceMeshContractError("signature is invalid")

    def unsigned_claims(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "source_device_id": self.source_device_id,
            "target_device_id": self.target_device_id,
            "owner_profile_id": self.owner_profile_id,
            "workspace_id": self.workspace_id,
            "issuer": self.issuer,
            "audience": self.audience,
            "capability": self.capability,
            "resource": self.resource,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
            "payload_digest": self.payload_digest,
        }


@dataclass(frozen=True)
class MeshDispatchV1:
    request_id: str
    direction: str
    status: str
    detail: str
    payload_digest: str


class DeviceMeshRegistryV1:
    """Authenticated registry and append-only audit projection."""

    _LEGACY_DDL = (
        """CREATE TABLE metadata(
          schema_version INTEGER NOT NULL CHECK(schema_version=1)
        )""",
        """CREATE TABLE devices(
          device_id TEXT PRIMARY KEY,
          owner_profile_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL,
          issuer TEXT NOT NULL UNIQUE,
          vault_service TEXT NOT NULL,
          vault_account TEXT NOT NULL,
          vault_label TEXT NOT NULL,
          enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL
        )""",
        """CREATE TABLE mesh_requests(
          request_id TEXT PRIMARY KEY,
          direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
          source_device_id TEXT NOT NULL,
          target_device_id TEXT NOT NULL,
          owner_profile_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL,
          capability TEXT NOT NULL,
          resource TEXT NOT NULL,
          nonce TEXT NOT NULL,
          payload_digest TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN
            ('reserved','sending','accepted','succeeded','denied','failed','reconciliation')),
          detail TEXT NOT NULL,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          UNIQUE(source_device_id,nonce)
        )""",
        """CREATE TABLE mesh_events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          entity_id TEXT NOT NULL,
          timestamp REAL NOT NULL,
          event TEXT NOT NULL,
          detail_json TEXT NOT NULL,
          prev_hash TEXT NOT NULL,
          event_hash TEXT NOT NULL UNIQUE
        )""",
        """CREATE INDEX idx_mesh_devices_scope
          ON devices(owner_profile_id,workspace_id,enabled)""",
        """CREATE INDEX idx_mesh_requests_status
          ON mesh_requests(direction,status,updated_at)""",
        """CREATE TRIGGER mesh_events_no_update BEFORE UPDATE ON mesh_events
          BEGIN SELECT RAISE(ABORT,'mesh events are immutable'); END""",
        """CREATE TRIGGER mesh_events_no_delete BEFORE DELETE ON mesh_events
          BEGIN SELECT RAISE(ABORT,'mesh events are immutable'); END""",
    )
    _LEDGER_DDL = (
        """CREATE TABLE mesh_ledger_head(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1),
          event_count INTEGER NOT NULL CHECK(event_count>=0),
          tail_seq INTEGER NOT NULL CHECK(tail_seq>=0),
          tail_hash TEXT NOT NULL CHECK(length(tail_hash)=64 AND tail_hash NOT GLOB '*[^0-9a-f]*'),
          projection_digest TEXT NOT NULL CHECK(length(projection_digest)=64 AND projection_digest NOT GLOB '*[^0-9a-f]*'),
          anchor_hash TEXT NOT NULL CHECK(length(anchor_hash)=64 AND anchor_hash NOT GLOB '*[^0-9a-f]*')
        )""",
        """CREATE TRIGGER mesh_ledger_head_update_guard
          BEFORE UPDATE ON mesh_ledger_head
          WHEN NOT (
            OLD.singleton=1 AND NEW.singleton=1 AND
            NEW.event_count=OLD.event_count+1 AND
            NEW.tail_seq=OLD.tail_seq+1 AND
            NEW.event_count=(SELECT COUNT(*) FROM mesh_events) AND
            NEW.tail_seq=COALESCE((SELECT MAX(seq) FROM mesh_events),0) AND
            NEW.tail_hash=COALESCE((SELECT event_hash FROM mesh_events ORDER BY seq DESC LIMIT 1),printf('%064d',0))
          )
          BEGIN SELECT RAISE(ABORT,'mesh ledger head transition is invalid'); END""",
        """CREATE TRIGGER mesh_ledger_head_no_delete BEFORE DELETE ON mesh_ledger_head
          BEGIN SELECT RAISE(ABORT,'mesh ledger head is immutable'); END""",
        """CREATE TRIGGER mesh_ledger_head_no_insert BEFORE INSERT ON mesh_ledger_head
          WHEN (SELECT COUNT(*) FROM mesh_ledger_head)>0
          BEGIN SELECT RAISE(ABORT,'mesh ledger head already exists'); END""",
    )
    _DDL = _LEGACY_DDL + _LEDGER_DDL

    def __init__(
        self,
        path: Path | str,
        gate: DeviceMeshFeatureGateV1,
        *,
        ledger_auth_key: bytes | bytearray | None = None,
        trust_legacy_ledger: bool = False,
    ) -> None:
        if type(gate) is not DeviceMeshFeatureGateV1 or not gate.enabled:
            raise DeviceMeshDenied("device mesh is disabled")
        if (
            not isinstance(ledger_auth_key, (bytes, bytearray))
            or len(ledger_auth_key) != 32
        ):
            raise DeviceMeshDenied(
                "device-mesh ledger authentication key is unavailable"
            )
        if type(trust_legacy_ledger) is not bool:
            raise DeviceMeshContractError(
                "legacy ledger trust must be an exact boolean"
            )
        self.path = Path(path)
        _private_path(self.path)
        self._ledger_auth_key = bytes(ledger_auth_key)
        self._trust_legacy_ledger = trust_legacy_ledger
        self._lock = threading.RLock()
        self._expected_signature = self._build_expected_signature()
        self._legacy_signature = self._build_signature(self._LEGACY_DDL)
        self.initialize()

    @staticmethod
    def _signature(connection: sqlite3.Connection) -> str:
        objects = []
        for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ):
            if row[3] is None:
                raise DeviceMeshError("schema object has no stored SQL")
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
            _canonical_json({"objects": objects, "details": details}).encode()
        ).hexdigest()

    @classmethod
    def _build_signature(cls, ddl: tuple[str, ...]) -> str:
        connection = sqlite3.connect(":memory:")
        try:
            for statement in ddl:
                connection.execute(statement)
            connection.execute("INSERT INTO metadata(schema_version) VALUES(1)")
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
        # This is byte-for-byte the prior canonical JSON shape, but rows are
        # hashed incrementally so ledger lifetime is not coupled to wire limits.
        digest = hashlib.sha256()
        digest.update(b'{"devices":')
        _update_projection_rows(
            digest, connection, "SELECT * FROM devices ORDER BY device_id"
        )
        digest.update(b',"mesh_requests":')
        _update_projection_rows(
            digest,
            connection,
            "SELECT * FROM mesh_requests ORDER BY request_id",
        )
        digest.update(b',"metadata":')
        _update_projection_rows(
            digest,
            connection,
            "SELECT schema_version FROM metadata ORDER BY schema_version",
        )
        digest.update(b"}")
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
            _canonical_json(
                {
                    "event_count": event_count,
                    "tail_seq": tail_seq,
                    "tail_hash": tail_hash,
                    "projection_digest": projection_digest,
                }
            ).encode(),
            hashlib.sha256,
        ).hexdigest()

    def _initialize_ledger_head(self, connection: sqlite3.Connection) -> None:
        row = connection.execute(
            "SELECT COUNT(*),COALESCE(MAX(seq),0) FROM mesh_events"
        ).fetchone()
        event_count, tail_seq = int(row[0]), int(row[1])
        tail = connection.execute(
            "SELECT event_hash FROM mesh_events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        tail_hash = "0" * 64 if tail is None else str(tail[0])
        projection_digest = self._projection_digest(connection)
        connection.execute(
            "INSERT INTO mesh_ledger_head VALUES(1,?,?,?,?,?)",
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
        previous_hash = "0" * 64
        expected_sequence = 1
        for row in connection.execute(
            "SELECT seq,entity_id,timestamp,event,detail_json,prev_hash,event_hash "
            "FROM mesh_events ORDER BY seq"
        ):
            sequence = int(row[0])
            entity_id = str(row[1])
            timestamp = float(row[2])
            event = str(row[3])
            detail_json = str(row[4])
            prev_hash = str(row[5])
            event_hash = str(row[6])
            try:
                detail = json.loads(detail_json)
            except json.JSONDecodeError as exc:
                raise DeviceMeshError("device-mesh event chain is invalid") from exc
            if (
                sequence != expected_sequence
                or not entity_id
                or not event
                or not math.isfinite(timestamp)
                or timestamp <= 0
                or type(detail) is not dict
                or _canonical_json(detail) != detail_json
                or prev_hash != previous_hash
            ):
                raise DeviceMeshError("device-mesh event chain is invalid")
            expected_hash = hashlib.sha256(
                _canonical_json(
                    {
                        "entity_id": entity_id,
                        "timestamp": timestamp,
                        "event": event,
                        "detail_json": detail_json,
                        "prev_hash": previous_hash,
                    }
                ).encode()
            ).hexdigest()
            if not hmac.compare_digest(expected_hash, event_hash):
                raise DeviceMeshError("device-mesh event chain is invalid")
            previous_hash = event_hash
            expected_sequence += 1
        return expected_sequence - 1, expected_sequence - 1, previous_hash

    def _validate_ledger_head(self, connection: sqlite3.Connection) -> None:
        event_count, tail_seq, tail_hash = self._validate_event_chain(connection)
        rows = connection.execute("SELECT * FROM mesh_ledger_head").fetchall()
        if len(rows) != 1:
            raise DeviceMeshError("device-mesh ledger anchor is invalid")
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
            raise DeviceMeshError("device-mesh ledger anchor is invalid")

    def _advance_ledger_head(
        self, connection: sqlite3.Connection, sequence: int, tail_hash: str
    ) -> None:
        row = connection.execute("SELECT * FROM mesh_ledger_head").fetchone()
        if row is None:
            raise DeviceMeshError("device-mesh ledger anchor is unavailable")
        event_count = int(row["event_count"]) + 1
        projection_digest = self._projection_digest(connection)
        anchor_hash = self._anchor_hash(
            event_count, sequence, tail_hash, projection_digest
        )
        changed = connection.execute(
            "UPDATE mesh_ledger_head SET event_count=?,tail_seq=?,tail_hash=?,"
            "projection_digest=?,anchor_hash=? WHERE singleton=1",
            (event_count, sequence, tail_hash, projection_digest, anchor_hash),
        ).rowcount
        if changed != 1:
            raise DeviceMeshError("device-mesh ledger anchor update failed")

    def initialize(self) -> None:
        with self._lock:
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
                    connection.execute("INSERT INTO metadata(schema_version) VALUES(1)")
                    connection.execute("PRAGMA user_version=1")
                    self._initialize_ledger_head(connection)
                    connection.execute("COMMIT")
                elif (
                    version == 1
                    and self._signature(connection) == self._legacy_signature
                ):
                    if not self._trust_legacy_ledger:
                        raise DeviceMeshDenied(
                            "legacy device-mesh ledger requires explicit trusted initialization"
                        )
                    connection.execute("BEGIN IMMEDIATE")
                    if (
                        connection.execute("PRAGMA integrity_check").fetchone()[0]
                        != "ok"
                    ):
                        raise DeviceMeshError(
                            "device-mesh schema authentication failed"
                        )
                    self._validate_event_chain(connection)
                    for statement in self._LEDGER_DDL:
                        connection.execute(statement)
                    self._initialize_ledger_head(connection)
                    connection.execute("COMMIT")
                connection.execute("BEGIN IMMEDIATE")
                if (
                    int(connection.execute("PRAGMA user_version").fetchone()[0]) != 1
                    or [
                        tuple(row)
                        for row in connection.execute(
                            "SELECT schema_version FROM metadata"
                        )
                    ]
                    != [(1,)]
                    or self._signature(connection) != self._expected_signature
                    or connection.execute("PRAGMA integrity_check").fetchone()[0]
                    != "ok"
                ):
                    raise DeviceMeshError("device-mesh schema authentication failed")
                self._validate_ledger_head(connection)
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def _event(
        self,
        connection: sqlite3.Connection,
        entity_id: str,
        event: str,
        detail: Mapping[str, object],
    ) -> None:
        previous = connection.execute(
            "SELECT event_hash FROM mesh_events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev_hash = "0" * 64 if previous is None else str(previous[0])
        timestamp = time.time()
        detail_json = _canonical_json(dict(detail))
        event_hash = hashlib.sha256(
            _canonical_json(
                {
                    "entity_id": entity_id,
                    "timestamp": timestamp,
                    "event": event,
                    "detail_json": detail_json,
                    "prev_hash": prev_hash,
                }
            ).encode()
        ).hexdigest()
        cursor = connection.execute(
            "INSERT INTO mesh_events(entity_id,timestamp,event,detail_json,prev_hash,event_hash) "
            "VALUES(?,?,?,?,?,?)",
            (entity_id, timestamp, event, detail_json, prev_hash, event_hash),
        )
        sequence = int(cursor.lastrowid or 0)
        if sequence <= 0:
            raise DeviceMeshError("device-mesh event sequence is invalid")
        self._advance_ledger_head(connection, sequence, event_hash)

    def enroll(self, device: EnrolledDeviceV1) -> None:
        if type(device) is not EnrolledDeviceV1:
            raise DeviceMeshContractError("exact EnrolledDeviceV1 is required")
        _identifier(device.device_id, "device_id")
        _identifier(device.owner_profile_id, "owner_profile_id")
        _identifier(device.workspace_id, "workspace_id")
        _identifier(device.issuer, "issuer")
        if type(device.secret_reference) is not SecretReference:
            raise DeviceMeshContractError("exact SecretReference is required")
        if type(device.enabled) is not bool:
            raise DeviceMeshContractError("enabled must be an exact boolean")
        now = time.time()
        with self._verified_transaction() as connection:
            connection.execute(
                "INSERT INTO devices VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    device.device_id,
                    device.owner_profile_id,
                    device.workspace_id,
                    device.issuer,
                    device.secret_reference.service,
                    device.secret_reference.account,
                    device.secret_reference.label,
                    int(device.enabled),
                    now,
                    now,
                ),
            )
            self._event(
                connection,
                device.device_id,
                "device.enrolled",
                {"enabled": device.enabled},
            )

    def device(self, device_id: str) -> EnrolledDeviceV1:
        key = _identifier(device_id, "device_id")
        with self._verified_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM devices WHERE device_id=?", (key,)
            ).fetchone()
        if row is None:
            raise DeviceMeshDenied("device is not enrolled")
        return EnrolledDeviceV1(
            str(row["device_id"]),
            str(row["owner_profile_id"]),
            str(row["workspace_id"]),
            str(row["issuer"]),
            SecretReference(
                str(row["vault_service"]),
                str(row["vault_account"]),
                str(row["vault_label"]),
            ),
            bool(row["enabled"]),
        )

    def count_scope(self, owner_profile_id: str, workspace_id: str) -> int:
        """Return a scope-bound device count without exposing vault references."""

        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        with self._verified_transaction() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM devices "
                "WHERE owner_profile_id=? AND workspace_id=?",
                (owner, workspace),
            ).fetchone()
        return int(row[0])

    def set_enabled(self, device_id: str, enabled: bool) -> EnrolledDeviceV1:
        key = _identifier(device_id, "device_id")
        if type(enabled) is not bool:
            raise DeviceMeshContractError("enabled must be an exact boolean")
        with self._verified_transaction() as connection:
            changed = connection.execute(
                "UPDATE devices SET enabled=?,updated_at=? WHERE device_id=?",
                (int(enabled), time.time(), key),
            ).rowcount
            if changed != 1:
                raise DeviceMeshDenied("device is not enrolled")
            self._event(
                connection,
                key,
                "device.enabled" if enabled else "device.disabled",
                {"enabled": enabled},
            )
        return self.device(key)

    def reserve(
        self, request: AuthenticatedMeshRequestV1, direction: str
    ) -> MeshDispatchV1:
        if type(request) is not AuthenticatedMeshRequestV1:
            raise DeviceMeshContractError(
                "exact AuthenticatedMeshRequestV1 is required"
            )
        if direction not in {"inbound", "outbound"}:
            raise DeviceMeshContractError("direction is invalid")
        now = time.time()
        try:
            with self._verified_transaction() as connection:
                connection.execute(
                    "INSERT INTO mesh_requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        request.request_id,
                        direction,
                        request.source_device_id,
                        request.target_device_id,
                        request.owner_profile_id,
                        request.workspace_id,
                        request.capability,
                        request.resource,
                        request.nonce,
                        request.payload_digest,
                        "reserved",
                        "registered_before_side_effect",
                        now,
                        now,
                    ),
                )
                self._event(
                    connection, request.request_id, f"mesh.{direction}.reserved", {}
                )
        except sqlite3.IntegrityError as exc:
            raise DeviceMeshReplay("request or nonce was already observed") from exc
        return MeshDispatchV1(
            request.request_id,
            direction,
            "reserved",
            "registered_before_side_effect",
            request.payload_digest,
        )

    def finish(self, request_id: str, status: str, detail: str) -> MeshDispatchV1:
        key = _identifier(request_id, "request_id")
        if status not in {
            "sending",
            "accepted",
            "succeeded",
            "denied",
            "failed",
            "reconciliation",
        }:
            raise DeviceMeshContractError("status is invalid")
        if type(detail) is not str or not detail or len(detail) > 191:
            raise DeviceMeshContractError("detail is invalid")
        with self._verified_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM mesh_requests WHERE request_id=?", (key,)
            ).fetchone()
            if row is None:
                raise DeviceMeshError("mesh request is unknown")
            connection.execute(
                "UPDATE mesh_requests SET status=?,detail=?,updated_at=? WHERE request_id=?",
                (status, detail, time.time(), key),
            )
            self._event(connection, key, f"mesh.request.{status}", {"detail": detail})
            return MeshDispatchV1(
                key, str(row["direction"]), status, detail, str(row["payload_digest"])
            )

    def recover_uncertain(self) -> int:
        with self._verified_transaction() as connection:
            rows = connection.execute(
                "SELECT request_id FROM mesh_requests WHERE direction='outbound' "
                "AND status IN ('reserved','sending')"
            ).fetchall()
            for row in rows:
                key = str(row[0])
                connection.execute(
                    "UPDATE mesh_requests SET status='reconciliation',detail=?,updated_at=? "
                    "WHERE request_id=?",
                    ("restart_requires_reconciliation", time.time(), key),
                )
                self._event(
                    connection,
                    key,
                    "mesh.request.reconciliation",
                    {"detail": "restart_requires_reconciliation"},
                )
            return len(rows)

    def dispatch(self, request_id: str) -> MeshDispatchV1:
        key = _identifier(request_id, "request_id")
        with self._verified_transaction() as connection:
            row = connection.execute(
                "SELECT * FROM mesh_requests WHERE request_id=?", (key,)
            ).fetchone()
        if row is None:
            raise DeviceMeshError("mesh request is unknown")
        return MeshDispatchV1(
            key,
            str(row["direction"]),
            str(row["status"]),
            str(row["detail"]),
            str(row["payload_digest"]),
        )


def _signature(request: AuthenticatedMeshRequestV1, secret: bytes) -> str:
    return hmac.new(
        secret, _canonical_json(request.unsigned_claims()).encode(), hashlib.sha256
    ).hexdigest()


class AuthenticatedDeviceMeshV1:
    """Explicit-send/explicit-receive runtime with zero idle work."""

    def __init__(
        self,
        *,
        local_device_id: str,
        registry: DeviceMeshRegistryV1,
        vault_reader: Callable[[SecretReference], bytes | None],
        authority: Callable[[str, str, str, str, str], bool],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.local_device_id = _identifier(local_device_id, "local_device_id")
        if type(registry) is not DeviceMeshRegistryV1:
            raise DeviceMeshContractError("exact DeviceMeshRegistryV1 is required")
        if not callable(vault_reader) or not callable(authority) or not callable(clock):
            raise DeviceMeshContractError("mesh dependencies must be callable")
        self._registry = registry
        self._vault_reader = vault_reader
        self._authority = authority
        self._clock = clock
        self.background_workers = 0
        self.polling_interval = None

    def issue(
        self,
        *,
        target_device_id: str,
        capability: str,
        resource: str,
        payload: bytes | bytearray,
        ttl_seconds: float = 60.0,
    ) -> tuple[AuthenticatedMeshRequestV1, bytes]:
        source = self._registry.device(self.local_device_id)
        target = self._registry.device(target_device_id)
        if not source.enabled or not target.enabled:
            raise DeviceMeshDenied("device is disabled")
        if (source.owner_profile_id, source.workspace_id) != (
            target.owner_profile_id,
            target.workspace_id,
        ):
            raise DeviceMeshDenied("device scope does not match")
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, (int, float))
            or not 1 <= ttl_seconds <= _MAX_TOKEN_LIFETIME_SECONDS
        ):
            raise DeviceMeshContractError("ttl_seconds is invalid")
        raw = _payload(payload)
        now = _finite_time(self._clock(), "clock")
        unsigned = AuthenticatedMeshRequestV1(
            "req_" + uuid.uuid4().hex,
            source.device_id,
            target.device_id,
            source.owner_profile_id,
            source.workspace_id,
            source.issuer,
            target.issuer,
            _capability(capability),
            _identifier(resource, "resource"),
            now,
            now + float(ttl_seconds),
            "nonce_" + uuid.uuid4().hex,
            hashlib.sha256(raw).hexdigest(),
            "0" * 64,
        )
        signed = AuthenticatedMeshRequestV1(
            **{
                **unsigned.__dict__,
                "signature": _signature(
                    unsigned, _secret(source.secret_reference, self._vault_reader)
                ),
            }
        )
        return signed, raw

    def send(
        self,
        request: AuthenticatedMeshRequestV1,
        payload: bytes | bytearray,
        transport: DeviceMeshTransport,
    ) -> MeshDispatchV1:
        raw = _payload(payload)
        if hashlib.sha256(raw).hexdigest() != request.payload_digest:
            raise DeviceMeshDenied("payload digest does not match")
        if request.source_device_id != self.local_device_id:
            raise DeviceMeshDenied("request source is not local")
        self._registry.reserve(request, "outbound")
        self._registry.finish(
            request.request_id, "sending", "transport_invoked_after_reservation"
        )
        try:
            acknowledgement = transport.send(request, raw)
            if (
                type(acknowledgement) is not str
                or not acknowledgement
                or len(acknowledgement) > 191
            ):
                raise DeviceMeshError("transport acknowledgement is invalid")
            return self._registry.finish(
                request.request_id, "accepted", "authenticated_transport_acknowledged"
            )
        except BaseException:
            self._registry.finish(
                request.request_id, "reconciliation", "transport_outcome_unknown"
            )
            raise

    def authenticate(
        self,
        request: AuthenticatedMeshRequestV1,
        payload: bytes | bytearray,
    ) -> bytes:
        """Authenticate one inbound envelope without granting or executing it.

        Listener adapters use this narrow seam to persist their own durable
        intent before consulting the central authority.  Authentication is not
        authority and this method deliberately has no handler callback.
        """

        if type(request) is not AuthenticatedMeshRequestV1:
            raise DeviceMeshContractError(
                "exact AuthenticatedMeshRequestV1 is required"
            )
        raw = _payload(payload)
        now = _finite_time(self._clock(), "clock")
        source = self._registry.device(request.source_device_id)
        target = self._registry.device(request.target_device_id)
        if (
            request.target_device_id != self.local_device_id
            or target.device_id != self.local_device_id
        ):
            raise DeviceMeshDenied("request audience device does not match")
        if not source.enabled or not target.enabled:
            raise DeviceMeshDenied("device is disabled")
        if request.issuer != source.issuer or request.audience != target.issuer:
            raise DeviceMeshDenied("request issuer or audience does not match")
        if (
            request.owner_profile_id != source.owner_profile_id
            or request.workspace_id != source.workspace_id
            or (target.owner_profile_id, target.workspace_id)
            != (source.owner_profile_id, source.workspace_id)
        ):
            raise DeviceMeshDenied("request scope does not match")
        if (
            request.issued_at > now + _MAX_CLOCK_SKEW_SECONDS
            or request.expires_at < now
        ):
            raise DeviceMeshDenied("request is outside its validity window")
        if request.expires_at - request.issued_at > _MAX_TOKEN_LIFETIME_SECONDS:
            raise DeviceMeshDenied("request lifetime exceeds the boundary")
        if hashlib.sha256(raw).hexdigest() != request.payload_digest:
            raise DeviceMeshDenied("payload digest does not match")
        expected = _signature(
            request,
            _secret(source.secret_reference, self._vault_reader),
        )
        if not hmac.compare_digest(expected, request.signature):
            raise DeviceMeshDenied("request authentication failed")
        return raw

    def receive(
        self,
        request: AuthenticatedMeshRequestV1,
        payload: bytes | bytearray,
        handler: Callable[[AuthenticatedMeshRequestV1, bytes], object],
    ) -> MeshDispatchV1:
        raw = self.authenticate(request, payload)
        self._registry.reserve(request, "inbound")
        try:
            allowed = self._authority(
                request.owner_profile_id,
                request.workspace_id,
                request.capability,
                request.resource,
                request.source_device_id,
            )
            if type(allowed) is not bool or not allowed:
                return self._registry.finish(
                    request.request_id, "denied", "central_authority_denied"
                )
            if not callable(handler):
                raise DeviceMeshContractError("handler must be callable")
            self._registry.finish(
                request.request_id, "accepted", "central_authority_accepted"
            )
            handler(request, raw)
            return self._registry.finish(
                request.request_id, "succeeded", "handler_completed"
            )
        except DeviceMeshContractError:
            self._registry.finish(
                request.request_id, "failed", "handler_contract_failed"
            )
            raise
        except BaseException:
            self._registry.finish(request.request_id, "failed", "handler_failed")
            raise
