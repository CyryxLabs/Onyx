"""Isolated Phase 6 Agentic Core V2 candidate.

V2 composes the frozen V1 typed-plan and evidence authority.  It adds a
cross-instance coordination ledger for materialization and lineage-wide compute
budgets.  It remains strict default-off and has no startup/live wiring.
"""

from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

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
    CapabilityPolicyV1,
    CritiqueV1,
    DataClassV1,
    DeterministicPlannerAdapterV1,
    EffectClassV1,
    EvidenceReceiptV1,
    ExternalAgentAdapterV1,
    ExternalAgentBudgetV1,
    ExternalAgentRequestV1,
    ExternalAgentStatusV1,
    GoalV1,
    IndependentVerifierV1,
    MissionBudgetV1,
    ModelDescriptorV1,
    ModelRouterV1,
    PlanProjectionV1,
    PlanStateV1,
    PlanV1,
    PlannerAdapterV1,
    PlannerV1,
    PlanningProposalV1,
    RecoveryRecordV1,
    RiskLevelV1,
    RouteDecisionV1,
    RouteRequestV1,
    StepV1,
    VerificationReportV1,
    WorkspaceScopeV1,
    _canonical_arguments,
    _identifier,
    _sha,
    capability_policy_v1,
)


FEATURE_FLAG = "ONYX_PHASE6_AGENTIC_CORE_V2"
COORDINATION_SCHEMA_VERSION = 2
MATERIALIZATION_LEASE_SECONDS = 30.0
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

# V2 deliberately retains the frozen V1 domain serialization.  These aliases
# make that compatibility explicit while all corrected authority lives below.
MissionBudgetV2 = MissionBudgetV1
GoalV2 = GoalV1
WorkspaceScopeV2 = WorkspaceScopeV1
StepV2 = StepV1
PlanV2 = PlanV1
PlanProjectionV2 = PlanProjectionV1
PlanStateV2 = PlanStateV1
RiskLevelV2 = RiskLevelV1
EffectClassV2 = EffectClassV1
DataClassV2 = DataClassV1
CapabilityPolicyV2 = CapabilityPolicyV1
ModelDescriptorV2 = ModelDescriptorV1
ModelRouterV2 = ModelRouterV1
RouteRequestV2 = RouteRequestV1
RouteDecisionV2 = RouteDecisionV1
PlanningProposalV2 = PlanningProposalV1
PlannerAdapterV2 = PlannerAdapterV1
EvidenceReceiptV2 = EvidenceReceiptV1
VerificationReportV2 = VerificationReportV1
AdmissionResultV2 = AdmissionResultV1
RecoveryRecordV2 = RecoveryRecordV1
CritiqueV2 = CritiqueV1
BoundedCriticV2 = BoundedCriticV1
ExternalAgentBudgetV2 = ExternalAgentBudgetV1
ExternalAgentRequestV2 = ExternalAgentRequestV1
ExternalAgentStatusV2 = ExternalAgentStatusV1
ExternalAgentAdapterV2 = ExternalAgentAdapterV1


class AgenticCoreV2Error(AgenticCoreV1Error):
    """V2 coordination or integrity failure."""


class AgenticCoreV2ContractError(AgenticCoreV1ContractError):
    """A V2 host-owned contract is invalid."""


class AgenticCoreV2Denied(AgenticCoreV1Denied):
    """A V2 operation was denied before mutation."""


class ComputeBudgetExhaustedV2(AgenticCoreV2Denied):
    """The lineage-wide compute wall budget is terminally exhausted."""


@dataclass(frozen=True)
class AgenticFeatureGateV2:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise AgenticCoreV2ContractError("enabled must be an exact boolean")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "AgenticFeatureGateV2":
        import os

        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True)
class ComputeLeaseV2:
    plan_id: str
    root_plan_id: str
    token: str
    operation: str
    started_monotonic: float
    allowed_seconds: float


@dataclass(frozen=True)
class ComputeBudgetSnapshotV2:
    plan_id: str
    root_plan_id: str
    limit_seconds: float
    consumed_seconds: float
    remaining_seconds: float
    exhausted: bool
    active_operation: str | None


@dataclass(frozen=True)
class MaterializationReservationV2:
    plan_id: str
    disposition: str
    lease_token: str | None
    mission_id: str | None


