"""Default-off audience research and 30/60/90 strategy contract for Phase 10.

Fifth Phase 10 (Social organic operating system) slice: the strategy layer.
It holds cited audience research, 30/60/90 strategy plans, per-platform
funnels and KPIs, and a sample-floored experiment ledger as a pure
deterministic, hermetic contract. It calls no model, opens no network,
persists nothing and takes no action.

Governance is structural, not advisory:

* **Cited research only.** Every `ResearchClaimV1` cites a `source_ref`, and
  every `AudienceSegmentV1` carries at least one claim — audiences cannot be
  invented (the PRD anti-fabrication guard).
* **Per-platform metrics.** A `KpiV1` always names exactly one platform —
  cross-platform metric equivalence is not representable.
* **The 30/60/90 cadence as a contract.** A `StrategyPlanV1` carries exactly
  the three horizons, each with non-empty goals.
* **Sample-floored experiments.** `winner_declared` requires an observed
  sample at or above the declared minimum, and the minimum at or above the
  global floor — no winner claims from inadequate samples.
* **No action surface.** Projections only; publishing, scheduling and any
  provider read remain later, separately gated slices.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

from core.phase10_brand_passport_v1 import PLATFORMS

FEATURE_FLAG: Final = "ONYX_PHASE10_AUDIENCE_STRATEGY_V1"
ENABLED_VALUE: Final = "true"
MAX_ITEMS: Final = 2_000
MAX_ID_BYTES: Final = 256
MAX_TEXT_BYTES: Final = 20_000
STRATEGY_HORIZONS: Final = (30, 60, 90)
EXPERIMENT_MIN_SAMPLE_FLOOR: Final = 100
MAX_SAMPLE: Final = 1_000_000_000
_CONSTRUCTION_KEY = object()

# The accepted Phase 10 content-draft four-file acceptance tuple.
ACCEPTED_CONTENT_DRAFT_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase10-content-draft-v1/manifest.json",
        "f57046e1f65de10484b8ef31c706323683fd57952076d164dd0395150fdba8ff",
    ),
    (
        "docs/onyx/acceptance/VE-P10-CONTENT-DRAFT-V1-E6-001.md",
        "94f0964876f8c4a094ec8a3152501a87f20ddd8c1e08545eee591d92c822ad13",
    ),
    (
        "docs/onyx/acceptance/VE-P10-CONTENT-DRAFT-V1-E6-001.manifest.json",
        "8af9f47156ccd9ad8de232a105a40b6a32d9a42a85852d48de29c805fa5d850f",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P10-CONTENT-DRAFT-V1-E6-001.sha256",
        "cee917429abc1c5463a839411973307b6cf381a6e2003256a309ae5360e8a221",
    ),
)


class AudienceStrategyV1Error(RuntimeError):
    pass


class AudienceStrategyV1ContractError(ValueError):
    pass


class AudienceStrategyV1Denied(PermissionError):
    pass


def _text(value: object, maximum: int, *, field_name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise AudienceStrategyV1ContractError(f"{field_name} contract violation")
    if len(value.encode("utf-8")) > maximum:
        raise AudienceStrategyV1ContractError(f"{field_name} contract violation")
    return value


def _integer(value: object, *, field_name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise AudienceStrategyV1ContractError(f"{field_name} contract violation")
    return value


def _platform(value: object, *, field_name: str) -> str:
    platform = _text(value, MAX_ID_BYTES, field_name=field_name)
    if platform not in PLATFORMS:
        raise AudienceStrategyV1ContractError(f"{field_name} platform is unknown")
    return platform


def _sequence(value: object, *, field_name: str) -> tuple[object, ...]:
    if type(value) not in (list, tuple):
        raise AudienceStrategyV1ContractError(f"{field_name} must be a sequence")
    if len(value) > MAX_ITEMS:
        raise AudienceStrategyV1ContractError(f"{field_name} exceeds item cap")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class AudienceStrategyFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise AudienceStrategyV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "AudienceStrategyFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class ResearchClaimV1:
    claim_id: str
    claim_text: str
    source_ref: str
    platform: str


@dataclass(frozen=True, slots=True)
class AudienceSegmentV1:
    segment_id: str
    brand_id: str
    platform: str
    description: str
    claims: tuple[ResearchClaimV1, ...]


@dataclass(frozen=True, slots=True)
class KpiV1:
    kpi_id: str
    platform: str
    metric: str
    target_value: int
    horizon_days: int


@dataclass(frozen=True, slots=True)
class FunnelStageV1:
    stage_id: str
    order: int
    kpi_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategyPlanV1:
    plan_id: str
    brand_id: str
    goals_30: tuple[str, ...]
    goals_60: tuple[str, ...]
    goals_90: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExperimentV1:
    experiment_id: str
    hypothesis: str
    platform: str
    min_sample: int
    observed_sample: int
    winner_declared: bool


@dataclass(frozen=True, slots=True)
class AudienceStrategySnapshotV1:
    segments: tuple[AudienceSegmentV1, ...]
    kpis: tuple[KpiV1, ...]
    funnel: tuple[FunnelStageV1, ...]
    plans: tuple[StrategyPlanV1, ...]
    experiments: tuple[ExperimentV1, ...]


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_CONTENT_DRAFT_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise AudienceStrategyV1Denied(
                "accepted content-draft evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise AudienceStrategyV1Denied("accepted content-draft evidence drift")


class AudienceStrategySetV1:
    """Deterministic, hermetic audience/strategy set with PRD guards."""

    __slots__ = ("_segments", "_kpis", "_funnel", "_plans", "_experiments")

    def __init__(self, *, construction_key: object) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise AudienceStrategyV1ContractError(
                "use create_audience_strategy_set_v1"
            )
        self._segments: dict[str, AudienceSegmentV1] = {}
        self._kpis: dict[str, KpiV1] = {}
        self._funnel: dict[str, FunnelStageV1] = {}
        self._plans: dict[str, StrategyPlanV1] = {}
        self._experiments: dict[str, ExperimentV1] = {}

    def _load_claim(self, raw: object) -> ResearchClaimV1:
        if type(raw) is not dict or set(raw) != {
            "claim_id",
            "claim_text",
            "source_ref",
            "platform",
        }:
            raise AudienceStrategyV1ContractError("claim keys contract violation")
        return ResearchClaimV1(
            claim_id=_text(raw["claim_id"], MAX_ID_BYTES, field_name="claim_id"),
            claim_text=_text(raw["claim_text"], MAX_TEXT_BYTES, field_name="claim_text"),
            source_ref=_text(raw["source_ref"], MAX_ID_BYTES, field_name="source_ref"),
            platform=_platform(raw["platform"], field_name="claim platform"),
        )

    def _load_segment(self, raw: object) -> AudienceSegmentV1:
        if type(raw) is not dict or set(raw) != {
            "segment_id",
            "brand_id",
            "platform",
            "description",
            "claims",
        }:
            raise AudienceStrategyV1ContractError("segment keys contract violation")
        claims: list[ResearchClaimV1] = []
        seen: set[str] = set()
        for item in _sequence(raw["claims"], field_name="claims"):
            claim = self._load_claim(item)
            if claim.claim_id in seen:
                raise AudienceStrategyV1ContractError("duplicate claim_id in segment")
            seen.add(claim.claim_id)
            claims.append(claim)
        if not claims:
            raise AudienceStrategyV1ContractError(
                "segment carries no research claim"
            )
        return AudienceSegmentV1(
            segment_id=_text(raw["segment_id"], MAX_ID_BYTES, field_name="segment_id"),
            brand_id=_text(raw["brand_id"], MAX_ID_BYTES, field_name="brand_id"),
            platform=_platform(raw["platform"], field_name="segment platform"),
            description=_text(
                raw["description"], MAX_TEXT_BYTES, field_name="description"
            ),
            claims=tuple(claims),
        )

    def _load_kpi(self, raw: object) -> KpiV1:
        if type(raw) is not dict or set(raw) != {
            "kpi_id",
            "platform",
            "metric",
            "target_value",
            "horizon_days",
        }:
            raise AudienceStrategyV1ContractError("kpi keys contract violation")
        horizon = _integer(
            raw["horizon_days"], field_name="horizon_days", minimum=1, maximum=365
        )
        if horizon not in STRATEGY_HORIZONS:
            raise AudienceStrategyV1ContractError("kpi horizon is not 30/60/90")
        return KpiV1(
            kpi_id=_text(raw["kpi_id"], MAX_ID_BYTES, field_name="kpi_id"),
            platform=_platform(raw["platform"], field_name="kpi platform"),
            metric=_text(raw["metric"], MAX_ID_BYTES, field_name="metric"),
            target_value=_integer(
                raw["target_value"], field_name="target_value",
                minimum=0, maximum=MAX_SAMPLE,
            ),
            horizon_days=horizon,
        )

    def _load_stage(self, raw: object) -> FunnelStageV1:
        if type(raw) is not dict or set(raw) != {"stage_id", "order", "kpi_ids"}:
            raise AudienceStrategyV1ContractError("funnel keys contract violation")
        kpi_ids: list[str] = []
        for item in _sequence(raw["kpi_ids"], field_name="kpi_ids"):
            kpi_id = _text(item, MAX_ID_BYTES, field_name="kpi_ids")
            if kpi_id not in self._kpis:
                raise AudienceStrategyV1ContractError(
                    "funnel references unknown kpi"
                )
            if kpi_id in kpi_ids:
                raise AudienceStrategyV1ContractError("duplicate kpi in stage")
            kpi_ids.append(kpi_id)
        return FunnelStageV1(
            stage_id=_text(raw["stage_id"], MAX_ID_BYTES, field_name="stage_id"),
            order=_integer(raw["order"], field_name="order", minimum=1, maximum=64),
            kpi_ids=tuple(kpi_ids),
        )

    def _load_plan(self, raw: object) -> StrategyPlanV1:
        if type(raw) is not dict or set(raw) != {
            "plan_id",
            "brand_id",
            "goals_30",
            "goals_60",
            "goals_90",
        }:
            raise AudienceStrategyV1ContractError("plan keys contract violation")
        horizons: dict[str, tuple[str, ...]] = {}
        for field_name in ("goals_30", "goals_60", "goals_90"):
            goals: list[str] = []
            for item in _sequence(raw[field_name], field_name=field_name):
                goals.append(_text(item, MAX_TEXT_BYTES, field_name=field_name))
            if not goals:
                raise AudienceStrategyV1ContractError(
                    "strategy horizon carries no goal"
                )
            horizons[field_name] = tuple(goals)
        return StrategyPlanV1(
            plan_id=_text(raw["plan_id"], MAX_ID_BYTES, field_name="plan_id"),
            brand_id=_text(raw["brand_id"], MAX_ID_BYTES, field_name="brand_id"),
            goals_30=horizons["goals_30"],
            goals_60=horizons["goals_60"],
            goals_90=horizons["goals_90"],
        )

    def _load_experiment(self, raw: object) -> ExperimentV1:
        if type(raw) is not dict or set(raw) != {
            "experiment_id",
            "hypothesis",
            "platform",
            "min_sample",
            "observed_sample",
            "winner_declared",
        }:
            raise AudienceStrategyV1ContractError(
                "experiment keys contract violation"
            )
        minimum = _integer(
            raw["min_sample"], field_name="min_sample",
            minimum=EXPERIMENT_MIN_SAMPLE_FLOOR, maximum=MAX_SAMPLE,
        )
        observed = _integer(
            raw["observed_sample"], field_name="observed_sample",
            minimum=0, maximum=MAX_SAMPLE,
        )
        winner = raw["winner_declared"]
        if type(winner) is not bool:
            raise AudienceStrategyV1ContractError(
                "winner_declared must be exact bool"
            )
        if winner and observed < minimum:
            raise AudienceStrategyV1ContractError(
                "winner declared from an inadequate sample"
            )
        return ExperimentV1(
            experiment_id=_text(
                raw["experiment_id"], MAX_ID_BYTES, field_name="experiment_id"
            ),
            hypothesis=_text(
                raw["hypothesis"], MAX_TEXT_BYTES, field_name="hypothesis"
            ),
            platform=_platform(raw["platform"], field_name="experiment platform"),
            min_sample=minimum,
            observed_sample=observed,
            winner_declared=winner,
        )

    def build(self, plan: object) -> AudienceStrategySnapshotV1:
        if type(plan) is not dict or set(plan) != {
            "segments",
            "kpis",
            "funnel",
            "plans",
            "experiments",
        }:
            raise AudienceStrategyV1ContractError("plan keys contract violation")

        for raw in _sequence(plan["segments"], field_name="segments"):
            segment = self._load_segment(raw)
            if segment.segment_id in self._segments:
                raise AudienceStrategyV1ContractError("duplicate segment_id")
            self._segments[segment.segment_id] = segment

        for raw in _sequence(plan["kpis"], field_name="kpis"):
            kpi = self._load_kpi(raw)
            if kpi.kpi_id in self._kpis:
                raise AudienceStrategyV1ContractError("duplicate kpi_id")
            self._kpis[kpi.kpi_id] = kpi

        orders: set[int] = set()
        for raw in _sequence(plan["funnel"], field_name="funnel"):
            stage = self._load_stage(raw)
            if stage.stage_id in self._funnel:
                raise AudienceStrategyV1ContractError("duplicate stage_id")
            if stage.order in orders:
                raise AudienceStrategyV1ContractError("duplicate funnel order")
            orders.add(stage.order)
            self._funnel[stage.stage_id] = stage

        for raw in _sequence(plan["plans"], field_name="plans"):
            strategy = self._load_plan(raw)
            if strategy.plan_id in self._plans:
                raise AudienceStrategyV1ContractError("duplicate plan_id")
            self._plans[strategy.plan_id] = strategy

        for raw in _sequence(plan["experiments"], field_name="experiments"):
            experiment = self._load_experiment(raw)
            if experiment.experiment_id in self._experiments:
                raise AudienceStrategyV1ContractError("duplicate experiment_id")
            self._experiments[experiment.experiment_id] = experiment

        return AudienceStrategySnapshotV1(
            segments=tuple(self._segments[key] for key in sorted(self._segments)),
            kpis=tuple(self._kpis[key] for key in sorted(self._kpis)),
            funnel=tuple(
                self._funnel[key]
                for key in sorted(self._funnel, key=lambda k: self._funnel[k].order)
            ),
            plans=tuple(self._plans[key] for key in sorted(self._plans)),
            experiments=tuple(
                self._experiments[key] for key in sorted(self._experiments)
            ),
        )

    def is_winner_supported(self, experiment_id: str) -> bool:
        experiment = self._experiments.get(experiment_id)
        return (
            experiment is not None
            and experiment.winner_declared
            and experiment.observed_sample >= experiment.min_sample
        )


def create_audience_strategy_set_v1(project_root: Path | str) -> AudienceStrategySetV1:
    _verify_entry(project_root)
    return AudienceStrategySetV1(construction_key=_CONSTRUCTION_KEY)


__all__ = [
    "FEATURE_FLAG",
    "ENABLED_VALUE",
    "STRATEGY_HORIZONS",
    "EXPERIMENT_MIN_SAMPLE_FLOOR",
    "AudienceStrategyFeatureGateV1",
    "ResearchClaimV1",
    "AudienceSegmentV1",
    "KpiV1",
    "FunnelStageV1",
    "StrategyPlanV1",
    "ExperimentV1",
    "AudienceStrategySnapshotV1",
    "AudienceStrategySetV1",
    "AudienceStrategyV1Error",
    "AudienceStrategyV1ContractError",
    "AudienceStrategyV1Denied",
    "create_audience_strategy_set_v1",
]
