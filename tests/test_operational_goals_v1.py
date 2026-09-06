from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from core.missions import MissionStore
from core.operational_goals_v1 import (
    GoalLevelV1,
    GoalStatusV1,
    OperationalGoalContractError,
    OperationalGoalDenied,
    OperationalGoalError,
    OperationalGoalFeatureGateV1,
    OperationalGoalStoreV1,
)
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


def _store(tmp_path: Path) -> OperationalGoalStoreV1:
    return OperationalGoalStoreV1(
        tmp_path / "operational-goals.sqlite3", OperationalGoalFeatureGateV1(True)
    )


def _objective(store: OperationalGoalStoreV1, target_at: float | None = None):
    return store.create(
        owner_profile_id="owner_primary",
        workspace_id="workspace_personal",
        level=GoalLevelV1.OBJECTIVE,
        title="Ship an evidence-backed result",
        objective="Complete the operational result without accepting model prose as proof",
        definition_of_done=("runtime_status_observed",),
        target_at=target_at,
    )


def _verified_runner(_tool: str, _arguments: dict[str, object], _key: str):
    return {
        "status": "succeeded",
        "data": {"runtime": "observed"},
        "evidence": [],
        "postconditions": [
            {"name": "runtime_status_observed", "satisfied": True}
        ],
        "waiting_for": None,
    }


def _verified_phase6(tmp_path: Path):
    state = AgenticStateStoreV6(
        tmp_path / "phase6-plans.sqlite3", AgenticFeatureGateV6(True)
    )
    missions = MissionStore(tmp_path / "missions.sqlite3")
    scope = WorkspaceScopeV1(
        "workspace_personal", (str(tmp_path.resolve()),), DataClassV1.CONFIDENTIAL
    )
    core = AgenticCoreV6(state, missions, scope)
    goal = GoalV1(
        "goal_operational_evidence",
        "corr_operational_evidence",
        "workspace_personal",
        "Inspect local runtime",
        ("runtime observed",),
        ("local metadata",),
        ("no network",),
        DataClassV1.INTERNAL,
        MissionBudgetV1(
            max_steps=2,
            wall_seconds=30.0,
            max_retries_per_step=0,
            max_repair_cycles=1,
            max_compute_seconds=5.0,
        ),
    )
    projection = core.submit(
        goal,
        "request:operational-goal:001",
        [
            {
                "step_id": "step_runtime_status",
                "capability": "local_system_status",
                "arguments": {},
                "dependencies": [],
                "timeout_seconds": 2.0,
                "max_retries": 0,
                "postconditions": ["runtime_status_observed"],
            }
        ],
    )
    admission = core.materialize(projection.plan_id)
    assert admission.mission_id is not None
    set_permission_callback(lambda request: request["digest"])
    missions.approve(admission.mission_id)
    set_permission_callback(None)

    assert (
        core.execute_approved(projection.plan_id, _verified_runner).state
        == "succeeded"
    )
    return core, state, missions, projection.plan_id, admission.mission_id


def test_feature_is_strict_default_off_and_requires_absolute_path(tmp_path: Path):
    assert OperationalGoalFeatureGateV1.from_environ({}).enabled is False
    assert OperationalGoalFeatureGateV1.from_environ(
        {"ONYX_OPERATIONAL_GOALS_V1": "true"}
    ).enabled
    with pytest.raises(OperationalGoalDenied):
        OperationalGoalStoreV1(
            tmp_path / "off.sqlite3", OperationalGoalFeatureGateV1(False)
        )
    with pytest.raises(OperationalGoalContractError):
        OperationalGoalStoreV1(
            Path("relative.sqlite3"), OperationalGoalFeatureGateV1(True)
        )


def test_hierarchy_scope_and_level_are_host_validated(tmp_path: Path):
    store = _store(tmp_path)
    root = _objective(store)
    child = store.create(
        owner_profile_id="owner_primary",
        workspace_id="workspace_personal",
        level=GoalLevelV1.KEY_RESULT,
        title="Produce verified evidence",
        objective="Bind a key result to the exact owner and workspace",
        definition_of_done=("runtime_status_observed",),
        parent_id=root.goal_id,
    )
    assert child.parent_id == root.goal_id
    with pytest.raises(OperationalGoalDenied):
        store.create(
            owner_profile_id="owner_other",
            workspace_id="workspace_personal",
            level=GoalLevelV1.MILESTONE,
            title="Cross owner child",
            objective="This must never cross the owner boundary",
            definition_of_done=("runtime_status_observed",),
            parent_id=child.goal_id,
        )
    with pytest.raises(OperationalGoalContractError):
        store.create(
            owner_profile_id="owner_primary",
            workspace_id="workspace_personal",
            level=GoalLevelV1.TASK,
            title="Invalid root",
            objective="A task cannot be a root operational goal",
            definition_of_done=("runtime_status_observed",),
        )


