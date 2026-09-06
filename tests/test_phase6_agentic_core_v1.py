from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from core.missions import MissionStore
from core.permission_broker import set_permission_callback
from core.phase6_agentic_core_v1 import (
    AdapterStatusV1,
    AgenticCoreV1,
    AgenticCoreV1ContractError,
    AgenticCoreV1Denied,
    AgenticCoreV1Error,
    AgenticCoreV1Unavailable,
    AgenticFeatureGateV1,
    AgenticStateStoreV1,
    BoundedCriticV1,
    DataClassV1,
    DeclarationOnlyPlannerAdapterV1,
    DisabledExternalAgentAdapterV1,
    ExternalAgentBudgetV1,
    ExternalAgentRequestV1,
    GoalV1,
    MissionBudgetV1,
    ModelDescriptorV1,
    ModelRouterV1,
    PlanStateV1,
    RiskLevelV1,
    RouteRequestV1,
    StepV1,
    WorkspaceScopeV1,
    capability_policy_v1,
    create_phase6_agentic_core_v1,
)


@pytest.fixture(autouse=True)
def _reset_permission_callback():
    set_permission_callback(None)
    yield
    set_permission_callback(None)


def _goal(*, repairs: int = 2, seconds: float = 60.0) -> GoalV1:
    return GoalV1(
        "goal_daily_status",
        "corr_daily_status",
        "workspace_personal",
        "Inspect local Onyx runtime status",
        ("runtime status is observed",),
        ("local runtime metadata",),
        ("no external network", "no mutation"),
        DataClassV1.INTERNAL,
        MissionBudgetV1(
            max_steps=5,
            wall_seconds=seconds,
            max_retries_per_step=1,
            max_repair_cycles=repairs,
            max_compute_seconds=seconds,
        ),
    )


def _status_step(**overrides):
    value = {
        "step_id": "step_status",
        "capability": "local_system_status",
        "arguments": {},
        "dependencies": [],
        "timeout_seconds": 5.0,
        "max_retries": 1,
        "postconditions": ["runtime_status_observed"],
    }
    value.update(overrides)
    return value


def _core(tmp_path: Path) -> tuple[AgenticCoreV1, AgenticStateStoreV1, MissionStore]:
    state = AgenticStateStoreV1(
        tmp_path / "phase6.sqlite3", AgenticFeatureGateV1(True)
    )
    missions = MissionStore(tmp_path / "missions.sqlite3")
    scope = WorkspaceScopeV1(
        "workspace_personal", (str(tmp_path.resolve()),), DataClassV1.CONFIDENTIAL
    )
    return AgenticCoreV1(state, missions, scope), state, missions


def _submit(core: AgenticCoreV1, key: str = "request:daily:0001"):
    return core.submit(_goal(), key, [_status_step()])


def _approve(missions: MissionStore, mission_id: str) -> None:
    set_permission_callback(lambda request: request["digest"])
    missions.approve(mission_id)


def test_default_off_gate_creates_no_sidecar(tmp_path: Path):
    path = tmp_path / "disabled.sqlite3"
    missions = MissionStore(tmp_path / "missions.sqlite3")
    with pytest.raises(AgenticCoreV1Denied):
        create_phase6_agentic_core_v1(
            gate=AgenticFeatureGateV1(False),
            sidecar_path=path,
            mission_store=missions,
            workspace_scope=WorkspaceScopeV1(
                "workspace_personal",
                (str(tmp_path.resolve()),),
                DataClassV1.CONFIDENTIAL,
            ),
        )
    assert not path.exists()
    assert AgenticFeatureGateV1.from_environ({}).enabled is False
    assert AgenticFeatureGateV1.from_environ(
        {"ONYX_PHASE6_AGENTIC_CORE_V1": "1"}
    ).enabled is False
    assert AgenticFeatureGateV1.from_environ(
        {"ONYX_PHASE6_AGENTIC_CORE_V1": "true"}
    ).enabled is True


def test_goal_and_budget_are_strict_provider_free():
    with pytest.raises(AgenticCoreV1ContractError):
        MissionBudgetV1(max_api_calls=1)
    with pytest.raises(AgenticCoreV1ContractError):
        MissionBudgetV1(max_cost_micro=1)
    with pytest.raises(AgenticCoreV1ContractError):
        GoalV1(
            "Goal",
            "corr_ok",
            "workspace_personal",
            "x",
            ("done",),
            ("scope",),
            ("none",),
            DataClassV1.INTERNAL,
            MissionBudgetV1(),
        )


