from __future__ import annotations

import multiprocessing
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from core.missions import MissionError, MissionStore
from core.permission_broker import set_permission_callback
from core.phase6_agentic_core_v1 import (
    DataClassV1,
    DeterministicPlannerAdapterV1,
    GoalV1,
    IndependentVerifierV1,
    MissionBudgetV1,
    ModelRouterV1,
    PlanStateV1,
    WorkspaceScopeV1,
)
from core.phase6_agentic_core_v3 import (
    AgenticCoreV3,
    AgenticCoreV3Denied,
    AgenticCoreV3Error,
    AgenticFeatureGateV3,
    AgenticStateStoreV3,
    ComputeBudgetExhaustedV3,
    artifact_root_v2,
    create_phase6_agentic_core_v3,
)
from scripts.verify_legacy_evidence_retirement_v1 import (
    classify_historical_artifact,
    verify_recorded_manifest,
)


FROZEN = {
    "core/phase6_agentic_core_v1.py": "ab7a6cfec738c31b7beb66ac7a66584f892231ce8a3a2c9e81f30945123cc965",
    "tests/test_phase6_agentic_core_v1.py": "409e9c59b1650f155c3075e176541f438e0cf588f4242dadeb2126b306792b0a",
    "docs/onyx/adrs/ADR-0010-default-off-agentic-core-v1.md": "71c70c591298ba33b7d46ed4c373ee734538ee4161de5fa93fd4f5f175901e07",
    "docs/onyx/checkpoints/phase6-agentic-core-v1/PHASE6_AGENTIC_CORE_V1_CHECKPOINT.md": "b4d0f7faccbd0fc02be7266fdc8d5d82c4227c9649826f49b655544269cb29d7",
    "docs/onyx/checkpoints/phase6-agentic-core-v1/manifest.json": "82eea75a58beec613eba2823d928a76b6d520d9f76b4e4f6b8c811058c77cbd1",
    "core/phase6_agentic_core_v2.py": "da46b34cb77e57586d1d9ed7964ccb426f031f30a05a2e27b528fbaf0ea95120",
    "tests/test_phase6_agentic_core_v2.py": "ae432f6c805efb5bc8c2e6bc482191226fbe1c7e500444a9ec5d97761917dfc9",
    "docs/onyx/adrs/ADR-0011-phase6-agentic-core-v2-coordination-and-compute.md": "c8b3179e82d1d9ce22a8d345e457998f085efcee9e4acc723c7d4e980733cc7d",
    "docs/onyx/checkpoints/phase6-agentic-core-v2/PHASE6_AGENTIC_CORE_V2_CHECKPOINT.md": "f9870daa1be3bd011a1123f8b18c656f54b92cf30306a237ee8b853a4f714ef7",
    "docs/onyx/checkpoints/phase6-agentic-core-v2/manifest.json": "c1608dbb7042b1f940422f9ca7c8791eb6935ec15505fe2859c0f756e129dcbc",
}


@pytest.fixture(autouse=True)
def _reset_permission_callback():
    set_permission_callback(None)
    yield
    set_permission_callback(None)


