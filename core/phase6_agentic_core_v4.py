"""Isolated Phase 6 Agentic Core V4 candidate.

V4 preserves frozen V1-V3 and adds authenticated SQLite schemas, expired-only
CAS recovery, strict full-input mission materialization, and terminable process
execution with an explicit lifecycle. It is not live-wired.
"""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import os
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TypeVar

from core.mission_tools import run as run_mission_tool
from core.missions import (
    InvalidTransition,
    Mission,
    MissionError,
    MissionStore,
    ToolRunner,
)
from core.phase6_agentic_core_v1 import (
    AdmissionResultV1,
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
    VerificationReportV1,
    WorkspaceScopeV1,
    _canonical_arguments,
    _identifier,
    _sha,
    capability_policy_v1,
)
from core.phase6_agentic_core_v2 import PlannerV2, artifact_root_v2


FEATURE_FLAG = "ONYX_PHASE6_AGENTIC_CORE_V4"
SCHEMA_VERSION = 4
DEFAULT_FENCE_SECONDS = 30.0
DEFAULT_RECOVERY_LIMIT = 100
DEFAULT_RETENTION_SECONDS = 7 * 24 * 60 * 60
_REQUEST_KEY = re.compile(r"^[A-Za-z0-9_.:-]{8,192}$")
_T = TypeVar("_T")


class AgenticCoreV4Error(RuntimeError):
    """V4 authority, schema or execution failure."""


class AgenticCoreV4ContractError(ValueError):
    """A V4 caller supplied a non-canonical contract."""


class AgenticCoreV4Denied(PermissionError):
    """A V4 authority denied an operation."""


class ComputeBudgetExhaustedV4(AgenticCoreV4Denied):
    """The lineage compute account is terminally exhausted."""


class ProcessCallTimeoutV4(ComputeBudgetExhaustedV4):
    """A child process was terminated at its admitted deadline."""


class RemoteCallFailedV4(AgenticCoreV4Error):
    """A process-isolated callback raised in the child."""


@dataclass(frozen=True)
class AgenticFeatureGateV4:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise AgenticCoreV4ContractError("enabled must be an exact boolean")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "AgenticFeatureGateV4":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True)
class ComputeLeaseV4:
    account_id: str
    plan_id: str | None
    token: str
    operation: str
    allowed_seconds: float
    started_monotonic: float
    started_wall: float
    deadline_wall: float
    generation: int


@dataclass(frozen=True)
class ComputeSnapshotV4:
    account_id: str
    limit_seconds: float
    consumed_seconds: float
    remaining_seconds: float
    exhausted: bool


@dataclass(frozen=True)
class FenceClaimV4:
    plan_id: str
    generation: int
    owner_token: str | None
    disposition: str
    mission_id: str | None


@dataclass(frozen=True)
class CompactionResultV4:
    plans_deleted: int
    accounts_deleted: int
    materializations_deleted: int


def _process_worker(connection: Any) -> None:
    """Child entrypoint. Only returned values can cross the authority boundary."""

    try:
        while True:
            message = connection.recv()
            if message[0] == "close":
                connection.send(("closed",))
                return
            if message[0] != "call":
                connection.send(("error", "invalid process message"))
                continue
            _kind, callback, args, kwargs = message
            try:
                connection.send(("ok", callback(*args, **kwargs)))
            except BaseException as exc:
                connection.send(
                    ("error", f"{type(exc).__module__}.{type(exc).__qualname__}: {exc}")
                )
    except (EOFError, BrokenPipeError, OSError):
        return
    finally:
        connection.close()


class TerminableProcessExecutorV4:
    """Spawn-process executor with synchronous terminate/join and close sentinel."""

    def __init__(self, *, start_method: str = "spawn") -> None:
        if start_method != "spawn":
            raise AgenticCoreV4ContractError("V4 requires portable spawn isolation")
        self._context = multiprocessing.get_context(start_method)
        self._lock = threading.RLock()
        self._process: multiprocessing.Process | None = None
        self._connection: Any | None = None
        self._closed = False

    def __enter__(self) -> "TerminableProcessExecutorV4":
        if self.closed:
            raise AgenticCoreV4Denied("process executor is closed")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def worker_pid(self) -> int | None:
        with self._lock:
            if self._process is None or not self._process.is_alive():
                return None
            return self._process.pid

    def _start(self) -> None:
        if self._process is not None:
            if self._process.is_alive():
                return
            self._process.join(timeout=0)
            self._process.close()
            self._process = None
        parent, child = self._context.Pipe(duplex=True)
        process = self._context.Process(
            target=_process_worker,
            args=(child,),
            name="onyx-phase6-v4-terminable",
            daemon=False,
        )
        process.start()
        child.close()
        self._connection = parent
        self._process = process

    def _terminate(self) -> None:
        connection, process = self._connection, self._process
        self._connection = None
        self._process = None
        if connection is not None:
            connection.close()
        if process is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=5.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=5.0)
            process.close()

    def invoke(
        self,
        callback: Callable[..., _T],
        timeout_seconds: float,
        *args: object,
        **kwargs: object,
    ) -> _T:
        if not callable(callback):
            raise AgenticCoreV4ContractError("callback must be callable")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise AgenticCoreV4ContractError("process deadline is invalid")
        with self._lock:
            if self._closed:
                raise AgenticCoreV4Denied("process executor is closed")
            self._start()
            assert self._connection is not None
            try:
                self._connection.send(("call", callback, args, kwargs))
            except Exception:
                self._terminate()
                raise
            if not self._connection.poll(float(timeout_seconds)):
                self._terminate()
                raise ProcessCallTimeoutV4("BUDGET_EXHAUSTED")
            try:
                message = self._connection.recv()
            except (EOFError, BrokenPipeError, OSError) as exc:
                self._terminate()
                raise AgenticCoreV4Error(
                    "isolated process ended without a result"
                ) from exc
            if message[0] == "error":
                raise RemoteCallFailedV4(str(message[1]))
            if message[0] != "ok":
                raise AgenticCoreV4Error(
                    "isolated process returned an invalid envelope"
                )
            return message[1]  # type: ignore[no-any-return]

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._connection is not None and self._process is not None:
                try:
                    if self._process.is_alive():
                        self._connection.send(("close",))
                        if self._connection.poll(2.0):
                            self._connection.recv()
                        self._process.join(timeout=2.0)
                except (EOFError, BrokenPipeError, OSError):
                    pass
            self._terminate()


