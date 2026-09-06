"""Default-off guild execution-intent binding (Guild A9.4).

Fourth Onyx Engineering Guild slice — the bridge between the accepted
descriptive substrate (A9.1 authority, A9.2 stories/QA, A9.3 workflows) and
the Phase 11 project autopilot. It binds a workflow run's **next** stage to
an exact, validated execution intent: what would run, for which story, by
which authorized role, over which bounded patch scope, against which exact
autopilot version. It calls no model, opens no network, spawns no process,
persists nothing and takes no action.

Governance is structural, not advisory:

* **Version-pinned target.** Intents are constructible only while
  `core/phase11_project_autopilot_v1.py` is byte-exact
  (`AUTOPILOT_MODULE_SHA256`) and still declares
  `MISSION_TYPE = "project_autopilot_v1"` — an intent against a drifted
  autopilot is denied.
* **Forward-only binding.** An intent names the exact next uncompleted
  stage of a known A9.3 run; completed, skipped and out-of-order stages are
  rejected, and the intent's story must be the run's story.
* **Authority coupling.** The intended assignee must hold the stage's
  required operation under the A9.1 registry, exclusive owner sets
  respected.
* **Bounded scope.** A non-empty workspace-relative `patch_scope` with a
  closed path grammar (no traversal, no absolute paths, no separators
  outside POSIX form) and a byte-capped `gate_argv_shape`.
* **Owner-gated by construction.** `requires_owner_approval` must be
  exactly True, and `is_dispatchable()` is structurally False — dispatch
  arrives only with a later slice under session grants, the approval inbox,
  cost budgets and the kill switch.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

from core.guild_handoff_v1 import GuildStoryLedgerSnapshotV1
from core.guild_profiles_v1 import GuildRegistrySnapshotV1
from core.guild_workflow_v1 import GuildWorkflowSnapshotV1

FEATURE_FLAG: Final = "ONYX_GUILD_EXECUTION_INTENT_V1"
ENABLED_VALUE: Final = "true"
MAX_ITEMS: Final = 2_000
MAX_ID_BYTES: Final = 256
MAX_SCOPE_ENTRIES: Final = 64
MAX_ARGV_TOKENS: Final = 64
_SCOPE_RE: Final = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")
_CONSTRUCTION_KEY = object()

AUTOPILOT_MODULE_PATH: Final = "core/phase11_project_autopilot_v1.py"
AUTOPILOT_MODULE_SHA256: Final = (
    "a5dc26eb034748045a7a69c826a56615f176561006cefd60518d79e4ff8b8430"
)
AUTOPILOT_MODULE_BYTES: Final = 185_305
AUTOPILOT_MISSION_TYPE_LITERAL: Final = 'MISSION_TYPE = "project_autopilot_v1"'

# The accepted Guild Workflow (A9.3) four-file acceptance tuple.
ACCEPTED_GUILD_WORKFLOW_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/guild-workflow-v1/manifest.json",
        "ff15e7724f5ab0d30e4f02eedfce0728d54184a86c49183b4679e88aaf99d456",
    ),
    (
        "docs/onyx/acceptance/VE-GUILD-WORKFLOW-V1-E6-001.md",
        "c6a382e47c08c30ce720d4c15a64d1553eaee3a894871d357d9307f86a3a74fe",
    ),
    (
        "docs/onyx/acceptance/VE-GUILD-WORKFLOW-V1-E6-001.manifest.json",
        "7f3350a8a23cfdfbba80abf63cab496a7b7dbacd4611092b6d7e32b05d071e32",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-GUILD-WORKFLOW-V1-E6-001.sha256",
        "b4711e50af05fdaf85249b20fdf8d235f9041f05f769a5b2f3a1f7665d84fe9a",
    ),
)


class GuildExecutionIntentV1Error(RuntimeError):
    pass


class GuildExecutionIntentV1ContractError(ValueError):
    pass


class GuildExecutionIntentV1Denied(PermissionError):
    pass


def _text(value: object, maximum: int, *, field_name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise GuildExecutionIntentV1ContractError(f"{field_name} contract violation")
    if len(value.encode("utf-8")) > maximum:
        raise GuildExecutionIntentV1ContractError(f"{field_name} contract violation")
    return value


def _sequence(
    value: object, *, field_name: str, maximum: int = MAX_ITEMS
) -> tuple[object, ...]:
    if type(value) not in (list, tuple):
        raise GuildExecutionIntentV1ContractError(f"{field_name} must be a sequence")
    if len(value) > maximum:
        raise GuildExecutionIntentV1ContractError(f"{field_name} exceeds item cap")
    return tuple(value)


def _scope_entry(value: object, *, field_name: str) -> str:
    entry = _text(value, MAX_ID_BYTES, field_name=field_name)
    if "\\" in entry or _SCOPE_RE.fullmatch(entry) is None:
        raise GuildExecutionIntentV1ContractError(
            f"{field_name} path grammar violation"
        )
    if any(part in {".", ".."} for part in entry.split("/")):
        raise GuildExecutionIntentV1ContractError(
            f"{field_name} path grammar violation"
        )
    return entry


@dataclass(frozen=True, slots=True)
class GuildExecutionIntentFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise GuildExecutionIntentV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "GuildExecutionIntentFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class AutopilotIdentityV1:
    module_path: str
    module_sha256: str
    module_bytes: int
    mission_type: str


@dataclass(frozen=True, slots=True)
class ExecutionIntentV1:
    intent_id: str
    run_id: str
    stage_id: str
    story_id: str
    assigned_role_id: str
    required_operation: str
    patch_scope: tuple[str, ...]
    gate_argv_shape: tuple[str, ...]
    requires_owner_approval: bool


@dataclass(frozen=True, slots=True)
class GuildExecutionIntentSnapshotV1:
    autopilot: AutopilotIdentityV1
    intents: tuple[ExecutionIntentV1, ...]


def _verify_entry(project_root: Path | str) -> AutopilotIdentityV1:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_GUILD_WORKFLOW_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise GuildExecutionIntentV1Denied(
                "accepted guild-workflow evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise GuildExecutionIntentV1Denied("accepted guild-workflow evidence drift")
    autopilot = (root / AUTOPILOT_MODULE_PATH).resolve()
    try:
        autopilot.relative_to(root)
        data = autopilot.read_bytes()
    except (OSError, ValueError) as exc:
        raise GuildExecutionIntentV1Denied("autopilot module unavailable") from exc
    if len(data) != AUTOPILOT_MODULE_BYTES or not hmac.compare_digest(
        hashlib.sha256(data).hexdigest(), AUTOPILOT_MODULE_SHA256
    ):
        raise GuildExecutionIntentV1Denied("autopilot module drift")
    if AUTOPILOT_MISSION_TYPE_LITERAL not in data.decode("utf-8"):
        raise GuildExecutionIntentV1Denied("autopilot mission type drift")
    return AutopilotIdentityV1(
        module_path=AUTOPILOT_MODULE_PATH,
        module_sha256=AUTOPILOT_MODULE_SHA256,
        module_bytes=AUTOPILOT_MODULE_BYTES,
        mission_type="project_autopilot_v1",
    )


class GuildExecutionIntentLedgerV1:
    """Deterministic, hermetic execution-intent ledger; dispatch-free."""

    __slots__ = ("_autopilot", "_intents", "_bound_stages")

    def __init__(self, *, construction_key: object, autopilot: AutopilotIdentityV1) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise GuildExecutionIntentV1ContractError(
                "use create_guild_execution_intent_ledger_v1"
            )
        self._autopilot = autopilot
        self._intents: dict[str, ExecutionIntentV1] = {}
        self._bound_stages: set[tuple[str, str]] = set()

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

    def _load_intent(
        self,
        raw: object,
        registry: GuildRegistrySnapshotV1,
        workflow: GuildWorkflowSnapshotV1,
    ) -> ExecutionIntentV1:
        if type(raw) is not dict or set(raw) != {
            "intent_id",
            "run_id",
            "stage_id",
            "story_id",
            "assigned_role_id",
            "patch_scope",
            "gate_argv_shape",
            "requires_owner_approval",
        }:
            raise GuildExecutionIntentV1ContractError("intent keys contract violation")
        run_id = _text(raw["run_id"], MAX_ID_BYTES, field_name="run_id")
        run = next((item for item in workflow.runs if item.run_id == run_id), None)
        if run is None:
            raise GuildExecutionIntentV1ContractError("intent references unknown run")
        template = next(
            item for item in workflow.templates if item.template_id == run.template_id
        )
        if len(run.completed_stages) >= len(template.stages):
            raise GuildExecutionIntentV1ContractError(
                "run is complete; no stage remains to intend"
            )
        next_stage = template.stages[len(run.completed_stages)]
        stage_id = _text(raw["stage_id"], MAX_ID_BYTES, field_name="stage_id")
        if stage_id != next_stage.stage_id:
            raise GuildExecutionIntentV1ContractError(
                "intent must bind the run's exact next stage"
            )
        story_id = _text(raw["story_id"], MAX_ID_BYTES, field_name="story_id")
        if story_id != run.story_id:
            raise GuildExecutionIntentV1ContractError(
                "intent story does not match the run"
            )
        role_id = _text(
            raw["assigned_role_id"], MAX_ID_BYTES, field_name="assigned_role_id"
        )
        if not self._operation_permitted(
            registry, role_id, next_stage.required_operation
        ):
            raise GuildExecutionIntentV1ContractError(
                "assignee does not hold the stage operation"
            )
        scope: list[str] = []
        for item in _sequence(
            raw["patch_scope"], field_name="patch_scope", maximum=MAX_SCOPE_ENTRIES
        ):
            entry = _scope_entry(item, field_name="patch_scope")
            if entry in scope:
                raise GuildExecutionIntentV1ContractError("duplicate patch scope entry")
            scope.append(entry)
        if not scope:
            raise GuildExecutionIntentV1ContractError("patch scope must be non-empty")
        argv: list[str] = []
        for item in _sequence(
            raw["gate_argv_shape"], field_name="gate_argv_shape", maximum=MAX_ARGV_TOKENS
        ):
            argv.append(_text(item, MAX_ID_BYTES, field_name="gate_argv_shape"))
        approval = raw["requires_owner_approval"]
        if approval is not True:
            raise GuildExecutionIntentV1ContractError(
                "requires_owner_approval must be exactly True"
            )
        return ExecutionIntentV1(
            intent_id=_text(raw["intent_id"], MAX_ID_BYTES, field_name="intent_id"),
            run_id=run_id,
            stage_id=stage_id,
            story_id=story_id,
            assigned_role_id=role_id,
            required_operation=next_stage.required_operation,
            patch_scope=tuple(scope),
            gate_argv_shape=tuple(argv),
            requires_owner_approval=True,
        )

    def build(
        self,
        registry: GuildRegistrySnapshotV1,
        ledger: GuildStoryLedgerSnapshotV1,
        workflow: GuildWorkflowSnapshotV1,
        plan: object,
    ) -> GuildExecutionIntentSnapshotV1:
        if type(registry) is not GuildRegistrySnapshotV1:
            raise GuildExecutionIntentV1ContractError(
                "registry must be an exact GuildRegistrySnapshotV1"
            )
        if type(ledger) is not GuildStoryLedgerSnapshotV1:
            raise GuildExecutionIntentV1ContractError(
                "ledger must be an exact GuildStoryLedgerSnapshotV1"
            )
        if type(workflow) is not GuildWorkflowSnapshotV1:
            raise GuildExecutionIntentV1ContractError(
                "workflow must be an exact GuildWorkflowSnapshotV1"
            )
        if type(plan) is not dict or set(plan) != {"intents"}:
            raise GuildExecutionIntentV1ContractError("plan keys contract violation")
        ledger_story_ids = {story.story_id for story in ledger.stories}
        for raw in _sequence(plan["intents"], field_name="intents"):
            intent = self._load_intent(raw, registry, workflow)
            if intent.story_id not in ledger_story_ids:
                raise GuildExecutionIntentV1ContractError(
                    "intent story is absent from the story ledger"
                )
            if intent.intent_id in self._intents:
                raise GuildExecutionIntentV1ContractError("duplicate intent_id")
            bound = (intent.run_id, intent.stage_id)
            if bound in self._bound_stages:
                raise GuildExecutionIntentV1ContractError(
                    "stage already carries an open intent"
                )
            self._bound_stages.add(bound)
            self._intents[intent.intent_id] = intent
        return GuildExecutionIntentSnapshotV1(
            autopilot=self._autopilot,
            intents=tuple(self._intents[key] for key in sorted(self._intents)),
        )

    def intent_for(self, run_id: str, stage_id: str) -> ExecutionIntentV1 | None:
        for intent in self._intents.values():
            if intent.run_id == run_id and intent.stage_id == stage_id:
                return intent
        return None

    def is_dispatchable(self, intent_id: str) -> bool:
        # Structurally False in V1: dispatch authority does not exist here.
        # It arrives only with a later, separately accepted slice under
        # session grants, the approval inbox, cost budgets and the kill
        # switch. The argument is accepted so callers bind the projection
        # per intent; the answer never varies.
        _ = intent_id
        return False


def create_guild_execution_intent_ledger_v1(
    project_root: Path | str,
) -> GuildExecutionIntentLedgerV1:
    autopilot = _verify_entry(project_root)
    return GuildExecutionIntentLedgerV1(
        construction_key=_CONSTRUCTION_KEY, autopilot=autopilot
    )


__all__ = [
    "FEATURE_FLAG",
    "ENABLED_VALUE",
    "AUTOPILOT_MODULE_PATH",
    "AUTOPILOT_MODULE_SHA256",
    "GuildExecutionIntentFeatureGateV1",
    "AutopilotIdentityV1",
    "ExecutionIntentV1",
    "GuildExecutionIntentSnapshotV1",
    "GuildExecutionIntentLedgerV1",
    "GuildExecutionIntentV1Error",
    "GuildExecutionIntentV1ContractError",
    "GuildExecutionIntentV1Denied",
    "create_guild_execution_intent_ledger_v1",
]