def artifact_root_v2(artifacts: Mapping[str, str]) -> str:
    """Return SHA-256 of sorted ``path NUL digest`` records joined by LF.

    Paths must be unique normalized relative POSIX paths. Digests must be
    lowercase SHA-256 hex. No trailing LF is appended. The manifest itself is
    excluded to avoid a circular digest.
    """

    if type(artifacts) is not dict or not artifacts:
        raise AgenticCoreV2ContractError(
            "artifact mapping must be a non-empty plain dict"
        )
    records: list[str] = []
    for raw_path, digest in artifacts.items():
        if type(raw_path) is not str or type(digest) is not str:
            raise AgenticCoreV2ContractError("artifact path and digest must be strings")
        path = PurePosixPath(raw_path)
        if (
            not raw_path
            or "\\" in raw_path
            or path.is_absolute()
            or raw_path != path.as_posix()
            or any(part in {"", ".", ".."} for part in path.parts)
            or "\x00" in raw_path
        ):
            raise AgenticCoreV2ContractError(
                "artifact path is not canonical relative POSIX"
            )
        if _SHA256.fullmatch(digest) is None:
            raise AgenticCoreV2ContractError("artifact digest is not lowercase SHA-256")
        records.append(f"{raw_path}\0{digest}")
    payload = "\n".join(sorted(records)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class _CapturedPlannerAdapterV2:
    descriptor: ModelDescriptorV1
    proposal: PlanningProposalV1

    def propose(self, goal: GoalV1) -> PlanningProposalV1:
        del goal
        return self.proposal


class PlannerV2:
    """Route once, capture invoked identity, and reject self-asserted mismatch."""

    def __init__(self, router: ModelRouterV1, adapter: PlannerAdapterV1) -> None:
        if not isinstance(adapter, PlannerAdapterV1):
            raise AgenticCoreV2ContractError("planner adapter contract is invalid")
        self._router = router
        self._adapter = adapter

    def plan(
        self,
        goal: GoalV1,
        request_key: str,
        *,
        repair_cycle: int = 0,
        supersedes_plan_id: str | None = None,
    ) -> PlanV1:
        descriptor = self._adapter.descriptor
        if type(descriptor) is not ModelDescriptorV1:
            raise AgenticCoreV2ContractError("invoked adapter descriptor must be exact")
        decision = self._router.route(
            RouteRequestV1(
                goal.workspace_id,
                goal.data_class,
                "structured_plan",
                True,
                True,
                60_000,
                0,
                900,
            )
        )
        if decision.adapter_id != descriptor.adapter_id:
            raise AgenticCoreV2Denied(
                "invoked adapter is not the host-selected adapter"
            )
        proposal = self._adapter.propose(goal)
        if type(proposal) is not PlanningProposalV1:
            raise AgenticCoreV2ContractError("planner proposal must be exact")
        if proposal.adapter_id != descriptor.adapter_id:
            raise AgenticCoreV2Denied(
                "proposal adapter identity does not match the invoked adapter descriptor"
            )
        captured = _CapturedPlannerAdapterV2(descriptor, proposal)
        return PlannerV1(self._router, captured).plan(
            goal,
            request_key,
            repair_cycle=repair_cycle,
            supersedes_plan_id=supersedes_plan_id,
        )


class AgenticStateStoreV2:
    """Frozen V1 plan/evidence store plus a cross-instance V2 authority ledger."""

    _DDL = """
    CREATE TABLE metadata(schema_version INTEGER NOT NULL);
    CREATE TABLE budget_accounts(
      root_plan_id TEXT PRIMARY KEY,
      limit_seconds REAL NOT NULL,
      consumed_seconds REAL NOT NULL,
      exhausted INTEGER NOT NULL,
      active_plan_id TEXT,
      active_token TEXT,
      active_operation TEXT,
      active_started_wall REAL,
      active_deadline_wall REAL
    );
    CREATE TABLE plan_lineage(
      plan_id TEXT PRIMARY KEY,
      root_plan_id TEXT NOT NULL REFERENCES budget_accounts(root_plan_id),
      created_at REAL NOT NULL
    );
    CREATE INDEX plan_lineage_root ON plan_lineage(root_plan_id,plan_id);
    CREATE TABLE materializations(
      plan_id TEXT PRIMARY KEY,
      status TEXT NOT NULL CHECK(status IN ('reserved','bound','orphaned')),
      lease_token TEXT,
      lease_expires REAL,
      mission_id TEXT UNIQUE,
      reason TEXT NOT NULL,
      updated_at REAL NOT NULL
    );
    CREATE TABLE orphan_missions(
      mission_id TEXT PRIMARY KEY,
      plan_id TEXT NOT NULL,
      reason TEXT NOT NULL,
      tombstoned_at REAL NOT NULL
    );
    CREATE TRIGGER lineage_no_update BEFORE UPDATE ON plan_lineage
      BEGIN SELECT RAISE(ABORT,'phase6 v2 lineage is immutable'); END;
    CREATE TRIGGER lineage_no_delete BEFORE DELETE ON plan_lineage
      BEGIN SELECT RAISE(ABORT,'phase6 v2 lineage is immutable'); END;
    CREATE TRIGGER orphan_no_update BEFORE UPDATE ON orphan_missions
      BEGIN SELECT RAISE(ABORT,'phase6 v2 orphan tombstones are immutable'); END;
    CREATE TRIGGER orphan_no_delete BEFORE DELETE ON orphan_missions
      BEGIN SELECT RAISE(ABORT,'phase6 v2 orphan tombstones are immutable'); END;
    """

    def __init__(self, path: Path | str, gate: AgenticFeatureGateV2) -> None:
        if type(gate) is not AgenticFeatureGateV2 or not gate.enabled:
            raise AgenticCoreV2Denied("Phase 6 V2 agentic core is disabled")
        self._path = Path(path)
        if not self._path.is_absolute() or self._path.name in {"", ".", ".."}:
            raise AgenticCoreV2ContractError(
                "an explicit absolute sidecar path is required"
            )
        self._coord_path = self._path.with_name(
            f"{self._path.stem}.v2-coordination{self._path.suffix or '.sqlite3'}"
        )
        self._lock = threading.RLock()
        # V2 explicitly opts into the frozen V1 storage component internally;
        # neither V1 nor V2 is environment-enabled or wired live by this action.
        self._plans = AgenticStateStoreV1(self._path, AgenticFeatureGateV1(True))
        self.initialize()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def coordination_path(self) -> Path:
        return self._coord_path

    @property
    def plans(self) -> AgenticStateStoreV1:
        return self._plans

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
                        + f"\nINSERT INTO metadata VALUES({COORDINATION_SCHEMA_VERSION});"
                        + f"\nPRAGMA user_version={COORDINATION_SCHEMA_VERSION};\nCOMMIT;"
                    )
                else:
                    expected = {
                        "metadata",
                        "budget_accounts",
                        "plan_lineage",
                        "materializations",
                        "orphan_missions",
                    }
                    if version != COORDINATION_SCHEMA_VERSION or tables != expected:
                        raise AgenticCoreV2Error(
                            "Phase 6 V2 coordination schema diverges"
                        )
                    triggers = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='trigger'"
                        )
                    }
                    indexes = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='index' "
                            "AND name NOT LIKE 'sqlite_%'"
                        )
                    }
                    if triggers != {
                        "lineage_no_update",
                        "lineage_no_delete",
                        "orphan_no_update",
                        "orphan_no_delete",
                    } or indexes != {"plan_lineage_root"}:
                        raise AgenticCoreV2Error(
                            "Phase 6 V2 coordination authority objects diverge"
                        )
                    rows = connection.execute(
                        "SELECT schema_version FROM metadata"
                    ).fetchall()
                    if len(rows) != 1 or rows[0][0] != COORDINATION_SCHEMA_VERSION:
                        raise AgenticCoreV2Error("Phase 6 V2 metadata diverges")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    @property
    def kill_latched(self) -> bool:
        return self._plans.kill_latched

    def create_plan(
        self,
        plan: PlanV1,
        *,
        root_plan_id: str | None = None,
        initial_compute_seconds: float = 0.0,
    ) -> PlanProjectionV1:
        root = (
            plan.plan_id
            if root_plan_id is None
            else _identifier(root_plan_id, "root_plan_id")
        )
        if (
            isinstance(initial_compute_seconds, bool)
            or not isinstance(initial_compute_seconds, (int, float))
            or not math.isfinite(initial_compute_seconds)
            or initial_compute_seconds < 0
        ):
            raise AgenticCoreV2ContractError("initial compute charge is invalid")
        self._plans.create_plan(plan)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                account = connection.execute(
                    "SELECT * FROM budget_accounts WHERE root_plan_id=?", (root,)
                ).fetchone()
                if account is None:
                    if root != plan.plan_id:
                        raise AgenticCoreV2Denied(
                            "repair root compute account is unavailable"
                        )
                    consumed = float(initial_compute_seconds)
                    exhausted = int(consumed >= plan.goal.budget.max_compute_seconds)
                    connection.execute(
                        "INSERT INTO budget_accounts VALUES(?,?,?,?,NULL,NULL,NULL,NULL,NULL)",
                        (
                            root,
                            plan.goal.budget.max_compute_seconds,
                            consumed,
                            exhausted,
                        ),
                    )
                elif (
                    float(account["limit_seconds"])
                    != plan.goal.budget.max_compute_seconds
                ):
                    raise AgenticCoreV2Denied(
                        "repair compute budget diverges from its lineage"
                    )
                existing = connection.execute(
                    "SELECT root_plan_id FROM plan_lineage WHERE plan_id=?",
                    (plan.plan_id,),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        "INSERT INTO plan_lineage VALUES(?,?,?)",
                        (plan.plan_id, root, time.time()),
                    )
                elif existing[0] != root:
                    raise AgenticCoreV2Denied(
                        "plan is already bound to another compute lineage"
                    )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        if self.budget_snapshot(plan.plan_id).exhausted:
            self._block_budget(plan.plan_id)
        return self._plans.get_projection(plan.plan_id)

    def _account_row(self, connection: sqlite3.Connection, plan_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT b.* FROM plan_lineage l JOIN budget_accounts b "
            "ON b.root_plan_id=l.root_plan_id WHERE l.plan_id=?",
            (_identifier(plan_id, "plan_id"),),
        ).fetchone()
        if row is None:
            raise AgenticCoreV2Denied("plan has no V2 compute account")
        return row

    @staticmethod
    def _snapshot(plan_id: str, row: Mapping[str, object]) -> ComputeBudgetSnapshotV2:
        limit = float(row["limit_seconds"])
        consumed = float(row["consumed_seconds"])
        return ComputeBudgetSnapshotV2(
            plan_id,
            str(row["root_plan_id"]),
            limit,
            consumed,
            max(0.0, limit - consumed),
            bool(row["exhausted"]) or consumed >= limit,
            str(row["active_operation"])
            if row["active_operation"] is not None
            else None,
        )

    def budget_snapshot(self, plan_id: str) -> ComputeBudgetSnapshotV2:
        connection = self._connect()
        try:
            return self._snapshot(plan_id, self._account_row(connection, plan_id))
        finally:
            connection.close()

    def begin_compute(self, plan_id: str, operation: str) -> ComputeLeaseV2:
        canonical = _identifier(plan_id, "plan_id")
        operation_id = _identifier(operation, "compute operation")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = self._account_row(connection, canonical)
                now = time.time()
                if row["active_token"] is not None:
                    deadline = float(row["active_deadline_wall"])
                    if deadline > now:
                        raise AgenticCoreV2Denied(
                            "compute lineage is active in another instance"
                        )
                    elapsed = max(0.0, now - float(row["active_started_wall"]))
                    consumed = float(row["consumed_seconds"]) + elapsed
                    exhausted = int(consumed >= float(row["limit_seconds"]))
                    connection.execute(
                        "UPDATE budget_accounts SET consumed_seconds=?,exhausted=?,"
                        "active_plan_id=NULL,active_token=NULL,active_operation=NULL,"
                        "active_started_wall=NULL,active_deadline_wall=NULL WHERE root_plan_id=?",
                        (consumed, exhausted, row["root_plan_id"]),
                    )
                    row = self._account_row(connection, canonical)
                snapshot = self._snapshot(canonical, row)
                if snapshot.exhausted or snapshot.remaining_seconds <= 0:
                    raise ComputeBudgetExhaustedV2("BUDGET_EXHAUSTED")
                token = f"compute_{uuid.uuid4().hex}"
                connection.execute(
                    "UPDATE budget_accounts SET active_plan_id=?,active_token=?,active_operation=?,"
                    "active_started_wall=?,active_deadline_wall=? WHERE root_plan_id=?",
                    (
                        canonical,
                        token,
                        operation_id,
                        now,
                        now + snapshot.remaining_seconds,
                        snapshot.root_plan_id,
                    ),
                )
                connection.execute("COMMIT")
                return ComputeLeaseV2(
                    canonical,
                    snapshot.root_plan_id,
                    token,
                    operation_id,
                    time.monotonic(),
                    snapshot.remaining_seconds,
                )
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def finish_compute(
        self, lease: ComputeLeaseV2, *, elapsed_seconds: float | None = None
    ) -> ComputeBudgetSnapshotV2:
        if type(lease) is not ComputeLeaseV2:
            raise AgenticCoreV2ContractError("exact compute lease required")
        elapsed = (
            time.monotonic() - lease.started_monotonic
            if elapsed_seconds is None
            else elapsed_seconds
        )
        if (
            isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(elapsed)
            or elapsed < 0
        ):
            raise AgenticCoreV2ContractError("compute elapsed time is invalid")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = self._account_row(connection, lease.plan_id)
                if (
                    row["active_token"] != lease.token
                    or row["active_plan_id"] != lease.plan_id
                ):
                    raise AgenticCoreV2Denied("compute lease identity diverges")
                wall_elapsed = max(0.0, time.time() - float(row["active_started_wall"]))
                charge = max(float(elapsed), wall_elapsed)
                consumed = float(row["consumed_seconds"]) + charge
                exhausted = int(consumed >= float(row["limit_seconds"]))
                connection.execute(
                    "UPDATE budget_accounts SET consumed_seconds=?,exhausted=?,"
                    "active_plan_id=NULL,active_token=NULL,active_operation=NULL,"
                    "active_started_wall=NULL,active_deadline_wall=NULL WHERE root_plan_id=?",
                    (consumed, exhausted, lease.root_plan_id),
                )
                row = self._account_row(connection, lease.plan_id)
                connection.execute("COMMIT")
                return self._snapshot(lease.plan_id, row)
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def charge_compute(self, plan_id: str, seconds: float) -> ComputeBudgetSnapshotV2:
        lease = self.begin_compute(plan_id, "recovery")
        return self.finish_compute(lease, elapsed_seconds=seconds)

    def recover_expired_compute(
        self, *, explicit_restart: bool = False
    ) -> tuple[str, ...]:
        now = time.time()
        exhausted_plans: list[str] = []
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    "SELECT * FROM budget_accounts WHERE active_token IS NOT NULL "
                    "AND (? OR active_deadline_wall<=?)",
                    (int(explicit_restart), now),
                ).fetchall()
                for row in rows:
                    elapsed = max(0.0, now - float(row["active_started_wall"]))
                    consumed = float(row["consumed_seconds"]) + elapsed
                    exhausted = int(consumed >= float(row["limit_seconds"]))
                    connection.execute(
                        "UPDATE budget_accounts SET consumed_seconds=?,exhausted=?,"
                        "active_plan_id=NULL,active_token=NULL,active_operation=NULL,"
                        "active_started_wall=NULL,active_deadline_wall=NULL WHERE root_plan_id=?",
                        (consumed, exhausted, row["root_plan_id"]),
                    )
                    if exhausted:
                        exhausted_plans.extend(
                            item[0]
                            for item in connection.execute(
                                "SELECT plan_id FROM plan_lineage WHERE root_plan_id=?",
                                (row["root_plan_id"],),
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

    def _block_budget(self, plan_id: str) -> None:
        projection = self._plans.get_projection(plan_id)
        if projection.state in {
            PlanStateV1.COMPLETE,
            PlanStateV1.FAILED,
            PlanStateV1.CANCELLED,
            PlanStateV1.BLOCKED,
        }:
            return
        self._plans.set_state(plan_id, PlanStateV1.BLOCKED, "BUDGET_EXHAUSTED")

    def block_budget(self, plan_id: str) -> None:
        self._block_budget(plan_id)

    # Frozen V1 plan/evidence operations are deliberately delegated.
    def get_plan(self, plan_id: str) -> PlanV1:
        return self._plans.get_plan(plan_id)

    def get_projection(self, plan_id: str) -> PlanProjectionV1:
        return self._plans.get_projection(plan_id)

    def list_projections(self) -> tuple[PlanProjectionV1, ...]:
        return self._plans.list_projections()

    def events(self, plan_id: str) -> tuple[dict[str, object], ...]:
        return self._plans.events(plan_id)

    def receipts(self, plan_id: str) -> tuple[EvidenceReceiptV1, ...]:
        return self._plans.receipts(plan_id)

    def reserve_materialization(self, plan_id: str) -> MaterializationReservationV2:
        canonical = _identifier(plan_id, "plan_id")
        projection = self._plans.get_projection(canonical)
        if projection.mission_id is not None:
            return MaterializationReservationV2(
                canonical, "bound", None, projection.mission_id
            )
        now = time.time()
        token = f"materialize_{uuid.uuid4().hex}"
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM materializations WHERE plan_id=?", (canonical,)
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO materializations VALUES(?,?,?,?,?,?,?)",
                        (
                            canonical,
                            "reserved",
                            token,
                            now + MATERIALIZATION_LEASE_SECONDS,
                            None,
                            "store_level_reservation",
                            now,
                        ),
                    )
                    disposition = "owner"
                    mission_id = None
                elif row["status"] == "bound":
                    disposition = "bound"
                    mission_id = str(row["mission_id"])
                    token = None
                elif row["status"] == "orphaned":
                    disposition = "orphaned"
                    mission_id = str(row["mission_id"]) if row["mission_id"] else None
                    token = None
                elif float(row["lease_expires"]) > now:
                    disposition = "leased"
                    mission_id = None
                    token = None
                else:
                    connection.execute(
                        "UPDATE materializations SET lease_token=?,lease_expires=?,"
                        "reason=?,updated_at=? WHERE plan_id=? AND status='reserved'",
                        (
                            token,
                            now + MATERIALIZATION_LEASE_SECONDS,
                            "expired_lease_recovered",
                            now,
                            canonical,
                        ),
                    )
                    disposition = "recovery_owner"
                    mission_id = None
                connection.execute("COMMIT")
                return MaterializationReservationV2(
                    canonical, disposition, token, mission_id
                )
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def finalize_materialization(
        self, plan_id: str, lease_token: str, mission_id: str
    ) -> None:
        canonical = _identifier(plan_id, "plan_id")
        token = _identifier(lease_token, "materialization lease token")
        mission = _identifier(mission_id, "mission_id")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                changed = connection.execute(
                    "UPDATE materializations SET status='bound',lease_token=NULL,"
                    "lease_expires=NULL,mission_id=?,reason='mission_bound',updated_at=? "
                    "WHERE plan_id=? AND status='reserved' AND lease_token=?",
                    (mission, time.time(), canonical, token),
                ).rowcount
                if changed != 1:
                    raise AgenticCoreV2Denied(
                        "materialization lease was lost before binding"
                    )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def tombstone_orphan(
        self, plan_id: str, lease_token: str, mission_id: str, reason: str
    ) -> None:
        canonical = _identifier(plan_id, "plan_id")
        token = _identifier(lease_token, "materialization lease token")
        mission = _identifier(mission_id, "mission_id")
        safe_reason = str(reason).strip()[:512] or "orphaned_before_binding"
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM materializations WHERE plan_id=?", (canonical,)
                ).fetchone()
                if (
                    row is None
                    or row["status"] != "reserved"
                    or row["lease_token"] != token
                ):
                    raise AgenticCoreV2Denied("orphan tombstone lost its reservation")
                connection.execute(
                    "INSERT OR IGNORE INTO orphan_missions VALUES(?,?,?,?)",
                    (mission, canonical, safe_reason, time.time()),
                )
                connection.execute(
                    "UPDATE materializations SET status='orphaned',lease_token=NULL,"
                    "lease_expires=NULL,mission_id=?,reason=?,updated_at=? WHERE plan_id=?",
                    (mission, safe_reason, time.time(), canonical),
                )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def orphan_missions(self, plan_id: str) -> tuple[str, ...]:
        canonical = _identifier(plan_id, "plan_id")
        connection = self._connect()
        try:
            return tuple(
                str(row[0])
                for row in connection.execute(
                    "SELECT mission_id FROM orphan_missions WHERE plan_id=? ORDER BY mission_id",
                    (canonical,),
                ).fetchall()
            )
        finally:
            connection.close()


