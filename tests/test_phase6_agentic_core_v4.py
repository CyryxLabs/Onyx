from __future__ import annotations

import gc
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
    MissionBudgetV1,
    ModelRouterV1,
    PlanStateV1,
    WorkspaceScopeV1,
)
from core.phase6_agentic_core_v2 import PlannerV2, artifact_root_v2
from core.phase6_agentic_core_v4 import (
    AgenticCoreV4,
    AgenticCoreV4ContractError,
    AgenticCoreV4Denied,
    AgenticCoreV4Error,
    AgenticFeatureGateV4,
    AgenticStateStoreV4,
    ComputeBudgetExhaustedV4,
    ProcessCallTimeoutV4,
    StrictMissionMaterializerV4,
    TerminableProcessExecutorV4,
)
from scripts.verify_legacy_evidence_retirement_v1 import (
    classify_historical_artifact,
    verify_recorded_manifest,
)


FROZEN = {
    "core/phase6_agentic_core_v1.py": "ab7a6cfec738c31b7beb66ac7a66584f892231ce8a3a2c9e81f30945123cc965",
    "tests/test_phase6_agentic_core_v1.py": "409e9c59b1650f155c3075e176541f438e0cf588f4242dadeb2126b306792b0a",
    "core/phase6_agentic_core_v2.py": "da46b34cb77e57586d1d9ed7964ccb426f031f30a05a2e27b528fbaf0ea95120",
    "tests/test_phase6_agentic_core_v2.py": "ae432f6c805efb5bc8c2e6bc482191226fbe1c7e500444a9ec5d97761917dfc9",
    "core/phase6_agentic_core_v3.py": "406215c8031d48aba5fb189a8f14160e539391f9c48a3b9ba24a00d4f9d89484",
    "tests/test_phase6_agentic_core_v3.py": "8329b1e7cc1be66d34555d5c5f08c9c2a3fcb13a91bc7ddfa635ccfa303ff14b",
    "core/missions.py": "fe2074eb132c09beecb9f13c5151659e745cf888676c4244c037e0a7ed7f2fe5",
    "docs/onyx/adrs/ADR-0012-phase6-agentic-core-v3-bounded-execution-and-fencing.md": "f67066fdb4e34c049e830f89f68be49e2b989b8ad312125a2e676ddc35eac9ac",
    "docs/onyx/checkpoints/phase6-agentic-core-v3/PHASE6_AGENTIC_CORE_V3_CHECKPOINT.md": "af2411905da6a27c695014d85c3c403fc8792b154907689f4dc920aa69cf1bf2",
    "docs/onyx/checkpoints/phase6-agentic-core-v3/manifest.json": "3d77e96c6561445adb8b2cdb61e400d4ba896d6556ed0c357bb270c501d98288",
}


def _echo(value: object) -> object:
    return value


def _sleep_return(seconds: float) -> str:
    time.sleep(seconds)
    return "late"


def _verified_runner(_tool: str, _arguments: dict[str, object], _key: str):
    return {
        "status": "succeeded",
        "data": {"label": "v4-process"},
        "evidence": [],
        "postconditions": [{"name": "runtime_status_observed", "satisfied": True}],
        "waiting_for": None,
    }


def _materialize_v4_process(
    root_text: str,
    plan_id: str,
    pause_stage: str | None,
    ready,
    release,
    output,
):
    core = None
    try:
        root = Path(root_text)
        state = AgenticStateStoreV4(
            root / "plans.sqlite3",
            AgenticFeatureGateV4(True),
            fence_seconds=0.1,
        )
        missions = MissionStore(root / "missions.sqlite3")
        scope = WorkspaceScopeV1(
            "workspace_personal", (str(root.resolve()),), DataClassV1.CONFIDENTIAL
        )
        core = AgenticCoreV4(state, missions, scope)

        def hook(stage, _claim):
            if stage == pause_stage:
                ready.set()
                if not release.wait(10):
                    raise RuntimeError("test release timeout")

        result = core.materialize(plan_id, stage_hook=hook)
        output.put(("ok", result.reason, result.mission_id))
    except BaseException as exc:
        output.put(("error", type(exc).__name__, str(exc)))
    finally:
        if core is not None:
            core.close()


def _goal(index: int = 0, *, compute: float = 5.0) -> GoalV1:
    return GoalV1(
        f"goal_phase6_v4_{index}",
        f"corr_phase6_v4_{index}",
        "workspace_personal",
        f"Inspect local runtime {index}",
        ("runtime observed",),
        ("local runtime metadata",),
        ("no external network",),
        DataClassV1.INTERNAL,
        MissionBudgetV1(
            max_steps=3,
            wall_seconds=30.0,
            max_retries_per_step=0,
            max_repair_cycles=1,
            max_compute_seconds=compute,
        ),
    )


