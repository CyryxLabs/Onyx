"""Event-driven automation around the existing Onyx Phase 6 executor.

Rules bind one exact metadata-only event contract to one already materialized and
approved Phase 6 mission.  The module owns no worker thread, timer, planner,
permission prompt or tool executor.  Native adapters publish events; the host
explicitly drains the bounded queue through ``AgenticCoreV6.execute_approved``.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from core.operational_goals_v1 import OperationalGoalStoreV1
from core.phase6_agentic_core_v1 import PlanStateV1
from core.phase6_agentic_core_v6 import AgenticCoreV6, normalized_sql_v6


SCHEMA_VERSION = 1
FEATURE_FLAG = "ONYX_GOVERNED_AUTOMATION_V1"
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,191}")
_EVENT_TYPE = re.compile(r"[a-z][a-z0-9_.-]{2,127}")
_SENSITIVE_PARTS = frozenset(
    {
        "body",
        "clipboard",
        "content",
        "cookie",
        "credential",
        "image",
        "password",
        "screenshot",
        "secret",
        "text",
        "token",
        "transcript",
    }
)


class GovernedAutomationError(RuntimeError):
    pass


class GovernedAutomationContractError(ValueError):
    pass


class GovernedAutomationDenied(PermissionError):
    pass


class GovernedAutomationQueueFull(GovernedAutomationError):
    pass


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise GovernedAutomationContractError(f"{label} is invalid")
    return value


def _event_type(value: object) -> str:
    if type(value) is not str or _EVENT_TYPE.fullmatch(value) is None:
        raise GovernedAutomationContractError("event_type is invalid")
    return value


def _canonical_json(value: object) -> str:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise GovernedAutomationContractError("value is not canonical JSON") from exc
    if len(encoded.encode("utf-8")) > 32_768:
        raise GovernedAutomationContractError("value exceeds its byte budget")
    return encoded


def _metadata(value: Mapping[str, object] | None) -> tuple[tuple[str, str], ...]:
    if value is None:
        return ()
    if type(value) is not dict or len(value) > 24:
        raise GovernedAutomationContractError("metadata must be a bounded plain mapping")
    output: list[tuple[str, str]] = []
    for key, raw in sorted(value.items()):
        canonical_key = _event_type(key)
        key_parts = set(canonical_key.replace("-", ".").replace("_", ".").split("."))
        if key_parts & _SENSITIVE_PARTS:
            raise GovernedAutomationDenied("event metadata may not contain sensitive content")
        if type(raw) not in {str, int, float, bool}:
            raise GovernedAutomationContractError("metadata values must be scalar")
        if isinstance(raw, float) and not math.isfinite(raw):
            raise GovernedAutomationContractError("metadata number is not finite")
        rendered = str(raw).lower() if type(raw) is bool else str(raw)
        if not rendered or len(rendered) > 256 or "\x00" in rendered:
            raise GovernedAutomationContractError("metadata value is invalid")
        output.append((canonical_key, rendered))
    return tuple(output)


@dataclass(frozen=True)
class AutomationEventV1:
    event_id: str
    event_type: str
    source_id: str
    owner_profile_id: str
    workspace_id: str
    occurred_at: float
    metadata: tuple[tuple[str, str], ...] = ()
    coalesce_key: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.event_id, "event_id")
        _event_type(self.event_type)
        _identifier(self.source_id, "source_id")
        _identifier(self.owner_profile_id, "owner_profile_id")
        _identifier(self.workspace_id, "workspace_id")
        if (
            isinstance(self.occurred_at, bool)
            or not isinstance(self.occurred_at, (int, float))
            or not math.isfinite(self.occurred_at)
            or self.occurred_at <= 0
        ):
            raise GovernedAutomationContractError("occurred_at is invalid")
        if type(self.metadata) is not tuple or dict(self.metadata) != dict(
            _metadata(dict(self.metadata))
        ):
            raise GovernedAutomationContractError("metadata is not canonical")
        if self.coalesce_key is not None:
            _identifier(self.coalesce_key, "coalesce_key")

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        source_id: str,
        owner_profile_id: str,
        workspace_id: str,
        metadata: Mapping[str, object] | None = None,
        coalesce_key: str | None = None,
        occurred_at: float | None = None,
    ) -> "AutomationEventV1":
        return cls(
            "evt_" + uuid.uuid4().hex,
            _event_type(event_type),
            _identifier(source_id, "source_id"),
            _identifier(owner_profile_id, "owner_profile_id"),
            _identifier(workspace_id, "workspace_id"),
            time.time() if occurred_at is None else float(occurred_at),
            _metadata(metadata),
            _identifier(coalesce_key, "coalesce_key")
            if coalesce_key is not None
            else None,
        )


@dataclass(frozen=True)
class AutomationRuleV1:
    rule_id: str
    owner_profile_id: str
    workspace_id: str
    event_type: str
    metadata_filter: tuple[tuple[str, str], ...]
    plan_id: str
    mission_id: str
    goal_id: str | None
    expires_at: float
    max_uses: int
    use_count: int
    enabled: bool
    revision: int


@dataclass(frozen=True)
class AutomationDispatchV1:
    dispatch_id: str
    rule_id: str
    event_id: str
    status: str
    result_digest: str | None
    detail: str


@dataclass(frozen=True)
class GovernedAutomationFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise GovernedAutomationContractError("enabled must be an exact boolean")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "GovernedAutomationFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


class AutomationRuleStoreV1:
    _DDL = (
        """CREATE TABLE metadata(
          schema_version INTEGER NOT NULL CHECK(schema_version=1)
        )""",
        """CREATE TABLE automation_rules(
          rule_id TEXT PRIMARY KEY,
          owner_profile_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL,
          event_type TEXT NOT NULL,
          metadata_filter_json TEXT NOT NULL,
          plan_id TEXT NOT NULL UNIQUE,
          mission_id TEXT NOT NULL UNIQUE,
          goal_id TEXT,
          expires_at REAL NOT NULL,
          max_uses INTEGER NOT NULL CHECK(max_uses BETWEEN 1 AND 10000),
          use_count INTEGER NOT NULL CHECK(use_count BETWEEN 0 AND max_uses),
          enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
          revision INTEGER NOT NULL CHECK(revision>=1),
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL
        )""",
        """CREATE TABLE automation_dispatches(
          dispatch_id TEXT PRIMARY KEY,
          rule_id TEXT NOT NULL REFERENCES automation_rules(rule_id),
          event_id TEXT NOT NULL,
          event_digest TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN
            ('reserved','running','succeeded','failed','waiting','reconciliation')),
          result_digest TEXT,
          detail TEXT NOT NULL,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          UNIQUE(rule_id,event_id)
        )""",
        """CREATE TABLE automation_events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          entity_id TEXT NOT NULL,
          timestamp REAL NOT NULL,
          event TEXT NOT NULL,
          detail_json TEXT NOT NULL,
          prev_hash TEXT NOT NULL,
          event_hash TEXT NOT NULL UNIQUE
        )""",
        """CREATE INDEX idx_automation_rules_match
          ON automation_rules(owner_profile_id,workspace_id,event_type,enabled)""",
        """CREATE INDEX idx_automation_dispatch_status
          ON automation_dispatches(status,updated_at)""",
        """CREATE INDEX idx_automation_events_entity
          ON automation_events(entity_id,seq)""",
        """CREATE TRIGGER automation_events_no_update
          BEFORE UPDATE ON automation_events
          BEGIN SELECT RAISE(ABORT,'automation events are immutable'); END""",
        """CREATE TRIGGER automation_events_no_delete
          BEFORE DELETE ON automation_events
          BEGIN SELECT RAISE(ABORT,'automation events are immutable'); END""",
    )

    def __init__(self, path: Path | str, gate: GovernedAutomationFeatureGateV1) -> None:
        if type(gate) is not GovernedAutomationFeatureGateV1 or not gate.enabled:
            raise GovernedAutomationDenied("governed automation is disabled")
        self.path = Path(path)
        if not self.path.is_absolute() or self.path.name in {"", ".", ".."}:
            raise GovernedAutomationContractError("an explicit absolute database path is required")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.parent.is_symlink() or (self.path.exists() and self.path.is_symlink()):
            raise GovernedAutomationDenied("linked automation storage is forbidden")
        self._lock = threading.RLock()
        self._expected_signature = self._expected()
        self.initialize()

    @staticmethod
    def _signature(connection: sqlite3.Connection) -> str:
        objects = []
        for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ):
            if row[3] is None:
                raise GovernedAutomationError("schema object has no SQL")
            objects.append((row[0], row[1], row[2], normalized_sql_v6(str(row[3]))))
        return hashlib.sha256(_canonical_json(objects).encode("utf-8")).hexdigest()

    @classmethod
    def _expected(cls) -> str:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            for statement in cls._DDL:
                connection.execute(statement)
            connection.execute("INSERT INTO metadata VALUES(1)")
            connection.execute("PRAGMA user_version=1")
            return cls._signature(connection)
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
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
                        "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                    ).fetchone()[0]
                )
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if count == 0 and version == 0:
                    connection.execute("BEGIN IMMEDIATE")
                    for statement in self._DDL:
                        connection.execute(statement)
                    connection.execute("INSERT INTO metadata VALUES(1)")
                    connection.execute("PRAGMA user_version=1")
                    connection.execute("COMMIT")
                if (
                    int(connection.execute("PRAGMA user_version").fetchone()[0]) != 1
                    or [tuple(row) for row in connection.execute("SELECT * FROM metadata")]
                    != [(1,)]
                    or self._signature(connection) != self._expected_signature
                    or connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or connection.execute("PRAGMA foreign_key_check").fetchall()
                ):
                    raise GovernedAutomationError("automation schema authentication failed")
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
        connection: sqlite3.Connection, entity_id: str, event: str, detail: object
    ) -> None:
        safe_event = _event_type(event)
        detail_json = _canonical_json(detail)
        row = connection.execute(
            "SELECT event_hash FROM automation_events WHERE entity_id=? "
            "ORDER BY seq DESC LIMIT 1",
            (entity_id,),
        ).fetchone()
        previous = str(row[0]) if row is not None else ""
        timestamp = time.time()
        digest = hashlib.sha256(
            f"{entity_id}\0{timestamp:.9f}\0{safe_event}\0{detail_json}\0{previous}".encode()
        ).hexdigest()
        connection.execute(
            "INSERT INTO automation_events(entity_id,timestamp,event,detail_json,prev_hash,event_hash) "
            "VALUES(?,?,?,?,?,?)",
            (entity_id, timestamp, safe_event, detail_json, previous, digest),
        )

    @staticmethod
    def _rule(row: sqlite3.Row) -> AutomationRuleV1:
        filters = _metadata(dict(json.loads(str(row["metadata_filter_json"]))))
        return AutomationRuleV1(
            str(row["rule_id"]),
            str(row["owner_profile_id"]),
            str(row["workspace_id"]),
            str(row["event_type"]),
            filters,
            str(row["plan_id"]),
            str(row["mission_id"]),
            str(row["goal_id"]) if row["goal_id"] is not None else None,
            float(row["expires_at"]),
            int(row["max_uses"]),
            int(row["use_count"]),
            bool(row["enabled"]),
            int(row["revision"]),
        )

    def create_rule(
        self,
        *,
        core: AgenticCoreV6,
        owner_profile_id: str,
        workspace_id: str,
        event_type: str,
        metadata_filter: Mapping[str, object],
        plan_id: str,
        mission_id: str,
        expires_at: float,
        max_uses: int = 1,
        goal_id: str | None = None,
        enabled: bool = True,
    ) -> AutomationRuleV1:
        if type(core) is not AgenticCoreV6 or core.closed:
            raise GovernedAutomationContractError("an open exact AgenticCoreV6 is required")
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        kind = _event_type(event_type)
        filters = _metadata(metadata_filter)
        plan = _identifier(plan_id, "plan_id")
        mission = _identifier(mission_id, "mission_id")
        linked_goal = _identifier(goal_id, "goal_id") if goal_id is not None else None
        if (
            isinstance(expires_at, bool)
            or not isinstance(expires_at, (int, float))
            or not math.isfinite(expires_at)
            or expires_at <= time.time()
            or expires_at > time.time() + 366 * 86_400
        ):
            raise GovernedAutomationContractError("expires_at is invalid")
        if isinstance(max_uses, bool) or not isinstance(max_uses, int) or not 1 <= max_uses <= 10_000:
            raise GovernedAutomationContractError("max_uses is invalid")
        if type(enabled) is not bool:
            raise GovernedAutomationContractError("enabled is invalid")
        projection = core._state.get_projection(plan)
        bound_mission = core._missions.get(mission)
        if (
            projection.mission_id != mission
            or projection.state
            not in {PlanStateV1.AWAITING_APPROVAL, PlanStateV1.RUNNING, PlanStateV1.PAUSED}
            or bound_mission.state not in {"running", "paused"}
        ):
            raise GovernedAutomationDenied(
                "automation requires one exact already-approved Phase 6 mission"
            )
        plan_value = core._state.get_plan(plan)
        if plan_value.goal.workspace_id != workspace:
            raise GovernedAutomationDenied("automation workspace diverges from its plan")
        rule_id = "rule_" + uuid.uuid4().hex
        now = time.time()
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO automation_rules VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        rule_id,
                        owner,
                        workspace,
                        kind,
                        _canonical_json(dict(filters)),
                        plan,
                        mission,
                        linked_goal,
                        float(expires_at),
                        max_uses,
                        0,
                        int(enabled),
                        1,
                        now,
                        now,
                    ),
                )
                self._append_event(
                    connection,
                    rule_id,
                    "automation.rule.created",
                    {
                        "event_type": kind,
                        "plan_id": plan,
                        "mission_id": mission,
                        "expires_at": float(expires_at),
                        "max_uses": max_uses,
                        "enabled": enabled,
                    },
                )
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return self.get_rule(rule_id)

    def set_enabled(self, rule_id: str, enabled: bool) -> AutomationRuleV1:
        """Arm or disarm a rule without changing its Phase 6 authority binding."""

        key = _identifier(rule_id, "rule_id")
        if type(enabled) is not bool:
            raise GovernedAutomationContractError("enabled is invalid")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT enabled FROM automation_rules WHERE rule_id=?", (key,)
                ).fetchone()
                if row is None:
                    raise KeyError(key)
                if bool(row["enabled"]) != enabled:
                    changed = connection.execute(
                        "UPDATE automation_rules SET enabled=?,revision=revision+1,updated_at=? "
                        "WHERE rule_id=?",
                        (int(enabled), time.time(), key),
                    ).rowcount
                    if changed != 1:
                        raise GovernedAutomationError(
                            "automation rule enablement changed concurrently"
                        )
                    self._append_event(
                        connection,
                        key,
                        "automation.rule.enabled" if enabled else "automation.rule.disabled",
                        {"enabled": enabled},
                    )
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return self.get_rule(key)

    def get_rule(self, rule_id: str) -> AutomationRuleV1:
        key = _identifier(rule_id, "rule_id")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM automation_rules WHERE rule_id=?", (key,)
            ).fetchone()
            if row is None:
                raise KeyError(key)
            return self._rule(row)
        finally:
            connection.close()

    def count_scope(self, owner_profile_id: str, workspace_id: str) -> int:
        """Return a scope-bound rule count without exposing plan or mission IDs."""

        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT COUNT(*) FROM automation_rules "
                "WHERE owner_profile_id=? AND workspace_id=?",
                (owner, workspace),
            ).fetchone()
            return int(row[0])
        finally:
            connection.close()

    def matching(self, event: AutomationEventV1) -> tuple[AutomationRuleV1, ...]:
        if type(event) is not AutomationEventV1:
            raise GovernedAutomationContractError("exact AutomationEventV1 is required")
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM automation_rules WHERE owner_profile_id=? AND workspace_id=? "
                "AND event_type=? AND enabled=1 AND use_count<max_uses AND expires_at>? "
                "ORDER BY created_at,rule_id",
                (
                    event.owner_profile_id,
                    event.workspace_id,
                    event.event_type,
                    time.time(),
                ),
            ).fetchall()
        finally:
            connection.close()
        observed = dict(event.metadata)
        matches: list[AutomationRuleV1] = []
        for row in rows:
            rule = self._rule(row)
            if all(
                observed.get(key) == value
                for key, value in rule.metadata_filter
            ):
                matches.append(rule)
        return tuple(matches)

    def reserve(
        self, rule_id: str, event: AutomationEventV1
    ) -> AutomationDispatchV1 | None:
        rule_key = _identifier(rule_id, "rule_id")
        event_digest = hashlib.sha256(
            _canonical_json(
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "source_id": event.source_id,
                    "owner_profile_id": event.owner_profile_id,
                    "workspace_id": event.workspace_id,
                    "occurred_at": event.occurred_at,
                    "metadata": dict(event.metadata),
                }
            ).encode()
        ).hexdigest()
        dispatch_id = "dsp_" + hashlib.sha256(
            f"{rule_key}\0{event.event_id}".encode()
        ).hexdigest()
        now = time.time()
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM automation_dispatches WHERE rule_id=? AND event_id=?",
                    (rule_key, event.event_id),
                ).fetchone()
                if existing is not None:
                    connection.execute("COMMIT")
                    return None
                row = connection.execute(
                    "SELECT * FROM automation_rules WHERE rule_id=?", (rule_key,)
                ).fetchone()
                if row is None:
                    raise KeyError(rule_key)
                rule = self._rule(row)
                if (
                    not rule.enabled
                    or rule.use_count >= rule.max_uses
                    or rule.expires_at <= now
                    or rule.owner_profile_id != event.owner_profile_id
                    or rule.workspace_id != event.workspace_id
                    or rule.event_type != event.event_type
                    or not all(dict(event.metadata).get(k) == v for k, v in rule.metadata_filter)
                ):
                    connection.execute("COMMIT")
                    return None
                connection.execute(
                    "INSERT INTO automation_dispatches VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        dispatch_id,
                        rule_key,
                        event.event_id,
                        event_digest,
                        "reserved",
                        None,
                        "event_reserved",
                        now,
                        now,
                    ),
                )
                connection.execute(
                    "UPDATE automation_rules SET use_count=use_count+1,revision=revision+1,"
                    "updated_at=? WHERE rule_id=?",
                    (now, rule_key),
                )
                self._append_event(
                    connection,
                    dispatch_id,
                    "automation.dispatch.reserved",
                    {"rule_id": rule_key, "event_digest": event_digest},
                )
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return AutomationDispatchV1(
            dispatch_id, rule_key, event.event_id, "reserved", None, "event_reserved"
        )

    def finish(
        self, dispatch_id: str, *, status: str, result_digest: str | None, detail: str
    ) -> AutomationDispatchV1:
        key = _identifier(dispatch_id, "dispatch_id")
        if status not in {"running", "succeeded", "failed", "waiting", "reconciliation"}:
            raise GovernedAutomationContractError("dispatch status is invalid")
        if result_digest is not None and re.fullmatch(r"[0-9a-f]{64}", result_digest) is None:
            raise GovernedAutomationContractError("result_digest is invalid")
        safe_detail = _event_type(detail)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM automation_dispatches WHERE dispatch_id=?", (key,)
                ).fetchone()
                if row is None:
                    raise KeyError(key)
                current = str(row["status"])
                transitions = {
                    "reserved": {"running", "reconciliation"},
                    "running": {"succeeded", "failed", "waiting", "reconciliation"},
                }
                if status not in transitions.get(current, set()):
                    if current == status and row["result_digest"] == result_digest:
                        connection.execute("COMMIT")
                        return AutomationDispatchV1(
                            key,
                            str(row["rule_id"]),
                            str(row["event_id"]),
                            current,
                            str(row["result_digest"])
                            if row["result_digest"] is not None
                            else None,
                            str(row["detail"]),
                        )
                    raise GovernedAutomationDenied("dispatch transition is not allowed")
                connection.execute(
                    "UPDATE automation_dispatches SET status=?,result_digest=?,detail=?,"
                    "updated_at=? WHERE dispatch_id=?",
                    (status, result_digest, safe_detail, time.time(), key),
                )
                self._append_event(
                    connection,
                    key,
                    f"automation.dispatch.{status}",
                    {"result_digest": result_digest, "detail": safe_detail},
                )
                connection.execute("COMMIT")
                row = connection.execute(
                    "SELECT * FROM automation_dispatches WHERE dispatch_id=?", (key,)
                ).fetchone()
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        assert row is not None
        return AutomationDispatchV1(
            key,
            str(row["rule_id"]),
            str(row["event_id"]),
            str(row["status"]),
            str(row["result_digest"]) if row["result_digest"] is not None else None,
            str(row["detail"]),
        )

    def recover_uncertain(self) -> int:
        """Quarantine interrupted dispatches; never auto-replay an effect."""
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    "SELECT dispatch_id FROM automation_dispatches "
                    "WHERE status IN ('reserved','running')"
                ).fetchall()
                for row in rows:
                    key = str(row[0])
                    connection.execute(
                        "UPDATE automation_dispatches SET status='reconciliation',"
                        "detail='restart_requires_reconciliation',updated_at=? "
                        "WHERE dispatch_id=?",
                        (time.time(), key),
                    )
                    self._append_event(
                        connection,
                        key,
                        "automation.dispatch.reconciliation",
                        {"detail": "restart_requires_reconciliation"},
                    )
                connection.execute("COMMIT")
                return len(rows)
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()


@dataclass(frozen=True)
class _QueuedDispatchV1:
    event: AutomationEventV1
    rule: AutomationRuleV1
    dispatch: AutomationDispatchV1


class EventDrivenAutomationRuntimeV1:
    """Bounded explicit-drain queue.  It performs zero work while idle."""

    def __init__(
        self,
        *,
        core: AgenticCoreV6,
        rules: AutomationRuleStoreV1,
        goal_store: OperationalGoalStoreV1 | None = None,
        max_queue: int = 256,
    ) -> None:
        if type(core) is not AgenticCoreV6 or core.closed:
            raise GovernedAutomationContractError("an open exact AgenticCoreV6 is required")
        if type(rules) is not AutomationRuleStoreV1:
            raise GovernedAutomationContractError("exact AutomationRuleStoreV1 is required")
        if goal_store is not None and type(goal_store) is not OperationalGoalStoreV1:
            raise GovernedAutomationContractError("goal_store type is invalid")
        if isinstance(max_queue, bool) or not isinstance(max_queue, int) or not 1 <= max_queue <= 4096:
            raise GovernedAutomationContractError("max_queue is invalid")
        self._core = core
        self._rules = rules
        self._goals = goal_store
        self._max_queue = max_queue
        self._queue: deque[_QueuedDispatchV1] = deque()
        self._coalesce: dict[tuple[str, str], str] = {}
        self._lock = threading.RLock()
        self._idle_cycles = 0

    @property
    def queued(self) -> int:
        with self._lock:
            return len(self._queue)

    @property
    def idle_cycles(self) -> int:
        return self._idle_cycles

    def publish(self, event: AutomationEventV1) -> tuple[str, ...]:
        if type(event) is not AutomationEventV1:
            raise GovernedAutomationContractError("exact AutomationEventV1 is required")
        queued: list[str] = []
        with self._lock:
            for rule in self._rules.matching(event):
                coalesce = (
                    (rule.rule_id, event.coalesce_key)
                    if event.coalesce_key is not None
                    else None
                )
                if coalesce is not None and coalesce in self._coalesce:
                    continue
                if len(self._queue) >= self._max_queue:
                    raise GovernedAutomationQueueFull("automation queue is full")
                dispatch = self._rules.reserve(rule.rule_id, event)
                if dispatch is None:
                    continue
                self._queue.append(_QueuedDispatchV1(event, rule, dispatch))
                if coalesce is not None:
                    self._coalesce[coalesce] = dispatch.dispatch_id
                queued.append(dispatch.dispatch_id)
        return tuple(queued)

    def drain_one(self, runner=None) -> AutomationDispatchV1 | None:
        with self._lock:
            if not self._queue:
                return None
            item = self._queue.popleft()
            if item.event.coalesce_key is not None:
                self._coalesce.pop((item.rule.rule_id, item.event.coalesce_key), None)
        self._rules.finish(
            item.dispatch.dispatch_id,
            status="running",
            result_digest=None,
            detail="phase6_execution_started",
        )
        try:
            current_rule = self._rules.get_rule(item.rule.rule_id)
            if current_rule.expires_at <= time.time() or not current_rule.enabled:
                raise GovernedAutomationDenied("automation rule expired or was disabled")
            projection = self._core._state.get_projection(current_rule.plan_id)
            mission = self._core._missions.get(current_rule.mission_id)
            if (
                projection.mission_id != current_rule.mission_id
                or mission.state not in {"running", "paused"}
            ):
                raise GovernedAutomationDenied("Phase 6 mission binding is no longer runnable")
            mission = self._core.execute_approved(current_rule.plan_id, runner)
            projection = self._core._state.get_projection(current_rule.plan_id)
            snapshot = self._core._missions.authority_snapshot(current_rule.mission_id)
            result_digest = hashlib.sha256(
                _canonical_json(
                    {
                        "plan_id": current_rule.plan_id,
                        "plan_state": projection.state.value,
                        "mission_id": current_rule.mission_id,
                        "mission_state": mission.state,
                        "authority_snapshot_hash": snapshot.snapshot_hash,
                    }
                ).encode()
            ).hexdigest()
            if mission.state == "succeeded" and projection.state is PlanStateV1.COMPLETE:
                if current_rule.goal_id is not None:
                    if self._goals is None:
                        raise GovernedAutomationDenied("goal-bound rule has no goal store")
                    self._goals.reconcile_verified(
                        current_rule.goal_id,
                        state_store=self._core._state,
                        mission_store=self._core._missions,
                    )
                return self._rules.finish(
                    item.dispatch.dispatch_id,
                    status="succeeded",
                    result_digest=result_digest,
                    detail="phase6_evidence_verified",
                )
            if mission.state in {"waiting", "paused", "running"}:
                return self._rules.finish(
                    item.dispatch.dispatch_id,
                    status="waiting",
                    result_digest=result_digest,
                    detail="phase6_mission_waiting",
                )
            return self._rules.finish(
                item.dispatch.dispatch_id,
                status="failed",
                result_digest=result_digest,
                detail="phase6_mission_failed",
            )
        except BaseException as exc:
            digest = hashlib.sha256(type(exc).__name__.encode()).hexdigest()
            return self._rules.finish(
                item.dispatch.dispatch_id,
                status="failed",
                result_digest=digest,
                detail="governed_dispatch_failed",
            )
