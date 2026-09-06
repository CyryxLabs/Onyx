"""Evidence-gated operational goals around the existing Phase 6 authority.

This module is a projection only.  It never plans, authorizes, executes or
approves work.  Completion is derived from the existing Phase 6 V6 plan store
and MissionStore evidence; model text and direct status assignments cannot
complete a goal.
"""

from __future__ import annotations

import hashlib
import json
import math
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
FEATURE_FLAG = "ONYX_OPERATIONAL_GOALS_V1"
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,191}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class OperationalGoalError(RuntimeError):
    """Base error for the operational-goal projection."""


class OperationalGoalContractError(ValueError):
    """A caller supplied a non-canonical goal contract."""


class OperationalGoalDenied(PermissionError):
    """The requested projection change is not authorized by evidence."""


class GoalLevelV1(str, Enum):
    OBJECTIVE = "objective"
    KEY_RESULT = "key_result"
    MILESTONE = "milestone"
    TASK = "task"
    DAILY_ACTION = "daily_action"


class GoalStatusV1(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


_CHILD_LEVEL = {
    GoalLevelV1.OBJECTIVE: GoalLevelV1.KEY_RESULT,
    GoalLevelV1.KEY_RESULT: GoalLevelV1.MILESTONE,
    GoalLevelV1.MILESTONE: GoalLevelV1.TASK,
    GoalLevelV1.TASK: GoalLevelV1.DAILY_ACTION,
}


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise OperationalGoalContractError(f"{label} is invalid")
    return value


def _text(value: object, label: str, maximum: int) -> str:
    if type(value) is not str:
        raise OperationalGoalContractError(f"{label} must be text")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise OperationalGoalContractError(f"{label} is invalid")
    return normalized


def _canonical_json(value: object) -> str:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise OperationalGoalContractError("value is not canonical JSON") from exc
    if len(encoded.encode("utf-8")) > 65_536:
        raise OperationalGoalContractError("value exceeds its byte budget")
    return encoded


def _conditions(values: Sequence[str]) -> tuple[str, ...]:
    if type(values) not in {tuple, list} or not 1 <= len(values) <= 32:
        raise OperationalGoalContractError("definition_of_done is invalid")
    result = tuple(_identifier(item, "definition_of_done item") for item in values)
    if len(set(result)) != len(result):
        raise OperationalGoalContractError("definition_of_done is not canonical")
    return result


def _private_path(path: Path) -> None:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise OperationalGoalContractError("an explicit absolute database path is required")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise OperationalGoalDenied("linked goal directory is forbidden")
    attributes = getattr(path.parent.stat(), "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if attributes & reparse:
        raise OperationalGoalDenied("reparse-point goal directory is forbidden")
    if path.exists() and path.is_symlink():
        raise OperationalGoalDenied("linked goal database is forbidden")


@dataclass(frozen=True)
class OperationalGoalV1:
    goal_id: str
    owner_profile_id: str
    workspace_id: str
    parent_id: str | None
    level: GoalLevelV1
    title: str
    objective: str
    definition_of_done: tuple[str, ...]
    status: GoalStatusV1
    target_at: float | None
    plan_id: str | None
    mission_id: str | None
    verification_digest: str | None
    revision: int
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class GoalProjectionV1:
    goal: OperationalGoalV1
    score: float
    health: str
    children: tuple[str, ...]


@dataclass(frozen=True)
class OperationalGoalFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise OperationalGoalContractError("enabled must be an exact boolean")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "OperationalGoalFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


class OperationalGoalStoreV1:
    """Append-audited goal projection with Phase 6 evidence-gated completion."""

    _DDL = (
        """CREATE TABLE metadata(
          schema_version INTEGER NOT NULL CHECK(schema_version=1)
        )""",
        """CREATE TABLE goals(
          goal_id TEXT PRIMARY KEY,
          owner_profile_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL,
          parent_id TEXT REFERENCES goals(goal_id),
          level TEXT NOT NULL CHECK(level IN
            ('objective','key_result','milestone','task','daily_action')),
          title TEXT NOT NULL,
          objective TEXT NOT NULL,
          definition_json TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN
            ('draft','active','paused','completed','cancelled')),
          target_at REAL,
          plan_id TEXT UNIQUE,
          mission_id TEXT UNIQUE,
          verification_digest TEXT,
          revision INTEGER NOT NULL CHECK(revision>=1),
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL
        )""",
        """CREATE TABLE goal_events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          goal_id TEXT NOT NULL REFERENCES goals(goal_id),
          timestamp REAL NOT NULL,
          event TEXT NOT NULL,
          detail_json TEXT NOT NULL,
          prev_hash TEXT NOT NULL,
          event_hash TEXT NOT NULL UNIQUE
        )""",
        """CREATE INDEX idx_goals_scope
          ON goals(owner_profile_id,workspace_id,status,level)""",
        """CREATE INDEX idx_goal_events_goal
          ON goal_events(goal_id,seq)""",
        """CREATE TRIGGER goal_events_no_update BEFORE UPDATE ON goal_events
          BEGIN SELECT RAISE(ABORT,'goal events are immutable'); END""",
        """CREATE TRIGGER goal_events_no_delete BEFORE DELETE ON goal_events
          BEGIN SELECT RAISE(ABORT,'goal events are immutable'); END""",
    )

    def __init__(self, path: Path | str, gate: OperationalGoalFeatureGateV1) -> None:
        if type(gate) is not OperationalGoalFeatureGateV1 or not gate.enabled:
            raise OperationalGoalDenied("operational goals are disabled")
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
                raise OperationalGoalError("schema object has no stored SQL")
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
            _canonical_json({"objects": objects, "details": details}).encode("utf-8")
        ).hexdigest()

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
                count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM sqlite_master "
                        "WHERE name NOT LIKE 'sqlite_%'"
                    ).fetchone()[0]
                )
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if count == 0 and version == 0:
                    connection.execute("BEGIN IMMEDIATE")
                    for statement in self._DDL:
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO metadata(schema_version) VALUES(?)",
                        (SCHEMA_VERSION,),
                    )
                    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    connection.execute("COMMIT")
                metadata = connection.execute(
                    "SELECT schema_version FROM metadata"
                ).fetchall()
                if (
                    int(connection.execute("PRAGMA user_version").fetchone()[0])
                    != SCHEMA_VERSION
                    or [tuple(row) for row in metadata] != [(SCHEMA_VERSION,)]
                    or self._signature(connection) != self._expected_signature
                    or connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or connection.execute("PRAGMA foreign_key_check").fetchall()
                ):
                    raise OperationalGoalError("operational-goal schema authentication failed")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
            if os.name != "nt" and self.path.exists():
                os.chmod(self.path, 0o600)

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        goal_id: str,
        event: str,
        detail: object,
    ) -> None:
        safe_event = _identifier(event, "event")
        detail_json = _canonical_json(detail)
        previous = connection.execute(
            "SELECT event_hash FROM goal_events WHERE goal_id=? "
            "ORDER BY seq DESC LIMIT 1",
            (goal_id,),
        ).fetchone()
        prev_hash = str(previous[0]) if previous is not None else ""
        timestamp = time.time()
        event_hash = hashlib.sha256(
            f"{goal_id}\0{timestamp:.9f}\0{safe_event}\0{detail_json}\0{prev_hash}".encode(
                "utf-8"
            )
        ).hexdigest()
        connection.execute(
            "INSERT INTO goal_events(goal_id,timestamp,event,detail_json,prev_hash,event_hash) "
            "VALUES(?,?,?,?,?,?)",
            (goal_id, timestamp, safe_event, detail_json, prev_hash, event_hash),
        )

    @staticmethod
    def _row(row: sqlite3.Row) -> OperationalGoalV1:
        target_at = row["target_at"]
        digest = row["verification_digest"]
        if digest is not None and _SHA256.fullmatch(str(digest)) is None:
            raise OperationalGoalError("stored verification digest is invalid")
        return OperationalGoalV1(
            str(row["goal_id"]),
            str(row["owner_profile_id"]),
            str(row["workspace_id"]),
            str(row["parent_id"]) if row["parent_id"] is not None else None,
            GoalLevelV1(str(row["level"])),
            str(row["title"]),
            str(row["objective"]),
            _conditions(json.loads(str(row["definition_json"]))),
            GoalStatusV1(str(row["status"])),
            float(target_at) if target_at is not None else None,
            str(row["plan_id"]) if row["plan_id"] is not None else None,
            str(row["mission_id"]) if row["mission_id"] is not None else None,
            str(digest) if digest is not None else None,
            int(row["revision"]),
            float(row["created_at"]),
            float(row["updated_at"]),
        )

    def create(
        self,
        *,
        owner_profile_id: str,
        workspace_id: str,
        level: GoalLevelV1,
        title: str,
        objective: str,
        definition_of_done: Sequence[str],
        parent_id: str | None = None,
        target_at: float | None = None,
    ) -> OperationalGoalV1:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        if type(level) is not GoalLevelV1:
            raise OperationalGoalContractError("level must be an exact GoalLevelV1")
        safe_title = _text(title, "title", 240)
        safe_objective = _text(objective, "objective", 2_000)
        conditions = _conditions(definition_of_done)
        if target_at is not None and (
            isinstance(target_at, bool)
            or not isinstance(target_at, (int, float))
            or not math.isfinite(target_at)
            or target_at <= 0
        ):
            raise OperationalGoalContractError("target_at is invalid")
        goal_id = "ogl_" + uuid.uuid4().hex
        now = time.time()
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                if parent_id is None:
                    if level is not GoalLevelV1.OBJECTIVE:
                        raise OperationalGoalContractError(
                            "only an objective may be a root goal"
                        )
                else:
                    parent_key = _identifier(parent_id, "parent_id")
                    parent = connection.execute(
                        "SELECT * FROM goals WHERE goal_id=?", (parent_key,)
                    ).fetchone()
                    if parent is None:
                        raise KeyError(parent_key)
                    parent_goal = self._row(parent)
                    if (
                        parent_goal.owner_profile_id != owner
                        or parent_goal.workspace_id != workspace
                        or _CHILD_LEVEL.get(parent_goal.level) is not level
                        or parent_goal.status
                        in {GoalStatusV1.COMPLETED, GoalStatusV1.CANCELLED}
                    ):
                        raise OperationalGoalDenied("parent goal binding is invalid")
                connection.execute(
                    "INSERT INTO goals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        goal_id,
                        owner,
                        workspace,
                        parent_id,
                        level.value,
                        safe_title,
                        safe_objective,
                        _canonical_json(list(conditions)),
                        GoalStatusV1.DRAFT.value,
                        float(target_at) if target_at is not None else None,
                        None,
                        None,
                        None,
                        1,
                        now,
                        now,
                    ),
                )
                self._append_event(
                    connection,
                    goal_id,
                    "goal.created",
                    {"level": level.value, "parent_id": parent_id},
                )
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return self.get(goal_id)

    def get(self, goal_id: str) -> OperationalGoalV1:
        key = _identifier(goal_id, "goal_id")
        self.initialize()
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM goals WHERE goal_id=?", (key,)
            ).fetchone()
            if row is None:
                raise KeyError(key)
            self._verified_events(connection, key)
            return self._row(row)
        finally:
            connection.close()

    @staticmethod
    def _verified_events(
        connection: sqlite3.Connection, goal_id: str
    ) -> tuple[dict[str, object], ...]:
        previous = ""
        output: list[dict[str, object]] = []
        for row in connection.execute(
            "SELECT * FROM goal_events WHERE goal_id=? ORDER BY seq", (goal_id,)
        ):
            expected = hashlib.sha256(
                f"{goal_id}\0{row['timestamp']:.9f}\0{row['event']}\0"
                f"{row['detail_json']}\0{previous}".encode("utf-8")
            ).hexdigest()
            if row["prev_hash"] != previous or row["event_hash"] != expected:
                raise OperationalGoalError("goal event lineage diverges")
            output.append(
                {
                    "seq": int(row["seq"]),
                    "timestamp": float(row["timestamp"]),
                    "event": str(row["event"]),
                    "detail": json.loads(str(row["detail_json"])),
                    "event_hash": expected,
                }
            )
            previous = expected
        if not output:
            raise OperationalGoalError("goal event lineage is unavailable")
        return tuple(output)

    def events(self, goal_id: str) -> tuple[dict[str, object], ...]:
        key = _identifier(goal_id, "goal_id")
        connection = self._connect()
        try:
            if connection.execute(
                "SELECT 1 FROM goals WHERE goal_id=?", (key,)
            ).fetchone() is None:
                raise KeyError(key)
            return self._verified_events(connection, key)
        finally:
            connection.close()

    def _owner_transition(
        self, goal_id: str, target: GoalStatusV1, reason: str
    ) -> OperationalGoalV1:
        key = _identifier(goal_id, "goal_id")
        safe_reason = _text(reason, "reason", 512)
        allowed = {
            GoalStatusV1.DRAFT: {GoalStatusV1.ACTIVE, GoalStatusV1.CANCELLED},
            GoalStatusV1.ACTIVE: {GoalStatusV1.PAUSED, GoalStatusV1.CANCELLED},
            GoalStatusV1.PAUSED: {GoalStatusV1.ACTIVE, GoalStatusV1.CANCELLED},
        }
        if target is GoalStatusV1.COMPLETED:
            raise OperationalGoalDenied("completion requires Phase 6 evidence")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM goals WHERE goal_id=?", (key,)
                ).fetchone()
                if row is None:
                    raise KeyError(key)
                current = GoalStatusV1(str(row["status"]))
                if target not in allowed.get(current, set()):
                    raise OperationalGoalDenied("goal transition is not allowed")
                now = time.time()
                connection.execute(
                    "UPDATE goals SET status=?,revision=revision+1,updated_at=? "
                    "WHERE goal_id=?",
                    (target.value, now, key),
                )
                self._append_event(
                    connection,
                    key,
                    f"goal.{target.value}",
                    {"reason": safe_reason},
                )
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return self.get(key)

    def activate(self, goal_id: str, reason: str = "owner_activated") -> OperationalGoalV1:
        return self._owner_transition(goal_id, GoalStatusV1.ACTIVE, reason)

    def pause(self, goal_id: str, reason: str = "owner_paused") -> OperationalGoalV1:
        return self._owner_transition(goal_id, GoalStatusV1.PAUSED, reason)

    def cancel(self, goal_id: str, reason: str = "owner_cancelled") -> OperationalGoalV1:
        return self._owner_transition(goal_id, GoalStatusV1.CANCELLED, reason)

    def bind_plan(
        self, goal_id: str, *, plan_id: str, mission_id: str
    ) -> OperationalGoalV1:
        key = _identifier(goal_id, "goal_id")
        plan = _identifier(plan_id, "plan_id")
        mission = _identifier(mission_id, "mission_id")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM goals WHERE goal_id=?", (key,)
                ).fetchone()
                if row is None:
                    raise KeyError(key)
                goal = self._row(row)
                if goal.status in {GoalStatusV1.COMPLETED, GoalStatusV1.CANCELLED}:
                    raise OperationalGoalDenied("terminal goal cannot be rebound")
                if goal.plan_id is not None or goal.mission_id is not None:
                    if goal.plan_id == plan and goal.mission_id == mission:
                        connection.execute("COMMIT")
                        return goal
                    raise OperationalGoalDenied("goal already has an immutable plan binding")
                connection.execute(
                    "UPDATE goals SET plan_id=?,mission_id=?,revision=revision+1,updated_at=? "
                    "WHERE goal_id=?",
                    (plan, mission, time.time(), key),
                )
                self._append_event(
                    connection,
                    key,
                    "goal.plan_bound",
                    {"plan_id": plan, "mission_id": mission},
                )
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return self.get(key)

    def reconcile_verified(
        self,
        goal_id: str,
        *,
        state_store: AgenticStateStoreV6,
        mission_store: MissionStore,
    ) -> OperationalGoalV1:
        """Complete one goal only from exact current Phase 6/MissionStore truth."""

        if type(state_store) is not AgenticStateStoreV6:
            raise OperationalGoalContractError("exact AgenticStateStoreV6 is required")
        if type(mission_store) is not MissionStore:
            raise OperationalGoalContractError("exact MissionStore is required")
        goal = self.get(goal_id)
        if goal.status is GoalStatusV1.COMPLETED:
            return goal
        if goal.status not in {GoalStatusV1.ACTIVE, GoalStatusV1.PAUSED}:
            raise OperationalGoalDenied("only an active or paused goal may reconcile")
        if goal.plan_id is None or goal.mission_id is None:
            raise OperationalGoalDenied("goal has no Phase 6 mission binding")

        projection = state_store.get_projection(goal.plan_id)
        if (
            projection.state is not PlanStateV1.COMPLETE
            or projection.mission_id != goal.mission_id
            or projection.mission_plan_digest is None
        ):
            raise OperationalGoalDenied("Phase 6 plan is not independently complete")
        mission = mission_store.get(goal.mission_id)
        snapshot = mission_store.authority_snapshot(goal.mission_id)
        if mission.state != "succeeded" or snapshot.state != "succeeded":
            raise OperationalGoalDenied("mission authority is not succeeded")
        receipts = state_store.plans.receipts(goal.plan_id)
        if not receipts:
            raise OperationalGoalDenied("Phase 6 verification receipts are unavailable")
        mission_event_hashes = {
            str(item["event_hash"]) for item in mission_store.events(goal.mission_id)
        }
        observed_conditions: set[str] = set()
        receipt_payloads: list[dict[str, object]] = []
        for receipt in receipts:
            if (
                receipt.status != "verified"
                or receipt.plan_id != goal.plan_id
                or receipt.mission_id != goal.mission_id
                or receipt.authority_snapshot_hash != snapshot.snapshot_hash
                or receipt.event_hash not in mission_event_hashes
            ):
                raise OperationalGoalDenied("Phase 6 receipt binding diverges")
            observed_conditions.update(receipt.postconditions)
            receipt_payloads.append(receipt.payload())
        missing = set(goal.definition_of_done) - observed_conditions
        if missing:
            raise OperationalGoalDenied(
                "definition of done lacks verified postconditions: "
                + ", ".join(sorted(missing))
            )
        verification_digest = hashlib.sha256(
            _canonical_json(
                {
                    "goal_id": goal.goal_id,
                    "plan_id": goal.plan_id,
                    "mission_id": goal.mission_id,
                    "mission_plan_digest": projection.mission_plan_digest,
                    "authority_snapshot_hash": snapshot.snapshot_hash,
                    "receipts": receipt_payloads,
                }
            ).encode("utf-8")
        ).hexdigest()

        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    "SELECT * FROM goals WHERE goal_id=?", (goal.goal_id,)
                ).fetchone()
                if current is None:
                    raise KeyError(goal.goal_id)
                current_goal = self._row(current)
                if (
                    current_goal.revision != goal.revision
                    or current_goal.plan_id != goal.plan_id
                    or current_goal.mission_id != goal.mission_id
                    or current_goal.status not in {GoalStatusV1.ACTIVE, GoalStatusV1.PAUSED}
                ):
                    raise OperationalGoalDenied("goal changed during evidence reconciliation")
                connection.execute(
                    "UPDATE goals SET status='completed',verification_digest=?,"
                    "revision=revision+1,updated_at=? WHERE goal_id=?",
                    (verification_digest, time.time(), goal.goal_id),
                )
                self._append_event(
                    connection,
                    goal.goal_id,
                    "goal.completed",
                    {
                        "verification_digest": verification_digest,
                        "authority_snapshot_hash": snapshot.snapshot_hash,
                    },
                )
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return self.get(goal.goal_id)

    def projection(self, goal_id: str, *, now: float | None = None) -> GoalProjectionV1:
        goal = self.get(goal_id)
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT goal_id,status FROM goals WHERE parent_id=? ORDER BY created_at",
                (goal.goal_id,),
            ).fetchall()
        finally:
            connection.close()
        children = tuple(str(row["goal_id"]) for row in rows)
        if goal.status is GoalStatusV1.COMPLETED:
            score = 1.0
        elif children:
            score = sum(self.projection(child, now=now).score for child in children) / len(
                children
            )
        else:
            score = 0.0
        current = time.time() if now is None else float(now)
        if goal.status is GoalStatusV1.CANCELLED:
            health = "cancelled"
        elif goal.status is GoalStatusV1.COMPLETED:
            health = "complete"
        elif goal.target_at is not None and current > goal.target_at:
            health = "overdue"
        elif goal.status is GoalStatusV1.PAUSED:
            health = "paused"
        else:
            health = "on_track"
        return GoalProjectionV1(goal, round(score, 6), health, children)

    def attention_queue(
        self, *, owner_profile_id: str, workspace_id: str, now: float | None = None
    ) -> tuple[GoalProjectionV1, ...]:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        current = time.time() if now is None else float(now)
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT goal_id FROM goals WHERE owner_profile_id=? AND workspace_id=? "
                "AND status IN ('active','paused') ORDER BY "
                "CASE WHEN target_at IS NULL THEN 1 ELSE 0 END,target_at,created_at",
                (owner, workspace),
            ).fetchall()
        finally:
            connection.close()
        return tuple(self.projection(str(row[0]), now=current) for row in rows)