def _plan(index: int = 0, *, compute: float = 5.0):
    goal = _goal(index, compute=compute)
    adapter = DeterministicPlannerAdapterV1(
        goal.workspace_id,
        [
            {
                "step_id": f"step_status_{index}",
                "capability": "local_system_status",
                "arguments": {},
                "dependencies": [],
                "timeout_seconds": 2.0,
                "max_retries": 0,
                "postconditions": ["runtime_status_observed"],
            }
        ],
    )
    return PlannerV2(ModelRouterV1((adapter.descriptor,)), adapter).plan(
        goal, f"request:v4:plan:{index:03d}"
    )


def _state(tmp_path: Path) -> AgenticStateStoreV4:
    return AgenticStateStoreV4(tmp_path / "plans.sqlite3", AgenticFeatureGateV4(True))


def _mission_spec(extra: bool = False) -> list[dict[str, object]]:
    step: dict[str, object] = {
        "tool": "local_system_status",
        "args": {},
        "estimated_provider_cost": 0.0,
    }
    if extra:
        step["unknown"] = "must fail"
    return [step]


def test_v1_v2_v3_artifacts_remain_exactly_frozen():
    root = Path(__file__).resolve().parents[1]
    states = {
        path: classify_historical_artifact(root, path, digest)["state"]
        for path, digest in FROZEN.items()
    }
    assert states["core/missions.py"] == "superseded-not-rebound"
    assert states["tests/test_phase6_agentic_core_v2.py"] == (
        "superseded-not-rebound"
    )
    assert states["tests/test_phase6_agentic_core_v3.py"] == (
        "superseded-not-rebound"
    )
    assert set(states.values()) <= {"preserved-exact", "superseded-not-rebound"}


def test_v4_is_strict_default_off_and_not_live_wired(tmp_path: Path):
    assert AgenticFeatureGateV4.from_environ({}).enabled is False
    assert (
        AgenticFeatureGateV4.from_environ(
            {"ONYX_PHASE6_AGENTIC_CORE_V4": "true"}
        ).enabled
        is True
    )
    with pytest.raises(AgenticCoreV4Denied):
        AgenticStateStoreV4(tmp_path / "off.sqlite3", AgenticFeatureGateV4(False))
    root = Path(__file__).resolve().parents[1]
    for path in ("main.py", "ui.py", "dashboard/server.py"):
        assert "phase6_agentic_core_v4" not in (root / path).read_text(encoding="utf-8")


@pytest.mark.parametrize("tamper", ["index", "trigger", "table"])
def test_canonical_schema_authentication_rejects_same_name_changes(
    tmp_path: Path, tamper: str
):
    state = _state(tmp_path)
    with sqlite3.connect(state.coordination_path) as connection:
        if tamper == "index":
            connection.execute("DROP INDEX runtime_terminal_idx")
            connection.execute(
                "CREATE INDEX runtime_terminal_idx ON runtime_plans(plan_id,terminal)"
            )
        elif tamper == "trigger":
            connection.execute("DROP TRIGGER lineage_identity_no_update")
            connection.execute(
                "CREATE TRIGGER lineage_identity_no_update BEFORE DELETE ON plan_lineage "
                "BEGIN SELECT RAISE(ABORT,'changed'); END"
            )
        else:
            connection.execute("ALTER TABLE runtime_plans ADD COLUMN hidden TEXT")
    with pytest.raises(AgenticCoreV4Error, match="authentication failed"):
        AgenticStateStoreV4(state.plans.path, AgenticFeatureGateV4(True))


def test_recovery_and_compaction_query_plans_use_exact_indexes_without_temp_sort(
    tmp_path: Path,
):
    state = _state(tmp_path)
    with sqlite3.connect(state.coordination_path) as connection:
        expired = " ".join(
            str(row[-1])
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM budget_accounts "
                "WHERE active_token IS NOT NULL AND active_deadline_wall<=? "
                "ORDER BY active_deadline_wall,account_id LIMIT ?",
                (time.time(), 3),
            )
        )
        terminal = " ".join(
            str(row[-1])
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT plan_id FROM runtime_plans "
                "WHERE terminal=1 AND updated_at<? "
                "ORDER BY terminal,updated_at,plan_id LIMIT ?",
                (time.time(), 3),
            )
        )
    assert "budget_expired_idx" in expired
    assert "runtime_terminal_idx" in terminal
    assert "TEMP B-TREE" not in expired.upper()
    assert "TEMP B-TREE" not in terminal.upper()


