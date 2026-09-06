"""Evidence-backed site/project lifecycle projection.

This projection never runs a shell, build, preview server, Git command or
publisher.  It binds each lifecycle operation to one immutable Phase 6
plan/mission and advances only from verified receipts.  Project paths must be
real descendants of explicitly supplied controlled workspace roots.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

from core.missions import MissionStore
from core.phase6_agentic_core_v1 import PlanStateV1
from core.phase6_agentic_core_v6 import AgenticStateStoreV6, normalized_sql_v6


SCHEMA_VERSION = 1
FEATURE_FLAG = "ONYX_SITE_PROJECTS_V1"
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,191}")


class SiteProjectError(RuntimeError):
    pass


class SiteProjectContractError(ValueError):
    pass


class SiteProjectDenied(PermissionError):
    pass


class SiteOperationV1(str, Enum):
    BUILD = "build"
    PREVIEW = "preview"
    PUBLISH = "publish"


class SiteStageV1(str, Enum):
    DRAFT = "draft"
    BUILT = "built"
    PREVIEW_READY = "preview_ready"
    PUBLISHED = "published"
    ARCHIVED = "archived"


_REQUIRED_POSTCONDITIONS: dict[SiteOperationV1, str] = {
    SiteOperationV1.BUILD: "site_build_verified",
    SiteOperationV1.PREVIEW: "site_preview_verified",
    SiteOperationV1.PUBLISH: "site_publish_verified",
}
_EXPECTED_STAGE: dict[SiteOperationV1, SiteStageV1] = {
    SiteOperationV1.BUILD: SiteStageV1.DRAFT,
    SiteOperationV1.PREVIEW: SiteStageV1.BUILT,
    SiteOperationV1.PUBLISH: SiteStageV1.PREVIEW_READY,
}
_NEXT_STAGE: dict[SiteOperationV1, SiteStageV1] = {
    SiteOperationV1.BUILD: SiteStageV1.BUILT,
    SiteOperationV1.PREVIEW: SiteStageV1.PREVIEW_READY,
    SiteOperationV1.PUBLISH: SiteStageV1.PUBLISHED,
}


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise SiteProjectContractError(f"{label} is invalid")
    return value


def _canonical_json(value: object) -> str:
    try:
        result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise SiteProjectContractError("value is not canonical JSON") from exc
    if len(result.encode()) > 65_536:
        raise SiteProjectContractError("value exceeds its byte budget")
    return result


def _private_path(path: Path) -> None:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise SiteProjectContractError("an explicit absolute database path is required")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise SiteProjectDenied("linked site projection directory is forbidden")
    attributes = getattr(path.parent.stat(), "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if attributes & reparse:
        raise SiteProjectDenied("reparse-point site projection directory is forbidden")
    if path.exists() and path.is_symlink():
        raise SiteProjectDenied("linked site projection database is forbidden")


def _operation(value: SiteOperationV1) -> SiteOperationV1:
    if type(value) is not SiteOperationV1:
        raise SiteProjectContractError("exact SiteOperationV1 is required")
    return value


def _conditions(values: Sequence[str]) -> tuple[str, ...]:
    if type(values) not in {tuple, list} or not 1 <= len(values) <= 16:
        raise SiteProjectContractError("required postconditions are invalid")
    result = tuple(_identifier(item, "postcondition") for item in values)
    if len(set(result)) != len(result):
        raise SiteProjectContractError("postconditions are not canonical")
    return result


def _controlled_root(candidate: Path, roots: tuple[Path, ...]) -> Path:
    if not candidate.is_absolute():
        raise SiteProjectContractError("project root must be absolute")
    try:
        original = candidate.absolute()
        if original.is_symlink():
            raise SiteProjectDenied("linked project root is forbidden")
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise SiteProjectDenied("project root is unavailable") from exc
    if not resolved.is_dir():
        raise SiteProjectDenied("project root must be a directory")
    matched: Path | None = None
    for root in roots:
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            continue
        if not relative.parts:
            continue
        matched = root
        cursor = root
        for part in relative.parts:
            cursor = cursor / part
            info = cursor.lstat()
            attributes = getattr(info, "st_file_attributes", 0)
            reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if stat.S_ISLNK(info.st_mode) or attributes & reparse:
                raise SiteProjectDenied("linked project path component is forbidden")
        break
    if matched is None:
        raise SiteProjectDenied("project root is outside controlled workspaces")
    return resolved


@dataclass(frozen=True)
class SiteProjectFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise SiteProjectContractError("enabled must be an exact boolean")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "SiteProjectFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True)
class SiteProjectV1:
    project_id: str
    owner_profile_id: str
    workspace_id: str
    repository_id: str
    root: str
    stage: SiteStageV1
    revision: int
    verification_digest: str | None


@dataclass(frozen=True)
class SiteOperationBindingV1:
    binding_id: str
    project_id: str
    operation: SiteOperationV1
    plan_id: str
    mission_id: str
    required_postconditions: tuple[str, ...]
    status: str
    verification_digest: str | None


class SiteProjectStoreV1:
    _DDL = (
        """CREATE TABLE metadata(schema_version INTEGER NOT NULL CHECK(schema_version=1))""",
        """CREATE TABLE site_projects(
          project_id TEXT PRIMARY KEY,
          owner_profile_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL,
          repository_id TEXT NOT NULL,
          root TEXT NOT NULL UNIQUE,
          stage TEXT NOT NULL CHECK(stage IN
            ('draft','built','preview_ready','published','archived')),
          revision INTEGER NOT NULL CHECK(revision>=1),
          verification_digest TEXT,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL
        )""",
        """CREATE TABLE site_operations(
          binding_id TEXT PRIMARY KEY,
          project_id TEXT NOT NULL REFERENCES site_projects(project_id),
          operation TEXT NOT NULL CHECK(operation IN ('build','preview','publish')),
          plan_id TEXT NOT NULL UNIQUE,
          mission_id TEXT NOT NULL UNIQUE,
          required_json TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('bound','verified','cancelled')),
          verification_digest TEXT,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          UNIQUE(project_id,operation,status)
        )""",
        """CREATE TABLE site_project_events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          entity_id TEXT NOT NULL,
          timestamp REAL NOT NULL,
          event TEXT NOT NULL,
          detail_json TEXT NOT NULL,
          prev_hash TEXT NOT NULL,
          event_hash TEXT NOT NULL UNIQUE
        )""",
        """CREATE INDEX idx_site_projects_scope
          ON site_projects(owner_profile_id,workspace_id,stage)""",
        """CREATE TRIGGER site_project_events_no_update BEFORE UPDATE ON site_project_events
          BEGIN SELECT RAISE(ABORT,'site project events are immutable'); END""",
        """CREATE TRIGGER site_project_events_no_delete BEFORE DELETE ON site_project_events
          BEGIN SELECT RAISE(ABORT,'site project events are immutable'); END""",
    )

    def __init__(
        self,
        path: Path | str,
        gate: SiteProjectFeatureGateV1,
        *,
        controlled_roots: Sequence[Path | str],
    ) -> None:
        if type(gate) is not SiteProjectFeatureGateV1 or not gate.enabled:
            raise SiteProjectDenied("site projects are disabled")
        if type(controlled_roots) not in {tuple, list} or not controlled_roots:
            raise SiteProjectContractError("controlled_roots are required")
        roots: list[Path] = []
        for value in controlled_roots:
            root = Path(value)
            if not root.is_absolute():
                raise SiteProjectContractError("controlled roots must be absolute")
            try:
                resolved = root.resolve(strict=True)
            except OSError as exc:
                raise SiteProjectDenied("controlled root is unavailable") from exc
            if not resolved.is_dir() or root.is_symlink():
                raise SiteProjectDenied("controlled root must be a real directory")
            roots.append(resolved)
        self.path = Path(path)
        _private_path(self.path)
        self._roots = tuple(roots)
        self._lock = threading.RLock()
        self._expected_signature = self._build_expected_signature()
        self.initialize()

    @staticmethod
    def execution_boundary() -> dict[str, object]:
        return {
            "shell_executor": None,
            "network_publisher": None,
            "inherited_environment": (),
            "credential_transport": "os_vault_reference_only",
            "execution_authority": "phase6_exact_plan_and_mission",
        }

    @staticmethod
    def _signature(connection: sqlite3.Connection) -> str:
        objects = []
        for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ):
            if row[3] is None:
                raise SiteProjectError("schema object has no stored SQL")
            objects.append((row[0], row[1], row[2], normalized_sql_v6(str(row[3]))))
        details: dict[str, object] = {}
        for table in sorted(row[1] for row in objects if row[0] == "table"):
            details[f"table_xinfo:{table}"] = [
                tuple(item) for item in connection.execute(f"PRAGMA table_xinfo('{table}')")
            ]
            details[f"foreign_key_list:{table}"] = [
                tuple(item) for item in connection.execute(f"PRAGMA foreign_key_list('{table}')")
            ]
        return hashlib.sha256(_canonical_json({"objects": objects, "details": details}).encode()).hexdigest()

    @classmethod
    def _build_expected_signature(cls) -> str:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("PRAGMA foreign_keys=ON")
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
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def initialize(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
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
                    or connection.execute("PRAGMA foreign_key_check").fetchall()
                ):
                    raise SiteProjectError("site-project schema authentication failed")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        entity_id: str,
        event: str,
        detail: Mapping[str, object],
    ) -> None:
        previous = connection.execute(
            "SELECT event_hash FROM site_project_events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev_hash = "0" * 64 if previous is None else str(previous[0])
        timestamp = time.time()
        detail_json = _canonical_json(dict(detail))
        event_hash = hashlib.sha256(_canonical_json({
            "entity_id": entity_id, "timestamp": timestamp, "event": event,
            "detail_json": detail_json, "prev_hash": prev_hash,
        }).encode()).hexdigest()
        connection.execute(
            "INSERT INTO site_project_events(entity_id,timestamp,event,detail_json,prev_hash,event_hash) "
            "VALUES(?,?,?,?,?,?)",
            (entity_id, timestamp, event, detail_json, prev_hash, event_hash),
        )

    @staticmethod
    def _project(row: sqlite3.Row) -> SiteProjectV1:
        return SiteProjectV1(
            str(row["project_id"]), str(row["owner_profile_id"]),
            str(row["workspace_id"]), str(row["repository_id"]), str(row["root"]),
            SiteStageV1(str(row["stage"])), int(row["revision"]),
            None if row["verification_digest"] is None else str(row["verification_digest"]),
        )

    def create(
        self,
        *,
        owner_profile_id: str,
        workspace_id: str,
        repository_id: str,
        root: Path | str,
    ) -> SiteProjectV1:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        repository = _identifier(repository_id, "repository_id")
        controlled = _controlled_root(Path(root), self._roots)
        project_id = "site_" + uuid.uuid4().hex
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO site_projects VALUES(?,?,?,?,?,?,?,?,?,?)",
                (project_id, owner, workspace, repository, str(controlled),
                 SiteStageV1.DRAFT.value, 1, None, now, now),
            )
            self._event(connection, project_id, "site_project.created", {
                "repository_id": repository, "root_digest": hashlib.sha256(str(controlled).encode()).hexdigest(),
            })
            connection.execute("COMMIT")
        return self.get(project_id)

    def get(self, project_id: str) -> SiteProjectV1:
        key = _identifier(project_id, "project_id")
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM site_projects WHERE project_id=?", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return self._project(row)

    def count_scope(self, owner_profile_id: str, workspace_id: str) -> int:
        """Return a scope-bound project count without disclosing local roots."""

        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM site_projects "
                "WHERE owner_profile_id=? AND workspace_id=?",
                (owner, workspace),
            ).fetchone()
        return int(row[0])

    def get_binding(self, binding_id: str) -> SiteOperationBindingV1:
        key = _identifier(binding_id, "binding_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM site_operations WHERE binding_id=?", (key,)
            ).fetchone()
        if row is None:
            raise KeyError(key)
        return SiteOperationBindingV1(
            str(row["binding_id"]),
            str(row["project_id"]),
            SiteOperationV1(str(row["operation"])),
            str(row["plan_id"]),
            str(row["mission_id"]),
            tuple(json.loads(str(row["required_json"]))),
            str(row["status"]),
            None
            if row["verification_digest"] is None
            else str(row["verification_digest"]),
        )

    def bind_operation(
        self,
        project_id: str,
        *,
        operation: SiteOperationV1,
        plan_id: str,
        mission_id: str,
        required_postconditions: Sequence[str] | None = None,
    ) -> SiteOperationBindingV1:
        project = self.get(project_id)
        selected = _operation(operation)
        if project.stage is not _EXPECTED_STAGE[selected]:
            raise SiteProjectDenied("site operation is not valid for the current stage")
        plan = _identifier(plan_id, "plan_id")
        mission = _identifier(mission_id, "mission_id")
        required = _conditions(
            (_REQUIRED_POSTCONDITIONS[selected],)
            if required_postconditions is None else required_postconditions
        )
        if _REQUIRED_POSTCONDITIONS[selected] not in required:
            raise SiteProjectDenied("mandatory operation postcondition is missing")
        binding_id = "site_binding_" + uuid.uuid4().hex
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = self._project(connection.execute(
                "SELECT * FROM site_projects WHERE project_id=?", (project.project_id,)
            ).fetchone())
            if current.revision != project.revision or current.stage is not project.stage:
                raise SiteProjectDenied("site project changed during binding")
            connection.execute(
                "INSERT INTO site_operations VALUES(?,?,?,?,?,?,?,?,?,?)",
                (binding_id, project.project_id, selected.value, plan, mission,
                 _canonical_json(required), "bound", None, now, now),
            )
            self._event(connection, binding_id, "site_operation.bound", {
                "project_id": project.project_id, "operation": selected.value,
                "plan_id": plan, "mission_id": mission,
            })
            connection.execute("COMMIT")
        return SiteOperationBindingV1(
            binding_id, project.project_id, selected, plan, mission, required,
            "bound", None,
        )

    def reconcile_verified(
        self,
        binding_id: str,
        *,
        state_store: AgenticStateStoreV6,
        mission_store: MissionStore,
    ) -> SiteProjectV1:
        if type(state_store) is not AgenticStateStoreV6:
            raise SiteProjectContractError("exact AgenticStateStoreV6 is required")
        if type(mission_store) is not MissionStore:
            raise SiteProjectContractError("exact MissionStore is required")
        key = _identifier(binding_id, "binding_id")
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM site_operations WHERE binding_id=?", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        operation = SiteOperationV1(str(row["operation"]))
        project = self.get(str(row["project_id"]))
        if str(row["status"]) == "verified":
            return project
        if project.stage is not _EXPECTED_STAGE[operation]:
            raise SiteProjectDenied("site project stage diverges from its operation")
        plan_id = str(row["plan_id"])
        mission_id = str(row["mission_id"])
        projection = state_store.get_projection(plan_id)
        if (
            projection.state is not PlanStateV1.COMPLETE
            or projection.mission_id != mission_id
            or projection.mission_plan_digest is None
        ):
            raise SiteProjectDenied("Phase 6 plan is not independently complete")
        mission = mission_store.get(mission_id)
        snapshot = mission_store.authority_snapshot(mission_id)
        if mission.state != "succeeded" or snapshot.state != "succeeded":
            raise SiteProjectDenied("mission authority is not succeeded")
        receipts = state_store.plans.receipts(plan_id)
        if not receipts:
            raise SiteProjectDenied("Phase 6 verification receipts are unavailable")
        event_hashes = {str(item["event_hash"]) for item in mission_store.events(mission_id)}
        observed: set[str] = set()
        receipt_payloads: list[dict[str, object]] = []
        for receipt in receipts:
            if (
                receipt.status != "verified"
                or receipt.plan_id != plan_id
                or receipt.mission_id != mission_id
                or receipt.authority_snapshot_hash != snapshot.snapshot_hash
                or receipt.event_hash not in event_hashes
            ):
                raise SiteProjectDenied("Phase 6 receipt binding diverges")
            observed.update(receipt.postconditions)
            receipt_payloads.append(receipt.payload())
        required = tuple(json.loads(str(row["required_json"])))
        missing = set(required) - observed
        if missing:
            raise SiteProjectDenied(
                "site operation lacks verified postconditions: " + ", ".join(sorted(missing))
            )
        digest = hashlib.sha256(_canonical_json({
            "binding_id": key, "project_id": project.project_id,
            "operation": operation.value, "plan_id": plan_id, "mission_id": mission_id,
            "mission_plan_digest": projection.mission_plan_digest,
            "authority_snapshot_hash": snapshot.snapshot_hash, "receipts": receipt_payloads,
        }).encode()).hexdigest()
        next_stage = _NEXT_STAGE[operation]
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE site_operations SET status='verified',verification_digest=?,updated_at=? "
                "WHERE binding_id=? AND status='bound'",
                (digest, time.time(), key),
            ).rowcount
            if changed != 1:
                raise SiteProjectDenied("site operation changed during reconciliation")
            changed = connection.execute(
                "UPDATE site_projects SET stage=?,revision=revision+1,verification_digest=?,updated_at=? "
                "WHERE project_id=? AND stage=? AND revision=?",
                (next_stage.value, digest, time.time(), project.project_id,
                 project.stage.value, project.revision),
            ).rowcount
            if changed != 1:
                raise SiteProjectDenied("site project changed during reconciliation")
            self._event(connection, key, "site_operation.verified", {
                "operation": operation.value, "stage": next_stage.value,
                "verification_digest": digest,
            })
            connection.execute("COMMIT")
        return self.get(project.project_id)
