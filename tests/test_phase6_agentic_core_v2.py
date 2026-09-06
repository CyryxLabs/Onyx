from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from core.missions import InvalidTransition, MissionStore
from core.permission_broker import set_permission_callback
from core.phase6_agentic_core_v1 import (
    AdapterStatusV1,
    DataClassV1,
    GoalV1,
    IndependentVerifierV1,
    MissionBudgetV1,
    ModelDescriptorV1,
    ModelRouterV1,
    PlanStateV1,
    PlanningProposalV1,
    WorkspaceScopeV1,
    capability_policy_v1,
)
from core.phase6_agentic_core_v2 import (
    AgenticCoreV2,
    AgenticCoreV2ContractError,
    AgenticCoreV2Denied,
    AgenticCoreV2Error,
    AgenticFeatureGateV2,
    AgenticStateStoreV2,
    ComputeBudgetExhaustedV2,
    PlannerV2,
    artifact_root_v2,
    create_phase6_agentic_core_v2,
)
from scripts.verify_legacy_evidence_retirement_v1 import verify_recorded_manifest


V1_FROZEN = {
    "core/phase6_agentic_core_v1.py": "ab7a6cfec738c31b7beb66ac7a66584f892231ce8a3a2c9e81f30945123cc965",
    "tests/test_phase6_agentic_core_v1.py": "409e9c59b1650f155c3075e176541f438e0cf588f4242dadeb2126b306792b0a",
    "docs/onyx/adrs/ADR-0010-default-off-agentic-core-v1.md": "71c70c591298ba33b7d46ed4c373ee734538ee4161de5fa93fd4f5f175901e07",
    "docs/onyx/checkpoints/phase6-agentic-core-v1/PHASE6_AGENTIC_CORE_V1_CHECKPOINT.md": "b4d0f7faccbd0fc02be7266fdc8d5d82c4227c9649826f49b655544269cb29d7",
    "docs/onyx/checkpoints/phase6-agentic-core-v1/manifest.json": "82eea75a58beec613eba2823d928a76b6d520d9f76b4e4f6b8c811058c77cbd1",
}


@pytest.fixture(autouse=True)
def _reset_permission_callback():
    set_permission_callback(None)
    yield
    set_permission_callback(None)


def _goal(*, compute: float = 5.0, repairs: int = 2) -> GoalV1:
    return GoalV1(
        "goal_phase6_v2",
        "corr_phase6_v2",
        "workspace_personal",
        "Inspect local Onyx runtime status",
        ("runtime status is observed",),
        ("local runtime metadata",),
        ("no external network", "no mutation"),
        DataClassV1.INTERNAL,
        MissionBudgetV1(
            max_steps=5,
            wall_seconds=30.0,
            max_retries_per_step=0,
            max_repair_cycles=repairs,
            max_compute_seconds=compute,
        ),
    )


def _step(step_id: str = "step_status", *, timeout: float = 2.0):
    return {
        "step_id": step_id,
        "capability": "local_system_status",
        "arguments": {},
        "dependencies": [],
        "timeout_seconds": timeout,
        "max_retries": 0,
        "postconditions": ["runtime_status_observed"],
    }


def _core(
    root: Path,
) -> tuple[AgenticCoreV2, AgenticStateStoreV2, MissionStore]:
    state = AgenticStateStoreV2(root / "phase6-v2.sqlite3", AgenticFeatureGateV2(True))
    missions = MissionStore(root / "missions.sqlite3")
    scope = WorkspaceScopeV1(
        "workspace_personal", (str(root.resolve()),), DataClassV1.CONFIDENTIAL
    )
    return AgenticCoreV2(state, missions, scope), state, missions


def _approve(missions: MissionStore, mission_id: str) -> None:
    set_permission_callback(lambda request: request["digest"])
    missions.approve(mission_id)
    set_permission_callback(None)


def _verified_result(label: str):
    return {
        "status": "succeeded",
        "data": {"label": label},
        "evidence": [],
        "postconditions": [{"name": "runtime_status_observed", "satisfied": True}],
        "waiting_for": None,
    }


def test_v1_candidate_bytes_remain_frozen():
    root = Path(__file__).resolve().parents[1]
    observed = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in V1_FROZEN
    }
    assert observed == V1_FROZEN


