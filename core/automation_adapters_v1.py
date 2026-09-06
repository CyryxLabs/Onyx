"""Bounded native adapters for the governed automation runtime.

Adapters only authenticate and normalize external signals into metadata-only
``AutomationEventV1`` values.  They do not schedule workers, poll URLs, watch
directories, execute plans or call providers.  A host native event source must
invoke them explicitly.
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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.governed_automation_v1 import AutomationEventV1
from core.native_vault import SecretReference
from core.phase6_agentic_core_v6 import normalized_sql_v6


SCHEMA_VERSION = 1
FEATURE_FLAG = "ONYX_AUTOMATION_ADAPTERS_V1"
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,191}")
_SIGNATURE = re.compile(r"sha256=([0-9a-f]{64})")
_MAX_WEBHOOK_BYTES = 65_536
_WEBHOOK_WINDOW_SECONDS = 300.0


class AutomationAdapterError(RuntimeError):
    pass


class AutomationAdapterContractError(ValueError):
    pass


class AutomationAdapterDenied(PermissionError):
    pass


class AutomationAdapterReplay(AutomationAdapterDenied):
    pass


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise AutomationAdapterContractError(f"{label} is invalid")
    return value


def _canonical_json(value: object) -> str:
    try:
        result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise AutomationAdapterContractError("value is not canonical JSON") from exc
    if len(result.encode()) > 65_536:
        raise AutomationAdapterContractError("value exceeds its byte budget")
    return result


def _private_path(path: Path) -> None:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise AutomationAdapterContractError("an explicit absolute database path is required")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise AutomationAdapterDenied("linked adapter directory is forbidden")
    attributes = getattr(path.parent.stat(), "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if attributes & reparse:
        raise AutomationAdapterDenied("reparse-point adapter directory is forbidden")
    if path.exists() and path.is_symlink():
        raise AutomationAdapterDenied("linked adapter database is forbidden")


def _finite_time(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise AutomationAdapterContractError(f"{label} is invalid")
    return float(value)


@dataclass(frozen=True)
class AutomationAdapterFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise AutomationAdapterContractError("enabled must be an exact boolean")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "AutomationAdapterFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


class AutomationAdapterStateV1:
    _DDL = (
        """CREATE TABLE metadata(schema_version INTEGER NOT NULL CHECK(schema_version=1))""",
        """CREATE TABLE webhook_nonces(
          source_id TEXT NOT NULL,
          nonce TEXT NOT NULL,
          body_digest TEXT NOT NULL,
          observed_at REAL NOT NULL,
          PRIMARY KEY(source_id,nonce)
        )""",
        """CREATE TABLE time_occurrences(
          schedule_id TEXT NOT NULL,
          local_date TEXT NOT NULL,
          timezone TEXT NOT NULL,
          emitted_at REAL NOT NULL,
          PRIMARY KEY(schedule_id,local_date)
        )""",
        """CREATE INDEX idx_webhook_retention ON webhook_nonces(observed_at)""",
    )

    def __init__(self, path: Path | str, gate: AutomationAdapterFeatureGateV1) -> None:
        if type(gate) is not AutomationAdapterFeatureGateV1 or not gate.enabled:
            raise AutomationAdapterDenied("automation adapters are disabled")
        self.path = Path(path)
        _private_path(self.path)
        self._lock = threading.RLock()
        self._expected_signature = self._build_expected_signature()
        self.initialize()

    @staticmethod
    def _signature(connection: sqlite3.Connection) -> str:
        objects = []
        for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ):
            if row[3] is None:
                raise AutomationAdapterError("schema object has no stored SQL")
            objects.append((row[0], row[1], row[2], normalized_sql_v6(str(row[3]))))
        details: dict[str, object] = {}
        for table in sorted(row[1] for row in objects if row[0] == "table"):
            details[f"table_xinfo:{table}"] = [
                tuple(item) for item in connection.execute(f"PRAGMA table_xinfo('{table}')")
            ]
        return hashlib.sha256(_canonical_json({"objects": objects, "details": details}).encode()).hexdigest()

    @classmethod
    def _build_expected_signature(cls) -> str:
        connection = sqlite3.connect(":memory:")
        try:
            for statement in cls._DDL:
                connection.execute(statement)
            connection.execute("INSERT INTO metadata(schema_version) VALUES(1)")
            connection.execute("PRAGMA user_version=1")
            return cls._signature(connection)
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        _private_path(self.path)
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def initialize(self) -> None:
        with self._lock, self._connect() as connection:
            count = int(connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
            ).fetchone()[0])
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if count == 0 and version == 0:
                connection.execute("BEGIN IMMEDIATE")
                for statement in self._DDL:
                    connection.execute(statement)
                connection.execute("INSERT INTO metadata(schema_version) VALUES(1)")
                connection.execute("PRAGMA user_version=1")
                connection.execute("COMMIT")
            if (
                int(connection.execute("PRAGMA user_version").fetchone()[0]) != 1
                or [tuple(row) for row in connection.execute("SELECT schema_version FROM metadata")] != [(1,)]
                or self._signature(connection) != self._expected_signature
                or connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            ):
                raise AutomationAdapterError("automation-adapter schema authentication failed")

    def register_nonce(
        self, source_id: str, nonce: str, body_digest: str, observed_at: float
    ) -> None:
        try:
            with self._lock, self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO webhook_nonces VALUES(?,?,?,?)",
                    (source_id, nonce, body_digest, observed_at),
                )
                connection.execute(
                    "DELETE FROM webhook_nonces WHERE observed_at<?",
                    (observed_at - 86400.0,),
                )
                connection.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise AutomationAdapterReplay("webhook nonce was already observed") from exc

    def register_time_occurrence(
        self, schedule_id: str, local_date: str, timezone: str, emitted_at: float
    ) -> bool:
        try:
            with self._lock, self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO time_occurrences VALUES(?,?,?,?)",
                    (schedule_id, local_date, timezone, emitted_at),
                )
                connection.execute("COMMIT")
            return True
        except sqlite3.IntegrityError:
            return False


class SignedWebhookAdapterV1:
    def __init__(
        self,
        *,
        state: AutomationAdapterStateV1,
        source_id: str,
        secret_reference: SecretReference,
        vault_reader: Callable[[SecretReference], bytes | None],
        clock: Callable[[], float] = time.time,
    ) -> None:
        if type(state) is not AutomationAdapterStateV1:
            raise AutomationAdapterContractError("exact adapter state is required")
        if type(secret_reference) is not SecretReference:
            raise AutomationAdapterContractError("exact SecretReference is required")
        if not callable(vault_reader) or not callable(clock):
            raise AutomationAdapterContractError("webhook dependencies must be callable")
        self._state = state
        self._source_id = _identifier(source_id, "source_id")
        self._secret_reference = secret_reference
        self._vault_reader = vault_reader
        self._clock = clock
        self.background_workers = 0
        self.polling_interval = None

    def ingest(
        self,
        *,
        body: bytes | bytearray,
        signature: str,
        timestamp: float,
        nonce: str,
        owner_profile_id: str,
        workspace_id: str,
        event_type: str,
        coalesce_key: str | None = None,
    ) -> AutomationEventV1:
        if not isinstance(body, (bytes, bytearray)):
            raise AutomationAdapterContractError("webhook body must be bytes")
        raw = bytes(body)
        if not raw or len(raw) > _MAX_WEBHOOK_BYTES:
            raise AutomationAdapterDenied("webhook body size is invalid")
        observed = _finite_time(self._clock(), "clock")
        sent_at = _finite_time(timestamp, "timestamp")
        if abs(observed - sent_at) > _WEBHOOK_WINDOW_SECONDS:
            raise AutomationAdapterDenied("webhook timestamp is outside its replay window")
        nonce_value = _identifier(nonce, "nonce")
        match = _SIGNATURE.fullmatch(signature)
        if match is None:
            raise AutomationAdapterDenied("webhook signature is malformed")
        secret = self._vault_reader(self._secret_reference)
        if not isinstance(secret, bytes) or not 32 <= len(secret) <= 256:
            raise AutomationAdapterDenied("webhook credential is unavailable")
        signed = f"{sent_at:.6f}.".encode() + raw
        expected = hmac.new(secret, signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, match.group(1)):
            raise AutomationAdapterDenied("webhook authentication failed")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AutomationAdapterContractError("webhook body is not bounded JSON") from exc
        if type(decoded) is not dict:
            raise AutomationAdapterContractError("webhook JSON must be a plain object")
        body_digest = hashlib.sha256(raw).hexdigest()
        self._state.register_nonce(self._source_id, nonce_value, body_digest, observed)
        return AutomationEventV1.create(
            event_type=event_type,
            source_id=self._source_id,
            owner_profile_id=owner_profile_id,
            workspace_id=workspace_id,
            metadata=decoded,
            coalesce_key=coalesce_key,
            occurred_at=sent_at,
        )


class ExplicitTimezoneTriggerV1:
    def __init__(self, state: AutomationAdapterStateV1) -> None:
        if type(state) is not AutomationAdapterStateV1:
            raise AutomationAdapterContractError("exact adapter state is required")
        self._state = state
        self.background_workers = 0
        self.polling_interval = None

    def due_event(
        self,
        *,
        schedule_id: str,
        timezone: str,
        hour: int,
        minute: int,
        now: float,
        owner_profile_id: str,
        workspace_id: str,
        event_type: str,
    ) -> AutomationEventV1 | None:
        schedule = _identifier(schedule_id, "schedule_id")
        if type(timezone) is not str or not timezone or len(timezone) > 128:
            raise AutomationAdapterContractError("timezone is invalid")
        if type(hour) is not int or not 0 <= hour <= 23 or type(minute) is not int or not 0 <= minute <= 59:
            raise AutomationAdapterContractError("schedule time is invalid")
        timestamp = _finite_time(now, "now")
        try:
            zone = ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise AutomationAdapterContractError("timezone is unknown") from exc
        local = datetime.fromtimestamp(timestamp, zone)
        if (local.hour, local.minute) != (hour, minute):
            return None
        local_date = local.date().isoformat()
        if not self._state.register_time_occurrence(schedule, local_date, timezone, timestamp):
            return None
        return AutomationEventV1.create(
            event_type=event_type,
            source_id="native_time_scheduler",
            owner_profile_id=owner_profile_id,
            workspace_id=workspace_id,
            metadata={"schedule_id": schedule, "local_date": local_date, "timezone": timezone},
            coalesce_key=f"{schedule}:{local_date}",
            occurred_at=timestamp,
        )


class WorkspaceFileEventAdapterV1:
    def __init__(self, roots: Sequence[Path | str]) -> None:
        if type(roots) not in {tuple, list} or not roots:
            raise AutomationAdapterContractError("workspace roots are required")
        resolved: list[Path] = []
        for value in roots:
            root = Path(value)
            if not root.is_absolute() or root.is_symlink():
                raise AutomationAdapterDenied("workspace root must be real and absolute")
            try:
                candidate = root.resolve(strict=True)
            except OSError as exc:
                raise AutomationAdapterDenied("workspace root is unavailable") from exc
            if not candidate.is_dir():
                raise AutomationAdapterDenied("workspace root must be a directory")
            resolved.append(candidate)
        self._roots = tuple(resolved)
        self.background_workers = 0
        self.polling_interval = None

    def from_native_event(
        self,
        *,
        path: Path | str,
        event_kind: str,
        owner_profile_id: str,
        workspace_id: str,
        occurred_at: float | None = None,
    ) -> AutomationEventV1:
        if event_kind not in {"created", "modified", "renamed", "deleted"}:
            raise AutomationAdapterContractError("file event kind is invalid")
        candidate = Path(path)
        if not candidate.is_absolute():
            raise AutomationAdapterDenied("file event path must be absolute")
        # Deleted paths may no longer resolve; their parent still must resolve
        # inside a controlled root. Existing paths may not be links/reparse points.
        probe = candidate if candidate.exists() else candidate.parent
        try:
            resolved_probe = probe.resolve(strict=True)
        except OSError as exc:
            raise AutomationAdapterDenied("file event boundary is unavailable") from exc
        root = next((item for item in self._roots if resolved_probe == item or item in resolved_probe.parents), None)
        if root is None or (candidate.exists() and resolved_probe == root):
            raise AutomationAdapterDenied("file event is outside controlled workspaces")
        if candidate.exists():
            info = candidate.lstat()
            attributes = getattr(info, "st_file_attributes", 0)
            reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if candidate.is_symlink() or attributes & reparse:
                raise AutomationAdapterDenied("linked file event is forbidden")
        relative = candidate.absolute().relative_to(root)
        extension = candidate.suffix.casefold()[:24] or "none"
        timestamp = time.time() if occurred_at is None else _finite_time(occurred_at, "occurred_at")
        path_digest = hashlib.sha256(relative.as_posix().encode()).hexdigest()
        return AutomationEventV1.create(
            event_type="workspace.file.changed",
            source_id="native_workspace_events",
            owner_profile_id=owner_profile_id,
            workspace_id=workspace_id,
            metadata={
                "event_kind": event_kind,
                "extension": extension,
                "path_digest": path_digest,
                "root_digest": hashlib.sha256(str(root).encode()).hexdigest(),
            },
            coalesce_key="file_" + path_digest,
            occurred_at=timestamp,
        )
