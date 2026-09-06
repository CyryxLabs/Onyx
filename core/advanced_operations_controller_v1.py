"""Lazy host controller for one Advanced Operations live composition.

The controller performs no background work.  A trusted UI/model surface calls
``status`` or ``attention``; only then does it bind to the exact current Phase 6
live session.  Session rotation closes the old projection composition before a
new one is created.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path
from typing import Callable, Mapping

from core.advanced_operations_live_v1 import (
    AdvancedOperationsLiveFeatureGateV1,
    AdvancedOperationsSessionV1,
    create_advanced_operations_session_v1,
)
from core.device_mesh_v1 import EnrolledDeviceV1
from core.missions import MissionError, MissionStore
from core.governed_automation_v1 import AutomationRuleV1
from core.native_vault import NativeSecretVault, SecretReference
from core.operational_goals_v1 import GoalLevelV1, OperationalGoalV1
from core.operational_rhythm_v1 import RhythmCadenceV1
from core.phase6_agentic_core_v1 import PlanStateV1
from core.phase6_agentic_core_v6 import AgenticCoreV6, AgenticStateStoreV6
from core.phase6_live_wiring_v1 import SESSION_ATTRIBUTE, LiveWiringSessionV1
from core.personality_preferences_v1 import (
    ActivePreferenceV1,
    PreferenceEvidenceV1,
    PreferenceKeyV1,
    PreferenceSuggestionV1,
)
from core.site_projects_v1 import (
    SiteOperationBindingV1,
    SiteOperationV1,
    SiteProjectV1,
)
from core.workflow_graph_v1 import WorkflowProjectionV1


HOST_CONTROLLER = "_advanced_operations_controller_v1"


class AdvancedOperationsControllerError(RuntimeError):
    pass


class AdvancedOperationsControllerDenied(PermissionError):
    pass


class AdvancedOperationsControllerV1:
    def __init__(
        self,
        host: object,
        *,
        owner_authority: Callable[[str, str, str, str], bool],
        device_mesh_ledger_auth_key: bytes | bytearray | None = None,
    ) -> None:
        if host is None or not callable(owner_authority):
            raise AdvancedOperationsControllerError(
                "exact controller dependencies are required"
            )
        self._host = host
        self._owner_authority = owner_authority
        self._device_mesh_ledger_auth_key = device_mesh_ledger_auth_key
        self._phase6_session: LiveWiringSessionV1 | None = None
        self._operations: AdvancedOperationsSessionV1 | None = None
        self._closed = False
        self._lock = threading.RLock()
        self._native_workspace_events_requested = False
        self.background_workers = 0
        self.polling_interval = None

    @property
    def closed(self) -> bool:
        return self._closed

    def _detach(self) -> None:
        operations = self._operations
        self._operations = None
        self._phase6_session = None
        if operations is not None:
            operations.close()

    def _bind_current(self) -> AdvancedOperationsSessionV1 | None:
        if self._closed:
            raise AdvancedOperationsControllerDenied(
                "advanced operations controller is closed"
            )
        observed = getattr(self._host, SESSION_ATTRIBUTE, None)
        if observed is self._phase6_session and self._operations is not None:
            if (
                observed is not None
                and not observed.closed
                and not self._operations.closed
            ):
                return self._operations
        self._detach()
        if observed is None:
            return None
        if type(observed) is not LiveWiringSessionV1 or observed.closed:
            raise AdvancedOperationsControllerDenied(
                "live Phase 6 session authority diverged"
            )
        facade = observed.facade
        core = getattr(facade, "_core", None)
        state = getattr(facade, "_state", None)
        missions = getattr(self._host, "_missions", None)
        workspace = getattr(core, "_workspace", None)
        if (
            type(core) is not AgenticCoreV6
            or type(state) is not AgenticStateStoreV6
            or getattr(core, "_state", None) is not state
            or type(missions) is not MissionStore
            or getattr(core, "_missions", None) is not missions
            or workspace is None
            or workspace.workspace_id != observed.identity.workspace_id
        ):
            raise AdvancedOperationsControllerDenied(
                "live Phase 6 authorities diverged"
            )
        operations = create_advanced_operations_session_v1(
            gate=AdvancedOperationsLiveFeatureGateV1(True),
            owner_profile_id=observed.identity.profile_id,
            workspace_id=observed.identity.workspace_id,
            core=core,
            state=state,
            missions=missions,
            state_root=Path(observed.state_path).parent / "advanced-operations-v1",
            controlled_roots=workspace.allowed_roots,
            owner_authority=self._owner_authority,
            device_mesh_ledger_auth_key=self._device_mesh_ledger_auth_key,
        )
        if type(operations) is not AdvancedOperationsSessionV1:
            raise AdvancedOperationsControllerError(
                "advanced operations factory returned drift"
            )
        self._phase6_session = observed
        self._operations = operations
        return operations

    def status(self) -> dict[str, object]:
        with self._lock:
            operations = self._bind_current()
            if operations is None:
                return {
                    "contract": "OnyxAdvancedOperationsController.v1",
                    "status": "waiting_for_live_session",
                    "background_workers": 0,
                    "polling_interval": None,
                }
            result = dict(operations.status())
            result["controller_contract"] = "OnyxAdvancedOperationsController.v1"
            return result

    def request_native_workspace_events(self) -> None:
        """Arm native events without constructing Qt objects off-thread."""

        with self._lock:
            if self._closed:
                raise AdvancedOperationsControllerDenied(
                    "advanced operations controller is closed"
                )
            self._native_workspace_events_requested = True

    def ui_status(self) -> dict[str, object]:
        """Return status and bind the armed Qt publisher on the UI thread."""

        with self._lock:
            operations = self._bind_current()
            if operations is None:
                return {
                    "contract": "OnyxAdvancedOperationsController.v1",
                    "status": "waiting_for_live_session",
                    "background_workers": 0,
                    "polling_interval": None,
                }
            if (
                self._native_workspace_events_requested
                and operations.native_workspace_events is None
            ):
                native_status = operations.enable_native_workspace_events().status()
                if (
                    native_status.active is not True
                    or native_status.background_workers != 0
                    or native_status.polling_interval is not None
                ):
                    raise AdvancedOperationsControllerDenied(
                        "native workspace event publisher failed closed"
                    )
            result = dict(operations.status())
            result["controller_contract"] = "OnyxAdvancedOperationsController.v1"
            return result

    def attention(self, *, now: float | None = None) -> dict[str, object]:
        with self._lock:
            operations = self._bind_current()
            if operations is None:
                return {
                    "contract": "OnyxAdvancedAttention.v1",
                    "status": "waiting_for_live_session",
                    "attention": (),
                    "goals": (),
                }
            return {
                "contract": "OnyxAdvancedAttention.v1",
                "status": "ready",
                **operations.attention(now=now),
            }

    def daily_rhythm(
        self, *, cadence: str = "auto", now: float | None = None
    ) -> dict[str, object]:
        """Project today's focus without mutating goals or dispatching work."""

        try:
            selected = RhythmCadenceV1(cadence).value
        except (TypeError, ValueError) as exc:
            raise AdvancedOperationsControllerDenied(
                "rhythm cadence is invalid"
            ) from exc
        with self._lock:
            operations = self._bind_current()
            if operations is None:
                return {
                    "contract": "OnyxOperationalRhythm.v1",
                    "status": "waiting_for_live_session",
                    "cadence": selected,
                    "focus": (),
                    "actions": (),
                    "warnings": (),
                    "read_only": True,
                    "external_dispatch": False,
                    "goal_mutations": 0,
                    "background_workers": 0,
                    "polling_interval": None,
                }
            return operations.daily_rhythm(cadence=selected, now=now)

    def enable_native_workspace_events(self) -> dict[str, object]:
        """Bind native workspace notifications on the trusted Qt host thread."""

        with self._lock:
            operations = self._bind_current()
            if operations is None:
                raise AdvancedOperationsControllerDenied(
                    "live Phase 6 session is unavailable"
                )
            status = operations.enable_native_workspace_events().status()
            return {
                "contract": "OnyxNativeWorkspaceEvents.v1",
                "status": "active" if status.active else "closed",
                "watched_paths": status.watched_paths,
                "background_workers": status.background_workers,
                "polling_interval": status.polling_interval,
            }

    def preference_prompt_projection(self) -> str:
        """Return only owner-approved style preferences for the next session."""

        with self._lock:
            operations = self._bind_current()
            if operations is None:
                return ""
            return operations.preferences.prompt_projection(
                operations.identity.owner_profile_id,
                operations.identity.workspace_id,
            )

    @staticmethod
    def _goal_payload(goal: OperationalGoalV1) -> dict[str, object]:
        return {
            "goal_id": goal.goal_id,
            "parent_id": goal.parent_id,
            "level": goal.level.value,
            "title": goal.title,
            "objective": goal.objective,
            "definition_of_done": list(goal.definition_of_done),
            "status": goal.status.value,
            "target_at": goal.target_at,
            "plan_id": goal.plan_id,
            "mission_id": goal.mission_id,
            "verification_digest": goal.verification_digest,
            "revision": goal.revision,
        }

    @staticmethod
    def _rule_payload(rule: AutomationRuleV1) -> dict[str, object]:
        return {
            "rule_id": rule.rule_id,
            "event_type": rule.event_type,
            "metadata_filter": dict(rule.metadata_filter),
            "plan_id": rule.plan_id,
            "mission_id": rule.mission_id,
            "goal_id": rule.goal_id,
            "expires_at": rule.expires_at,
            "max_uses": rule.max_uses,
            "use_count": rule.use_count,
            "enabled": rule.enabled,
            "revision": rule.revision,
        }

    @staticmethod
    def _site_payload(project: SiteProjectV1) -> dict[str, object]:
        return {
            "project_id": project.project_id,
            "repository_id": project.repository_id,
            "stage": project.stage.value,
            "revision": project.revision,
            "verification_digest": project.verification_digest,
        }

    @staticmethod
    def _site_binding_payload(binding: SiteOperationBindingV1) -> dict[str, object]:
        return {
            "binding_id": binding.binding_id,
            "project_id": binding.project_id,
            "operation": binding.operation.value,
            "plan_id": binding.plan_id,
            "mission_id": binding.mission_id,
            "required_postconditions": list(binding.required_postconditions),
            "status": binding.status,
            "verification_digest": binding.verification_digest,
        }

    @staticmethod
    def _workflow_payload(workflow: WorkflowProjectionV1) -> dict[str, object]:
        binding = workflow.binding
        return {
            "workflow_id": workflow.workflow_id,
            "name": workflow.name,
            "description": workflow.description,
            "status": workflow.status.value,
            "revision": workflow.revision,
            "graph": workflow.graph.payload(),
            "binding": None
            if binding is None
            else {
                "node_id": binding.node_id,
                "plan_id": binding.plan_id,
                "mission_id": binding.mission_id,
                "rule_id": binding.rule_id,
                "required_postconditions": binding.required_postconditions,
                "status": binding.status,
                "verification_digest": binding.verification_digest,
            },
        }

    @staticmethod
    def _preference_suggestion_payload(
        suggestion: PreferenceSuggestionV1,
    ) -> dict[str, object]:
        return {
            "suggestion_id": suggestion.suggestion_id,
            "key": suggestion.key.value,
            "suggested_value": suggestion.suggested_value,
            "confidence": suggestion.confidence,
            "evidence_count": suggestion.evidence_count,
            "status": suggestion.status,
            "revision": suggestion.revision,
        }

    @staticmethod
    def _active_preference_payload(
        preference: ActivePreferenceV1 | None,
    ) -> dict[str, object] | None:
        if preference is None:
            return None
        return {
            "key": preference.key.value,
            "value": preference.value,
            "source_suggestion_id": preference.source_suggestion_id,
            "revision": preference.revision,
        }

    @staticmethod
    def _device_payload(device: EnrolledDeviceV1) -> dict[str, object]:
        return {
            "device_id": device.device_id,
            "issuer": device.issuer,
            "enabled": device.enabled,
            "credential_backend": "native_vault",
        }

    def execute(self, arguments: Mapping[str, object]) -> dict[str, object]:
        """Execute one local metadata operation without external dispatch.

        Identity and workspace scope always come from the bound Phase 6 session;
        model arguments cannot select either authority. Goal completion remains
        evidence-only through ``reconcile_verified``.
        """

        if not isinstance(arguments, Mapping):
            raise AdvancedOperationsControllerDenied("arguments must be a mapping")
        action_value = arguments.get("action")
        if type(action_value) is not str:
            raise AdvancedOperationsControllerDenied("an exact action is required")
        action = action_value.strip().lower().replace("-", "_").replace(" ", "_")
        if action == "status":
            return self.status()
        if action == "attention":
            return self.attention()
        if action == "daily_rhythm":
            cadence = arguments.get("cadence", "auto")
            if type(cadence) is not str:
                raise AdvancedOperationsControllerDenied("rhythm cadence is invalid")
            return self.daily_rhythm(cadence=cadence)
        supported_goal_actions = {
            "create_goal",
            "get_goal",
            "activate_goal",
            "pause_goal",
            "cancel_goal",
            "reconcile_goal",
        }
        supported_rule_actions = {"create_automation_rule", "get_automation_rule"}
        supported_site_actions = {
            "create_site_project",
            "get_site_project",
            "bind_site_operation",
            "reconcile_site_operation",
        }
        supported_workflow_actions = {
            "create_workflow",
            "get_workflow",
            "bind_workflow_plan",
            "activate_workflow",
            "pause_workflow",
            "cancel_workflow",
            "reconcile_workflow",
        }
        supported_preference_actions = {
            "suggest_preference",
            "get_preference_suggestion",
            "promote_preference",
            "reject_preference",
            "rollback_preference",
            "get_active_preference",
        }
        supported_device_actions = {
            "enroll_device",
            "get_device",
            "enable_device",
            "disable_device",
        }
        if action not in (
            supported_goal_actions
            | supported_rule_actions
            | supported_site_actions
            | supported_workflow_actions
            | supported_preference_actions
            | supported_device_actions
        ):
            raise AdvancedOperationsControllerDenied(
                "advanced operations action is unsupported"
            )
        with self._lock:
            operations = self._bind_current()
            if operations is None:
                return {
                    "contract": "OnyxAdvancedOperationsCommand.v1",
                    "status": "waiting_for_live_session",
                    "action": action,
                }
            goals = operations.goals
            if action in supported_device_actions:
                if operations.mesh_registry is None:
                    raise AdvancedOperationsControllerDenied(
                        "device mesh is disabled because its ledger authentication key is unavailable"
                    )
                device_id = arguments.get("device_id")
                if type(device_id) is not str:
                    raise AdvancedOperationsControllerDenied("device_id is required")
                if action == "enroll_device":
                    issuer = arguments.get("device_issuer")
                    if type(issuer) is not str:
                        raise AdvancedOperationsControllerDenied(
                            "device_issuer is required"
                        )
                    owner = operations.identity.owner_profile_id
                    workspace = operations.identity.workspace_id
                    decision_digest = hashlib.sha256(
                        f"enroll-device:{owner}:{workspace}:{device_id}:{issuer}".encode()
                    ).hexdigest()
                    if (
                        self._owner_authority(
                            owner, workspace, device_id, decision_digest
                        )
                        is not True
                    ):
                        raise AdvancedOperationsControllerDenied(
                            "owner authority denied device enrollment"
                        )
                    reference = SecretReference(
                        "Onyx.DeviceMesh.v1",
                        device_id,
                        f"Onyx device {device_id}",
                    )
                    vault = NativeSecretVault(reference)
                    if vault.get_bytes() is not None:
                        raise AdvancedOperationsControllerDenied(
                            "device credential already exists"
                        )
                    vault.set_bytes(os.urandom(32))
                    try:
                        device = EnrolledDeviceV1(
                            device_id=device_id,
                            owner_profile_id=owner,
                            workspace_id=workspace,
                            issuer=issuer,
                            secret_reference=reference,
                            enabled=True,
                        )
                        operations.mesh_registry.enroll(device)
                    except BaseException:
                        vault.delete()
                        raise
                else:
                    device = operations.mesh_registry.device(device_id)
                    self._require_device_scope(operations, device)
                    if action == "enable_device":
                        device = operations.mesh_registry.set_enabled(device_id, True)
                    elif action == "disable_device":
                        device = operations.mesh_registry.set_enabled(device_id, False)
                return {
                    "contract": "OnyxAdvancedOperationsCommand.v1",
                    "status": "completed",
                    "action": action,
                    "device": self._device_payload(device),
                    "external_dispatch": False,
                }
            if action in supported_preference_actions:
                suggestion: PreferenceSuggestionV1 | None = None
                active: ActivePreferenceV1 | None = None
                if action == "suggest_preference":
                    key_value = arguments.get("preference_key")
                    value = arguments.get("preference_value")
                    evidence_value = arguments.get("preference_evidence")
                    if type(key_value) is not str or type(value) is not str:
                        raise AdvancedOperationsControllerDenied(
                            "preference_key and preference_value are required"
                        )
                    if type(evidence_value) is not list:
                        raise AdvancedOperationsControllerDenied(
                            "preference_evidence must be an exact object list"
                        )
                    try:
                        key = PreferenceKeyV1(key_value)
                        evidence = tuple(
                            PreferenceEvidenceV1(
                                evidence_id=item["evidence_id"],
                                source_type=item["source_type"],
                                source_reference=item["source_reference"],
                                observation_digest=item["observation_digest"],
                                occurred_at=item["occurred_at"],
                            )
                            for item in evidence_value
                            if type(item) is dict
                            and set(item)
                            == {
                                "evidence_id",
                                "source_type",
                                "source_reference",
                                "observation_digest",
                                "occurred_at",
                            }
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        raise AdvancedOperationsControllerDenied(
                            "preference evidence is invalid"
                        ) from exc
                    if len(evidence) != len(evidence_value):
                        raise AdvancedOperationsControllerDenied(
                            "preference evidence is invalid"
                        )
                    suggestion = operations.preferences.suggest(
                        owner_profile_id=operations.identity.owner_profile_id,
                        workspace_id=operations.identity.workspace_id,
                        key=key,
                        value=value,
                        evidence=evidence,
                    )
                elif action in {
                    "get_preference_suggestion",
                    "promote_preference",
                    "reject_preference",
                }:
                    suggestion_id = arguments.get("suggestion_id")
                    if type(suggestion_id) is not str:
                        raise AdvancedOperationsControllerDenied(
                            "suggestion_id is required"
                        )
                    suggestion = operations.preferences.get_suggestion(suggestion_id)
                    self._require_preference_scope(operations, suggestion)
                    if action == "promote_preference":
                        active = operations.preferences.promote(suggestion_id)
                        suggestion = operations.preferences.get_suggestion(
                            suggestion_id
                        )
                    elif action == "reject_preference":
                        suggestion = operations.preferences.reject(suggestion_id)
                else:
                    key_value = arguments.get("preference_key")
                    if type(key_value) is not str:
                        raise AdvancedOperationsControllerDenied(
                            "preference_key is required"
                        )
                    try:
                        key = PreferenceKeyV1(key_value)
                    except ValueError as exc:
                        raise AdvancedOperationsControllerDenied(
                            "preference_key is invalid"
                        ) from exc
                    if action == "rollback_preference":
                        active = operations.preferences.rollback(
                            operations.identity.owner_profile_id,
                            operations.identity.workspace_id,
                            key,
                        )
                    else:
                        active = operations.preferences.active(
                            operations.identity.owner_profile_id,
                            operations.identity.workspace_id,
                            key,
                        )
                response: dict[str, object] = {
                    "contract": "OnyxAdvancedOperationsCommand.v1",
                    "status": "completed",
                    "action": action,
                    "external_dispatch": False,
                }
                if suggestion is not None:
                    response["preference_suggestion"] = (
                        self._preference_suggestion_payload(suggestion)
                    )
                if action in {
                    "promote_preference",
                    "rollback_preference",
                    "get_active_preference",
                }:
                    response["active_preference"] = self._active_preference_payload(
                        active
                    )
                if action in {"promote_preference", "rollback_preference"}:
                    response["applies_on_next_live_session"] = True
                return response
            if action in supported_workflow_actions:
                if action == "create_workflow":
                    nodes = arguments.get("workflow_nodes")
                    edges = arguments.get("workflow_edges")
                    if (
                        type(nodes) is not list
                        or any(type(item) is not dict for item in nodes)
                        or type(edges) is not list
                        or any(type(item) is not dict for item in edges)
                    ):
                        raise AdvancedOperationsControllerDenied(
                            "workflow_nodes and workflow_edges must be exact object lists"
                        )
                    workflow = operations.workflows.create(
                        owner_profile_id=operations.identity.owner_profile_id,
                        workspace_id=operations.identity.workspace_id,
                        name=arguments.get("workflow_name"),
                        description=arguments.get("workflow_description"),
                        nodes=nodes,
                        edges=edges,
                    )
                else:
                    workflow_id = arguments.get("workflow_id")
                    if type(workflow_id) is not str:
                        raise AdvancedOperationsControllerDenied(
                            "workflow_id is required"
                        )
                    workflow = operations.workflows.get(workflow_id)
                    self._require_workflow_scope(operations, workflow)
                    if action == "bind_workflow_plan":
                        plan_id = arguments.get("plan_id")
                        mission_id = arguments.get("mission_id")
                        required = arguments.get("required_postconditions")
                        if type(plan_id) is not str or type(mission_id) is not str:
                            raise AdvancedOperationsControllerDenied(
                                "plan_id and mission_id are required"
                            )
                        if (
                            type(required) is not list
                            or not required
                            or any(type(item) is not str for item in required)
                        ):
                            raise AdvancedOperationsControllerDenied(
                                "required_postconditions must be an exact text list"
                            )
                        try:
                            projection = operations.state.get_projection(plan_id)
                            plan = operations.state.get_plan(plan_id)
                            mission = operations.missions.get(mission_id)
                        except (KeyError, MissionError) as exc:
                            raise AdvancedOperationsControllerDenied(
                                "workflow Phase 6 authority is invalid"
                            ) from exc
                        if (
                            projection.mission_id != mission.id
                            or plan.goal.workspace_id
                            != operations.identity.workspace_id
                            or projection.state
                            not in {
                                PlanStateV1.AWAITING_APPROVAL,
                                PlanStateV1.RUNNING,
                                PlanStateV1.PAUSED,
                            }
                            or mission.state not in {"running", "paused"}
                        ):
                            raise AdvancedOperationsControllerDenied(
                                "workflow Phase 6 authority diverges"
                            )
                        workflow = operations.workflows.bind_plan(
                            workflow_id,
                            plan_id=plan_id,
                            mission_id=mission_id,
                            required_postconditions=required,
                            rule_id=self._create_workflow_rule(
                                operations,
                                workflow,
                                plan_id=plan_id,
                                mission_id=mission_id,
                                arguments=arguments,
                            ).rule_id,
                        )
                    elif action == "activate_workflow":
                        workflow = self._set_workflow_active(
                            operations, workflow, active=True
                        )
                    elif action == "pause_workflow":
                        workflow = self._set_workflow_active(
                            operations, workflow, active=False
                        )
                    elif action == "cancel_workflow":
                        workflow = self._set_workflow_active(
                            operations, workflow, active=False, cancel=True
                        )
                    elif action == "reconcile_workflow":
                        workflow = operations.workflows.reconcile_verified(
                            workflow_id,
                            state_store=operations.state,
                            mission_store=operations.missions,
                        )
                        if workflow.binding is not None and workflow.binding.rule_id:
                            operations.rules.set_enabled(
                                workflow.binding.rule_id, False
                            )
                return {
                    "contract": "OnyxAdvancedOperationsCommand.v1",
                    "status": "completed",
                    "action": action,
                    "workflow": self._workflow_payload(workflow),
                    "external_dispatch": False,
                }
            if action in supported_rule_actions:
                if action == "create_automation_rule":
                    metadata_filter = arguments.get("metadata_filter", {})
                    if type(metadata_filter) is not dict:
                        raise AdvancedOperationsControllerDenied(
                            "metadata_filter must be an exact object"
                        )
                    plan_id = arguments.get("plan_id")
                    mission_id = arguments.get("mission_id")
                    event_type = arguments.get("event_type")
                    expires_at = arguments.get("expires_at")
                    max_uses = arguments.get("max_uses", 1)
                    goal_id = arguments.get("goal_id")
                    if any(
                        type(value) is not str
                        for value in (plan_id, mission_id, event_type)
                    ):
                        raise AdvancedOperationsControllerDenied(
                            "event_type, plan_id and mission_id are required"
                        )
                    if isinstance(expires_at, bool) or not isinstance(
                        expires_at, (int, float)
                    ):
                        raise AdvancedOperationsControllerDenied(
                            "expires_at is required"
                        )
                    if isinstance(max_uses, bool) or type(max_uses) is not int:
                        raise AdvancedOperationsControllerDenied("max_uses is invalid")
                    if goal_id is not None and type(goal_id) is not str:
                        raise AdvancedOperationsControllerDenied("goal_id is invalid")
                    try:
                        plan = operations.state.get_projection(plan_id)
                        mission = operations.missions.get(mission_id)
                    except (KeyError, MissionError) as exc:
                        raise AdvancedOperationsControllerDenied(
                            "automation authority is invalid"
                        ) from exc
                    if plan.mission_id != mission.id:
                        raise AdvancedOperationsControllerDenied(
                            "automation mission diverges from its plan"
                        )
                    rule = operations.rules.create_rule(
                        core=operations.core,
                        owner_profile_id=operations.identity.owner_profile_id,
                        workspace_id=operations.identity.workspace_id,
                        event_type=event_type,
                        metadata_filter=metadata_filter,
                        plan_id=plan_id,
                        mission_id=mission_id,
                        expires_at=float(expires_at),
                        max_uses=max_uses,
                        goal_id=goal_id,
                    )
                else:
                    rule_id = arguments.get("rule_id")
                    if type(rule_id) is not str:
                        raise AdvancedOperationsControllerDenied("rule_id is required")
                    rule = operations.rules.get_rule(rule_id)
                    if (
                        rule.owner_profile_id != operations.identity.owner_profile_id
                        or rule.workspace_id != operations.identity.workspace_id
                    ):
                        raise AdvancedOperationsControllerDenied(
                            "automation rule scope diverged"
                        )
                return {
                    "contract": "OnyxAdvancedOperationsCommand.v1",
                    "status": "completed",
                    "action": action,
                    "automation_rule": self._rule_payload(rule),
                    "external_dispatch": False,
                }
            if action in supported_site_actions:
                project: SiteProjectV1
                binding: SiteOperationBindingV1 | None = None
                if action == "create_site_project":
                    repository_id = arguments.get("repository_id")
                    root = arguments.get("root")
                    if type(repository_id) is not str or type(root) is not str:
                        raise AdvancedOperationsControllerDenied(
                            "repository_id and root are required"
                        )
                    project = operations.sites.create(
                        owner_profile_id=operations.identity.owner_profile_id,
                        workspace_id=operations.identity.workspace_id,
                        repository_id=repository_id,
                        root=root,
                    )
                elif action == "reconcile_site_operation":
                    binding_id = arguments.get("binding_id")
                    if type(binding_id) is not str:
                        raise AdvancedOperationsControllerDenied(
                            "binding_id is required"
                        )
                    binding = operations.sites.get_binding(binding_id)
                    project = operations.sites.get(binding.project_id)
                    self._require_site_scope(operations, project)
                    project = operations.sites.reconcile_verified(
                        binding_id,
                        state_store=operations.state,
                        mission_store=operations.missions,
                    )
                else:
                    project_id = arguments.get("project_id")
                    if type(project_id) is not str:
                        raise AdvancedOperationsControllerDenied(
                            "project_id is required"
                        )
                    project = operations.sites.get(project_id)
                    self._require_site_scope(operations, project)
                    if action == "bind_site_operation":
                        operation = arguments.get("operation")
                        plan_id = arguments.get("plan_id")
                        mission_id = arguments.get("mission_id")
                        required = arguments.get("required_postconditions")
                        if any(
                            type(value) is not str
                            for value in (operation, plan_id, mission_id)
                        ):
                            raise AdvancedOperationsControllerDenied(
                                "operation, plan_id and mission_id are required"
                            )
                        if required is not None and (
                            type(required) is not list
                            or any(type(item) is not str for item in required)
                        ):
                            raise AdvancedOperationsControllerDenied(
                                "required_postconditions must be an exact text list"
                            )
                        try:
                            selected_operation = SiteOperationV1(operation)
                            plan = operations.state.get_projection(plan_id)
                            mission = operations.missions.get(mission_id)
                        except (ValueError, KeyError, MissionError) as exc:
                            raise AdvancedOperationsControllerDenied(
                                "site operation authority is invalid"
                            ) from exc
                        if plan.mission_id != mission.id:
                            raise AdvancedOperationsControllerDenied(
                                "site operation mission diverges from its plan"
                            )
                        binding = operations.sites.bind_operation(
                            project_id,
                            operation=selected_operation,
                            plan_id=plan_id,
                            mission_id=mission_id,
                            required_postconditions=required,
                        )
                response = {
                    "contract": "OnyxAdvancedOperationsCommand.v1",
                    "status": "completed",
                    "action": action,
                    "site_project": self._site_payload(project),
                    "external_dispatch": False,
                }
                if binding is not None:
                    response["site_binding"] = self._site_binding_payload(binding)
                return response
            goal: OperationalGoalV1
            if action == "create_goal":
                raw_level = arguments.get("level", "objective")
                if type(raw_level) is not str:
                    raise AdvancedOperationsControllerDenied("goal level is invalid")
                try:
                    level = GoalLevelV1(raw_level.strip().lower())
                except ValueError as exc:
                    raise AdvancedOperationsControllerDenied(
                        "goal level is invalid"
                    ) from exc
                raw_conditions = arguments.get("definition_of_done")
                if type(raw_conditions) is not list or any(
                    type(item) is not str for item in raw_conditions
                ):
                    raise AdvancedOperationsControllerDenied(
                        "definition_of_done must be an exact text list"
                    )
                parent_id = arguments.get("parent_id")
                if parent_id is not None and type(parent_id) is not str:
                    raise AdvancedOperationsControllerDenied("parent_id is invalid")
                target_at = arguments.get("target_at")
                if target_at is not None and (
                    isinstance(target_at, bool)
                    or not isinstance(target_at, (int, float))
                ):
                    raise AdvancedOperationsControllerDenied("target_at is invalid")
                goal = goals.create(
                    owner_profile_id=operations.identity.owner_profile_id,
                    workspace_id=operations.identity.workspace_id,
                    level=level,
                    title=arguments.get("title"),
                    objective=arguments.get("objective"),
                    definition_of_done=raw_conditions,
                    parent_id=parent_id,
                    target_at=float(target_at) if target_at is not None else None,
                )
            else:
                goal_id = arguments.get("goal_id")
                if type(goal_id) is not str:
                    raise AdvancedOperationsControllerDenied("goal_id is required")
                if action == "get_goal":
                    goal = goals.get(goal_id)
                elif action == "activate_goal":
                    goal = goals.activate(goal_id, "owner_voice_activated")
                elif action == "pause_goal":
                    goal = goals.pause(goal_id, "owner_voice_paused")
                elif action == "cancel_goal":
                    goal = goals.cancel(goal_id, "owner_voice_cancelled")
                elif action == "reconcile_goal":
                    goal = goals.reconcile_verified(
                        goal_id,
                        state_store=operations.state,
                        mission_store=operations.missions,
                    )
            return {
                "contract": "OnyxAdvancedOperationsCommand.v1",
                "status": "completed",
                "action": action,
                "goal": self._goal_payload(goal),
                "external_dispatch": False,
            }

    @staticmethod
    def _require_site_scope(
        operations: AdvancedOperationsSessionV1, project: SiteProjectV1
    ) -> None:
        if (
            project.owner_profile_id != operations.identity.owner_profile_id
            or project.workspace_id != operations.identity.workspace_id
        ):
            raise AdvancedOperationsControllerDenied("site project scope diverged")

    @staticmethod
    def _require_workflow_scope(
        operations: AdvancedOperationsSessionV1,
        workflow: WorkflowProjectionV1,
    ) -> None:
        if (
            workflow.owner_profile_id != operations.identity.owner_profile_id
            or workflow.workspace_id != operations.identity.workspace_id
        ):
            raise AdvancedOperationsControllerDenied("workflow scope diverged")

    @staticmethod
    def _create_workflow_rule(
        operations: AdvancedOperationsSessionV1,
        workflow: WorkflowProjectionV1,
        *,
        plan_id: str,
        mission_id: str,
        arguments: Mapping[str, object],
    ) -> AutomationRuleV1:
        trigger = next(
            node for node in workflow.graph.nodes if node.kind.value == "trigger"
        )
        filters = {
            str(node.config_dict()["field"]): node.config_dict()["equals"]
            for node in workflow.graph.nodes
            if node.kind.value == "condition"
        }
        supplied_filter = arguments.get("metadata_filter", {})
        if type(supplied_filter) is not dict:
            raise AdvancedOperationsControllerDenied(
                "metadata_filter must be an exact object"
            )
        if supplied_filter and supplied_filter != filters:
            raise AdvancedOperationsControllerDenied(
                "workflow metadata_filter diverges from condition nodes"
            )
        expires_at = arguments.get("expires_at", time.time() + 365 * 86_400)
        max_uses = arguments.get("max_uses", 10_000)
        if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
            raise AdvancedOperationsControllerDenied("workflow expires_at is invalid")
        if type(max_uses) is not int:
            raise AdvancedOperationsControllerDenied("workflow max_uses is invalid")
        return operations.rules.create_rule(
            core=operations.core,
            owner_profile_id=operations.identity.owner_profile_id,
            workspace_id=operations.identity.workspace_id,
            event_type=str(trigger.config_dict()["event_type"]),
            metadata_filter=filters,
            plan_id=plan_id,
            mission_id=mission_id,
            expires_at=float(expires_at),
            max_uses=max_uses,
            enabled=False,
        )

    @staticmethod
    def _set_workflow_active(
        operations: AdvancedOperationsSessionV1,
        workflow: WorkflowProjectionV1,
        *,
        active: bool,
        cancel: bool = False,
    ) -> WorkflowProjectionV1:
        binding = workflow.binding
        if binding is None or binding.rule_id is None:
            raise AdvancedOperationsControllerDenied(
                "workflow has no governed automation binding"
            )
        operations.rules.set_enabled(binding.rule_id, active)
        try:
            if cancel:
                return operations.workflows.cancel(workflow.workflow_id)
            if active:
                return operations.workflows.activate(workflow.workflow_id)
            return operations.workflows.pause(workflow.workflow_id)
        except BaseException:
            operations.rules.set_enabled(binding.rule_id, not active)
            raise

    @staticmethod
    def _require_preference_scope(
        operations: AdvancedOperationsSessionV1,
        suggestion: PreferenceSuggestionV1,
    ) -> None:
        if (
            suggestion.owner_profile_id != operations.identity.owner_profile_id
            or suggestion.workspace_id != operations.identity.workspace_id
        ):
            raise AdvancedOperationsControllerDenied("preference scope diverged")

    @staticmethod
    def _require_device_scope(
        operations: AdvancedOperationsSessionV1,
        device: EnrolledDeviceV1,
    ) -> None:
        if (
            device.owner_profile_id != operations.identity.owner_profile_id
            or device.workspace_id != operations.identity.workspace_id
        ):
            raise AdvancedOperationsControllerDenied("device scope diverged")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._detach()
            self._closed = True


__all__ = [
    "HOST_CONTROLLER",
    "AdvancedOperationsControllerDenied",
    "AdvancedOperationsControllerError",
    "AdvancedOperationsControllerV1",
]