def test_v2_is_strict_default_off_without_side_effects(tmp_path: Path):
    path = tmp_path / "disabled.sqlite3"
    assert AgenticFeatureGateV2.from_environ({}).enabled is False
    with pytest.raises(AgenticCoreV2Denied):
        create_phase6_agentic_core_v2(
            gate=AgenticFeatureGateV2(False),
            sidecar_path=path,
            mission_store=MissionStore(tmp_path / "missions.sqlite3"),
            workspace_scope=WorkspaceScopeV1(
                "workspace_personal",
                (str(tmp_path.resolve()),),
                DataClassV1.INTERNAL,
            ),
        )
    assert not path.exists()


def test_v2_is_absent_from_live_startup_surfaces():
    root = Path(__file__).resolve().parents[1]
    for relative in ("main.py", "ui.py", "dashboard/server.py"):
        text = (root / relative).read_text(encoding="utf-8")
        assert "phase6_agentic_core_v2" not in text


def test_coordination_schema_tamper_is_rejected_on_reopen(tmp_path: Path):
    _core_instance, state, _missions = _core(tmp_path)
    with sqlite3.connect(state.coordination_path) as connection:
        connection.execute("DROP TRIGGER lineage_no_delete")
    with pytest.raises(AgenticCoreV2Error, match="authority objects"):
        AgenticStateStoreV2(tmp_path / "phase6-v2.sqlite3", AgenticFeatureGateV2(True))


def test_adapter_claim_must_match_independently_captured_descriptor():
    descriptor = ModelDescriptorV1(
        "honest_adapter",
        AdapterStatusV1.AVAILABLE_LOCAL,
        ("structured_plan",),
        DataClassV1.CONFIDENTIAL,
        ("workspace_personal",),
        True,
        False,
        True,
        1000,
        0,
        0,
    )

    class LyingAdapter:
        @property
        def descriptor(self):
            return descriptor

        def propose(self, goal):
            del goal
            return PlanningProposalV1((_step(),), "different_adapter", "prompt_v2")

    with pytest.raises(AgenticCoreV2Denied, match="identity"):
        PlannerV2(ModelRouterV1((descriptor,)), LyingAdapter()).plan(
            _goal(), "request:adapter:mismatch"
        )


def test_adapter_mismatch_is_rejected_before_plan_persistence(tmp_path: Path):
    core, state, _missions = _core(tmp_path)
    descriptor = ModelDescriptorV1(
        "honest_adapter",
        AdapterStatusV1.AVAILABLE_LOCAL,
        ("structured_plan",),
        DataClassV1.CONFIDENTIAL,
        ("workspace_personal",),
        True,
        False,
        True,
        1000,
        0,
        0,
    )

    class LyingAdapter:
        def __init__(self, invoked_descriptor):
            self.descriptor = invoked_descriptor

        def propose(self, goal):
            del goal
            return PlanningProposalV1((_step(),), "different_adapter", "prompt_v2")

    with pytest.raises(AgenticCoreV2Denied):
        core.submit_with_planner(
            _goal(),
            "request:adapter:not-persisted",
            ModelRouterV1((descriptor,)),
            LyingAdapter(descriptor),
        )
    assert state.list_projections() == ()


def test_cross_instance_materialization_barrier_creates_exactly_one_mission(
    tmp_path: Path,
):
    core_a, _state_a, missions_a = _core(tmp_path)
    projection = core_a.submit(_goal(), "request:materialize:race", [_step()])
    core_b, _state_b, _missions_b = _core(tmp_path)
    barrier = threading.Barrier(3)
    results = []
    failures = []

    def invoke(core):
        try:
            barrier.wait(timeout=5)
            results.append(core.materialize(projection.plan_id))
        except BaseException as exc:
            failures.append(exc)

    threads = [
        threading.Thread(target=invoke, args=(core_a,)),
        threading.Thread(target=invoke, args=(core_b,)),
    ]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=10)
    assert failures == []
    assert len(missions_a.list()) == 1
    bound = core_a._state.get_projection(projection.plan_id).mission_id
    assert bound is not None
    assert all(result.mission_id in {None, bound} for result in results)