def _normalize_sql(value: str) -> str:
    return " ".join(value.strip().rstrip(";").split()).lower()


def _schema_signature(connection: sqlite3.Connection) -> str:
    objects = []
    for row in connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
    ):
        objects.append((row[0], row[1], row[2], _normalize_sql(str(row[3]))))
    tables = [row[1] for row in objects if row[0] == "table"]
    details: dict[str, object] = {}
    for table in tables:
        details[f"table_xinfo:{table}"] = [
            tuple(row) for row in connection.execute(f"PRAGMA table_xinfo('{table}')")
        ]
        details[f"foreign_key_list:{table}"] = [
            tuple(row)
            for row in connection.execute(f"PRAGMA foreign_key_list('{table}')")
        ]
        indexes = [
            tuple(row) for row in connection.execute(f"PRAGMA index_list('{table}')")
        ]
        details[f"index_list:{table}"] = indexes
        for index in indexes:
            details[f"index_xinfo:{index[1]}"] = [
                tuple(row)
                for row in connection.execute(f"PRAGMA index_xinfo('{index[1]}')")
            ]
    payload = {"objects": objects, "details": details}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class AgenticStateStoreV4:
    """Frozen V1 evidence plus canonically authenticated V4 coordination."""

    _DDL = (
        "CREATE TABLE metadata(schema_version INTEGER NOT NULL "
        "CHECK(schema_version=4))",
        "CREATE TABLE budget_accounts("
        "account_id TEXT PRIMARY KEY,request_key TEXT NOT NULL UNIQUE,"
        "limit_seconds REAL NOT NULL CHECK(limit_seconds>0),"
        "consumed_seconds REAL NOT NULL CHECK(consumed_seconds>=0),"
        "exhausted INTEGER NOT NULL CHECK(exhausted IN (0,1)),"
        "active_plan_id TEXT,active_token TEXT,active_operation TEXT,"
        "active_started_wall REAL,active_deadline_wall REAL,"
        "generation INTEGER NOT NULL CHECK(generation>=0),"
        "terminal_at REAL,updated_at REAL NOT NULL)",
        "CREATE INDEX budget_expired_idx ON budget_accounts("
        "active_deadline_wall,account_id) WHERE active_token IS NOT NULL",
        "CREATE INDEX budget_terminal_idx ON budget_accounts(terminal_at,account_id)",
        "CREATE TABLE plan_lineage("
        "plan_id TEXT PRIMARY KEY,account_id TEXT NOT NULL "
        "REFERENCES budget_accounts(account_id),created_at REAL NOT NULL)",
        "CREATE INDEX lineage_account_idx ON plan_lineage(account_id,plan_id)",
        "CREATE TABLE materializations("
        "plan_id TEXT PRIMARY KEY,generation INTEGER NOT NULL CHECK(generation>=1),"
        "owner_token TEXT,lease_expires REAL,"
        "status TEXT NOT NULL CHECK(status IN ('reserved','bound')),"
        "mission_id TEXT UNIQUE,updated_at REAL NOT NULL)",
        "CREATE INDEX materialization_recovery_idx ON materializations("
        "status,lease_expires,plan_id)",
        "CREATE TABLE runtime_plans("
        "plan_id TEXT PRIMARY KEY,terminal INTEGER NOT NULL "
        "CHECK(terminal IN (0,1)),updated_at REAL NOT NULL)",
        "CREATE INDEX runtime_terminal_idx ON runtime_plans("
        "terminal,updated_at,plan_id)",
        "CREATE TRIGGER lineage_identity_no_update BEFORE UPDATE OF plan_id,account_id "
        "ON plan_lineage BEGIN SELECT RAISE(ABORT,'phase6 v4 lineage is immutable'); END",
    )

    def __init__(
        self,
        path: Path | str,
        gate: AgenticFeatureGateV4,
        *,
        fence_seconds: float = DEFAULT_FENCE_SECONDS,
    ) -> None:
        if type(gate) is not AgenticFeatureGateV4 or not gate.enabled:
            raise AgenticCoreV4Denied("Phase 6 V4 agentic core is disabled")
        self._path = Path(path)
        if not self._path.is_absolute() or self._path.name in {"", ".", ".."}:
            raise AgenticCoreV4ContractError(
                "an explicit absolute sidecar path is required"
            )
        if (
            isinstance(fence_seconds, bool)
            or not isinstance(fence_seconds, (int, float))
            or not math.isfinite(fence_seconds)
            or not 0.05 <= fence_seconds <= 300.0
        ):
            raise AgenticCoreV4ContractError(
                "materialization fence duration is invalid"
            )
        self._fence_seconds = float(fence_seconds)
        self._coord_path = self._path.with_name(
            f"{self._path.stem}.v4-coordination{self._path.suffix or '.sqlite3'}"
        )
        self._plans = AgenticStateStoreV1(self._path, AgenticFeatureGateV1(True))
        self._lock = threading.RLock()
        self._expected_signature = self._build_expected_signature()
        self.initialize()

    @classmethod
    def _build_expected_signature(cls) -> str:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            for statement in cls._DDL:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO metadata(schema_version) VALUES(?)", (SCHEMA_VERSION,)
            )
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            return _schema_signature(connection)
        finally:
            connection.close()

    @property
    def plans(self) -> AgenticStateStoreV1:
        return self._plans

    @property
    def coordination_path(self) -> Path:
        return self._coord_path

    @property
    def schema_signature(self) -> str:
        return self._expected_signature

    @property
    def kill_latched(self) -> bool:
        return self._plans.kill_latched

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._coord_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def initialize(self) -> None:
        with self._lock:
            self._coord_path.parent.mkdir(parents=True, exist_ok=True)
            connection = self._connect()
            try:
                existing = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                ).fetchone()[0]
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if existing == 0 and version == 0:
                    connection.execute("BEGIN IMMEDIATE")
                    for statement in self._DDL:
                        connection.execute(statement)
                    connection.execute(
                        "INSERT INTO metadata(schema_version) VALUES(?)",
                        (SCHEMA_VERSION,),
                    )
                    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    connection.execute("COMMIT")
                signature = _schema_signature(connection)
                metadata = connection.execute(
                    "SELECT schema_version FROM metadata"
                ).fetchall()
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
                if (
                    signature != self._expected_signature
                    or int(connection.execute("PRAGMA user_version").fetchone()[0])
                    != SCHEMA_VERSION
                    or [tuple(row) for row in metadata] != [(SCHEMA_VERSION,)]
                    or integrity != "ok"
                    or foreign_keys
                ):
                    raise AgenticCoreV4Error(
                        "Phase 6 V4 coordination schema authentication failed"
                    )
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    @staticmethod
    def _account_id(request_key: str) -> str:
        if (
            not isinstance(request_key, str)
            or _REQUEST_KEY.fullmatch(request_key) is None
        ):
            raise AgenticCoreV4ContractError("request key is invalid")
        return f"budget_{hashlib.sha256(request_key.encode('utf-8')).hexdigest()}"

    @staticmethod
    def _validate_limit(limit: int) -> None:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 1000
        ):
            raise AgenticCoreV4ContractError("limit is invalid")

    def reserve_request_budget(self, request_key: str, limit_seconds: float) -> str:
        if (
            isinstance(limit_seconds, bool)
            or not isinstance(limit_seconds, (int, float))
            or not math.isfinite(limit_seconds)
            or not 0.01 <= limit_seconds <= 86400
        ):
            raise AgenticCoreV4ContractError("compute budget is invalid")
        account_id = self._account_id(request_key)
        now = time.time()
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT request_key,limit_seconds FROM budget_accounts "
                    "WHERE account_id=?",
                    (account_id,),
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO budget_accounts VALUES(?,?,?,?,?,NULL,NULL,NULL,"
                        "NULL,NULL,0,NULL,?)",
                        (account_id, request_key, float(limit_seconds), 0.0, 0, now),
                    )
                elif row["request_key"] != request_key or float(
                    row["limit_seconds"]
                ) != float(limit_seconds):
                    raise AgenticCoreV4Denied(
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
        canonical_account = _identifier(account_id, "account_id")
        projection = self._plans.create_plan(plan)
        now = time.time()
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                if (
                    connection.execute(
                        "SELECT 1 FROM budget_accounts WHERE account_id=?",
                        (canonical_account,),
                    ).fetchone()
                    is None
                ):
                    raise AgenticCoreV4Denied("compute account is unavailable")
                existing = connection.execute(
                    "SELECT account_id FROM plan_lineage WHERE plan_id=?",
                    (plan.plan_id,),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        "INSERT INTO plan_lineage VALUES(?,?,?)",
                        (plan.plan_id, canonical_account, now),
                    )
                    connection.execute(
                        "INSERT INTO runtime_plans VALUES(?,?,?)",
                        (plan.plan_id, 0, now),
                    )
                elif existing[0] != canonical_account:
                    raise AgenticCoreV4Denied("plan compute lineage diverges")
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
                raise AgenticCoreV4Denied("plan has no V4 compute lineage")
            return str(row[0])
        finally:
            connection.close()

    @staticmethod
    def _snapshot(row: Mapping[str, object]) -> ComputeSnapshotV4:
        limit = float(row["limit_seconds"])
        consumed = float(row["consumed_seconds"])
        return ComputeSnapshotV4(
            str(row["account_id"]),
            limit,
            consumed,
            max(0.0, limit - consumed),
            bool(row["exhausted"]) or consumed >= limit,
        )

    def compute_snapshot(self, account_or_plan_id: str) -> ComputeSnapshotV4:
        canonical = _identifier(account_or_plan_id, "compute identity")
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM budget_accounts WHERE account_id=?", (canonical,)
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT b.* FROM budget_accounts b JOIN plan_lineage l "
                    "ON l.account_id=b.account_id WHERE l.plan_id=?",
                    (canonical,),
                ).fetchone()
            if row is None:
                raise AgenticCoreV4Denied("compute account is unavailable")
            return self._snapshot(row)
        finally:
            connection.close()

    def begin_compute(self, account_or_plan_id: str, operation: str) -> ComputeLeaseV4:
        canonical = _identifier(account_or_plan_id, "compute identity")
        operation_id = _identifier(operation, "compute operation")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM budget_accounts WHERE account_id=?", (canonical,)
                ).fetchone()
                plan_id: str | None = None
                if row is None:
                    plan_id = canonical
                    row = connection.execute(
                        "SELECT b.* FROM budget_accounts b JOIN plan_lineage l "
                        "ON l.account_id=b.account_id WHERE l.plan_id=?",
                        (canonical,),
                    ).fetchone()
                if row is None:
                    raise AgenticCoreV4Denied("compute account is unavailable")
                if row["active_token"] is not None:
                    raise AgenticCoreV4Denied(
                        "compute account already has an active reservation"
                    )
                snapshot = self._snapshot(row)
                if snapshot.exhausted:
                    raise ComputeBudgetExhaustedV4("BUDGET_EXHAUSTED")
                now = time.time()
                deadline = now + snapshot.remaining_seconds
                generation = int(row["generation"]) + 1
                token = f"compute_{uuid.uuid4().hex}"
                changed = connection.execute(
                    "UPDATE budget_accounts SET active_plan_id=?,active_token=?,"
                    "active_operation=?,active_started_wall=?,active_deadline_wall=?,"
                    "generation=?,updated_at=? WHERE account_id=? AND generation=? "
                    "AND active_token IS NULL",
                    (
                        plan_id,
                        token,
                        operation_id,
                        now,
                        deadline,
                        generation,
                        now,
                        row["account_id"],
                        row["generation"],
                    ),
                ).rowcount
                if changed != 1:
                    raise AgenticCoreV4Denied("compute reservation race lost")
                connection.execute("COMMIT")
                return ComputeLeaseV4(
                    str(row["account_id"]),
                    plan_id,
                    token,
                    operation_id,
                    snapshot.remaining_seconds,
                    time.monotonic(),
                    now,
                    deadline,
                    generation,
                )
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def renew_compute(
        self, lease: ComputeLeaseV4, *, extend_seconds: float
    ) -> ComputeLeaseV4:
        if type(lease) is not ComputeLeaseV4:
            raise AgenticCoreV4ContractError("exact compute lease is required")
        if (
            isinstance(extend_seconds, bool)
            or not isinstance(extend_seconds, (int, float))
            or not math.isfinite(extend_seconds)
            or extend_seconds <= 0
        ):
            raise AgenticCoreV4ContractError("compute lease extension is invalid")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                now = time.time()
                deadline = now + float(extend_seconds)
                generation = lease.generation + 1
                changed = connection.execute(
                    "UPDATE budget_accounts SET active_deadline_wall=?,generation=?,"
                    "updated_at=? WHERE account_id=? AND active_token=? "
                    "AND active_deadline_wall=? AND generation=?",
                    (
                        deadline,
                        generation,
                        now,
                        lease.account_id,
                        lease.token,
                        lease.deadline_wall,
                        lease.generation,
                    ),
                ).rowcount
                if changed != 1:
                    raise AgenticCoreV4Denied("compute lease renewal race lost")
                connection.execute("COMMIT")
                return ComputeLeaseV4(
                    lease.account_id,
                    lease.plan_id,
                    lease.token,
                    lease.operation,
                    float(extend_seconds),
                    lease.started_monotonic,
                    lease.started_wall,
                    deadline,
                    generation,
                )
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def finish_compute(
        self, lease: ComputeLeaseV4, *, force_exhausted: bool = False
    ) -> ComputeSnapshotV4:
        if type(lease) is not ComputeLeaseV4 or type(force_exhausted) is not bool:
            raise AgenticCoreV4ContractError("compute completion contract is invalid")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM budget_accounts WHERE account_id=?",
                    (lease.account_id,),
                ).fetchone()
                if row is None:
                    raise AgenticCoreV4Denied("compute account is unavailable")
                elapsed = max(
                    0.0,
                    time.monotonic() - lease.started_monotonic,
                    time.time() - lease.started_wall,
                )
                consumed = float(row["consumed_seconds"]) + elapsed
                exhausted = int(
                    force_exhausted or consumed >= float(row["limit_seconds"])
                )
                now = time.time()
                changed = connection.execute(
                    "UPDATE budget_accounts SET consumed_seconds=?,exhausted=?,"
                    "active_plan_id=NULL,active_token=NULL,active_operation=NULL,"
                    "active_started_wall=NULL,active_deadline_wall=NULL,generation=?,"
                    "updated_at=? WHERE account_id=? AND active_token=? "
                    "AND active_deadline_wall=? AND generation=?",
                    (
                        consumed,
                        exhausted,
                        lease.generation + 1,
                        now,
                        lease.account_id,
                        lease.token,
                        lease.deadline_wall,
                        lease.generation,
                    ),
                ).rowcount
                if changed != 1:
                    raise AgenticCoreV4Denied("compute completion fence diverged")
                updated = connection.execute(
                    "SELECT * FROM budget_accounts WHERE account_id=?",
                    (lease.account_id,),
                ).fetchone()
                connection.execute("COMMIT")
                if updated is None:
                    raise AgenticCoreV4Error("compute account disappeared")
                return self._snapshot(updated)
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def recover_compute(
        self,
        *,
        limit: int = DEFAULT_RECOVERY_LIMIT,
        now: float | None = None,
        before_cas: Callable[[ComputeLeaseV4], None] | None = None,
    ) -> tuple[str, ...]:
        """Close only expired leases with an exact persisted CAS fence."""

        self._validate_limit(limit)
        observed_now = time.time() if now is None else float(now)
        if not math.isfinite(observed_now):
            raise AgenticCoreV4ContractError("recovery time is invalid")
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM budget_accounts WHERE active_token IS NOT NULL "
                "AND active_deadline_wall<=? ORDER BY active_deadline_wall,account_id "
                "LIMIT ?",
                (observed_now, limit),
            ).fetchall()
        finally:
            connection.close()
        recovered: list[str] = []
        for row in rows:
            lease = ComputeLeaseV4(
                str(row["account_id"]),
                str(row["active_plan_id"])
                if row["active_plan_id"] is not None
                else None,
                str(row["active_token"]),
                str(row["active_operation"]),
                max(
                    0.0,
                    float(row["active_deadline_wall"])
                    - float(row["active_started_wall"]),
                ),
                0.0,
                float(row["active_started_wall"]),
                float(row["active_deadline_wall"]),
                int(row["generation"]),
            )
            if before_cas is not None:
                before_cas(lease)
            with self._lock:
                candidate = self._connect()
                try:
                    candidate.execute("BEGIN IMMEDIATE")
                    elapsed = max(0.0, observed_now - lease.started_wall)
                    consumed = float(row["consumed_seconds"]) + elapsed
                    exhausted = int(consumed >= float(row["limit_seconds"]))
                    changed = candidate.execute(
                        "UPDATE budget_accounts SET consumed_seconds=?,exhausted=?,"
                        "active_plan_id=NULL,active_token=NULL,active_operation=NULL,"
                        "active_started_wall=NULL,active_deadline_wall=NULL,generation=?,"
                        "updated_at=? WHERE account_id=? AND active_token=? "
                        "AND active_deadline_wall=? AND generation=? "
                        "AND active_deadline_wall<=?",
                        (
                            consumed,
                            exhausted,
                            lease.generation + 1,
                            observed_now,
                            lease.account_id,
                            lease.token,
                            lease.deadline_wall,
                            lease.generation,
                            observed_now,
                        ),
                    ).rowcount
                    if changed == 1:
                        plan_rows = candidate.execute(
                            "SELECT plan_id FROM plan_lineage WHERE account_id=? "
                            "ORDER BY plan_id LIMIT ?",
                            (lease.account_id, limit - len(recovered)),
                        ).fetchall()
                        recovered.extend(str(item[0]) for item in plan_rows)
                    candidate.execute("COMMIT")
                except Exception:
                    if candidate.in_transaction:
                        candidate.execute("ROLLBACK")
                    raise
                finally:
                    candidate.close()
            if len(recovered) >= limit:
                break
        return tuple(recovered[:limit])

    def recovery_candidates(
        self, *, limit: int = DEFAULT_RECOVERY_LIMIT, now: float | None = None
    ) -> tuple[str, ...]:
        self._validate_limit(limit)
        observed_now = time.time() if now is None else float(now)
        connection = self._connect()
        try:
            return tuple(
                str(row[0])
                for row in connection.execute(
                    "SELECT plan_id FROM runtime_plans WHERE terminal=0 "
                    "AND updated_at<=? ORDER BY terminal,updated_at,plan_id LIMIT ?",
                    (observed_now, limit),
                ).fetchall()
            )
        finally:
            connection.close()

    def touch_runtime(self, plan_id: str, *, terminal: bool = False) -> None:
        canonical = _identifier(plan_id, "plan_id")
        if type(terminal) is not bool:
            raise AgenticCoreV4ContractError("terminal must be exact boolean")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                changed = connection.execute(
                    "UPDATE runtime_plans SET terminal=?,updated_at=? WHERE plan_id=?",
                    (int(terminal), time.time(), canonical),
                ).rowcount
                if changed != 1:
                    raise AgenticCoreV4Denied("runtime plan index is unavailable")
                if terminal:
                    account = connection.execute(
                        "SELECT account_id FROM plan_lineage WHERE plan_id=?",
                        (canonical,),
                    ).fetchone()
                    if account is not None:
                        active = connection.execute(
                            "SELECT COUNT(*) FROM runtime_plans r JOIN plan_lineage l "
                            "ON l.plan_id=r.plan_id WHERE l.account_id=? AND r.terminal=0",
                            (account[0],),
                        ).fetchone()[0]
                        if int(active) == 0:
                            now = time.time()
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

    def get_plan(self, plan_id: str) -> PlanV1:
        return self._plans.get_plan(plan_id)

    def get_projection(self, plan_id: str) -> PlanProjectionV1:
        return self._plans.get_projection(plan_id)

    def block_budget(self, plan_id: str) -> None:
        canonical = _identifier(plan_id, "plan_id")
        projection = self._plans.get_projection(canonical)
        if projection.state not in {
            PlanStateV1.COMPLETE,
            PlanStateV1.FAILED,
            PlanStateV1.CANCELLED,
            PlanStateV1.BLOCKED,
        }:
            self._plans.set_state(canonical, PlanStateV1.BLOCKED, "BUDGET_EXHAUSTED")
        self.touch_runtime(canonical, terminal=True)

    def claim_materialization(self, plan_id: str) -> FenceClaimV4:
        canonical = _identifier(plan_id, "plan_id")
        projection = self._plans.get_projection(canonical)
        if projection.mission_id is not None:
            return FenceClaimV4(canonical, 0, None, "bound", projection.mission_id)
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
                    generation, disposition, mission_id = 1, "owner", None
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
                elif row["status"] == "bound":
                    generation = int(row["generation"])
                    disposition, mission_id, owner = (
                        "bound",
                        str(row["mission_id"]),
                        None,
                    )
                elif float(row["lease_expires"]) > now:
                    generation = int(row["generation"])
                    disposition, mission_id, owner = "observer", None, None
                else:
                    generation = int(row["generation"]) + 1
                    disposition, mission_id = "recovery_owner", None
                    connection.execute(
                        "UPDATE materializations SET generation=?,owner_token=?,"
                        "lease_expires=?,updated_at=? WHERE plan_id=? AND generation=?",
                        (
                            generation,
                            owner,
                            now + self._fence_seconds,
                            now,
                            canonical,
                            row["generation"],
                        ),
                    )
                connection.execute("COMMIT")
                return FenceClaimV4(
                    canonical, generation, owner, disposition, mission_id
                )
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def renew_fence(self, claim: FenceClaimV4) -> bool:
        if type(claim) is not FenceClaimV4 or claim.owner_token is None:
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

    def fence_is_current(self, claim: FenceClaimV4) -> bool:
        if type(claim) is not FenceClaimV4 or claim.owner_token is None:
            return False
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT generation,owner_token,status,lease_expires "
                "FROM materializations WHERE plan_id=?",
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

    def finalize_materialization(self, claim: FenceClaimV4, mission_id: str) -> bool:
        if type(claim) is not FenceClaimV4 or claim.owner_token is None:
            return False
        mission = _identifier(mission_id, "mission_id")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                changed = connection.execute(
                    "UPDATE materializations SET status='bound',owner_token=NULL,"
                    "lease_expires=NULL,mission_id=?,updated_at=? WHERE plan_id=? "
                    "AND status='reserved' AND generation=? AND owner_token=? "
                    "AND lease_expires>?",
                    (
                        mission,
                        time.time(),
                        claim.plan_id,
                        claim.generation,
                        claim.owner_token,
                        time.time(),
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

    def observe_materialization(self, plan_id: str) -> FenceClaimV4:
        canonical = _identifier(plan_id, "plan_id")
        projection = self._plans.get_projection(canonical)
        if projection.mission_id is not None:
            return FenceClaimV4(canonical, 0, None, "bound", projection.mission_id)
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM materializations WHERE plan_id=?", (canonical,)
            ).fetchone()
            if row is None:
                return FenceClaimV4(canonical, 0, None, "unclaimed", None)
            return FenceClaimV4(
                canonical,
                int(row["generation"]),
                None,
                "bound" if row["status"] == "bound" else "observer",
                str(row["mission_id"]) if row["mission_id"] is not None else None,
            )
        finally:
            connection.close()

    def compact(
        self,
        *,
        retention_seconds: float = DEFAULT_RETENTION_SECONDS,
        limit: int = 100,
    ) -> CompactionResultV4:
        if (
            isinstance(retention_seconds, bool)
            or not isinstance(retention_seconds, (int, float))
            or not math.isfinite(retention_seconds)
            or retention_seconds < 0
        ):
            raise AgenticCoreV4ContractError("retention is invalid")
        self._validate_limit(limit)
        cutoff = time.time() - float(retention_seconds)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                plans = [
                    str(row[0])
                    for row in connection.execute(
                        "SELECT plan_id FROM runtime_plans WHERE terminal=1 "
                        "AND updated_at<? ORDER BY terminal,updated_at,plan_id LIMIT ?",
                        (cutoff, limit),
                    ).fetchall()
                ]
                materializations_deleted = 0
                for plan_id in plans:
                    materializations_deleted += connection.execute(
                        "DELETE FROM materializations WHERE plan_id=? AND status='bound'",
                        (plan_id,),
                    ).rowcount
                    connection.execute(
                        "DELETE FROM runtime_plans WHERE plan_id=?", (plan_id,)
                    )
                    connection.execute(
                        "DELETE FROM plan_lineage WHERE plan_id=?", (plan_id,)
                    )
                account_rows = connection.execute(
                    "SELECT account_id FROM budget_accounts WHERE terminal_at IS NOT NULL "
                    "AND terminal_at<? AND NOT EXISTS(SELECT 1 FROM plan_lineage l "
                    "WHERE l.account_id=budget_accounts.account_id) "
                    "ORDER BY terminal_at,account_id LIMIT ?",
                    (cutoff, limit),
                ).fetchall()
                accounts_deleted = 0
                for account in account_rows:
                    accounts_deleted += connection.execute(
                        "DELETE FROM budget_accounts WHERE account_id=?",
                        (account[0],),
                    ).rowcount
                connection.execute("COMMIT")
                return CompactionResultV4(
                    len(plans), accounts_deleted, materializations_deleted
                )
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()


class StrictMissionMaterializerV4:
    """Exact-input ledger in front of frozen MissionStore.create_idempotent."""

    _DDL = (
        "CREATE TABLE input_bindings("
        "materialization_key TEXT PRIMARY KEY,input_digest TEXT NOT NULL,"
        "canonical_input TEXT NOT NULL,created_at REAL NOT NULL)"
    )

    def __init__(
        self, store: MissionStore, ledger_path: Path | str | None = None
    ) -> None:
        if type(store) is not MissionStore:
            raise AgenticCoreV4ContractError("exact MissionStore is required")
        self._store = store
        self._path = (
            Path(ledger_path)
            if ledger_path is not None
            else store.path.with_name(f"{store.path.stem}.v4-inputs.sqlite3")
        )
        if not self._path.is_absolute():
            raise AgenticCoreV4ContractError("exact-input ledger path must be absolute")
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT type,name,tbl_name,sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%'"
            ).fetchall()
            if not rows:
                connection.execute(self._DDL)
                connection.commit()
            elif len(rows) != 1 or (
                rows[0][0],
                rows[0][1],
                rows[0][2],
                _normalize_sql(rows[0][3]),
            ) != (
                "table",
                "input_bindings",
                "input_bindings",
                _normalize_sql(self._DDL),
            ):
                raise AgenticCoreV4Error("V4 exact-input ledger schema diverges")
        finally:
            connection.close()

    @staticmethod
    def _canonical_input(
        title: str,
        steps: list[dict[str, Any]],
        tool_allowlist: list[str] | None,
        max_steps: int,
        max_seconds: float,
        max_retries: int,
        provider_cost_limit: float,
    ) -> str:
        if (
            type(title) is not str
            or not title
            or title != title.strip()
            or len(title) > 240
        ):
            raise AgenticCoreV4ContractError(
                "title must be canonical non-empty text of at most 240 characters"
            )
        if type(steps) is not list or not steps:
            raise AgenticCoreV4ContractError("steps must be an exact non-empty list")
        canonical_steps: list[dict[str, object]] = []
        allowed_step_fields = {"tool", "args", "estimated_provider_cost"}
        for index, step in enumerate(steps):
            if type(step) is not dict or not set(step).issubset(allowed_step_fields):
                raise AgenticCoreV4ContractError(
                    f"step {index} contains unknown or non-canonical fields"
                )
            if set(step) != {"tool", "args", "estimated_provider_cost"}:
                raise AgenticCoreV4ContractError(
                    f"step {index} must contain the exact V4 field set"
                )
            if type(step["tool"]) is not str or not step["tool"].strip():
                raise AgenticCoreV4ContractError(f"step {index} tool is invalid")
            if type(step["args"]) is not dict:
                raise AgenticCoreV4ContractError(
                    f"step {index} args must be an exact object"
                )
            cost = step["estimated_provider_cost"]
            if (
                isinstance(cost, bool)
                or not isinstance(cost, (int, float))
                or not math.isfinite(cost)
                or cost < 0
            ):
                raise AgenticCoreV4ContractError(f"step {index} cost is invalid")
            canonical_steps.append(
                {
                    "tool": step["tool"],
                    "args": step["args"],
                    "estimated_provider_cost": cost,
                }
            )
        if tool_allowlist is not None and (
            type(tool_allowlist) is not list
            or any(type(item) is not str or not item for item in tool_allowlist)
        ):
            raise AgenticCoreV4ContractError("tool allowlist is invalid")
        payload = {
            "title": title,
            "steps": canonical_steps,
            "tool_allowlist": tool_allowlist,
            "max_steps": max_steps,
            "max_seconds": max_seconds,
            "max_retries": max_retries,
            "provider_cost_limit": provider_cost_limit,
        }
        try:
            return json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
        except (TypeError, ValueError) as exc:
            raise AgenticCoreV4ContractError(
                "mission input is not canonical JSON"
            ) from exc

    def create_idempotent(
        self,
        materialization_key: str,
        title: str,
        steps: list[dict[str, Any]],
        *,
        tool_allowlist: list[str] | None = None,
        max_steps: int = 25,
        max_seconds: float = 900,
        max_retries: int = 2,
        provider_cost_limit: float = 0.0,
    ) -> Mission:
        if (
            type(materialization_key) is not str
            or _REQUEST_KEY.fullmatch(materialization_key) is None
        ):
            raise AgenticCoreV4ContractError("materialization key is invalid")
        canonical = self._canonical_input(
            title,
            steps,
            tool_allowlist,
            max_steps,
            max_seconds,
            max_retries,
            provider_cost_limit,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT input_digest,canonical_input FROM input_bindings "
                    "WHERE materialization_key=?",
                    (materialization_key,),
                ).fetchone()
                if row is not None and (
                    row["input_digest"] != digest or row["canonical_input"] != canonical
                ):
                    raise MissionError(
                        "materialization key is bound to different exact caller input"
                    )
                if row is None:
                    connection.execute(
                        "INSERT INTO input_bindings VALUES(?,?,?,?)",
                        (materialization_key, digest, canonical, time.time()),
                    )
                mission = self._store.create_idempotent(
                    materialization_key,
                    title,
                    steps,
                    tool_allowlist=tool_allowlist,
                    max_steps=max_steps,
                    max_seconds=max_seconds,
                    max_retries=max_retries,
                    provider_cost_limit=provider_cost_limit,
                )
                connection.execute("COMMIT")
                return mission
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()


