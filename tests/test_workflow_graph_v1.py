from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.missions import MissionStore
from core.permission_broker import set_permission_callback
from core.phase6_agentic_core_v1 import (
    DataClassV1,
    GoalV1,
    MissionBudgetV1,
    WorkspaceScopeV1,
)
from core.phase6_agentic_core_v6 import (
    AgenticCoreV6,
    AgenticFeatureGateV6,
    AgenticStateStoreV6,
)
from core.workflow_graph_v1 import (
    WorkflowFeatureGateV1,
    WorkflowGraphContractError,
    WorkflowGraphDenied,
    WorkflowGraphStoreV1,
    WorkflowGraphV1,
    WorkflowStatusV1,
)


def _nodes() -> list[dict[str, object]]:
    return [
        {
            "node_id": "trigger_manual",
            "kind": "trigger",
            "config": {"event_type": "owner.manual"},
        },
        {
            "node_id": "condition_ready",
            "kind": "condition",
            "config": {"field": "status", "equals": "ready"},
        },
        {
            "node_id": "plan_execute",
            "kind": "plan",
            "config": {"label": "Approved Phase 6 execution"},
        },
        {
            "node_id": "output_receipt",
            "kind": "output",
            "config": {"label": "Verified receipt"},
        },
    ]


def _edges() -> list[dict[str, str]]:
    return [
        {"source": "trigger_manual", "target": "condition_ready", "route": "next"},
        {"source": "condition_ready", "target": "plan_execute", "route": "true"},
        {"source": "plan_execute", "target": "output_receipt", "route": "next"},
    ]


def _store(tmp_path: Path) -> WorkflowGraphStoreV1:
    return WorkflowGraphStoreV1(
        tmp_path / "workflow-graph.sqlite3", WorkflowFeatureGateV1(True)
    )


def _create(store: WorkflowGraphStoreV1):
    return store.create(
        owner_profile_id="owner_primary",
        workspace_id="workspace_personal",
        name="Daily verified workflow",
        description="Run one approved plan and expose its verified receipt.",
        nodes=_nodes(),
        edges=_edges(),
    )


def _verified_runner(_tool: str, _arguments: dict[str, object], _key: str):
    return {
        "status": "succeeded",
        "data": {"artifact": "observed"},
        "evidence": [],
        "postconditions": [{"name": "workflow_result_verified", "satisfied": True}],
        "waiting_for": None,
    }


def _verified_phase6(tmp_path: Path):
    state = AgenticStateStoreV6(
        tmp_path / "phase6.sqlite3", AgenticFeatureGateV6(True)
    )
    missions = MissionStore(tmp_path / "missions.sqlite3")
    scope = WorkspaceScopeV1(
        "workspace_personal", (str(tmp_path.resolve()),), DataClassV1.CONFIDENTIAL
    )
    core = AgenticCoreV6(state, missions, scope)
    projection = core.submit(
        GoalV1(
            "goal_workflow_run",
            "corr_workflow_run",
            "workspace_personal",
            "Run controlled workflow",
            ("verified result",),
            ("local metadata",),
            ("no direct external execution",),
            DataClassV1.INTERNAL,
            MissionBudgetV1(
                max_steps=2,
                wall_seconds=30.0,
                max_retries_per_step=0,
                max_repair_cycles=1,
                max_compute_seconds=5.0,
            ),
        ),
        "request:workflow:001",
        [
            {
                "step_id": "step_workflow_run",
                "capability": "local_system_status",
                "arguments": {},
                "dependencies": [],
                "timeout_seconds": 2.0,
                "max_retries": 0,
                "postconditions": ["workflow_result_verified"],
            }
        ],
    )
    admission = core.materialize(projection.plan_id)
    assert admission.mission_id is not None
    set_permission_callback(lambda request: request["digest"])
    missions.approve(admission.mission_id)
    set_permission_callback(None)
    assert core.execute_approved(projection.plan_id, _verified_runner).state == "succeeded"
    return core, state, missions, projection.plan_id, admission.mission_id


def test_feature_defaults_off_and_has_no_runtime_worker(tmp_path: Path) -> None:
    assert WorkflowFeatureGateV1.from_environ({}).enabled is False
    with pytest.raises(WorkflowGraphDenied, match="disabled"):
        WorkflowGraphStoreV1(
            tmp_path / "off.sqlite3", WorkflowFeatureGateV1(False)
        )
    source = Path("core/workflow_graph_v1.py").read_text(encoding="utf-8")
    assert "import subprocess" not in source
    assert "import requests" not in source
    assert "import urllib" not in source
    assert "sleep(" not in source


def test_graph_is_deterministic_connected_and_acyclic() -> None:
    first = WorkflowGraphV1.create(_nodes(), _edges())
    second = WorkflowGraphV1.create(list(reversed(_nodes())), list(reversed(_edges())))
    assert first.digest == second.digest
    assert first.order[0] == "trigger_manual"
    cyclic = _edges() + [
        {"source": "output_receipt", "target": "trigger_manual", "route": "next"}
    ]
    with pytest.raises(WorkflowGraphContractError, match="endpoints|cycle"):
        WorkflowGraphV1.create(_nodes(), cyclic)