def test_binding_failure_cancels_and_tombstones_orphan(tmp_path: Path, monkeypatch):
    core, state, missions = _core(tmp_path)
    projection = core.submit(_goal(), "request:orphan:binding", [_step()])

    def fail_binding(*_args, **_kwargs):
        raise RuntimeError("injected binding fault")

    monkeypatch.setattr(state.plans, "bind_mission", fail_binding)
    with pytest.raises(RuntimeError, match="injected binding fault"):
        core.materialize(projection.plan_id)
    created = missions.list()
    assert len(created) == 1
    assert created[0].state == "cancelled"
    assert state.orphan_missions(projection.plan_id) == (created[0].id,)
    assert state.get_projection(projection.plan_id).state is PlanStateV1.BLOCKED
    with pytest.raises(InvalidTransition):
        missions.approve(created[0].id)
    second = core.materialize(projection.plan_id)
    assert second.reason == "orphaned_mission_tombstoned"
    assert len(missions.list()) == 1


def test_expired_reservation_discovers_and_cancels_crash_orphan(tmp_path: Path):
    core, state, missions = _core(tmp_path)
    projection = core.submit(_goal(), "request:orphan:crash", [_step()])
    reservation = state.reserve_materialization(projection.plan_id)
    assert reservation.disposition == "owner"
    plan = state.get_plan(projection.plan_id)
    policy = capability_policy_v1("local_system_status")
    assert policy.mission_tool is not None
    orphan = missions.create(
        core._mission_title(plan),
        [{"tool": policy.mission_tool, "args": {}, "estimated_provider_cost": 0.0}],
        tool_allowlist=[policy.mission_tool],
        max_steps=plan.goal.budget.max_steps,
        max_seconds=plan.goal.budget.wall_seconds,
        max_retries=plan.goal.budget.max_retries_per_step,
        provider_cost_limit=0.0,
    )
    with sqlite3.connect(state.coordination_path) as connection:
        connection.execute(
            "UPDATE materializations SET lease_expires=? WHERE plan_id=?",
            (time.time() - 1.0, projection.plan_id),
        )
    second_core, _second_state, _second_missions = _core(tmp_path)
    result = second_core.materialize(projection.plan_id)
    assert result.reason == "orphaned_mission_tombstoned"
    assert missions.get(orphan.id).state == "cancelled"
    assert state.orphan_missions(projection.plan_id) == (orphan.id,)
    assert len(missions.list()) == 1


def test_total_compute_budget_cancels_late_runner_and_blocks_plan(tmp_path: Path):
    core, state, missions = _core(tmp_path)
    projection = core.submit(
        _goal(compute=0.05), "request:compute:late", [_step(timeout=1.0)]
    )
    admission = core.materialize(projection.plan_id)
    assert admission.mission_id is not None
    _approve(missions, admission.mission_id)
    late_finished = threading.Event()

    def slow(*_args):
        time.sleep(0.15)
        late_finished.set()
        return _verified_result("too-late")

    mission = core.execute_approved(projection.plan_id, slow)
    assert mission.state == "cancelled"
    assert state.get_projection(projection.plan_id).state is PlanStateV1.BLOCKED
    assert state.budget_snapshot(projection.plan_id).exhausted is True
    assert late_finished.wait(1.0)
    assert missions.get(admission.mission_id).state == "cancelled"


def test_compute_budget_is_cumulative_across_steps(tmp_path: Path):
    core, state, missions = _core(tmp_path)
    first = _step("step_one", timeout=1.0)
    second = _step("step_two", timeout=1.0)
    second["dependencies"] = ["step_one"]
    projection = core.submit(
        _goal(compute=0.09), "request:compute:cumulative", [first, second]
    )
    admission = core.materialize(projection.plan_id)
    assert admission.mission_id is not None
    _approve(missions, admission.mission_id)

    def cumulative(*_args):
        time.sleep(0.055)
        return _verified_result("bounded")

    mission = core.execute_approved(projection.plan_id, cumulative)
    assert mission.state == "cancelled"
    snapshot = state.budget_snapshot(projection.plan_id)
    assert snapshot.consumed_seconds >= snapshot.limit_seconds
    assert state.get_projection(projection.plan_id).state is PlanStateV1.BLOCKED


