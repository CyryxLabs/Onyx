"""Owner-present, one-time pairing ceremony for the existing Onyx device mesh.

The ceremony proves possession of a short-lived code before a device may be
enrolled.  It deliberately owns no listener, discovery, transport, credential
or background worker.  Codes are returned once, stored only as salted hashes
and never form part of a URL.  A successful claim is still not authority to run
anything: enrollment and every later request remain inside ``device_mesh_v1``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import sqlite3
import stat
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final


FEATURE_FLAG: Final = "ONYX_DEVICE_PAIRING_V1"
MAX_LIFETIME_SECONDS: Final = 300.0
MAX_ATTEMPTS: Final = 5
CODE_ALPHABET: Final = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
CODE_LENGTH: Final = 8
_ZERO_HASH: Final = "0" * 64


class DevicePairingError(RuntimeError):
    pass


class DevicePairingContractError(ValueError):
    pass


class DevicePairingDenied(PermissionError):
    pass


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or not 3 <= len(value) <= 192:
        raise DevicePairingContractError(f"{label} is invalid")
    if not value[0].isalpha() or any(not (c.isalnum() or c in "_.:-") for c in value):
        raise DevicePairingContractError(f"{label} is invalid")
    return value


def _now(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DevicePairingContractError("clock is invalid")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise DevicePairingContractError("clock is invalid")
    return result


def _private_path(path: Path) -> None:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise DevicePairingContractError("an absolute database path is required")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or (path.exists() and path.is_symlink()):
        raise DevicePairingDenied("linked pairing storage is forbidden")
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if getattr(path.parent.stat(), "st_file_attributes", 0) & reparse:
        raise DevicePairingDenied("reparse-point pairing storage is forbidden")


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _normalize_code(value: object) -> str:
    if type(value) is not str:
        raise DevicePairingDenied("pairing code is invalid")
    code = value.replace("-", "").replace(" ", "").upper()
    if len(code) != CODE_LENGTH or any(c not in CODE_ALPHABET for c in code):
        raise DevicePairingDenied("pairing code is invalid")
    return code


@dataclass(frozen=True, slots=True)
class PairingChallengeV1:
    pairing_id: str
    owner_profile_id: str
    workspace_id: str
    device_id: str
    issuer: str
    display_code: str
    expires_at: float
    transport_hint: str = "enter_code_on_trusted_local_pairing_surface"
    background_workers: int = 0
    polling_interval: None = None


@dataclass(frozen=True, slots=True)
class PairingClaimV1:
    pairing_id: str
    owner_profile_id: str
    workspace_id: str
    device_id: str
    issuer: str
    status: str
    claimed_at: float
    code_exposed: bool = False
    credential_issued: bool = False


@dataclass(frozen=True, slots=True)
class PairingStatusV1:
    pairing_id: str
    device_id: str
    status: str
    attempts: int
    expires_at: float
    code_exposed: bool = False
    credential_issued: bool = False


class DevicePairingStoreV1:
    """Durable, hash-audited pairing state with zero idle work."""

    _DDL = (
        """CREATE TABLE pairing_sessions(
          pairing_id TEXT PRIMARY KEY, owner_profile_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL, device_id TEXT NOT NULL, issuer TEXT NOT NULL,
          salt BLOB NOT NULL, code_digest TEXT NOT NULL, expires_at REAL NOT NULL,
          attempts INTEGER NOT NULL CHECK(attempts BETWEEN 0 AND 5),
          status TEXT NOT NULL CHECK(status IN ('pending','claimed','expired','cancelled')),
          created_at REAL NOT NULL, updated_at REAL NOT NULL
        )""",
        """CREATE UNIQUE INDEX idx_pairing_pending_device
          ON pairing_sessions(owner_profile_id,workspace_id,device_id)
          WHERE status='pending'""",
        """CREATE TABLE pairing_events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT, pairing_id TEXT NOT NULL,
          occurred_at REAL NOT NULL, event TEXT NOT NULL, detail_json TEXT NOT NULL,
          prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE
        )""",
        """CREATE TRIGGER pairing_events_no_update BEFORE UPDATE ON pairing_events
          BEGIN SELECT RAISE(ABORT,'pairing events are immutable'); END""",
        """CREATE TRIGGER pairing_events_no_delete BEFORE DELETE ON pairing_events
          BEGIN SELECT RAISE(ABORT,'pairing events are immutable'); END""",
    )

    def __init__(
        self,
        path: Path | str,
        *,
        enabled: bool,
        clock: Callable[[], float] = time.time,
        code_factory: Callable[[], str] | None = None,
        salt_factory: Callable[[int], bytes] = secrets.token_bytes,
    ) -> None:
        if type(enabled) is not bool or not enabled:
            raise DevicePairingDenied("device pairing is disabled")
        if not callable(clock) or not callable(salt_factory):
            raise DevicePairingContractError("pairing dependencies are invalid")
        self.path = Path(path)
        _private_path(self.path)
        self._clock = clock
        self._code_factory = code_factory or self._random_code
        self._salt_factory = salt_factory
        self._lock = threading.RLock()
        self.background_workers = 0
        self.polling_interval = None
        self._initialize()

    @staticmethod
    def _random_code() -> str:
        return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))

    def _connect(self) -> sqlite3.Connection:
        _private_path(self.path)
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
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
                raise DevicePairingError("pairing schema version is invalid")
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise DevicePairingError("pairing storage integrity failed")

    @staticmethod
    def _digest(salt: bytes, code: str) -> str:
        return hashlib.sha256(salt + code.encode("ascii")).hexdigest()

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        pairing_id: str,
        event: str,
        detail: dict[str, object],
        occurred_at: float,
    ) -> None:
        previous = connection.execute(
            "SELECT event_hash FROM pairing_events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev_hash = _ZERO_HASH if previous is None else str(previous[0])
        detail_json = _canonical(detail)
        event_hash = hashlib.sha256(_canonical({
            "pairing_id": pairing_id,
            "occurred_at": occurred_at,
            "event": event,
            "detail_json": detail_json,
            "prev_hash": prev_hash,
        }).encode("utf-8")).hexdigest()
        connection.execute(
            "INSERT INTO pairing_events(pairing_id,occurred_at,event,detail_json,prev_hash,event_hash) VALUES(?,?,?,?,?,?)",
            (pairing_id, occurred_at, event, detail_json, prev_hash, event_hash),
        )

    def initiate(
        self,
        *,
        owner_profile_id: str,
        workspace_id: str,
        device_id: str,
        issuer: str,
        ttl_seconds: float = 180.0,
    ) -> PairingChallengeV1:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        device = _identifier(device_id, "device_id")
        issuer_value = _identifier(issuer, "issuer")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)):
            raise DevicePairingContractError("ttl_seconds is invalid")
        ttl = float(ttl_seconds)
        if not 30.0 <= ttl <= MAX_LIFETIME_SECONDS:
            raise DevicePairingContractError("ttl_seconds is invalid")
        code = _normalize_code(self._code_factory())
        salt = self._salt_factory(32)
        if type(salt) is not bytes or len(salt) != 32:
            raise DevicePairingContractError("pairing salt is invalid")
        now = _now(self._clock())
        pairing_id = "pair_" + uuid.uuid4().hex
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE pairing_sessions SET status='expired',updated_at=? WHERE status='pending' AND expires_at<=?",
                (now, now),
            )
            try:
                connection.execute(
                    "INSERT INTO pairing_sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pairing_id, owner, workspace, device, issuer_value, salt,
                     self._digest(salt, code), now + ttl, 0, "pending", now, now),
                )
            except sqlite3.IntegrityError as exc:
                connection.execute("ROLLBACK")
                raise DevicePairingDenied("a pending pairing already exists for this device") from exc
            self._event(connection, pairing_id, "pairing.initiated", {
                "owner_profile_id": owner, "workspace_id": workspace,
                "device_id": device, "issuer": issuer_value, "expires_at": now + ttl,
                "code_persisted": False, "credential_issued": False,
            }, now)
            connection.execute("COMMIT")
        grouped = f"{code[:4]}-{code[4:]}"
        return PairingChallengeV1(pairing_id, owner, workspace, device, issuer_value, grouped, now + ttl)

    def claim(self, *, pairing_id: str, display_code: str) -> PairingClaimV1:
        key = _identifier(pairing_id, "pairing_id")
        code = _normalize_code(display_code)
        now = _now(self._clock())
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM pairing_sessions WHERE pairing_id=?", (key,)
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise DevicePairingDenied("pairing session is unavailable")
            if str(row["status"]) != "pending":
                connection.execute("ROLLBACK")
                raise DevicePairingDenied("pairing session is not pending")
            if float(row["expires_at"]) <= now:
                connection.execute(
                    "UPDATE pairing_sessions SET status='expired',updated_at=? WHERE pairing_id=?",
                    (now, key),
                )
                self._event(connection, key, "pairing.expired", {}, now)
                connection.execute("COMMIT")
                raise DevicePairingDenied("pairing session expired")
            attempts = int(row["attempts"]) + 1
            valid = hmac.compare_digest(
                self._digest(bytes(row["salt"]), code), str(row["code_digest"])
            )
            if not valid:
                terminal = attempts >= MAX_ATTEMPTS
                connection.execute(
                    "UPDATE pairing_sessions SET attempts=?,status=?,updated_at=? WHERE pairing_id=?",
                    (attempts, "cancelled" if terminal else "pending", now, key),
                )
                self._event(connection, key, "pairing.rejected", {
                    "attempt": attempts, "terminal": terminal,
                }, now)
                connection.execute("COMMIT")
                raise DevicePairingDenied("pairing code was rejected")
            connection.execute(
                "UPDATE pairing_sessions SET attempts=?,status='claimed',salt=?,code_digest=?,updated_at=? WHERE pairing_id=?",
                (attempts, b"", _ZERO_HASH, now, key),
            )
            self._event(connection, key, "pairing.claimed", {
                "device_id": str(row["device_id"]), "credential_issued": False,
            }, now)
            connection.execute("COMMIT")
            return PairingClaimV1(
                key, str(row["owner_profile_id"]), str(row["workspace_id"]),
                str(row["device_id"]), str(row["issuer"]), "claimed", now,
            )

    def cancel(self, pairing_id: str) -> PairingStatusV1:
        key = _identifier(pairing_id, "pairing_id")
        now = _now(self._clock())
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE pairing_sessions SET status='cancelled',salt=?,code_digest=?,updated_at=? WHERE pairing_id=? AND status='pending'",
                (b"", _ZERO_HASH, now, key),
            ).rowcount
            if changed != 1:
                connection.execute("ROLLBACK")
                raise DevicePairingDenied("pending pairing session is unavailable")
            self._event(connection, key, "pairing.cancelled", {}, now)
            connection.execute("COMMIT")
        return self.status(key)

    def status(self, pairing_id: str) -> PairingStatusV1:
        key = _identifier(pairing_id, "pairing_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT pairing_id,device_id,status,attempts,expires_at FROM pairing_sessions WHERE pairing_id=?",
                (key,),
            ).fetchone()
        if row is None:
            raise DevicePairingDenied("pairing session is unavailable")
        return PairingStatusV1(
            str(row["pairing_id"]), str(row["device_id"]), str(row["status"]),
            int(row["attempts"]), float(row["expires_at"]),
        )


__all__ = [
    "FEATURE_FLAG", "MAX_LIFETIME_SECONDS", "MAX_ATTEMPTS",
    "DevicePairingError", "DevicePairingContractError", "DevicePairingDenied",
    "PairingChallengeV1", "PairingClaimV1", "PairingStatusV1",
    "DevicePairingStoreV1",
]
