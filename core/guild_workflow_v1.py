"""Default-off guild workflow templates and run projections (Guild A9.3).

Third Onyx Engineering Guild slice. It encodes AEXOS workflow definitions
(the Story Development Cycle) as byte-pinned, validated templates and
projects workflow runs over them: template stages bind a required operation
and a story-lifecycle completion status; a run's completed stages must be an
exact template prefix, each assignee must hold the stage's required
operation under the accepted registry (exclusive owner sets respected), and
the linked story's recorded status must match the last completed stage. It
calls no model, opens no network, spawns no process, persists nothing and
takes no action.

This completes the guild's **descriptive** substrate. Nothing here runs,
schedules or dispatches; execution arrives only with later, separately
gated slices.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

from core.guild_handoff_v1 import STORY_STATUSES, GuildStoryLedgerSnapshotV1
from core.guild_profiles_v1 import GuildRegistrySnapshotV1

FEATURE_FLAG: Final = "ONYX_GUILD_WORKFLOW_V1"
ENABLED_VALUE: Final = "true"
MAX_ITEMS: Final = 2_000
MAX_ID_BYTES: Final = 256
MAX_SOURCE_BYTES: Final = 1_000_000
_OPERATION_RE: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_CONSTRUCTION_KEY = object()

# The accepted Guild Handoff (A9.2) four-file acceptance tuple.
ACCEPTED_GUILD_HANDOFF_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/guild-handoff-v1/manifest.json",
        "4498cab1dd227ddab8a43b8961cf00bdbdbd8f2a8a61f181b5ed100e41e655e8",
    ),
    (
        "docs/onyx/acceptance/VE-GUILD-HANDOFF-V1-E6-001.md",
        "3aaee02e674044acdc7d4433c56c17510dd8da9b90eb3efbaecbba37e4f8020b",
    ),
    (
        "docs/onyx/acceptance/VE-GUILD-HANDOFF-V1-E6-001.manifest.json",
        "4fd4ef3871bea2ecf60904b10e3bacc686ffac8f4c19fe8322bc3088f878a015",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-GUILD-HANDOFF-V1-E6-001.sha256",
        "5e879789f6710fe7aecc0b2cf1a5439aa52517c3a1ce334f1bf9964a67b2302b",
    ),
)


class GuildWorkflowV1Error(RuntimeError):
    pass


class GuildWorkflowV1ContractError(ValueError):
    pass


class GuildWorkflowV1Denied(PermissionError):
    pass


def _text(value: object, maximum: int, *, field_name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise GuildWorkflowV1ContractError(f"{field_name} contract violation")
    if len(value.encode("utf-8")) > maximum:
        raise GuildWorkflowV1ContractError(f"{field_name} contract violation")
    return value


def _operation(value: object, *, field_name: str) -> str:
    if type(value) is not str or _OPERATION_RE.fullmatch(value) is None:
        raise GuildWorkflowV1ContractError(f"{field_name} operation grammar violation")
    return value


def _sequence(value: object, *, field_name: str) -> tuple[object, ...]:
    if type(value) not in (list, tuple):
        raise GuildWorkflowV1ContractError(f"{field_name} must be a sequence")
    if len(value) > MAX_ITEMS:
        raise GuildWorkflowV1ContractError(f"{field_name} exceeds item cap")
    return tuple(value)


def _pinned_source(raw_sha: object, raw_bytes: object, *, field_name: str) -> str:
    if type(raw_sha) is not str or _SHA256_RE.fullmatch(raw_sha) is None:
        raise GuildWorkflowV1ContractError(f"{field_name} must be lowercase sha256 hex")
    if type(raw_bytes) is not bytes or not raw_bytes:
        raise GuildWorkflowV1ContractError(f"{field_name} bytes contract violation")
    if len(raw_bytes) > MAX_SOURCE_BYTES:
        raise GuildWorkflowV1ContractError(f"{field_name} bytes contract violation")
    if not hmac.compare_digest(hashlib.sha256(raw_bytes).hexdigest(), raw_sha):
        raise GuildWorkflowV1ContractError(f"{field_name} source bytes drift")
    return raw_sha


@dataclass(frozen=True, slots=True)
class GuildWorkflowFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise GuildWorkflowV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "GuildWorkflowFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class WorkflowStageV1:
    stage_id: str
    required_operation: str
    story_status_at_completion: str


@dataclass(frozen=True, slots=True)
class WorkflowTemplateV1:
    template_id: str
    stages: tuple[WorkflowStageV1, ...]
    source_ref: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class CompletedStageV1:
    stage_id: str
    assigned_role_id: str


@dataclass(frozen=True, slots=True)
class WorkflowRunV1:
    run_id: str
    template_id: str
    story_id: str
    completed_stages: tuple[CompletedStageV1, ...]


@dataclass(frozen=True, slots=True)
class GuildWorkflowSnapshotV1:
    templates: tuple[WorkflowTemplateV1, ...]
    runs: tuple[WorkflowRunV1, ...]


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_GUILD_HANDOFF_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise GuildWorkflowV1Denied(
                "accepted guild-handoff evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise GuildWorkflowV1Denied("accepted guild-handoff evidence drift")


class GuildWorkflowV1:
    """Deterministic, hermetic workflow-template and run-projection ledger."""

    __slots__ = ("_templates", "_runs")

    def __init__(self, *, construction_key: object) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise GuildWorkflowV1ContractError("use create_guild_workflow_v1")
        self._templates: dict[str, WorkflowTemplateV1] = {}
        self._runs: dict[str, WorkflowRunV1] = {}

    def _load_template(self, raw: object) -> WorkflowTemplateV1:
        if type(raw) is not dict or set(raw) != {
            "template_id",
            "stages",
            "source_ref",
            "source_sha256",
            "source_bytes",
        }:
            raise GuildWorkflowV1ContractError("template keys contract violation")
        stages: list[WorkflowStageV1] = []
        seen: set[str] = set()
        order = {status: index for index, status in enumerate(STORY_STATUSES)}
        previous = -1
        for item in _sequence(raw["stages"], field_name="stages"):
            if type(item) is not dict or set(item) != {
                "stage_id",
                "required_operation",
                "story_status_at_completion",
            }:
                raise GuildWorkflowV1ContractError("stage keys contract violation")
            stage_id = _text(item["stage_id"], MAX_ID_BYTES, field_name="stage_id")
            if stage_id in seen:
                raise GuildWorkflowV1ContractError("duplicate stage_id")
            seen.add(stage_id)
            status = _text(
                item["story_status_at_completion"],
                MAX_ID_BYTES,
                field_name="story_status_at_completion",
            )
            if status not in order:
                raise GuildWorkflowV1ContractError("stage completion status unknown")
            if order[status] <= previous:
                raise GuildWorkflowV1ContractError(
                    "stage completion statuses must progress"
                )
            previous = order[status]
            stages.append(
                WorkflowStageV1(
                    stage_id=stage_id,
                    required_operation=_operation(
                        item["required_operation"], field_name="required_operation"
                    ),
                    story_status_at_completion=status,
                )
            )
        if not stages:
            raise GuildWorkflowV1ContractError("template has no stages")
        if stages[-1].story_status_at_completion != "done":
            raise GuildWorkflowV1ContractError("template must end at done")
        return WorkflowTemplateV1(
            template_id=_text(raw["template_id"], MAX_ID_BYTES, field_name="template_id"),
            stages=tuple(stages),
            source_ref=_text(raw["source_ref"], MAX_ID_BYTES, field_name="source_ref"),
            source_sha256=_pinned_source(
                raw["source_sha256"], raw["source_bytes"], field_name="template"
            ),
        )

    @staticmethod
    def _operation_permitted(
        registry: GuildRegistrySnapshotV1, role_id: str, operation: str
    ) -> bool:
        profile = next(
            (item for item in registry.profiles if item.role_id == role_id), None
        )
        if profile is None or operation not in profile.allowed_operations:
            return False
        for exclusive_operation, owners in registry.matrix.exclusive_owners:
            if exclusive_operation == operation:
                return role_id in owners
        return True

    def _load_run(
        self,
        raw: object,
        registry: GuildRegistrySnapshotV1,
        story_statuses: dict[str, str],
    ) -> WorkflowRunV1:
        if type(raw) is not dict or set(raw) != {
            "run_id",
            "template_id",
            "story_id",
            "completed_stages",
        }:
            raise GuildWorkflowV1ContractError("run keys contract violation")
        template_id = _text(raw["template_id"], MAX_ID_BYTES, field_name="template_id")
        template = self._templates.get(template_id)
        if template is None:
            raise GuildWorkflowV1ContractError("run references unknown template")
        story_id = _text(raw["story_id"], MAX_ID_BYTES, field_name="story_id")
        if story_id not in story_statuses:
            raise GuildWorkflowV1ContractError("run references unknown story")
        completed: list[CompletedStageV1] = []
        for index, item in enumerate(
            _sequence(raw["completed_stages"], field_name="completed_stages")
        ):
            if type(item) is not dict or set(item) != {"stage_id", "assigned_role_id"}:
                raise GuildWorkflowV1ContractError(
                    "completed stage keys contract violation"
                )
            if index >= len(template.stages):
                raise GuildWorkflowV1ContractError("run exceeds template stages")
            stage = template.stages[index]
            stage_id = _text(item["stage_id"], MAX_ID_BYTES, field_name="stage_id")
            if stage_id != stage.stage_id:
                raise GuildWorkflowV1ContractError(
                    "run stages must be an exact template prefix"
                )
            role_id = _text(
                item["assigned_role_id"], MAX_ID_BYTES, field_name="assigned_role_id"
            )
            if not self._operation_permitted(
                registry, role_id, stage.required_operation
            ):
                raise GuildWorkflowV1ContractError(
                    "assignee does not hold the stage operation"
                )
            completed.append(
                CompletedStageV1(stage_id=stage_id, assigned_role_id=role_id)
            )
        expected_status = (
            "draft"
            if not completed
            else template.stages[len(completed) - 1].story_status_at_completion
        )
        if story_statuses[story_id] != expected_status:
            raise GuildWorkflowV1ContractError(
                "story status does not match run progress"
            )
        return WorkflowRunV1(
            run_id=_text(raw["run_id"], MAX_ID_BYTES, field_name="run_id"),
            template_id=template_id,
            story_id=story_id,
            completed_stages=tuple(completed),
        )

    def build(
        self,
        registry: GuildRegistrySnapshotV1,
        ledger: GuildStoryLedgerSnapshotV1,
        plan: object,
    ) -> GuildWorkflowSnapshotV1:
        if type(registry) is not GuildRegistrySnapshotV1:
            raise GuildWorkflowV1ContractError(
                "registry must be an exact GuildRegistrySnapshotV1"
            )
        if type(ledger) is not GuildStoryLedgerSnapshotV1:
            raise GuildWorkflowV1ContractError(
                "ledger must be an exact GuildStoryLedgerSnapshotV1"
            )
        if type(plan) is not dict or set(plan) != {"templates", "runs"}:
            raise GuildWorkflowV1ContractError("plan keys contract violation")
        story_statuses = {story.story_id: story.status for story in ledger.stories}

        seen_sources: set[str] = set()
        for raw in _sequence(plan["templates"], field_name="templates"):
            template = self._load_template(raw)
            if template.template_id in self._templates:
                raise GuildWorkflowV1ContractError("duplicate template_id")
            if template.source_ref in seen_sources:
                raise GuildWorkflowV1ContractError("duplicate source_ref")
            seen_sources.add(template.source_ref)
            self._templates[template.template_id] = template

        for raw in _sequence(plan["runs"], field_name="runs"):
            run = self._load_run(raw, registry, story_statuses)
            if run.run_id in self._runs:
                raise GuildWorkflowV1ContractError("duplicate run_id")
            self._runs[run.run_id] = run

        return GuildWorkflowSnapshotV1(
            templates=tuple(self._templates[key] for key in sorted(self._templates)),
            runs=tuple(self._runs[key] for key in sorted(self._runs)),
        )

    def run_stage(self, run_id: str) -> str | None:
        run = self._runs.get(run_id)
        if run is None or not run.completed_stages:
            return None
        return run.completed_stages[-1].stage_id

    def is_run_complete(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if run is None:
            return False
        template = self._templates[run.template_id]
        return len(run.completed_stages) == len(template.stages)


def create_guild_workflow_v1(project_root: Path | str) -> GuildWorkflowV1:
    _verify_entry(project_root)
    return GuildWorkflowV1(construction_key=_CONSTRUCTION_KEY)


__all__ = [
    "FEATURE_FLAG",
    "ENABLED_VALUE",
    "GuildWorkflowFeatureGateV1",
    "WorkflowStageV1",
    "WorkflowTemplateV1",
    "CompletedStageV1",
    "WorkflowRunV1",
    "GuildWorkflowSnapshotV1",
    "GuildWorkflowV1",
    "GuildWorkflowV1Error",
    "GuildWorkflowV1ContractError",
    "GuildWorkflowV1Denied",
    "create_guild_workflow_v1",
]
