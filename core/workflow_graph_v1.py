"""Governed, durable workflow graphs over existing Phase 6 authority.

This is a clean-room Onyx implementation.  A workflow is declarative metadata;
it cannot execute shell commands, HTTP requests, provider calls or arbitrary
code.  V1 binds exactly one plan node to an already-approved Phase 6 mission
and advances to complete only from independently verified Phase 6 receipts.
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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from core.missions import MissionError, MissionStore
from core.phase6_agentic_core_v1 import PlanStateV1
from core.phase6_agentic_core_v6 import AgenticStateStoreV6


SCHEMA_VERSION = 1
FEATURE_FLAG = "ONYX_WORKFLOW_GRAPH_V1"
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,191}")
_CONFIG_KEY = re.compile(r"[a-z][a-z0-9_.-]{1,63}")
_EVENT_TYPE = re.compile(r"[a-z][a-z0-9_.-]{2,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SENSITIVE = frozenset(
    {
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "password",
        "secret",
        "token",
    }
)
_MAX_NODES = 32
_MAX_EDGES = 64


class WorkflowGraphError(RuntimeError):
    pass


class WorkflowGraphContractError(ValueError):
    pass


class WorkflowGraphDenied(PermissionError):
    pass


class WorkflowNodeKindV1(str, Enum):
    TRIGGER = "trigger"
    CONDITION = "condition"
    TRANSFORM = "transform"
    PLAN = "plan"
    OUTPUT = "output"


class WorkflowStatusV1(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise WorkflowGraphContractError(f"{label} is invalid")
    return value


def _text(value: object, label: str, maximum: int) -> str:
    if type(value) is not str:
        raise WorkflowGraphContractError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum or any(ord(char) < 32 for char in result):
        raise WorkflowGraphContractError(f"{label} is invalid")
    return result


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def _private_path(path: Path) -> None:
    if not path.is_absolute() or path.is_symlink():
        raise WorkflowGraphContractError("workflow store path is invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise WorkflowGraphContractError("workflow store parent is invalid")
    if os.name != "nt":
        os.chmod(path.parent, 0o700)


def _config(value: object) -> tuple[tuple[str, str], ...]:
    if type(value) is not dict or len(value) > 8:
        raise WorkflowGraphContractError("workflow node config is invalid")
    result: list[tuple[str, str]] = []
    for raw_key, raw_value in value.items():
        if type(raw_key) is not str or _CONFIG_KEY.fullmatch(raw_key) is None:
            raise WorkflowGraphContractError("workflow config key is invalid")
        if any(part in _SENSITIVE for part in raw_key.split(".")):
            raise WorkflowGraphDenied("workflow config cannot contain secrets")
        if type(raw_value) not in {str, bool, int, float}:
            raise WorkflowGraphContractError("workflow config value is invalid")
        if isinstance(raw_value, float) and not math.isfinite(raw_value):
            raise WorkflowGraphContractError("workflow config value is invalid")
        encoded = _canonical_json(raw_value)
        if len(encoded) > 512:
            raise WorkflowGraphContractError("workflow config value is too large")
        result.append((raw_key, encoded))
    return tuple(sorted(result))


@dataclass(frozen=True, slots=True)
class WorkflowNodeV1:
    node_id: str
    kind: WorkflowNodeKindV1
    config: tuple[tuple[str, str], ...]

    @classmethod
    def create(cls, value: Mapping[str, object]) -> "WorkflowNodeV1":
        if type(value) is not dict or set(value) != {"node_id", "kind", "config"}:
            raise WorkflowGraphContractError("workflow node is malformed")
        try:
            kind = WorkflowNodeKindV1(value["kind"])
        except (TypeError, ValueError) as exc:
            raise WorkflowGraphContractError("workflow node kind is invalid") from exc
        node = cls(
            _identifier(value["node_id"], "node_id"),
            kind,
            _config(value["config"]),
        )
        config = node.config_dict()
        required = {
            WorkflowNodeKindV1.TRIGGER: {"event_type"},
            WorkflowNodeKindV1.CONDITION: {"field", "equals"},
            WorkflowNodeKindV1.TRANSFORM: {"operation"},
            WorkflowNodeKindV1.PLAN: {"label"},
            WorkflowNodeKindV1.OUTPUT: {"label"},
        }[kind]
        if set(config) != required:
            raise WorkflowGraphContractError("workflow node config shape is invalid")
        if kind is WorkflowNodeKindV1.TRIGGER and _EVENT_TYPE.fullmatch(
            str(config["event_type"])
        ) is None:
            raise WorkflowGraphContractError("workflow trigger event is invalid")
        if kind is WorkflowNodeKindV1.TRANSFORM and config["operation"] not in {
            "select",
            "summarize_metadata",
            "normalize_metadata",
        }:
            raise WorkflowGraphDenied("workflow transform is not allowlisted")
        return node

    def config_dict(self) -> dict[str, object]:
        return {key: json.loads(value) for key, value in self.config}

    def payload(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "kind": self.kind.value,
            "config": self.config_dict(),
        }


@dataclass(frozen=True, slots=True)
class WorkflowEdgeV1:
    source: str
    target: str
    route: str

    @classmethod
    def create(cls, value: Mapping[str, object]) -> "WorkflowEdgeV1":
        if type(value) is not dict or set(value) != {"source", "target", "route"}:
            raise WorkflowGraphContractError("workflow edge is malformed")
        route = _text(value["route"], "route", 32)
        if route not in {"next", "true", "false"}:
            raise WorkflowGraphContractError("workflow edge route is invalid")
        return cls(
            _identifier(value["source"], "edge source"),
            _identifier(value["target"], "edge target"),
            route,
        )

    def payload(self) -> dict[str, str]:
        return {"source": self.source, "target": self.target, "route": self.route}


@dataclass(frozen=True, slots=True)
class WorkflowGraphV1:
    nodes: tuple[WorkflowNodeV1, ...]
    edges: tuple[WorkflowEdgeV1, ...]
    order: tuple[str, ...]
    digest: str

    @classmethod
    def create(
        cls,
        nodes: Sequence[Mapping[str, object]],
        edges: Sequence[Mapping[str, object]],
    ) -> "WorkflowGraphV1":
        if type(nodes) not in {list, tuple} or not 2 <= len(nodes) <= _MAX_NODES:
            raise WorkflowGraphContractError("workflow node count is invalid")
        if type(edges) not in {list, tuple} or not 1 <= len(edges) <= _MAX_EDGES:
            raise WorkflowGraphContractError("workflow edge count is invalid")
        parsed_nodes = tuple(WorkflowNodeV1.create(item) for item in nodes)
        parsed_edges = tuple(WorkflowEdgeV1.create(item) for item in edges)
        by_id = {node.node_id: node for node in parsed_nodes}
        if len(by_id) != len(parsed_nodes):
            raise WorkflowGraphContractError("workflow node IDs are not unique")
        if sum(node.kind is WorkflowNodeKindV1.TRIGGER for node in parsed_nodes) != 1:
            raise WorkflowGraphContractError("workflow requires exactly one trigger")
        if sum(node.kind is WorkflowNodeKindV1.PLAN for node in parsed_nodes) != 1:
            raise WorkflowGraphContractError("workflow V1 requires exactly one plan node")
        if sum(node.kind is WorkflowNodeKindV1.OUTPUT for node in parsed_nodes) != 1:
            raise WorkflowGraphContractError("workflow requires exactly one output")
        if len({(edge.source, edge.target, edge.route) for edge in parsed_edges}) != len(
            parsed_edges
        ):
            raise WorkflowGraphContractError("workflow edges are not unique")
        incoming = {node_id: 0 for node_id in by_id}
        outgoing: dict[str, list[str]] = {node_id: [] for node_id in by_id}
        for edge in parsed_edges:
            if edge.source not in by_id or edge.target not in by_id or edge.source == edge.target:
                raise WorkflowGraphContractError("workflow edge endpoint is invalid")
            outgoing[edge.source].append(edge.target)
            incoming[edge.target] += 1
            if edge.route in {"true", "false"} and by_id[edge.source].kind is not WorkflowNodeKindV1.CONDITION:
                raise WorkflowGraphContractError("branch routes require a condition node")
        trigger = next(node for node in parsed_nodes if node.kind is WorkflowNodeKindV1.TRIGGER)
        output = next(node for node in parsed_nodes if node.kind is WorkflowNodeKindV1.OUTPUT)
        if incoming[trigger.node_id] != 0 or outgoing[output.node_id]:
            raise WorkflowGraphContractError("workflow endpoints are invalid")
        ready = sorted(node_id for node_id, degree in incoming.items() if degree == 0)
        order: list[str] = []
        degrees = dict(incoming)
        while ready:
            node_id = ready.pop(0)
            order.append(node_id)
            for target in sorted(outgoing[node_id]):
                degrees[target] -= 1
                if degrees[target] == 0:
                    ready.append(target)
                    ready.sort()
        if len(order) != len(parsed_nodes):
            raise WorkflowGraphContractError("workflow graph contains a cycle")
        reachable = {trigger.node_id}
        frontier = [trigger.node_id]
        while frontier:
            current = frontier.pop()
            for target in outgoing[current]:
                if target not in reachable:
                    reachable.add(target)
                    frontier.append(target)
        if reachable != set(by_id) or output.node_id not in reachable:
            raise WorkflowGraphContractError("workflow graph is disconnected")
        payload = {
            "nodes": [by_id[node_id].payload() for node_id in sorted(by_id)],
            "edges": [edge.payload() for edge in sorted(parsed_edges, key=lambda item: (item.source, item.target, item.route))],
            "order": order,
        }
        digest = hashlib.sha256(_canonical_json(payload).encode()).hexdigest()
        return cls(parsed_nodes, parsed_edges, tuple(order), digest)

    def payload(self) -> dict[str, object]:
        by_id = {node.node_id: node for node in self.nodes}
        return {
            "nodes": [by_id[node_id].payload() for node_id in sorted(by_id)],
            "edges": [
                edge.payload()
                for edge in sorted(
                    self.edges, key=lambda item: (item.source, item.target, item.route)
                )
            ],
            "order": list(self.order),
            "digest": self.digest,
        }


@dataclass(frozen=True, slots=True)
class WorkflowFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise WorkflowGraphContractError("workflow feature gate is invalid")

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "WorkflowFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True, slots=True)
class WorkflowBindingV1:
    workflow_id: str
    node_id: str
    plan_id: str
    mission_id: str
    rule_id: str | None
    required_postconditions: tuple[str, ...]
    status: str
    verification_digest: str | None


@dataclass(frozen=True, slots=True)
class WorkflowProjectionV1:
    workflow_id: str
    owner_profile_id: str
    workspace_id: str
    name: str
    description: str
    status: WorkflowStatusV1
    revision: int
    graph: WorkflowGraphV1
    binding: WorkflowBindingV1 | None


class WorkflowGraphStoreV1:
    def __init__(self, path: Path | str, gate: WorkflowFeatureGateV1) -> None:
        if type(gate) is not WorkflowFeatureGateV1 or not gate.enabled:
            raise WorkflowGraphDenied("workflow graph feature is disabled")
        self.path = Path(path)
        _private_path(self.path)
        self._lock = threading.RLock()
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflow_meta(
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflows(
                    workflow_id TEXT PRIMARY KEY,
                    owner_profile_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    graph_json TEXT NOT NULL,
                    graph_digest TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_bindings(
                    workflow_id TEXT PRIMARY KEY REFERENCES workflows(workflow_id),
                    node_id TEXT NOT NULL,
                    plan_id TEXT NOT NULL,
                    mission_id TEXT NOT NULL,
                    rule_id TEXT,
                    required_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    verification_digest TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_events(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE,
                    created_at REAL NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS workflow_events_no_update
                BEFORE UPDATE ON workflow_events
                BEGIN
                    SELECT RAISE(ABORT, 'workflow events are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS workflow_events_no_delete
                BEFORE DELETE ON workflow_events
                BEGIN
                    SELECT RAISE(ABORT, 'workflow events are append-only');
                END;
                """
            )
            existing = connection.execute(
                "SELECT value FROM workflow_meta WHERE key='schema_version'"
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO workflow_meta VALUES('schema_version',?)",
                    (str(SCHEMA_VERSION),),
                )
            elif str(existing[0]) != str(SCHEMA_VERSION):
                raise WorkflowGraphDenied("workflow store schema diverged")
            self._verify_events(connection)

    @staticmethod
    def _verify_events(connection: sqlite3.Connection) -> None:
        expected_previous = "0" * 64
        for row in connection.execute(
            "SELECT workflow_id,event_type,payload_json,previous_hash,event_hash,created_at "
            "FROM workflow_events ORDER BY sequence"
        ):
            try:
                payload = json.loads(str(row[2]))
                expected_hash = hashlib.sha256(
                    _canonical_json(
                        {
                            "workflow_id": str(row[0]),
                            "event_type": str(row[1]),
                            "payload": payload,
                            "previous_hash": expected_previous,
                            "created_at": float(row[5]),
                        }
                    ).encode()
                ).hexdigest()
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise WorkflowGraphDenied("workflow event chain diverged") from exc
            if str(row[3]) != expected_previous or str(row[4]) != expected_hash:
                raise WorkflowGraphDenied("workflow event chain diverged")
            expected_previous = expected_hash

    @staticmethod
    def _graph(raw: str, digest: str) -> WorkflowGraphV1:
        payload = json.loads(raw)
        graph = WorkflowGraphV1.create(payload["nodes"], payload["edges"])
        if graph.digest != digest:
            raise WorkflowGraphDenied("workflow graph digest diverged")
        return graph

    @staticmethod
    def _binding(row: sqlite3.Row | None) -> WorkflowBindingV1 | None:
        if row is None:
            return None
        digest = None if row["verification_digest"] is None else str(row["verification_digest"])
        if digest is not None and _SHA256.fullmatch(digest) is None:
            raise WorkflowGraphDenied("workflow verification digest diverged")
        return WorkflowBindingV1(
            str(row["workflow_id"]),
            str(row["node_id"]),
            str(row["plan_id"]),
            str(row["mission_id"]),
            None if row["rule_id"] is None else str(row["rule_id"]),
            tuple(json.loads(str(row["required_json"]))),
            str(row["status"]),
            digest,
        )

    def _event(
        self,
        connection: sqlite3.Connection,
        workflow_id: str,
        event_type: str,
        payload: Mapping[str, object],
    ) -> None:
        self._verify_events(connection)
        previous = connection.execute(
            "SELECT event_hash FROM workflow_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_hash = "0" * 64 if previous is None else str(previous[0])
        payload_json = _canonical_json(dict(payload))
        created_at = time.time()
        event_hash = hashlib.sha256(
            _canonical_json(
                {
                    "workflow_id": workflow_id,
                    "event_type": event_type,
                    "payload": json.loads(payload_json),
                    "previous_hash": previous_hash,
                    "created_at": created_at,
                }
            ).encode()
        ).hexdigest()
        connection.execute(
            "INSERT INTO workflow_events(workflow_id,event_type,payload_json,previous_hash,event_hash,created_at) VALUES(?,?,?,?,?,?)",
            (workflow_id, event_type, payload_json, previous_hash, event_hash, created_at),
        )

    def create(
        self,
        *,
        owner_profile_id: str,
        workspace_id: str,
        name: str,
        description: str,
        nodes: Sequence[Mapping[str, object]],
        edges: Sequence[Mapping[str, object]],
    ) -> WorkflowProjectionV1:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        title = _text(name, "workflow name", 160)
        detail = _text(description, "workflow description", 1000)
        graph = WorkflowGraphV1.create(nodes, edges)
        workflow_id = "workflow_" + uuid.uuid4().hex
        now = time.time()
        graph_json = _canonical_json(
            {"nodes": [node.payload() for node in graph.nodes], "edges": [edge.payload() for edge in graph.edges]}
        )
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO workflows VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    workflow_id,
                    owner,
                    workspace,
                    title,
                    detail,
                    WorkflowStatusV1.DRAFT.value,
                    1,
                    graph_json,
                    graph.digest,
                    now,
                    now,
                ),
            )
            self._event(connection, workflow_id, "workflow.created", {"graph_digest": graph.digest})
            connection.execute("COMMIT")
        return self.get(workflow_id)

    def get(self, workflow_id: str) -> WorkflowProjectionV1:
        key = _identifier(workflow_id, "workflow_id")
        with self._connect() as connection:
            self._verify_events(connection)
            row = connection.execute("SELECT * FROM workflows WHERE workflow_id=?", (key,)).fetchone()
            binding_row = connection.execute(
                "SELECT * FROM workflow_bindings WHERE workflow_id=?", (key,)
            ).fetchone()
        if row is None:
            raise KeyError(key)
        try:
            status = WorkflowStatusV1(str(row["status"]))
        except ValueError as exc:
            raise WorkflowGraphDenied("workflow status diverged") from exc
        return WorkflowProjectionV1(
            key,
            str(row["owner_profile_id"]),
            str(row["workspace_id"]),
            str(row["name"]),
            str(row["description"]),
            status,
            int(row["revision"]),
            self._graph(str(row["graph_json"]), str(row["graph_digest"])),
            self._binding(binding_row),
        )

    def count_scope(self, owner_profile_id: str, workspace_id: str) -> int:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM workflows WHERE owner_profile_id=? AND workspace_id=?",
                (owner, workspace),
            ).fetchone()
        return int(row[0])

    def list_scope(
        self, owner_profile_id: str, workspace_id: str, *, limit: int = 8
    ) -> tuple[WorkflowProjectionV1, ...]:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        if type(limit) is not int or not 1 <= limit <= 32:
            raise WorkflowGraphContractError("workflow list limit is invalid")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT workflow_id FROM workflows WHERE owner_profile_id=? AND workspace_id=? "
                "ORDER BY updated_at DESC,workflow_id LIMIT ?",
                (owner, workspace, limit),
            ).fetchall()
        return tuple(self.get(str(row[0])) for row in rows)

    def bind_plan(
        self,
        workflow_id: str,
        *,
        plan_id: str,
        mission_id: str,
        required_postconditions: Sequence[str],
        rule_id: str | None = None,
    ) -> WorkflowProjectionV1:
        workflow = self.get(workflow_id)
        if workflow.status is not WorkflowStatusV1.DRAFT or workflow.binding is not None:
            raise WorkflowGraphDenied("workflow plan can only bind once while draft")
        plan_node = next(node for node in workflow.graph.nodes if node.kind is WorkflowNodeKindV1.PLAN)
        plan = _identifier(plan_id, "plan_id")
        mission = _identifier(mission_id, "mission_id")
        rule = _identifier(rule_id, "rule_id") if rule_id is not None else None
        if type(required_postconditions) not in {list, tuple} or not required_postconditions:
            raise WorkflowGraphContractError("workflow postconditions are required")
        required = tuple(sorted({_text(item, "postcondition", 160) for item in required_postconditions}))
        if len(required) != len(required_postconditions) or len(required) > 32:
            raise WorkflowGraphContractError("workflow postconditions are invalid")
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE workflows SET revision=revision+1,updated_at=? WHERE workflow_id=? AND status='draft' AND revision=?",
                (now, workflow.workflow_id, workflow.revision),
            ).rowcount
            if changed != 1:
                raise WorkflowGraphDenied("workflow changed during plan binding")
            connection.execute(
                "INSERT INTO workflow_bindings VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    workflow.workflow_id,
                    plan_node.node_id,
                    plan,
                    mission,
                    rule,
                    _canonical_json(required),
                    "bound",
                    None,
                    now,
                    now,
                ),
            )
            self._event(
                connection,
                workflow.workflow_id,
                "workflow.plan_bound",
                {
                    "node_id": plan_node.node_id,
                    "plan_id": plan,
                    "mission_id": mission,
                    "rule_id": rule,
                },
            )
            connection.execute("COMMIT")
        return self.get(workflow.workflow_id)

    def _transition(self, workflow_id: str, target: WorkflowStatusV1) -> WorkflowProjectionV1:
        workflow = self.get(workflow_id)
        allowed = {
            WorkflowStatusV1.DRAFT: {WorkflowStatusV1.ACTIVE, WorkflowStatusV1.CANCELLED},
            WorkflowStatusV1.ACTIVE: {WorkflowStatusV1.PAUSED, WorkflowStatusV1.CANCELLED},
            WorkflowStatusV1.PAUSED: {WorkflowStatusV1.ACTIVE, WorkflowStatusV1.CANCELLED},
        }
        if target not in allowed.get(workflow.status, set()):
            raise WorkflowGraphDenied("workflow transition is not allowed")
        if target is WorkflowStatusV1.ACTIVE and workflow.binding is None:
            raise WorkflowGraphDenied("workflow requires one Phase 6 plan binding")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE workflows SET status=?,revision=revision+1,updated_at=? WHERE workflow_id=? AND status=? AND revision=?",
                (target.value, time.time(), workflow.workflow_id, workflow.status.value, workflow.revision),
            ).rowcount
            if changed != 1:
                raise WorkflowGraphDenied("workflow changed during transition")
            self._event(connection, workflow.workflow_id, f"workflow.{target.value}", {})
            connection.execute("COMMIT")
        return self.get(workflow.workflow_id)

    def activate(self, workflow_id: str) -> WorkflowProjectionV1:
        return self._transition(workflow_id, WorkflowStatusV1.ACTIVE)

    def pause(self, workflow_id: str) -> WorkflowProjectionV1:
        return self._transition(workflow_id, WorkflowStatusV1.PAUSED)

    def cancel(self, workflow_id: str) -> WorkflowProjectionV1:
        return self._transition(workflow_id, WorkflowStatusV1.CANCELLED)

    def reconcile_verified(
        self,
        workflow_id: str,
        *,
        state_store: AgenticStateStoreV6,
        mission_store: MissionStore,
    ) -> WorkflowProjectionV1:
        if type(state_store) is not AgenticStateStoreV6 or type(mission_store) is not MissionStore:
            raise WorkflowGraphContractError("exact Phase 6 stores are required")
        workflow = self.get(workflow_id)
        if workflow.status is WorkflowStatusV1.COMPLETED:
            return workflow
        if workflow.status not in {WorkflowStatusV1.ACTIVE, WorkflowStatusV1.PAUSED} or workflow.binding is None:
            raise WorkflowGraphDenied("workflow is not reconcilable")
        binding = workflow.binding
        try:
            projection = state_store.get_projection(binding.plan_id)
            mission = mission_store.get(binding.mission_id)
            snapshot = mission_store.authority_snapshot(binding.mission_id)
        except (KeyError, MissionError) as exc:
            raise WorkflowGraphDenied("workflow Phase 6 authority is unavailable") from exc
        if (
            projection.state is not PlanStateV1.COMPLETE
            or projection.mission_id != binding.mission_id
            or projection.mission_plan_digest is None
            or mission.state != "succeeded"
            or snapshot.state != "succeeded"
        ):
            raise WorkflowGraphDenied("workflow Phase 6 plan is not independently complete")
        event_hashes = {str(item["event_hash"]) for item in mission_store.events(binding.mission_id)}
        receipts = state_store.plans.receipts(binding.plan_id)
        if not receipts:
            raise WorkflowGraphDenied("workflow verification receipts are unavailable")
        observed: set[str] = set()
        receipt_payloads: list[dict[str, object]] = []
        for receipt in receipts:
            if (
                receipt.status != "verified"
                or receipt.plan_id != binding.plan_id
                or receipt.mission_id != binding.mission_id
                or receipt.authority_snapshot_hash != snapshot.snapshot_hash
                or receipt.event_hash not in event_hashes
            ):
                raise WorkflowGraphDenied("workflow verification receipt diverged")
            observed.update(receipt.postconditions)
            receipt_payloads.append(receipt.payload())
        missing = set(binding.required_postconditions) - observed
        if missing:
            raise WorkflowGraphDenied(
                "workflow lacks verified postconditions: " + ", ".join(sorted(missing))
            )
        digest = hashlib.sha256(
            _canonical_json(
                {
                    "workflow_id": workflow.workflow_id,
                    "graph_digest": workflow.graph.digest,
                    "plan_id": binding.plan_id,
                    "mission_id": binding.mission_id,
                    "mission_plan_digest": projection.mission_plan_digest,
                    "authority_snapshot_hash": snapshot.snapshot_hash,
                    "receipts": receipt_payloads,
                }
            ).encode()
        ).hexdigest()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE workflow_bindings SET status='verified',verification_digest=?,updated_at=? WHERE workflow_id=? AND status='bound'",
                (digest, time.time(), workflow.workflow_id),
            ).rowcount
            if changed != 1:
                raise WorkflowGraphDenied("workflow binding changed during reconciliation")
            changed = connection.execute(
                "UPDATE workflows SET status='completed',revision=revision+1,updated_at=? WHERE workflow_id=? AND status IN ('active','paused') AND revision=?",
                (time.time(), workflow.workflow_id, workflow.revision),
            ).rowcount
            if changed != 1:
                raise WorkflowGraphDenied("workflow changed during reconciliation")
            self._event(connection, workflow.workflow_id, "workflow.completed", {"verification_digest": digest})
            connection.execute("COMMIT")
        return self.get(workflow.workflow_id)


__all__ = [
    "FEATURE_FLAG",
    "WorkflowBindingV1",
    "WorkflowEdgeV1",
    "WorkflowFeatureGateV1",
    "WorkflowGraphContractError",
    "WorkflowGraphDenied",
    "WorkflowGraphError",
    "WorkflowGraphStoreV1",
    "WorkflowGraphV1",
    "WorkflowNodeKindV1",
    "WorkflowNodeV1",
    "WorkflowProjectionV1",
    "WorkflowStatusV1",
]