def _plan_in_process(
    goal: GoalV1,
    request_key: str,
    proposed_steps: Sequence[Mapping[str, object]],
    repair_cycle: int = 0,
    supersedes_plan_id: str | None = None,
) -> PlanV1:
    adapter = DeterministicPlannerAdapterV1(goal.workspace_id, proposed_steps)
    return PlannerV2(ModelRouterV1((adapter.descriptor,)), adapter).plan(
        goal,
        request_key,
        repair_cycle=repair_cycle,
        supersedes_plan_id=supersedes_plan_id,
    )


def _critique_in_process(plan: PlanV1, findings: Sequence[str]) -> object:
    return BoundedCriticV1().critique(plan, findings)


def _verify_in_process(
    plan: PlanV1, mission_path: str, mission_id: str, expected_digest: str
) -> VerificationReportV1:
    return IndependentVerifierV1().verify(
        plan, MissionStore(Path(mission_path)), mission_id, expected_digest
    )


def _mission_state_in_process(mission_path: str, mission_id: str) -> str:
    return MissionStore(Path(mission_path)).get(mission_id).state


_MISSION_TO_PLAN = {
    "awaiting_approval": PlanStateV1.AWAITING_APPROVAL,
    "running": PlanStateV1.RUNNING,
    "waiting": PlanStateV1.WAITING,
    "paused": PlanStateV1.PAUSED,
    "succeeded": PlanStateV1.VERIFYING,
    "failed": PlanStateV1.FAILED,
    "cancelled": PlanStateV1.CANCELLED,
}


