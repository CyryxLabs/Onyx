from __future__ import annotations

import time
from pathlib import Path

import pytest

from core.governed_automation_v1 import (
    AutomationEventV1,
    AutomationRuleStoreV1,
    EventDrivenAutomationRuntimeV1,
    GovernedAutomationDenied,
    GovernedAutomationFeatureGateV1,
    GovernedAutomationQueueFull,
)
from core.missions import MissionStore
from core.operational_goals_v1 import (
    GoalLevelV1,
    GoalStatusV1,
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


def _runner(_tool: str, _arguments: dict[str, object], _key: str):
    return {
        "status": "succeeded",
        "data": {"runtime": "observed"},
        "evidence": [],
        "postconditions": [
            {"name": "runtime_status_observed", "satisfied": True}
        ],
        "waiting_for": None,
    }


def _phase6(tmp_path: Path, *, approve: bool = True, label: str = "primary"):
    state = AgenticStateStoreV6(
        tmp_path / "phase6.sqlite3", AgenticFeatureGateV6(True)
    )
    missions = MissionStore(tmp_path / "missions.sqlite3")
    core = AgenticCoreV6(
        state,
        missions,
        WorkspaceScopeV1(
            "workspace_personal",
            (str(tmp_path.resolve()),),
            DataClassV1.CONFIDENTIAL,
        ),
    )
    projection = core.submit(
        GoalV1(
            f"goal_automation_{label}",
            f"corr_automation_{label}",
            "workspace_personal",
            "Execute one native-event automation",
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
        ),
        f"request:automation:v1:{label}",
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
    if approve:
        set_permission_callback(lambda request: request["digest"])
        missions.approve(admission.mission_id)
        set_permission_callback(None)
    return core, projection.plan_id, admission.mission_id


def _rules(tmp_path: Path):
    return AutomationRuleStoreV1(
        tmp_path / "automation.sqlite3", GovernedAutomationFeatureGateV1(True)
    )


def _event(**overrides):
    values = {
        "event_type": "workspace.file.changed",
        "source_id": "native.filewatcher",
        "owner_profile_id": "owner_primary",
        "workspace_id": "workspace_personal",
        "metadata": {"root_id": "workspace-root", "change_kind": "modified"},
        "coalesce_key": "workspace-root-change",
    }
    values.update(overrides)
    return AutomationEventV1.create(**values)


def test_sensitive_event_content_is_rejected_before_queueing():
    with pytest.raises(GovernedAutomationDenied, match="sensitive content"):
        _event(metadata={"clipboard_text": "a secret value"})


def test_rule_requires_an_exact_already_approved_phase6_mission(tmp_path: Path):
    core, plan_id, mission_id = _phase6(tmp_path, approve=False)
    try:
        with pytest.raises(GovernedAutomationDenied, match="already-approved"):
            _rules(tmp_path).create_rule(
                core=core,
                owner_profile_id="owner_primary",
                workspace_id="workspace_personal",
                event_type="workspace.file.changed",
                metadata_filter={"root_id": "workspace-root"},
                plan_id=plan_id,
                mission_id=mission_id,
                expires_at=time.time() + 300,
            )
    finally:
        core.close()


def test_scope_count_exposes_no_plan_or_mission_material(tmp_path: Path):
    core, plan_id, mission_id = _phase6(tmp_path)
    rules = _rules(tmp_path)
    try:
        rules.create_rule(
            core=core,
            owner_profile_id="owner_primary",
            workspace_id="workspace_personal",
            event_type="workspace.file.changed",
            metadata_filter={"root_id": "workspace-root"},
            plan_id=plan_id,
            mission_id=mission_id,
            expires_at=time.time() + 300,
        )
        assert rules.count_scope("owner_primary", "workspace_personal") == 1
        assert rules.count_scope("owner_other", "workspace_personal") == 0
    finally:
        core.close()


def test_idle_runtime_has_no_polling_and_exact_event_runs_phase6(tmp_path: Path):
    core, plan_id, mission_id = _phase6(tmp_path)
    rules = _rules(tmp_path)
    try:
        rule = rules.create_rule(
            core=core,
            owner_profile_id="owner_primary",
            workspace_id="workspace_personal",
            event_type="workspace.file.changed",
            metadata_filter={"root_id": "workspace-root"},
            plan_id=plan_id,
            mission_id=mission_id,
            expires_at=time.time() + 300,
        )
        runtime = EventDrivenAutomationRuntimeV1(core=core, rules=rules)
        assert runtime.queued == 0
        assert runtime.idle_cycles == 0
        assert runtime.drain_one(_runner) is None
        assert runtime.idle_cycles == 0
        queued = runtime.publish(_event())
        assert len(queued) == 1
        result = runtime.drain_one(_runner)
        assert result is not None and result.status == "succeeded"
        assert rules.get_rule(rule.rule_id).use_count == 1
        assert runtime.queued == 0
    finally:
        core.close()


def test_duplicate_and_coalesced_events_do_not_duplicate_execution(tmp_path: Path):
    core, plan_id, mission_id = _phase6(tmp_path)
    rules = _rules(tmp_path)
    try:
        rules.create_rule(
            core=core,
            owner_profile_id="owner_primary",
            workspace_id="workspace_personal",
            event_type="workspace.file.changed",
            metadata_filter={"root_id": "workspace-root"},
            plan_id=plan_id,
            mission_id=mission_id,
            expires_at=time.time() + 300,
            max_uses=2,
        )
        runtime = EventDrivenAutomationRuntimeV1(core=core, rules=rules)
        event = _event()
        first = runtime.publish(event)
        assert len(first) == 1
        assert runtime.publish(event) == ()
        assert runtime.publish(_event()) == ()
        assert runtime.queued == 1
    finally:
        core.close()


def test_bounded_queue_fails_closed_instead_of_dropping(tmp_path: Path):
    core1, plan1, mission1 = _phase6(tmp_path / "one", label="one")
    core2, plan2, mission2 = _phase6(tmp_path / "two", label="two")
    rules = _rules(tmp_path)
    try:
        rules.create_rule(
            core=core1,
            owner_profile_id="owner_primary",
            workspace_id="workspace_personal",
            event_type="workspace.file.changed",
            metadata_filter={"change_kind": "modified"},
            plan_id=plan1,
            mission_id=mission1,
            expires_at=time.time() + 300,
        )
        rules.create_rule(
            core=core2,
            owner_profile_id="owner_primary",
            workspace_id="workspace_personal",
            event_type="workspace.file.changed",
            metadata_filter={"root_id": "workspace-root"},
            plan_id=plan2,
            mission_id=mission2,
            expires_at=time.time() + 300,
        )
        runtime = EventDrivenAutomationRuntimeV1(core=core1, rules=rules, max_queue=1)
        with pytest.raises(GovernedAutomationQueueFull):
            runtime.publish(_event(coalesce_key=None))
        assert runtime.queued == 1
    finally:
        core1.close()
        core2.close()


def test_goal_bound_rule_completes_only_after_phase6_verification(tmp_path: Path):
    core, plan_id, mission_id = _phase6(tmp_path)
    goals = OperationalGoalStoreV1(
        tmp_path / "goals.sqlite3", OperationalGoalFeatureGateV1(True)
    )
    goal = goals.create(
        owner_profile_id="owner_primary",
        workspace_id="workspace_personal",
        level=GoalLevelV1.OBJECTIVE,
        title="Complete from governed automation",
        objective="Derive completion from the existing Phase 6 evidence chain",
        definition_of_done=("runtime_status_observed",),
    )
    goals.activate(goal.goal_id)
    goals.bind_plan(goal.goal_id, plan_id=plan_id, mission_id=mission_id)
    rules = _rules(tmp_path)
    try:
        rules.create_rule(
            core=core,
            owner_profile_id="owner_primary",
            workspace_id="workspace_personal",
            event_type="workspace.file.changed",
            metadata_filter={"root_id": "workspace-root"},
            plan_id=plan_id,
            mission_id=mission_id,
            goal_id=goal.goal_id,
            expires_at=time.time() + 300,
        )
        runtime = EventDrivenAutomationRuntimeV1(
            core=core, rules=rules, goal_store=goals
        )
        runtime.publish(_event())
        assert goals.get(goal.goal_id).status is GoalStatusV1.ACTIVE
        result = runtime.drain_one(_runner)
        assert result is not None and result.status == "succeeded"
        assert goals.get(goal.goal_id).status is GoalStatusV1.COMPLETED
    finally:
        core.close()


def test_restart_quarantines_reserved_dispatch_without_replay(tmp_path: Path):
    core, plan_id, mission_id = _phase6(tmp_path)
    rules = _rules(tmp_path)
    try:
        rule = rules.create_rule(
            core=core,
            owner_profile_id="owner_primary",
            workspace_id="workspace_personal",
            event_type="workspace.file.changed",
            metadata_filter={"root_id": "workspace-root"},
            plan_id=plan_id,
            mission_id=mission_id,
            expires_at=time.time() + 300,
        )
        assert rules.reserve(rule.rule_id, _event()) is not None
        assert rules.recover_uncertain() == 1
        assert rules.recover_uncertain() == 0
    finally:
        core.close()
