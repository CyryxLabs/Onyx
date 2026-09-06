"""Default-off guild governed project envelope (Guild A9.5).

Fifth and final Onyx Engineering Guild slice of the substrate: every guild
project is wrapped in a governed envelope — hard cost and loss budgets,
declared measurable KPIs, and the owner's termination rule encoded as an
executable decommission policy. It calls no model, opens no network, spawns
no process, persists nothing and takes no action.

Governance is structural, not advisory:

* **Hard budgets.** Cost and loss caps are micro-unit integers with a
  strictly positive floor and an absolute ceiling; an unlimited budget is
  not representable, and the loss budget can never exceed the cost budget.
* **Declared KPIs.** Each KPI names a metric, an integer target and a
  measurement reference — continuation is earned with evidence, never
  assumed.
* **Decommission policy (the owner's rule as mechanism).** Every envelope
  carries `max_consecutive_gate_failures >= 1`, a non-empty
  `kill_switch_ref`, and `on_budget_breach` / `on_kpi_failure` drawn from
  the closed vocabulary `{"revoke_and_decommission"}` — in V1 no softer
  outcome is representable.
* **Owner-gated intents.** Bound intents must exist in the accepted A9.4
  ledger snapshot and must still declare `requires_owner_approval`.
* **Inert in V1.** `is_active()` is structurally False: activation, real
  spending, measurement and decommission EXECUTION belong to the runtime
  slice that couples session grants, the approval inbox, cost
  observability and the kill switch.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

from core.guild_execution_intent_v1 import GuildExecutionIntentSnapshotV1
from core.guild_profiles_v1 import GuildRegistrySnapshotV1

FEATURE_FLAG: Final = "ONYX_GUILD_PROJECT_ENVELOPE_V1"
ENABLED_VALUE: Final = "true"
MAX_ITEMS: Final = 2_000
MAX_ID_BYTES: Final = 256
MAX_TEXT_BYTES: Final = 4_000
MIN_BUDGET_MICRO: Final = 1
MAX_BUDGET_MICRO: Final = 1_000_000_000_000_000
MAX_TARGET_VALUE: Final = 1_000_000_000
MAX_GATE_FAILURES: Final = 100
DECOMMISSION_OUTCOMES: Final = ("revoke_and_decommission",)
_CONSTRUCTION_KEY = object()

# The accepted Guild Execution-Intent (A9.4) four-file acceptance tuple.
ACCEPTED_GUILD_EXECUTION_INTENT_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/guild-execution-intent-v1/manifest.json",
        "be439c4df9b960128b875298844d1b6eb69d2b01703f2b4346e23ed5f8c67b98",
    ),
    (
        "docs/onyx/acceptance/VE-GUILD-EXECUTION-INTENT-V1-E6-001.md",
        "5bce58279b58bfb9e8fda57ec53278a9474291ee33bb4ca44d2e5af84119306e",
    ),
    (
        "docs/onyx/acceptance/VE-GUILD-EXECUTION-INTENT-V1-E6-001.manifest.json",
        "8413aef59403a9c50c0575045f81dda22cb38f985ede37d08b7a08485275ad03",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-GUILD-EXECUTION-INTENT-V1-E6-001.sha256",
        "3e93a29112524cf04da54ea3ab6a89733130a86e3463b985a6b354edb3140494",
    ),
)


class GuildProjectEnvelopeV1Error(RuntimeError):
    pass


class GuildProjectEnvelopeV1ContractError(ValueError):
    pass


class GuildProjectEnvelopeV1Denied(PermissionError):
    pass


def _text(value: object, maximum: int, *, field_name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise GuildProjectEnvelopeV1ContractError(f"{field_name} contract violation")
    if len(value.encode("utf-8")) > maximum:
        raise GuildProjectEnvelopeV1ContractError(f"{field_name} contract violation")
    return value


def _integer(value: object, *, field_name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise GuildProjectEnvelopeV1ContractError(f"{field_name} contract violation")
    return value


def _sequence(value: object, *, field_name: str) -> tuple[object, ...]:
    if type(value) not in (list, tuple):
        raise GuildProjectEnvelopeV1ContractError(f"{field_name} must be a sequence")
    if len(value) > MAX_ITEMS:
        raise GuildProjectEnvelopeV1ContractError(f"{field_name} exceeds item cap")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class GuildProjectEnvelopeFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise GuildProjectEnvelopeV1ContractError(
                "feature gate must be exact bool"
            )

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "GuildProjectEnvelopeFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class ProjectBudgetV1:
    cost_cap_micro: int
    loss_budget_micro: int
    max_missions: int


@dataclass(frozen=True, slots=True)
class ProjectKpiV1:
    kpi_id: str
    metric: str
    target_value: int
    measurement_ref: str


@dataclass(frozen=True, slots=True)
class DecommissionPolicyV1:
    max_consecutive_gate_failures: int
    on_budget_breach: str
    on_kpi_failure: str
    kill_switch_ref: str


@dataclass(frozen=True, slots=True)
class ProjectEnvelopeV1:
    project_id: str
    team_pack_id: str
    intent_ids: tuple[str, ...]
    budget: ProjectBudgetV1
    kpis: tuple[ProjectKpiV1, ...]
    decommission: DecommissionPolicyV1


@dataclass(frozen=True, slots=True)
class GuildProjectLedgerSnapshotV1:
    envelopes: tuple[ProjectEnvelopeV1, ...]


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_GUILD_EXECUTION_INTENT_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise GuildProjectEnvelopeV1Denied(
                "accepted execution-intent evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise GuildProjectEnvelopeV1Denied(
                "accepted execution-intent evidence drift"
            )


class GuildProjectLedgerV1:
    """Deterministic, hermetic governed-envelope ledger; inert in V1."""

    __slots__ = ("_envelopes",)

    def __init__(self, *, construction_key: object) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise GuildProjectEnvelopeV1ContractError(
                "use create_guild_project_ledger_v1"
            )
        self._envelopes: dict[str, ProjectEnvelopeV1] = {}

    def _load_budget(self, raw: object) -> ProjectBudgetV1:
        if type(raw) is not dict or set(raw) != {
            "cost_cap_micro",
            "loss_budget_micro",
            "max_missions",
        }:
            raise GuildProjectEnvelopeV1ContractError(
                "budget keys contract violation"
            )
        cost = _integer(
            raw["cost_cap_micro"], field_name="cost_cap_micro",
            minimum=MIN_BUDGET_MICRO, maximum=MAX_BUDGET_MICRO,
        )
        loss = _integer(
            raw["loss_budget_micro"], field_name="loss_budget_micro",
            minimum=MIN_BUDGET_MICRO, maximum=MAX_BUDGET_MICRO,
        )
        if loss > cost:
            raise GuildProjectEnvelopeV1ContractError(
                "loss budget exceeds the cost cap"
            )
        return ProjectBudgetV1(
            cost_cap_micro=cost,
            loss_budget_micro=loss,
            max_missions=_integer(
                raw["max_missions"], field_name="max_missions",
                minimum=1, maximum=MAX_ITEMS,
            ),
        )

    def _load_kpi(self, raw: object) -> ProjectKpiV1:
        if type(raw) is not dict or set(raw) != {
            "kpi_id",
            "metric",
            "target_value",
            "measurement_ref",
        }:
            raise GuildProjectEnvelopeV1ContractError("kpi keys contract violation")
        return ProjectKpiV1(
            kpi_id=_text(raw["kpi_id"], MAX_ID_BYTES, field_name="kpi_id"),
            metric=_text(raw["metric"], MAX_ID_BYTES, field_name="metric"),
            target_value=_integer(
                raw["target_value"], field_name="target_value",
                minimum=0, maximum=MAX_TARGET_VALUE,
            ),
            measurement_ref=_text(
                raw["measurement_ref"], MAX_ID_BYTES, field_name="measurement_ref"
            ),
        )

    def _load_decommission(self, raw: object) -> DecommissionPolicyV1:
        if type(raw) is not dict or set(raw) != {
            "max_consecutive_gate_failures",
            "on_budget_breach",
            "on_kpi_failure",
            "kill_switch_ref",
        }:
            raise GuildProjectEnvelopeV1ContractError(
                "decommission policy keys contract violation"
            )
        breach = _text(
            raw["on_budget_breach"], MAX_ID_BYTES, field_name="on_budget_breach"
        )
        failure = _text(
            raw["on_kpi_failure"], MAX_ID_BYTES, field_name="on_kpi_failure"
        )
        for outcome in (breach, failure):
            if outcome not in DECOMMISSION_OUTCOMES:
                raise GuildProjectEnvelopeV1ContractError(
                    "decommission outcome is not permitted"
                )
        return DecommissionPolicyV1(
            max_consecutive_gate_failures=_integer(
                raw["max_consecutive_gate_failures"],
                field_name="max_consecutive_gate_failures",
                minimum=1, maximum=MAX_GATE_FAILURES,
            ),
            on_budget_breach=breach,
            on_kpi_failure=failure,
            kill_switch_ref=_text(
                raw["kill_switch_ref"], MAX_ID_BYTES, field_name="kill_switch_ref"
            ),
        )

    def _load_envelope(
        self,
        raw: object,
        registry: GuildRegistrySnapshotV1,
        intents: GuildExecutionIntentSnapshotV1,
    ) -> ProjectEnvelopeV1:
        if type(raw) is not dict or set(raw) != {
            "project_id",
            "team_pack_id",
            "intent_ids",
            "budget",
            "kpis",
            "decommission",
        }:
            raise GuildProjectEnvelopeV1ContractError(
                "envelope keys contract violation"
            )
        team_pack_id = _text(
            raw["team_pack_id"], MAX_ID_BYTES, field_name="team_pack_id"
        )
        if not any(pack.pack_id == team_pack_id for pack in registry.team_packs):
            raise GuildProjectEnvelopeV1ContractError(
                "envelope references unknown team pack"
            )
        known_intents = {intent.intent_id: intent for intent in intents.intents}
        intent_ids: list[str] = []
        for item in _sequence(raw["intent_ids"], field_name="intent_ids"):
            intent_id = _text(item, MAX_ID_BYTES, field_name="intent_ids")
            intent = known_intents.get(intent_id)
            if intent is None:
                raise GuildProjectEnvelopeV1ContractError(
                    "envelope references unknown intent"
                )
            if intent.requires_owner_approval is not True:
                raise GuildProjectEnvelopeV1ContractError(
                    "envelope intent is not owner-gated"
                )
            if intent_id in intent_ids:
                raise GuildProjectEnvelopeV1ContractError("duplicate intent binding")
            intent_ids.append(intent_id)
        kpis: list[ProjectKpiV1] = []
        seen_kpis: set[str] = set()
        for item in _sequence(raw["kpis"], field_name="kpis"):
            kpi = self._load_kpi(item)
            if kpi.kpi_id in seen_kpis:
                raise GuildProjectEnvelopeV1ContractError("duplicate kpi_id")
            seen_kpis.add(kpi.kpi_id)
            kpis.append(kpi)
        if not kpis:
            raise GuildProjectEnvelopeV1ContractError(
                "envelope declares no KPI"
            )
        return ProjectEnvelopeV1(
            project_id=_text(raw["project_id"], MAX_ID_BYTES, field_name="project_id"),
            team_pack_id=team_pack_id,
            intent_ids=tuple(intent_ids),
            budget=self._load_budget(raw["budget"]),
            kpis=tuple(kpis),
            decommission=self._load_decommission(raw["decommission"]),
        )

    def build(
        self,
        registry: GuildRegistrySnapshotV1,
        intents: GuildExecutionIntentSnapshotV1,
        plan: object,
    ) -> GuildProjectLedgerSnapshotV1:
        if type(registry) is not GuildRegistrySnapshotV1:
            raise GuildProjectEnvelopeV1ContractError(
                "registry must be an exact GuildRegistrySnapshotV1"
            )
        if type(intents) is not GuildExecutionIntentSnapshotV1:
            raise GuildProjectEnvelopeV1ContractError(
                "intents must be an exact GuildExecutionIntentSnapshotV1"
            )
        if type(plan) is not dict or set(plan) != {"envelopes"}:
            raise GuildProjectEnvelopeV1ContractError("plan keys contract violation")
        bound: set[str] = set()
        for raw in _sequence(plan["envelopes"], field_name="envelopes"):
            envelope = self._load_envelope(raw, registry, intents)
            if envelope.project_id in self._envelopes:
                raise GuildProjectEnvelopeV1ContractError("duplicate project_id")
            for intent_id in envelope.intent_ids:
                if intent_id in bound:
                    raise GuildProjectEnvelopeV1ContractError(
                        "intent is bound by another envelope"
                    )
                bound.add(intent_id)
            self._envelopes[envelope.project_id] = envelope
        return GuildProjectLedgerSnapshotV1(
            envelopes=tuple(
                self._envelopes[key] for key in sorted(self._envelopes)
            )
        )

    def remaining_cost_micro(self, project_id: str, spent_micro: int) -> int:
        # Pure arithmetic projection over a declared cap: never a permission.
        envelope = self._envelopes.get(project_id)
        if envelope is None:
            raise GuildProjectEnvelopeV1ContractError("unknown project")
        spent = _integer(
            spent_micro, field_name="spent_micro", minimum=0, maximum=MAX_BUDGET_MICRO
        )
        return max(0, envelope.budget.cost_cap_micro - spent)

    def is_budget_breached(self, project_id: str, spent_micro: int) -> bool:
        return self.remaining_cost_micro(project_id, spent_micro) == 0

    def decommission_outcome(self, project_id: str) -> str | None:
        envelope = self._envelopes.get(project_id)
        return None if envelope is None else envelope.decommission.on_budget_breach

    def is_active(self, project_id: str) -> bool:
        # Structurally False in V1: envelopes describe governance; activation,
        # spending, measurement and decommission execution belong to the
        # runtime slice that couples grants, approvals, budgets and the kill
        # switch. The argument is accepted so callers bind the projection per
        # project; the answer never varies.
        _ = project_id
        return False


def create_guild_project_ledger_v1(project_root: Path | str) -> GuildProjectLedgerV1:
    _verify_entry(project_root)
    return GuildProjectLedgerV1(construction_key=_CONSTRUCTION_KEY)


__all__ = [
    "FEATURE_FLAG",
    "ENABLED_VALUE",
    "DECOMMISSION_OUTCOMES",
    "MIN_BUDGET_MICRO",
    "GuildProjectEnvelopeFeatureGateV1",
    "ProjectBudgetV1",
    "ProjectKpiV1",
    "DecommissionPolicyV1",
    "ProjectEnvelopeV1",
    "GuildProjectLedgerSnapshotV1",
    "GuildProjectLedgerV1",
    "GuildProjectEnvelopeV1Error",
    "GuildProjectEnvelopeV1ContractError",
    "GuildProjectEnvelopeV1Denied",
    "create_guild_project_ledger_v1",
]