def test_unknown_or_consequential_capability_is_denied():
    for name in ("send_message", "deploy", "browser_control"):
        with pytest.raises(AgenticCoreV1Denied):
            capability_policy_v1(name)
    assert capability_policy_v1("local_system_status").provider_free is True
    assert capability_policy_v1("local_catalog_read").executor == "phase5"


def test_model_risk_labels_cannot_override_host_policy(tmp_path: Path):
    core, _, _ = _core(tmp_path)
    projection = core.submit(
        _goal(),
        "request:risk:0001",
        [
            _status_step(
                risk="critical",
                effect="external_mutation",
                approval_required=True,
            )
        ],
    )
    assert projection.state is PlanStateV1.PLANNED


def test_dag_cycle_and_unknown_dependency_are_rejected(tmp_path: Path):
    core, _, _ = _core(tmp_path)
    with pytest.raises(AgenticCoreV1ContractError, match="cycle"):
        core.submit(
            _goal(),
            "request:cycle:0001",
            [
                _status_step(step_id="step_a", dependencies=["step_b"]),
                _status_step(step_id="step_b", dependencies=["step_a"]),
            ],
        )
    with pytest.raises(AgenticCoreV1ContractError, match="unknown dependency"):
        core.submit(
            _goal(),
            "request:dependency:0001",
            [_status_step(dependencies=["step_missing"])],
        )


def test_plan_idempotency_replays_and_drift_denies(tmp_path: Path):
    core, state, _ = _core(tmp_path)
    first = _submit(core)
    second = _submit(core)
    assert first == second
    with pytest.raises(AgenticCoreV1Denied, match="already bound"):
        core.submit(
            _goal(),
            "request:daily:0001",
            [_status_step(timeout_seconds=4.0)],
        )
    events = state.events(first.plan_id)
    assert [item["event"] for item in events] == ["plan.created"]


def test_local_catalog_is_plannable_but_waits_for_phase5(tmp_path: Path):
    core, state, _ = _core(tmp_path)
    projection = core.submit(
        _goal(),
        "request:catalog:0001",
        [
            {
                "step_id": "step_catalog",
                "capability": "local_catalog_read",
                "arguments": {"page_size": 10},
                "dependencies": [],
                "timeout_seconds": 5.0,
                "max_retries": 1,
                "postconditions": ["catalog_page_observed"],
            }
        ],
    )
    result = core.materialize(projection.plan_id)
    assert result.state is PlanStateV1.WAITING_FOR_PHASE5
    assert result.mission_id is None
    assert state.get_projection(projection.plan_id).state is PlanStateV1.WAITING_FOR_PHASE5


def test_materialization_delegates_to_single_mission_store_and_is_idempotent(tmp_path: Path):
    core, state, missions = _core(tmp_path)
    projection = _submit(core)
    admitted = core.materialize(projection.plan_id)
    assert admitted.state is PlanStateV1.AWAITING_APPROVAL
    assert admitted.mission_id is not None
    assert missions.get(admitted.mission_id).state == "awaiting_approval"
    replay = core.materialize(projection.plan_id)
    assert replay.mission_id == admitted.mission_id
    assert len(missions.list()) == 1
    assert state.get_projection(projection.plan_id).mission_plan_digest == missions.plan_summary(
        admitted.mission_id
    )["plan_digest"]


def test_execute_does_not_open_approval_and_then_verifies_evidence(tmp_path: Path):
    core, state, missions = _core(tmp_path)
    projection = _submit(core)
    admitted = core.materialize(projection.plan_id)
    assert admitted.mission_id
    prompts = []
    set_permission_callback(lambda request: prompts.append(request) or request["digest"])
    still_waiting = core.execute_approved(projection.plan_id)
    assert still_waiting.state == "awaiting_approval"
    assert prompts == []
    missions.approve(admitted.mission_id)
    assert len(prompts) == 1
    result = core.execute_approved(projection.plan_id)
    assert result.state == "succeeded"
    assert state.get_projection(projection.plan_id).state is PlanStateV1.COMPLETE
    receipts = state.receipts(projection.plan_id)
    assert len(receipts) == 1
    assert receipts[0].status == "verified"
    assert receipts[0].postconditions == ("runtime_status_observed",)


