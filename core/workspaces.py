"""Default-off M1b workspace registry and non-destructive legacy backfill."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import stat
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Mapping

from core.control_plane import (
    ControlPlaneError,
    ControlPlaneIOError,
    ControlPlaneStore,
    _InitializationLock,
    _WindowsNamedMutex,
    _current_windows_sid,
    _reject_link_chain,
    _save_windows_dacl,
    _secure_private_directory,
    _verify_windows_sddl,
    _verify_windows_private_ancestor,
    _windows_owner_sid,
)
from core.paths import memory_dir


WORKSPACE_REGISTRY_FLAG = "ONYX_WORKSPACE_REGISTRY_V1"
M1B_BACKFILL_FLAG = "ONYX_M1B_BACKFILL_V1"
LEGACY_WORKSPACE_ID = "legacy-default"
WORKSPACE_SCHEMA_VERSION = 1
BACKFILL_SCHEMA_VERSION = 1
BACKFILL_LEASE_SECONDS = 10.0
BACKFILL_HEARTBEAT_SECONDS = 2.0

_WORKSPACE_ID = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_WORKSPACE_CLASSES = frozenset({"cyryx", "client", "professional", "personal"})
_WORKSPACE_STATUSES = frozenset({"active", "inactive"})
_MISSION_STATES = frozenset(
    {
        "draft",
        "awaiting_approval",
        "running",
        "waiting",
        "paused",
        "succeeded",
        "failed",
        "cancelled",
    }
)
_BACKFILL_RUN_SELECT = (
    "run_id,schema_version,status,mission_source_identity,mission_source_hash,"
    "memory_source_identity,memory_source_hash,started_at,completed_at,readback_hash,"
    "payload_json,lease_owner,lease_expires_at,heartbeat_at,lease_epoch"
)
_MARKER_SEAL = object()
_PATHS_SEAL = object()
_SNAPSHOT_ROOT_LOCK = threading.RLock()


def _validate_private_directory(path: Path) -> None:
    _reject_link_chain(path)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise BackfillSourceError("snapshot root is not a directory")
    if os.name == "nt":
        current_sid = _current_windows_sid()
        if _windows_owner_sid(path) != current_sid:
            raise BackfillSourceError("snapshot root is not owned by the current user")
        _verify_windows_sddl(
            _save_windows_dacl(path), current_sid, is_directory=True
        )
        return
    getuid = getattr(os, "getuid", None)
    if getuid is not None and info.st_uid != getuid():
        raise BackfillSourceError("snapshot root is not owned by the current user")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise BackfillSourceError("snapshot root permissions are not owner-only")


def _prepare_snapshot_root(path: Path) -> None:
    process_lock = (
        _WindowsNamedMutex(path)
        if os.name == "nt"
        else _InitializationLock(path.parent)
    )
    process_lock.acquire()
    try:
        if path.exists():
            _validate_private_directory(path)
            return
        path.mkdir(mode=0o700, parents=False, exist_ok=False)
        _secure_private_directory(path)
        _validate_private_directory(path)
    finally:
        process_lock.release()


class WorkspaceError(ControlPlaneError):
    pass


class WorkspaceExtensionDisabled(WorkspaceError):
    pass


class WorkspaceIdentityError(WorkspaceError):
    pass


class WorkspaceUnknown(WorkspaceIdentityError):
    pass


class WorkspaceInactive(WorkspaceIdentityError):
    pass


class WorkspaceIsolationError(WorkspaceError):
    pass


class WorkspacePendingReview(WorkspaceError):
    pass


class LegacyMarkerError(WorkspaceError):
    pass


class BackfillDisabled(WorkspaceExtensionDisabled):
    pass


class BackfillSourceError(WorkspaceError):
    pass


class BackfillConflict(WorkspaceError):
    pass


@dataclass(frozen=True)
class WorkspaceRecord:
    workspace_id: str
    display_name: str
    workspace_class: str
    status: str
    schema_version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class BackfillResult:
    run_id: str
    status: str
    mission_scanned: int
    mission_assigned: int
    mission_pending: int
    memory_scanned: int
    memory_assigned: int
    memory_pending: int
    candidate_read_back: int
    context_read_back: int
    readback_hash: str
    idempotent_replay: bool


@dataclass(frozen=True)
class _FileEvidence:
    role: str
    name: str
    identity: tuple[int, int]
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True)
class _Candidate:
    source_kind: str
    source_id: str
    schema_version: int
    logical_hash: str
    reason: str
    assignable: bool


@dataclass(frozen=True)
class LegacySnapshot:
    mission_identity: str
    mission_hash: str
    memory_identity: str
    memory_hash: str
    directory_identity: tuple[int, int]
    directory_listing: tuple[str, ...]
    manifest: tuple[_FileEvidence, ...]
    missions: tuple[_Candidate, ...]
    memories: tuple[_Candidate, ...]


class _LegacyHostMarker:
    __slots__ = ()

    def __new__(cls, seal: object = None) -> "_LegacyHostMarker":
        if cls is not _LegacyHostMarker or seal is not _MARKER_SEAL:
            raise TypeError("legacy host marker is not caller-constructible")
        return super().__new__(cls)

    def __reduce__(self) -> object:
        raise TypeError("legacy host marker is not serializable")

    def __copy__(self) -> object:
        raise TypeError("legacy host marker is not copyable")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("legacy host marker is not copyable")

    def __init_subclass__(cls, **_kwargs: object) -> None:
        raise TypeError("legacy host marker cannot be subclassed")


_HOST_MARKER = _LegacyHostMarker(_MARKER_SEAL)


class LegacySourcePaths:
    """Opaque host-owned source binding; request payloads cannot construct it."""

    __slots__ = ("root", "mission_database", "memory_database", "long_term_json")

    def __init__(self, seal: object, root: Path):
        if seal is not _PATHS_SEAL:
            raise TypeError("legacy source paths are host-owned")
        canonical = Path(os.path.abspath(root))
        self.root = canonical
        self.mission_database = canonical / "onyx_missions.sqlite3"
        self.memory_database = canonical / "onyx_memory.sqlite3"
        self.long_term_json = canonical / "long_term.json"


def _host_owned_source_paths(marker: object) -> LegacySourcePaths:
    if marker is not _HOST_MARKER:
        raise LegacyMarkerError("trusted host marker is required for legacy sources")
    return LegacySourcePaths(_PATHS_SEAL, memory_dir())


def _enabled(flag: str, environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return source.get(flag, "").strip().casefold() in {"1", "true"}


def workspace_registry_enabled(environ: Mapping[str, str] | None = None) -> bool:
    return _enabled(WORKSPACE_REGISTRY_FLAG, environ)


def m1b_backfill_enabled(environ: Mapping[str, str] | None = None) -> bool:
    return _enabled(M1B_BACKFILL_FLAG, environ)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _workspace_id(value: object) -> str:
    if not isinstance(value, str) or not _WORKSPACE_ID.fullmatch(value):
        raise WorkspaceIdentityError("an explicit valid workspace_id is required")
    return value


def _source_id(value: object, kind: str) -> str:
    if not isinstance(value, str) or not _SOURCE_ID.fullmatch(value):
        raise BackfillSourceError(f"{kind} source contains a malformed ID")
    return value


def _workspace_record(row: tuple[object, ...]) -> WorkspaceRecord:
    workspace_id, version, status, payload_text, created_at, updated_at = row
    try:
        payload = json.loads(str(payload_text))
    except (TypeError, ValueError) as exc:
        raise BackfillConflict("workspace payload is malformed") from exc
    if (
        int(version) != WORKSPACE_SCHEMA_VERSION
        or status not in _WORKSPACE_STATUSES
        or not isinstance(payload, dict)
        or not isinstance(payload.get("display_name"), str)
        or not payload["display_name"].strip()
        or payload.get("workspace_class") not in _WORKSPACE_CLASSES
    ):
        raise BackfillConflict("workspace row violates the M1b contract")
    return WorkspaceRecord(
        str(workspace_id),
        payload["display_name"],
        payload["workspace_class"],
        str(status),
        int(version),
        str(created_at),
        str(updated_at),
    )


class WorkspaceRegistry:
    def __init__(self, store: ControlPlaneStore, *, enabled: bool | None = None):
        if enabled is not None and type(enabled) is not bool:
            raise TypeError("enabled must be bool or None")
        self.store = store
        self.enabled = workspace_registry_enabled() if enabled is None else enabled

    def initialize(self) -> "WorkspaceRegistry":
        if not self.enabled:
            raise WorkspaceExtensionDisabled(
                f"{WORKSPACE_REGISTRY_FLAG} is disabled; legacy runtime is unchanged"
            )
        self.store.initialize()
        return self

    def __enter__(self) -> "WorkspaceRegistry":
        return self.initialize()

    def __exit__(self, *_exc: object) -> None:
        self.store.close()

    def _connection(self) -> sqlite3.Connection:
        if not self.enabled:
            raise WorkspaceExtensionDisabled(f"{WORKSPACE_REGISTRY_FLAG} is disabled")
        return self.store._require_connection()

    def _lookup_raw(self, workspace_id: str) -> WorkspaceRecord:
        row = self._connection().execute(
            "SELECT workspace_id,schema_version,status,payload_json,created_at,updated_at "
            "FROM workspaces WHERE workspace_id=?",
            (workspace_id,),
        ).fetchone()
        if row is None:
            raise WorkspaceUnknown(f"unknown workspace_id {workspace_id}")
        record = _workspace_record(tuple(row))
        if record.workspace_id != workspace_id:
            raise WorkspaceIsolationError("workspace lookup returned a different identity")
        return record

    def get(self, workspace_id: object) -> WorkspaceRecord:
        normalized = _workspace_id(workspace_id)
        if normalized == LEGACY_WORKSPACE_ID:
            raise LegacyMarkerError("legacy-default requires LegacyWorkspaceAdapter")
        return self._lookup_raw(normalized)

    def require_active(self, workspace_id: object) -> WorkspaceRecord:
        record = self.get(workspace_id)
        if record.status != "active":
            raise WorkspaceInactive(f"workspace {record.workspace_id} is inactive")
        return record

    def register(
        self,
        workspace_id: object,
        *,
        display_name: str,
        workspace_class: str,
        active: bool = True,
    ) -> WorkspaceRecord:
        normalized = _workspace_id(workspace_id)
        if normalized == LEGACY_WORKSPACE_ID:
            raise LegacyMarkerError("legacy-default requires LegacyWorkspaceAdapter")
        if not isinstance(display_name, str) or not display_name.strip():
            raise WorkspaceIdentityError("display_name is required")
        if workspace_class not in _WORKSPACE_CLASSES:
            raise WorkspaceIdentityError("workspace class is invalid")
        if type(active) is not bool:
            raise TypeError("active must be bool")
        return self._upsert(
            normalized,
            display_name.strip(),
            workspace_class,
            "active" if active else "inactive",
        )

    def _upsert(
        self, workspace_id: str, display_name: str, workspace_class: str, status: str
    ) -> WorkspaceRecord:
        connection = self._connection()
        now = _now()
        payload = _json(
            {
                "display_name": display_name,
                "workspace_class": workspace_class,
                "registry_version": WORKSPACE_SCHEMA_VERSION,
            }
        )
        try:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute(
                "SELECT created_at FROM workspaces WHERE workspace_id=?", (workspace_id,)
            ).fetchone()
            connection.execute(
                "INSERT INTO workspaces VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(workspace_id) DO UPDATE SET "
                "schema_version=excluded.schema_version,status=excluded.status,"
                "payload_json=excluded.payload_json,updated_at=excluded.updated_at",
                (
                    workspace_id,
                    WORKSPACE_SCHEMA_VERSION,
                    status,
                    payload,
                    str(old[0]) if old else now,
                    now,
                ),
            )
            connection.execute("COMMIT")
        except sqlite3.DatabaseError as exc:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise ControlPlaneIOError(f"workspace registry write failed: {exc}") from exc
        return self._lookup_raw(workspace_id)

    def set_active(self, workspace_id: object, active: bool) -> WorkspaceRecord:
        if type(active) is not bool:
            raise TypeError("active must be bool")
        record = self.get(workspace_id)
        return self._upsert(
            record.workspace_id,
            record.display_name,
            record.workspace_class,
            "active" if active else "inactive",
        )

    def mission_reference(self, workspace_id: object, mission_id: object) -> dict[str, object]:
        workspace = self.require_active(workspace_id)
        mission = _source_id(mission_id, "mission")
        row = self._connection().execute(
            "SELECT workspace_id,operational_phase,payload_json FROM mission_contexts "
            "WHERE mission_id=?",
            (mission,),
        ).fetchone()
        if row is None:
            raise WorkspaceUnknown("mission context is unknown")
        if row[0] != workspace.workspace_id:
            raise WorkspaceIsolationError("mission context belongs to another workspace")
        if row[1] == "PENDING_REVIEW":
            raise WorkspacePendingReview("mission context is pending review")
        payload = json.loads(str(row[2]))
        run = self._connection().execute(
            "SELECT status FROM backfill_runs WHERE run_id=?", (payload.get("run_id"),)
        ).fetchall()
        if len(run) != 1 or run[0][0] != "verified":
            raise WorkspacePendingReview("mission context backfill is not verified")
        return payload

    def memory_reference(self, workspace_id: object, memory_id: object) -> dict[str, object]:
        workspace = self.require_active(workspace_id)
        memory = _source_id(memory_id, "memory")
        rows = self._connection().execute(
            "SELECT workspace_id,status,payload_json FROM memory_metadata "
            "WHERE source_memory_id=?",
            (memory,),
        ).fetchall()
        if not rows:
            raise WorkspaceUnknown("memory reference is unknown")
        row = next((item for item in rows if item[0] == workspace.workspace_id), None)
        if row is None:
            raise WorkspaceIsolationError("memory reference belongs to another workspace")
        if row[1] != "active":
            raise WorkspacePendingReview("memory reference is not reviewed")
        payload = json.loads(str(row[2]))
        run = self._connection().execute(
            "SELECT status FROM backfill_runs WHERE run_id=?", (payload.get("run_id"),)
        ).fetchall()
        if len(run) != 1 or run[0][0] != "verified":
            raise WorkspacePendingReview("memory reference backfill is not verified")
        return payload


class LegacyWorkspaceAdapter:
    """Identity-bound compatibility adapter limited to ``legacy-default``."""

    __slots__ = ("registry", "_marker")

    def __init__(self, registry: WorkspaceRegistry, marker: object):
        if marker is not _HOST_MARKER:
            raise LegacyMarkerError("trusted host-owned legacy marker is required")
        self.registry = registry
        self._marker = marker

    def __copy__(self) -> object:
        raise TypeError("legacy workspace adapter is not copyable")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("legacy workspace adapter is not copyable")

    def __reduce__(self) -> object:
        raise TypeError("legacy workspace adapter is not serializable")

    def __init_subclass__(cls, **_kwargs: object) -> None:
        raise TypeError("legacy workspace adapter cannot be subclassed")

    def resolve(self) -> WorkspaceRecord:
        if getattr(self, "_marker", None) is not _HOST_MARKER:
            raise LegacyMarkerError("legacy adapter authorization is invalid")
        if not isinstance(getattr(self, "registry", None), WorkspaceRegistry):
            raise LegacyMarkerError("legacy adapter registry binding is invalid")
        try:
            record = self.registry._lookup_raw(LEGACY_WORKSPACE_ID)
        except WorkspaceUnknown:
            record = self.registry._upsert(
                LEGACY_WORKSPACE_ID, "Legacy Default", "personal", "active"
            )
        if record.workspace_id != LEGACY_WORKSPACE_ID:
            raise WorkspaceIsolationError("legacy adapter resolved an unexpected workspace")
        if record.status != "active":
            raise WorkspaceInactive("legacy-default is inactive")
        return record


def _validate_legacy_path(path: Path, *, directory: bool) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise BackfillSourceError(f"legacy source path could not be inspected: {exc}") from exc
    reparse = bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )
    expected_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if stat.S_ISLNK(info.st_mode) or reparse or not expected_type:
        raise BackfillSourceError("legacy source path is linked, reparse, or non-regular")
    _reject_link_chain(path)
    if os.name == "nt":
        try:
            _verify_windows_private_ancestor(path)
        except ControlPlaneError as exc:
            raise BackfillSourceError(f"legacy source ACL is unsafe: {exc}") from exc
    else:
        getuid = getattr(os, "getuid", None)
        if getuid is not None and info.st_uid != getuid():
            raise BackfillSourceError("legacy source is not owned by the current user")
        if stat.S_IMODE(info.st_mode) & 0o022:
            raise BackfillSourceError(
                "legacy source grants write access to another principal"
            )
    return info


def _hash_file(path: Path, role: str) -> _FileEvidence:
    inspected = _validate_legacy_path(path, directory=False)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise BackfillSourceError(f"could not read {role} source: {exc}") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise BackfillSourceError(f"{role} source is not a regular file")
        if (int(inspected.st_dev), int(inspected.st_ino)) != (
            int(before.st_dev),
            int(before.st_ino),
        ):
            raise BackfillSourceError(f"{role} source identity changed before open")
        digest = hashlib.sha256()
        while block := os.read(descriptor, 1024 * 1024):
            digest.update(block)
        after = os.fstat(descriptor)
        identity = (int(before.st_dev), int(before.st_ino))
        if identity != (int(after.st_dev), int(after.st_ino)) or before.st_size != after.st_size:
            raise BackfillSourceError(f"{role} source changed while hashing")
        return _FileEvidence(
            role,
            path.name,
            identity,
            int(after.st_size),
            int(after.st_mtime_ns),
            digest.hexdigest(),
        )
    finally:
        os.close(descriptor)


def _copy_verified(path: Path, evidence: _FileEvidence, destination: Path) -> None:
    inspected = _validate_legacy_path(path, directory=False)
    if (int(inspected.st_dev), int(inspected.st_ino)) != evidence.identity:
        raise BackfillSourceError("legacy source identity changed before stable copy")
    source_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    target_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    source = os.open(path, source_flags)
    target = os.open(destination, target_flags, 0o600)
    digest = hashlib.sha256()
    try:
        before = os.fstat(source)
        if (int(before.st_dev), int(before.st_ino)) != evidence.identity:
            raise BackfillSourceError("legacy source identity changed before copy")
        while block := os.read(source, 1024 * 1024):
            digest.update(block)
            os.write(target, block)
        after = os.fstat(source)
        if (
            (int(after.st_dev), int(after.st_ino)) != evidence.identity
            or int(after.st_size) != evidence.size
            or digest.hexdigest() != evidence.sha256
        ):
            raise BackfillSourceError("legacy source changed during stable copy")
        os.fsync(target)
    finally:
        os.close(target)
        os.close(source)


class LegacySnapshotReader:
    """Read stable copies of fixed host-owned legacy source families."""

    def __init__(self, paths: LegacySourcePaths, marker: object):
        if marker is not _HOST_MARKER or not isinstance(paths, LegacySourcePaths):
            raise LegacyMarkerError("host-owned source binding is required")
        self.paths = paths

    def _family(self) -> tuple[tuple[Path, str, bool], ...]:
        output: list[tuple[Path, str, bool]] = []
        for main, role in (
            (self.paths.mission_database, "mission"),
            (self.paths.memory_database, "memory"),
        ):
            output.append((main, role, True))
            for suffix in ("-wal", "-shm", "-journal"):
                output.append((Path(f"{main}{suffix}"), role, False))
        output.append((self.paths.long_term_json, "memory", False))
        return tuple(output)

    def manifest(self) -> tuple[_FileEvidence, ...]:
        evidence = []
        for path, role, required in self._family():
            try:
                path.lstat()
            except FileNotFoundError:
                if required:
                    raise BackfillSourceError(f"required {role} database is missing")
                continue
            except OSError as exc:
                raise BackfillSourceError(
                    f"could not inspect {role} source path: {exc}"
                ) from exc
            try:
                evidence.append(_hash_file(path, role))
            except ControlPlaneError as exc:
                raise BackfillSourceError(
                    f"unsafe {role} source path: {exc}"
                ) from exc
        return tuple(evidence)

    def _directory_state(self) -> tuple[tuple[int, int], tuple[str, ...]]:
        try:
            info = _validate_legacy_path(self.paths.root, directory=True)
            listing = tuple(sorted(item.name for item in self.paths.root.iterdir()))
        except OSError as exc:
            raise BackfillSourceError(f"could not inspect legacy source directory: {exc}") from exc
        return (int(info.st_dev), int(info.st_ino)), listing

    @staticmethod
    def _manifest_hash(manifest: tuple[_FileEvidence, ...], role: str) -> str:
        rows = [
            {"role": item.role, "name": item.name, "size": item.size, "sha256": item.sha256}
            for item in manifest
            if item.role == role
        ]
        return hashlib.sha256(_json(rows).encode()).hexdigest()

    @contextlib.contextmanager
    def capture(self, snapshot_root: Path) -> Iterator[LegacySnapshot]:
        with _SNAPSHOT_ROOT_LOCK:
            _prepare_snapshot_root(snapshot_root)
        directory_before = self._directory_state()
        before = self.manifest()
        with tempfile.TemporaryDirectory(
            prefix="onyx-m1b-snapshot-", dir=snapshot_root
        ) as temporary:
            target = Path(temporary)
            _secure_private_directory(target)
            for path, _role, _required in self._family():
                matching = next((item for item in before if item.name == path.name), None)
                if matching is None:
                    continue
                destination = target / path.name
                try:
                    _copy_verified(path, matching, destination)
                except OSError as exc:
                    raise BackfillSourceError(f"stable source copy failed: {exc}") from exc
                if hashlib.sha256(destination.read_bytes()).hexdigest() != matching.sha256:
                    raise BackfillSourceError("stable source copy hash mismatch")
            after = self.manifest()
            directory_after = self._directory_state()
            if after != before or directory_after != directory_before:
                raise BackfillSourceError("legacy source family changed during snapshot")
            missions = _parse_missions(target / self.paths.mission_database.name)
            memories = _parse_memories(target / self.paths.memory_database.name)
            mission_hash = hashlib.sha256(
                (
                    self._manifest_hash(before, "mission")
                    + _json([(item.source_id, item.logical_hash) for item in missions])
                ).encode()
            ).hexdigest()
            memory_hash = hashlib.sha256(
                (
                    self._manifest_hash(before, "memory")
                    + _json([(item.source_id, item.logical_hash) for item in memories])
                ).encode()
            ).hexdigest()
            snapshot = LegacySnapshot(
                os.fspath(self.paths.mission_database),
                mission_hash,
                os.fspath(self.paths.memory_database),
                memory_hash,
                directory_before[0],
                directory_before[1],
                before,
                missions,
                memories,
            )
            yield snapshot

    def unchanged(self, snapshot: LegacySnapshot) -> bool:
        try:
            return self.manifest() == snapshot.manifest and self._directory_state() == (
                snapshot.directory_identity,
                snapshot.directory_listing,
            )
        except BackfillSourceError:
            return False


def _authorizer(action: int, argument1: str | None, argument2: str | None, *_: object) -> int:
    denied = {
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_UPDATE,
        sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_CREATE_INDEX,
        sqlite3.SQLITE_CREATE_TABLE,
        sqlite3.SQLITE_CREATE_TEMP_INDEX,
        sqlite3.SQLITE_CREATE_TEMP_TABLE,
        sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
        sqlite3.SQLITE_CREATE_TEMP_VIEW,
        sqlite3.SQLITE_CREATE_TRIGGER,
        sqlite3.SQLITE_CREATE_VIEW,
        sqlite3.SQLITE_DROP_INDEX,
        sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_INDEX,
        sqlite3.SQLITE_DROP_TEMP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_TRIGGER,
        sqlite3.SQLITE_DROP_TEMP_VIEW,
        sqlite3.SQLITE_DROP_TRIGGER,
        sqlite3.SQLITE_DROP_VIEW,
        sqlite3.SQLITE_ALTER_TABLE,
        sqlite3.SQLITE_ATTACH,
        sqlite3.SQLITE_DETACH,
        sqlite3.SQLITE_TRANSACTION,
    }
    readonly_pragmas = {
        "table_info",
        "table_xinfo",
        "index_list",
        "index_xinfo",
        "foreign_key_list",
    }
    if action in denied or (
        action == sqlite3.SQLITE_PRAGMA
        and (argument1 or "").casefold() not in readonly_pragmas
    ):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


@contextlib.contextmanager
def _readonly_database(path: Path) -> Iterator[sqlite3.Connection]:
    try:
        connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        if [row[0] for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
            raise BackfillSourceError("legacy snapshot integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise BackfillSourceError("legacy snapshot foreign-key check failed")
        connection.set_authorizer(_authorizer)
        yield connection
    except sqlite3.DatabaseError as exc:
        raise BackfillSourceError(f"legacy snapshot is not a valid read-only database: {exc}") from exc
    finally:
        if "connection" in locals():
            connection.close()


def _columns(connection: sqlite3.Connection, table: str) -> frozenset[str]:
    return frozenset(str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")'))


def _column_contract(
    connection: sqlite3.Connection, table: str, column: str
) -> tuple[str, int, int]:
    rows = {
        str(row[1]): (str(row[2]).upper(), int(row[3]), int(row[5]))
        for row in connection.execute(f'PRAGMA table_xinfo("{table}")')
        if int(row[6]) == 0
    }
    if column not in rows:
        raise BackfillSourceError(f"{table}.{column} is missing")
    return rows[column]


def _unique_indexes(connection: sqlite3.Connection, table: str) -> set[tuple[str, ...]]:
    output: set[tuple[str, ...]] = set()
    for row in connection.execute(f'PRAGMA index_list("{table}")'):
        if int(row[2]) != 1:
            continue
        output.add(
            tuple(
                str(item[2])
                for item in connection.execute(f'PRAGMA index_xinfo("{row[1]}")')
                if int(item[5]) == 1
            )
        )
    return output


def _normalized_ddl(value: object) -> str:
    normalized = re.sub(r"\s+", "", str(value).casefold())
    return normalized.replace("createtableifnotexists", "createtable", 1)


_MEMORY_TABLE_DDL = _normalized_ddl(
    """
    CREATE TABLE memories(
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL CHECK(kind IN ('semantic','episodic')),
        content TEXT NOT NULL,
        source TEXT NOT NULL,
        citation TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        salience REAL NOT NULL CHECK(salience >= 0 AND salience <= 1),
        session_id TEXT,
        task_id TEXT,
        category TEXT,
        memory_key TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        content_hash TEXT NOT NULL,
        access_count INTEGER NOT NULL DEFAULT 0,
        last_accessed_at TEXT
    )
    """
)


def _memory_text(row: sqlite3.Row, field: str, maximum: int, *, optional: bool = False) -> str | None:
    value = row[field]
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise BackfillSourceError(f"memory {field} is not text")
    clean = " ".join(value.split())
    if not clean or clean != value or len(clean) > maximum:
        raise BackfillSourceError(f"memory {field} violates the legacy store contract")
    return clean


def _parse_missions(path: Path) -> tuple[_Candidate, ...]:
    base_mission = {
        "id", "title", "state", "created_at", "updated_at", "max_steps", "max_seconds",
        "max_retries", "provider_cost_limit", "tool_allowlist", "current_step", "error",
        "deadline", "approval_digest",
    }
    lease_columns = {"lease_owner", "lease_expires", "lease_heartbeat"}
    step_columns = {
        "id", "mission_id", "position", "tool", "args", "state", "attempts",
        "idempotency_key", "result", "error", "wait_reason", "started_at", "completed_at",
    }
    event_base = {"seq", "mission_id", "timestamp", "event", "detail"}
    with _readonly_database(path) as connection:
        versions = connection.execute("SELECT version FROM schema_meta").fetchall()
        if len(versions) != 1 or int(versions[0][0]) not in {1, 2, 3}:
            raise BackfillSourceError("mission snapshot schema version is unsupported")
        version = int(versions[0][0])
        expected_mission = base_mission | (lease_columns if version == 3 else set())
        expected_event = event_base | ({"prev_hash", "event_hash"} if version >= 2 else set())
        if (
            _columns(connection, "missions") != expected_mission
            or _columns(connection, "steps") != step_columns
            or _columns(connection, "events") != expected_event
        ):
            raise BackfillSourceError("mission snapshot schema is hybrid or malformed")
        if (
            _column_contract(connection, "missions", "id") != ("TEXT", 0, 1)
            or _column_contract(connection, "missions", "state") != ("TEXT", 1, 0)
            or _column_contract(connection, "steps", "id") != ("TEXT", 0, 1)
            or _column_contract(connection, "steps", "mission_id") != ("TEXT", 1, 0)
            or _column_contract(connection, "events", "seq") != ("INTEGER", 0, 1)
        ):
            raise BackfillSourceError("mission table_xinfo contract is invalid")
        step_fks = {
            (str(row[2]), str(row[3]), str(row[4]))
            for row in connection.execute("PRAGMA foreign_key_list('steps')")
        }
        if step_fks != {("missions", "mission_id", "id")}:
            raise BackfillSourceError("mission step foreign-key contract is invalid")
        unique_steps = _unique_indexes(connection, "steps")
        if {("idempotency_key",), ("mission_id", "position")} - unique_steps:
            raise BackfillSourceError("mission step uniqueness contract is invalid")
        if version == 3:
            triggers = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger'"
                )
            }
            if not {"events_no_update", "events_no_delete"}.issubset(triggers):
                raise BackfillSourceError("mission immutable-event triggers are missing")
        if connection.execute(
            "SELECT count(*) FROM steps s LEFT JOIN missions m ON m.id=s.mission_id WHERE m.id IS NULL"
        ).fetchone()[0] or connection.execute(
            "SELECT count(*) FROM events e LEFT JOIN missions m ON m.id=e.mission_id WHERE m.id IS NULL"
        ).fetchone()[0]:
            raise BackfillSourceError("mission snapshot contains orphan rows")
        if connection.execute(
            "SELECT count(*) FROM (SELECT mission_id,position,count(*) n FROM steps "
            "GROUP BY mission_id,position HAVING n!=1)"
        ).fetchone()[0] or connection.execute(
            "SELECT count(*) FROM (SELECT idempotency_key,count(*) n FROM steps "
            "GROUP BY idempotency_key HAVING n!=1)"
        ).fetchone()[0]:
            raise BackfillSourceError("mission snapshot contains duplicate step identities")
        candidates = []
        for mission in connection.execute("SELECT * FROM missions ORDER BY id"):
            mission_id = _source_id(mission["id"], "mission")
            if mission["state"] not in _MISSION_STATES:
                raise BackfillSourceError("mission snapshot contains an invalid state")
            steps = [dict(row) for row in connection.execute(
                "SELECT * FROM steps WHERE mission_id=? ORDER BY position,id", (mission_id,)
            )]
            events = [dict(row) for row in connection.execute(
                "SELECT * FROM events WHERE mission_id=? ORDER BY seq", (mission_id,)
            )]
            if version >= 2:
                previous = ""
                for event in events:
                    expected = hashlib.sha256(
                        f"{mission_id}\0{float(event['timestamp']):.9f}\0{event['event']}\0"
                        f"{event['detail']}\0{previous}".encode()
                    ).hexdigest()
                    if event["prev_hash"] != previous or event["event_hash"] != expected:
                        raise BackfillSourceError("mission event chain is invalid")
                    previous = event["event_hash"]
            logical_hash = hashlib.sha256(
                _json({"mission": dict(mission), "steps": steps, "events": events}).encode()
            ).hexdigest()
            leased = version == 3 and mission["lease_owner"] is not None
            live = mission["state"] == "running" or leased
            unverifiable_v1 = version == 1
            candidates.append(
                _Candidate(
                    "mission",
                    mission_id,
                    version,
                    logical_hash,
                    (
                        "unverifiable_v1_event_chain"
                        if unverifiable_v1
                        else "live_or_leased_mission"
                        if live
                        else "authorized_legacy_mission"
                    ),
                    not live and not unverifiable_v1,
                )
            )
        return tuple(candidates)


def _parse_memories(path: Path) -> tuple[_Candidate, ...]:
    expected = {
        "id", "kind", "content", "source", "citation", "created_at", "updated_at",
        "salience", "session_id", "task_id", "category", "memory_key", "metadata_json",
        "content_hash", "access_count", "last_accessed_at",
    }
    with _readonly_database(path) as connection:
        versions = connection.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchall()
        if len(versions) != 1 or int(versions[0][0]) != 1:
            raise BackfillSourceError("memory snapshot schema version is unsupported")
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='memories'"
        ).fetchall()
        if len(table_sql) != 1 or _normalized_ddl(table_sql[0][0]) != _MEMORY_TABLE_DDL:
            raise BackfillSourceError("memory table DDL/CHECK contract is invalid")
        if _columns(connection, "memories") != expected:
            raise BackfillSourceError("memory snapshot schema is hybrid or malformed")
        if (
            _column_contract(connection, "memories", "id") != ("TEXT", 0, 1)
            or _column_contract(connection, "memories", "content_hash") != ("TEXT", 1, 0)
            or ("kind", "source", "content_hash")
            not in _unique_indexes(connection, "memories")
        ):
            raise BackfillSourceError("memory semantic schema contract is invalid")
        output = []
        for row in connection.execute("SELECT * FROM memories ORDER BY id"):
            memory_id = _source_id(row["id"], "memory")
            if row["kind"] not in {"semantic", "episodic"}:
                raise BackfillSourceError("memory kind is invalid")
            try:
                salience = float(row["salience"])
            except (TypeError, ValueError, OverflowError) as exc:
                raise BackfillSourceError("memory salience is invalid") from exc
            if not math.isfinite(salience) or not 0.0 <= salience <= 1.0:
                raise BackfillSourceError("memory salience is outside the valid range")
            if type(row["access_count"]) is not int or row["access_count"] < 0:
                raise BackfillSourceError("memory access_count is invalid")
            content = _memory_text(row, "content", 4000)
            source = _memory_text(row, "source", 240)
            _memory_text(row, "citation", 300)
            _memory_text(row, "created_at", 80)
            _memory_text(row, "updated_at", 80)
            category = _memory_text(row, "category", 240, optional=True)
            memory_key = _memory_text(row, "memory_key", 240, optional=True)
            _memory_text(row, "session_id", 240, optional=True)
            _memory_text(row, "task_id", 240, optional=True)
            _memory_text(row, "last_accessed_at", 80, optional=True)
            identity = f"{content.casefold()}\0{category or ''}\0{memory_key or ''}"
            content_hash = hashlib.sha256(identity.encode()).hexdigest()
            stable_id = "mem_" + hashlib.sha256(
                f"{row['kind']}\0{source}\0{content_hash}".encode()
            ).hexdigest()[:24]
            if row["content_hash"] != content_hash or memory_id != stable_id:
                raise BackfillSourceError("memory content hash or deterministic ID is invalid")
            try:
                metadata = json.loads(str(row["metadata_json"]))
            except (TypeError, ValueError) as exc:
                raise BackfillSourceError("memory metadata_json is invalid") from exc
            if not isinstance(metadata, dict):
                raise BackfillSourceError("memory metadata_json must be an object")
            logical = {
                key: row[key]
                for key in (
                    "id", "kind", "content", "source", "citation", "created_at",
                    "updated_at", "salience", "session_id", "task_id", "category",
                    "memory_key", "content_hash",
                )
            }
            logical["metadata_json"] = _json(metadata)
            logical_hash = hashlib.sha256(_json(logical).encode()).hexdigest()
            output.append(
                _Candidate(
                    "memory",
                    memory_id,
                    1,
                    logical_hash,
                    "workspace_assignment_ambiguous",
                    False,
                )
            )
        return tuple(output)


def _lease_window() -> tuple[str, str]:
    heartbeat = datetime.now(timezone.utc)
    expires = heartbeat + timedelta(seconds=BACKFILL_LEASE_SECONDS)
    return heartbeat.isoformat(), expires.isoformat()


class _BackfillHeartbeat:
    def __init__(self, path: Path, run_id: str, owner: str, epoch: int):
        self.path = path
        self.run_id = run_id
        self.owner = owner
        self.epoch = epoch
        self._stop = threading.Event()
        self._lost = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(max(2.0, BACKFILL_HEARTBEAT_SECONDS * 2))
        if self._thread.is_alive():
            raise BackfillConflict("backfill heartbeat did not stop")
        if self._lost.is_set():
            raise BackfillConflict("backfill lease ownership was lost")

    def _run(self) -> None:
        interval = max(0.05, BACKFILL_HEARTBEAT_SECONDS)
        while not self._stop.wait(interval):
            connection: sqlite3.Connection | None = None
            try:
                connection = sqlite3.connect(
                    f"{self.path.as_uri()}?mode=rw",
                    uri=True,
                    timeout=max(1.0, interval),
                    isolation_level=None,
                )
                heartbeat, expires = _lease_window()
                changed = connection.execute(
                    "UPDATE backfill_runs SET heartbeat_at=?,lease_expires_at=? "
                    "WHERE run_id=? AND lease_owner=? AND lease_epoch=? "
                    "AND status IN ('started','applied_unverified')",
                    (heartbeat, expires, self.run_id, self.owner, self.epoch),
                ).rowcount
                if changed != 1:
                    self._lost.set()
                    return
            except sqlite3.DatabaseError:
                # A main-thread BEGIN IMMEDIATE transaction itself fences takeover.
                continue
            finally:
                if connection is not None:
                    connection.close()


class LegacyContextBackfill:
    def __init__(
        self,
        registry: WorkspaceRegistry,
        adapter: LegacyWorkspaceAdapter,
        reader: LegacySnapshotReader,
        *,
        enabled: bool | None = None,
    ):
        if enabled is not None and type(enabled) is not bool:
            raise TypeError("enabled must be bool or None")
        self.registry = registry
        self.adapter = adapter
        self.reader = reader
        self.enabled = m1b_backfill_enabled() if enabled is None else enabled
        self._lock = threading.RLock()

    def _before_source_recheck(self) -> None:
        pass

    def _before_readback(self) -> None:
        pass

    @staticmethod
    def _candidate_id(source_identity: str, candidate: _Candidate) -> str:
        digest = hashlib.sha256(
            f"{candidate.source_kind}\0{source_identity}\0{candidate.source_id}".encode()
        ).hexdigest()
        return "legacy-candidate-" + digest

    def _record_failed(self, run_id: str, owner: str, epoch: int, reason: str) -> None:
        connection = self.registry._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE backfill_runs SET status='failed',completed_at=?,payload_json=? "
                "WHERE run_id=? AND lease_owner=? AND lease_epoch=? AND status!='verified'",
                (_now(), _json({"failure": reason[:500]}), run_id, owner, epoch),
            ).rowcount
            if changed != 1:
                raise BackfillConflict("backfill failure writer lost its lease fence")
            connection.execute("COMMIT")
        except (sqlite3.DatabaseError, BackfillConflict):
            if connection.in_transaction:
                connection.execute("ROLLBACK")

    def _readback(self, run_id: str) -> tuple[int, int, str]:
        self._before_readback()
        uri = f"{self.registry.store.path.as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise BackfillConflict("sidecar read-back integrity failed")
            connection.execute("PRAGMA foreign_keys=ON")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise BackfillConflict("sidecar read-back foreign-key check failed")
            candidates = connection.execute(
                "SELECT candidate_id,source_kind,source_identity,source_id,"
                "source_schema_version,logical_hash,run_id,status,reason,workspace_id,"
                "created_at,updated_at "
                "FROM legacy_backfill_candidates WHERE run_id=? ORDER BY candidate_id",
                (run_id,),
            ).fetchall()
            contexts = connection.execute(
                "SELECT mission_id,workspace_id,schema_version,operational_phase,payload_json,"
                "created_at,updated_at "
                "FROM mission_contexts WHERE json_extract(payload_json,'$.run_id')=? "
                "ORDER BY mission_id",
                (run_id,),
            ).fetchall()
            digest = hashlib.sha256(
                _json({"candidates": candidates, "contexts": contexts}).encode()
            ).hexdigest()
            return len(candidates), len(contexts), digest
        finally:
            connection.close()

    def _expected_readback(
        self,
        snapshot: LegacySnapshot,
        workspace: WorkspaceRecord,
        run_id: str,
        started: str,
    ) -> tuple[int, int, str, int, int, int]:
        candidates: list[tuple[object, ...]] = []
        contexts: list[tuple[object, ...]] = []
        assigned = pending_missions = pending_memories = 0
        for candidate in (*snapshot.missions, *snapshot.memories):
            identity = (
                snapshot.mission_identity
                if candidate.source_kind == "mission"
                else snapshot.memory_identity
            )
            target_status = "assigned" if candidate.assignable else "pending_review"
            target_workspace = workspace.workspace_id if candidate.assignable else None
            candidates.append(
                (
                    self._candidate_id(identity, candidate),
                    candidate.source_kind,
                    identity,
                    candidate.source_id,
                    candidate.schema_version,
                    candidate.logical_hash,
                    run_id,
                    target_status,
                    candidate.reason,
                    target_workspace,
                    started,
                    started,
                )
            )
            if candidate.source_kind == "mission" and candidate.assignable:
                payload = _json(
                    {
                        "assignment": "legacy_adapter_authorized",
                        "logical_hash": candidate.logical_hash,
                        "run_id": run_id,
                        "source_id": candidate.source_id,
                    }
                )
                contexts.append(
                    (
                        candidate.source_id,
                        workspace.workspace_id,
                        BACKFILL_SCHEMA_VERSION,
                        "LEGACY_BACKFILLED",
                        payload,
                        started,
                        started,
                    )
                )
                assigned += 1
            elif candidate.source_kind == "mission":
                pending_missions += 1
            else:
                pending_memories += 1
        candidates.sort(key=lambda row: str(row[0]))
        contexts.sort(key=lambda row: str(row[0]))
        digest = hashlib.sha256(
            _json({"candidates": candidates, "contexts": contexts}).encode()
        ).hexdigest()
        return (
            len(candidates),
            len(contexts),
            digest,
            assigned,
            pending_missions,
            pending_memories,
        )

    @staticmethod
    def _run_row_hash(row: tuple[object, ...], result: Mapping[str, object]) -> str:
        if len(row) != 15:
            raise BackfillConflict("backfill run row width is invalid")
        auditable = [value for index, value in enumerate(row) if index != 10]
        return hashlib.sha256(
            _json({"run": auditable, "result": dict(result)}).encode()
        ).hexdigest()

    @classmethod
    def _sealed_payload(
        cls,
        row: tuple[object, ...],
        result: BackfillResult,
        completed_at: str,
        readback_hash: str,
    ) -> str:
        if len(row) != 15:
            raise BackfillConflict("backfill run row width is invalid")
        sealed_row = list(row)
        sealed_row[2] = "verified"
        sealed_row[8] = completed_at
        sealed_row[9] = readback_hash
        sealed_row[10] = None
        saved = asdict(result)
        return _json(
            {
                "result": saved,
                "run_row_hash": cls._run_row_hash(tuple(sealed_row), saved),
            }
        )

    @staticmethod
    def _verified_time(value: object, label: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value))
            if parsed.tzinfo is None:
                raise ValueError("timezone is missing")
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError) as exc:
            raise BackfillConflict(f"verified backfill {label} is invalid") from exc

    def _verified_replay(
        self,
        row: tuple[object, ...],
        snapshot: LegacySnapshot,
        workspace: WorkspaceRecord,
    ) -> BackfillResult:
        if len(row) != 15 or row[0] != (
            "m1b-backfill-"
            + hashlib.sha256(
                f"{snapshot.mission_hash}\0{snapshot.memory_hash}".encode()
            ).hexdigest()
        ):
            raise BackfillConflict("verified backfill run identity diverges")
        if row[1] != BACKFILL_SCHEMA_VERSION or row[2] != "verified":
            raise BackfillConflict("verified backfill schema/status is invalid")
        self._assert_run_sources(row, snapshot)
        try:
            payload = json.loads(str(row[10]))
            saved = payload["result"]
            recorded_run_hash = payload["run_row_hash"]
        except (KeyError, TypeError, ValueError) as exc:
            raise BackfillConflict("verified backfill payload is invalid") from exc
        if (
            not isinstance(payload, dict)
            or set(payload) != {"result", "run_row_hash"}
            or not isinstance(saved, dict)
            or not isinstance(recorded_run_hash, str)
        ):
            raise BackfillConflict("verified backfill payload contract is invalid")
        if self._run_row_hash(row, saved) != recorded_run_hash:
            raise BackfillConflict("verified backfill run-row digest diverges")
        started = self._verified_time(row[7], "started_at")
        completed = self._verified_time(row[8], "completed_at")
        heartbeat = self._verified_time(row[13], "heartbeat_at")
        expires = self._verified_time(row[12], "lease_expires_at")
        if completed < started or expires < heartbeat:
            raise BackfillConflict("verified backfill time ordering is invalid")
        if not isinstance(row[11], str) or not re.fullmatch(
            r"m1b-owner-[0-9a-f]{32}", row[11]
        ):
            raise BackfillConflict("verified backfill lease owner is invalid")
        if type(row[14]) is not int or row[14] < 1:
            raise BackfillConflict("verified backfill lease epoch is invalid")
        run_id = str(row[0])
        candidate_count, context_count, readback_hash = self._readback(run_id)
        expected = self._expected_readback(snapshot, workspace, run_id, str(row[7]))
        expected_result = {
            "run_id": run_id,
            "status": "verified",
            "mission_scanned": len(snapshot.missions),
            "mission_assigned": expected[3],
            "mission_pending": expected[4],
            "memory_scanned": len(snapshot.memories),
            "memory_assigned": 0,
            "memory_pending": expected[5],
            "candidate_read_back": expected[0],
            "context_read_back": expected[1],
            "readback_hash": expected[2],
        }
        if (
            (candidate_count, context_count, readback_hash) != expected[:3]
            or row[9] != readback_hash
            or any(saved.get(key) != value for key, value in expected_result.items())
            or type(saved.get("idempotent_replay")) is not bool
        ):
            raise BackfillConflict("verified backfill replay read-back diverges")
        return BackfillResult(**{**saved, "idempotent_replay": True})

    def _wait_for_terminal_run(
        self,
        run_id: str,
        snapshot: LegacySnapshot,
        workspace: WorkspaceRecord,
    ) -> BackfillResult:
        connection = self.registry._connection()
        for _attempt in range(100):
            concurrent = connection.execute(
                f"SELECT {_BACKFILL_RUN_SELECT} FROM backfill_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if concurrent is not None and concurrent[2] == "verified":
                return self._verified_replay(tuple(concurrent), snapshot, workspace)
            if concurrent is not None and concurrent[2] == "failed":
                raise BackfillConflict("concurrent backfill failed")
            if concurrent is not None and concurrent[2] not in {
                "started",
                "applied_unverified",
            }:
                raise BackfillConflict(
                    f"concurrent backfill has invalid status {concurrent[2]}"
                )
            time.sleep(0.05)
        raise BackfillConflict("concurrent backfill did not reach a terminal state")

    @staticmethod
    def _lease_is_expired(expires_at: object) -> bool:
        try:
            expires = datetime.fromisoformat(str(expires_at))
            if expires.tzinfo is None:
                raise ValueError("timezone is missing")
        except (TypeError, ValueError, OverflowError) as exc:
            raise BackfillConflict("backfill run has an invalid lease expiry") from exc
        return datetime.now(timezone.utc) >= expires.astimezone(timezone.utc)

    @staticmethod
    def _assert_run_sources(prior: tuple[object, ...], snapshot: LegacySnapshot) -> None:
        expected = (
            snapshot.mission_identity,
            snapshot.mission_hash,
            snapshot.memory_identity,
            snapshot.memory_hash,
        )
        if tuple(prior[3:7]) != expected:
            raise BackfillConflict("stale backfill source identity/hash diverges")

    def _recover_stale_applied(
        self,
        run_id: str,
        snapshot: LegacySnapshot,
        workspace: WorkspaceRecord,
        started: str,
        owner: str,
        epoch: int,
    ) -> BackfillResult:
        lease = _BackfillHeartbeat(self.registry.store.path, run_id, owner, epoch)
        lease.start()
        try:
            if not self.reader.unchanged(snapshot):
                raise BackfillSourceError("legacy source changed before stale recovery")
            candidate_count, context_count, readback_hash = self._readback(run_id)
            expected = self._expected_readback(snapshot, workspace, run_id, started)
            if (candidate_count, context_count, readback_hash) != expected[:3]:
                raise BackfillConflict("stale applied backfill read-back diverges")
        finally:
            lease.stop()
        result = BackfillResult(
            run_id,
            "verified",
            len(snapshot.missions),
            expected[3],
            expected[4],
            len(snapshot.memories),
            0,
            expected[5],
            candidate_count,
            context_count,
            readback_hash,
            True,
        )
        connection = self.registry._connection()
        connection.execute("BEGIN IMMEDIATE")
        try:
            current = connection.execute(
                f"SELECT {_BACKFILL_RUN_SELECT} FROM backfill_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if (
                current is None
                or current[2] != "applied_unverified"
                or current[7] != started
                or current[11] != owner
                or current[14] != epoch
            ):
                raise BackfillConflict("stale applied backfill changed during recovery")
            self._assert_run_sources(tuple(current), snapshot)
            completed_at = _now()
            payload = self._sealed_payload(
                tuple(current), result, completed_at, readback_hash
            )
            changed = connection.execute(
                "UPDATE backfill_runs SET status='verified',completed_at=?,readback_hash=?,"
                "payload_json=? WHERE run_id=? AND status='applied_unverified' AND started_at=? "
                "AND lease_owner=? AND lease_epoch=?",
                (
                    completed_at,
                    readback_hash,
                    payload,
                    run_id,
                    started,
                    owner,
                    epoch,
                ),
            ).rowcount
            if changed != 1:
                raise BackfillConflict("stale applied backfill changed during recovery")
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        return result

    def _take_over_stale_started(
        self,
        run_id: str,
        snapshot: LegacySnapshot,
        prior_started: str,
        owner: str,
        epoch: int,
    ) -> str:
        candidate_count, context_count, _digest = self._readback(run_id)
        if candidate_count or context_count:
            raise BackfillConflict("stale started backfill contains unexpected sidecar rows")
        replacement_started = _now()
        manifest = _json({"manifest": [asdict(item) for item in snapshot.manifest]})
        connection = self.registry._connection()
        connection.execute("BEGIN IMMEDIATE")
        try:
            changed = connection.execute(
                "UPDATE backfill_runs SET started_at=?,completed_at=NULL,readback_hash=NULL,"
                "payload_json=? WHERE run_id=? AND status='started' AND started_at=? "
                "AND lease_owner=? AND lease_epoch=?",
                (replacement_started, manifest, run_id, prior_started, owner, epoch),
            ).rowcount
            if changed != 1:
                raise BackfillConflict("stale started backfill changed during takeover")
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        return replacement_started

    def _claim_expired_run(
        self, run_id: str, prior: tuple[object, ...], owner: str
    ) -> int:
        prior_owner = str(prior[11])
        prior_expiry = str(prior[12])
        prior_epoch = int(prior[14])
        heartbeat, expires = _lease_window()
        connection = self.registry._connection()
        connection.execute("BEGIN IMMEDIATE")
        try:
            changed = connection.execute(
                "UPDATE backfill_runs SET lease_owner=?,heartbeat_at=?,lease_expires_at=?,"
                "lease_epoch=lease_epoch+1 WHERE run_id=? AND status=? AND lease_owner=? "
                "AND lease_epoch=? AND lease_expires_at=?",
                (
                    owner,
                    heartbeat,
                    expires,
                    run_id,
                    prior[2],
                    prior_owner,
                    prior_epoch,
                    prior_expiry,
                ),
            ).rowcount
            if changed != 1:
                raise BackfillConflict("expired backfill lease changed during takeover")
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        return prior_epoch + 1

    def run(self) -> BackfillResult:
        if not self.enabled:
            raise BackfillDisabled(f"{M1B_BACKFILL_FLAG} is disabled")
        workspace = self.adapter.resolve()
        snapshot_root = self.registry.store.path.parent / ".m1b-snapshots"
        with self._lock, self.reader.capture(snapshot_root) as snapshot:
            run_id = "m1b-backfill-" + hashlib.sha256(
                f"{snapshot.mission_hash}\0{snapshot.memory_hash}".encode()
            ).hexdigest()
            owner = "m1b-owner-" + secrets.token_hex(16)
            epoch = 1
            connection = self.registry._connection()
            prior = connection.execute(
                f"SELECT {_BACKFILL_RUN_SELECT} FROM backfill_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            started: str | None = None
            lease: _BackfillHeartbeat | None = None
            if prior is not None:
                if prior[2] == "verified":
                    return self._verified_replay(tuple(prior), snapshot, workspace)
                if prior[2] in {"started", "applied_unverified"}:
                    if not self._lease_is_expired(prior[12]):
                        return self._wait_for_terminal_run(run_id, snapshot, workspace)
                    self._assert_run_sources(tuple(prior), snapshot)
                    epoch = self._claim_expired_run(run_id, tuple(prior), owner)
                    if prior[2] == "applied_unverified":
                        return self._recover_stale_applied(
                            run_id,
                            snapshot,
                            workspace,
                            str(prior[7]),
                            owner,
                            epoch,
                        )
                    lease = _BackfillHeartbeat(
                        self.registry.store.path, run_id, owner, epoch
                    )
                    lease.start()
                    try:
                        started = self._take_over_stale_started(
                            run_id, snapshot, str(prior[7]), owner, epoch
                        )
                    except Exception:
                        lease.stop()
                        raise
                else:
                    raise BackfillConflict(f"prior backfill run is {prior[2]}")
            if started is None:
                started = _now()
                heartbeat_at, lease_expires_at = _lease_window()
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        "INSERT INTO backfill_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            run_id,
                            BACKFILL_SCHEMA_VERSION,
                            "started",
                            snapshot.mission_identity,
                            snapshot.mission_hash,
                            snapshot.memory_identity,
                            snapshot.memory_hash,
                            started,
                            None,
                            None,
                            _json({"manifest": [asdict(item) for item in snapshot.manifest]}),
                            owner,
                            lease_expires_at,
                            heartbeat_at,
                            epoch,
                        ),
                    )
                    connection.execute("COMMIT")
                except sqlite3.IntegrityError:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    return self._wait_for_terminal_run(run_id, snapshot, workspace)
            if lease is None:
                lease = _BackfillHeartbeat(
                    self.registry.store.path, run_id, owner, epoch
                )
                lease.start()
            lease_stopped = False
            try:
                connection.execute("BEGIN IMMEDIATE")
                fence = connection.execute(
                    "SELECT status,lease_owner,lease_epoch FROM backfill_runs WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                if fence is None or tuple(fence) != ("started", owner, epoch):
                    raise BackfillConflict("backfill worker lost its lease fence before staging")
                assigned = pending_missions = pending_memories = 0
                for candidate in (*snapshot.missions, *snapshot.memories):
                    identity = (
                        snapshot.mission_identity
                        if candidate.source_kind == "mission"
                        else snapshot.memory_identity
                    )
                    candidate_id = self._candidate_id(identity, candidate)
                    existing = connection.execute(
                        "SELECT source_schema_version,logical_hash,status,reason,workspace_id "
                        "FROM legacy_backfill_candidates WHERE candidate_id=?",
                        (candidate_id,),
                    ).fetchone()
                    target_status = "assigned" if candidate.assignable else "pending_review"
                    target_workspace = workspace.workspace_id if candidate.assignable else None
                    expected = (
                        candidate.schema_version,
                        candidate.logical_hash,
                        target_status,
                        candidate.reason,
                        target_workspace,
                    )
                    if existing is not None and tuple(existing) != expected:
                        raise BackfillConflict("candidate replay diverges from staged state")
                    if existing is None:
                        connection.execute(
                            "INSERT INTO legacy_backfill_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                candidate_id,
                                candidate.source_kind,
                                identity,
                                candidate.source_id,
                                candidate.schema_version,
                                candidate.logical_hash,
                                run_id,
                                target_status,
                                candidate.reason,
                                target_workspace,
                                started,
                                started,
                            ),
                        )
                    if candidate.source_kind == "mission" and candidate.assignable:
                        payload = _json(
                            {
                                "assignment": "legacy_adapter_authorized",
                                "logical_hash": candidate.logical_hash,
                                "run_id": run_id,
                                "source_id": candidate.source_id,
                            }
                        )
                        existing_context = connection.execute(
                            "SELECT workspace_id,operational_phase,payload_json FROM mission_contexts "
                            "WHERE mission_id=?",
                            (candidate.source_id,),
                        ).fetchone()
                        expected_context = (workspace.workspace_id, "LEGACY_BACKFILLED", payload)
                        if existing_context is not None and tuple(existing_context) != expected_context:
                            raise BackfillConflict("mission context conflicts with legacy assignment")
                        if existing_context is None:
                            connection.execute(
                                "INSERT INTO mission_contexts VALUES(?,?,?,?,?,?,?)",
                                (
                                    candidate.source_id,
                                    workspace.workspace_id,
                                    BACKFILL_SCHEMA_VERSION,
                                    "LEGACY_BACKFILLED",
                                    payload,
                                    started,
                                    started,
                                ),
                            )
                        assigned += 1
                    elif candidate.source_kind == "mission":
                        pending_missions += 1
                    else:
                        pending_memories += 1
                self._before_source_recheck()
                if not self.reader.unchanged(snapshot):
                    raise BackfillSourceError("legacy source family changed before sidecar commit")
                provisional = {
                    "run_id": run_id,
                    "status": "applied_unverified",
                    "mission_scanned": len(snapshot.missions),
                    "mission_assigned": assigned,
                    "mission_pending": pending_missions,
                    "memory_scanned": len(snapshot.memories),
                    "memory_assigned": 0,
                    "memory_pending": pending_memories,
                    "candidate_read_back": 0,
                    "context_read_back": 0,
                    "readback_hash": "",
                    "idempotent_replay": False,
                }
                heartbeat_at, lease_expires_at = _lease_window()
                changed = connection.execute(
                    "UPDATE backfill_runs SET status='applied_unverified',completed_at=?,"
                    "payload_json=?,heartbeat_at=?,lease_expires_at=? "
                    "WHERE run_id=? AND status='started' AND lease_owner=? AND lease_epoch=?",
                    (
                        _now(),
                        _json({"result": provisional}),
                        heartbeat_at,
                        lease_expires_at,
                        run_id,
                        owner,
                        epoch,
                    ),
                ).rowcount
                if changed != 1:
                    raise BackfillConflict("backfill worker lost its lease fence at staging commit")
                connection.execute("COMMIT")
                candidate_count, context_count, readback_hash = self._readback(run_id)
                expected = self._expected_readback(
                    snapshot, workspace, run_id, started
                )
                if (
                    (candidate_count, context_count, readback_hash) != expected[:3]
                    or (assigned, pending_missions, pending_memories) != expected[3:]
                ):
                    raise BackfillConflict("sidecar read-back content diverges")
                lease.stop()
                lease_stopped = True
                result = BackfillResult(
                    run_id,
                    "verified",
                    len(snapshot.missions),
                    assigned,
                    pending_missions,
                    len(snapshot.memories),
                    0,
                    pending_memories,
                    candidate_count,
                    context_count,
                    readback_hash,
                    False,
                )
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    f"SELECT {_BACKFILL_RUN_SELECT} FROM backfill_runs WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                if (
                    current is None
                    or current[2] != "applied_unverified"
                    or current[7] != started
                    or current[11] != owner
                    or current[14] != epoch
                ):
                    raise BackfillConflict(
                        "backfill verification state changed concurrently"
                    )
                self._assert_run_sources(tuple(current), snapshot)
                completed_at = _now()
                payload = self._sealed_payload(
                    tuple(current), result, completed_at, readback_hash
                )
                changed = connection.execute(
                    "UPDATE backfill_runs SET status='verified',completed_at=?,readback_hash=?,"
                    "payload_json=? WHERE run_id=? AND status='applied_unverified' "
                    "AND lease_owner=? AND lease_epoch=?",
                    (
                        completed_at,
                        readback_hash,
                        payload,
                        run_id,
                        owner,
                        epoch,
                    ),
                ).rowcount
                if changed != 1:
                    raise BackfillConflict("backfill verification state changed concurrently")
                connection.execute("COMMIT")
                return result
            except Exception as exc:
                failure: Exception = exc
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                if not lease_stopped:
                    try:
                        lease.stop()
                    except Exception as lease_exc:
                        failure = lease_exc
                self._record_failed(run_id, owner, epoch, str(failure))
                if isinstance(failure, (WorkspaceError, ControlPlaneError)):
                    raise failure
                if isinstance(failure, sqlite3.DatabaseError):
                    raise BackfillConflict(
                        f"backfill database failure: {failure}"
                    ) from failure
                raise failure


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reviewed opt-in Onyx M1b backfill")
    parser.add_argument("--confirm-host-owned-legacy", action="store_true")
    arguments = parser.parse_args(argv)
    if not arguments.confirm_host_owned_legacy:
        parser.error("--confirm-host-owned-legacy is required")
    marker = _HOST_MARKER
    store = ControlPlaneStore()
    registry = WorkspaceRegistry(store)
    with registry:
        adapter = LegacyWorkspaceAdapter(registry, marker)
        reader = LegacySnapshotReader(_host_owned_source_paths(marker), marker)
        result = LegacyContextBackfill(registry, adapter, reader).run()
    print(_json(asdict(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