def _goal(*, compute: float = 5.0, repairs: int = 2) -> GoalV1:
    return GoalV1(
        "goal_phase6_v3",
        "corr_phase6_v3",
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


def _verified(label: str):
    return {
        "status": "succeeded",
        "data": {"label": label},
        "evidence": [],
        "postconditions": [{"name": "runtime_status_observed", "satisfied": True}],
        "waiting_for": None,
    }


def _core(root: Path, *, compute_fence: float = 0.2, verifier=None, critic=None):
    state = AgenticStateStoreV3(
        root / "phase6-v3.sqlite3",
        AgenticFeatureGateV3(True),
        fence_seconds=compute_fence,
    )
    missions = MissionStore(root / "missions.sqlite3")
    scope = WorkspaceScopeV1(
        "workspace_personal", (str(root.resolve()),), DataClassV1.CONFIDENTIAL
    )
    return (
        AgenticCoreV3(state, missions, scope, verifier=verifier, critic=critic),
        state,
        missions,
    )


def _approve(missions: MissionStore, mission_id: str) -> None:
    set_permission_callback(lambda request: request["digest"])
    missions.approve(mission_id)
    set_permission_callback(None)


def _materialize_process(
    root_text: str,
    plan_id: str,
    pause_stage: str | None,
    ready,
    release,
    output,
):
    try:
        root = Path(root_text)
        core, _state, _missions = _core(root, compute_fence=0.1)

        def hook(stage, _claim):
            if stage == pause_stage:
                ready.set()
                if not release.wait(10):
                    raise RuntimeError("test release timeout")

        result = core.materialize(plan_id, stage_hook=hook)
        output.put(("ok", result.reason, result.mission_id))
    except BaseException as exc:
        output.put(("error", type(exc).__name__, str(exc)))


def _force_fence_expired(state: AgenticStateStoreV3, plan_id: str) -> None:
    with sqlite3.connect(state.coordination_path) as connection:
        connection.execute(
            "UPDATE materializations SET lease_expires=? WHERE plan_id=?",
            (time.time() - 1.0, plan_id),
        )


def test_v1_and_v2_reviewed_artifacts_remain_frozen():
    root = Path(__file__).resolve().parents[1]
    states = {
        name: classify_historical_artifact(root, name, digest)["state"]
        for name, digest in FROZEN.items()
    }
    assert states["tests/test_phase6_agentic_core_v2.py"] == (
        "superseded-not-rebound"
    )
    assert set(states.values()) <= {"preserved-exact", "superseded-not-rebound"}


def test_v3_is_strict_default_off_without_side_effects(tmp_path: Path):
    path = tmp_path / "disabled.sqlite3"
    assert AgenticFeatureGateV3.from_environ({}).enabled is False
    with pytest.raises(AgenticCoreV3Denied):
        create_phase6_agentic_core_v3(
            gate=AgenticFeatureGateV3(False),
            sidecar_path=path,
            mission_store=MissionStore(tmp_path / "missions.sqlite3"),
            workspace_scope=WorkspaceScopeV1(
                "workspace_personal",
                (str(tmp_path.resolve()),),
                DataClassV1.INTERNAL,
            ),
        )
    assert not path.exists()


def test_v3_is_absent_from_live_startup_surfaces():
    root = Path(__file__).resolve().parents[1]
    for relative in ("main.py", "ui.py", "dashboard/server.py"):
        assert "phase6_agentic_core_v3" not in (root / relative).read_text(
            encoding="utf-8"
        )


def test_mission_store_idempotent_create_converges_and_rejects_key_reuse(
    tmp_path: Path,
):
    store = MissionStore(tmp_path / "missions.sqlite3")
    spec = [{"tool": "local_system_status", "args": {}}]
    first = store.create_idempotent("plan.materialize.0001", "Exact", spec)
    second = store.create_idempotent("plan.materialize.0001", "Exact", spec)
    assert first.id == second.id
    assert len(store.list()) == 1
    with pytest.raises(MissionError, match="another immutable plan"):
        store.create_idempotent("plan.materialize.0001", "Different", spec)


def test_planner_timeout_exhausts_account_and_does_not_leak_threads(tmp_path: Path):
    core, state, _missions = _core(tmp_path)
    release = threading.Event()
    base = DeterministicPlannerAdapterV1("workspace_personal", [_step()])

    class HungPlanner:
        descriptor = base.descriptor

        def propose(self, goal):
            del goal
            release.wait(5)
            return base.propose(_goal())

    worker_ident = core._executor.worker_ident
    with pytest.raises(ComputeBudgetExhaustedV3):
        core.submit_with_planner(
            _goal(compute=0.05),
            "request:v3:hung:planner",
            ModelRouterV1((base.descriptor,)),
            HungPlanner(),
        )
    assert core._executor.poisoned is True
    assert core._executor.worker_ident == worker_ident
    bounded_threads = [
        thread
        for thread in threading.enumerate()
        if thread.name == "onyx-phase6-v3-bounded-sync"
    ]
    with pytest.raises(AgenticCoreV3Denied, match="executor is unavailable"):
        core.submit(_goal(), "request:v3:hung:planner:second", [_step()])
    assert [
        thread
        for thread in threading.enumerate()
        if thread.name == "onyx-phase6-v3-bounded-sync"
    ] == bounded_threads
    account = state.reserve_request_budget("request:v3:hung:planner", 0.05)
    assert state.compute_snapshot(account).exhausted is True
    assert state.plans.list_projections() == ()
    release.set()
    time.sleep(0.05)
    assert state.plans.list_projections() == ()


def test_planner_exception_is_charged_even_without_plan_persistence(tmp_path: Path):
    core, state, _missions = _core(tmp_path)
    base = DeterministicPlannerAdapterV1("workspace_personal", [_step()])

    class FailingPlanner:
        descriptor = base.descriptor

        def propose(self, goal):
            del goal
            time.sleep(0.02)
            raise RuntimeError("planner fault")

    with pytest.raises(RuntimeError, match="planner fault"):
        core.submit_with_planner(
            _goal(compute=1.0),
            "request:v3:planner:fault",
            ModelRouterV1((base.descriptor,)),
            FailingPlanner(),
        )
    account = state.reserve_request_budget("request:v3:planner:fault", 1.0)
    assert state.compute_snapshot(account).consumed_seconds >= 0.02


def test_hung_runner_is_cancelled_blocked_and_late_result_discarded(tmp_path: Path):
    core, state, missions = _core(tmp_path)
    projection = core.submit(
        _goal(compute=0.08), "request:v3:hung:runner", [_step(timeout=1.0)]
    )
    admission = core.materialize(projection.plan_id)
    assert admission.mission_id is not None
    _approve(missions, admission.mission_id)
    release = threading.Event()
    late = threading.Event()

    def hung(*_args):
        release.wait(5)
        late.set()
        return _verified("late")

    mission = core.execute_approved(projection.plan_id, hung)
    assert mission.state == "cancelled"
    assert state.get_projection(projection.plan_id).state is PlanStateV1.BLOCKED
    assert state.compute_snapshot(projection.plan_id).exhausted is True
    release.set()
    assert late.wait(1)
    assert missions.get(admission.mission_id).state == "cancelled"


def test_hung_critic_is_bounded_and_charged(tmp_path: Path):
    core, state, _missions = _core(tmp_path)
    projection = core.submit(
        _goal(compute=0.08), "request:v3:hung:critic:source", [_step()]
    )
    state.plans.set_state(projection.plan_id, PlanStateV1.BLOCKED, "repair fixture")

    class HungCritic:
        def critique(self, plan, findings):
            del plan, findings
            time.sleep(0.3)
            raise AssertionError("late critic must be discarded")

    core._critic = HungCritic()
    with pytest.raises(ComputeBudgetExhaustedV3):
        core.repair(
            projection.plan_id,
            "request:v3:hung:critic:repair",
            [_step("step_repair")],
            ["repair"],
        )
    assert state.compute_snapshot(projection.plan_id).exhausted is True


def test_hung_repair_planner_is_bounded_and_charged(tmp_path: Path, monkeypatch):
    core, state, _missions = _core(tmp_path)
    projection = core.submit(
        _goal(compute=0.1), "request:v3:hung:repair:source", [_step()]
    )
    state.plans.set_state(projection.plan_id, PlanStateV1.BLOCKED, "repair fixture")

    def hung_plan(*_args, **_kwargs):
        time.sleep(0.3)
        raise AssertionError("late repair planner must be discarded")

    monkeypatch.setattr("core.phase6_agentic_core_v3.PlannerV2.plan", hung_plan)
    with pytest.raises(ComputeBudgetExhaustedV3):
        core.repair(
            projection.plan_id,
            "request:v3:hung:repair:next",
            [_step("step_repair")],
            ["repair"],
        )
    assert state.compute_snapshot(projection.plan_id).exhausted is True


def test_verifier_timeout_never_projects_complete(tmp_path: Path):
    class HungVerifier(IndependentVerifierV1):
        def verify(self, *args, **kwargs):
            del args, kwargs
            time.sleep(0.3)
            raise AssertionError("late verifier must be discarded")

    core, state, missions = _core(tmp_path, verifier=HungVerifier())
    projection = core.submit(_goal(compute=0.15), "request:v3:hung:verifier", [_step()])
    admission = core.materialize(projection.plan_id)
    assert admission.mission_id is not None
    _approve(missions, admission.mission_id)
    mission = core.execute_approved(
        projection.plan_id, lambda *_args: _verified("fast")
    )
    assert mission.state == "succeeded"
    assert state.compute_snapshot(projection.plan_id).exhausted is True
    assert state.get_projection(projection.plan_id).state is PlanStateV1.BLOCKED
    time.sleep(0.2)
    assert state.get_projection(projection.plan_id).state is PlanStateV1.BLOCKED


@pytest.mark.parametrize("pause_stage", ["claimed", "after_create"])
def test_forced_expiry_two_processes_converge_on_exactly_one_mission(
    tmp_path: Path, pause_stage: str
):
    core, state, missions = _core(tmp_path, compute_fence=0.1)
    projection = core.submit(_goal(), f"request:v3:fence:{pause_stage}", [_step()])
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    never_pause = context.Event()
    never_release = context.Event()
    output = context.Queue()
    stale = context.Process(
        target=_materialize_process,
        args=(str(tmp_path), projection.plan_id, pause_stage, ready, release, output),
    )
    stale.start()
    assert ready.wait(10)
    _force_fence_expired(state, projection.plan_id)
    winner = context.Process(
        target=_materialize_process,
        args=(
            str(tmp_path),
            projection.plan_id,
            None,
            never_pause,
            never_release,
            output,
        ),
    )
    winner.start()
    winner.join(15)
    assert winner.exitcode == 0
    release.set()
    stale.join(15)
    assert stale.exitcode == 0
    results = [output.get(timeout=5), output.get(timeout=5)]
    assert all(item[0] == "ok" for item in results), results
    stored = missions.list()
    assert len(stored) == 1
    bound = state.get_projection(projection.plan_id).mission_id
    assert bound == stored[0].id
    assert stored[0].state == "awaiting_approval"
    assert any(item[2] == bound for item in results)
    _approve(missions, bound)
    executed = core.execute_approved(
        projection.plan_id, lambda *_args: _verified("single-winner")
    )
    assert executed.state == "succeeded"
    assert state.get_projection(projection.plan_id).state is PlanStateV1.COMPLETE


def test_recovery_is_indexed_bounded_and_does_not_scan_all_projections(
    tmp_path: Path, monkeypatch
):
    core, state, _missions = _core(tmp_path)
    for index in range(6):
        core.submit(_goal(), f"request:v3:recovery:{index:02d}", [_step()])
    assert len(state.recovery_candidates(limit=2)) == 2
    monkeypatch.setattr(
        state.plans,
        "list_projections",
        lambda: (_ for _ in ()).throw(AssertionError("full scan forbidden")),
    )
    records = core.recover(limit=2)
    assert len(records) == 2


def test_recovery_queries_use_declared_coordination_indexes(tmp_path: Path):
    _core_instance, state, _missions = _core(tmp_path)
    with sqlite3.connect(state.coordination_path) as connection:
        runtime_plan = " ".join(
            str(row[-1])
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT plan_id FROM runtime_plans "
                "WHERE terminal=0 AND recovery_after<=? "
                "ORDER BY recovery_after,plan_id LIMIT ?",
                (time.time(), 10),
            )
        )
        active_plan = " ".join(
            str(row[-1])
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM budget_accounts "
                "WHERE active_token IS NOT NULL "
                "ORDER BY active_deadline_wall,account_id LIMIT ?",
                (10,),
            )
        )
    assert "runtime_recovery_idx" in runtime_plan
    assert "budget_active_idx" in active_plan