def test_dispatch_binding_rejects_wrong_runner_tool_or_args(tmp_path: Path):
    core, state, missions = _core(tmp_path)
    projection = _submit(core)
    admitted = core.materialize(projection.plan_id)
    assert admitted.mission_id
    _approve(missions, admitted.mission_id)

    def runner(tool, arguments, key):
        arguments["injected"] = True
        return {
            "status": "succeeded",
            "data": {},
            "evidence": [],
            "postconditions": [
                {"name": "runtime_status_observed", "satisfied": True}
            ],
            "waiting_for": None,
        }

    result = core.execute_approved(projection.plan_id, runner)
    assert result.state == "failed"
    assert state.get_projection(projection.plan_id).state is PlanStateV1.FAILED


def test_step_timeout_is_enforced_as_verified_failure(tmp_path: Path):
    core, state, missions = _core(tmp_path)
    projection = core.submit(
        _goal(seconds=1.0),
        "request:timeout:0001",
        [_status_step(timeout_seconds=0.01, max_retries=0)],
    )
    admitted = core.materialize(projection.plan_id)
    assert admitted.mission_id
    _approve(missions, admitted.mission_id)

    def slow_runner(tool, arguments, key):
        del tool, arguments, key
        time.sleep(0.02)
        return {
            "status": "succeeded",
            "data": {},
            "evidence": [],
            "postconditions": [
                {"name": "runtime_status_observed", "satisfied": True}
            ],
            "waiting_for": None,
        }

    result = core.execute_approved(projection.plan_id, slow_runner)
    assert result.state == "failed"
    assert state.get_projection(projection.plan_id).state is PlanStateV1.FAILED


def test_independent_verifier_rejects_wrong_postcondition(tmp_path: Path):
    core, state, missions = _core(tmp_path)
    projection = core.submit(
        _goal(),
        "request:verify:0001",
        [_status_step(postconditions=["expected_other_condition"])],
    )
    admitted = core.materialize(projection.plan_id)
    assert admitted.mission_id
    _approve(missions, admitted.mission_id)
    result = core.execute_approved(projection.plan_id)
    assert result.state == "succeeded"
    assert state.get_projection(projection.plan_id).state is PlanStateV1.BLOCKED
    report = core.verify(projection.plan_id)
    assert report.status == "rejected"
    assert "postconditions_mismatch:step_status" in report.findings


def test_kill_latch_cancels_bound_work_and_survives_restart(tmp_path: Path):
    core, state, missions = _core(tmp_path)
    projection = _submit(core)
    admitted = core.materialize(projection.plan_id)
    assert admitted.mission_id
    _approve(missions, admitted.mission_id)
    killed = core.kill("owner emergency stop")
    assert killed[0].state is PlanStateV1.CANCELLED
    assert missions.get(admitted.mission_id).state == "cancelled"
    reopened_state = AgenticStateStoreV1(
        state.path, AgenticFeatureGateV1(True)
    )
    reopened = AgenticCoreV1(
        reopened_state,
        MissionStore(tmp_path / "missions.sqlite3"),
        WorkspaceScopeV1(
            "workspace_personal", (str(tmp_path.resolve()),), DataClassV1.CONFIDENTIAL
        ),
    )
    assert reopened.kill_latched is True
    assert reopened.recover()[0].state is PlanStateV1.CANCELLED
    with pytest.raises(AgenticCoreV1Denied, match="kill switch"):
        _submit(reopened, "request:daily:0002")


def test_cancel_discards_late_result_via_mission_store(tmp_path: Path):
    core, state, missions = _core(tmp_path)
    projection = _submit(core)
    admitted = core.materialize(projection.plan_id)
    assert admitted.mission_id
    _approve(missions, admitted.mission_id)
    started = threading.Event()
    release = threading.Event()

    def runner(tool, arguments, key):
        del tool, arguments, key
        started.set()
        release.wait(2)
        return {
            "status": "succeeded",
            "data": {},
            "evidence": [],
            "postconditions": [
                {"name": "runtime_status_observed", "satisfied": True}
            ],
            "waiting_for": None,
        }

    thread = threading.Thread(
        target=lambda: core.execute_approved(projection.plan_id, runner), daemon=True
    )
    thread.start()
    assert started.wait(2)
    cancel_thread = threading.Thread(target=lambda: core.cancel(projection.plan_id))
    cancel_thread.start()
    cancel_thread.join(2)
    assert not cancel_thread.is_alive()
    release.set()
    thread.join(2)
    assert missions.get(admitted.mission_id).state == "cancelled"
    assert state.get_projection(projection.plan_id).state is PlanStateV1.CANCELLED