def test_recover_compute_never_clears_living_or_renewed_lease(tmp_path: Path):
    state = _state(tmp_path)
    plan = _plan()
    account = state.reserve_request_budget("request:v4:living:001", 10.0)
    state.register_plan(plan, account)
    lease = state.begin_compute(plan.plan_id, "planner")
    assert state.recover_compute(limit=3) == ()
    with sqlite3.connect(state.coordination_path) as connection:
        connection.execute(
            "UPDATE budget_accounts SET active_deadline_wall=? WHERE account_id=?",
            (time.time() - 1.0, account),
        )
    renewed: list[object] = []

    def renew(observed):
        if not renewed:
            renewed.append(state.renew_compute(observed, extend_seconds=10.0))

    assert state.recover_compute(limit=3, before_cas=renew) == ()
    with sqlite3.connect(state.coordination_path) as connection:
        row = connection.execute(
            "SELECT active_token,active_deadline_wall,generation "
            "FROM budget_accounts WHERE account_id=?",
            (account,),
        ).fetchone()
    assert row[0] == lease.token
    assert row[1] > time.time()
    assert row[2] > lease.generation


def test_expired_recovery_has_one_global_limit_across_accounts(tmp_path: Path):
    state = _state(tmp_path)
    accounts = []
    for index in range(5):
        plan = _plan(index)
        account = state.reserve_request_budget(f"request:v4:expired:{index:03d}", 5.0)
        state.register_plan(plan, account)
        state.begin_compute(plan.plan_id, "runner")
        accounts.append(account)
    with sqlite3.connect(state.coordination_path) as connection:
        connection.execute(
            "UPDATE budget_accounts SET active_deadline_wall=?", (time.time() - 1.0,)
        )
    recovered = state.recover_compute(limit=3)
    assert len(recovered) == 3
    with sqlite3.connect(state.coordination_path) as connection:
        remaining = connection.execute(
            "SELECT COUNT(*) FROM budget_accounts WHERE active_token IS NOT NULL"
        ).fetchone()[0]
    assert remaining == 2


def test_exact_materializer_rejects_lossy_or_unknown_input_before_write(
    tmp_path: Path,
):
    store = MissionStore(tmp_path / "missions.sqlite3")
    materializer = StrictMissionMaterializerV4(store)
    with pytest.raises(AgenticCoreV4ContractError, match="240"):
        materializer.create_idempotent(
            "request.v4.title.001", "x" * 241, _mission_spec()
        )
    with pytest.raises(AgenticCoreV4ContractError, match="unknown"):
        materializer.create_idempotent(
            "request.v4.extra.001", "Exact", _mission_spec(extra=True)
        )
    assert store.list() == []
    first = materializer.create_idempotent(
        "request.v4.replay.001", "A" * 240, _mission_spec()
    )
    second = materializer.create_idempotent(
        "request.v4.replay.001", "A" * 240, _mission_spec()
    )
    assert first.id == second.id
    with pytest.raises(MissionError, match="different exact caller input"):
        materializer.create_idempotent(
            "request.v4.replay.001", "B" * 240, _mission_spec()
        )
    assert len(store.list()) == 1


def test_process_timeout_terminates_and_joins_worker():
    executor = TerminableProcessExecutorV4()
    with pytest.raises(ProcessCallTimeoutV4):
        executor.invoke(_sleep_return, 0.05, 5.0)
    assert executor.worker_pid is None
    assert executor.invoke(_echo, 2.0, "recovered") == "recovered"
    executor.close()
    assert executor.worker_pid is None


def test_lineage_deadline_terminates_process_charges_and_exhausts(tmp_path: Path):
    state = _state(tmp_path)
    account = state.reserve_request_budget("request:v4:hung:planner", 0.08)
    missions = MissionStore(tmp_path / "missions.sqlite3")
    scope = WorkspaceScopeV1(
        "workspace_personal", (str(tmp_path.resolve()),), DataClassV1.CONFIDENTIAL
    )
    with AgenticCoreV4(state, missions, scope) as core:
        with pytest.raises(ComputeBudgetExhaustedV4):
            core._bounded_call(account, "planner", _sleep_return, (5.0,))
        assert state.compute_snapshot(account).exhausted is True
        assert core._executor.worker_pid is None


