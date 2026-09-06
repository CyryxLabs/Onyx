from __future__ import annotations

from pathlib import Path

import pytest

from core.advanced_operations_live_v1 import (
    AdvancedOperationsLiveDenied,
    AdvancedOperationsLiveFeatureGateV1,
    create_advanced_operations_session_v1,
)
from core.missions import MissionStore
from core.native_workspace_events_v1 import NativeWorkspaceEventPublisherV1
from core.operational_goals_v1 import GoalLevelV1
from core.personality_preferences_v1 import PreferenceKeyV1
from core.phase6_agentic_core_v1 import DataClassV1, WorkspaceScopeV1
from core.phase6_agentic_core_v6 import (
    AgenticCoreV6,
    AgenticFeatureGateV6,
    AgenticStateStoreV6,
)


OWNER = "owner_primary"
WORKSPACE = "workspace_personal"
DEVICE_MESH_LEDGER_KEY = b"m" * 32


def _authorities(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state = AgenticStateStoreV6(tmp_path / "phase6.sqlite3", AgenticFeatureGateV6(True))
    missions = MissionStore(tmp_path / "missions.sqlite3")
    core = AgenticCoreV6(
        state,
        missions,
        WorkspaceScopeV1(
            WORKSPACE, (str(workspace.resolve()),), DataClassV1.CONFIDENTIAL
        ),
    )
    return workspace, core, state, missions


def _session(tmp_path: Path, *, authority=lambda *_args: True):
    workspace, core, state, missions = _authorities(tmp_path)
    session = create_advanced_operations_session_v1(
        gate=AdvancedOperationsLiveFeatureGateV1(True),
        owner_profile_id=OWNER,
        workspace_id=WORKSPACE,
        core=core,
        state=state,
        missions=missions,
        state_root=tmp_path / "advanced",
        controlled_roots=(workspace,),
        owner_authority=authority,
        device_mesh_ledger_auth_key=DEVICE_MESH_LEDGER_KEY,
    )
    assert session is not None
    return session, workspace, core, state, missions


def test_feature_defaults_off_and_disabled_factory_is_noop(tmp_path: Path) -> None:
    assert AdvancedOperationsLiveFeatureGateV1.from_environ({}).enabled is False
    workspace, core, state, missions = _authorities(tmp_path)
    try:
        assert (
            create_advanced_operations_session_v1(
                gate=AdvancedOperationsLiveFeatureGateV1(False),
                owner_profile_id=OWNER,
                workspace_id=WORKSPACE,
                core=core,
                state=state,
                missions=missions,
                state_root=tmp_path / "advanced",
                controlled_roots=(workspace,),
                owner_authority=lambda *_args: True,
            )
            is None
        )
    finally:
        core.close()


def test_session_reuses_exact_phase6_and_mission_authorities_with_zero_workers(
    tmp_path: Path,
) -> None:
    session, _workspace, core, state, missions = _session(tmp_path)
    try:
        status = session.status()
        assert status["status"] == "ready"
        assert status["phase6_reused"] is True
        assert status["mission_store_reused"] is True
        assert session.core is core
        assert session.state is state
        assert session.missions is missions
        assert status["background_workers"] == 0
        assert status["polling_interval"] is None
        assert session.automation._core is core
        assert status["automation_rules"] == 0
        assert status["enrolled_devices"] == 0
        assert status["site_projects"] == 0
        assert status["active_preferences"] == 0
        assert status["workflow_graphs"] == 0
        assert "workflow_graphs" in status["capabilities"]
        assert status["context_nodes"] == 0
        assert status["context_edges"] == 0
        assert "durable_context_graph" in status["capabilities"]
        assert status["workflow_summaries"] == ()
    finally:
        session.close()
        core.close()


def test_native_workspace_publisher_is_explicit_singleton_and_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, workspace, core, _state, _missions = _session(tmp_path)
    publisher = object.__new__(NativeWorkspaceEventPublisherV1)
    publisher._closed = False
    publisher._paths = (workspace,)
    publisher._published_events = 0
    publisher._coalesced_automation_events = 0
    publisher._denied_events = 0
    publisher._callback_errors = 0
    close_calls: list[bool] = []

    def close() -> None:
        close_calls.append(True)
        publisher._closed = True

    publisher.close = close
    monkeypatch.setattr(
        "core.advanced_operations_live_v1.create_qt_native_workspace_event_publisher_v1",
        lambda **_kwargs: publisher,
    )
    try:
        assert session.status()["native_workspace_events"] == "disabled"
        assert session.enable_native_workspace_events() is publisher
        assert session.enable_native_workspace_events() is publisher
        assert session.status()["native_workspace_events"] == "active"
    finally:
        session.close()
        core.close()
    assert close_calls == [True]


def test_all_projection_databases_share_one_private_session_root(
    tmp_path: Path,
) -> None:
    session, _workspace, core, _state, _missions = _session(tmp_path)
    try:
        expected = {
            "operational-goals-v1.sqlite3",
            "governed-automation-v1.sqlite3",
            "device-mesh-v1.sqlite3",
            "personality-preferences-v1.sqlite3",
            "site-projects-v1.sqlite3",
            "automation-adapters-v1.sqlite3",
            "workflow-graphs-v1.sqlite3",
            "context-graph-v1.sqlite3",
        }
        assert {item.name for item in session.root.iterdir()} == expected
    finally:
        session.close()
        core.close()


def test_attention_is_read_only_and_goal_truth_remains_evidence_gated(
    tmp_path: Path,
) -> None:
    session, _workspace, core, _state, _missions = _session(tmp_path)
    try:
        goal = session.goals.create(
            owner_profile_id=OWNER,
            workspace_id=WORKSPACE,
            level=GoalLevelV1.OBJECTIVE,
            title="Operate Onyx",
            objective="Keep the live assistant operational with verified outcomes",
            definition_of_done=("installed_runtime_verified",),
            target_at=10.0,
        )
        session.goals.activate(goal.goal_id)
        attention = session.attention(now=20.0)
        assert attention["goals"][0]["health"] == "overdue"
        assert attention["goals"][0]["score"] == 0.0
        assert attention["rhythm"]["cadence"] in {
            "morning_plan",
            "midday_check",
            "evening_review",
        }
        assert attention["rhythm"]["focus"][0]["title"] == "Operate Onyx"
        assert attention["rhythm"]["read_only"] is True
        assert attention["rhythm"]["external_dispatch"] is False
        assert session.goals.get(goal.goal_id).revision == 2
        assert len(session.goals.events(goal.goal_id)) == 2
    finally:
        session.close()
        core.close()


def test_owner_authority_remains_the_only_preference_promotion_path(
    tmp_path: Path,
) -> None:
    session, _workspace, core, _state, _missions = _session(
        tmp_path, authority=lambda *_args: False
    )
    try:
        assert (
            session.preferences.active(
                OWNER, WORKSPACE, PreferenceKeyV1.RESPONSE_DETAIL
            )
            is None
        )
        assert session.preferences.prompt_projection(OWNER, WORKSPACE) == ""
    finally:
        session.close()
        core.close()


def test_workspace_identity_mismatch_fails_before_any_live_session(
    tmp_path: Path,
) -> None:
    workspace, core, state, missions = _authorities(tmp_path)
    try:
        with pytest.raises(AdvancedOperationsLiveDenied, match="workspace authority"):
            create_advanced_operations_session_v1(
                gate=AdvancedOperationsLiveFeatureGateV1(True),
                owner_profile_id=OWNER,
                workspace_id="workspace_other",
                core=core,
                state=state,
                missions=missions,
                state_root=tmp_path / "advanced",
                controlled_roots=(workspace,),
                owner_authority=lambda *_args: True,
            )
    finally:
        core.close()
