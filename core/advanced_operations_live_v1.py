"""One live-session composition root for the clean-room operational blocks.

The composition reuses the exact live Agentic Core V6 and MissionStore.  It
creates projections and event queues only; it owns no executor, provider,
listener, polling worker, shell, permission broker or UI shell.
"""

from __future__ import annotations

import os
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from core.automation_adapters_v1 import (
    AutomationAdapterFeatureGateV1,
    AutomationAdapterStateV1,
)
from core.context_graph_v1 import ContextGraphFeatureGateV1, ContextGraphStoreV1
from core.device_mesh_v1 import DeviceMeshFeatureGateV1, DeviceMeshRegistryV1
from core.event_awareness_v1 import AwarenessPolicyV1, EventDrivenAwarenessV1
from core.governed_automation_v1 import (
    AutomationRuleStoreV1,
    EventDrivenAutomationRuntimeV1,
    GovernedAutomationFeatureGateV1,
)
from core.missions import MissionStore
from core.native_workspace_events_v1 import (
    NativeWorkspaceEventFeatureGateV1,
    NativeWorkspaceEventPublisherV1,
    create_qt_native_workspace_event_publisher_v1,
)
from core.operational_goals_v1 import (
    OperationalGoalFeatureGateV1,
    OperationalGoalStoreV1,
)
from core.operational_rhythm_v1 import OperationalRhythmV1, RhythmCadenceV1
from core.personality_preferences_v1 import (
    PersonalityPreferenceFeatureGateV1,
    PersonalityPreferenceStoreV1,
)
from core.phase6_agentic_core_v6 import AgenticCoreV6, AgenticStateStoreV6
from core.site_projects_v1 import SiteProjectFeatureGateV1, SiteProjectStoreV1
from core.workflow_graph_v1 import WorkflowFeatureGateV1, WorkflowGraphStoreV1


FEATURE_FLAG = "ONYX_ADVANCED_OPERATIONS_LIVE_V1"
SESSION_ATTRIBUTE = "_advanced_operations_live_v1_session"
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_CONSTRUCTION_KEY = object()


class AdvancedOperationsLiveError(RuntimeError):
    pass


class AdvancedOperationsLiveContractError(ValueError):
    pass


class AdvancedOperationsLiveDenied(PermissionError):
    pass


def _state_root(value: Path | str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise AdvancedOperationsLiveContractError(
            "an explicit absolute state root is required"
        )
    absolute = path.absolute()
    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        raise AdvancedOperationsLiveContractError(
            "state root cannot be resolved"
        ) from exc
    if resolved != absolute:
        raise AdvancedOperationsLiveDenied("state root uses a link or alias")
    cursor = path
    while not cursor.exists():
        parent = cursor.parent
        if parent == cursor:
            raise AdvancedOperationsLiveDenied("state root has no existing ancestor")
        cursor = parent
    try:
        while True:
            info = cursor.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
            ):
                raise AdvancedOperationsLiveDenied("state root ancestry uses a link")
            if cursor.parent == cursor:
                break
            cursor = cursor.parent
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if (
            not path.is_dir()
            or path.is_symlink()
            or path.resolve(strict=True) != absolute
        ):
            raise AdvancedOperationsLiveDenied(
                "state root is not a private real directory"
            )
    except OSError as exc:
        raise AdvancedOperationsLiveDenied("state root authentication failed") from exc
    return absolute


def _roots(values: Sequence[Path | str]) -> tuple[Path, ...]:
    if type(values) not in {tuple, list} or not values:
        raise AdvancedOperationsLiveContractError("controlled roots are required")
    result: list[Path] = []
    for value in values:
        root = Path(value)
        if not root.is_absolute() or root.is_symlink():
            raise AdvancedOperationsLiveDenied(
                "controlled root must be real and absolute"
            )
        try:
            resolved = root.resolve(strict=True)
        except OSError as exc:
            raise AdvancedOperationsLiveDenied(
                "controlled root is unavailable"
            ) from exc
        if not resolved.is_dir():
            raise AdvancedOperationsLiveDenied("controlled root must be a directory")
        result.append(resolved)
    if len(set(result)) != len(result):
        raise AdvancedOperationsLiveContractError("controlled roots are not canonical")
    return tuple(result)


