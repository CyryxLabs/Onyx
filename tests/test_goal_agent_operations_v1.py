from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path

import pytest

from core.goal_agent_operations_v1 import (
    MAX_DECOMPOSITION_ITEMS,
    DecompositionStateV1,
    DelegationStateV1,
    GoalAgentOperationsContractError,
    GoalAgentOperationsDenied,
    GoalAgentOperationsError,
    GoalAgentOperationsFeatureGateV1,
    GoalAgentOperationsStoreV1,
    GoalAgentRetentionPolicyV1,
    GoalAgentScopeCapabilityV1,
    GoalCompletionEvidenceResolverV1,
    UncertaintyV1,
)
from core.missions import MissionStore
from core.operational_goals_v1 import (
    GoalLevelV1,
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
from core.phase6_agentic_core_v6 import AgenticCoreV6, AgenticFeatureGateV6, AgenticStateStoreV6


KEY = b"goal-agent-operations-test-key-000000000000000000000000"
SCOPE = GoalAgentScopeCapabilityV1("owner_primary", "workspace_personal")


def _goals(tmp_path: Path) -> OperationalGoalStoreV1:
    return OperationalGoalStoreV1(
        tmp_path / "goals.sqlite3", OperationalGoalFeatureGateV1(True)
    )


def _authority(tmp_path: Path) -> tuple[AgenticStateStoreV6, MissionStore]:
    return (
        AgenticStateStoreV6(
            tmp_path / "phase6.sqlite3", AgenticFeatureGateV6(True)
        ),
        MissionStore(tmp_path / "missions.sqlite3"),
    )


def _store(
    tmp_path: Path,
    goals: OperationalGoalStoreV1,
    state: AgenticStateStoreV6,
    missions: MissionStore,
    *,
    path: Path | None = None,
    key: bytes = KEY,
    scope: GoalAgentScopeCapabilityV1 = SCOPE,
    policy: GoalAgentRetentionPolicyV1 | None = None,
) -> GoalAgentOperationsStoreV1:
    return GoalAgentOperationsStoreV1(
        path or tmp_path / "operations.sqlite3",
        GoalAgentOperationsFeatureGateV1(True),
        goals,
        scope,
        GoalCompletionEvidenceResolverV1(state, missions),
        key,
        policy,
    )


def _objective(
    goals: OperationalGoalStoreV1,
    *,
    workspace: str = "workspace_personal",
):
    return goals.create(
        owner_profile_id="owner_primary",
        workspace_id=workspace,
        level=GoalLevelV1.OBJECTIVE,
        title="Deliver verified operations",
        objective="Coordinate bounded work without accepting a claim as evidence",
        definition_of_done=("runtime_status_observed",),
    )


def _role(store: GoalAgentOperationsStoreV1, request: str):
    return store.register_role(
        name="Operations coordinator",
        purpose="Coordinate verified operational work",
        responsibilities=("Review evidence", "Escalate blocked work"),
        request_id=request,
    )


def _proposal() -> dict[str, object]:
    return {
        "version": 1,
        "summary": "Decompose an objective into bounded evidence-gated work",
        "items": [
            {
                "client_id": "node_key_result",
                "parent": "$root",
                "level": "key_result",
                "title": "Produce evidence",
                "objective": "Collect exact evidence for the operational result",
                "definition_of_done": ["runtime_status_observed"],
                "dependencies": [],
                "effort_min_minutes": 30,
                "effort_max_minutes": 90,
                "uncertainty": "medium",
            },
            {
                "client_id": "node_milestone",
                "parent": "node_key_result",
                "level": "milestone",
                "title": "Verify evidence",
                "objective": "Verify the declared evidence condition",
                "definition_of_done": ["runtime_status_observed"],
                "dependencies": [],
                "effort_min_minutes": 15,
                "effort_max_minutes": 45,
                "uncertainty": "low",
            },
        ],
    }


def _verified_runner(_tool: str, _arguments: dict[str, object], _key: str):
    return {
        "status": "succeeded",
        "data": {"runtime": "observed"},
        "evidence": [],
        "postconditions": [{"name": "runtime_status_observed", "satisfied": True}],
        "waiting_for": None,
    }


def _complete_goal(
    tmp_path: Path,
    goals: OperationalGoalStoreV1,
    goal_id: str,
    state: AgenticStateStoreV6,
    missions: MissionStore,
) -> AgenticCoreV6:
    core = AgenticCoreV6(
        state,
        missions,
        WorkspaceScopeV1(
            "workspace_personal", (str(tmp_path.resolve()),), DataClassV1.CONFIDENTIAL
        ),
    )
    request = GoalV1(
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
        request,
        "request:operational-goal:001",
        [{
            "step_id": "step_runtime_status",
            "capability": "local_system_status",
            "arguments": {},
            "dependencies": [],
            "timeout_seconds": 2.0,
            "max_retries": 0,
            "postconditions": ["runtime_status_observed"],
        }],
    )
    admission = core.materialize(projection.plan_id)
    assert admission.mission_id is not None
    set_permission_callback(lambda request: request["digest"])
    try:
        missions.approve(admission.mission_id)
    finally:
        set_permission_callback(None)
    assert core.execute_approved(projection.plan_id, _verified_runner).state == "succeeded"
    goals.bind_plan(goal_id, plan_id=projection.plan_id, mission_id=admission.mission_id)
    goals.reconcile_verified(goal_id, state_store=state, mission_store=missions)
    return core


def test_default_off_constructor_contract_and_instance_scope(tmp_path: Path):
    goals = _goals(tmp_path)
    state, missions = _authority(tmp_path)
    assert not GoalAgentOperationsFeatureGateV1.from_environ({}).enabled
    with pytest.raises(GoalAgentOperationsDenied, match="disabled"):
        GoalAgentOperationsStoreV1(
            tmp_path / "off.sqlite3",
            GoalAgentOperationsFeatureGateV1(False),
            goals,
            SCOPE,
            GoalCompletionEvidenceResolverV1(state, missions),
            KEY,
        )
    store = _store(tmp_path, goals, state, missions)
    assert store.owner_profile_id == "owner_primary"
    assert store.workspace_id == "workspace_personal"
    assert "owner_profile_id" not in inspect.signature(store.register_role).parameters
    assert "workspace_id" not in inspect.signature(store.delegate).parameters
    assert "completion_receipt" not in inspect.signature(
        store.transition_delegation
    ).parameters
    with pytest.raises(GoalAgentOperationsDenied, match="scope capability"):
        _store(
            tmp_path,
            goals,
            state,
            missions,
            scope=GoalAgentScopeCapabilityV1("owner_primary", "workspace_foreign"),
        )


def test_estimation_and_structured_decomposition_are_bounded(tmp_path: Path):
    goals = _goals(tmp_path)
    state, missions = _authority(tmp_path)
    root = _objective(goals)
    dependency = _objective(goals)
    foreign = _objective(goals, workspace="workspace_foreign")
    store = _store(tmp_path, goals, state, missions)
    estimate = store.record_estimate(
        goal_id=root.goal_id,
        effort_min_minutes=60,
        effort_max_minutes=180,
        uncertainty=UncertaintyV1.HIGH,
        dependency_goal_ids=(dependency.goal_id,),
        assumptions=("Dependency remains available",),
    )
    assert not estimate.promise
    assert store.record_estimate(
        goal_id=root.goal_id,
        effort_min_minutes=60,
        effort_max_minutes=180,
        uncertainty=UncertaintyV1.HIGH,
        dependency_goal_ids=(dependency.goal_id,),
        assumptions=("Dependency remains available",),
    ) == estimate
    with pytest.raises(GoalAgentOperationsDenied, match="scope"):
        store.record_estimate(
            goal_id=root.goal_id,
            effort_min_minutes=1,
            effort_max_minutes=2,
            uncertainty=UncertaintyV1.LOW,
            dependency_goal_ids=(foreign.goal_id,),
        )

    record = store.submit_decomposition(
        root_goal_id=root.goal_id,
        request_id="request_decomposition_primary",
        proposal=_proposal(),
    )
    assert record.state is DecompositionStateV1.PROPOSED
    accepted = store.review_decomposition(
        record.decomposition_id,
        decision=DecompositionStateV1.ACCEPTED,
        reason="Owner reviewed structured proposal",
    )
    assert accepted.state is DecompositionStateV1.ACCEPTED
    assert store.decompositions(root_goal_id=root.goal_id, limit=1).items == (
        accepted,
    )
    cycle = _proposal()
    cycle["items"][0]["dependencies"] = ["node_milestone"]  # type: ignore[index]
    cycle["items"][1]["dependencies"] = ["node_key_result"]  # type: ignore[index]
    with pytest.raises(GoalAgentOperationsContractError, match="cycle"):
        store.submit_decomposition(
            root_goal_id=root.goal_id,
            request_id="request_decomposition_cycle",
            proposal=cycle,
        )
    oversized = _proposal()
    oversized["items"] = [
        {**_proposal()["items"][0], "client_id": f"node_{index:02d}"}  # type: ignore[index]
        for index in range(MAX_DECOMPOSITION_ITEMS + 1)
    ]
    with pytest.raises(GoalAgentOperationsContractError, match="bounded plan size"):
        store.submit_decomposition(
            root_goal_id=root.goal_id,
            request_id="request_decomposition_oversized",
            proposal=oversized,
        )


def test_all_entities_have_bounded_pagination_and_quota(tmp_path: Path):
    goals = _goals(tmp_path)
    state, missions = _authority(tmp_path)
    root = _objective(goals)
    policy = GoalAgentRetentionPolicyV1(
        max_roles=3,
        max_estimates=10,
        max_decompositions=10,
        max_cadences=10,
        max_delegations=10,
        max_events=100,
    )
    store = _store(tmp_path, goals, state, missions, policy=policy)
    roles = [_role(store, f"request_role_{index}") for index in range(3)]
    with pytest.raises(GoalAgentOperationsDenied, match="roles retention quota"):
        _role(store, "request_role_over_quota")
    page1 = store.roster(limit=2)
    page2 = store.roster(limit=2, cursor=page1.next_cursor or 0)
    assert page1.items == tuple(roles[:2])
    assert page2.items == (roles[2],)
    cadence = store.configure_cadence(
        goal_id=root.goal_id,
        role_id=roles[1].role_id,
        interval_seconds=3_600,
        next_due_at=100.0,
        enabled=True,
        request_id="request_cadence_primary",
    )
    delegation = store.delegate(
        goal_id=root.goal_id,
        from_role_id=roles[0].role_id,
        to_role_id=roles[1].role_id,
        instruction="Review evidence",
        request_id="request_delegation_primary",
    )
    assert store.cadences(limit=1).items == (cadence,)
    assert store.due_accountability(now=101.0, limit=1).items == (cadence,)
    assert store.delegations(limit=1).items == (delegation,)
    assert store.inbox(to_role_id=roles[1].role_id, limit=1).items == (delegation,)
    assert len(store.events(limit=2).items) == 2
    assert store.events(limit=2).next_cursor is not None


def test_fake_completion_and_caller_receipt_injection_are_impossible(tmp_path: Path):
    goals = _goals(tmp_path)
    state, missions = _authority(tmp_path)
    root = goals.activate(_objective(goals).goal_id)
    store = _store(tmp_path, goals, state, missions)
    role = _role(store, "request_role_target")
    delegation = store.delegate(
        goal_id=root.goal_id,
        from_role_id=None,
        to_role_id=role.role_id,
        instruction="Validate result",
        request_id="request_delegation_fake",
    )
    store.transition_delegation(
        delegation.delegation_id,
        target=DelegationStateV1.ACCEPTED,
        reason="Accepted",
    )
    with pytest.raises(GoalAgentOperationsDenied, match="completed goal evidence"):
        store.transition_delegation(
            delegation.delegation_id,
            target=DelegationStateV1.COMPLETED,
            reason="Model claimed completion",
        )
    with pytest.raises(TypeError, match="completion_receipt"):
        store.transition_delegation(  # type: ignore[call-arg]
            delegation.delegation_id,
            target=DelegationStateV1.COMPLETED,
            reason="Untrusted caller supplied fake data",
            completion_receipt={"evidence_digests": ["0" * 64]},
        )


def test_completion_is_derived_from_exact_phase6_receipt_set(tmp_path: Path):
    goals = _goals(tmp_path)
    state, missions = _authority(tmp_path)
    root = goals.activate(_objective(goals).goal_id)
    store = _store(tmp_path, goals, state, missions)
    role = _role(store, "request_role_target")
    delegation = store.delegate(
        goal_id=root.goal_id,
        from_role_id=None,
        to_role_id=role.role_id,
        instruction="Confirm authoritative evidence",
        request_id="request_delegation_complete",
    )
    store.transition_delegation(
        delegation.delegation_id,
        target=DelegationStateV1.ACCEPTED,
        reason="Accepted",
    )
    core = _complete_goal(tmp_path, goals, root.goal_id, state, missions)
    try:
        completed = store.transition_delegation(
            delegation.delegation_id,
            target=DelegationStateV1.COMPLETED,
            reason="Exact authority reconciled",
        )
        assert completed.state is DelegationStateV1.COMPLETED
        assert completed.completion_digest is not None
        assert store.transition_delegation(
            delegation.delegation_id,
            target=DelegationStateV1.COMPLETED,
            reason="Idempotent authoritative replay",
        ) == completed
        connection = sqlite3.connect(store.path)
        receipt = connection.execute(
            "SELECT completion_receipt_json FROM delegations WHERE delegation_id=?",
            (delegation.delegation_id,),
        ).fetchone()[0]
        connection.close()
        assert "receipt_digests" in receipt
        assert "evidence_digests" not in receipt
    finally:
        core.close()


def _restore_event_triggers(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TRIGGER operation_events_no_update BEFORE UPDATE ON operation_events "
        "BEGIN SELECT RAISE(ABORT,'operation events are immutable'); END"
    )
    connection.execute(
        "CREATE TRIGGER operation_events_no_delete BEFORE DELETE ON operation_events "
        "BEGIN SELECT RAISE(ABORT,'operation events are immutable'); END"
    )


@pytest.mark.parametrize("mode", ["tail", "all", "projection", "head"])
def test_authenticated_head_detects_truncation_and_projection_tamper(
    tmp_path: Path, mode: str
):
    case = tmp_path / mode
    case.mkdir()
    goals = _goals(case)
    state, missions = _authority(case)
    store = _store(case, goals, state, missions)
    role = _role(store, "request_role_primary")
    connection = sqlite3.connect(store.path)
    if mode in {"tail", "all"}:
        connection.execute("DROP TRIGGER operation_events_no_update")
        connection.execute("DROP TRIGGER operation_events_no_delete")
        if mode == "tail":
            connection.execute(
                "DELETE FROM operation_events WHERE seq=(SELECT MAX(seq) FROM operation_events)"
            )
        else:
            connection.execute("DELETE FROM operation_events")
        _restore_event_triggers(connection)
    elif mode == "projection":
        connection.execute(
            "UPDATE roles SET purpose='tampered' WHERE role_id=?", (role.role_id,)
        )
    else:
        connection.execute("UPDATE ledger_state SET event_count=0")
    connection.commit()
    connection.close()
    with pytest.raises(GoalAgentOperationsError):
        if mode == "projection":
            store.get_role(role.role_id)
        else:
            store.events(limit=1)
    with pytest.raises(GoalAgentOperationsError):
        _store(case, goals, state, missions)


def test_wrong_key_scope_retention_and_post_open_tamper_fail_closed(tmp_path: Path):
    goals = _goals(tmp_path)
    state, missions = _authority(tmp_path)
    store = _store(tmp_path, goals, state, missions)
    role = _role(store, "request_role_primary")
    with pytest.raises(GoalAgentOperationsError, match="ledger head"):
        _store(
            tmp_path,
            goals,
            state,
            missions,
            key=b"different-key-000000000000000000000000000000000000",
        )
    with pytest.raises(GoalAgentOperationsDenied, match="retention policy"):
        _store(
            tmp_path,
            goals,
            state,
            missions,
            policy=GoalAgentRetentionPolicyV1(minimum_retention_seconds=63_072_000),
        )
    connection = sqlite3.connect(store.path)
    connection.execute(
        "UPDATE roles SET purpose='post-open tamper' WHERE role_id=?", (role.role_id,)
    )
    connection.commit()
    connection.close()
    with pytest.raises(GoalAgentOperationsError, match="row authentication"):
        store.get_role(role.role_id)


def test_exact_quota_policy_is_bound_across_reopen(tmp_path: Path):
    goals = _goals(tmp_path)
    state, missions = _authority(tmp_path)
    original = GoalAgentRetentionPolicyV1(max_roles=1)
    _store(tmp_path, goals, state, missions, policy=original)
    with pytest.raises(GoalAgentOperationsDenied, match="retention policy"):
        _store(
            tmp_path,
            goals,
            state,
            missions,
            policy=GoalAgentRetentionPolicyV1(max_roles=2),
        )


@pytest.mark.parametrize(
    "field",
    [
        "policy_version",
        "max_roles",
        "max_estimates",
        "max_decompositions",
        "max_cadences",
        "max_delegations",
        "max_events",
        "minimum_retention_seconds",
    ],
)
def test_each_persisted_policy_field_is_hmac_authenticated(
    tmp_path: Path, field: str
):
    case = tmp_path / field
    case.mkdir()
    goals = _goals(case)
    state, missions = _authority(case)
    store = _store(case, goals, state, missions)
    connection = sqlite3.connect(store.path)
    connection.execute(f"UPDATE ledger_state SET {field}={field}+1")
    connection.commit()
    connection.close()
    with pytest.raises(GoalAgentOperationsError, match="ledger head"):
        _store(case, goals, state, missions)


def test_growth_over_400_uses_bounded_pages_without_full_rescan(tmp_path: Path):
    goals = _goals(tmp_path)
    state, missions = _authority(tmp_path)
    root = _objective(goals)
    policy = GoalAgentRetentionPolicyV1(
        max_roles=8,
        max_estimates=500,
        max_decompositions=8,
        max_cadences=8,
        max_delegations=8,
        max_events=600,
    )
    store = _store(tmp_path, goals, state, missions, policy=policy)
    full_verifications = 0

    def forbidden_full_verification(_connection: sqlite3.Connection) -> None:
        nonlocal full_verifications
        full_verifications += 1
        raise AssertionError("per-operation full materialization is forbidden")

    store._verify_state_full = forbidden_full_verification  # type: ignore[method-assign]
    for index in range(450):
        store.record_estimate(
            goal_id=root.goal_id,
            effort_min_minutes=10,
            effort_max_minutes=20,
            uncertainty=UncertaintyV1.MEDIUM,
            assumptions=(f"bounded assumption {index}",),
        )
    assert full_verifications == 0
    first = store.estimates(goal_id=root.goal_id, limit=17)
    second = store.estimates(
        goal_id=root.goal_id, limit=17, cursor=first.next_cursor or 0
    )
    event_page = store.events(limit=19)
    assert len(first.items) == len(second.items) == 17
    assert len(event_page.items) == 19
    assert first.next_cursor is not None and event_page.next_cursor is not None
    assert len(store.events(limit=100).items) == 100