class AgenticCoreV4:
    """V4 facade using only process-isolated admitted computation."""

    def __init__(
        self,
        state_store: AgenticStateStoreV4,
        mission_store: MissionStore,
        workspace_scope: WorkspaceScopeV1,
        *,
        executor: TerminableProcessExecutorV4 | None = None,
    ) -> None:
        if (
            type(state_store) is not AgenticStateStoreV4
            or type(mission_store) is not MissionStore
            or type(workspace_scope) is not WorkspaceScopeV1
        ):
            raise AgenticCoreV4ContractError(
                "exact V4 state, MissionStore and workspace scope are required"
            )
        self._state = state_store
        self._missions = mission_store
        self._workspace = workspace_scope
        self._executor = executor or TerminableProcessExecutorV4()
        self._materializer = StrictMissionMaterializerV4(mission_store)
        self._closed = False

    def __enter__(self) -> "AgenticCoreV4":
        if self._closed:
            raise AgenticCoreV4Denied("V4 core is closed")
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    @property
    def kill_latched(self) -> bool:
        return self._state.kill_latched

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._executor.close()

    def _validate_plan_scope(self, plan: PlanV1) -> None:
        if plan.goal.workspace_id != self._workspace.workspace_id:
            raise AgenticCoreV4Denied("goal workspace does not match host scope")
        ranks = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}
        if (
            ranks[plan.goal.data_class.value]
            > ranks[self._workspace.maximum_data_class.value]
        ):
            raise AgenticCoreV4Denied("goal data class exceeds workspace scope")
        for step in plan.steps:
            if step.capability.startswith("workspace_"):
                root = step.arguments.get("root")
                if type(root) is not str or root not in self._workspace.allowed_roots:
                    raise AgenticCoreV4Denied("workspace root is outside host scope")

    def _bounded_call(
        self,
        account_or_plan_id: str,
        operation: str,
        callback: Callable[..., _T],
        args: tuple[object, ...],
        *,
        timeout_cap: float | None = None,
    ) -> _T:
        if self._closed:
            raise AgenticCoreV4Denied("V4 core is closed")
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
                raise AgenticCoreV4ContractError("bounded timeout cap is invalid")
            effective = min(effective, float(timeout_cap))
        value: _T | None = None
        failure: BaseException | None = None
        timed_out = False
        try:
            value = self._executor.invoke(callback, effective, *args)
        except BaseException as exc:
            failure = exc
            timed_out = isinstance(exc, ProcessCallTimeoutV4)
        snapshot = self._state.finish_compute(lease, force_exhausted=timed_out)
        if snapshot.exhausted:
            if lease.plan_id is not None:
                self._state.block_budget(lease.plan_id)
            raise ComputeBudgetExhaustedV4("BUDGET_EXHAUSTED")
        if failure is not None:
            raise failure
        return value  # type: ignore[return-value]

    def submit(
        self,
        goal: GoalV1,
        request_key: str,
        proposed_steps: Sequence[Mapping[str, object]],
    ) -> PlanProjectionV1:
        if self.kill_latched:
            raise AgenticCoreV4Denied("Phase 6 V4 kill switch is latched")
        account = self._state.reserve_request_budget(
            request_key, goal.budget.max_compute_seconds
        )
        plan = self._bounded_call(
            account,
            "planner",
            _plan_in_process,
            (goal, request_key, tuple(proposed_steps)),
        )
        if type(plan) is not PlanV1:
            raise AgenticCoreV4Error("isolated planner returned an invalid plan")
        self._validate_plan_scope(plan)
        return self._state.register_plan(plan, account)

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
            raise AgenticCoreV4Denied("repair requires failed or blocked source")
        critique = self._bounded_call(
            plan_id, "critic", _critique_in_process, (source, tuple(findings))
        )
        if not getattr(critique, "repair_allowed", False):
            raise AgenticCoreV4Denied("bounded repair budget is exhausted")
        repaired = self._bounded_call(
            plan_id,
            "repair_planner",
            _plan_in_process,
            (
                source.goal,
                request_key,
                tuple(proposed_steps),
                source.repair_cycle + 1,
                source.plan_id,
            ),
        )
        if type(repaired) is not PlanV1:
            raise AgenticCoreV4Error("isolated repair planner returned invalid plan")
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
        stage_hook: Callable[[str, FenceClaimV4], None] | None = None,
    ) -> AdmissionResultV1:
        plan = self._state.get_plan(plan_id)
        self._validate_plan_scope(plan)
        projection = self._state.get_projection(plan_id)
        if projection.mission_id is not None:
            return AdmissionResultV1(
                plan_id,
                projection.state,
                projection.mission_id,
                "idempotent_existing_mission_binding",
            )
        policies = tuple(
            capability_policy_v1(step.capability) for step in plan.ordered_steps()
        )
        if any(policy.executor == "phase5" for policy in policies):
            self._state.plans.set_state(
                plan_id, PlanStateV1.WAITING_FOR_PHASE5, "Phase 5 binding required"
            )
            return AdmissionResultV1(
                plan_id,
                PlanStateV1.WAITING_FOR_PHASE5,
                None,
                "phase5_catalog_dispatch_not_wired",
            )
        claim = self._state.claim_materialization(plan_id)
        if claim.disposition == "bound":
            return AdmissionResultV1(
                plan_id, projection.state, claim.mission_id, "idempotent_fenced_binding"
            )
        if claim.disposition == "observer":
            return AdmissionResultV1(
                plan_id, projection.state, None, "materialization_winner_observed"
            )
        if stage_hook is not None:
            stage_hook("claimed", claim)
        if not self._state.renew_fence(claim) or not self._state.fence_is_current(
            claim
        ):
            observed = self._state.observe_materialization(plan_id)
            return AdmissionResultV1(
                plan_id,
                projection.state,
                observed.mission_id,
                "stale_owner_observed_winner",
            )
        if stage_hook is not None:
            stage_hook("before_create", claim)
        mission_steps: list[dict[str, Any]] = []
        for step, policy in zip(plan.ordered_steps(), policies, strict=True):
            if policy.mission_tool is None:
                raise AgenticCoreV4Error("mission tool binding is unavailable")
            mission_steps.append(
                {
                    "tool": policy.mission_tool,
                    "args": step.arguments,
                    "estimated_provider_cost": 0.0,
                }
            )
        mission = self._materializer.create_idempotent(
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
                projection.state,
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
        self._state.touch_runtime(plan_id)
        return AdmissionResultV1(
            plan_id,
            PlanStateV1.AWAITING_APPROVAL,
            mission.id,
            "fenced_exact_input_mission_binding",
        )

    def execute_approved(
        self, plan_id: str, runner: ToolRunner | None = None
    ) -> Mission:
        plan = self._state.get_plan(plan_id)
        projection = self._state.get_projection(plan_id)
        if projection.mission_id is None:
            raise AgenticCoreV4Denied("plan has no mission binding")
        mission_id = projection.mission_id
        selected_runner = runner or run_mission_tool
        summary = self._missions.plan_summary(mission_id)
        expected: dict[str, object] = {}
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
                raise AgenticCoreV4Denied("mission key diverges from immutable plan")
            try:
                return self._bounded_call(
                    plan_id,
                    f"step.{step.step_id}",
                    selected_runner,
                    (tool, dict(arguments), key),
                    timeout_cap=step.timeout_seconds,
                )
            except (ProcessCallTimeoutV4, ComputeBudgetExhaustedV4):
                try:
                    current = self._missions.get(mission_id)
                    if current.state in {
                        "awaiting_approval",
                        "running",
                        "waiting",
                        "paused",
                    }:
                        self._missions.cancel(mission_id)
                except (InvalidTransition, MissionError, KeyError):
                    pass
                self._state.block_budget(plan_id)
                return {
                    "status": "failed",
                    "data": {"reason": "BUDGET_EXHAUSTED"},
                    "evidence": [],
                    "postconditions": [],
                    "waiting_for": None,
                }

        mission = self._missions.get(mission_id)
        if mission.state in {"running", "paused"}:
            mission = self._missions.run(mission_id, bounded_runner)
        mapped = _MISSION_TO_PLAN.get(mission.state)
        if mapped is not None:
            self._state.plans.set_state(
                plan_id, mapped, f"mission_store:{mission.state}"
            )
        if mission.state == "succeeded":
            self.verify(plan_id)
        if mission.state in {"succeeded", "failed", "cancelled"}:
            self._state.touch_runtime(plan_id, terminal=True)
        return mission

    def verify(self, plan_id: str) -> VerificationReportV1:
        plan = self._state.get_plan(plan_id)
        projection = self._state.get_projection(plan_id)
        if projection.mission_id is None or projection.mission_plan_digest is None:
            raise AgenticCoreV4Denied("plan has no mission evidence binding")
        report = self._bounded_call(
            plan_id,
            "verifier",
            _verify_in_process,
            (
                plan,
                str(self._missions.path),
                projection.mission_id,
                projection.mission_plan_digest,
            ),
        )
        if type(report) is not VerificationReportV1:
            raise AgenticCoreV4Error("isolated verifier returned invalid report")
        self._state.plans.record_receipts(report.receipts)
        self._state.plans.set_state(
            plan_id,
            PlanStateV1.COMPLETE
            if report.status == "verified"
            else PlanStateV1.BLOCKED,
            "independent_verification_passed"
            if report.status == "verified"
            else "independent_verification_failed",
        )
        self._state.touch_runtime(plan_id, terminal=True)
        return report

    def recover(self, *, limit: int = DEFAULT_RECOVERY_LIMIT) -> tuple[str, ...]:
        exhausted = self._state.recover_compute(limit=limit)
        for plan_id in exhausted:
            projection = self._state.get_projection(plan_id)
            if projection.mission_id is not None:
                try:
                    mission = self._missions.get(projection.mission_id)
                    if mission.state in {"running", "waiting", "paused"}:
                        self._missions.cancel(mission.id)
                except (InvalidTransition, MissionError, KeyError):
                    pass
            self._state.block_budget(plan_id)
        output: list[str] = []
        for plan_id in self._state.recovery_candidates(limit=limit):
            projection = self._state.get_projection(plan_id)
            if projection.mission_id is None:
                output.append(plan_id)
                continue
            state = self._bounded_call(
                plan_id,
                "recovery",
                _mission_state_in_process,
                (str(self._missions.path), projection.mission_id),
            )
            mapped = _MISSION_TO_PLAN.get(state)
            if mapped is not None:
                self._state.plans.set_state(plan_id, mapped, f"mission_store:{state}")
            output.append(plan_id)
        return tuple(output)


def create_phase6_agentic_core_v4(
    *,
    gate: AgenticFeatureGateV4,
    sidecar_path: Path | str,
    mission_store: MissionStore,
    workspace_scope: WorkspaceScopeV1,
    fence_seconds: float = DEFAULT_FENCE_SECONDS,
) -> AgenticCoreV4:
    state = AgenticStateStoreV4(sidecar_path, gate, fence_seconds=fence_seconds)
    return AgenticCoreV4(state, mission_store, workspace_scope)


artifact_root_v4 = artifact_root_v2
