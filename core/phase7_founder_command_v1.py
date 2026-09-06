"""Cited read-only Founder Command projections for Phase 7.

The generator calls the accepted Company Graph projector itself. It does not
accept an unauthenticated graph snapshot, fetch sources, persist a brief,
invoke a model, or execute a recommendation.

V1 preserves declared contradictions and detects structured incompatible
statuses. General open-text/NLP contradiction discovery is intentionally not
claimed by this deterministic slice.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from core.phase7_company_graph_v1 import (
    SEMANTICS,
    CompanyGraphAssertionV1,
    CompanyGraphItemV1,
    CompanyGraphProjectionV1,
    CompanyGraphProjectorV1,
    _projection_sha256,
)
from memory.store import contains_secret


FEATURE_FLAG: Final = "ONYX_PHASE7_FOUNDER_COMMAND_V1"
ENABLED_VALUE: Final = "true"
SCHEMA: Final = "OnyxFounderCommandBrief.v1"
MAX_ACTION_CANDIDATES: Final = 500
MAX_ITEMS: Final = 2_000
MAX_TEXT_BYTES: Final = 2_000
DAY_MS: Final = 86_400_000
ACCEPTED_GRAPH_ENTRY_ROOTS: Final = (
    (
        (
            "docs/onyx/checkpoints/"
            "phase7-approved-sources-company-graph-v1/manifest.json"
        ),
        "fa5fea91caf6914e559cbc22420841b602eeace0153653dc57591fb0070f23f3",
    ),
    (
        (
            "docs/onyx/acceptance/"
            "VE-P7-APPROVED-SOURCES-COMPANY-GRAPH-V1-E6-001.md"
        ),
        "b5336b1484c1225b58454dd39cfeb6fad51662fd46b7658bfbb3572389222650",
    ),
    (
        (
            "docs/onyx/acceptance/"
            "VE-P7-APPROVED-SOURCES-COMPANY-GRAPH-V1-E6-001.manifest.json"
        ),
        "27522c63449d625c97b500ac8ed9048aeddb4cf1d20f77a96bd5431cd21cd14d",
    ),
    (
        (
            "docs/onyx/"
            "VE-ACCEPTANCE-P7-APPROVED-SOURCES-COMPANY-GRAPH-V1-E6-001.sha256"
        ),
        "d5d17c9fdceb76b43405afc8b54129f1e6c9af1e35e67f140cb25aeafb674f85",
    ),
)
CADENCES: Final = frozenset({"daily", "weekly"})
FRESHNESS_STATES: Final = frozenset({"aging", "current", "stale"})
ACTION_KINDS: Final = frozenset(
    {"operating_action", "revenue_opportunity"}
)
GOALS: Final = frozenset(
    {
        "customer_learning",
        "near_term_revenue",
        "product_delivery",
        "risk_reduction",
    }
)
CONTRADICTION_KINDS: Final = frozenset(
    {"declared", "potential_undeclared"}
)
SEVERITIES: Final = frozenset({"critical", "high", "medium"})
_SLUG = re.compile(r"^[a-z][a-z0-9-]{2,79}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CLAIM_ID = re.compile(r"^m2a-claim-[0-9a-f]{64}$")
_CONSTRUCTION_KEY = object()


class FounderCommandV1Error(RuntimeError):
    """Base Founder Command error."""


class FounderCommandV1ContractError(ValueError):
    """Input violates the Founder Command contract."""


class FounderCommandV1Denied(PermissionError):
    """Entry, graph, freshness, provenance or scope policy denied."""


@dataclass(frozen=True, slots=True)
class FounderCommandFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise FounderCommandV1ContractError(
                "feature gate must be exact bool"
            )

    @classmethod
    def from_environ(
        cls,
        environ: dict[str, str] | os._Environ[str] | None = None,
    ) -> "FounderCommandFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class SemanticFreshnessWindowV1:
    semantic: str
    aging_after_ms: int
    stale_after_ms: int

    def __post_init__(self) -> None:
        if (
            type(self.semantic) is not str
            or self.semantic not in SEMANTICS
            or type(self.aging_after_ms) is not int
            or type(self.stale_after_ms) is not int
            or self.aging_after_ms <= 0
            or self.stale_after_ms <= self.aging_after_ms
        ):
            raise FounderCommandV1ContractError(
                "semantic freshness window is invalid"
            )


@dataclass(frozen=True, slots=True)
class FounderFreshnessPolicyV1:
    windows: tuple[SemanticFreshnessWindowV1, ...]

    def __post_init__(self) -> None:
        if (
            type(self.windows) is not tuple
            or not self.windows
            or any(
                type(item) is not SemanticFreshnessWindowV1
                for item in self.windows
            )
            or tuple(sorted(self.windows, key=lambda item: item.semantic))
            != self.windows
            or len({item.semantic for item in self.windows})
            != len(self.windows)
        ):
            raise FounderCommandV1ContractError(
                "freshness policy must be exact, unique, and sorted"
            )
        expected = {
            "approved_fact",
            "current_status",
            "dependency",
            "evidence",
            "hypothesis",
            "metric",
            "proposed_decision",
            "rejected_decision",
            "risk",
            "superseded_decision",
        }
        if {item.semantic for item in self.windows} != expected:
            raise FounderCommandV1ContractError(
                "freshness policy must cover every graph semantic"
            )

    def window(self, semantic: str) -> SemanticFreshnessWindowV1:
        for item in self.windows:
            if item.semantic == semantic:
                return item
        raise FounderCommandV1Denied("freshness semantic is unavailable")


DEFAULT_FRESHNESS_POLICY_V1: Final = FounderFreshnessPolicyV1(
    windows=tuple(
        sorted(
            (
                SemanticFreshnessWindowV1(
                    "approved_fact",
                    30 * DAY_MS,
                    90 * DAY_MS,
                ),
                SemanticFreshnessWindowV1(
                    "current_status",
                    DAY_MS,
                    3 * DAY_MS,
                ),
                SemanticFreshnessWindowV1(
                    "dependency",
                    3 * DAY_MS,
                    7 * DAY_MS,
                ),
                SemanticFreshnessWindowV1(
                    "evidence",
                    7 * DAY_MS,
                    30 * DAY_MS,
                ),
                SemanticFreshnessWindowV1(
                    "hypothesis",
                    7 * DAY_MS,
                    30 * DAY_MS,
                ),
                SemanticFreshnessWindowV1(
                    "metric",
                    DAY_MS,
                    3 * DAY_MS,
                ),
                SemanticFreshnessWindowV1(
                    "proposed_decision",
                    7 * DAY_MS,
                    30 * DAY_MS,
                ),
                SemanticFreshnessWindowV1(
                    "rejected_decision",
                    30 * DAY_MS,
                    90 * DAY_MS,
                ),
                SemanticFreshnessWindowV1(
                    "risk",
                    3 * DAY_MS,
                    7 * DAY_MS,
                ),
                SemanticFreshnessWindowV1(
                    "superseded_decision",
                    30 * DAY_MS,
                    90 * DAY_MS,
                ),
            ),
            key=lambda item: item.semantic,
        )
    )
)


@dataclass(frozen=True, slots=True)
class FounderActionCandidateV1:
    action_id: str
    kind: str
    goal: str
    title: str
    claim_ids: tuple[str, ...]
    impact_bp: int
    urgency_bp: int
    effort_bp: int
    downside_bp: int
    known_context: str | None
    inference: str | None
    unknowns: tuple[str, ...]
    alternative_explanations: tuple[str, ...]
    recommended_action: str
    verification_method: str
    completion_evidence: str
    downside: str

    def __post_init__(self) -> None:
        _slug("action_id", self.action_id)
        if self.kind not in ACTION_KINDS:
            raise FounderCommandV1ContractError("action kind is invalid")
        if self.goal not in GOALS:
            raise FounderCommandV1ContractError("action goal is invalid")
        _text("action title", self.title)
        if (
            type(self.claim_ids) is not tuple
            or not self.claim_ids
            or tuple(sorted(self.claim_ids)) != self.claim_ids
            or len(set(self.claim_ids)) != len(self.claim_ids)
            or any(not _CLAIM_ID.fullmatch(item) for item in self.claim_ids)
        ):
            raise FounderCommandV1ContractError(
                "action claim_ids must be nonempty, unique, and sorted"
            )
        for field in (
            "impact_bp",
            "urgency_bp",
            "effort_bp",
            "downside_bp",
        ):
            value = getattr(self, field)
            if type(value) is not int or not 0 <= value <= 10_000:
                raise FounderCommandV1ContractError(
                    "action scores must be exact basis points"
                )
        _optional_text("known_context", self.known_context)
        _optional_text("inference", self.inference)
        if self.known_context is None and self.inference is None:
            raise FounderCommandV1ContractError(
                "action must separate known context or inference"
            )
        _text_tuple("unknowns", self.unknowns, maximum=32)
        _text_tuple(
            "alternative_explanations",
            self.alternative_explanations,
            maximum=16,
        )
        _text("recommended_action", self.recommended_action)
        _text("verification_method", self.verification_method)
        _text("completion_evidence", self.completion_evidence)
        _text("downside", self.downside)


@dataclass(frozen=True, slots=True)
class FounderFreshnessFindingV1:
    claim_id: str
    semantic: str
    state: str
    age_ms: int
    refresh_due_at_ms: int
    stale_at_ms: int

    def __post_init__(self) -> None:
        if (
            not _CLAIM_ID.fullmatch(self.claim_id)
            or type(self.semantic) is not str
            or self.semantic not in SEMANTICS
            or self.state not in FRESHNESS_STATES
            or type(self.age_ms) is not int
            or self.age_ms < 0
            or type(self.refresh_due_at_ms) is not int
            or type(self.stale_at_ms) is not int
            or self.stale_at_ms <= self.refresh_due_at_ms
        ):
            raise FounderCommandV1ContractError(
                "freshness finding contract drift"
            )


@dataclass(frozen=True, slots=True)
class FounderContradictionV1:
    kind: str
    severity: str
    project_id: str
    subject_id: str
    semantic: str
    claim_ids: tuple[str, ...]
    citations: tuple[str, ...]
    explanation: str

    def __post_init__(self) -> None:
        if (
            self.kind not in CONTRADICTION_KINDS
            or self.severity not in SEVERITIES
            or type(self.claim_ids) is not tuple
            or len(self.claim_ids) < 2
            or tuple(sorted(self.claim_ids)) != self.claim_ids
            or len(set(self.claim_ids)) != len(self.claim_ids)
            or any(not _CLAIM_ID.fullmatch(item) for item in self.claim_ids)
            or type(self.citations) is not tuple
            or not self.citations
            or tuple(sorted(set(self.citations))) != self.citations
        ):
            raise FounderCommandV1ContractError(
                "contradiction finding contract drift"
            )
        _slug("project_id", self.project_id)
        _slug("subject_id", self.subject_id)
        if self.semantic not in SEMANTICS:
            raise FounderCommandV1ContractError(
                "contradiction semantic is invalid"
            )
        _text("contradiction explanation", self.explanation)


@dataclass(frozen=True, slots=True)
class FounderPortfolioProjectV1:
    project_id: str
    project_name: str
    claim_ids: tuple[str, ...]
    status_claim_ids: tuple[str, ...]
    blocker_claim_ids: tuple[str, ...]
    dependency_claim_ids: tuple[str, ...]
    risk_claim_ids: tuple[str, ...]
    decision_claim_ids: tuple[str, ...]
    stale_claim_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _slug("project_id", self.project_id)
        _text("project_name", self.project_name)
        if not self.claim_ids:
            raise FounderCommandV1ContractError(
                "portfolio project must contain claims"
            )
        for value in (
            self.claim_ids,
            self.status_claim_ids,
            self.blocker_claim_ids,
            self.dependency_claim_ids,
            self.risk_claim_ids,
            self.decision_claim_ids,
            self.stale_claim_ids,
        ):
            if (
                type(value) is not tuple
                or tuple(sorted(set(value))) != value
                or any(not _CLAIM_ID.fullmatch(item) for item in value)
            ):
                raise FounderCommandV1ContractError(
                    "portfolio claim index contract drift"
                )


@dataclass(frozen=True, slots=True)
class FounderPrioritizedActionV1:
    action_id: str
    kind: str
    goal: str
    title: str
    claim_ids: tuple[str, ...]
    citations: tuple[str, ...]
    priority_bp: int
    impact_bp: int
    urgency_bp: int
    effort_bp: int
    downside_bp: int
    evidence_class: str
    known_context: str | None
    inference: str | None
    unknowns: tuple[str, ...]
    alternative_explanations: tuple[str, ...]
    recommended_action: str
    verification_method: str
    completion_evidence: str
    downside: str

    def __post_init__(self) -> None:
        _slug("action_id", self.action_id)
        if (
            self.kind not in ACTION_KINDS
            or self.goal not in GOALS
            or type(self.claim_ids) is not tuple
            or not self.claim_ids
            or tuple(sorted(self.claim_ids)) != self.claim_ids
            or len(set(self.claim_ids)) != len(self.claim_ids)
            or any(not _CLAIM_ID.fullmatch(item) for item in self.claim_ids)
            or type(self.priority_bp) is not int
            or not 0 <= self.priority_bp <= 10_000
            or self.evidence_class not in {"inferred", "known", "unknown"}
            or type(self.citations) is not tuple
            or not self.citations
            or tuple(sorted(set(self.citations))) != self.citations
        ):
            raise FounderCommandV1ContractError(
                "prioritized action contract drift"
            )
        _text("action title", self.title)
        for field in (
            "impact_bp",
            "urgency_bp",
            "effort_bp",
            "downside_bp",
        ):
            value = getattr(self, field)
            if type(value) is not int or not 0 <= value <= 10_000:
                raise FounderCommandV1ContractError(
                    "prioritized action score drift"
                )
        _optional_text("known_context", self.known_context)
        _optional_text("inference", self.inference)
        if self.known_context is None and self.inference is None:
            raise FounderCommandV1ContractError(
                "prioritized action lacks evidence interpretation"
            )
        _text_tuple("unknowns", self.unknowns, maximum=32)
        _text_tuple(
            "alternative_explanations",
            self.alternative_explanations,
            maximum=16,
        )
        _text("recommended_action", self.recommended_action)
        _text("verification_method", self.verification_method)
        _text("completion_evidence", self.completion_evidence)
        _text("downside", self.downside)


@dataclass(frozen=True, slots=True)
class FounderBriefDeltaV1:
    baseline: bool
    previous_brief_sha256: str | None
    added_claim_ids: tuple[str, ...]
    removed_claim_ids: tuple[str, ...]
    changed_subjects: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            type(self.baseline) is not bool
            or (
                self.previous_brief_sha256 is not None
                and not _HEX64.fullmatch(self.previous_brief_sha256)
            )
            or self.baseline
            != (self.previous_brief_sha256 is None)
        ):
            raise FounderCommandV1ContractError("brief delta contract drift")
        for value in (self.added_claim_ids, self.removed_claim_ids):
            if (
                type(value) is not tuple
                or tuple(sorted(set(value))) != value
                or any(not _CLAIM_ID.fullmatch(item) for item in value)
            ):
                raise FounderCommandV1ContractError(
                    "brief delta claim index drift"
                )
        if (
            type(self.changed_subjects) is not tuple
            or tuple(sorted(set(self.changed_subjects)))
            != self.changed_subjects
        ):
            raise FounderCommandV1ContractError(
                "brief changed-subject index drift"
            )


@dataclass(frozen=True, slots=True)
class FounderCommandBriefV1:
    workspace_id: str
    principal_id: str
    cadence: str
    generated_at_ms: int
    graph_sha256: str
    items: tuple[CompanyGraphItemV1, ...]
    freshness: tuple[FounderFreshnessFindingV1, ...]
    contradictions: tuple[FounderContradictionV1, ...]
    portfolio: tuple[FounderPortfolioProjectV1, ...]
    known_claim_ids: tuple[str, ...]
    inferred_claim_ids: tuple[str, ...]
    unknown_claim_ids: tuple[str, ...]
    critical_blocker_claim_ids: tuple[str, ...]
    dependency_claim_ids: tuple[str, ...]
    decision_queue_claim_ids: tuple[str, ...]
    risk_register_claim_ids: tuple[str, ...]
    revenue_opportunities: tuple[FounderPrioritizedActionV1, ...]
    recommended_top_actions: tuple[FounderPrioritizedActionV1, ...]
    delta: FounderBriefDeltaV1
    abstentions: tuple[str, ...]
    brief_sha256: str
    read_only: bool
    content_trust: str

    def __post_init__(self) -> None:
        if (
            self.cadence not in CADENCES
            or type(self.generated_at_ms) is not int
            or self.generated_at_ms < 0
            or not _HEX64.fullmatch(self.graph_sha256)
            or type(self.items) is not tuple
            or not self.items
            or len(self.items) > MAX_ITEMS
            or any(type(item) is not CompanyGraphItemV1 for item in self.items)
            or tuple(sorted(self.items, key=lambda item: item.claim_id))
            != self.items
            or type(self.freshness) is not tuple
            or any(
                type(item) is not FounderFreshnessFindingV1
                for item in self.freshness
            )
            or type(self.contradictions) is not tuple
            or any(
                type(item) is not FounderContradictionV1
                for item in self.contradictions
            )
            or type(self.portfolio) is not tuple
            or any(
                type(item) is not FounderPortfolioProjectV1
                for item in self.portfolio
            )
            or type(self.revenue_opportunities) is not tuple
            or type(self.recommended_top_actions) is not tuple
            or len(self.recommended_top_actions) > 3
            or any(
                type(item) is not FounderPrioritizedActionV1
                for item in (
                    *self.revenue_opportunities,
                    *self.recommended_top_actions,
                )
            )
            or type(self.delta) is not FounderBriefDeltaV1
            or type(self.abstentions) is not tuple
            or not _HEX64.fullmatch(self.brief_sha256)
            or self.read_only is not True
            or self.content_trust != "untrusted_data"
        ):
            raise FounderCommandV1ContractError(
                "Founder Brief contract drift"
            )
        for value in (
            self.known_claim_ids,
            self.inferred_claim_ids,
            self.unknown_claim_ids,
            self.critical_blocker_claim_ids,
            self.dependency_claim_ids,
            self.decision_queue_claim_ids,
            self.risk_register_claim_ids,
        ):
            if (
                type(value) is not tuple
                or tuple(sorted(set(value))) != value
                or any(not _CLAIM_ID.fullmatch(item) for item in value)
            ):
                raise FounderCommandV1ContractError(
                    "Founder Brief claim queue drift"
                )
        _text_tuple("abstentions", self.abstentions, maximum=16)
        item_ids = {item.claim_id for item in self.items}
        classified = (
            set(self.known_claim_ids)
            | set(self.inferred_claim_ids)
            | set(self.unknown_claim_ids)
        )
        if (
            classified != item_ids
            or set(self.known_claim_ids) & set(self.inferred_claim_ids)
            or set(self.known_claim_ids) & set(self.unknown_claim_ids)
            or set(self.inferred_claim_ids) & set(self.unknown_claim_ids)
            or {item.claim_id for item in self.freshness} != item_ids
            or any(
                claim_id not in item_ids
                for claim_id in (
                    *self.critical_blocker_claim_ids,
                    *self.dependency_claim_ids,
                    *self.decision_queue_claim_ids,
                    *self.risk_register_claim_ids,
                )
            )
            or any(
                claim_id not in item_ids
                for action in (
                    *self.revenue_opportunities,
                    *self.recommended_top_actions,
                )
                for claim_id in action.claim_ids
            )
            or any(
                claim_id not in item_ids
                for project in self.portfolio
                for claim_id in project.claim_ids
            )
        ):
            raise FounderCommandV1ContractError(
                "Founder Brief internal reference drift"
            )
        values = {
            field: getattr(self, field)
            for field in (
                "workspace_id",
                "principal_id",
                "cadence",
                "generated_at_ms",
                "graph_sha256",
                "items",
                "freshness",
                "contradictions",
                "portfolio",
                "known_claim_ids",
                "inferred_claim_ids",
                "unknown_claim_ids",
                "critical_blocker_claim_ids",
                "dependency_claim_ids",
                "decision_queue_claim_ids",
                "risk_register_claim_ids",
                "revenue_opportunities",
                "recommended_top_actions",
                "delta",
                "abstentions",
            )
        }
        if _brief_sha256(**values) != self.brief_sha256:
            raise FounderCommandV1ContractError(
                "Founder Brief digest drift"
            )


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FounderCommandV1ContractError(
            "value is not canonical JSON"
        ) from exc


def _text(label: str, value: str, maximum: int = MAX_TEXT_BYTES) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum
        or any(ord(character) < 32 for character in value)
        or contains_secret(value)
    ):
        raise FounderCommandV1ContractError(
            f"{label} contains unsafe or secret-like material"
        )
    return value


def _optional_text(label: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _text(label, value)


def _text_tuple(
    label: str,
    value: tuple[str, ...],
    *,
    maximum: int,
) -> tuple[str, ...]:
    if (
        type(value) is not tuple
        or len(value) > maximum
        or len(set(value)) != len(value)
    ):
        raise FounderCommandV1ContractError(f"{label} is invalid")
    for item in value:
        _text(label, item)
    return value


def _slug(label: str, value: str) -> str:
    _text(label, value, 80)
    if not _SLUG.fullmatch(value):
        raise FounderCommandV1ContractError(f"{label} is invalid")
    return value


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise FounderCommandV1Denied("accepted graph evidence is unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_graph_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    if root.is_symlink() or not root.is_dir():
        raise FounderCommandV1Denied("project root is invalid")
    for relative, expected in ACCEPTED_GRAPH_ENTRY_ROOTS:
        path = root / relative
        try:
            observed = _digest(path)
        except OSError as exc:
            raise FounderCommandV1Denied(
                "accepted graph evidence is unreadable"
            ) from exc
        if observed != expected:
            raise FounderCommandV1Denied(
                "accepted graph evidence drift"
            )


def _item_payload(item: CompanyGraphItemV1) -> dict[str, object]:
    return {
        "claim_id": item.claim_id,
        "semantic": item.semantic,
        "project_id": item.project_id,
        "project_name": item.project_name,
        "subject_id": item.subject_id,
        "subject_name": item.subject_name,
        "owner": item.owner,
        "status": item.status,
        "blockers": list(item.blockers),
        "next_milestone": item.next_milestone,
        "definition_of_done": item.definition_of_done,
        "last_verified_ms": item.last_verified_ms,
        "confidence_bp": item.confidence_bp,
        "verification_status": item.verification_status,
        "source_names": list(item.source_names),
        "citations": list(item.citations),
        "evidence_ids": list(item.evidence_ids),
        "evidence_sha256": list(item.evidence_sha256),
        "authority_summary": list(item.authority_summary),
        "knowledge_class": item.knowledge_class,
        "freshness": item.freshness,
        "content_trust": item.content_trust,
    }


def _action_payload(item: FounderPrioritizedActionV1) -> dict[str, object]:
    return {
        "action_id": item.action_id,
        "kind": item.kind,
        "goal": item.goal,
        "title": item.title,
        "claim_ids": list(item.claim_ids),
        "citations": list(item.citations),
        "priority_bp": item.priority_bp,
        "impact_bp": item.impact_bp,
        "urgency_bp": item.urgency_bp,
        "effort_bp": item.effort_bp,
        "downside_bp": item.downside_bp,
        "evidence_class": item.evidence_class,
        "known_context": item.known_context,
        "inference": item.inference,
        "unknowns": list(item.unknowns),
        "alternative_explanations": list(item.alternative_explanations),
        "recommended_action": item.recommended_action,
        "verification_method": item.verification_method,
        "completion_evidence": item.completion_evidence,
        "downside": item.downside,
    }


def _brief_payload(
    *,
    workspace_id: str,
    principal_id: str,
    cadence: str,
    generated_at_ms: int,
    graph_sha256: str,
    items: tuple[CompanyGraphItemV1, ...],
    freshness: tuple[FounderFreshnessFindingV1, ...],
    contradictions: tuple[FounderContradictionV1, ...],
    portfolio: tuple[FounderPortfolioProjectV1, ...],
    known_claim_ids: tuple[str, ...],
    inferred_claim_ids: tuple[str, ...],
    unknown_claim_ids: tuple[str, ...],
    critical_blocker_claim_ids: tuple[str, ...],
    dependency_claim_ids: tuple[str, ...],
    decision_queue_claim_ids: tuple[str, ...],
    risk_register_claim_ids: tuple[str, ...],
    revenue_opportunities: tuple[FounderPrioritizedActionV1, ...],
    recommended_top_actions: tuple[FounderPrioritizedActionV1, ...],
    delta: FounderBriefDeltaV1,
    abstentions: tuple[str, ...],
) -> dict[str, object]:
    return {
        "schema": SCHEMA,
        "workspace_id": workspace_id,
        "principal_id": principal_id,
        "cadence": cadence,
        "generated_at_ms": generated_at_ms,
        "graph_sha256": graph_sha256,
        "items": [_item_payload(item) for item in items],
        "freshness": [
            {
                "claim_id": item.claim_id,
                "semantic": item.semantic,
                "state": item.state,
                "age_ms": item.age_ms,
                "refresh_due_at_ms": item.refresh_due_at_ms,
                "stale_at_ms": item.stale_at_ms,
            }
            for item in freshness
        ],
        "contradictions": [
            {
                "kind": item.kind,
                "severity": item.severity,
                "project_id": item.project_id,
                "subject_id": item.subject_id,
                "semantic": item.semantic,
                "claim_ids": list(item.claim_ids),
                "citations": list(item.citations),
                "explanation": item.explanation,
            }
            for item in contradictions
        ],
        "portfolio": [
            {
                "project_id": item.project_id,
                "project_name": item.project_name,
                "claim_ids": list(item.claim_ids),
                "status_claim_ids": list(item.status_claim_ids),
                "blocker_claim_ids": list(item.blocker_claim_ids),
                "dependency_claim_ids": list(item.dependency_claim_ids),
                "risk_claim_ids": list(item.risk_claim_ids),
                "decision_claim_ids": list(item.decision_claim_ids),
                "stale_claim_ids": list(item.stale_claim_ids),
            }
            for item in portfolio
        ],
        "known_claim_ids": list(known_claim_ids),
        "inferred_claim_ids": list(inferred_claim_ids),
        "unknown_claim_ids": list(unknown_claim_ids),
        "critical_blocker_claim_ids": list(
            critical_blocker_claim_ids
        ),
        "dependency_claim_ids": list(dependency_claim_ids),
        "decision_queue_claim_ids": list(decision_queue_claim_ids),
        "risk_register_claim_ids": list(risk_register_claim_ids),
        "revenue_opportunities": [
            _action_payload(item) for item in revenue_opportunities
        ],
        "recommended_top_actions": [
            _action_payload(item) for item in recommended_top_actions
        ],
        "delta": {
            "baseline": delta.baseline,
            "previous_brief_sha256": delta.previous_brief_sha256,
            "added_claim_ids": list(delta.added_claim_ids),
            "removed_claim_ids": list(delta.removed_claim_ids),
            "changed_subjects": list(delta.changed_subjects),
        },
        "abstentions": list(abstentions),
        "read_only": True,
        "content_trust": "untrusted_data",
    }


def _brief_sha256(**values: object) -> str:
    return hashlib.sha256(_canonical(_brief_payload(**values))).hexdigest()


def _freshness(
    items: tuple[CompanyGraphItemV1, ...],
    policy: FounderFreshnessPolicyV1,
    now_ms: int,
) -> tuple[FounderFreshnessFindingV1, ...]:
    findings: list[FounderFreshnessFindingV1] = []
    for item in items:
        age = now_ms - item.last_verified_ms
        if age < 0:
            raise FounderCommandV1Denied(
                "graph contains a future verification time"
            )
        window = policy.window(item.semantic)
        state = (
            "stale"
            if age >= window.stale_after_ms
            else "aging"
            if age >= window.aging_after_ms
            else "current"
        )
        findings.append(
            FounderFreshnessFindingV1(
                claim_id=item.claim_id,
                semantic=item.semantic,
                state=state,
                age_ms=age,
                refresh_due_at_ms=(
                    item.last_verified_ms + window.aging_after_ms
                ),
                stale_at_ms=(
                    item.last_verified_ms + window.stale_after_ms
                ),
            )
        )
    return tuple(sorted(findings, key=lambda item: item.claim_id))


def _citations(
    claim_ids: tuple[str, ...],
    by_claim: dict[str, CompanyGraphItemV1],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                citation
                for claim_id in claim_ids
                for citation in by_claim[claim_id].citations
            }
        )
    )


def _contradictions(
    projection: CompanyGraphProjectionV1,
) -> tuple[FounderContradictionV1, ...]:
    by_claim = {item.claim_id: item for item in projection.items}
    findings: list[FounderContradictionV1] = []
    declared_pairs = {tuple(pair) for pair in projection.contradictions}
    superseded_pairs = {
        frozenset(pair) for pair in projection.supersessions
    }
    for pair in sorted(declared_pairs):
        left, right = (by_claim[pair[0]], by_claim[pair[1]])
        findings.append(
            FounderContradictionV1(
                kind="declared",
                severity=(
                    "critical"
                    if "verified_complete" in {left.status, right.status}
                    else "high"
                ),
                project_id=left.project_id,
                subject_id=left.subject_id,
                semantic=left.semantic,
                claim_ids=pair,
                citations=_citations(pair, by_claim),
                explanation=(
                    "The Domain Ledger explicitly declares these claims "
                    "contradictory; neither is silently discarded."
                ),
            )
        )
    groups: dict[
        tuple[str, str, str],
        list[CompanyGraphItemV1],
    ] = {}
    for item in projection.items:
        if item.semantic not in {
            "approved_fact",
            "current_status",
            "metric",
        }:
            continue
        groups.setdefault(
            (item.project_id, item.subject_id, item.semantic),
            [],
        ).append(item)
    for key, group in sorted(groups.items()):
        active = [
            item
            for item in group
            if item.status not in {"rejected", "superseded", "unknown"}
        ]
        for left_index, left in enumerate(active):
            for right in active[left_index + 1 :]:
                pair = tuple(sorted((left.claim_id, right.claim_id)))
                if (
                    pair in declared_pairs
                    or frozenset(pair) in superseded_pairs
                    or left.status == right.status
                ):
                    continue
                findings.append(
                    FounderContradictionV1(
                        kind="potential_undeclared",
                        severity=(
                            "critical"
                            if "verified_complete"
                            in {left.status, right.status}
                            else "high"
                        ),
                        project_id=key[0],
                        subject_id=key[1],
                        semantic=key[2],
                        claim_ids=pair,
                        citations=_citations(pair, by_claim),
                        explanation=(
                            "Two active source-grounded claims describe the "
                            "same subject and semantic with incompatible "
                            "statuses but lack a declared contradiction or "
                            "supersession."
                        ),
                    )
                )
    return tuple(
        sorted(
            findings,
            key=lambda item: (
                item.project_id,
                item.subject_id,
                item.semantic,
                item.kind,
                item.claim_ids,
            ),
        )
    )


def _portfolio(
    items: tuple[CompanyGraphItemV1, ...],
    freshness: tuple[FounderFreshnessFindingV1, ...],
) -> tuple[FounderPortfolioProjectV1, ...]:
    stale = {
        item.claim_id for item in freshness if item.state == "stale"
    }
    projects: dict[str, list[CompanyGraphItemV1]] = {}
    for item in items:
        projects.setdefault(item.project_id, []).append(item)
    result: list[FounderPortfolioProjectV1] = []
    for project_id, project_items in sorted(projects.items()):
        names = {item.project_name for item in project_items}
        if len(names) != 1:
            raise FounderCommandV1Denied(
                "project identity has conflicting display names"
            )
        result.append(
            FounderPortfolioProjectV1(
                project_id=project_id,
                project_name=next(iter(names)),
                claim_ids=tuple(
                    sorted(item.claim_id for item in project_items)
                ),
                status_claim_ids=tuple(
                    sorted(
                        item.claim_id
                        for item in project_items
                        if item.semantic == "current_status"
                    )
                ),
                blocker_claim_ids=tuple(
                    sorted(
                        item.claim_id
                        for item in project_items
                        if item.status == "blocked" or item.blockers
                    )
                ),
                dependency_claim_ids=tuple(
                    sorted(
                        item.claim_id
                        for item in project_items
                        if item.semantic == "dependency"
                    )
                ),
                risk_claim_ids=tuple(
                    sorted(
                        item.claim_id
                        for item in project_items
                        if item.semantic == "risk"
                    )
                ),
                decision_claim_ids=tuple(
                    sorted(
                        item.claim_id
                        for item in project_items
                        if item.semantic
                        in {
                            "proposed_decision",
                            "rejected_decision",
                            "superseded_decision",
                        }
                    )
                ),
                stale_claim_ids=tuple(
                    sorted(
                        item.claim_id
                        for item in project_items
                        if item.claim_id in stale
                    )
                ),
            )
        )
    return tuple(result)


def _actions(
    candidates: tuple[FounderActionCandidateV1, ...],
    items: tuple[CompanyGraphItemV1, ...],
) -> tuple[FounderPrioritizedActionV1, ...]:
    by_claim = {item.claim_id: item for item in items}
    result: list[FounderPrioritizedActionV1] = []
    for candidate in candidates:
        if any(claim_id not in by_claim for claim_id in candidate.claim_ids):
            raise FounderCommandV1Denied(
                "action evidence is absent from the current graph"
            )
        linked = tuple(by_claim[item] for item in candidate.claim_ids)
        classes = {item.knowledge_class for item in linked}
        if candidate.known_context is not None and "known" not in classes:
            raise FounderCommandV1Denied(
                "known action context lacks a known graph claim"
            )
        if candidate.inference is not None and not (
            classes & {"inferred", "unknown"}
        ):
            raise FounderCommandV1Denied(
                "action inference lacks an inferred or unknown graph claim"
            )
        confidence = sum(item.confidence_bp for item in linked) // len(linked)
        priority = (
            candidate.impact_bp * 35
            + candidate.urgency_bp * 30
            + confidence * 20
            + (10_000 - candidate.effort_bp) * 10
            + (10_000 - candidate.downside_bp) * 5
        ) // 100
        evidence_class = (
            "known"
            if classes == {"known"}
            else "unknown"
            if "unknown" in classes
            else "inferred"
        )
        result.append(
            FounderPrioritizedActionV1(
                action_id=candidate.action_id,
                kind=candidate.kind,
                goal=candidate.goal,
                title=candidate.title,
                claim_ids=candidate.claim_ids,
                citations=_citations(candidate.claim_ids, by_claim),
                priority_bp=priority,
                impact_bp=candidate.impact_bp,
                urgency_bp=candidate.urgency_bp,
                effort_bp=candidate.effort_bp,
                downside_bp=candidate.downside_bp,
                evidence_class=evidence_class,
                known_context=candidate.known_context,
                inference=candidate.inference,
                unknowns=candidate.unknowns,
                alternative_explanations=candidate.alternative_explanations,
                recommended_action=candidate.recommended_action,
                verification_method=candidate.verification_method,
                completion_evidence=candidate.completion_evidence,
                downside=candidate.downside,
            )
        )
    return tuple(
        sorted(
            result,
            key=lambda item: (-item.priority_bp, item.action_id),
        )
    )


def _subject_claims(
    items: tuple[CompanyGraphItemV1, ...],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for item in items:
        key = f"{item.project_id}/{item.subject_id}/{item.semantic}"
        result.setdefault(key, []).append(item.claim_id)
    return {
        key: tuple(sorted(values))
        for key, values in sorted(result.items())
    }


def _verify_previous_brief(
    previous: FounderCommandBriefV1,
) -> None:
    values = {
        field: getattr(previous, field)
        for field in (
            "workspace_id",
            "principal_id",
            "cadence",
            "generated_at_ms",
            "graph_sha256",
            "items",
            "freshness",
            "contradictions",
            "portfolio",
            "known_claim_ids",
            "inferred_claim_ids",
            "unknown_claim_ids",
            "critical_blocker_claim_ids",
            "dependency_claim_ids",
            "decision_queue_claim_ids",
            "risk_register_claim_ids",
            "revenue_opportunities",
            "recommended_top_actions",
            "delta",
            "abstentions",
        )
    }
    if _brief_sha256(**values) != previous.brief_sha256:
        raise FounderCommandV1Denied("previous brief integrity drift")


def _delta(
    items: tuple[CompanyGraphItemV1, ...],
    previous: FounderCommandBriefV1 | None,
) -> FounderBriefDeltaV1:
    if previous is None:
        return FounderBriefDeltaV1(
            baseline=True,
            previous_brief_sha256=None,
            added_claim_ids=(),
            removed_claim_ids=(),
            changed_subjects=(),
        )
    _verify_previous_brief(previous)
    current_ids = {item.claim_id for item in items}
    previous_ids = {item.claim_id for item in previous.items}
    current_subjects = _subject_claims(items)
    previous_subjects = _subject_claims(previous.items)
    changed = tuple(
        sorted(
            key
            for key in set(current_subjects) | set(previous_subjects)
            if current_subjects.get(key) != previous_subjects.get(key)
        )
    )
    return FounderBriefDeltaV1(
        baseline=False,
        previous_brief_sha256=previous.brief_sha256,
        added_claim_ids=tuple(sorted(current_ids - previous_ids)),
        removed_claim_ids=tuple(sorted(previous_ids - current_ids)),
        changed_subjects=changed,
    )


class FounderCommandGeneratorV1:
    """Sealed, deterministic executive projection over the accepted graph."""

    __slots__ = ("_projector", "_policy", "_workspace_id", "_principal_id")

    def __init__(
        self,
        *,
        construction_key: object,
        projector: CompanyGraphProjectorV1,
        policy: FounderFreshnessPolicyV1,
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise FounderCommandV1ContractError(
                "use create_founder_command_generator_v1"
            )
        if (
            type(projector) is not CompanyGraphProjectorV1
            or type(policy) is not FounderFreshnessPolicyV1
        ):
            raise FounderCommandV1ContractError(
                "exact graph projector and freshness policy required"
            )
        projector._attest()
        self._projector = projector
        self._policy = policy
        self._workspace_id = projector.workspace_id
        self._principal_id = projector.principal_id

    def __init_subclass__(cls, **_kwargs: object) -> None:
        raise TypeError("FounderCommandGeneratorV1 cannot be subclassed")

    def __copy__(self) -> object:
        raise TypeError("FounderCommandGeneratorV1 cannot be copied")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("FounderCommandGeneratorV1 cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError("FounderCommandGeneratorV1 cannot be serialized")

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    @property
    def principal_id(self) -> str:
        return self._principal_id

    def generate(
        self,
        assertions: tuple[CompanyGraphAssertionV1, ...],
        *,
        now_ms: int,
        allowed_sensitivities: tuple[str, ...],
        cadence: str,
        action_candidates: tuple[FounderActionCandidateV1, ...] = (),
        previous_brief: FounderCommandBriefV1 | None = None,
    ) -> FounderCommandBriefV1:
        if cadence not in CADENCES:
            raise FounderCommandV1ContractError("cadence is invalid")
        if (
            type(action_candidates) is not tuple
            or len(action_candidates) > MAX_ACTION_CANDIDATES
            or any(
                type(item) is not FounderActionCandidateV1
                for item in action_candidates
            )
            or tuple(
                sorted(action_candidates, key=lambda item: item.action_id)
            )
            != action_candidates
            or len({item.action_id for item in action_candidates})
            != len(action_candidates)
        ):
            raise FounderCommandV1ContractError(
                "action candidates must be unique and sorted"
            )
        if (
            previous_brief is not None
            and type(previous_brief) is not FounderCommandBriefV1
        ):
            raise FounderCommandV1ContractError(
                "previous brief must be exact V1"
            )
        self._projector._attest()
        projection = self._projector.project(
            assertions,
            now_ms=now_ms,
            allowed_sensitivities=allowed_sensitivities,
        )
        if (
            type(projection) is not CompanyGraphProjectionV1
            or projection.workspace_id != self.workspace_id
            or projection.principal_id != self.principal_id
            or projection.generated_at_ms != now_ms
            or projection.graph_sha256
            != _projection_sha256(
                workspace_id=projection.workspace_id,
                principal_id=projection.principal_id,
                generated_at_ms=projection.generated_at_ms,
                items=projection.items,
                relations=projection.relations,
                contradictions=projection.contradictions,
                supersessions=projection.supersessions,
            )
        ):
            raise FounderCommandV1Denied("graph projection integrity drift")
        if previous_brief is not None and (
            previous_brief.workspace_id != self.workspace_id
            or previous_brief.principal_id != self.principal_id
            or previous_brief.generated_at_ms >= now_ms
        ):
            raise FounderCommandV1Denied(
                "previous brief scope or chronology drift"
            )
        freshness = _freshness(projection.items, self._policy, now_ms)
        contradictions = _contradictions(projection)
        portfolio = _portfolio(projection.items, freshness)
        actions = _actions(action_candidates, projection.items)
        revenue = tuple(
            item for item in actions if item.kind == "revenue_opportunity"
        )
        abstentions: list[str] = []
        if not revenue:
            abstentions.append(
                "No source-grounded revenue opportunity was supplied; "
                "revenue, customers, traction and runway are not inferred."
            )
        if not action_candidates:
            abstentions.append(
                "No evidence-linked action candidate was supplied; "
                "recommended top actions are empty."
            )
        item_by_id = {item.claim_id: item for item in projection.items}
        known = tuple(
            sorted(
                item.claim_id
                for item in projection.items
                if item.knowledge_class == "known"
            )
        )
        inferred = tuple(
            sorted(
                item.claim_id
                for item in projection.items
                if item.knowledge_class == "inferred"
            )
        )
        unknown = tuple(
            sorted(
                item.claim_id
                for item in projection.items
                if item.knowledge_class == "unknown"
            )
        )
        blockers = tuple(
            sorted(
                item.claim_id
                for item in projection.items
                if item.status == "blocked" or item.blockers
            )
        )
        dependencies = tuple(
            sorted(
                item.claim_id
                for item in projection.items
                if item.semantic == "dependency"
            )
        )
        decisions = tuple(
            sorted(
                item.claim_id
                for item in projection.items
                if item.semantic == "proposed_decision"
                and item.status == "proposed"
            )
        )
        risks = tuple(
            sorted(
                item.claim_id
                for item in projection.items
                if item.semantic == "risk"
            )
        )
        for claim_id in (
            *known,
            *inferred,
            *unknown,
            *blockers,
            *dependencies,
            *decisions,
            *risks,
        ):
            if not item_by_id[claim_id].citations:
                raise FounderCommandV1Denied(
                    "material brief item lacks a citation"
                )
        delta = _delta(projection.items, previous_brief)
        values: dict[str, object] = {
            "workspace_id": self.workspace_id,
            "principal_id": self.principal_id,
            "cadence": cadence,
            "generated_at_ms": now_ms,
            "graph_sha256": projection.graph_sha256,
            "items": projection.items,
            "freshness": freshness,
            "contradictions": contradictions,
            "portfolio": portfolio,
            "known_claim_ids": known,
            "inferred_claim_ids": inferred,
            "unknown_claim_ids": unknown,
            "critical_blocker_claim_ids": blockers,
            "dependency_claim_ids": dependencies,
            "decision_queue_claim_ids": decisions,
            "risk_register_claim_ids": risks,
            "revenue_opportunities": revenue,
            "recommended_top_actions": actions[:3],
            "delta": delta,
            "abstentions": tuple(abstentions),
        }
        brief = FounderCommandBriefV1(
            **values,
            brief_sha256=_brief_sha256(**values),
            read_only=True,
            content_trust="untrusted_data",
        )
        self._projector._attest()
        return brief


def create_founder_command_generator_v1(
    *,
    gate: FounderCommandFeatureGateV1 | None = None,
    projector: CompanyGraphProjectorV1 | None = None,
    policy: FounderFreshnessPolicyV1 = DEFAULT_FRESHNESS_POLICY_V1,
    project_root: Path | str | None = None,
) -> FounderCommandGeneratorV1 | None:
    selected = (
        FounderCommandFeatureGateV1.from_environ()
        if gate is None
        else gate
    )
    if type(selected) is not FounderCommandFeatureGateV1:
        raise FounderCommandV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    _verify_graph_entry(
        Path(__file__).resolve().parents[1]
        if project_root is None
        else project_root
    )
    if projector is None:
        raise FounderCommandV1ContractError(
            "enabled generator requires a graph projector"
        )
    return FounderCommandGeneratorV1(
        construction_key=_CONSTRUCTION_KEY,
        projector=projector,
        policy=policy,
    )


__all__ = [
    "ACCEPTED_GRAPH_ENTRY_ROOTS",
    "ACTION_KINDS",
    "CADENCES",
    "DEFAULT_FRESHNESS_POLICY_V1",
    "ENABLED_VALUE",
    "FEATURE_FLAG",
    "FounderActionCandidateV1",
    "FounderBriefDeltaV1",
    "FounderCommandBriefV1",
    "FounderCommandFeatureGateV1",
    "FounderCommandGeneratorV1",
    "FounderCommandV1ContractError",
    "FounderCommandV1Denied",
    "FounderCommandV1Error",
    "FounderContradictionV1",
    "FounderFreshnessFindingV1",
    "FounderFreshnessPolicyV1",
    "FounderPortfolioProjectV1",
    "FounderPrioritizedActionV1",
    "GOALS",
    "SemanticFreshnessWindowV1",
    "create_founder_command_generator_v1",
]