def test_model_text_or_direct_transition_cannot_complete_goal(tmp_path: Path):
    store = _store(tmp_path)
    goal = store.activate(_objective(store).goal_id)
    assert goal.status is GoalStatusV1.ACTIVE
    with pytest.raises(OperationalGoalDenied, match="Phase 6 evidence"):
        store._owner_transition(
            goal.goal_id,
            GoalStatusV1.COMPLETED,
            "The model said the task was completed successfully",
        )
    with pytest.raises(OperationalGoalDenied, match="no Phase 6 mission binding"):
        store.reconcile_verified(
            goal.goal_id,
            state_store=AgenticStateStoreV6(
                tmp_path / "empty-plans.sqlite3", AgenticFeatureGateV6(True)
            ),
            mission_store=MissionStore(tmp_path / "empty-missions.sqlite3"),
        )


def test_exact_verified_phase6_receipts_complete_goal_idempotently(tmp_path: Path):
    store = _store(tmp_path)
    goal = store.activate(_objective(store).goal_id)
    core, state, missions, plan_id, mission_id = _verified_phase6(tmp_path)
    try:
        bound = store.bind_plan(goal.goal_id, plan_id=plan_id, mission_id=mission_id)
        assert store.bind_plan(
            goal.goal_id, plan_id=plan_id, mission_id=mission_id
        ) == bound
        complete = store.reconcile_verified(
            goal.goal_id, state_store=state, mission_store=missions
        )
        assert complete.status is GoalStatusV1.COMPLETED
        assert complete.verification_digest is not None
        assert len(complete.verification_digest) == 64
        assert (
            store.reconcile_verified(
                goal.goal_id, state_store=state, mission_store=missions
            )
            == complete
        )
        assert store.projection(goal.goal_id).score == 1.0
        assert store.events(goal.goal_id)[-1]["event"] == "goal.completed"
    finally:
        core.close()


def test_missing_verified_postcondition_fails_closed(tmp_path: Path):
    store = _store(tmp_path)
    goal = store.create(
        owner_profile_id="owner_primary",
        workspace_id="workspace_personal",
        level=GoalLevelV1.OBJECTIVE,
        title="Require a stronger result",
        objective="Reject evidence that does not meet the declared definition of done",
        definition_of_done=("different_required_postcondition",),
    )
    store.activate(goal.goal_id)
    core, state, missions, plan_id, mission_id = _verified_phase6(tmp_path)
    try:
        store.bind_plan(goal.goal_id, plan_id=plan_id, mission_id=mission_id)
        with pytest.raises(OperationalGoalDenied, match="lacks verified postconditions"):
            store.reconcile_verified(
                goal.goal_id, state_store=state, mission_store=missions
            )
        assert store.get(goal.goal_id).status is GoalStatusV1.ACTIVE
    finally:
        core.close()


def test_attention_queue_is_read_only_and_reports_overdue(tmp_path: Path):
    store = _store(tmp_path)
    goal = store.activate(_objective(store, target_at=10.0).goal_id)
    before = hashlib.sha256(store.path.read_bytes()).hexdigest()
    queue = store.attention_queue(
        owner_profile_id="owner_primary", workspace_id="workspace_personal", now=20.0
    )
    after = hashlib.sha256(store.path.read_bytes()).hexdigest()
    assert [item.goal.goal_id for item in queue] == [goal.goal_id]
    assert queue[0].health == "overdue"
    assert before == after


def test_event_tamper_and_schema_tamper_fail_closed(tmp_path: Path):
    store = _store(tmp_path)
    goal = _objective(store)
    connection = sqlite3.connect(store.path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE goal_events SET detail_json='{}' WHERE goal_id=?",
                (goal.goal_id,),
            )
        connection.rollback()
    finally:
        connection.close()

    store.path.unlink()
    connection = sqlite3.connect(store.path)
    try:
        connection.execute("CREATE TABLE metadata(schema_version INTEGER NOT NULL)")
        connection.execute("INSERT INTO metadata VALUES(1)")
        connection.execute("PRAGMA user_version=1")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(OperationalGoalError, match="schema authentication"):
        OperationalGoalStoreV1(store.path, OperationalGoalFeatureGateV1(True))
