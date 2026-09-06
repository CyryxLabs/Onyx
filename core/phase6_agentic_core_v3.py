"""Isolated Phase 6 Agentic Core V3 candidate.

V3 preserves V1/V2 and adds bounded synchronous-call execution, durable
generation fencing, deterministic MissionStore materialization, indexed
recovery, and terminal coordination retention. It is not live-wired.
"""

from __future__ import annotations

import hashlib
import math
import queue
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TypeVar

from core.missions import (
    InvalidTransition,
    Mission,
    MissionError,
    MissionStore,
    ToolRunner,
)
from core.mission_tools import run as run_mission_tool
from core.phase6_agentic_core_v1 import (
    AdmissionResultV1,
    AgenticCoreV1,
    AgenticCoreV1ContractError,
    AgenticCoreV1Denied,
    AgenticCoreV1Error,
    AgenticFeatureGateV1,
    AgenticStateStoreV1,
    BoundedCriticV1,
    DeterministicPlannerAdapterV1,
    GoalV1,
    IndependentVerifierV1,
    ModelRouterV1,
    PlanProjectionV1,
    PlanStateV1,
    PlanV1,
    PlannerAdapterV1,
    RecoveryRecordV1,
    StepV1,
    VerificationReportV1,
    WorkspaceScopeV1,
    _canonical_arguments,
    _identifier,
    _sha,
    capability_policy_v1,
)
from core.phase6_agentic_core_v2 import PlannerV2, artifact_root_v2


FEATURE_FLAG = "ONYX_PHASE6_AGENTIC_CORE_V3"
SCHEMA_VERSION = 3
DEFAULT_FENCE_SECONDS = 30.0
DEFAULT_RECOVERY_LIMIT = 100
DEFAULT_RETENTION_SECONDS = 7 * 24 * 60 * 60
_REQUEST_KEY = re.compile(r"^[A-Za-z0-9_.:-]{8,192}$")
_T = TypeVar("_T")


class AgenticCoreV3Error(AgenticCoreV1Error):
    """V3 coordination or bounded-execution failure."""


class AgenticCoreV3ContractError(AgenticCoreV1ContractError):
    """A V3 contract is invalid."""


class AgenticCoreV3Denied(AgenticCoreV1Denied):
    """A V3 authority denied an operation."""


class ComputeBudgetExhaustedV3(AgenticCoreV3Denied):
    """The lineage compute account is terminally exhausted."""


class BoundedCallTimeoutV3(ComputeBudgetExhaustedV3):
    """A synchronous call did not complete by its reserved deadline."""


@dataclass(frozen=True)
class AgenticFeatureGateV3:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise AgenticCoreV3ContractError("enabled must be an exact boolean")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "AgenticFeatureGateV3":
        import os

        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True)
class ComputeLeaseV3:
    account_id: str
    plan_id: str | None
    token: str
    operation: str
    allowed_seconds: float
    started_monotonic: float


@dataclass(frozen=True)
class ComputeSnapshotV3:
    account_id: str
    limit_seconds: float
    consumed_seconds: float
    remaining_seconds: float
    exhausted: bool


@dataclass(frozen=True)
class FenceClaimV3:
    plan_id: str
    generation: int
    owner_token: str | None
    disposition: str
    mission_id: str | None


@dataclass(frozen=True)
class CompactionResultV3:
    plans_deleted: int
    accounts_deleted: int
    materializations_deleted: int


@dataclass
class _CallTask:
    token: str
    callback: Callable[[], object]
    completed: threading.Event
    result: list[tuple[bool, object]]


class BoundedSyncExecutorV3:
    """One-worker executor: a hung call can consume at most one daemon thread."""

    def __init__(self) -> None:
        self._tasks: queue.Queue[_CallTask] = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._active_token: str | None = None
        self._poisoned = False
        self._worker = threading.Thread(
            target=self._run,
            name="onyx-phase6-v3-bounded-sync",
            daemon=True,
        )
        self._worker.start()

    @property
    def poisoned(self) -> bool:
        with self._lock:
            return self._poisoned

    @property
    def worker_ident(self) -> int | None:
        return self._worker.ident

    def _run(self) -> None:
        while True:
            task = self._tasks.get()
            try:
                outcome: tuple[bool, object]
                try:
                    outcome = (True, task.callback())
                except BaseException as exc:
                    outcome = (False, exc)
                with self._lock:
                    if self._active_token == task.token:
                        task.result.append(outcome)
                        self._active_token = None
                        task.completed.set()
            finally:
                self._tasks.task_done()

    def invoke(self, callback: Callable[[], _T], timeout_seconds: float) -> _T:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise AgenticCoreV3ContractError("bounded call timeout is invalid")
        task = _CallTask(f"call_{uuid.uuid4().hex}", callback, threading.Event(), [])
        with self._lock:
            if self._poisoned or self._active_token is not None:
                raise AgenticCoreV3Denied("bounded synchronous executor is unavailable")
            self._active_token = task.token
            self._tasks.put_nowait(task)
        if not task.completed.wait(float(timeout_seconds)):
            with self._lock:
                if self._active_token == task.token:
                    self._active_token = None
                self._poisoned = True
            raise BoundedCallTimeoutV3("BUDGET_EXHAUSTED")
        if not task.result:
            raise AgenticCoreV3Error("bounded call completed without a result")
        succeeded, value = task.result[0]
        if not succeeded:
            if not isinstance(value, BaseException):
                raise AgenticCoreV3Error("bounded call failure payload is invalid")
            raise value
        return value  # type: ignore[return-value]


