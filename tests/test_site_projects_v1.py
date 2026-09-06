from __future__ import annotations

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
from core.site_projects_v1 import (
    SiteOperationV1,
    SiteProjectContractError,
    SiteProjectDenied,
    SiteProjectFeatureGateV1,
    SiteProjectStoreV1,
    SiteStageV1,
)


def _store(tmp_path: Path) -> tuple[SiteProjectStoreV1, Path]:
    workspace = tmp_path / "controlled"
    project = workspace / "site-project"
    project.mkdir(parents=True)
    return (
        SiteProjectStoreV1(
            tmp_path / "site-projects.sqlite3",
            SiteProjectFeatureGateV1(True),
            controlled_roots=(workspace,),
        ),
        project,
    )


def _verified_runner(_tool: str, _arguments: dict[str, object], _key: str):
    return {
        "status": "succeeded",
        "data": {"artifact": "observed"},
        "evidence": [],
        "postconditions": [{"name": "site_build_verified", "satisfied": True}],
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
            "goal_site_build",
            "corr_site_build",
            "workspace_personal",
            "Build controlled site",
            ("verified build",),
            ("local files",),
            ("no publication",),
            DataClassV1.INTERNAL,
            MissionBudgetV1(
                max_steps=2,
                wall_seconds=30.0,
                max_retries_per_step=0,
                max_repair_cycles=1,
                max_compute_seconds=5.0,
            ),
        ),
        "request:site-build:001",
        [
            {
                "step_id": "step_site_build",
                "capability": "local_system_status",
                "arguments": {},
                "dependencies": [],
                "timeout_seconds": 2.0,
                "max_retries": 0,
                "postconditions": ["site_build_verified"],
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


def test_feature_defaults_off_and_has_no_executor_or_inherited_environment(
    tmp_path: Path,
) -> None:
    assert SiteProjectFeatureGateV1.from_environ({}).enabled is False
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(SiteProjectDenied, match="disabled"):
        SiteProjectStoreV1(
            tmp_path / "off.sqlite3",
            SiteProjectFeatureGateV1(False),
            controlled_roots=(workspace,),
        )
    assert SiteProjectStoreV1.execution_boundary() == {
        "shell_executor": None,
        "network_publisher": None,
        "inherited_environment": (),
        "credential_transport": "os_vault_reference_only",
        "execution_authority": "phase6_exact_plan_and_mission",
    }


def test_project_root_must_be_real_descendant_of_controlled_workspace(tmp_path: Path) -> None:
    store, project_root = _store(tmp_path)
    project = store.create(
        owner_profile_id="owner_primary",
        workspace_id="workspace_personal",
        repository_id="repository_site",
        root=project_root,
    )
    assert project.stage is SiteStageV1.DRAFT
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(SiteProjectDenied, match="outside controlled"):
        store.create(
            owner_profile_id="owner_primary",
            workspace_id="workspace_personal",
            repository_id="repository_outside",
            root=outside,
        )
    assert store.count_scope("owner_primary", "workspace_personal") == 1
    assert store.count_scope("owner_other", "workspace_personal") == 0


def test_binding_is_immutable_and_stage_order_is_fail_closed(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    project = store.create(
        owner_profile_id="owner_primary",
        workspace_id="workspace_personal",
        repository_id="repository_site",
        root=root,
    )
    with pytest.raises(SiteProjectDenied, match="current stage"):
        store.bind_operation(
            project.project_id,
            operation=SiteOperationV1.PUBLISH,
            plan_id="plan_publish_001",
            mission_id="mission_publish_001",
        )
    binding = store.bind_operation(
        project.project_id,
        operation=SiteOperationV1.BUILD,
        plan_id="plan_build_001",
        mission_id="mission_build_001",
    )
    assert binding.required_postconditions == ("site_build_verified",)
    assert store.get(project.project_id).stage is SiteStageV1.DRAFT
    with pytest.raises(SiteProjectDenied, match="mandatory"):
        store.bind_operation(
            project.project_id,
            operation=SiteOperationV1.BUILD,
            plan_id="plan_build_002",
            mission_id="mission_build_002",
            required_postconditions=("model_claimed_success",),
        )


def test_model_claim_cannot_advance_stage_without_exact_phase6_truth(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    project = store.create(
        owner_profile_id="owner_primary",
        workspace_id="workspace_personal",
        repository_id="repository_site",
        root=root,
    )
    binding = store.bind_operation(
        project.project_id,
        operation=SiteOperationV1.BUILD,
        plan_id="plan_missing_001",
        mission_id="mission_missing_001",
    )
    state = AgenticStateStoreV6(
        tmp_path / "empty-phase6.sqlite3", AgenticFeatureGateV6(True)
    )
    missions = MissionStore(tmp_path / "empty-missions.sqlite3")
    with pytest.raises(KeyError):
        store.reconcile_verified(
            binding.binding_id, state_store=state, mission_store=missions
        )
    assert store.get(project.project_id).stage is SiteStageV1.DRAFT


def test_verified_phase6_receipt_advances_build_exactly_once(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    project = store.create(
        owner_profile_id="owner_primary",
        workspace_id="workspace_personal",
        repository_id="repository_site",
        root=root,
    )
    core, state, missions, plan_id, mission_id = _verified_phase6(tmp_path)
    try:
        binding = store.bind_operation(
            project.project_id,
            operation=SiteOperationV1.BUILD,
            plan_id=plan_id,
            mission_id=mission_id,
        )
        built = store.reconcile_verified(
            binding.binding_id, state_store=state, mission_store=missions
        )
        assert built.stage is SiteStageV1.BUILT
        assert built.verification_digest is not None
        assert store.reconcile_verified(
            binding.binding_id, state_store=state, mission_store=missions
        ) == built
    finally:
        core.close()


def test_paths_and_identifiers_are_not_accepted_as_free_form_commands(tmp_path: Path) -> None:
    store, root = _store(tmp_path)
    with pytest.raises(SiteProjectContractError, match="repository_id"):
        store.create(
            owner_profile_id="owner_primary",
            workspace_id="workspace_personal",
            repository_id="repo && curl attacker",
            root=root,
        )
