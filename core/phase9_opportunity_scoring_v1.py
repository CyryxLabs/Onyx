"""Default-off transparent opportunity scoring for Phase 9.

This second Phase 9 slice implements the PRD opportunity-scoring contract as a
pure deterministic weighted model over a fixed set of dimensions (pain/economic
cost, urgency, buyer/payability, timing, competition, Cyryx advantage, time to
MVP/revenue, complexity, distribution, moat, legal/platform risk and evidence
confidence). Every dimension has an explicit fixed weight and an explicit
benefit/cost direction, and the result exposes the full per-dimension breakdown
so a score is fully auditable. It calls no model, opens no network, persists
nothing and takes no action — a score can never trigger a trade or any other
side effect. Live source ingestion, model-assisted scoring and any autonomous
acting on a score are deliberately out of scope for later gated successors.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

FEATURE_FLAG: Final = "ONYX_PHASE9_OPPORTUNITY_SCORING_V1"
ENABLED_VALUE: Final = "true"
SCORE_MIN: Final = 0
SCORE_MAX: Final = 5
MAX_ITEMS: Final = 1_000
MAX_ID_BYTES: Final = 256
MAX_TITLE_BYTES: Final = 4_000
LOW_CONFIDENCE_AT: Final = 1
_CONSTRUCTION_KEY = object()

# (name, weight, is_cost). Benefit dimensions reward a high raw score; cost/risk
# dimensions reward a low raw score (their effective value is inverted). Weights
# are fixed and transparent; the ladder and directions are documented in the ADR.
DIMENSIONS: Final = (
    ("pain_economic_cost", 3, False),
    ("urgency", 2, False),
    ("buyer_payability", 3, False),
    ("timing", 2, False),
    ("competition", 2, True),
    ("cyryx_advantage", 3, False),
    ("time_to_mvp_revenue", 2, True),
    ("complexity", 2, True),
    ("distribution", 2, False),
    ("moat", 2, False),
    ("legal_platform_risk", 2, True),
    ("evidence_confidence", 3, False),
)
DIMENSION_NAMES: Final = tuple(name for name, _weight, _cost in DIMENSIONS)
_TOTAL_WEIGHT: Final = sum(weight for _name, weight, _cost in DIMENSIONS)
_MAX_POINTS: Final = _TOTAL_WEIGHT * SCORE_MAX
ACCEPTED_INGESTION_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase9-intelligence-ingestion-v1/manifest.json",
        "2d7650b305b203ce9c74e576652d8221b4dac2498d37c7450ab365325e04a78f",
    ),
    (
        "docs/onyx/acceptance/VE-P9-INTELLIGENCE-INGESTION-V1-E6-001.md",
        "8496c3cbc39bbca67c25241355ad494a622b64076733436ebe5447eb1e209465",
    ),
    (
        "docs/onyx/acceptance/VE-P9-INTELLIGENCE-INGESTION-V1-E6-001.manifest.json",
        "6105adc37682a47296d87181dc5f7e70a3aa82e039b1f4a335830139acd1bbf1",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P9-INTELLIGENCE-INGESTION-V1-E6-001.sha256",
        "dcf8b3351ee909f44efe7b5e442f8c26acc361bf580adceb48ff398ba61e0a84",
    ),
)


class OpportunityScoringV1Error(RuntimeError):
    pass


class OpportunityScoringV1ContractError(ValueError):
    pass


class OpportunityScoringV1Denied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class OpportunityScoringFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise OpportunityScoringV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "OpportunityScoringFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class DimensionScoreV1:
    name: str
    raw: int
    is_cost: bool
    effective: int
    weight: int
    points: int
    max_points: int


@dataclass(frozen=True, slots=True)
class OpportunityScoreV1:
    opportunity_id: str
    title: str
    total_score: int
    band: str
    low_confidence: bool
    rank: int
    dimensions: tuple[DimensionScoreV1, ...]


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_INGESTION_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise OpportunityScoringV1Denied(
                "accepted ingestion evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise OpportunityScoringV1Denied("accepted ingestion evidence drift")


def _text(value: object, maximum: int, *, field: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise OpportunityScoringV1ContractError(f"{field} contract violation")
    if len(value.encode("utf-8")) > maximum:
        raise OpportunityScoringV1ContractError(f"{field} contract violation")
    return value


def _band(total: int) -> str:
    if total >= 80:
        return "priority"
    if total >= 60:
        return "pursue"
    if total >= 40:
        return "consider"
    return "watch"


class OpportunityScoringSessionV1:
    """Deterministic, transparent weighted opportunity scorer."""

    __slots__ = ()

    def __init__(self, *, construction_key: object) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise OpportunityScoringV1ContractError(
                "use create_opportunity_scoring_v1"
            )

    def _score_one(self, raw: object) -> tuple[str, str, int, bool, tuple[DimensionScoreV1, ...]]:
        if type(raw) is not dict:
            raise OpportunityScoringV1ContractError("item must be an object")
        opportunity_id = _text(raw.get("opportunity_id"), MAX_ID_BYTES, field="opportunity_id")
        title = _text(raw.get("title"), MAX_TITLE_BYTES, field="title")
        scores = raw.get("scores")
        if type(scores) is not dict:
            raise OpportunityScoringV1ContractError("scores must be an object")
        if set(scores) != set(DIMENSION_NAMES):
            raise OpportunityScoringV1ContractError("scores must cover every dimension exactly")
        earned = 0
        dimensions: list[DimensionScoreV1] = []
        low_confidence = False
        for name, weight, is_cost in DIMENSIONS:
            value = scores[name]
            if type(value) is not int or type(value) is bool or not SCORE_MIN <= value <= SCORE_MAX:
                raise OpportunityScoringV1ContractError(f"{name} score is out of range")
            effective = (SCORE_MAX - value) if is_cost else value
            points = weight * effective
            earned += points
            if name == "evidence_confidence" and value <= LOW_CONFIDENCE_AT:
                low_confidence = True
            dimensions.append(
                DimensionScoreV1(
                    name, value, is_cost, effective, weight, points, weight * SCORE_MAX
                )
            )
        total = (earned * 100 + _MAX_POINTS // 2) // _MAX_POINTS
        return opportunity_id, title, total, low_confidence, tuple(dimensions)

    def score(self, raw: object) -> OpportunityScoreV1:
        opportunity_id, title, total, low_confidence, dimensions = self._score_one(raw)
        return OpportunityScoreV1(
            opportunity_id, title, total, _band(total), low_confidence, 1, dimensions
        )

    def score_batch(self, raw_items: object) -> tuple[OpportunityScoreV1, ...]:
        if type(raw_items) is not list or len(raw_items) > MAX_ITEMS:
            raise OpportunityScoringV1ContractError("opportunity batch is invalid")
        scored: list[tuple[str, str, int, bool, tuple[DimensionScoreV1, ...]]] = []
        seen: set[str] = set()
        for raw in raw_items:
            result = self._score_one(raw)
            if result[0] in seen:
                raise OpportunityScoringV1ContractError("duplicate opportunity_id")
            seen.add(result[0])
            scored.append(result)
        order = sorted(
            range(len(scored)), key=lambda i: (-scored[i][2], scored[i][0])
        )
        rank_of = {index: position + 1 for position, index in enumerate(order)}
        return tuple(
            OpportunityScoreV1(
                opportunity_id,
                title,
                total,
                _band(total),
                low_confidence,
                rank_of[index],
                dimensions,
            )
            for index, (opportunity_id, title, total, low_confidence, dimensions) in enumerate(
                scored
            )
        )


def create_opportunity_scoring_v1(
    *,
    gate: OpportunityScoringFeatureGateV1 | None = None,
    project_root: Path | str | None = None,
) -> OpportunityScoringSessionV1 | None:
    selected = (
        OpportunityScoringFeatureGateV1.from_environ() if gate is None else gate
    )
    if type(selected) is not OpportunityScoringFeatureGateV1:
        raise OpportunityScoringV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    _verify_entry(
        Path(__file__).resolve().parents[1] if project_root is None else project_root
    )
    return OpportunityScoringSessionV1(construction_key=_CONSTRUCTION_KEY)


__all__ = [
    "DIMENSION_NAMES",
    "DIMENSIONS",
    "DimensionScoreV1",
    "FEATURE_FLAG",
    "OpportunityScoreV1",
    "OpportunityScoringFeatureGateV1",
    "OpportunityScoringSessionV1",
    "OpportunityScoringV1ContractError",
    "OpportunityScoringV1Denied",
    "OpportunityScoringV1Error",
    "SCORE_MAX",
    "create_opportunity_scoring_v1",
]