class AgenticStateStoreV3:
    """V1 immutable plan evidence plus V3 compute/fence/recovery authority."""

    _DDL = """
    CREATE TABLE metadata(schema_version INTEGER NOT NULL);
    CREATE TABLE budget_accounts(
      account_id TEXT PRIMARY KEY,
      request_key TEXT NOT NULL UNIQUE,
      limit_seconds REAL NOT NULL,
      consumed_seconds REAL NOT NULL,
      exhausted INTEGER NOT NULL,
      active_plan_id TEXT,
      active_token TEXT,
      active_operation TEXT,
      active_started_wall REAL,
      active_deadline_wall REAL,
      terminal_at REAL,
      updated_at REAL NOT NULL
    );
    CREATE INDEX budget_terminal_idx ON budget_accounts(terminal_at,account_id);
    CREATE INDEX budget_active_idx
      ON budget_accounts(active_deadline_wall,account_id)
      WHERE active_token IS NOT NULL;
    CREATE TABLE plan_lineage(
      plan_id TEXT PRIMARY KEY,
      account_id TEXT NOT NULL REFERENCES budget_accounts(account_id),
      created_at REAL NOT NULL
    );
    CREATE INDEX lineage_account_idx ON plan_lineage(account_id,plan_id);
    CREATE TABLE materializations(
      plan_id TEXT PRIMARY KEY,
      generation INTEGER NOT NULL,
      owner_token TEXT,
      lease_expires REAL,
      status TEXT NOT NULL CHECK(status IN ('reserved','bound')),
      mission_id TEXT UNIQUE,
      updated_at REAL NOT NULL
    );
    CREATE INDEX materialization_recovery_idx
      ON materializations(status,lease_expires,plan_id);
    CREATE TABLE runtime_plans(
      plan_id TEXT PRIMARY KEY,
      terminal INTEGER NOT NULL,
      recovery_after REAL NOT NULL,
      updated_at REAL NOT NULL
    );
    CREATE INDEX runtime_recovery_idx
      ON runtime_plans(terminal,recovery_after,plan_id);
    CREATE TRIGGER lineage_identity_no_update BEFORE UPDATE OF plan_id,account_id
      ON plan_lineage BEGIN SELECT RAISE(ABORT,'phase6 v3 lineage is immutable'); END;
    """

    def __init__(
        self,
        path: Path | str,
        gate: AgenticFeatureGateV3,
        *,
        fence_seconds: float = DEFAULT_FENCE_SECONDS,
    ) -> None:
        if type(gate) is not AgenticFeatureGateV3 or not gate.enabled:
            raise AgenticCoreV3Denied("Phase 6 V3 agentic core is disabled")
        self._path = Path(path)
        if not self._path.is_absolute() or self._path.name in {"", ".", ".."}:
            raise AgenticCoreV3ContractError(
                "an explicit absolute sidecar path is required"
            )
        if (
            isinstance(fence_seconds, bool)
            or not isinstance(fence_seconds, (int, float))
            or not math.isfinite(fence_seconds)
            or not 0.05 <= fence_seconds <= 300.0
        ):
            raise AgenticCoreV3ContractError(
                "materialization fence duration is invalid"
            )
        self._fence_seconds = float(fence_seconds)
        self._coord_path = self._path.with_name(
            f"{self._path.stem}.v3-coordination{self._path.suffix or '.sqlite3'}"
        )
        self._plans = AgenticStateStoreV1(self._path, AgenticFeatureGateV1(True))
        self._lock = threading.RLock()
        self.initialize()

    @property
    def plans(self) -> AgenticStateStoreV1:
        return self._plans

    @property
    def coordination_path(self) -> Path:
        return self._coord_path

    @property
    def kill_latched(self) -> bool:
        return self._plans.kill_latched

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._coord_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def initialize(self) -> None:
        with self._lock:
            self._coord_path.parent.mkdir(parents=True, exist_ok=True)
            connection = self._connect()
            try:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name NOT LIKE 'sqlite_%'"
                    )
                }
                if version == 0 and not tables:
                    connection.executescript(
                        "BEGIN IMMEDIATE;\n"
                        + self._DDL
                        + f"\nINSERT INTO metadata VALUES({SCHEMA_VERSION});"
                        + f"\nPRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;"
                    )
                else:
                    expected_tables = {
                        "metadata",
                        "budget_accounts",
                        "plan_lineage",
                        "materializations",
                        "runtime_plans",
                    }
                    indexes = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='index' "
                            "AND name NOT LIKE 'sqlite_%'"
                        )
                    }
                    triggers = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='trigger'"
                        )
                    }
                    metadata = connection.execute(
                        "SELECT schema_version FROM metadata"
                    ).fetchall()
                    if (
                        version != SCHEMA_VERSION
                        or tables != expected_tables
                        or indexes
                        != {
                            "budget_active_idx",
                            "budget_terminal_idx",
                            "lineage_account_idx",
                            "materialization_recovery_idx",
                            "runtime_recovery_idx",
                        }
                        or triggers != {"lineage_identity_no_update"}
                        or len(metadata) != 1
                        or metadata[0][0] != SCHEMA_VERSION
                    ):
                        raise AgenticCoreV3Error(
                            "Phase 6 V3 coordination schema diverges"
                        )
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    @staticmethod
    def _account_id(request_key: str) -> str:
        if _REQUEST_KEY.fullmatch(request_key) is None:
            raise AgenticCoreV3ContractError("request key is invalid")
        return f"budget_{hashlib.sha256(request_key.encode()).hexdigest()}"

    def reserve_request_budget(self, request_key: str, limit_seconds: float) -> str:
        if (
            isinstance(limit_seconds, bool)
            or not isinstance(limit_seconds, (int, float))
            or not math.isfinite(limit_seconds)
            or not 0.01 <= limit_seconds <= 86400
        ):
            raise AgenticCoreV3ContractError("compute budget is invalid")
        account_id = self._account_id(request_key)
        now = time.time()
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM budget_accounts WHERE account_id=?", (account_id,)
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO budget_accounts VALUES(?,?,?,?,?,NULL,NULL,NULL,NULL,NULL,NULL,?)",
                        (account_id, request_key, float(limit_seconds), 0.0, 0, now),
                    )
                elif row["request_key"] != request_key or float(
                    row["limit_seconds"]
                ) != float(limit_seconds):
                    raise AgenticCoreV3Denied(
                        "request key is already bound to another compute budget"
                    )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return account_id

    def register_plan(self, plan: PlanV1, account_id: str) -> PlanProjectionV1:
        _identifier(account_id, "account_id")
        projection = self._plans.create_plan(plan)
        now = time.time()
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                account = connection.execute(
                    "SELECT request_key FROM budget_accounts WHERE account_id=?",
                    (account_id,),
                ).fetchone()
                if account is None:
                    raise AgenticCoreV3Denied("compute account is unavailable")
                existing = connection.execute(
                    "SELECT account_id FROM plan_lineage WHERE plan_id=?",
                    (plan.plan_id,),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        "INSERT INTO plan_lineage VALUES(?,?,?)",
                        (plan.plan_id, account_id, now),
                    )
                    connection.execute(
                        "INSERT INTO runtime_plans VALUES(?,?,?,?)",
                        (plan.plan_id, 0, now, now),
                    )
                elif existing[0] != account_id:
                    raise AgenticCoreV3Denied("plan compute lineage diverges")
                connection.execute(
                    "UPDATE budget_accounts SET terminal_at=NULL,updated_at=? "
                    "WHERE account_id=?",
                    (now, account_id),
                )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return projection

    def account_for_plan(self, plan_id: str) -> str:
        canonical = _identifier(plan_id, "plan_id")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT account_id FROM plan_lineage WHERE plan_id=?", (canonical,)
            ).fetchone()
            if row is None:
                raise AgenticCoreV3Denied("plan has no V3 compute lineage")
            return str(row[0])
        finally:
            connection.close()

    @staticmethod
    def _snapshot(row: Mapping[str, object]) -> ComputeSnapshotV3:
        limit = float(row["limit_seconds"])
        consumed = float(row["consumed_seconds"])
        return ComputeSnapshotV3(
            str(row["account_id"]),
            limit,
            consumed,
            max(0.0, limit - consumed),
            bool(row["exhausted"]) or consumed >= limit,
        )

    def compute_snapshot(self, account_or_plan_id: str) -> ComputeSnapshotV3:
        canonical = _identifier(account_or_plan_id, "compute identity")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM budget_accounts WHERE account_id=?", (canonical,)
            ).fetchone()
            if row is None:
                lineage = connection.execute(
                    "SELECT account_id FROM plan_lineage WHERE plan_id=?", (canonical,)
                ).fetchone()
                if lineage is None:
                    raise AgenticCoreV3Denied("compute account is unavailable")
                row = connection.execute(
                    "SELECT * FROM budget_accounts WHERE account_id=?", (lineage[0],)
                ).fetchone()
            if row is None:
                raise AgenticCoreV3Error("compute lineage references no account")
            return self._snapshot(row)
        finally:
            connection.close()

    def begin_compute(self, account_or_plan_id: str, operation: str) -> ComputeLeaseV3:
        canonical = _identifier(account_or_plan_id, "compute identity")
        operation_id = _identifier(operation, "compute operation")
        plan_id: str | None = None
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM budget_accounts WHERE account_id=?", (canonical,)
                ).fetchone()
                if row is None:
                    lineage = connection.execute(
                        "SELECT account_id FROM plan_lineage WHERE plan_id=?",
                        (canonical,),
                    ).fetchone()
                    if lineage is None:
                        raise AgenticCoreV3Denied("compute account is unavailable")
                    plan_id = canonical
                    row = connection.execute(
                        "SELECT * FROM budget_accounts WHERE account_id=?",
                        (lineage[0],),
                    ).fetchone()
                if row is None:
                    raise AgenticCoreV3Error("compute lineage references no account")
                now = time.time()
                if row["active_token"] is not None:
                    raise AgenticCoreV3Denied(
                        "compute account already has an active reservation"
                    )
                snapshot = self._snapshot(row)
                if snapshot.exhausted:
                    raise ComputeBudgetExhaustedV3("BUDGET_EXHAUSTED")
                token = f"compute_{uuid.uuid4().hex}"
                connection.execute(
                    "UPDATE budget_accounts SET active_plan_id=?,active_token=?,"
                    "active_operation=?,active_started_wall=?,active_deadline_wall=?,"
                    "updated_at=? WHERE account_id=?",
                    (
                        plan_id,
                        token,
                        operation_id,
                        now,
                        now + snapshot.remaining_seconds,
                        now,
                        snapshot.account_id,
                    ),
                )
                connection.execute("COMMIT")
                return ComputeLeaseV3(
                    snapshot.account_id,
                    plan_id,
                    token,
                    operation_id,
                    snapshot.remaining_seconds,
                    time.monotonic(),
                )
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def finish_compute(
        self, lease: ComputeLeaseV3, *, force_exhausted: bool = False
    ) -> ComputeSnapshotV3:
        if type(lease) is not ComputeLeaseV3 or type(force_exhausted) is not bool:
            raise AgenticCoreV3ContractError("compute completion contract is invalid")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM budget_accounts WHERE account_id=?",
                    (lease.account_id,),
                ).fetchone()
                if row is None or row["active_token"] != lease.token:
                    raise AgenticCoreV3Denied("compute reservation identity diverges")
                monotonic_elapsed = max(0.0, time.monotonic() - lease.started_monotonic)
                wall_elapsed = max(0.0, time.time() - float(row["active_started_wall"]))
                consumed = float(row["consumed_seconds"]) + max(
                    monotonic_elapsed, wall_elapsed
                )
                exhausted = int(
                    force_exhausted or consumed >= float(row["limit_seconds"])
                )
                now = time.time()
                connection.execute(
                    "UPDATE budget_accounts SET consumed_seconds=?,exhausted=?,"
                    "active_plan_id=NULL,active_token=NULL,active_operation=NULL,"
                    "active_started_wall=NULL,active_deadline_wall=NULL,updated_at=? "
                    "WHERE account_id=?",
                    (consumed, exhausted, now, lease.account_id),
                )
                updated = connection.execute(
                    "SELECT * FROM budget_accounts WHERE account_id=?",
                    (lease.account_id,),
                ).fetchone()
                connection.execute("COMMIT")
                if updated is None:
                    raise AgenticCoreV3Error("compute account disappeared")
                return self._snapshot(updated)
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def recover_compute(
        self, *, limit: int = DEFAULT_RECOVERY_LIMIT
    ) -> tuple[str, ...]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1000
        ):
            raise AgenticCoreV3ContractError("recovery limit is invalid")
        now = time.time()
        exhausted_plans: list[str] = []
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    "SELECT * FROM budget_accounts WHERE active_token IS NOT NULL "
                    "ORDER BY active_deadline_wall,account_id LIMIT ?",
                    (limit,),
                ).fetchall()
                for row in rows:
                    elapsed = max(0.0, now - float(row["active_started_wall"]))
                    consumed = float(row["consumed_seconds"]) + elapsed
                    exhausted = int(consumed >= float(row["limit_seconds"]))
                    connection.execute(
                        "UPDATE budget_accounts SET consumed_seconds=?,exhausted=?,"
                        "active_plan_id=NULL,active_token=NULL,active_operation=NULL,"
                        "active_started_wall=NULL,active_deadline_wall=NULL,updated_at=? "
                        "WHERE account_id=?",
                        (consumed, exhausted, now, row["account_id"]),
                    )
                    if exhausted:
                        exhausted_plans.extend(
                            str(item[0])
                            for item in connection.execute(
                                "SELECT plan_id FROM plan_lineage WHERE account_id=? "
                                "ORDER BY plan_id LIMIT ?",
                                (row["account_id"], limit),
                            ).fetchall()
                        )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return tuple(sorted(set(exhausted_plans)))

    def claim_materialization(self, plan_id: str) -> FenceClaimV3:
        canonical = _identifier(plan_id, "plan_id")
        projection = self._plans.get_projection(canonical)
        if projection.mission_id is not None:
            return FenceClaimV3(canonical, 0, None, "bound", projection.mission_id)
        now = time.time()
        owner = f"owner_{uuid.uuid4().hex}"
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM materializations WHERE plan_id=?", (canonical,)
                ).fetchone()
                if row is None:
                    generation = 1
                    connection.execute(
                        "INSERT INTO materializations VALUES(?,?,?,?,?,?,?)",
                        (
                            canonical,
                            generation,
                            owner,
                            now + self._fence_seconds,
                            "reserved",
                            None,
                            now,
                        ),
                    )
                    disposition = "owner"
                    mission_id = None
                elif row["status"] == "bound":
                    generation = int(row["generation"])
                    owner = None
                    disposition = "bound"
                    mission_id = str(row["mission_id"])
                elif float(row["lease_expires"]) > now:
                    generation = int(row["generation"])
                    owner = None
                    disposition = "observer"
                    mission_id = None
                else:
                    generation = int(row["generation"]) + 1
                    connection.execute(
                        "UPDATE materializations SET generation=?,owner_token=?,"
                        "lease_expires=?,updated_at=? WHERE plan_id=?",
                        (
                            generation,
                            owner,
                            now + self._fence_seconds,
                            now,
                            canonical,
                        ),
                    )
                    disposition = "recovery_owner"
                    mission_id = None
                connection.execute("COMMIT")
                return FenceClaimV3(
                    canonical, generation, owner, disposition, mission_id
                )
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def renew_fence(self, claim: FenceClaimV3) -> bool:
        if type(claim) is not FenceClaimV3 or claim.owner_token is None:
            return False
        now = time.time()
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                changed = connection.execute(
                    "UPDATE materializations SET lease_expires=?,updated_at=? "
                    "WHERE plan_id=? AND status='reserved' AND generation=? "
                    "AND owner_token=?",
                    (
                        now + self._fence_seconds,
                        now,
                        claim.plan_id,
                        claim.generation,
                        claim.owner_token,
                    ),
                ).rowcount
                connection.execute("COMMIT")
                return changed == 1
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def fence_is_current(self, claim: FenceClaimV3) -> bool:
        if type(claim) is not FenceClaimV3 or claim.owner_token is None:
            return False
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT generation,owner_token,status,lease_expires FROM materializations "
                "WHERE plan_id=?",
                (claim.plan_id,),
            ).fetchone()
            return bool(
                row is not None
                and int(row["generation"]) == claim.generation
                and row["owner_token"] == claim.owner_token
                and row["status"] == "reserved"
                and float(row["lease_expires"]) > time.time()
            )
        finally:
            connection.close()

    def finalize_materialization(self, claim: FenceClaimV3, mission_id: str) -> bool:
        if type(claim) is not FenceClaimV3 or claim.owner_token is None:
            return False
        mission = _identifier(mission_id, "mission_id")
        now = time.time()
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                changed = connection.execute(
                    "UPDATE materializations SET status='bound',owner_token=NULL,"
                    "lease_expires=NULL,mission_id=?,updated_at=? WHERE plan_id=? "
                    "AND status='reserved' AND generation=? AND owner_token=?",
                    (
                        mission,
                        now,
                        claim.plan_id,
                        claim.generation,
                        claim.owner_token,
                    ),
                ).rowcount
                connection.execute("COMMIT")
                return changed == 1
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def observe_materialization(self, plan_id: str) -> FenceClaimV3:
        canonical = _identifier(plan_id, "plan_id")
        projection = self._plans.get_projection(canonical)
        if projection.mission_id is not None:
            return FenceClaimV3(canonical, 0, None, "bound", projection.mission_id)
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM materializations WHERE plan_id=?", (canonical,)
            ).fetchone()
            if row is None:
                return FenceClaimV3(canonical, 0, None, "unclaimed", None)
            return FenceClaimV3(
                canonical,
                int(row["generation"]),
                None,
                "bound" if row["status"] == "bound" else "observer",
                str(row["mission_id"]) if row["mission_id"] is not None else None,
            )
        finally:
            connection.close()

    def touch_runtime(
        self,
        plan_id: str,
        *,
        terminal: bool = False,
        recovery_delay: float = 0.0,
    ) -> None:
        canonical = _identifier(plan_id, "plan_id")
        if type(terminal) is not bool or recovery_delay < 0:
            raise AgenticCoreV3ContractError("runtime projection update is invalid")
        now = time.time()
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                changed = connection.execute(
                    "UPDATE runtime_plans SET terminal=?,recovery_after=?,updated_at=? "
                    "WHERE plan_id=?",
                    (int(terminal), now + recovery_delay, now, canonical),
                ).rowcount
                if changed != 1:
                    raise AgenticCoreV3Denied("runtime plan index is unavailable")
                if terminal:
                    account = connection.execute(
                        "SELECT account_id FROM plan_lineage WHERE plan_id=?",
                        (canonical,),
                    ).fetchone()
                    if account is not None:
                        nonterminal = int(
                            connection.execute(
                                "SELECT COUNT(*) FROM plan_lineage l JOIN runtime_plans r "
                                "ON r.plan_id=l.plan_id WHERE l.account_id=? AND r.terminal=0",
                                (account[0],),
                            ).fetchone()[0]
                        )
                        if nonterminal == 0:
                            connection.execute(
                                "UPDATE budget_accounts SET terminal_at=?,updated_at=? "
                                "WHERE account_id=?",
                                (now, now, account[0]),
                            )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def recovery_candidates(
        self, *, limit: int = DEFAULT_RECOVERY_LIMIT
    ) -> tuple[str, ...]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1000
        ):
            raise AgenticCoreV3ContractError("recovery limit is invalid")
        connection = self._connect()
        try:
            return tuple(
                str(row[0])
                for row in connection.execute(
                    "SELECT plan_id FROM runtime_plans WHERE terminal=0 "
                    "AND recovery_after<=? ORDER BY recovery_after,plan_id LIMIT ?",
                    (time.time(), limit),
                ).fetchall()
            )
        finally:
            connection.close()

    def compact(
        self,
        *,
        retention_seconds: float = DEFAULT_RETENTION_SECONDS,
        limit: int = 100,
    ) -> CompactionResultV3:
        if (
            isinstance(retention_seconds, bool)
            or not isinstance(retention_seconds, (int, float))
            or not math.isfinite(retention_seconds)
            or retention_seconds < 0
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1000
        ):
            raise AgenticCoreV3ContractError("compaction bounds are invalid")
        cutoff = time.time() - float(retention_seconds)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                plan_ids = [
                    str(row[0])
                    for row in connection.execute(
                        "SELECT plan_id FROM runtime_plans WHERE terminal=1 AND updated_at<=? "
                        "ORDER BY updated_at,plan_id LIMIT ?",
                        (cutoff, limit),
                    ).fetchall()
                ]
                materializations_deleted = 0
                accounts: set[str] = set()
                for plan_id in plan_ids:
                    account = connection.execute(
                        "SELECT account_id FROM plan_lineage WHERE plan_id=?",
                        (plan_id,),
                    ).fetchone()
                    if account is not None:
                        accounts.add(str(account[0]))
                    materializations_deleted += connection.execute(
                        "DELETE FROM materializations WHERE plan_id=?", (plan_id,)
                    ).rowcount
                    connection.execute(
                        "DELETE FROM plan_lineage WHERE plan_id=?", (plan_id,)
                    )
                    connection.execute(
                        "DELETE FROM runtime_plans WHERE plan_id=?", (plan_id,)
                    )
                accounts_deleted = 0
                for account_id in accounts:
                    remaining = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM plan_lineage WHERE account_id=?",
                            (account_id,),
                        ).fetchone()[0]
                    )
                    if remaining == 0:
                        accounts_deleted += connection.execute(
                            "DELETE FROM budget_accounts WHERE account_id=? AND terminal_at<=?",
                            (account_id, cutoff),
                        ).rowcount
                connection.execute("COMMIT")
                return CompactionResultV3(
                    len(plan_ids), accounts_deleted, materializations_deleted
                )
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def get_plan(self, plan_id: str) -> PlanV1:
        return self._plans.get_plan(plan_id)

    def get_projection(self, plan_id: str) -> PlanProjectionV1:
        return self._plans.get_projection(plan_id)

    def block_budget(self, plan_id: str) -> None:
        projection = self._plans.get_projection(plan_id)
        if projection.state not in {
            PlanStateV1.BLOCKED,
            PlanStateV1.COMPLETE,
            PlanStateV1.FAILED,
            PlanStateV1.CANCELLED,
        }:
            self._plans.set_state(plan_id, PlanStateV1.BLOCKED, "BUDGET_EXHAUSTED")
        self.touch_runtime(plan_id, terminal=True)