class _BudgetedVerifierV2:
    verifier_id = IndependentVerifierV1.verifier_id

    def __init__(
        self, state: AgenticStateStoreV2, delegate: IndependentVerifierV1
    ) -> None:
        self._state = state
        self._delegate = delegate

    def verify(
        self,
        plan: PlanV1,
        mission_store: MissionStore,
        mission_id: str,
        mission_plan_digest: str,
    ) -> VerificationReportV1:
        try:
            lease = self._state.begin_compute(plan.plan_id, "verification")
        except ComputeBudgetExhaustedV2:
            return VerificationReportV1(
                plan.plan_id,
                mission_id,
                "rejected",
                ("BUDGET_EXHAUSTED",),
                (),
                "0" * 64,
            )
        report: VerificationReportV1 | None = None
        try:
            report = self._delegate.verify(
                plan, mission_store, mission_id, mission_plan_digest
            )
        finally:
            snapshot = self._state.finish_compute(lease)
        if snapshot.exhausted:
            return VerificationReportV1(
                plan.plan_id,
                mission_id,
                "rejected",
                ("BUDGET_EXHAUSTED",),
                report.receipts if report is not None else (),
                report.authority_snapshot_hash if report is not None else "0" * 64,
            )
        if report is None:
            raise AgenticCoreV2Error("verifier returned no bound report")
        return report