@dataclass(frozen=True)
class AdvancedOperationsLiveFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise AdvancedOperationsLiveContractError(
                "enabled must be an exact boolean"
            )

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "AdvancedOperationsLiveFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True)
class AdvancedOperationsIdentityV1:
    owner_profile_id: str
    workspace_id: str

    def __post_init__(self) -> None:
        # Reuse the exact identifiers accepted by the existing stores without
        # exporting their private validators.
        if not isinstance(self.owner_profile_id, str) or not isinstance(
            self.workspace_id, str
        ):
            raise AdvancedOperationsLiveContractError("identity fields are invalid")


class AdvancedOperationsSessionV1:
    """All default-off operational projections bound to one live Phase 6 core."""

    def __init__(
        self,
        *,
        _key: object,
        identity: AdvancedOperationsIdentityV1,
        core: AgenticCoreV6,
        state: AgenticStateStoreV6,
        missions: MissionStore,
        root: Path,
        controlled_roots: tuple[Path, ...],
        owner_authority: Callable[[str, str, str, str], bool],
        device_mesh_ledger_auth_key: bytes | bytearray | None,
    ) -> None:
        if _key is not _CONSTRUCTION_KEY:
            raise AdvancedOperationsLiveDenied("use the advanced operations factory")
        if (
            type(identity) is not AdvancedOperationsIdentityV1
            or type(core) is not AgenticCoreV6
            or type(state) is not AgenticStateStoreV6
            or getattr(core, "_state", None) is not state
            or getattr(core, "_missions", None) is not missions
            or type(missions) is not MissionStore
            or core.closed
            or not callable(owner_authority)
        ):
            raise AdvancedOperationsLiveContractError(
                "exact live authorities are required"
            )
        if device_mesh_ledger_auth_key is not None and (
            not isinstance(device_mesh_ledger_auth_key, (bytes, bytearray))
            or len(device_mesh_ledger_auth_key) != 32
        ):
            raise AdvancedOperationsLiveContractError(
                "device mesh ledger authentication key must be exactly 32 bytes"
            )
        workspace_scope = getattr(core, "_workspace", None)
        if (
            workspace_scope is None
            or getattr(workspace_scope, "workspace_id", None) != identity.workspace_id
            or tuple(Path(item).resolve() for item in workspace_scope.allowed_roots)
            != controlled_roots
        ):
            raise AdvancedOperationsLiveDenied("Phase 6 workspace authority diverged")
        self.identity = identity
        self.core = core
        self.state = state
        self.missions = missions
        self.root = root
        self.goals = OperationalGoalStoreV1(
            root / "operational-goals-v1.sqlite3", OperationalGoalFeatureGateV1(True)
        )
        self.rhythm = OperationalRhythmV1(self.goals)
        self.rules = AutomationRuleStoreV1(
            root / "governed-automation-v1.sqlite3",
            GovernedAutomationFeatureGateV1(True),
        )
        self.automation = EventDrivenAutomationRuntimeV1(
            core=core, rules=self.rules, goal_store=self.goals
        )
        self.context_graph = ContextGraphStoreV1(
            root / "context-graph-v1.sqlite3", ContextGraphFeatureGateV1(True)
        )
        self.awareness = EventDrivenAwarenessV1(
            AwarenessPolicyV1(
                allowed_sources=(
                    "native_foreground_events",
                    "native_workspace_events",
                    "native_calendar_events",
                    "native_mail_events",
                    "native_connectivity_events",
                    "native_owner_activity",
                    "native_mission_events",
                )
            ),
            goal_store=self.goals,
            context_graph=self.context_graph,
        )
        self.mesh_registry: DeviceMeshRegistryV1 | None = None
        if device_mesh_ledger_auth_key is not None:
            self.mesh_registry = DeviceMeshRegistryV1(
                root / "device-mesh-v1.sqlite3",
                DeviceMeshFeatureGateV1(True),
                ledger_auth_key=device_mesh_ledger_auth_key,
            )
        self.preferences = PersonalityPreferenceStoreV1(
            root / "personality-preferences-v1.sqlite3",
            PersonalityPreferenceFeatureGateV1(True),
            owner_authority=owner_authority,
        )
        self.sites = SiteProjectStoreV1(
            root / "site-projects-v1.sqlite3",
            SiteProjectFeatureGateV1(True),
            controlled_roots=controlled_roots,
        )
        self.workflows = WorkflowGraphStoreV1(
            root / "workflow-graphs-v1.sqlite3", WorkflowFeatureGateV1(True)
        )
        self.adapters = AutomationAdapterStateV1(
            root / "automation-adapters-v1.sqlite3",
            AutomationAdapterFeatureGateV1(True),
        )
        self._controlled_roots = controlled_roots
        self.native_workspace_events: NativeWorkspaceEventPublisherV1 | None = None
        self.background_workers = 0
        self.polling_interval = None
        self._closed = False
        self._lock = threading.RLock()

    @property
    def closed(self) -> bool:
        return self._closed

    def status(self) -> dict[str, object]:
        with self._lock:
            owner = self.identity.owner_profile_id
            workspace = self.identity.workspace_id
            context = self.context_graph.projection(owner, workspace)
            workflows = self.workflows.list_scope(owner, workspace)
            return {
                "contract": "OnyxAdvancedOperationsLive.v1",
                "status": "closed" if self._closed else "ready",
                "owner_profile_id": self.identity.owner_profile_id,
                "workspace_id": self.identity.workspace_id,
                "phase6_reused": getattr(self.core, "_state", None) is self.state,
                "mission_store_reused": getattr(self.core, "_missions", None)
                is self.missions,
                "background_workers": 0,
                "polling_interval": None,
                "automation_queued": self.automation.queued,
                "awareness_queued": self.awareness.queued,
                "automation_rules": self.rules.count_scope(owner, workspace),
                "enrolled_devices": (
                    self.mesh_registry.count_scope(owner, workspace)
                    if self.mesh_registry is not None
                    else 0
                ),
                "device_mesh_status": (
                    "ready"
                    if self.mesh_registry is not None
                    else "disabled_missing_ledger_key"
                ),
                "site_projects": self.sites.count_scope(owner, workspace),
                "workflow_graphs": self.workflows.count_scope(owner, workspace),
                "context_nodes": len(context.nodes),
                "context_edges": len(context.edges),
                "context_observations": context.observations,
                "workflow_summaries": tuple(
                    {
                        "name": item.name,
                        "status": item.status.value,
                        "node_kinds": tuple(
                            node.kind.value for node in item.graph.nodes
                        ),
                    }
                    for item in workflows
                ),
                "active_preferences": self.preferences.active_count(owner, workspace),
                "native_workspace_events": (
                    "active" if self.native_workspace_events is not None else "disabled"
                ),
                "capabilities": (
                    "operational_goals",
                    "operational_rhythm",
                    "governed_automation",
                    "event_awareness",
                    "durable_context_graph",
                    "personality_preferences",
                    "site_projects",
                    "workflow_graphs",
                    "automation_adapters",
                )
                + (("device_mesh_registry",) if self.mesh_registry is not None else ()),
            }

    def enable_native_workspace_events(self) -> NativeWorkspaceEventPublisherV1:
        """Bind explicit controlled roots to the host-owned Qt event loop once."""

        with self._lock:
            if self._closed:
                raise AdvancedOperationsLiveDenied(
                    "advanced operations session is closed"
                )
            if self.native_workspace_events is not None:
                return self.native_workspace_events
            publisher = create_qt_native_workspace_event_publisher_v1(
                gate=NativeWorkspaceEventFeatureGateV1(True),
                roots=self._controlled_roots,
                watched_paths=self._controlled_roots,
                owner_profile_id=self.identity.owner_profile_id,
                workspace_id=self.identity.workspace_id,
                automation=self.automation,
                awareness=self.awareness,
            )
            if type(publisher) is not NativeWorkspaceEventPublisherV1:
                raise AdvancedOperationsLiveContractError(
                    "native workspace publisher factory returned drift"
                )
            self.native_workspace_events = publisher
            return publisher

    def attention(self, *, now: float | None = None) -> dict[str, object]:
        if self._closed:
            raise AdvancedOperationsLiveDenied("advanced operations session is closed")
        projection = self.awareness.projection(
            owner_profile_id=self.identity.owner_profile_id,
            workspace_id=self.identity.workspace_id,
            now=now,
        )
        goals = self.goals.attention_queue(
            owner_profile_id=self.identity.owner_profile_id,
            workspace_id=self.identity.workspace_id,
            now=now,
        )
        rhythm = self.daily_rhythm(now=now)
        return {
            "active_application_id": projection.active_application_id,
            "active_project_id": projection.active_project_id,
            "recent_signal_count": projection.recent_signal_count,
            "attention": projection.attention,
            "goals": tuple(
                {
                    "goal_id": item.goal.goal_id,
                    "title": item.goal.title,
                    "level": item.goal.level.value,
                    "score": item.score,
                    "health": item.health,
                }
                for item in goals
            ),
            "rhythm": rhythm,
            "generated_at": projection.generated_at,
        }

    def daily_rhythm(
        self,
        *,
        cadence: RhythmCadenceV1 | str = RhythmCadenceV1.AUTO,
        now: float | None = None,
    ) -> dict[str, object]:
        if self._closed:
            raise AdvancedOperationsLiveDenied("advanced operations session is closed")
        return self.rhythm.project(
            owner_profile_id=self.identity.owner_profile_id,
            workspace_id=self.identity.workspace_id,
            cadence=cadence,
            now=now,
        ).payload()

    def close(self) -> None:
        with self._lock:
            publisher = self.native_workspace_events
            self.native_workspace_events = None
            if publisher is not None:
                publisher.close()
            self._closed = True