class _BudgetedVerifierV3:
    verifier_id = IndependentVerifierV1.verifier_id

    def __init__(
        self,
        bounded: Callable[[str, str, Callable[[], object], float | None], object],
        delegate: IndependentVerifierV1,
    ) -> None:
        self._bounded = bounded
        self._delegate = delegate

    def verify(
        self,
        plan: PlanV1,
        mission_store: MissionStore,
        mission_id: str,
        mission_plan_digest: str,
    ) -> VerificationReportV1:
        try:
            result = self._bounded(
                plan.plan_id,
                "verification",
                lambda: self._delegate.verify(
                    plan, mission_store, mission_id, mission_plan_digest
                ),
                None,
            )
        except (ComputeBudgetExhaustedV3, BoundedCallTimeoutV3):
            return VerificationReportV1(
                plan.plan_id,
                mission_id,
                "rejected",
                ("BUDGET_EXHAUSTED",),
                (),
                "0" * 64,
            )
        if type(result) is not VerificationReportV1:
            raise AgenticCoreV3Error("bounded verifier returned an invalid report")
        return result


class _BudgetAwareCoreV3(AgenticCoreV1):
    def __init__(
        self,
        state: AgenticStateStoreV3,
        missions: MissionStore,
        workspace: WorkspaceScopeV1,
        verifier: _BudgetedVerifierV3,
        critic: BoundedCriticV1,
    ) -> None:
        self._v3_state = state
        super().__init__(
            state.plans,
            missions,
            workspace,
            verifier=verifier,
            critic=critic,
        )

    def _sync(self, plan_id: str, mission: Mission) -> PlanProjectionV1:
        if self._v3_state.compute_snapshot(plan_id).exhausted:
            self._v3_state.block_budget(plan_id)
            return self._v3_state.get_projection(plan_id)
        projection = super()._sync(plan_id, mission)
        self._v3_state.touch_runtime(
            plan_id,
            terminal=projection.state
            in {
                PlanStateV1.COMPLETE,
                PlanStateV1.FAILED,
                PlanStateV1.CANCELLED,
                PlanStateV1.BLOCKED,
            },
            recovery_delay=1.0,
        )
        return projection


