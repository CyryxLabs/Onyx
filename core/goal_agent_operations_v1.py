"""Governed goal and agent-operations records for Onyx.

This module is deliberately source-only and default-off.  It does not call a
model, execute a goal, start a worker, or grant authority.  It records bounded
operational metadata around :class:`OperationalGoalStoreV1` and treats that
store's Phase 6 evidence-gated completion as the only completion authority.

Threat boundary: model-originated values are untrusted.  The host process and
arbitrary in-process Python are the trusted computing base; future activation
must inject the scope capability, integrity key and evidence resolver without
placing any of them in model-visible arguments.  V1 retains authenticated
records for at least the configured period and stops at hard quotas; it never
silently deletes or rewrites audit history.
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
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Sequence

from core.missions import MissionStore
from core.operational_goals_v1 import (
    GoalLevelV1,
    GoalStatusV1,
    OperationalGoalV1,
    OperationalGoalStoreV1,
)
from core.phase6_agentic_core_v1 import PlanStateV1
from core.phase6_agentic_core_v6 import AgenticStateStoreV6, normalized_sql_v6


SCHEMA_VERSION = 1
FEATURE_FLAG = "ONYX_GOAL_AGENT_OPERATIONS_V1"
MAX_DECOMPOSITION_ITEMS = 24
MAX_PAGE_SIZE = 100
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,191}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_LEVEL_CHILD = {
    GoalLevelV1.OBJECTIVE.value: GoalLevelV1.KEY_RESULT.value,
    GoalLevelV1.KEY_RESULT.value: GoalLevelV1.MILESTONE.value,
    GoalLevelV1.MILESTONE.value: GoalLevelV1.TASK.value,
    GoalLevelV1.TASK.value: GoalLevelV1.DAILY_ACTION.value,
}


class GoalAgentOperationsError(RuntimeError):
    """Persistent state or integrity is invalid."""


class GoalAgentOperationsContractError(ValueError):
    """A caller supplied a non-canonical bounded contract."""


class GoalAgentOperationsDenied(PermissionError):
    """An operation crossed authority or lifecycle boundaries."""


class RoleStateV1(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    RETIRED = "retired"


class DecompositionStateV1(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class DelegationStateV1(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class UncertaintyV1(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class GoalAgentOperationsFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise GoalAgentOperationsContractError("enabled must be an exact boolean")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "GoalAgentOperationsFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True)
class GoalAgentScopeCapabilityV1:
    """Scope asserted by trusted host wiring; arbitrary in-process Python is TCB."""

    owner_profile_id: str
    workspace_id: str

    def __post_init__(self) -> None:
        _identifier(self.owner_profile_id, "owner_profile_id")
        _identifier(self.workspace_id, "workspace_id")


@dataclass(frozen=True)
class GoalAgentRetentionPolicyV1:
    """Hard cardinality and minimum-retention bounds; V1 never silently deletes."""

    policy_version: int = 1
    max_roles: int = 128
    max_estimates: int = 2_048
    max_decompositions: int = 512
    max_cadences: int = 2_048
    max_delegations: int = 4_096
    max_events: int = 20_000
    minimum_retention_seconds: int = 31_536_000

    def __post_init__(self) -> None:
        for name, minimum, maximum in (
            ("policy_version", 1, 1),
            ("max_roles", 1, 1_024),
            ("max_estimates", 1, 20_000),
            ("max_decompositions", 1, 5_000),
            ("max_cadences", 1, 20_000),
            ("max_delegations", 1, 20_000),
            ("max_events", 10, 100_000),
            ("minimum_retention_seconds", 86_400, 315_360_000),
        ):
            _integer(getattr(self, name), name, minimum, maximum)


@dataclass(frozen=True)
class CanonicalGoalCompletionEvidenceV1:
    goal_id: str
    plan_id: str
    mission_id: str
    goal_verification_digest: str
    mission_plan_digest: str
    authority_snapshot_hash: str
    receipt_digests: tuple[str, ...]
    evidence_digest: str

    def payload(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "plan_id": self.plan_id,
            "mission_id": self.mission_id,
            "goal_verification_digest": self.goal_verification_digest,
            "mission_plan_digest": self.mission_plan_digest,
            "authority_snapshot_hash": self.authority_snapshot_hash,
            "receipt_digests": list(self.receipt_digests),
            "evidence_digest": self.evidence_digest,
        }


class GoalCompletionEvidenceResolverV1:
    """Derive completion evidence from exact Phase 6 and MissionStore truth."""

    def __init__(
        self, state_store: AgenticStateStoreV6, mission_store: MissionStore
    ) -> None:
        if type(state_store) is not AgenticStateStoreV6:
            raise GoalAgentOperationsContractError("exact AgenticStateStoreV6 is required")
        if type(mission_store) is not MissionStore:
            raise GoalAgentOperationsContractError("exact MissionStore is required")
        self._state = state_store
        self._missions = mission_store

    def resolve(self, goal: OperationalGoalV1) -> CanonicalGoalCompletionEvidenceV1:
        if (
            type(goal) is not OperationalGoalV1
            or getattr(goal, "status", None) is not GoalStatusV1.COMPLETED
            or type(getattr(goal, "verification_digest", None)) is not str
            or _SHA256.fullmatch(goal.verification_digest) is None
            or type(getattr(goal, "plan_id", None)) is not str
            or type(getattr(goal, "mission_id", None)) is not str
        ):
            raise GoalAgentOperationsDenied(
                "delegation completion requires completed goal evidence"
            )
        projection = self._state.get_projection(goal.plan_id)
        if (
            projection.state is not PlanStateV1.COMPLETE
            or projection.mission_id != goal.mission_id
            or type(projection.mission_plan_digest) is not str
            or _SHA256.fullmatch(projection.mission_plan_digest) is None
        ):
            raise GoalAgentOperationsDenied("Phase 6 completion evidence diverges")
        mission = self._missions.get(goal.mission_id)
        snapshot = self._missions.authority_snapshot(goal.mission_id)
        if mission.state != "succeeded" or snapshot.state != "succeeded":
            raise GoalAgentOperationsDenied("mission authority is not succeeded")
        mission_event_hashes = {
            str(item["event_hash"]) for item in self._missions.events(goal.mission_id)
        }
        receipts = self._state.plans.receipts(goal.plan_id)
        if not receipts:
            raise GoalAgentOperationsDenied("Phase 6 verification receipts are unavailable")
        receipt_digests: list[str] = []
        for receipt in receipts:
            if (
                receipt.status != "verified"
                or receipt.plan_id != goal.plan_id
                or receipt.mission_id != goal.mission_id
                or receipt.authority_snapshot_hash != snapshot.snapshot_hash
                or receipt.event_hash not in mission_event_hashes
            ):
                raise GoalAgentOperationsDenied("Phase 6 receipt binding diverges")
            receipt_digests.append(
                hashlib.sha256(
                    _canonical_json(receipt.payload()).encode("utf-8")
                ).hexdigest()
            )
        canonical = {
            "goal_id": goal.goal_id,
            "plan_id": goal.plan_id,
            "mission_id": goal.mission_id,
            "goal_verification_digest": goal.verification_digest,
            "mission_plan_digest": projection.mission_plan_digest,
            "authority_snapshot_hash": snapshot.snapshot_hash,
            "receipt_digests": sorted(receipt_digests),
        }
        evidence_digest = hashlib.sha256(
            _canonical_json(canonical).encode("utf-8")
        ).hexdigest()
        return CanonicalGoalCompletionEvidenceV1(
            goal.goal_id,
            goal.plan_id,
            goal.mission_id,
            goal.verification_digest,
            projection.mission_plan_digest,
            snapshot.snapshot_hash,
            tuple(sorted(receipt_digests)),
            evidence_digest,
        )


@dataclass(frozen=True)
class EffortEstimateV1:
    estimate_id: str
    owner_profile_id: str
    workspace_id: str
    goal_id: str
    effort_min_minutes: int
    effort_max_minutes: int
    uncertainty: UncertaintyV1
    dependency_goal_ids: tuple[str, ...]
    assumptions: tuple[str, ...]
    promise: bool
    estimate_digest: str
    created_at: float


@dataclass(frozen=True)
class RoleRecordV1:
    role_id: str
    owner_profile_id: str
    workspace_id: str
    name: str
    purpose: str
    responsibilities: tuple[str, ...]
    state: RoleStateV1
    revision: int
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class DecompositionRecordV1:
    decomposition_id: str
    owner_profile_id: str
    workspace_id: str
    root_goal_id: str
    request_id: str
    proposal: Mapping[str, object]
    proposal_digest: str
    state: DecompositionStateV1
    revision: int
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class AccountabilityCadenceV1:
    cadence_id: str
    owner_profile_id: str
    workspace_id: str
    goal_id: str
    role_id: str | None
    interval_seconds: int
    next_due_at: float
    enabled: bool
    request_id: str
    created_at: float


@dataclass(frozen=True)
class DelegationRecordV1:
    delegation_id: str
    owner_profile_id: str
    workspace_id: str
    goal_id: str
    from_role_id: str | None
    to_role_id: str
    instruction: str
    request_id: str
    state: DelegationStateV1
    completion_digest: str | None
    revision: int
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class BoundedPageV1:
    items: tuple[object, ...]
    next_cursor: int | None


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise GoalAgentOperationsContractError(f"{label} is invalid")
    return value


def _text(value: object, label: str, maximum: int) -> str:
    if type(value) is not str:
        raise GoalAgentOperationsContractError(f"{label} must be text")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum or "\x00" in normalized:
        raise GoalAgentOperationsContractError(f"{label} is invalid")
    return normalized


def _integer(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise GoalAgentOperationsContractError(f"{label} is invalid")
    return value


def _timestamp(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GoalAgentOperationsContractError(f"{label} is invalid")
    output = float(value)
    if not math.isfinite(output) or output <= 0:
        raise GoalAgentOperationsContractError(f"{label} is invalid")
    return output


def _canonical_json(value: object, *, maximum: int = 65_536) -> str:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise GoalAgentOperationsContractError("value is not canonical JSON") from exc
    if len(encoded.encode("utf-8")) > maximum:
        raise GoalAgentOperationsContractError("value exceeds its byte budget")
    return encoded


def _strings(
    values: object, label: str, *, maximum_items: int, maximum_text: int
) -> tuple[str, ...]:
    if type(values) not in {tuple, list} or not 1 <= len(values) <= maximum_items:
        raise GoalAgentOperationsContractError(f"{label} is invalid")
    result = tuple(_text(item, f"{label} item", maximum_text) for item in values)
    if len(set(result)) != len(result):
        raise GoalAgentOperationsContractError(f"{label} contains duplicates")
    return result


def _private_path(path: Path) -> None:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise GoalAgentOperationsContractError("an explicit absolute database path is required")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise GoalAgentOperationsDenied("linked operations directory is forbidden")
    attributes = getattr(path.parent.stat(), "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if attributes & reparse:
        raise GoalAgentOperationsDenied("reparse-point operations directory is forbidden")
    if path.exists() and path.is_symlink():
        raise GoalAgentOperationsDenied("linked operations database is forbidden")


class GoalAgentOperationsStoreV1:
    """HMAC-authenticated operations metadata bound to operational goals."""

    _DDL = (
        "CREATE TABLE metadata(schema_version INTEGER NOT NULL CHECK(schema_version=1))",
        """CREATE TABLE ledger_state(
          singleton INTEGER PRIMARY KEY CHECK(singleton=1),
          owner_profile_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
          event_count INTEGER NOT NULL CHECK(event_count>=0),
          tail_seq INTEGER NOT NULL CHECK(tail_seq>=0), tail_mac TEXT NOT NULL,
          projection_count INTEGER NOT NULL CHECK(projection_count>=0),
          projection_digest TEXT NOT NULL,
          roles_count INTEGER NOT NULL CHECK(roles_count>=0),
          estimates_count INTEGER NOT NULL CHECK(estimates_count>=0),
          decompositions_count INTEGER NOT NULL CHECK(decompositions_count>=0),
          cadences_count INTEGER NOT NULL CHECK(cadences_count>=0),
          delegations_count INTEGER NOT NULL CHECK(delegations_count>=0),
          policy_version INTEGER NOT NULL CHECK(policy_version>=1),
          max_roles INTEGER NOT NULL CHECK(max_roles>=1),
          max_estimates INTEGER NOT NULL CHECK(max_estimates>=1),
          max_decompositions INTEGER NOT NULL CHECK(max_decompositions>=1),
          max_cadences INTEGER NOT NULL CHECK(max_cadences>=1),
          max_delegations INTEGER NOT NULL CHECK(max_delegations>=1),
          max_events INTEGER NOT NULL CHECK(max_events>=10),
          minimum_retention_seconds INTEGER NOT NULL,
          head_mac TEXT NOT NULL)""",
        """CREATE TABLE roles(
          role_id TEXT PRIMARY KEY, owner_profile_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL, name TEXT NOT NULL, purpose TEXT NOT NULL,
          responsibilities_json TEXT NOT NULL,
          state TEXT NOT NULL CHECK(state IN ('active','paused','retired')),
          request_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>=1),
          created_at REAL NOT NULL, updated_at REAL NOT NULL, state_mac TEXT NOT NULL,
          UNIQUE(owner_profile_id,workspace_id,request_id))""",
        """CREATE TABLE estimates(
          estimate_id TEXT PRIMARY KEY, owner_profile_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL, goal_id TEXT NOT NULL,
          effort_min_minutes INTEGER NOT NULL, effort_max_minutes INTEGER NOT NULL,
          uncertainty TEXT NOT NULL CHECK(uncertainty IN ('low','medium','high')),
          dependencies_json TEXT NOT NULL, assumptions_json TEXT NOT NULL,
          promise INTEGER NOT NULL CHECK(promise=0), estimate_digest TEXT NOT NULL UNIQUE,
          created_at REAL NOT NULL, state_mac TEXT NOT NULL)""",
        """CREATE TABLE decompositions(
          decomposition_id TEXT PRIMARY KEY, owner_profile_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL, root_goal_id TEXT NOT NULL,
          request_id TEXT NOT NULL, proposal_json TEXT NOT NULL,
          proposal_digest TEXT NOT NULL,
          state TEXT NOT NULL CHECK(state IN ('proposed','accepted','rejected')),
          revision INTEGER NOT NULL CHECK(revision>=1), created_at REAL NOT NULL,
          updated_at REAL NOT NULL, state_mac TEXT NOT NULL,
          UNIQUE(owner_profile_id,workspace_id,request_id))""",
        """CREATE TABLE cadences(
          cadence_id TEXT PRIMARY KEY, owner_profile_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL, goal_id TEXT NOT NULL, role_id TEXT,
          interval_seconds INTEGER NOT NULL, next_due_at REAL NOT NULL,
          enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), request_id TEXT NOT NULL,
          created_at REAL NOT NULL, state_mac TEXT NOT NULL,
          UNIQUE(owner_profile_id,workspace_id,request_id))""",
        """CREATE TABLE delegations(
          delegation_id TEXT PRIMARY KEY, owner_profile_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL, goal_id TEXT NOT NULL, from_role_id TEXT,
          to_role_id TEXT NOT NULL, instruction TEXT NOT NULL, request_id TEXT NOT NULL,
          state TEXT NOT NULL CHECK(state IN
            ('proposed','accepted','declined','cancelled','completed')),
          completion_receipt_json TEXT, completion_digest TEXT,
          revision INTEGER NOT NULL CHECK(revision>=1), created_at REAL NOT NULL,
          updated_at REAL NOT NULL, state_mac TEXT NOT NULL,
          UNIQUE(owner_profile_id,workspace_id,request_id))""",
        """CREATE TABLE operation_events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL,
          entity_id TEXT NOT NULL, owner_profile_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL, timestamp REAL NOT NULL, event TEXT NOT NULL,
          detail_json TEXT NOT NULL, prev_mac TEXT NOT NULL, event_mac TEXT NOT NULL UNIQUE)""",
        "CREATE INDEX idx_roles_scope ON roles(owner_profile_id,workspace_id,state)",
        "CREATE INDEX idx_estimates_goal ON estimates(owner_profile_id,workspace_id,goal_id)",
        "CREATE INDEX idx_delegations_inbox ON delegations(owner_profile_id,workspace_id,to_role_id,state,created_at)",
        "CREATE INDEX idx_cadences_scope ON cadences(owner_profile_id,workspace_id,goal_id,role_id,created_at)",
        "CREATE INDEX idx_events_scope_seq ON operation_events(owner_profile_id,workspace_id,seq)",
        "CREATE TRIGGER operation_events_no_update BEFORE UPDATE ON operation_events BEGIN SELECT RAISE(ABORT,'operation events are immutable'); END",
        "CREATE TRIGGER operation_events_no_delete BEFORE DELETE ON operation_events BEGIN SELECT RAISE(ABORT,'operation events are immutable'); END",
    )
    _STATE_TABLES = ("roles", "estimates", "decompositions", "cadences", "delegations")
    _TABLE_IDS = {
        "roles": "role_id",
        "estimates": "estimate_id",
        "decompositions": "decomposition_id",
        "cadences": "cadence_id",
        "delegations": "delegation_id",
    }

    def __init__(
        self,
        path: Path | str,
        gate: GoalAgentOperationsFeatureGateV1,
        goals: OperationalGoalStoreV1,
        scope: GoalAgentScopeCapabilityV1,
        evidence_resolver: GoalCompletionEvidenceResolverV1,
        integrity_key: bytes,
        policy: GoalAgentRetentionPolicyV1 | None = None,
    ) -> None:
        if type(gate) is not GoalAgentOperationsFeatureGateV1 or not gate.enabled:
            raise GoalAgentOperationsDenied("goal-agent operations are disabled")
        if type(goals) is not OperationalGoalStoreV1:
            raise GoalAgentOperationsContractError("exact OperationalGoalStoreV1 is required")
        if type(scope) is not GoalAgentScopeCapabilityV1:
            raise GoalAgentOperationsContractError(
                "exact GoalAgentScopeCapabilityV1 is required"
            )
        if type(evidence_resolver) is not GoalCompletionEvidenceResolverV1:
            raise GoalAgentOperationsContractError(
                "exact GoalCompletionEvidenceResolverV1 is required"
            )
        if type(integrity_key) is not bytes or not 32 <= len(integrity_key) <= 128:
            raise GoalAgentOperationsContractError("integrity_key must be 32 to 128 bytes")
        self.path = Path(path)
        _private_path(self.path)
        self._goals = goals
        self._scope = scope
        self._evidence = evidence_resolver
        self._policy = policy or GoalAgentRetentionPolicyV1()
        if type(self._policy) is not GoalAgentRetentionPolicyV1:
            raise GoalAgentOperationsContractError(
                "policy must be an exact GoalAgentRetentionPolicyV1"
            )
        self._key = bytes(integrity_key)
        self._lock = threading.RLock()
        self._expected_signature = self._build_expected_signature()
        self.initialize()

    @property
    def owner_profile_id(self) -> str:
        return self._scope.owner_profile_id

    @property
    def workspace_id(self) -> str:
        return self._scope.workspace_id

    @staticmethod
    def _signature(connection: sqlite3.Connection) -> str:
        objects = []
        for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ):
            if row[3] is None:
                raise GoalAgentOperationsError("schema object has no stored SQL")
            objects.append((row[0], row[1], row[2], normalized_sql_v6(str(row[3]))))
        details: dict[str, object] = {}
        for table in sorted(row[1] for row in objects if row[0] == "table"):
            details[f"table_xinfo:{table}"] = [
                tuple(item) for item in connection.execute(f"PRAGMA table_xinfo('{table}')")
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
            for statement in cls._DDL:
                connection.execute(statement)
            connection.execute("INSERT INTO metadata VALUES(1)")
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

    def _mac(self, domain: str, payload: object) -> str:
        body = domain.encode("ascii") + b"\0" + _canonical_json(payload).encode("utf-8")
        return hmac.new(self._key, body, hashlib.sha256).hexdigest()

    @staticmethod
    def _row_payload(row: sqlite3.Row) -> dict[str, object]:
        return {
            key: row[key]
            for key in row.keys()
            if key not in {"state_mac", "rowid"}
        }

    def _leaf(self, table: str, entity_id: str, state_mac: str) -> int:
        return int(
            self._mac(
                "projection-leaf",
                {"table": table, "entity_id": entity_id, "state_mac": state_mac},
            ),
            16,
        )

    @staticmethod
    def _head_payload(row: sqlite3.Row | Mapping[str, object]) -> dict[str, object]:
        keys = (
            "singleton",
            "owner_profile_id",
            "workspace_id",
            "event_count",
            "tail_seq",
            "tail_mac",
            "projection_count",
            "projection_digest",
            "roles_count",
            "estimates_count",
            "decompositions_count",
            "cadences_count",
            "delegations_count",
            "policy_version",
            "max_roles",
            "max_estimates",
            "max_decompositions",
            "max_cadences",
            "max_delegations",
            "max_events",
            "minimum_retention_seconds",
        )
        return {key: row[key] for key in keys}

    def _head(self, connection: sqlite3.Connection) -> sqlite3.Row:
        rows = connection.execute("SELECT * FROM ledger_state").fetchall()
        if len(rows) != 1:
            raise GoalAgentOperationsError("authenticated ledger head is unavailable")
        return rows[0]

    def _verify_head(self, connection: sqlite3.Connection) -> sqlite3.Row:
        head = self._head(connection)
        expected = self._mac("ledger-head", self._head_payload(head))
        if not hmac.compare_digest(str(head["head_mac"]), expected):
            raise GoalAgentOperationsError("authenticated ledger head diverges")
        if (
            head["owner_profile_id"] != self.owner_profile_id
            or head["workspace_id"] != self.workspace_id
        ):
            raise GoalAgentOperationsDenied("store scope capability does not match ledger")
        expected_policy = {
            "policy_version": self._policy.policy_version,
            "max_roles": self._policy.max_roles,
            "max_estimates": self._policy.max_estimates,
            "max_decompositions": self._policy.max_decompositions,
            "max_cadences": self._policy.max_cadences,
            "max_delegations": self._policy.max_delegations,
            "max_events": self._policy.max_events,
            "minimum_retention_seconds": self._policy.minimum_retention_seconds,
        }
        if any(int(head[key]) != value for key, value in expected_policy.items()):
            raise GoalAgentOperationsDenied("retention policy does not match ledger")
        event_count = int(head["event_count"])
        tail_seq = int(head["tail_seq"])
        tail_mac = str(head["tail_mac"])
        if event_count == 0:
            if tail_seq != 0 or tail_mac != "":
                raise GoalAgentOperationsError("empty ledger head is invalid")
        else:
            tail = connection.execute(
                "SELECT seq,event_mac FROM operation_events WHERE seq=?", (tail_seq,)
            ).fetchone()
            if (
                tail is None
                or int(tail["seq"]) != tail_seq
                or not hmac.compare_digest(str(tail["event_mac"]), tail_mac)
                or connection.execute(
                    "SELECT 1 FROM operation_events WHERE seq>? LIMIT 1", (tail_seq,)
                ).fetchone()
                is not None
            ):
                raise GoalAgentOperationsError("ledger tail diverges")
        if (
            type(head["projection_digest"]) is not str
            or _SHA256.fullmatch(str(head["projection_digest"])) is None
        ):
            raise GoalAgentOperationsError("projection digest is invalid")
        return head

    def _verify_row(self, table: str, row: sqlite3.Row) -> sqlite3.Row:
        expected = self._mac(f"row:{table}", self._row_payload(row))
        if not hmac.compare_digest(str(row["state_mac"]), expected):
            raise GoalAgentOperationsError(f"{table} row authentication failed")
        if (
            row["owner_profile_id"] != self.owner_profile_id
            or row["workspace_id"] != self.workspace_id
        ):
            raise GoalAgentOperationsError(f"{table} row crossed the bound scope")
        return row

    def _verify_state_full(self, connection: sqlite3.Connection) -> None:
        head = self._verify_head(connection)
        projection = 0
        projection_count = 0
        table_counts: dict[str, int] = {}
        for table in self._STATE_TABLES:
            table_count = 0
            for row in connection.execute(f"SELECT * FROM {table}"):
                self._verify_row(table, row)
                projection ^= self._leaf(
                    table, str(row[self._TABLE_IDS[table]]), str(row["state_mac"])
                )
                projection_count += 1
                table_count += 1
            table_counts[table] = table_count
        maxima = {
            "roles": self._policy.max_roles,
            "estimates": self._policy.max_estimates,
            "decompositions": self._policy.max_decompositions,
            "cadences": self._policy.max_cadences,
            "delegations": self._policy.max_delegations,
        }
        if any(table_counts[table] > maxima[table] for table in self._STATE_TABLES):
            raise GoalAgentOperationsError("stored projection exceeds retention quota")
        previous = ""
        event_count = 0
        tail_seq = 0
        for row in connection.execute("SELECT * FROM operation_events ORDER BY seq"):
            payload = {
                "seq": int(row["seq"]),
                "entity_type": str(row["entity_type"]),
                "entity_id": str(row["entity_id"]),
                "owner_profile_id": str(row["owner_profile_id"]),
                "workspace_id": str(row["workspace_id"]),
                "timestamp": float(row["timestamp"]),
                "event": str(row["event"]),
                "detail_json": str(row["detail_json"]),
                "prev_mac": str(row["prev_mac"]),
            }
            expected = self._mac("event", payload)
            if row["prev_mac"] != previous or not hmac.compare_digest(
                str(row["event_mac"]), expected
            ):
                raise GoalAgentOperationsError("operation event lineage diverges")
            if (
                row["owner_profile_id"] != self.owner_profile_id
                or row["workspace_id"] != self.workspace_id
            ):
                raise GoalAgentOperationsError("operation event crossed the bound scope")
            previous = expected
            event_count += 1
            tail_seq = int(row["seq"])
        if event_count > self._policy.max_events:
            raise GoalAgentOperationsError("stored events exceed retention quota")
        if (
            int(head["event_count"]) != event_count
            or int(head["tail_seq"]) != tail_seq
            or str(head["tail_mac"]) != previous
            or int(head["projection_count"]) != projection_count
            or str(head["projection_digest"]) != f"{projection:064x}"
            or any(
                int(head[f"{table}_count"]) != table_counts[table]
                for table in self._STATE_TABLES
            )
        ):
            raise GoalAgentOperationsError("ledger head does not authenticate full state")

    def _new_head(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "singleton": 1,
            "owner_profile_id": self.owner_profile_id,
            "workspace_id": self.workspace_id,
            "event_count": 0,
            "tail_seq": 0,
            "tail_mac": "",
            "projection_count": 0,
            "projection_digest": "0" * 64,
            "roles_count": 0,
            "estimates_count": 0,
            "decompositions_count": 0,
            "cadences_count": 0,
            "delegations_count": 0,
            "policy_version": self._policy.policy_version,
            "max_roles": self._policy.max_roles,
            "max_estimates": self._policy.max_estimates,
            "max_decompositions": self._policy.max_decompositions,
            "max_cadences": self._policy.max_cadences,
            "max_delegations": self._policy.max_delegations,
            "max_events": self._policy.max_events,
            "minimum_retention_seconds": self._policy.minimum_retention_seconds,
        }
        payload["head_mac"] = self._mac("ledger-head", payload)
        return payload

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
                    connection.execute("INSERT INTO metadata VALUES(?)", (SCHEMA_VERSION,))
                    connection.execute(
                        "INSERT INTO ledger_state VALUES(:singleton,:owner_profile_id,"
                        ":workspace_id,:event_count,:tail_seq,:tail_mac,:projection_count,"
                        ":projection_digest,:roles_count,:estimates_count,"
                        ":decompositions_count,:cadences_count,:delegations_count,"
                        ":policy_version,:max_roles,:max_estimates,:max_decompositions,"
                        ":max_cadences,:max_delegations,:max_events,"
                        ":minimum_retention_seconds,:head_mac)",
                        self._new_head(),
                    )
                    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                    connection.execute("COMMIT")
                metadata = [tuple(row) for row in connection.execute("SELECT * FROM metadata")]
                if (
                    int(connection.execute("PRAGMA user_version").fetchone()[0])
                    != SCHEMA_VERSION
                    or metadata != [(SCHEMA_VERSION,)]
                    or self._signature(connection) != self._expected_signature
                    or connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or connection.execute("PRAGMA foreign_key_check").fetchall()
                ):
                    raise GoalAgentOperationsError("operations schema authentication failed")
                self._verify_state_full(connection)
                self._schema_cookie = int(
                    connection.execute("PRAGMA schema_version").fetchone()[0]
                )
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
            if os.name != "nt" and self.path.exists():
                os.chmod(self.path, 0o600)

    def _verified_connection(self) -> sqlite3.Connection:
        connection = self._connect()
        try:
            if (
                int(connection.execute("PRAGMA schema_version").fetchone()[0])
                != self._schema_cookie
            ):
                raise GoalAgentOperationsError("operations schema changed after open")
            self._verify_head(connection)
            return connection
        except BaseException:
            connection.close()
            raise

    def _ensure_quota(self, connection: sqlite3.Connection, table: str) -> None:
        maximum = {
            "roles": self._policy.max_roles,
            "estimates": self._policy.max_estimates,
            "decompositions": self._policy.max_decompositions,
            "cadences": self._policy.max_cadences,
            "delegations": self._policy.max_delegations,
        }[table]
        head = self._verify_head(connection)
        if int(head[f"{table}_count"]) >= maximum:
            raise GoalAgentOperationsDenied(f"{table} retention quota reached")

    def _append_event(
        self,
        connection: sqlite3.Connection,
        *,
        entity_type: str,
        entity_id: str,
        event: str,
        detail: object,
        projection_table: str,
        old_state_mac: str | None,
        new_state_mac: str,
    ) -> None:
        head = self._verify_head(connection)
        if int(head["event_count"]) >= self._policy.max_events:
            raise GoalAgentOperationsDenied("operation event retention quota reached")
        previous = str(head["tail_mac"])
        seq = int(head["tail_seq"]) + 1
        timestamp = time.time()
        detail_json = _canonical_json(detail)
        payload = {
            "seq": seq,
            "entity_type": _identifier(entity_type, "entity_type"),
            "entity_id": _identifier(entity_id, "entity_id"),
            "owner_profile_id": self.owner_profile_id,
            "workspace_id": self.workspace_id,
            "timestamp": timestamp,
            "event": _identifier(event, "event"),
            "detail_json": detail_json,
            "prev_mac": previous,
        }
        event_mac = self._mac("event", payload)
        connection.execute(
            "INSERT INTO operation_events VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                seq,
                payload["entity_type"],
                payload["entity_id"],
                self.owner_profile_id,
                self.workspace_id,
                timestamp,
                payload["event"],
                detail_json,
                previous,
                event_mac,
            ),
        )

        projection = int(str(head["projection_digest"]), 16)
        projection_count = int(head["projection_count"])
        if old_state_mac is not None:
            projection ^= self._leaf(projection_table, entity_id, old_state_mac)
        else:
            projection_count += 1
        projection ^= self._leaf(projection_table, entity_id, new_state_mac)
        updated_head: dict[str, object] = {
            "singleton": 1,
            "owner_profile_id": self.owner_profile_id,
            "workspace_id": self.workspace_id,
            "event_count": int(head["event_count"]) + 1,
            "tail_seq": seq,
            "tail_mac": event_mac,
            "projection_count": projection_count,
            "projection_digest": f"{projection:064x}",
            "roles_count": int(head["roles_count"]),
            "estimates_count": int(head["estimates_count"]),
            "decompositions_count": int(head["decompositions_count"]),
            "cadences_count": int(head["cadences_count"]),
            "delegations_count": int(head["delegations_count"]),
            "policy_version": int(head["policy_version"]),
            "max_roles": int(head["max_roles"]),
            "max_estimates": int(head["max_estimates"]),
            "max_decompositions": int(head["max_decompositions"]),
            "max_cadences": int(head["max_cadences"]),
            "max_delegations": int(head["max_delegations"]),
            "max_events": int(head["max_events"]),
            "minimum_retention_seconds": self._policy.minimum_retention_seconds,
        }
        if old_state_mac is None:
            updated_head[f"{projection_table}_count"] = (
                int(updated_head[f"{projection_table}_count"]) + 1
            )
        updated_head["head_mac"] = self._mac("ledger-head", updated_head)
        connection.execute(
            "UPDATE ledger_state SET event_count=:event_count,tail_seq=:tail_seq,"
            "tail_mac=:tail_mac,projection_count=:projection_count,"
            "projection_digest=:projection_digest,roles_count=:roles_count,"
            "estimates_count=:estimates_count,decompositions_count=:decompositions_count,"
            "cadences_count=:cadences_count,delegations_count=:delegations_count,"
            "head_mac=:head_mac WHERE singleton=1",
            updated_head,
        )

    def _goal(self, goal_id: object):
        key = _identifier(goal_id, "goal_id")
        goal = self._goals.get(key)
        if (
            goal.owner_profile_id != self.owner_profile_id
            or goal.workspace_id != self.workspace_id
        ):
            raise GoalAgentOperationsDenied("goal scope binding is invalid")
        return goal

    def _role_from(self, row: sqlite3.Row) -> RoleRecordV1:
        self._verify_row("roles", row)
        return RoleRecordV1(
            str(row["role_id"]), str(row["owner_profile_id"]),
            str(row["workspace_id"]), str(row["name"]), str(row["purpose"]),
            tuple(json.loads(str(row["responsibilities_json"]))),
            RoleStateV1(str(row["state"])), int(row["revision"]),
            float(row["created_at"]), float(row["updated_at"]),
        )

    def register_role(
        self, *, name: str, purpose: str, responsibilities: Sequence[str], request_id: str,
    ) -> RoleRecordV1:
        owner = self.owner_profile_id
        workspace = self.workspace_id
        request = _identifier(request_id, "request_id")
        safe_name = _text(name, "name", 120)
        safe_purpose = _text(purpose, "purpose", 1_000)
        duties = _strings(responsibilities, "responsibilities", maximum_items=16, maximum_text=240)
        intended = {"name": safe_name, "purpose": safe_purpose, "responsibilities": list(duties)}
        with self._lock:
            connection = self._verified_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_head(connection)
                prior = connection.execute(
                    "SELECT * FROM roles WHERE owner_profile_id=? AND workspace_id=? AND request_id=?",
                    (owner, workspace, request),
                ).fetchone()
                if prior is not None:
                    role = self._role_from(prior)
                    if intended != {"name": role.name, "purpose": role.purpose, "responsibilities": list(role.responsibilities)}:
                        raise GoalAgentOperationsDenied("role request replay diverges")
                    connection.execute("COMMIT")
                    return role
                self._ensure_quota(connection, "roles")
                role_id = "role_" + uuid.uuid4().hex
                now = time.time()
                payload = {
                    "role_id": role_id, "owner_profile_id": owner, "workspace_id": workspace,
                    "name": safe_name, "purpose": safe_purpose,
                    "responsibilities_json": _canonical_json(list(duties)),
                    "state": RoleStateV1.ACTIVE.value, "request_id": request,
                    "revision": 1, "created_at": now, "updated_at": now,
                }
                payload["state_mac"] = self._mac("row:roles", payload)
                connection.execute(
                    "INSERT INTO roles VALUES(:role_id,:owner_profile_id,:workspace_id,:name,:purpose,:responsibilities_json,:state,:request_id,:revision,:created_at,:updated_at,:state_mac)",
                    payload,
                )
                self._append_event(connection, entity_type="role", entity_id=role_id,
                    event="role.created", detail={"request_id": request},
                    projection_table="roles", old_state_mac=None,
                    new_state_mac=str(payload["state_mac"]))
                connection.execute("COMMIT")
                return self.get_role(role_id)
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def get_role(self, role_id: str) -> RoleRecordV1:
        key = _identifier(role_id, "role_id")
        connection = self._verified_connection()
        try:
            row = connection.execute("SELECT * FROM roles WHERE role_id=?", (key,)).fetchone()
            if row is None:
                raise KeyError(key)
            return self._role_from(row)
        finally:
            connection.close()

    def transition_role(
        self, role_id: str, *, target: RoleStateV1, reason: str,
    ) -> RoleRecordV1:
        if type(target) is not RoleStateV1:
            raise GoalAgentOperationsContractError("target must be an exact RoleStateV1")
        role = self.get_role(role_id)
        safe_reason = _text(reason, "reason", 512)
        allowed = {RoleStateV1.ACTIVE: {RoleStateV1.PAUSED, RoleStateV1.RETIRED},
                   RoleStateV1.PAUSED: {RoleStateV1.ACTIVE, RoleStateV1.RETIRED}}
        if target is role.state:
            return role
        if target not in allowed.get(role.state, set()):
            raise GoalAgentOperationsDenied("role transition is not allowed")
        with self._lock:
            connection = self._verified_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute("SELECT * FROM roles WHERE role_id=?", (role.role_id,)).fetchone()
                if row is None or int(row["revision"]) != role.revision:
                    raise GoalAgentOperationsDenied("role changed during transition")
                payload = self._row_payload(row)
                payload.update(state=target.value, revision=role.revision + 1, updated_at=time.time())
                mac = self._mac("row:roles", payload)
                connection.execute("UPDATE roles SET state=?,revision=?,updated_at=?,state_mac=? WHERE role_id=?",
                    (target.value, payload["revision"], payload["updated_at"], mac, role.role_id))
                self._append_event(connection, entity_type="role", entity_id=role.role_id,
                    event=f"role.{target.value}", detail={"reason": safe_reason},
                    projection_table="roles", old_state_mac=str(row["state_mac"]),
                    new_state_mac=mac)
                connection.execute("COMMIT")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return self.get_role(role.role_id)

    def roster(
        self,
        *,
        states: Sequence[RoleStateV1] = (RoleStateV1.ACTIVE, RoleStateV1.PAUSED),
        limit: int = 50,
        cursor: int = 0,
    ) -> BoundedPageV1:
        bounded = _integer(limit, "limit", 1, MAX_PAGE_SIZE)
        after = _integer(cursor, "cursor", 0, 2_147_483_647)
        if (
            type(states) not in {tuple, list}
            or not states
            or len(states) > len(RoleStateV1)
            or any(type(item) is not RoleStateV1 for item in states)
        ):
            raise GoalAgentOperationsContractError("states is invalid")
        values = tuple(item.value for item in states)
        placeholders = ",".join("?" for _ in values)
        connection = self._verified_connection()
        try:
            rows = connection.execute(
                f"SELECT rowid,* FROM roles WHERE owner_profile_id=? AND workspace_id=? "
                f"AND rowid>? AND state IN ({placeholders}) ORDER BY rowid LIMIT ?",
                (self.owner_profile_id, self.workspace_id, after, *values, bounded + 1),
            ).fetchall()
            visible = rows[:bounded]
            return BoundedPageV1(
                tuple(self._role_from(row) for row in visible),
                int(visible[-1]["rowid"]) if len(rows) > bounded else None,
            )
        finally:
            connection.close()

    def record_estimate(
        self, *, goal_id: str,
        effort_min_minutes: int, effort_max_minutes: int, uncertainty: UncertaintyV1,
        dependency_goal_ids: Sequence[str] = (), assumptions: Sequence[str] = (),
    ) -> EffortEstimateV1:
        goal = self._goal(goal_id)
        minimum = _integer(effort_min_minutes, "effort_min_minutes", 1, 525_600)
        maximum = _integer(effort_max_minutes, "effort_max_minutes", minimum, 1_051_200)
        if type(uncertainty) is not UncertaintyV1:
            raise GoalAgentOperationsContractError("uncertainty must be an exact UncertaintyV1")
        if type(dependency_goal_ids) not in {tuple, list} or len(dependency_goal_ids) > 24:
            raise GoalAgentOperationsContractError("dependency_goal_ids is invalid")
        dependencies = tuple(sorted(_identifier(item, "dependency_goal_id") for item in dependency_goal_ids))
        if len(set(dependencies)) != len(dependencies) or goal.goal_id in dependencies:
            raise GoalAgentOperationsContractError("dependency_goal_ids is not canonical")
        for dependency in dependencies:
            self._goal(dependency)
        if type(assumptions) not in {tuple, list} or len(assumptions) > 16:
            raise GoalAgentOperationsContractError("assumptions is invalid")
        safe_assumptions = tuple(_text(item, "assumption", 300) for item in assumptions)
        if len(set(safe_assumptions)) != len(safe_assumptions):
            raise GoalAgentOperationsContractError("assumptions contains duplicates")
        semantic = {
            "owner_profile_id": goal.owner_profile_id, "workspace_id": goal.workspace_id,
            "goal_id": goal.goal_id, "effort_min_minutes": minimum,
            "effort_max_minutes": maximum, "uncertainty": uncertainty.value,
            "dependency_goal_ids": list(dependencies), "assumptions": list(safe_assumptions),
            "promise": False,
        }
        digest = hashlib.sha256(_canonical_json(semantic).encode("utf-8")).hexdigest()
        estimate_id = "est_" + digest[:32]
        with self._lock:
            connection = self._verified_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_head(connection)
                prior = connection.execute("SELECT * FROM estimates WHERE estimate_digest=?", (digest,)).fetchone()
                if prior is None:
                    self._ensure_quota(connection, "estimates")
                    now = time.time()
                    payload = {
                        "estimate_id": estimate_id, "owner_profile_id": goal.owner_profile_id,
                        "workspace_id": goal.workspace_id, "goal_id": goal.goal_id,
                        "effort_min_minutes": minimum, "effort_max_minutes": maximum,
                        "uncertainty": uncertainty.value,
                        "dependencies_json": _canonical_json(list(dependencies)),
                        "assumptions_json": _canonical_json(list(safe_assumptions)),
                        "promise": 0, "estimate_digest": digest, "created_at": now,
                    }
                    payload["state_mac"] = self._mac("row:estimates", payload)
                    connection.execute("INSERT INTO estimates VALUES(:estimate_id,:owner_profile_id,:workspace_id,:goal_id,:effort_min_minutes,:effort_max_minutes,:uncertainty,:dependencies_json,:assumptions_json,:promise,:estimate_digest,:created_at,:state_mac)", payload)
                    self._append_event(connection, entity_type="estimate", entity_id=estimate_id,
                        event="estimate.recorded", detail={"estimate_digest": digest, "promise": False},
                        projection_table="estimates", old_state_mac=None,
                        new_state_mac=str(payload["state_mac"]))
                connection.execute("COMMIT")
                row = connection.execute("SELECT * FROM estimates WHERE estimate_digest=?", (digest,)).fetchone()
                assert row is not None
                self._verify_row("estimates", row)
                return EffortEstimateV1(
                    str(row["estimate_id"]), str(row["owner_profile_id"]), str(row["workspace_id"]),
                    str(row["goal_id"]), int(row["effort_min_minutes"]), int(row["effort_max_minutes"]),
                    UncertaintyV1(str(row["uncertainty"])), tuple(json.loads(str(row["dependencies_json"]))),
                    tuple(json.loads(str(row["assumptions_json"]))), False,
                    str(row["estimate_digest"]), float(row["created_at"]),
                )
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def estimates(
        self, *, goal_id: str | None = None, limit: int = 50, cursor: int = 0
    ) -> BoundedPageV1:
        bounded = _integer(limit, "limit", 1, MAX_PAGE_SIZE)
        after = _integer(cursor, "cursor", 0, 2_147_483_647)
        parameters: list[object] = [self.owner_profile_id, self.workspace_id, after]
        goal_clause = ""
        if goal_id is not None:
            goal_clause = " AND goal_id=?"
            parameters.append(self._goal(goal_id).goal_id)
        parameters.append(bounded + 1)
        connection = self._verified_connection()
        try:
            rows = connection.execute(
                "SELECT rowid,* FROM estimates WHERE owner_profile_id=? AND workspace_id=? "
                f"AND rowid>?{goal_clause} ORDER BY rowid LIMIT ?",
                parameters,
            ).fetchall()
            visible = rows[:bounded]
            items = []
            for row in visible:
                self._verify_row("estimates", row)
                items.append(
                    EffortEstimateV1(
                        str(row["estimate_id"]), str(row["owner_profile_id"]),
                        str(row["workspace_id"]), str(row["goal_id"]),
                        int(row["effort_min_minutes"]), int(row["effort_max_minutes"]),
                        UncertaintyV1(str(row["uncertainty"])),
                        tuple(json.loads(str(row["dependencies_json"]))),
                        tuple(json.loads(str(row["assumptions_json"]))), False,
                        str(row["estimate_digest"]), float(row["created_at"]),
                    )
                )
            return BoundedPageV1(
                tuple(items), int(visible[-1]["rowid"]) if len(rows) > bounded else None
            )
        finally:
            connection.close()

    def _validated_proposal(self, root_level: str, proposal: object) -> dict[str, object]:
        if type(proposal) is not dict or set(proposal) != {"version", "summary", "items"}:
            raise GoalAgentOperationsContractError("proposal must use the exact structured schema")
        if proposal["version"] != 1:
            raise GoalAgentOperationsContractError("proposal version is unsupported")
        summary = _text(proposal["summary"], "proposal summary", 1_000)
        raw_items = proposal["items"]
        if type(raw_items) is not list or not 1 <= len(raw_items) <= MAX_DECOMPOSITION_ITEMS:
            raise GoalAgentOperationsContractError("proposal items exceed the bounded plan size")
        items: dict[str, dict[str, object]] = {}
        required = {"client_id", "parent", "level", "title", "objective", "definition_of_done", "dependencies", "effort_min_minutes", "effort_max_minutes", "uncertainty"}
        for raw in raw_items:
            if type(raw) is not dict or set(raw) != required:
                raise GoalAgentOperationsContractError("proposal item must use the exact structured schema")
            client = _identifier(raw["client_id"], "client_id")
            if client in items:
                raise GoalAgentOperationsContractError("proposal client_id is duplicated")
            parent = raw["parent"]
            if parent != "$root":
                parent = _identifier(parent, "parent")
            level = raw["level"]
            if type(level) is not str or level not in {item.value for item in GoalLevelV1}:
                raise GoalAgentOperationsContractError("proposal level is invalid")
            done = _strings(raw["definition_of_done"], "definition_of_done", maximum_items=16, maximum_text=191)
            for condition in done:
                _identifier(condition, "definition_of_done item")
            dependencies = raw["dependencies"]
            if type(dependencies) is not list or len(dependencies) > MAX_DECOMPOSITION_ITEMS:
                raise GoalAgentOperationsContractError("proposal dependencies are invalid")
            deps = tuple(_identifier(item, "dependency") for item in dependencies)
            if len(set(deps)) != len(deps) or client in deps:
                raise GoalAgentOperationsContractError("proposal dependencies are not canonical")
            minimum = _integer(raw["effort_min_minutes"], "effort_min_minutes", 1, 525_600)
            maximum = _integer(raw["effort_max_minutes"], "effort_max_minutes", minimum, 1_051_200)
            try:
                uncertainty = UncertaintyV1(raw["uncertainty"])
            except (TypeError, ValueError) as exc:
                raise GoalAgentOperationsContractError("proposal uncertainty is invalid") from exc
            items[client] = {
                "client_id": client, "parent": parent, "level": level,
                "title": _text(raw["title"], "title", 240),
                "objective": _text(raw["objective"], "objective", 2_000),
                "definition_of_done": list(done), "dependencies": list(deps),
                "effort_min_minutes": minimum, "effort_max_minutes": maximum,
                "uncertainty": uncertainty.value,
            }
        for client, item in items.items():
            parent = item["parent"]
            if parent != "$root" and parent not in items:
                raise GoalAgentOperationsContractError("proposal parent is unavailable")
            parent_level = root_level if parent == "$root" else str(items[str(parent)]["level"])
            if _LEVEL_CHILD.get(parent_level) != item["level"]:
                raise GoalAgentOperationsContractError("proposal hierarchy skips a goal level")
            if any(dependency not in items for dependency in item["dependencies"]):
                raise GoalAgentOperationsContractError("proposal dependency is unavailable")

        def visit(node: str, edge: str, active: set[str], done: set[str]) -> None:
            if node in active:
                raise GoalAgentOperationsContractError(f"proposal {edge} cycle detected")
            if node in done:
                return
            active.add(node)
            links = ([items[node]["parent"]] if edge == "parent" else items[node]["dependencies"])
            for link in links:
                if link != "$root":
                    visit(str(link), edge, active, done)
            active.remove(node)
            done.add(node)

        for edge in ("parent", "dependency"):
            done_nodes: set[str] = set()
            for client in items:
                visit(client, edge, set(), done_nodes)
        normalized = {"version": 1, "summary": summary, "items": [items[key] for key in sorted(items)]}
        _canonical_json(normalized, maximum=32_768)
        return normalized

    def _decomposition_from(self, row: sqlite3.Row) -> DecompositionRecordV1:
        self._verify_row("decompositions", row)
        return DecompositionRecordV1(
            str(row["decomposition_id"]), str(row["owner_profile_id"]),
            str(row["workspace_id"]), str(row["root_goal_id"]), str(row["request_id"]),
            json.loads(str(row["proposal_json"])), str(row["proposal_digest"]),
            DecompositionStateV1(str(row["state"])), int(row["revision"]),
            float(row["created_at"]), float(row["updated_at"]),
        )

    def submit_decomposition(
        self, *, root_goal_id: str, request_id: str, proposal: Mapping[str, object],
    ) -> DecompositionRecordV1:
        goal = self._goal(root_goal_id)
        if goal.status in {GoalStatusV1.COMPLETED, GoalStatusV1.CANCELLED}:
            raise GoalAgentOperationsDenied("terminal goal cannot be decomposed")
        request = _identifier(request_id, "request_id")
        normalized = self._validated_proposal(goal.level.value, proposal)
        proposal_json = _canonical_json(normalized, maximum=32_768)
        digest = hashlib.sha256(proposal_json.encode("utf-8")).hexdigest()
        with self._lock:
            connection = self._verified_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_head(connection)
                prior = connection.execute("SELECT * FROM decompositions WHERE owner_profile_id=? AND workspace_id=? AND request_id=?", (goal.owner_profile_id, goal.workspace_id, request)).fetchone()
                if prior is not None:
                    record = self._decomposition_from(prior)
                    if record.root_goal_id != goal.goal_id or record.proposal_digest != digest:
                        raise GoalAgentOperationsDenied("decomposition request replay diverges")
                    connection.execute("COMMIT")
                    return record
                self._ensure_quota(connection, "decompositions")
                decomposition_id = "dec_" + uuid.uuid4().hex
                now = time.time()
                payload = {"decomposition_id": decomposition_id, "owner_profile_id": goal.owner_profile_id,
                    "workspace_id": goal.workspace_id, "root_goal_id": goal.goal_id,
                    "request_id": request, "proposal_json": proposal_json, "proposal_digest": digest,
                    "state": DecompositionStateV1.PROPOSED.value, "revision": 1,
                    "created_at": now, "updated_at": now}
                payload["state_mac"] = self._mac("row:decompositions", payload)
                connection.execute("INSERT INTO decompositions VALUES(:decomposition_id,:owner_profile_id,:workspace_id,:root_goal_id,:request_id,:proposal_json,:proposal_digest,:state,:revision,:created_at,:updated_at,:state_mac)", payload)
                self._append_event(connection, entity_type="decomposition", entity_id=decomposition_id,
                    event="decomposition.proposed", detail={"proposal_digest": digest, "item_count": len(normalized["items"])},
                    projection_table="decompositions", old_state_mac=None,
                    new_state_mac=str(payload["state_mac"]))
                connection.execute("COMMIT")
                row = connection.execute("SELECT * FROM decompositions WHERE decomposition_id=?", (decomposition_id,)).fetchone()
                assert row is not None
                return self._decomposition_from(row)
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def review_decomposition(
        self, decomposition_id: str, *, decision: DecompositionStateV1, reason: str,
    ) -> DecompositionRecordV1:
        key = _identifier(decomposition_id, "decomposition_id")
        if type(decision) is not DecompositionStateV1 or decision not in {
            DecompositionStateV1.ACCEPTED,
            DecompositionStateV1.REJECTED,
        }:
            raise GoalAgentOperationsContractError("decision must be accepted or rejected")
        safe_reason = _text(reason, "reason", 512)
        with self._lock:
            connection = self._verified_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_head(connection)
                row = connection.execute("SELECT * FROM decompositions WHERE decomposition_id=?", (key,)).fetchone()
                if row is None:
                    raise KeyError(key)
                record = self._decomposition_from(row)
                self._goal(record.root_goal_id)
                if record.state is decision:
                    connection.execute("COMMIT")
                    return record
                if record.state is not DecompositionStateV1.PROPOSED:
                    raise GoalAgentOperationsDenied("decomposition is already terminal")
                payload = self._row_payload(row)
                payload.update(state=decision.value, revision=record.revision + 1, updated_at=time.time())
                mac = self._mac("row:decompositions", payload)
                connection.execute("UPDATE decompositions SET state=?,revision=?,updated_at=?,state_mac=? WHERE decomposition_id=?",
                    (decision.value, payload["revision"], payload["updated_at"], mac, key))
                self._append_event(connection, entity_type="decomposition", entity_id=key,
                    event=f"decomposition.{decision.value}", detail={"reason": safe_reason},
                    projection_table="decompositions", old_state_mac=str(row["state_mac"]),
                    new_state_mac=mac)
                connection.execute("COMMIT")
                updated = connection.execute("SELECT * FROM decompositions WHERE decomposition_id=?", (key,)).fetchone()
                assert updated is not None
                return self._decomposition_from(updated)
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def decompositions(
        self, *, root_goal_id: str | None = None, limit: int = 50, cursor: int = 0
    ) -> BoundedPageV1:
        bounded = _integer(limit, "limit", 1, MAX_PAGE_SIZE)
        after = _integer(cursor, "cursor", 0, 2_147_483_647)
        parameters: list[object] = [self.owner_profile_id, self.workspace_id, after]
        goal_clause = ""
        if root_goal_id is not None:
            goal_clause = " AND root_goal_id=?"
            parameters.append(self._goal(root_goal_id).goal_id)
        parameters.append(bounded + 1)
        connection = self._verified_connection()
        try:
            rows = connection.execute(
                "SELECT rowid,* FROM decompositions WHERE owner_profile_id=? AND workspace_id=? "
                f"AND rowid>?{goal_clause} ORDER BY rowid LIMIT ?",
                parameters,
            ).fetchall()
            visible = rows[:bounded]
            return BoundedPageV1(
                tuple(self._decomposition_from(row) for row in visible),
                int(visible[-1]["rowid"]) if len(rows) > bounded else None,
            )
        finally:
            connection.close()

    def configure_cadence(
        self, *, goal_id: str,
        role_id: str | None, interval_seconds: int, next_due_at: float,
        enabled: bool, request_id: str,
    ) -> AccountabilityCadenceV1:
        goal = self._goal(goal_id)
        request = _identifier(request_id, "request_id")
        interval = _integer(interval_seconds, "interval_seconds", 900, 604_800)
        due = _timestamp(next_due_at, "next_due_at")
        if type(enabled) is not bool:
            raise GoalAgentOperationsContractError("enabled must be an exact boolean")
        role_key = None
        if role_id is not None:
            role = self.get_role(role_id)
            if role.state is RoleStateV1.RETIRED:
                raise GoalAgentOperationsDenied("retired role cannot own a cadence")
            role_key = role.role_id
        semantic = {"goal_id": goal.goal_id, "role_id": role_key, "interval_seconds": interval,
                    "next_due_at": due, "enabled": enabled}
        with self._lock:
            connection = self._verified_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_head(connection)
                prior = connection.execute("SELECT * FROM cadences WHERE owner_profile_id=? AND workspace_id=? AND request_id=?", (goal.owner_profile_id, goal.workspace_id, request)).fetchone()
                if prior is not None:
                    observed = {"goal_id": prior["goal_id"], "role_id": prior["role_id"],
                        "interval_seconds": int(prior["interval_seconds"]), "next_due_at": float(prior["next_due_at"]),
                        "enabled": bool(prior["enabled"])}
                    if observed != semantic:
                        raise GoalAgentOperationsDenied("cadence request replay diverges")
                    connection.execute("COMMIT")
                    return self._cadence_from(prior)
                self._ensure_quota(connection, "cadences")
                cadence_id = "cad_" + uuid.uuid4().hex
                now = time.time()
                payload = {"cadence_id": cadence_id, "owner_profile_id": goal.owner_profile_id,
                    "workspace_id": goal.workspace_id, **semantic, "enabled": int(enabled),
                    "request_id": request, "created_at": now}
                payload["state_mac"] = self._mac("row:cadences", payload)
                connection.execute("INSERT INTO cadences VALUES(:cadence_id,:owner_profile_id,:workspace_id,:goal_id,:role_id,:interval_seconds,:next_due_at,:enabled,:request_id,:created_at,:state_mac)", payload)
                self._append_event(connection, entity_type="cadence", entity_id=cadence_id,
                    event="cadence.configured", detail={**semantic, "enabled": enabled},
                    projection_table="cadences", old_state_mac=None,
                    new_state_mac=str(payload["state_mac"]))
                connection.execute("COMMIT")
                row = connection.execute("SELECT * FROM cadences WHERE cadence_id=?", (cadence_id,)).fetchone()
                assert row is not None
                return self._cadence_from(row)
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def _cadence_from(self, row: sqlite3.Row) -> AccountabilityCadenceV1:
        self._verify_row("cadences", row)
        return AccountabilityCadenceV1(
            str(row["cadence_id"]), str(row["owner_profile_id"]), str(row["workspace_id"]),
            str(row["goal_id"]), str(row["role_id"]) if row["role_id"] is not None else None,
            int(row["interval_seconds"]), float(row["next_due_at"]), bool(row["enabled"]),
            str(row["request_id"]), float(row["created_at"]),
        )

    def due_accountability(
        self, *, now: float, limit: int = 50, cursor: int = 0,
    ) -> BoundedPageV1:
        current = _timestamp(now, "now")
        bounded = _integer(limit, "limit", 1, MAX_PAGE_SIZE)
        after = _integer(cursor, "cursor", 0, 2_147_483_647)
        connection = self._verified_connection()
        try:
            rows = connection.execute(
                "SELECT c.rowid,c.* FROM cadences c WHERE c.owner_profile_id=? AND c.workspace_id=? "
                "AND c.rowid>? AND c.enabled=1 AND c.next_due_at<=? AND NOT EXISTS (SELECT 1 FROM cadences newer "
                "WHERE newer.owner_profile_id=c.owner_profile_id AND newer.workspace_id=c.workspace_id "
                "AND newer.goal_id=c.goal_id AND COALESCE(newer.role_id,'')=COALESCE(c.role_id,'') "
                "AND newer.created_at>c.created_at) ORDER BY c.rowid LIMIT ?",
                (self.owner_profile_id, self.workspace_id, after, current, bounded + 1),
            ).fetchall()
            visible = rows[:bounded]
            return BoundedPageV1(
                tuple(self._cadence_from(row) for row in visible),
                int(visible[-1]["rowid"]) if len(rows) > bounded else None,
            )
        finally:
            connection.close()

    def cadences(self, *, limit: int = 50, cursor: int = 0) -> BoundedPageV1:
        bounded = _integer(limit, "limit", 1, MAX_PAGE_SIZE)
        after = _integer(cursor, "cursor", 0, 2_147_483_647)
        connection = self._verified_connection()
        try:
            rows = connection.execute(
                "SELECT rowid,* FROM cadences WHERE owner_profile_id=? AND workspace_id=? "
                "AND rowid>? ORDER BY rowid LIMIT ?",
                (self.owner_profile_id, self.workspace_id, after, bounded + 1),
            ).fetchall()
            visible = rows[:bounded]
            return BoundedPageV1(
                tuple(self._cadence_from(row) for row in visible),
                int(visible[-1]["rowid"]) if len(rows) > bounded else None,
            )
        finally:
            connection.close()

    def _role_bound(self, role_id: str, *, active: bool) -> RoleRecordV1:
        role = self.get_role(role_id)
        if active and role.state is not RoleStateV1.ACTIVE:
            raise GoalAgentOperationsDenied("delegation requires an active role")
        return role

    def _delegation_from(self, row: sqlite3.Row) -> DelegationRecordV1:
        self._verify_row("delegations", row)
        return DelegationRecordV1(
            str(row["delegation_id"]), str(row["owner_profile_id"]), str(row["workspace_id"]),
            str(row["goal_id"]), str(row["from_role_id"]) if row["from_role_id"] is not None else None,
            str(row["to_role_id"]), str(row["instruction"]), str(row["request_id"]),
            DelegationStateV1(str(row["state"])),
            str(row["completion_digest"]) if row["completion_digest"] is not None else None,
            int(row["revision"]), float(row["created_at"]), float(row["updated_at"]),
        )

    def delegate(
        self, *, goal_id: str, from_role_id: str | None, to_role_id: str,
        instruction: str, request_id: str,
    ) -> DelegationRecordV1:
        goal = self._goal(goal_id)
        if goal.status in {GoalStatusV1.COMPLETED, GoalStatusV1.CANCELLED}:
            raise GoalAgentOperationsDenied("terminal goal cannot be delegated")
        to_role = self._role_bound(to_role_id, active=True)
        from_key = None
        if from_role_id is not None:
            from_role = self._role_bound(from_role_id, active=True)
            from_key = from_role.role_id
            if from_key == to_role.role_id:
                raise GoalAgentOperationsContractError("a role cannot delegate to itself")
        safe_instruction = _text(instruction, "instruction", 2_000)
        request = _identifier(request_id, "request_id")
        semantic = {"goal_id": goal.goal_id, "from_role_id": from_key,
                    "to_role_id": to_role.role_id, "instruction": safe_instruction}
        with self._lock:
            connection = self._verified_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_head(connection)
                prior = connection.execute("SELECT * FROM delegations WHERE owner_profile_id=? AND workspace_id=? AND request_id=?", (goal.owner_profile_id, goal.workspace_id, request)).fetchone()
                if prior is not None:
                    record = self._delegation_from(prior)
                    observed = {"goal_id": record.goal_id, "from_role_id": record.from_role_id,
                                "to_role_id": record.to_role_id, "instruction": record.instruction}
                    if observed != semantic:
                        raise GoalAgentOperationsDenied("delegation request replay diverges")
                    connection.execute("COMMIT")
                    return record
                self._ensure_quota(connection, "delegations")
                delegation_id = "del_" + uuid.uuid4().hex
                now = time.time()
                payload = {"delegation_id": delegation_id, "owner_profile_id": goal.owner_profile_id,
                    "workspace_id": goal.workspace_id, **semantic, "request_id": request,
                    "state": DelegationStateV1.PROPOSED.value,
                    "completion_receipt_json": None, "completion_digest": None,
                    "revision": 1, "created_at": now, "updated_at": now}
                payload["state_mac"] = self._mac("row:delegations", payload)
                connection.execute("INSERT INTO delegations VALUES(:delegation_id,:owner_profile_id,:workspace_id,:goal_id,:from_role_id,:to_role_id,:instruction,:request_id,:state,:completion_receipt_json,:completion_digest,:revision,:created_at,:updated_at,:state_mac)", payload)
                self._append_event(connection, entity_type="delegation", entity_id=delegation_id,
                    event="delegation.proposed", detail={"goal_id": goal.goal_id, "to_role_id": to_role.role_id},
                    projection_table="delegations", old_state_mac=None,
                    new_state_mac=str(payload["state_mac"]))
                connection.execute("COMMIT")
                row = connection.execute("SELECT * FROM delegations WHERE delegation_id=?", (delegation_id,)).fetchone()
                assert row is not None
                return self._delegation_from(row)
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def _completion_binding(
        self, record: DelegationRecordV1, goal: object
    ) -> tuple[str, str]:
        evidence = self._evidence.resolve(goal)
        receipt_json = _canonical_json(evidence.payload(), maximum=16_384)
        completion_digest = hashlib.sha256(
            (record.delegation_id + "\0" + receipt_json).encode("utf-8")
        ).hexdigest()
        return receipt_json, completion_digest

    def transition_delegation(
        self, delegation_id: str, *, target: DelegationStateV1, reason: str,
    ) -> DelegationRecordV1:
        key = _identifier(delegation_id, "delegation_id")
        if type(target) is not DelegationStateV1:
            raise GoalAgentOperationsContractError("target must be an exact DelegationStateV1")
        safe_reason = _text(reason, "reason", 512)
        with self._lock:
            connection = self._verified_connection()
            try:
                connection.execute("BEGIN IMMEDIATE")
                self._verify_head(connection)
                row = connection.execute("SELECT * FROM delegations WHERE delegation_id=?", (key,)).fetchone()
                if row is None:
                    raise KeyError(key)
                record = self._delegation_from(row)
                goal = self._goal(record.goal_id)
                if record.state is target:
                    if target is DelegationStateV1.COMPLETED:
                        replay_json, replay_digest = self._completion_binding(record, goal)
                        if (
                            not hmac.compare_digest(record.completion_digest or "", replay_digest)
                            or row["completion_receipt_json"] != replay_json
                        ):
                            raise GoalAgentOperationsDenied(
                                "delegation completion replay diverges"
                            )
                    connection.execute("COMMIT")
                    return record
                allowed = {DelegationStateV1.PROPOSED: {DelegationStateV1.ACCEPTED, DelegationStateV1.DECLINED, DelegationStateV1.CANCELLED},
                           DelegationStateV1.ACCEPTED: {DelegationStateV1.CANCELLED, DelegationStateV1.COMPLETED}}
                if target not in allowed.get(record.state, set()):
                    raise GoalAgentOperationsDenied("delegation transition is not allowed")
                receipt_json = None
                completion_digest = None
                if target is DelegationStateV1.COMPLETED:
                    receipt_json, completion_digest = self._completion_binding(record, goal)
                payload = self._row_payload(row)
                payload.update(state=target.value, completion_receipt_json=receipt_json,
                               completion_digest=completion_digest, revision=record.revision + 1,
                               updated_at=time.time())
                mac = self._mac("row:delegations", payload)
                connection.execute("UPDATE delegations SET state=?,completion_receipt_json=?,completion_digest=?,revision=?,updated_at=?,state_mac=? WHERE delegation_id=?",
                    (target.value, receipt_json, completion_digest, payload["revision"], payload["updated_at"], mac, key))
                self._append_event(connection, entity_type="delegation", entity_id=key,
                    event=f"delegation.{target.value}",
                    detail={"reason": safe_reason, "completion_digest": completion_digest},
                    projection_table="delegations", old_state_mac=str(row["state_mac"]),
                    new_state_mac=mac)
                connection.execute("COMMIT")
                updated = connection.execute("SELECT * FROM delegations WHERE delegation_id=?", (key,)).fetchone()
                assert updated is not None
                return self._delegation_from(updated)
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def inbox(
        self, *, to_role_id: str,
        states: Sequence[DelegationStateV1] = (DelegationStateV1.PROPOSED, DelegationStateV1.ACCEPTED),
        limit: int = 50, cursor: int = 0,
    ) -> BoundedPageV1:
        role = self._role_bound(to_role_id, active=False)
        bounded = _integer(limit, "limit", 1, MAX_PAGE_SIZE)
        after = _integer(cursor, "cursor", 0, 2_147_483_647)
        if type(states) not in {tuple, list} or not states or len(states) > len(DelegationStateV1) or any(type(item) is not DelegationStateV1 for item in states):
            raise GoalAgentOperationsContractError("states is invalid")
        values = tuple(item.value for item in states)
        placeholders = ",".join("?" for _ in values)
        connection = self._verified_connection()
        try:
            rows = connection.execute(
                f"SELECT rowid,* FROM delegations WHERE owner_profile_id=? AND workspace_id=? "
                f"AND rowid>? AND to_role_id=? AND state IN ({placeholders}) ORDER BY rowid LIMIT ?",
                (self.owner_profile_id, self.workspace_id, after, role.role_id, *values, bounded + 1),
            ).fetchall()
            visible = rows[:bounded]
            return BoundedPageV1(
                tuple(self._delegation_from(row) for row in visible),
                int(visible[-1]["rowid"]) if len(rows) > bounded else None,
            )
        finally:
            connection.close()

    def delegations(self, *, limit: int = 50, cursor: int = 0) -> BoundedPageV1:
        bounded = _integer(limit, "limit", 1, MAX_PAGE_SIZE)
        after = _integer(cursor, "cursor", 0, 2_147_483_647)
        connection = self._verified_connection()
        try:
            rows = connection.execute(
                "SELECT rowid,* FROM delegations WHERE owner_profile_id=? AND workspace_id=? "
                "AND rowid>? ORDER BY rowid LIMIT ?",
                (self.owner_profile_id, self.workspace_id, after, bounded + 1),
            ).fetchall()
            visible = rows[:bounded]
            return BoundedPageV1(
                tuple(self._delegation_from(row) for row in visible),
                int(visible[-1]["rowid"]) if len(rows) > bounded else None,
            )
        finally:
            connection.close()

    def events(self, *, limit: int = 50, cursor: int = 0) -> BoundedPageV1:
        bounded = _integer(limit, "limit", 1, MAX_PAGE_SIZE)
        after = _integer(cursor, "cursor", 0, 2_147_483_647)
        connection = self._verified_connection()
        try:
            rows = connection.execute(
                "SELECT * FROM operation_events WHERE owner_profile_id=? AND workspace_id=? "
                "AND seq>? ORDER BY seq LIMIT ?",
                (self.owner_profile_id, self.workspace_id, after, bounded + 1),
            ).fetchall()
            visible = rows[:bounded]
            previous = ""
            if visible and int(visible[0]["seq"]) > 1:
                prior = connection.execute(
                    "SELECT event_mac FROM operation_events WHERE seq=?",
                    (int(visible[0]["seq"]) - 1,),
                ).fetchone()
                if prior is None:
                    raise GoalAgentOperationsError("paged event predecessor is unavailable")
                previous = str(prior["event_mac"])
            items: list[dict[str, object]] = []
            for row in visible:
                payload = {
                    "seq": int(row["seq"]), "entity_type": str(row["entity_type"]),
                    "entity_id": str(row["entity_id"]),
                    "owner_profile_id": str(row["owner_profile_id"]),
                    "workspace_id": str(row["workspace_id"]),
                    "timestamp": float(row["timestamp"]), "event": str(row["event"]),
                    "detail_json": str(row["detail_json"]), "prev_mac": str(row["prev_mac"]),
                }
                expected = self._mac("event", payload)
                if row["prev_mac"] != previous or not hmac.compare_digest(
                    str(row["event_mac"]), expected
                ):
                    raise GoalAgentOperationsError("paged operation event diverges")
                previous = expected
                items.append(
                    {"seq": int(row["seq"]), "entity_type": str(row["entity_type"]),
                     "entity_id": str(row["entity_id"]), "event": str(row["event"]),
                     "detail": json.loads(str(row["detail_json"])), "event_mac": expected}
                )
            return BoundedPageV1(
                tuple(items), int(visible[-1]["seq"]) if len(rows) > bounded else None
            )
        finally:
            connection.close()