def test_recovery_never_auto_executes(tmp_path: Path):
    core, state, missions = _core(tmp_path)
    projection = _submit(core)
    admitted = core.materialize(projection.plan_id)
    assert admitted.mission_id
    _approve(missions, admitted.mission_id)
    before = missions.events(admitted.mission_id)
    reopened = AgenticCoreV1(
        AgenticStateStoreV1(state.path, AgenticFeatureGateV1(True)),
        MissionStore(tmp_path / "missions.sqlite3"),
        WorkspaceScopeV1(
            "workspace_personal", (str(tmp_path.resolve()),), DataClassV1.CONFIDENTIAL
        ),
    )
    recovered = reopened.recover()
    after = missions.events(admitted.mission_id)
    assert recovered[0].state is PlanStateV1.RUNNING
    assert before == after


def test_missing_bound_mission_fails_closed_on_recovery(tmp_path: Path):
    core, state, _ = _core(tmp_path)
    projection = _submit(core)
    admitted = core.materialize(projection.plan_id)
    assert admitted.mission_id
    missing = AgenticCoreV1(
        AgenticStateStoreV1(state.path, AgenticFeatureGateV1(True)),
        MissionStore(tmp_path / "different-missions.sqlite3"),
        WorkspaceScopeV1(
            "workspace_personal", (str(tmp_path.resolve()),), DataClassV1.CONFIDENTIAL
        ),
    )
    record = missing.recover()[0]
    assert record.state is PlanStateV1.BLOCKED
    assert record.reason == "mission_binding_missing"