def test_coordination_schema_inventory_fails_closed_on_tamper(tmp_path: Path):
    _core_instance, state, _missions = _core(tmp_path)
    with sqlite3.connect(state.coordination_path) as connection:
        connection.execute("DROP INDEX runtime_recovery_idx")
    with pytest.raises(AgenticCoreV3Error, match="schema diverges"):
        AgenticStateStoreV3(state.plans.path, AgenticFeatureGateV3(True))


def test_terminal_coordination_compaction_is_bounded(tmp_path: Path):
    core, state, _missions = _core(tmp_path)
    projection = core.submit(_goal(), "request:v3:compact:01", [_step()])
    state.plans.set_state(projection.plan_id, PlanStateV1.BLOCKED, "terminal fixture")
    state.touch_runtime(projection.plan_id, terminal=True)
    with sqlite3.connect(state.coordination_path) as connection:
        connection.execute(
            "UPDATE runtime_plans SET updated_at=0 WHERE plan_id=?",
            (projection.plan_id,),
        )
        connection.execute("UPDATE budget_accounts SET terminal_at=0")
    result = core.compact(retention_seconds=0, limit=1)
    assert result.plans_deleted == 1
    assert result.accounts_deleted == 1
    assert state.recovery_candidates(limit=10) == ()


def test_checkpoint_manifest_recomputes_artifact_root():
    root = Path(__file__).resolve().parents[1]
    result = verify_recorded_manifest(
        root,
        "docs/onyx/checkpoints/phase6-agentic-core-v3/manifest.json",
        "3d77e96c6561445adb8b2cdb61e400d4ba896d6556ed0c357bb270c501d98288",
        "9f0f710373441a86d6d77bf908cfc7cf81b7f06faab9b293dcba5d23dd33bf27",
        artifact_root_v2,
    )
    assert result["artifacts"] == 6
    assert result["states"]["core/missions.py"] == "superseded-not-rebound"