class _BudgetAwareAgenticCoreV1(AgenticCoreV1):
    """Internal V1 facade that cannot project success after V2 exhaustion."""

    def __init__(
        self,
        state: AgenticStateStoreV2,
        missions: MissionStore,
        workspace: WorkspaceScopeV1,
        verifier: IndependentVerifierV1,
        critic: BoundedCriticV1,
    ) -> None:
        self._v2_state = state
        super().__init__(
            state.plans,
            missions,
            workspace,
            verifier=_BudgetedVerifierV2(state, verifier),
            critic=critic,
        )

    def _sync(self, plan_id: str, mission: Mission) -> PlanProjectionV1:
        if self._v2_state.budget_snapshot(plan_id).exhausted:
            self._v2_state.block_budget(plan_id)
            return self._v2_state.get_projection(plan_id)
        return super()._sync(plan_id, mission)


class AgenticCoreV2:
    """Corrected V2 facade around the single stable MissionStore executor."""

    def __init__(
        self,
        state_store: AgenticStateStoreV2,
        mission_store: MissionStore,
        workspace_scope: WorkspaceScopeV1,
        *,
        verifier: IndependentVerifierV1 | None = None,
        critic: BoundedCriticV1 | None = None,
    ) -> None:
        if (
            type(state_store) is not AgenticStateStoreV2
            or type(mission_store) is not MissionStore
            or type(workspace_scope) is not WorkspaceScopeV1
        ):
            raise AgenticCoreV2ContractError(
                "exact V2 state, MissionStore and workspace scope instances are required"
            )
        self._state = state_store
        self._missions = mission_store
        self._workspace = workspace_scope
        self._verifier = verifier or IndependentVerifierV1()
        self._critic = critic or BoundedCriticV1()
        self._base = _BudgetAwareAgenticCoreV1(
            state_store,
            mission_store,
            workspace_scope,
            self._verifier,
            self._critic,
        )
        self._lock = threading.RLock()

    @property
    def kill_latched(self) -> bool:
        return self._state.kill_latched

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
            raise AgenticCoreV2Denied("Phase 6 V2 kill switch is latched")
        started = time.monotonic()
        plan = PlannerV2(router, adapter).plan(goal, request_key)
        elapsed = time.monotonic() - started
        self._validate_plan_scope(plan)
        return self._state.create_plan(plan, initial_compute_seconds=elapsed)

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
        if self.kill_latched:
            raise AgenticCoreV2Denied("Phase 6 V2 kill switch is latched")
        source = self._state.get_plan(plan_id)
        projection = self._state.get_projection(plan_id)
        if projection.state not in {PlanStateV1.FAILED, PlanStateV1.BLOCKED}:
            raise AgenticCoreV2Denied("repair requires a failed or blocked source plan")
        critique = self._critic.critique(source, findings)
        if not critique.repair_allowed:
            raise AgenticCoreV2Denied("bounded repair budget is exhausted")
        lease = self._state.begin_compute(source.plan_id, "repair")
        adapter = DeterministicPlannerAdapterV1(
            source.goal.workspace_id, proposed_steps
        )
        try:
            repaired = PlannerV2(ModelRouterV1((adapter.descriptor,)), adapter).plan(
                source.goal,
                request_key,
                repair_cycle=source.repair_cycle + 1,
                supersedes_plan_id=source.plan_id,
            )
        finally:
            snapshot = self._state.finish_compute(lease)
        if snapshot.exhausted:
            self._state.block_budget(source.plan_id)
            raise ComputeBudgetExhaustedV2("BUDGET_EXHAUSTED")
        self._validate_plan_scope(repaired)
        return self._state.create_plan(
            repaired,
            root_plan_id=snapshot.root_plan_id,
        )

    @staticmethod
    def _mission_title(plan: PlanV1) -> str:
        marker = f" [onyx-plan:{plan.plan_id}]"
        return f"{plan.goal.objective[: max(1, 240 - len(marker))]}{marker}"

    @staticmethod
    def _cancel_orphan(missions: MissionStore, mission: Mission) -> Mission:
        if mission.state in {"awaiting_approval", "running", "waiting", "paused"}:
            return missions.cancel(mission.id)
        return mission

    def materialize(self, plan_id: str) -> AdmissionResultV1:
        if self.kill_latched:
            raise AgenticCoreV2Denied("Phase 6 V2 kill switch is latched")
        plan = self._state.get_plan(plan_id)
        self._validate_plan_scope(plan)
        projection = self._state.get_projection(plan_id)
        if self._state.budget_snapshot(plan_id).exhausted:
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
            return AdmissionResultV1(
                plan_id,
                PlanStateV1.WAITING_FOR_PHASE5,
                None,
                "phase5_catalog_dispatch_not_wired",
            )
        reservation = self._state.reserve_materialization(plan_id)
        if reservation.disposition == "bound":
            current = self._state.get_projection(plan_id)
            return AdmissionResultV1(
                plan_id,
                current.state,
                reservation.mission_id,
                "idempotent_store_binding",
            )
        if reservation.disposition == "leased":
            return AdmissionResultV1(
                plan_id,
                projection.state,
                None,
                "materialization_reserved_by_another_instance",
            )
        if reservation.disposition == "orphaned":
            if self._state.budget_snapshot(plan_id).exhausted:
                self._state.block_budget(plan_id)
            if self._state.get_projection(plan_id).state not in {
                PlanStateV1.BLOCKED,
                PlanStateV1.FAILED,
                PlanStateV1.CANCELLED,
            }:
                self._state.plans.set_state(
                    plan_id, PlanStateV1.BLOCKED, "orphaned mission is tombstoned"
                )
            return AdmissionResultV1(
                plan_id, PlanStateV1.BLOCKED, None, "orphaned_mission_tombstoned"
            )
        if reservation.lease_token is None:
            raise AgenticCoreV2Error("materialization owner has no durable lease token")
        title = self._mission_title(plan)
        # A recovered expired reservation may have crashed after create but
        # before binding. The deterministic title makes that orphan discoverable.
        candidates = tuple(
            mission for mission in self._missions.list() if mission.title == title
        )
        if candidates:
            orphan = sorted(candidates, key=lambda item: (item.created_at, item.id))[0]
            self._cancel_orphan(self._missions, orphan)
            self._state.tombstone_orphan(
                plan_id,
                reservation.lease_token,
                orphan.id,
                "mission discovered without immutable plan binding",
            )
            self._state.plans.set_state(
                plan_id,
                PlanStateV1.BLOCKED,
                "orphaned mission cancelled and tombstoned",
            )
            return AdmissionResultV1(
                plan_id, PlanStateV1.BLOCKED, None, "orphaned_mission_tombstoned"
            )
        mission_steps: list[dict[str, object]] = []
        for step, policy in zip(ordered, policies, strict=True):
            if policy.mission_tool is None:
                raise AgenticCoreV2Error("mission tool binding is unavailable")
            mission_steps.append(
                {
                    "tool": policy.mission_tool,
                    "args": step.arguments,
                    "estimated_provider_cost": 0.0,
                }
            )
        mission: Mission | None = None
        try:
            mission = self._missions.create(
                title,
                mission_steps,
                tool_allowlist=sorted({str(item["tool"]) for item in mission_steps}),
                max_steps=plan.goal.budget.max_steps,
                max_seconds=plan.goal.budget.wall_seconds,
                max_retries=plan.goal.budget.max_retries_per_step,
                provider_cost_limit=0.0,
            )
            summary = self._missions.plan_summary(mission.id)
            self._state.plans.bind_mission(plan_id, mission.id, summary["plan_digest"])
            self._state.finalize_materialization(
                plan_id, reservation.lease_token, mission.id
            )
        except BaseException:
            if mission is not None:
                try:
                    self._cancel_orphan(self._missions, mission)
                finally:
                    self._state.tombstone_orphan(
                        plan_id,
                        reservation.lease_token,
                        mission.id,
                        "mission create completed but binding/finalization failed",
                    )
                    current = self._state.get_projection(plan_id)
                    if current.state not in {
                        PlanStateV1.BLOCKED,
                        PlanStateV1.FAILED,
                        PlanStateV1.CANCELLED,
                        PlanStateV1.COMPLETE,
                    }:
                        self._state.plans.set_state(
                            plan_id,
                            PlanStateV1.BLOCKED,
                            "mission binding failed; orphan cancelled and tombstoned",
                        )
            raise
        return AdmissionResultV1(
            plan_id,
            PlanStateV1.AWAITING_APPROVAL,
            mission.id,
            "cross_instance_reserved_and_bound",
        )

    def execute_approved(
        self, plan_id: str, runner: ToolRunner | None = None
    ) -> Mission:
        plan = self._state.get_plan(plan_id)
        projection = self._state.get_projection(plan_id)
        if projection.mission_id is None:
            raise AgenticCoreV2Denied("plan has no stable mission binding")
        mission_id = projection.mission_id
        selected_runner = runner or run_mission_tool
        ordered = plan.ordered_steps()
        summary = self._missions.plan_summary(mission_id)
        expected: dict[str, StepV1] = {}
        for position, (step, materialized) in enumerate(
            zip(ordered, summary["plan"]["steps"], strict=True)
        ):
            key = _sha(
                f"{mission_id}:{position}:{materialized['tool']}:"
                f"{_canonical_arguments(materialized['args'])}"
            )
            expected[key] = step

        def compute_bounded_runner(
            tool: str, arguments: dict[str, Any], key: str
        ) -> Any:
            step = expected.get(key)
            if step is None:
                raise AgenticCoreV2Denied(
                    "mission idempotency key is not bound to the plan"
                )
            lease: ComputeLeaseV2
            try:
                lease = self._state.begin_compute(plan_id, f"step.{step.step_id}")
            except ComputeBudgetExhaustedV2:
                self._cancel_orphan(self._missions, self._missions.get(mission_id))
                self._state.block_budget(plan_id)
                return {
                    "status": "failed",
                    "data": {"reason": "BUDGET_EXHAUSTED"},
                    "evidence": [],
                    "postconditions": [
                        {"name": "compute_budget_respected", "satisfied": False}
                    ],
                    "waiting_for": None,
                }
            effective_timeout = min(step.timeout_seconds, lease.allowed_seconds)
            result_box: list[tuple[bool, object]] = []
            completed = threading.Event()
            cancelled = threading.Event()

            def invoke() -> None:
                try:
                    outcome: tuple[bool, object] = (
                        True,
                        selected_runner(tool, dict(arguments), key),
                    )
                except BaseException as exc:
                    outcome = (False, exc)
                if not cancelled.is_set():
                    result_box.append(outcome)
                completed.set()

            worker = threading.Thread(
                target=invoke,
                name="onyx-phase6-v2-compute-budget",
                daemon=True,
            )
            worker.start()
            finished = completed.wait(effective_timeout)
            if not finished:
                cancelled.set()
            snapshot = self._state.finish_compute(lease)
            if not finished or snapshot.exhausted:
                cancelled.set()
                try:
                    current = self._missions.get(mission_id)
                    self._cancel_orphan(self._missions, current)
                except (InvalidTransition, MissionError, KeyError):
                    pass
                if snapshot.exhausted:
                    self._state.block_budget(plan_id)
                return {
                    "status": "failed",
                    "data": {
                        "reason": "BUDGET_EXHAUSTED"
                        if snapshot.exhausted
                        else "STEP_TIMEOUT",
                        "effective_timeout_seconds": effective_timeout,
                    },
                    "evidence": [],
                    "postconditions": [
                        {"name": "compute_budget_respected", "satisfied": False}
                    ],
                    "waiting_for": None,
                }
            if not result_box:
                raise AgenticCoreV2Error("completed runner produced no bound result")
            succeeded, outcome = result_box[0]
            if not succeeded:
                if not isinstance(outcome, BaseException):
                    raise AgenticCoreV2Error("runner failure payload is invalid")
                raise outcome
            return outcome

        return self._base.execute_approved(plan_id, compute_bounded_runner)

    def verify(self, plan_id: str) -> VerificationReportV1:
        if self._state.budget_snapshot(plan_id).exhausted:
            self._state.block_budget(plan_id)
            raise ComputeBudgetExhaustedV2("BUDGET_EXHAUSTED")
        return self._base.verify(plan_id)

    def cancel(self, plan_id: str, reason: str = "owner_cancelled") -> RecoveryRecordV1:
        return self._base.cancel(plan_id, reason)

    def kill(self, reason: str = "owner_kill") -> tuple[RecoveryRecordV1, ...]:
        return self._base.kill(reason)

    def recover(self) -> tuple[RecoveryRecordV1, ...]:
        # This explicit API is the restart boundary; it never auto-replays an
        # in-flight step. Any persisted active lease is charged and closed.
        exhausted = self._state.recover_expired_compute(explicit_restart=True)
        for plan_id in exhausted:
            projection = self._state.get_projection(plan_id)
            if projection.mission_id is not None:
                try:
                    self._cancel_orphan(
                        self._missions, self._missions.get(projection.mission_id)
                    )
                except (InvalidTransition, MissionError, KeyError):
                    pass
            self._state.block_budget(plan_id)
        started = time.monotonic()
        records = self._base.recover()
        elapsed = time.monotonic() - started
        for record in records:
            if record.state in {
                PlanStateV1.COMPLETE,
                PlanStateV1.FAILED,
                PlanStateV1.CANCELLED,
            }:
                continue
            try:
                snapshot = self._state.charge_compute(record.plan_id, elapsed)
            except (ComputeBudgetExhaustedV2, AgenticCoreV2Denied):
                snapshot = self._state.budget_snapshot(record.plan_id)
            if snapshot.exhausted:
                projection = self._state.get_projection(record.plan_id)
                if projection.mission_id is not None:
                    try:
                        self._cancel_orphan(
                            self._missions,
                            self._missions.get(projection.mission_id),
                        )
                    except (InvalidTransition, MissionError, KeyError):
                        pass
                self._state.block_budget(record.plan_id)
        return tuple(
            RecoveryRecordV1(
                item.plan_id,
                item.mission_id,
                self._state.get_projection(item.plan_id).state,
                "BUDGET_EXHAUSTED"
                if self._state.budget_snapshot(item.plan_id).exhausted
                else item.reason,
            )
            for item in records
        )


def create_phase6_agentic_core_v2(
    *,
    gate: AgenticFeatureGateV2,
    sidecar_path: Path | str,
    mission_store: MissionStore,
    workspace_scope: WorkspaceScopeV1,
) -> AgenticCoreV2:
    """Host-owned explicit factory; no environment lookup or live defaults."""

    if type(gate) is not AgenticFeatureGateV2 or not gate.enabled:
        raise AgenticCoreV2Denied("Phase 6 V2 agentic core is disabled")
    state = AgenticStateStoreV2(sidecar_path, gate)
    return AgenticCoreV2(state, mission_store, workspace_scope)