def test_plan_and_event_tamper_are_detected(tmp_path: Path):
    core, state, _ = _core(tmp_path)
    projection = _submit(core)
    with sqlite3.connect(state.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE plans SET plan_json=? WHERE plan_id=?",
                (json.dumps({"schema": "OnyxAgenticPlan.v1"}), projection.plan_id),
            )
        connection.execute("DROP TRIGGER plans_core_no_update")
        connection.execute(
            "UPDATE plans SET plan_json=? WHERE plan_id=?",
            (json.dumps({"schema": "OnyxAgenticPlan.v1"}), projection.plan_id),
        )
    with pytest.raises(AgenticCoreV1ContractError):
        state.get_plan(projection.plan_id)

    core2, state2, _ = _core(tmp_path / "event")
    projection2 = _submit(core2, "request:event:0001")
    with sqlite3.connect(state2.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE events SET event='tampered'")
    assert state2.events(projection2.plan_id)[0]["event"] == "plan.created"


def test_workspace_scope_is_bound_before_plan_persistence(tmp_path: Path):
    core, state, _ = _core(tmp_path)
    with pytest.raises(AgenticCoreV1Denied, match="workspace scope"):
        core.submit(
            _goal(),
            "request:root:outside",
            [
                {
                    "step_id": "step_inventory",
                    "capability": "workspace_inventory",
                    "arguments": {"root": str((tmp_path / "outside").resolve())},
                    "dependencies": [],
                    "timeout_seconds": 1.0,
                    "max_retries": 0,
                    "postconditions": ["inventory_completed"],
                }
            ],
        )
    assert state.list_projections() == ()


def test_kill_latch_cannot_be_reset_in_sidecar(tmp_path: Path):
    _, state, _ = _core(tmp_path)
    assert state.latch_kill() is True
    assert state.latch_kill() is False
    with sqlite3.connect(state.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="cannot be reset"):
            connection.execute("UPDATE metadata SET kill_latched=0")
    assert state.kill_latched is True


def test_sensitive_arguments_are_rejected_before_persistence(tmp_path: Path):
    core, state, _ = _core(tmp_path)
    with pytest.raises(AgenticCoreV1ContractError, match="sensitive"):
        core.submit(
            _goal(),
            "request:sensitive:0001",
            [_status_step(arguments={"token": "should-not-be-stored"})],
        )
    assert state.list_projections() == ()


def test_projection_tamper_diverges_from_append_only_evidence(tmp_path: Path):
    core, state, _ = _core(tmp_path)
    projection = _submit(core)
    with sqlite3.connect(state.path) as connection:
        connection.execute(
            "UPDATE plans SET state=? WHERE plan_id=?",
            (PlanStateV1.COMPLETE.value, projection.plan_id),
        )
    with pytest.raises(AgenticCoreV1Error, match="projection diverges"):
        state.get_projection(projection.plan_id)


def test_completed_plan_remains_complete_after_restart_recovery(tmp_path: Path):
    core, state, missions = _core(tmp_path)
    projection = _submit(core)
    admitted = core.materialize(projection.plan_id)
    assert admitted.mission_id
    _approve(missions, admitted.mission_id)
    assert core.execute_approved(projection.plan_id).state == "succeeded"
    reopened = AgenticCoreV1(
        AgenticStateStoreV1(state.path, AgenticFeatureGateV1(True)),
        MissionStore(tmp_path / "missions.sqlite3"),
        WorkspaceScopeV1(
            "workspace_personal", (str(tmp_path.resolve()),), DataClassV1.CONFIDENTIAL
        ),
    )
    record = reopened.recover()[0]
    assert record.state is PlanStateV1.COMPLETE


def test_model_router_hard_privacy_filters_override_cost_and_quality():
    local = ModelDescriptorV1(
        "local_private",
        AdapterStatusV1.AVAILABLE_LOCAL,
        ("structured_plan",),
        DataClassV1.CONFIDENTIAL,
        ("workspace_personal",),
        True,
        False,
        True,
        910,
        50,
        0,
    )
    remote = ModelDescriptorV1(
        "remote_cheaper",
        AdapterStatusV1.AVAILABLE_LOCAL,
        ("structured_plan",),
        DataClassV1.RESTRICTED,
        ("workspace_personal",),
        False,
        True,
        True,
        1_000,
        1,
        0,
    )
    decision = ModelRouterV1((remote, local)).route(
        RouteRequestV1(
            "workspace_personal",
            DataClassV1.CONFIDENTIAL,
            "structured_plan",
            True,
            True,
            1_000,
            0,
            900,
        )
    )
    assert decision.adapter_id == "local_private"
    blocked = ModelRouterV1((remote,)).route(
        RouteRequestV1(
            "workspace_personal",
            DataClassV1.CONFIDENTIAL,
            "structured_plan",
            True,
            True,
            1_000,
            0,
            900,
        )
    )
    assert blocked.status == "blocked"


def test_declaration_only_model_never_invokes():
    descriptor = ModelDescriptorV1(
        "future_provider",
        AdapterStatusV1.DECLARED_DISABLED,
        ("structured_plan",),
        DataClassV1.PUBLIC,
        ("workspace_personal",),
        False,
        True,
        True,
        0,
        0,
        0,
    )
    adapter = DeclarationOnlyPlannerAdapterV1(descriptor)
    with pytest.raises(AgenticCoreV1Unavailable):
        adapter.propose(_goal())


def test_bounded_critic_stops_at_repair_budget(tmp_path: Path):
    core, state, _ = _core(tmp_path)
    projection = _submit(core)
    plan = state.get_plan(projection.plan_id)
    critique = BoundedCriticV1().critique(plan, ["verification failed"])
    assert critique.repair_allowed is True
    zero_goal = _goal(repairs=0)
    zero_projection = core.submit(
        zero_goal, "request:repair:zero", [_status_step()]
    )
    zero_plan = state.get_plan(zero_projection.plan_id)
    assert BoundedCriticV1().critique(zero_plan, ["failed"]).repair_allowed is False


def test_external_agent_contract_is_repo_scoped_and_truthfully_blocked(tmp_path: Path):
    request = ExternalAgentRequestV1(
        "external_request",
        "workspace_personal",
        str(tmp_path.resolve()),
        "Inspect and test the repository",
        ("core", "tests"),
        (
            "deploy_production",
            "merge_protected_branch",
            "delete_repository",
            "rotate_credentials",
            "incur_spend",
        ),
        ExternalAgentBudgetV1(600, 2, 0, 0),
        "kill_external_request",
        ("diff", "tests", "artifacts"),
    )
    adapter = DisabledExternalAgentAdapterV1()
    status = adapter.start(request)
    assert status.status is AdapterStatusV1.BLOCKED_BY_ACCESS
    assert status.provider_session_id is None
    with pytest.raises(AgenticCoreV1ContractError):
        ExternalAgentRequestV1(
            "external_request",
            "workspace_personal",
            "relative/repo",
            "x",
            ("core",),
            request.forbidden_actions,
            request.budget,
            request.kill_token_id,
            request.evidence_requirements,
        )


def test_step_contract_rejects_policy_label_drift():
    with pytest.raises(AgenticCoreV1Denied, match="risk or effect"):
        StepV1(
            "step_status",
            "local_system_status",
            "read",
            "{}",
            (),
            "provider_free_research",
            RiskLevelV1.HIGH,
            capability_policy_v1("local_system_status").effect,
            False,
            1.0,
            0,
            ("runtime_status_observed",),
        )
