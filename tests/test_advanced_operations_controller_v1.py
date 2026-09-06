from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import hashlib
import time

import pytest

from core.advanced_operations_controller_v1 import (
    AdvancedOperationsControllerDenied,
    AdvancedOperationsControllerV1,
)
from core.governed_automation_v1 import AutomationEventV1
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
from core.phase6_live_wiring_v1 import (
    SESSION_ATTRIBUTE,
    LiveWiringIdentityV1,
    LiveWiringSessionV1,
)


def _authorities(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = AgenticStateStoreV6(tmp_path / "phase6.sqlite3", AgenticFeatureGateV6(True))
    missions = MissionStore(tmp_path / "missions.sqlite3")
    core = AgenticCoreV6(
        state,
        missions,
        WorkspaceScopeV1(
            "workspace-personal",
            (str(workspace.resolve()),),
            DataClassV1.CONFIDENTIAL,
        ),
    )
    return core, state, missions


def _phase6_session(tmp_path: Path, core, state) -> LiveWiringSessionV1:
    session_root = tmp_path / "session"
    session_root.mkdir(exist_ok=True)
    session = object.__new__(LiveWiringSessionV1)
    object.__setattr__(
        session,
        "identity",
        LiveWiringIdentityV1(
            "workspace-personal",
            "account-primary",
            "owner-primary",
            "principal-primary",
        ),
    )
    object.__setattr__(session, "session_key", "session_test")
    object.__setattr__(session, "state_path", session_root / "phase6.sqlite3")
    object.__setattr__(session, "receipt_path", session_root / "receipts.sqlite3")
    object.__setattr__(session, "facade", SimpleNamespace(_core=core, _state=state))
    object.__setattr__(session, "binding_digest", "0" * 64)
    object.__setattr__(session, "_closed", False)
    return session


def _approved_plan(core: AgenticCoreV6) -> tuple[str, str]:
    projection = core.submit(
        GoalV1(
            "goal_advanced_rule",
            "corr_advanced_rule",
            "workspace-personal",
            "Run one approved event workflow",
            ("runtime_status_observed",),
            ("local metadata",),
            ("no network",),
            DataClassV1.INTERNAL,
            MissionBudgetV1(
                max_steps=1,
                wall_seconds=30.0,
                max_retries_per_step=0,
                max_repair_cycles=1,
                max_compute_seconds=5.0,
            ),
        ),
        "request:advanced-rule:001",
        [
            {
                "step_id": "step_status",
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
    try:
        core._missions.approve(admission.mission_id)
    finally:
        set_permission_callback(None)
    return projection.plan_id, admission.mission_id


def _workflow_runner(_tool: str, _arguments: dict[str, object], _key: str):
    return {
        "status": "succeeded",
        "data": {"runtime": "observed"},
        "evidence": [],
        "postconditions": [{"name": "runtime_status_observed", "satisfied": True}],
        "waiting_for": None,
    }


def test_controller_waits_without_polling_until_live_phase6_exists(
    tmp_path: Path,
) -> None:
    host = SimpleNamespace()
    controller = AdvancedOperationsControllerV1(
        host, owner_authority=lambda *_args: True
    )
    assert controller.status() == {
        "contract": "OnyxAdvancedOperationsController.v1",
        "status": "waiting_for_live_session",
        "background_workers": 0,
        "polling_interval": None,
    }
    assert controller.background_workers == 0
    assert controller.polling_interval is None


def test_status_lazily_binds_exact_live_authorities(tmp_path: Path) -> None:
    core, state, missions = _authorities(tmp_path)
    host = SimpleNamespace(_missions=missions)
    setattr(host, SESSION_ATTRIBUTE, _phase6_session(tmp_path, core, state))
    controller = AdvancedOperationsControllerV1(
        host, owner_authority=lambda *_args: True
    )
    try:
        status = controller.status()
        assert status["status"] == "ready"
        assert status["phase6_reused"] is True
        assert status["mission_store_reused"] is True
        assert controller._operations is not None
        assert controller._operations.core is core
    finally:
        controller.close()
        core.close()


def test_session_rotation_closes_old_composition_before_rebinding(
    tmp_path: Path,
) -> None:
    core, state, missions = _authorities(tmp_path)
    host = SimpleNamespace(_missions=missions)
    first = _phase6_session(tmp_path, core, state)
    setattr(host, SESSION_ATTRIBUTE, first)
    controller = AdvancedOperationsControllerV1(
        host, owner_authority=lambda *_args: True
    )
    try:
        controller.status()
        old = controller._operations
        assert old is not None
        setattr(host, SESSION_ATTRIBUTE, None)
        assert controller.status()["status"] == "waiting_for_live_session"
        assert old.closed is True
        assert controller._operations is None
    finally:
        controller.close()
        core.close()


def test_mission_store_drift_fails_closed(tmp_path: Path) -> None:
    core, state, _missions = _authorities(tmp_path)
    host = SimpleNamespace(_missions=MissionStore(tmp_path / "other-missions.sqlite3"))
    setattr(host, SESSION_ATTRIBUTE, _phase6_session(tmp_path, core, state))
    controller = AdvancedOperationsControllerV1(
        host, owner_authority=lambda *_args: True
    )
    try:
        with pytest.raises(
            AdvancedOperationsControllerDenied, match="authorities diverged"
        ):
            controller.status()
    finally:
        controller.close()
        core.close()


def test_attention_is_safe_while_waiting_and_controller_close_is_terminal(
    tmp_path: Path,
) -> None:
    controller = AdvancedOperationsControllerV1(
        SimpleNamespace(), owner_authority=lambda *_args: True
    )
    assert controller.attention()["status"] == "waiting_for_live_session"
    controller.close()
    controller.close()
    with pytest.raises(AdvancedOperationsControllerDenied, match="closed"):
        controller.status()


def test_daily_rhythm_waits_read_only_and_rejects_unknown_cadence() -> None:
    controller = AdvancedOperationsControllerV1(
        SimpleNamespace(), owner_authority=lambda *_args: True
    )
    try:
        projection = controller.execute(
            {"action": "daily_rhythm", "cadence": "evening_review"}
        )
        assert projection == {
            "contract": "OnyxOperationalRhythm.v1",
            "status": "waiting_for_live_session",
            "cadence": "evening_review",
            "focus": (),
            "actions": (),
            "warnings": (),
            "read_only": True,
            "external_dispatch": False,
            "goal_mutations": 0,
            "background_workers": 0,
            "polling_interval": None,
        }
        assert controller._operations is None
        with pytest.raises(AdvancedOperationsControllerDenied, match="cadence"):
            controller.execute({"action": "daily_rhythm", "cadence": "weekly"})
    finally:
        controller.close()


def test_native_workspace_events_arm_without_constructing_qt_before_session() -> None:
    controller = AdvancedOperationsControllerV1(
        SimpleNamespace(), owner_authority=lambda *_args: True
    )
    try:
        controller.request_native_workspace_events()
        assert controller._native_workspace_events_requested is True
        assert controller.ui_status() == {
            "contract": "OnyxAdvancedOperationsController.v1",
            "status": "waiting_for_live_session",
            "background_workers": 0,
            "polling_interval": None,
        }
        assert controller._operations is None
    finally:
        controller.close()


def test_execute_creates_reads_and_transitions_scope_bound_goal(tmp_path: Path) -> None:
    core, state, missions = _authorities(tmp_path)
    host = SimpleNamespace(_missions=missions)
    setattr(host, SESSION_ATTRIBUTE, _phase6_session(tmp_path, core, state))
    controller = AdvancedOperationsControllerV1(
        host, owner_authority=lambda *_args: True
    )
    try:
        created = controller.execute(
            {
                "action": "create_goal",
                "level": "objective",
                "title": "Launch Onyx",
                "objective": "Deliver a verified daily assistant",
                "definition_of_done": ["installed_verified"],
            }
        )
        goal_id = created["goal"]["goal_id"]
        assert created["external_dispatch"] is False
        assert created["goal"]["status"] == "draft"
        assert (
            controller.execute({"action": "activate_goal", "goal_id": goal_id})["goal"][
                "status"
            ]
            == "active"
        )
        assert (
            controller.execute({"action": "pause_goal", "goal_id": goal_id})["goal"][
                "status"
            ]
            == "paused"
        )
        assert (
            controller.execute({"action": "get_goal", "goal_id": goal_id})["goal"][
                "title"
            ]
            == "Launch Onyx"
        )
    finally:
        controller.close()
        core.close()


def test_execute_waits_without_creating_state_before_phase6_session() -> None:
    controller = AdvancedOperationsControllerV1(
        SimpleNamespace(), owner_authority=lambda *_args: True
    )
    assert controller.execute(
        {
            "action": "create_goal",
            "level": "objective",
            "title": "Deferred",
            "objective": "Wait for the exact live authority",
            "definition_of_done": ["bound"],
        }
    ) == {
        "contract": "OnyxAdvancedOperationsCommand.v1",
        "status": "waiting_for_live_session",
        "action": "create_goal",
    }


def test_execute_rejects_unknown_actions_and_model_selected_identity(
    tmp_path: Path,
) -> None:
    core, state, missions = _authorities(tmp_path)
    host = SimpleNamespace(_missions=missions)
    setattr(host, SESSION_ATTRIBUTE, _phase6_session(tmp_path, core, state))
    controller = AdvancedOperationsControllerV1(
        host, owner_authority=lambda *_args: True
    )
    try:
        with pytest.raises(AdvancedOperationsControllerDenied, match="unsupported"):
            controller.execute({"action": "run_shell", "owner_profile_id": "attacker"})
        created = controller.execute(
            {
                "action": "create_goal",
                "owner_profile_id": "attacker",
                "workspace_id": "other-workspace",
                "level": "objective",
                "title": "Bound identity",
                "objective": "Ignore model-selected identity",
                "definition_of_done": ["verified"],
            }
        )
        stored = controller._operations.goals.get(created["goal"]["goal_id"])
        assert stored.owner_profile_id == "owner-primary"
        assert stored.workspace_id == "workspace-personal"
    finally:
        controller.close()
        core.close()


def test_execute_authors_rule_only_over_exact_approved_phase6_mission(
    tmp_path: Path,
) -> None:
    core, state, missions = _authorities(tmp_path)
    host = SimpleNamespace(_missions=missions)
    setattr(host, SESSION_ATTRIBUTE, _phase6_session(tmp_path, core, state))
    controller = AdvancedOperationsControllerV1(
        host, owner_authority=lambda *_args: True
    )
    try:
        plan_id, mission_id = _approved_plan(core)
        created = controller.execute(
            {
                "action": "create_automation_rule",
                "event_type": "workspace.file.changed",
                "metadata_filter": {"root_id": "primary"},
                "plan_id": plan_id,
                "mission_id": mission_id,
                "expires_at": time.time() + 300,
                "max_uses": 2,
            }
        )
        rule = created["automation_rule"]
        assert created["external_dispatch"] is False
        assert rule["plan_id"] == plan_id
        assert rule["mission_id"] == mission_id
        assert (
            controller.execute(
                {"action": "get_automation_rule", "rule_id": rule["rule_id"]}
            )["automation_rule"]
            == rule
        )
        with pytest.raises(AdvancedOperationsControllerDenied):
            controller.execute(
                {
                    "action": "create_automation_rule",
                    "event_type": "workspace.file.changed",
                    "metadata_filter": {},
                    "plan_id": "plan_missing",
                    "mission_id": "mission_missing",
                    "expires_at": time.time() + 300,
                }
            )
    finally:
        controller.close()
        core.close()


def test_execute_creates_reads_and_binds_governed_workflow(
    tmp_path: Path,
) -> None:
    core, state, missions = _authorities(tmp_path)
    host = SimpleNamespace(_missions=missions)
    setattr(host, SESSION_ATTRIBUTE, _phase6_session(tmp_path, core, state))
    controller = AdvancedOperationsControllerV1(
        host, owner_authority=lambda *_args: True
    )
    nodes = [
        {
            "node_id": "trigger_workspace",
            "kind": "trigger",
            "config": {"event_type": "workspace.file.changed"},
        },
        {
            "node_id": "plan_review",
            "kind": "plan",
            "config": {"label": "Review the approved change"},
        },
        {
            "node_id": "output_receipt",
            "kind": "output",
            "config": {"label": "Verified receipt"},
        },
    ]
    edges = [
        {"source": "trigger_workspace", "target": "plan_review", "route": "next"},
        {"source": "plan_review", "target": "output_receipt", "route": "next"},
    ]
    try:
        created = controller.execute(
            {
                "action": "create_workflow",
                "workflow_name": "Review workspace changes",
                "workflow_description": "Route a local event to one approved plan.",
                "workflow_nodes": nodes,
                "workflow_edges": edges,
            }
        )
        workflow_id = created["workflow"]["workflow_id"]
        assert created["workflow"]["status"] == "draft"
        assert created["external_dispatch"] is False
        assert controller.execute(
            {"action": "get_workflow", "workflow_id": workflow_id}
        )["workflow"]["graph"]["order"] == [
            "trigger_workspace",
            "plan_review",
            "output_receipt",
        ]
        plan_id, mission_id = _approved_plan(core)
        bound = controller.execute(
            {
                "action": "bind_workflow_plan",
                "workflow_id": workflow_id,
                "plan_id": plan_id,
                "mission_id": mission_id,
                "required_postconditions": ["runtime_status_observed"],
            }
        )
        assert bound["workflow"]["binding"] == {
            "node_id": "plan_review",
            "plan_id": plan_id,
            "mission_id": mission_id,
            "rule_id": bound["workflow"]["binding"]["rule_id"],
            "required_postconditions": ("runtime_status_observed",),
            "status": "bound",
            "verification_digest": None,
        }
        assert (
            controller.execute(
                {"action": "activate_workflow", "workflow_id": workflow_id}
            )["workflow"]["status"]
            == "active"
        )
        rule_id = bound["workflow"]["binding"]["rule_id"]
        assert controller._operations.rules.get_rule(rule_id).enabled is True
        assert (
            controller.execute(
                {"action": "pause_workflow", "workflow_id": workflow_id}
            )["workflow"]["status"]
            == "paused"
        )
        assert controller._operations.rules.get_rule(rule_id).enabled is False
        assert (
            controller.execute(
                {"action": "activate_workflow", "workflow_id": workflow_id}
            )["workflow"]["status"]
            == "active"
        )
        event = AutomationEventV1.create(
            event_type="workspace.file.changed",
            source_id="native_workspace_events",
            owner_profile_id="owner-primary",
            workspace_id="workspace-personal",
            metadata={},
        )
        assert len(controller._operations.automation.publish(event)) == 1
        dispatch = controller._operations.automation.drain_one(_workflow_runner)
        assert dispatch is not None and dispatch.status == "succeeded"
        completed = controller.execute(
            {"action": "reconcile_workflow", "workflow_id": workflow_id}
        )
        assert completed["workflow"]["status"] == "completed"
        assert completed["workflow"]["binding"]["verification_digest"]
        assert controller._operations.rules.get_rule(rule_id).enabled is False
    finally:
        controller.close()
        core.close()


def test_execute_manages_site_metadata_inside_controlled_workspace(
    tmp_path: Path,
) -> None:
    core, state, missions = _authorities(tmp_path)
    host = SimpleNamespace(_missions=missions)
    setattr(host, SESSION_ATTRIBUTE, _phase6_session(tmp_path, core, state))
    controller = AdvancedOperationsControllerV1(
        host, owner_authority=lambda *_args: True
    )
    site_root = Path(core._workspace.allowed_roots[0]) / "site"
    site_root.mkdir()
    try:
        created = controller.execute(
            {
                "action": "create_site_project",
                "repository_id": "repository_primary",
                "root": str(site_root),
            }
        )
        project = created["site_project"]
        assert project["stage"] == "draft"
        assert "root" not in project
        plan_id, mission_id = _approved_plan(core)
        bound = controller.execute(
            {
                "action": "bind_site_operation",
                "project_id": project["project_id"],
                "operation": "build",
                "plan_id": plan_id,
                "mission_id": mission_id,
            }
        )
        assert bound["site_binding"]["status"] == "bound"
        assert bound["external_dispatch"] is False
    finally:
        controller.close()
        core.close()


def test_execute_manages_owner_scoped_style_preferences(tmp_path: Path) -> None:
    core, state, missions = _authorities(tmp_path)
    host = SimpleNamespace(_missions=missions)
    setattr(host, SESSION_ATTRIBUTE, _phase6_session(tmp_path, core, state))
    controller = AdvancedOperationsControllerV1(
        host, owner_authority=lambda *_args: True
    )
    now = time.time()
    evidence = [
        {
            "evidence_id": f"evidence_{index}",
            "source_type": source,
            "source_reference": f"source_reference_{index}",
            "observation_digest": hashlib.sha256(str(index).encode()).hexdigest(),
            "occurred_at": now - index,
        }
        for index, source in enumerate(
            ("voice_session", "text_session", "owner_feedback"), start=1
        )
    ]
    try:
        created = controller.execute(
            {
                "action": "suggest_preference",
                "preference_key": "response_detail",
                "preference_value": "concise",
                "preference_evidence": evidence,
                "owner_profile_id": "attacker",
            }
        )
        suggestion = created["preference_suggestion"]
        assert suggestion["status"] == "pending"
        promoted = controller.execute(
            {
                "action": "promote_preference",
                "suggestion_id": suggestion["suggestion_id"],
            }
        )
        assert promoted["active_preference"]["value"] == "concise"
        assert (
            controller.execute(
                {
                    "action": "get_active_preference",
                    "preference_key": "response_detail",
                }
            )["active_preference"]["value"]
            == "concise"
        )
        rolled_back = controller.execute(
            {
                "action": "rollback_preference",
                "preference_key": "response_detail",
            }
        )
        assert rolled_back["active_preference"] is None
    finally:
        controller.close()
        core.close()


def test_execute_rejects_malformed_preference_evidence(tmp_path: Path) -> None:
    core, state, missions = _authorities(tmp_path)
    host = SimpleNamespace(_missions=missions)
    setattr(host, SESSION_ATTRIBUTE, _phase6_session(tmp_path, core, state))
    controller = AdvancedOperationsControllerV1(
        host, owner_authority=lambda *_args: True
    )
    try:
        with pytest.raises(AdvancedOperationsControllerDenied):
            controller.execute(
                {
                    "action": "suggest_preference",
                    "preference_key": "initiative",
                    "preference_value": "proactive",
                    "preference_evidence": [{"evidence_id": "incomplete"}],
                }
            )
    finally:
        controller.close()
        core.close()


def test_execute_enrolls_device_with_host_generated_native_vault_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core, state, missions = _authorities(tmp_path)
    host = SimpleNamespace(_missions=missions)
    setattr(host, SESSION_ATTRIBUTE, _phase6_session(tmp_path, core, state))
    controller = AdvancedOperationsControllerV1(
        host,
        owner_authority=lambda *_args: True,
        device_mesh_ledger_auth_key=b"m" * 32,
    )
    vault_values: dict[tuple[str, str], bytes] = {}

    class FakeVault:
        def __init__(self, reference):
            self.reference = reference

        def get_bytes(self):
            return vault_values.get((self.reference.service, self.reference.account))

        def set_bytes(self, value):
            vault_values[(self.reference.service, self.reference.account)] = bytes(
                value
            )

        def delete(self):
            return (
                vault_values.pop((self.reference.service, self.reference.account), None)
                is not None
            )

    monkeypatch.setattr(
        "core.advanced_operations_controller_v1.NativeSecretVault", FakeVault
    )
    try:
        enrolled = controller.execute(
            {
                "action": "enroll_device",
                "device_id": "device_primary",
                "device_issuer": "onyx.mobile.primary",
            }
        )
        assert enrolled["device"] == {
            "device_id": "device_primary",
            "issuer": "onyx.mobile.primary",
            "enabled": True,
            "credential_backend": "native_vault",
        }
        assert len(vault_values[("Onyx.DeviceMesh.v1", "device_primary")]) == 32
        assert (
            controller.execute(
                {"action": "disable_device", "device_id": "device_primary"}
            )["device"]["enabled"]
            is False
        )
        assert (
            controller.execute(
                {"action": "enable_device", "device_id": "device_primary"}
            )["device"]["enabled"]
            is True
        )
    finally:
        controller.close()
        core.close()
