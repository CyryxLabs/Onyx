"""Provider-free, read-only adapters for accepted Guild A9.1-A9.3 data."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from threading import RLock

from core.governance_nucleus_v1 import GovernanceV1ContractError, GovernanceV1Denied
from core.governed_capability_host_v1 import HostBoundCapabilityPortV1
from core.guild_handoff_v1 import MAX_QA_REJECTS, GuildStoryLedgerSnapshotV1
from core.guild_profiles_v1 import GuildRegistrySnapshotV1
from core.guild_workflow_v1 import GuildWorkflowSnapshotV1

OPERATIONS = frozenset(
    {"read.profiles", "read.handoffs", "read.workflows", "validate.handoff", "validate.workflow"}
)
_STORY_ORDER = {name: index for index, name in enumerate(
    ("draft", "validated", "in_progress", "in_review", "done")
)}


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


class GuildCapabilityPortV1(HostBoundCapabilityPortV1):
    """Project immutable Guild snapshots without granting or dispatching authority."""

    def __init__(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        registry: GuildRegistrySnapshotV1,
        stories: GuildStoryLedgerSnapshotV1,
        workflows: GuildWorkflowSnapshotV1,
    ) -> None:
        super().__init__()
        if type(principal_id) is not str or not principal_id:
            raise GovernanceV1ContractError("guild principal binding is required")
        if type(workspace_id) is not str or not workspace_id:
            raise GovernanceV1ContractError("guild workspace binding is required")
        if type(registry) is not GuildRegistrySnapshotV1:
            raise GovernanceV1ContractError("exact guild registry snapshot is required")
        if type(stories) is not GuildStoryLedgerSnapshotV1:
            raise GovernanceV1ContractError("exact guild story snapshot is required")
        if type(workflows) is not GuildWorkflowSnapshotV1:
            raise GovernanceV1ContractError("exact guild workflow snapshot is required")
        self._principal_id = principal_id
        self._workspace_id = workspace_id
        self._registry = registry
        self._stories = stories
        self._workflows = workflows
        self._events: set[str] = set()
        self._generation: dict[str, int] = {}
        self._killed = False
        self._lock = RLock()
        self._validate_snapshots()

    def _validate_snapshots(self) -> None:
        role_ids = {profile.role_id for profile in self._registry.profiles}
        story_ids = {story.story_id for story in self._stories.stories}
        handoff_ids: set[str] = set()
        rejects: dict[str, int] = {}
        for verdict in self._stories.verdicts:
            if verdict.verdict == "reject":
                rejects[verdict.story_id] = rejects.get(verdict.story_id, 0) + 1
        if any(count > MAX_QA_REJECTS for count in rejects.values()):
            raise GovernanceV1ContractError("guild QA iteration bound exceeded")
        for handoff in self._stories.handoffs:
            if handoff.handoff_id in handoff_ids or handoff.story_id not in story_ids:
                raise GovernanceV1ContractError("malformed or duplicate guild handoff")
            if handoff.from_role_id not in role_ids or handoff.to_role_id not in role_ids:
                raise GovernanceV1ContractError("guild handoff role is unknown")
            handoff_ids.add(handoff.handoff_id)
        template_ids: set[str] = set()
        for template in self._workflows.templates:
            if template.template_id in template_ids or not template.stages:
                raise GovernanceV1ContractError("malformed or duplicate workflow template")
            template_ids.add(template.template_id)
            stage_ids: set[str] = set()
            previous = -1
            for stage in template.stages:
                current = _STORY_ORDER.get(stage.story_status_at_completion, -1)
                if stage.stage_id in stage_ids or current <= previous:
                    raise GovernanceV1ContractError("workflow template stage contract violation")
                stage_ids.add(stage.stage_id)
                previous = current
            if template.stages[-1].story_status_at_completion != "done":
                raise GovernanceV1ContractError("workflow template must end at done")

    def _scope(self, arguments: Mapping[str, object], extra: set[str]) -> None:
        expected = {"principal_id", "workspace_id"} | extra
        if type(arguments) is not dict or set(arguments) != expected:
            raise GovernanceV1ContractError("guild operation arguments contract violation")
        if arguments["principal_id"] != self._principal_id or arguments["workspace_id"] != self._workspace_id:
            raise GovernanceV1Denied("guild principal or workspace binding mismatch")

    def _accept_event(self, subject: str, event_id: object, generation: object) -> None:
        if type(event_id) is not str or not event_id or len(event_id.encode()) > 256:
            raise GovernanceV1ContractError("guild event id is malformed")
        if type(generation) is not int or isinstance(generation, bool) or generation < 1:
            raise GovernanceV1ContractError("guild generation is malformed")
        if event_id in self._events:
            raise GovernanceV1Denied("guild event replay denied")
        if generation <= self._generation.get(subject, 0):
            raise GovernanceV1Denied("stale guild event denied")
        self._events.add(event_id)
        self._generation[subject] = generation

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object]) -> object:
        with self._lock:
            if self._killed:
                raise GovernanceV1Denied("guild capability kill is latched")
            if operation.startswith("read."):
                self._scope(arguments, set())
                snapshot = {"read.profiles": self._registry, "read.handoffs": self._stories,
                            "read.workflows": self._workflows}[operation]
                return {"projection_digest": _digest(asdict(snapshot)), "read_only": True,
                        "authority_granted": False, "direct_dispatch": False}
            if operation == "validate.handoff":
                self._scope(arguments, {"handoff_id", "event_id", "generation"})
                handoff_id = arguments["handoff_id"]
                if type(handoff_id) is not str or handoff_id not in {x.handoff_id for x in self._stories.handoffs}:
                    raise GovernanceV1ContractError("unknown or malformed handoff")
                self._accept_event("handoff:" + handoff_id, arguments["event_id"], arguments["generation"])
                return {"valid": True, "policy_only": True, "authority_granted": False}
            if operation == "validate.workflow":
                self._scope(arguments, {"template_id", "completed_stages", "event_id", "generation"})
                template_id = arguments["template_id"]
                completed = arguments["completed_stages"]
                if type(completed) is not list or any(type(item) is not str for item in completed):
                    raise GovernanceV1ContractError("workflow stage list is malformed")
                if len(completed) != len(set(completed)):
                    raise GovernanceV1Denied("duplicate workflow stage denied")
                template = next((item for item in self._workflows.templates if item.template_id == template_id), None)
                if template is None or tuple(completed) != tuple(stage.stage_id for stage in template.stages[:len(completed)]):
                    raise GovernanceV1Denied("workflow stages are not an exact template prefix")
                self._accept_event("workflow:" + str(template_id), arguments["event_id"], arguments["generation"])
                return {"valid": True, "policy_only": True, "authority_granted": False}
        raise GovernanceV1Denied("unknown guild operation")

    def revoke(self, binding_id: str) -> None:
        del binding_id

    def kill(self) -> bool:
        with self._lock:
            self._killed = True
        return True


__all__ = ["GuildCapabilityPortV1", "OPERATIONS"]