def test_graph_rejects_arbitrary_code_secrets_and_direct_effect_nodes() -> None:
    nodes = _nodes()
    nodes[2] = {
        "node_id": "plan_execute",
        "kind": "shell",
        "config": {"command": "curl attacker"},
    }
    with pytest.raises(WorkflowGraphContractError, match="kind"):
        WorkflowGraphV1.create(nodes, _edges())
    nodes = _nodes()
    nodes[2] = {
        "node_id": "plan_execute",
        "kind": "plan",
        "config": {"token": "secret-value"},
    }
    with pytest.raises(WorkflowGraphDenied, match="secrets"):
        WorkflowGraphV1.create(nodes, _edges())


def test_create_bind_activate_pause_and_scope_are_durable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    workflow = _create(store)
    assert workflow.status is WorkflowStatusV1.DRAFT
    assert store.count_scope("owner_primary", "workspace_personal") == 1
    assert store.count_scope("owner_other", "workspace_personal") == 0
    assert store.list_scope("owner_primary", "workspace_personal") == (workflow,)
    with pytest.raises(WorkflowGraphDenied, match="requires one Phase 6"):
        store.activate(workflow.workflow_id)
    bound = store.bind_plan(
        workflow.workflow_id,
        plan_id="plan_existing_001",
        mission_id="mission_existing_001",
        required_postconditions=("workflow_result_verified",),
    )
    assert bound.binding is not None
    assert store.activate(workflow.workflow_id).status is WorkflowStatusV1.ACTIVE
    assert store.pause(workflow.workflow_id).status is WorkflowStatusV1.PAUSED
    reopened = WorkflowGraphStoreV1(store.path, WorkflowFeatureGateV1(True))
    assert reopened.get(workflow.workflow_id).status is WorkflowStatusV1.PAUSED


def test_binding_is_immutable_and_model_claim_cannot_complete(tmp_path: Path) -> None:
    store = _store(tmp_path)
    workflow = _create(store)
    store.bind_plan(
        workflow.workflow_id,
        plan_id="plan_missing_001",
        mission_id="mission_missing_001",
        required_postconditions=("workflow_result_verified",),
    )
    store.activate(workflow.workflow_id)
    with pytest.raises(WorkflowGraphDenied, match="only bind once"):
        store.bind_plan(
            workflow.workflow_id,
            plan_id="plan_other_001",
            mission_id="mission_other_001",
            required_postconditions=("workflow_result_verified",),
        )
    empty_state = AgenticStateStoreV6(
        tmp_path / "empty-phase6.sqlite3", AgenticFeatureGateV6(True)
    )
    empty_missions = MissionStore(tmp_path / "empty-missions.sqlite3")
    with pytest.raises(WorkflowGraphDenied, match="authority is unavailable"):
        store.reconcile_verified(
            workflow.workflow_id,
            state_store=empty_state,
            mission_store=empty_missions,
        )
    assert store.get(workflow.workflow_id).status is WorkflowStatusV1.ACTIVE


def test_verified_phase6_receipt_completes_exactly_once(tmp_path: Path) -> None:
    store = _store(tmp_path)
    workflow = _create(store)
    core, state, missions, plan_id, mission_id = _verified_phase6(tmp_path)
    try:
        store.bind_plan(
            workflow.workflow_id,
            plan_id=plan_id,
            mission_id=mission_id,
            required_postconditions=("workflow_result_verified",),
        )
        store.activate(workflow.workflow_id)
        completed = store.reconcile_verified(
            workflow.workflow_id, state_store=state, mission_store=missions
        )
        assert completed.status is WorkflowStatusV1.COMPLETED
        assert completed.binding is not None
        assert completed.binding.status == "verified"
        assert completed.binding.verification_digest is not None
        assert store.reconcile_verified(
            workflow.workflow_id, state_store=state, mission_store=missions
        ) == completed
    finally:
        core.close()


def test_graph_and_status_tamper_fail_closed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    workflow = _create(store)
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE workflows SET status='model_completed',graph_digest=? WHERE workflow_id=?",
            ("0" * 64, workflow.workflow_id),
        )
    with pytest.raises(WorkflowGraphDenied, match="status diverged"):
        store.get(workflow.workflow_id)


def test_workflow_events_are_append_only_and_chain_tamper_fails_closed(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    workflow = _create(store)
    with sqlite3.connect(store.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "UPDATE workflow_events SET payload_json='{}' WHERE sequence=1"
            )
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TRIGGER workflow_events_no_update")
        connection.execute(
            "UPDATE workflow_events SET payload_json='{}' WHERE sequence=1"
        )
    with pytest.raises(WorkflowGraphDenied, match="event chain diverged"):
        store.get(workflow.workflow_id)