def test_twelve_create_close_cycles_have_zero_thread_and_child_delta():
    baseline_threads = {thread.ident for thread in threading.enumerate()}
    baseline_children = {child.pid for child in multiprocessing.active_children()}
    for index in range(12):
        with TerminableProcessExecutorV4() as executor:
            assert executor.invoke(_echo, 2.0, index) == index
        assert executor.worker_pid is None
    gc.collect()
    assert {thread.ident for thread in threading.enumerate()} == baseline_threads
    assert {
        child.pid for child in multiprocessing.active_children()
    } == baseline_children


def test_v4_end_to_end_plan_materialize_execute_verify_and_close(tmp_path: Path):
    state = _state(tmp_path)
    missions = MissionStore(tmp_path / "missions.sqlite3")
    scope = WorkspaceScopeV1(
        "workspace_personal", (str(tmp_path.resolve()),), DataClassV1.CONFIDENTIAL
    )
    with AgenticCoreV4(state, missions, scope) as core:
        projection = core.submit(
            _goal(77),
            "request:v4:e2e:077",
            [
                {
                    "step_id": "step_status_77",
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
        mission = core.execute_approved(projection.plan_id, _verified_runner)
        assert mission.state == "succeeded"
        assert state.get_projection(projection.plan_id).state is PlanStateV1.COMPLETE
    assert core.closed is True
    assert core._executor.worker_pid is None


@pytest.mark.parametrize("pause_stage", ["claimed", "after_create"])
def test_v4_forced_expiry_two_processes_converge_on_one_executable_mission(
    tmp_path: Path, pause_stage: str
):
    state = AgenticStateStoreV4(
        tmp_path / "plans.sqlite3",
        AgenticFeatureGateV4(True),
        fence_seconds=0.1,
    )
    missions = MissionStore(tmp_path / "missions.sqlite3")
    plan = _plan(88)
    account = state.reserve_request_budget("request:v4:fence:088", 5.0)
    state.register_plan(plan, account)
    context = multiprocessing.get_context("spawn")
    ready, release = context.Event(), context.Event()
    never_ready, never_release = context.Event(), context.Event()
    output = context.Queue()
    stale = context.Process(
        target=_materialize_v4_process,
        args=(str(tmp_path), plan.plan_id, pause_stage, ready, release, output),
    )
    stale.start()
    assert ready.wait(10)
    with sqlite3.connect(state.coordination_path) as connection:
        connection.execute(
            "UPDATE materializations SET lease_expires=? WHERE plan_id=?",
            (time.time() - 1.0, plan.plan_id),
        )
    winner = context.Process(
        target=_materialize_v4_process,
        args=(
            str(tmp_path),
            plan.plan_id,
            None,
            never_ready,
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
    assert state.get_projection(plan.plan_id).mission_id == stored[0].id
    scope = WorkspaceScopeV1(
        "workspace_personal", (str(tmp_path.resolve()),), DataClassV1.CONFIDENTIAL
    )
    with AgenticCoreV4(state, missions, scope) as core:
        set_permission_callback(lambda request: request["digest"])
        missions.approve(stored[0].id)
        set_permission_callback(None)
        assert (
            core.execute_approved(plan.plan_id, _verified_runner).state == "succeeded"
        )


def test_terminal_compaction_is_bounded_and_plan_uses_terminal_index(tmp_path: Path):
    state = _state(tmp_path)
    for index in range(5):
        plan = _plan(index)
        account = state.reserve_request_budget(f"request:v4:compact:{index:03d}", 5.0)
        state.register_plan(plan, account)
        state.touch_runtime(plan.plan_id, terminal=True)
    with sqlite3.connect(state.coordination_path) as connection:
        connection.execute("UPDATE runtime_plans SET updated_at=0")
    result = state.compact(retention_seconds=0, limit=3)
    assert result.plans_deleted == 3
    with sqlite3.connect(state.coordination_path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM runtime_plans").fetchone()[0] == 2
        )


def test_checkpoint_manifest_recomputes_artifact_root():
    root = Path(__file__).resolve().parents[1]
    result = verify_recorded_manifest(
        root,
        "docs/onyx/checkpoints/phase6-agentic-core-v4/manifest.json",
        "f831f52ff257b877f6dbb7b2eac279cee7c2ffd6c84b5761998ac37689e14315",
        "bdcdee76e4209c071705d4ad76a69515efd4dd6fe395005d3fa653da9c51b0cd",
        artifact_root_v2,
    )
    assert result["artifacts"] == 5
    assert result["states"]["tests/test_phase6_agentic_core_v4.py"] == (
        "superseded-not-rebound"
    )