def test_verifier_overrun_cannot_project_plan_complete(tmp_path: Path):
    class SlowVerifier(IndependentVerifierV1):
        def verify(self, *args, **kwargs):
            time.sleep(0.3)
            return super().verify(*args, **kwargs)

    state = AgenticStateStoreV2(
        tmp_path / "phase6-v2.sqlite3", AgenticFeatureGateV2(True)
    )
    missions = MissionStore(tmp_path / "missions.sqlite3")
    scope = WorkspaceScopeV1(
        "workspace_personal", (str(tmp_path.resolve()),), DataClassV1.CONFIDENTIAL
    )
    core = AgenticCoreV2(state, missions, scope, verifier=SlowVerifier())
    projection = core.submit(
        _goal(compute=0.2), "request:compute:verifier", [_step(timeout=1.0)]
    )
    admission = core.materialize(projection.plan_id)
    assert admission.mission_id is not None
    _approve(missions, admission.mission_id)
    mission = core.execute_approved(
        projection.plan_id, lambda *_args: _verified_result("fast-step")
    )
    assert mission.state == "succeeded"
    assert state.budget_snapshot(projection.plan_id).exhausted is True
    assert state.get_projection(projection.plan_id).state is PlanStateV1.BLOCKED


def test_budget_lineage_is_shared_by_repair(tmp_path: Path):
    core, state, _missions = _core(tmp_path)
    projection = core.submit(_goal(compute=0.05), "request:repair:source", [_step()])
    state.plans.set_state(projection.plan_id, PlanStateV1.BLOCKED, "test repair source")
    lease = state.begin_compute(projection.plan_id, "step.synthetic")
    state.finish_compute(lease, elapsed_seconds=0.06)
    with pytest.raises(ComputeBudgetExhaustedV2):
        core.repair(
            projection.plan_id,
            "request:repair:exhausted",
            [_step("step_repair")],
            ["retry required"],
        )


def test_successful_repair_reuses_and_charges_same_compute_account(tmp_path: Path):
    core, state, _missions = _core(tmp_path)
    projection = core.submit(_goal(compute=5.0), "request:repair:shared", [_step()])
    state.plans.set_state(projection.plan_id, PlanStateV1.BLOCKED, "test repair source")
    before = state.budget_snapshot(projection.plan_id)
    repaired = core.repair(
        projection.plan_id,
        "request:repair:shared:v2",
        [_step("step_repair")],
        ["retry required"],
    )
    after_source = state.budget_snapshot(projection.plan_id)
    after_repair = state.budget_snapshot(repaired.plan_id)
    assert after_repair.root_plan_id == before.root_plan_id
    assert after_source.root_plan_id == before.root_plan_id
    assert after_source.consumed_seconds >= before.consumed_seconds
    assert after_repair.consumed_seconds == after_source.consumed_seconds


def test_restart_recovery_charges_expired_compute_lease(tmp_path: Path):
    core, state, _missions = _core(tmp_path)
    projection = core.submit(_goal(compute=0.05), "request:recovery:budget", [_step()])
    state.begin_compute(projection.plan_id, "step.recovery")
    with sqlite3.connect(state.coordination_path) as connection:
        connection.execute(
            "UPDATE budget_accounts SET active_started_wall=?,active_deadline_wall=?",
            (time.time() - 0.1, time.time() - 0.01),
        )
    records = core.recover()
    assert records[0].reason == "BUDGET_EXHAUSTED"
    assert state.budget_snapshot(projection.plan_id).exhausted is True
    assert state.get_projection(projection.plan_id).state is PlanStateV1.BLOCKED


def test_artifact_root_algorithm_is_canonical_and_order_independent():
    values = {
        "z/file.txt": "f" * 64,
        "a/file.txt": "0" * 64,
    }
    expected = hashlib.sha256(
        ("a/file.txt\0" + "0" * 64 + "\n" + "z/file.txt\0" + "f" * 64).encode()
    ).hexdigest()
    assert artifact_root_v2(values) == expected
    assert artifact_root_v2(dict(reversed(tuple(values.items())))) == expected
    with pytest.raises(AgenticCoreV2ContractError):
        artifact_root_v2({"../escape": "0" * 64})


def test_checkpoint_manifest_recomputes_exact_artifact_root():
    root = Path(__file__).resolve().parents[1]
    result = verify_recorded_manifest(
        root,
        "docs/onyx/checkpoints/phase6-agentic-core-v2/manifest.json",
        "c1608dbb7042b1f940422f9ca7c8791eb6935ec15505fe2859c0f756e129dcbc",
        "5d8dd8b9d65f8aae17224b2cbeed74546c3c563eba76a87a9f53ac3ba7104ec4",
        artifact_root_v2,
    )
    assert result["artifacts"] == 6
    assert result["states"]["tests/test_missions.py"] == "superseded-not-rebound"