def create_advanced_operations_session_v1(
    *,
    gate: AdvancedOperationsLiveFeatureGateV1,
    owner_profile_id: str,
    workspace_id: str,
    core: AgenticCoreV6,
    state: AgenticStateStoreV6,
    missions: MissionStore,
    state_root: Path | str,
    controlled_roots: Sequence[Path | str],
    owner_authority: Callable[[str, str, str, str], bool],
    device_mesh_ledger_auth_key: bytes | bytearray | None = None,
) -> AdvancedOperationsSessionV1 | None:
    if type(gate) is not AdvancedOperationsLiveFeatureGateV1:
        raise AdvancedOperationsLiveContractError("exact feature gate is required")
    if not gate.enabled:
        return None
    root = _state_root(state_root)
    roots = _roots(controlled_roots)
    return AdvancedOperationsSessionV1(
        _key=_CONSTRUCTION_KEY,
        identity=AdvancedOperationsIdentityV1(owner_profile_id, workspace_id),
        core=core,
        state=state,
        missions=missions,
        root=root,
        controlled_roots=roots,
        owner_authority=owner_authority,
        device_mesh_ledger_auth_key=device_mesh_ledger_auth_key,
    )


__all__ = [
    "FEATURE_FLAG",
    "SESSION_ATTRIBUTE",
    "AdvancedOperationsIdentityV1",
    "AdvancedOperationsLiveContractError",
    "AdvancedOperationsLiveDenied",
    "AdvancedOperationsLiveError",
    "AdvancedOperationsLiveFeatureGateV1",
    "AdvancedOperationsSessionV1",
    "create_advanced_operations_session_v1",
]