class AgenticCoreV3:
    """V3 planner/operator/verifier facade with durable bounded authority."""

    def __init__(
        self,
        state_store: AgenticStateStoreV3,
        mission_store: MissionStore,
        workspace_scope: WorkspaceScopeV1,
        *,
        verifier: IndependentVerifierV1 | None = None,
        critic: BoundedCriticV1 | None = None,
        sync_executor: BoundedSyncExecutorV3 | None = None,
    ) -> None:
        if (
            type(state_store) is not AgenticStateStoreV3
            or type(mission_store) is not MissionStore
            or type(workspace_scope) is not WorkspaceScopeV1
        ):
            raise AgenticCoreV3ContractError(
                "exact V3 state, MissionStore and workspace scope are required"
            )
        self._state = state_store
        self._missions = mission_store
        self._workspace = workspace_scope
        self._verifier = verifier or IndependentVerifierV1()
        self._critic = critic or BoundedCriticV1()
        self._executor = sync_executor or BoundedSyncExecutorV3()
        budgeted_verifier = _BudgetedVerifierV3(self._bounded_object, self._verifier)
        self._base = _BudgetAwareCoreV3(
            state_store,
            mission_store,
            workspace_scope,
            budgeted_verifier,
            self._critic,
        )

    @property
    def kill_latched(self) -> bool:
        return self._state.kill_latched

    def _bounded_object(
        self,
        account_or_plan_id: str,
        operation: str,
        callback: Callable[[], object],
        timeout_cap: float | None,
    ) -> object:
        lease = self._state.begin_compute(account_or_plan_id, operation)
        effective = lease.allowed_seconds
        if timeout_cap is not None:
            if (
                isinstance(timeout_cap, bool)
                or not isinstance(timeout_cap, (int, float))
                or not math.isfinite(timeout_cap)
                or timeout_cap <= 0
            ):
                self._state.finish_compute(lease)
                raise AgenticCoreV3ContractError("bounded timeout cap is invalid")
            effective = min(effective, float(timeout_cap))
        value: object | None = None
        failure: BaseException | None = None
        timed_out = False
        try:
            value = self._executor.invoke(callback, effective)
        except BaseException as exc:
            failure = exc
            timed_out = isinstance(exc, BoundedCallTimeoutV3)
        deadline_was_budget = effective >= lease.allowed_seconds - 1e-9
        snapshot = self._state.finish_compute(
            lease, force_exhausted=timed_out and deadline_was_budget
        )
        if snapshot.exhausted:
            if lease.plan_id is not None:
                self._state.block_budget(lease.plan_id)
            raise ComputeBudgetExhaustedV3("BUDGET_EXHAUSTED")
        if failure is not None:
            raise failure
        return value

    def _validate_plan_scope(self, plan: PlanV1) -> None:
        self._base._validate_plan_scope(plan)

    def submit_with_planner(
        self,
        goal: GoalV1,
        request_key: str,
        router: ModelRouterV1,
        adapter: PlannerAdapterV1,
    ) -> PlanProjectionV1:
        if self.kill_latched:
            raise AgenticCoreV3Denied("Phase 6 V3 kill switch is latched")
        account = self._state.reserve_request_budget(
            request_key, goal.budget.max_compute_seconds
        )
        planned = self._bounded_object(
            account,
            "planner",
            lambda: PlannerV2(router, adapter).plan(goal, request_key),
            None,
        )
        if type(planned) is not PlanV1:
            raise AgenticCoreV3Error("bounded planner returned an invalid plan")
        self._validate_plan_scope(planned)
        return self._state.register_plan(planned, account)

    def submit(
        self,
        goal: GoalV1,
        request_key: str,
        proposed_steps: Sequence[Mapping[str, object]],
    ) -> PlanProjectionV1:
        adapter = DeterministicPlannerAdapterV1(goal.workspace_id, proposed_steps)
        return self.submit_with_planner(
            goal, request_key, ModelRouterV1((adapter.descriptor,)), adapter
        )

    def repair(
        self,
        plan_id: str,
        request_key: str,
        proposed_steps: Sequence[Mapping[str, object]],
        findings: Sequence[str],
    ) -> PlanProjectionV1:
        source = self._state.get_plan(plan_id)
        projection = self._state.get_projection(plan_id)
        if projection.state not in {PlanStateV1.FAILED, PlanStateV1.BLOCKED}:
            raise AgenticCoreV3Denied("repair requires a failed or blocked source plan")
        critique = self._bounded_object(
            source.plan_id,
            "critic",
            lambda: self._critic.critique(source, findings),
            None,
        )
        if not getattr(critique, "repair_allowed", False):
            raise AgenticCoreV3Denied("bounded repair budget is exhausted")
        adapter = DeterministicPlannerAdapterV1(
            source.goal.workspace_id, proposed_steps
        )
        repaired = self._bounded_object(
            source.plan_id,
            "repair_planner",
            lambda: PlannerV2(ModelRouterV1((adapter.descriptor,)), adapter).plan(
                source.goal,
                request_key,
                repair_cycle=source.repair_cycle + 1,
                supersedes_plan_id=source.plan_id,
            ),
            None,
        )
        if type(repaired) is not PlanV1:
            raise AgenticCoreV3Error("bounded repair planner returned an invalid plan")
        self._validate_plan_scope(repaired)
        return self._state.register_plan(
            repaired, self._state.account_for_plan(source.plan_id)
        )

    @staticmethod
    def _title(plan: PlanV1) -> str:
        marker = f" [onyx-plan:{plan.plan_id}]"
        return f"{plan.goal.objective[: max(1, 240 - len(marker))]}{marker}"

    def materialize(
        self,
        plan_id: str,
        *,
        stage_hook: Callable[[str, FenceClaimV3], None] | None = None,
    ) -> AdmissionResultV1:
        if self.kill_latched:
            raise AgenticCoreV3Denied("Phase 6 V3 kill switch is latched")
        plan = self._state.get_plan(plan_id)
        self._validate_plan_scope(plan)
        projection = self._state.get_projection(plan_id)
        if self._state.compute_snapshot(plan_id).exhausted:
            self._state.block_budget(plan_id)
            return AdmissionResultV1(
                plan_id, PlanStateV1.BLOCKED, None, "BUDGET_EXHAUSTED"
            )
        if projection.mission_id is not None:
            return AdmissionResultV1(
                plan_id,
                projection.state,
                projection.mission_id,
                "idempotent_existing_mission_binding",
            )
        ordered = plan.ordered_steps()
        policies = tuple(capability_policy_v1(step.capability) for step in ordered)
        if any(policy.executor == "phase5" for policy in policies):
            self._state.plans.set_state(
                plan_id,
                PlanStateV1.WAITING_FOR_PHASE5,
                "local_catalog_read remains owned by accepted Phase 5 integration",
            )
            self._state.touch_runtime(plan_id, recovery_delay=60.0)
            return AdmissionResultV1(
                plan_id,
                PlanStateV1.WAITING_FOR_PHASE5,
                None,
                "phase5_catalog_dispatch_not_wired",
            )
        claim = self._state.claim_materialization(plan_id)
        if claim.disposition == "bound":
            return AdmissionResultV1(
                plan_id,
                self._state.get_projection(plan_id).state,
                claim.mission_id,
                "idempotent_fenced_binding",
            )
        if claim.disposition == "observer":
            return AdmissionResultV1(
                plan_id,
                projection.state,
                None,
                "materialization_winner_observed",
            )
        if stage_hook is not None:
            stage_hook("claimed", claim)
        if not self._state.renew_fence(claim):
            observed = self._state.observe_materialization(plan_id)
            return AdmissionResultV1(
                plan_id,
                self._state.get_projection(plan_id).state,
                observed.mission_id,
                "stale_owner_observed_winner",
            )
        if stage_hook is not None:
            stage_hook("before_create", claim)
        if not self._state.renew_fence(claim):
            observed = self._state.observe_materialization(plan_id)
            return AdmissionResultV1(
                plan_id,
                self._state.get_projection(plan_id).state,
                observed.mission_id,
                "stale_owner_observed_winner",
            )
        mission_steps: list[dict[str, object]] = []
        for step, policy in zip(ordered, policies, strict=True):
            if policy.mission_tool is None:
                raise AgenticCoreV3Error("mission tool binding is unavailable")
            mission_steps.append(
                {
                    "tool": policy.mission_tool,
                    "args": step.arguments,
                    "estimated_provider_cost": 0.0,
                }
            )
        mission = self._missions.create_idempotent(
            plan.plan_id,
            self._title(plan),
            mission_steps,
            tool_allowlist=sorted({str(item["tool"]) for item in mission_steps}),
            max_steps=plan.goal.budget.max_steps,
            max_seconds=plan.goal.budget.wall_seconds,
            max_retries=plan.goal.budget.max_retries_per_step,
            provider_cost_limit=0.0,
        )
        if stage_hook is not None:
            stage_hook("after_create", claim)
        if not self._state.renew_fence(claim) or not self._state.fence_is_current(
            claim
        ):
            observed = self._state.observe_materialization(plan_id)
            return AdmissionResultV1(
                plan_id,
                self._state.get_projection(plan_id).state,
                observed.mission_id,
                "stale_owner_observed_winner",
            )
        summary = self._missions.plan_summary(mission.id)
        self._state.plans.bind_mission(plan_id, mission.id, summary["plan_digest"])
        if not self._state.finalize_materialization(claim, mission.id):
            observed = self._state.observe_materialization(plan_id)
            return AdmissionResultV1(
                plan_id,
                self._state.get_projection(plan_id).state,
                observed.mission_id or mission.id,
                "binding_converged_after_fence_loss",
            )
        self._state.touch_runtime(plan_id, recovery_delay=1.0)
        return AdmissionResultV1(
            plan_id,
            PlanStateV1.AWAITING_APPROVAL,
            mission.id,
            "fenced_idempotent_mission_binding",
        )

    def execute_approved(
        self, plan_id: str, runner: ToolRunner | None = None
    ) -> Mission:
        plan = self._state.get_plan(plan_id)
        projection = self._state.get_projection(plan_id)
        if projection.mission_id is None:
            raise AgenticCoreV3Denied("plan has no stable mission binding")
        mission_id = projection.mission_id
        selected_runner = runner or run_mission_tool
        summary = self._missions.plan_summary(mission_id)
        expected: dict[str, StepV1] = {}
        for position, (step, materialized) in enumerate(
            zip(plan.ordered_steps(), summary["plan"]["steps"], strict=True)
        ):
            key = _sha(
                f"{mission_id}:{position}:{materialized['tool']}:"
                f"{_canonical_arguments(materialized['args'])}"
            )
            expected[key] = step

        def bounded_runner(tool: str, arguments: dict[str, Any], key: str) -> Any:
            step = expected.get(key)
            if step is None:
                raise AgenticCoreV3Denied(
                    "mission idempotency key is not bound to plan"
                )
            try:
                return self._bounded_object(
                    plan_id,
                    f"step.{step.step_id}",
                    lambda: selected_runner(tool, dict(arguments), key),
                    step.timeout_seconds,
                )
            except (BoundedCallTimeoutV3, ComputeBudgetExhaustedV3):
                try:
                    mission = self._missions.get(mission_id)
                    if mission.state in {
                        "awaiting_approval",
                        "running",
                        "waiting",
                        "paused",
                    }:
                        self._missions.cancel(mission_id)
                except (InvalidTransition, MissionError, KeyError):
                    pass
                exhausted = self._state.compute_snapshot(plan_id).exhausted
                if exhausted:
                    self._state.block_budget(plan_id)
                return {
                    "status": "failed",
                    "data": {
                        "reason": "BUDGET_EXHAUSTED" if exhausted else "STEP_TIMEOUT"
                    },
                    "evidence": [],
                    "postconditions": [
                        {"name": "compute_budget_respected", "satisfied": False}
                    ],
                    "waiting_for": None,
                }

        mission = self._base.execute_approved(plan_id, bounded_runner)
        projection = self._state.get_projection(plan_id)
        if projection.state in {
            PlanStateV1.COMPLETE,
            PlanStateV1.FAILED,
            PlanStateV1.CANCELLED,
            PlanStateV1.BLOCKED,
        }:
            self._state.touch_runtime(plan_id, terminal=True)
        return mission

    def verify(self, plan_id: str) -> VerificationReportV1:
        if self._state.compute_snapshot(plan_id).exhausted:
            self._state.block_budget(plan_id)
            raise ComputeBudgetExhaustedV3("BUDGET_EXHAUSTED")
        report = self._base.verify(plan_id)
        projection = self._state.get_projection(plan_id)
        self._state.touch_runtime(
            plan_id,
            terminal=projection.state in {PlanStateV1.COMPLETE, PlanStateV1.BLOCKED},
        )
        return report

    def cancel(self, plan_id: str, reason: str = "owner_cancelled") -> RecoveryRecordV1:
        record = self._base.cancel(plan_id, reason)
        self._state.touch_runtime(plan_id, terminal=True)
        return record

    def kill(
        self, reason: str = "owner_kill", *, limit: int = DEFAULT_RECOVERY_LIMIT
    ) -> tuple[RecoveryRecordV1, ...]:
        self._state.plans.latch_kill()
        records: list[RecoveryRecordV1] = []
        for plan_id in self._state.recovery_candidates(limit=limit):
            try:
                records.append(self.cancel(plan_id, reason))
            except (AgenticCoreV1Denied, InvalidTransition, MissionError, KeyError):
                projection = self._state.get_projection(plan_id)
                if projection.state not in {
                    PlanStateV1.BLOCKED,
                    PlanStateV1.COMPLETE,
                    PlanStateV1.FAILED,
                    PlanStateV1.CANCELLED,
                }:
                    self._state.plans.set_state(
                        plan_id, PlanStateV1.BLOCKED, "kill requires reconciliation"
                    )
                self._state.touch_runtime(plan_id, terminal=True)
                records.append(
                    RecoveryRecordV1(
                        plan_id,
                        projection.mission_id,
                        PlanStateV1.BLOCKED,
                        "kill_requires_reconciliation",
                    )
                )
        return tuple(records)

    def _recover_one(self, plan_id: str) -> RecoveryRecordV1:
        projection = self._state.get_projection(plan_id)
        if projection.mission_id is None:
            return RecoveryRecordV1(
                plan_id, None, projection.state, "metadata_only_plan"
            )
        try:
            mission = self._missions.get(projection.mission_id)
        except KeyError:
            self._state.plans.set_state(
                plan_id,
                PlanStateV1.BLOCKED,
                "bound MissionStore mission is unavailable",
            )
            self._state.touch_runtime(plan_id, terminal=True)
            return RecoveryRecordV1(
                plan_id,
                projection.mission_id,
                PlanStateV1.BLOCKED,
                "mission_binding_missing",
            )
        projected = self._base._sync(plan_id, mission)
        return RecoveryRecordV1(
            plan_id,
            projection.mission_id,
            projected.state,
            f"mission_store:{mission.state}",
        )

    def recover(
        self, *, limit: int = DEFAULT_RECOVERY_LIMIT
    ) -> tuple[RecoveryRecordV1, ...]:
        exhausted = self._state.recover_compute(limit=limit)
        for plan_id in exhausted:
            projection = self._state.get_projection(plan_id)
            if projection.mission_id is not None:
                try:
                    mission = self._missions.get(projection.mission_id)
                    if mission.state in {
                        "awaiting_approval",
                        "running",
                        "waiting",
                        "paused",
                    }:
                        self._missions.cancel(mission.id)
                except (InvalidTransition, MissionError, KeyError):
                    pass
            self._state.block_budget(plan_id)
        output: list[RecoveryRecordV1] = []
        for plan_id in self._state.recovery_candidates(limit=limit):
            if self._state.compute_snapshot(plan_id).exhausted:
                self._state.block_budget(plan_id)
                projection = self._state.get_projection(plan_id)
                output.append(
                    RecoveryRecordV1(
                        plan_id,
                        projection.mission_id,
                        PlanStateV1.BLOCKED,
                        "BUDGET_EXHAUSTED",
                    )
                )
                continue
            try:
                recovered = self._bounded_object(
                    plan_id,
                    "recovery",
                    lambda plan_id=plan_id: self._recover_one(plan_id),
                    None,
                )
            except ComputeBudgetExhaustedV3:
                projection = self._state.get_projection(plan_id)
                output.append(
                    RecoveryRecordV1(
                        plan_id,
                        projection.mission_id,
                        PlanStateV1.BLOCKED,
                        "BUDGET_EXHAUSTED",
                    )
                )
                continue
            if type(recovered) is not RecoveryRecordV1:
                raise AgenticCoreV3Error("bounded recovery returned an invalid record")
            output.append(recovered)
            terminal = recovered.state in {
                PlanStateV1.COMPLETE,
                PlanStateV1.FAILED,
                PlanStateV1.CANCELLED,
                PlanStateV1.BLOCKED,
            }
            self._state.touch_runtime(
                plan_id, terminal=terminal, recovery_delay=0.0 if terminal else 1.0
            )
        return tuple(output)

    def compact(
        self,
        *,
        retention_seconds: float = DEFAULT_RETENTION_SECONDS,
        limit: int = 100,
    ) -> CompactionResultV3:
        return self._state.compact(retention_seconds=retention_seconds, limit=limit)


def create_phase6_agentic_core_v3(
    *,
    gate: AgenticFeatureGateV3,
    sidecar_path: Path | str,
    mission_store: MissionStore,
    workspace_scope: WorkspaceScopeV1,
    fence_seconds: float = DEFAULT_FENCE_SECONDS,
) -> AgenticCoreV3:
    if type(gate) is not AgenticFeatureGateV3 or not gate.enabled:
        raise AgenticCoreV3Denied("Phase 6 V3 agentic core is disabled")
    state = AgenticStateStoreV3(sidecar_path, gate, fence_seconds=fence_seconds)
    return AgenticCoreV3(state, mission_store, workspace_scope)


__all__ = [
    "AgenticCoreV3",
    "AgenticCoreV3ContractError",
    "AgenticCoreV3Denied",
    "AgenticCoreV3Error",
    "AgenticFeatureGateV3",
    "AgenticStateStoreV3",
    "BoundedCallTimeoutV3",
    "BoundedSyncExecutorV3",
    "CompactionResultV3",
    "ComputeBudgetExhaustedV3",
    "FenceClaimV3",
    "artifact_root_v2",
    "create_phase6_agentic_core_v3",
]
