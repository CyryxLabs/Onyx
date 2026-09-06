"""Provider-free, read-only A10/A12/A11 intelligence capability adapter."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Final
from urllib.parse import unquote, urlsplit

from core.governance_nucleus_v1 import GovernanceV1ContractError, GovernanceV1Denied
from core.governed_capability_host_v1 import HostBoundCapabilityPortV1
from core.phase7_company_graph_v1 import (
    CompanyGraphAssertionV1,
    CompanyGraphProjectorV1,
)
from core.phase7_founder_command_v1 import (
    FounderActionCandidateV1,
    FounderCommandBriefV1,
    FounderCommandGeneratorV1,
)
from core.phase9_intelligence_ingestion_v1 import IntelligenceIngestionSessionV1
from core.phase9_opportunity_scoring_v1 import OpportunityScoringSessionV1


OPERATIONS: Final = frozenset(
    {"claims.query", "conflicts.query", "opportunities.query", "brief.daily", "brief.weekly"}
)
APPROVED_RIGHTS: Final = frozenset(
    {"internal_authorized", "licensed", "open_license", "owner_created", "public_domain", "public_metadata", "user_owned"}
)
MAX_OUTPUT_ITEMS: Final = 100
MAX_INPUT_ITEMS: Final = 1_000
MAX_TEXT_BYTES: Final = 2_048


@dataclass(frozen=True, slots=True)
class IntelligenceSourceGrantV1:
    """Exact source route admitted to the provider-free projection."""

    source_id: str
    citation: str
    rights: str
    workspace_id: str
    principal_id: str
    fresh_until_ms: int
    revoked: bool = False


def _text(value: object, *, field: str, maximum: int = MAX_TEXT_BYTES) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise GovernanceV1ContractError(f"{field} is invalid")
    if len(value.encode("utf-8")) > maximum:
        raise GovernanceV1ContractError(f"{field} exceeds its bound")
    return value


def _digest(value: object) -> str:
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise GovernanceV1ContractError("intelligence projection is not canonical") from exc
    return hashlib.sha256(encoded).hexdigest()


def _canonical_https(value: str) -> str:
    _text(value, field="citation")
    try:
        parsed = urlsplit(value)
        decoded_path = unquote(parsed.path)
    except (ValueError, UnicodeError) as exc:
        raise GovernanceV1Denied("source route is invalid") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.port not in {None, 443}
        or "\\" in decoded_path
        or any(part == ".." for part in decoded_path.split("/"))
        or parsed.hostname != parsed.hostname.lower()
    ):
        raise GovernanceV1Denied("source redirect or route escape denied")
    return value


class IntelligenceCapabilityPortV1(HostBoundCapabilityPortV1):
    """Chain accepted projections without acquiring provider or action authority."""

    def __init__(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        projector: CompanyGraphProjectorV1,
        founder: FounderCommandGeneratorV1,
        ingestion: IntelligenceIngestionSessionV1,
        scoring: OpportunityScoringSessionV1,
        assertions: tuple[CompanyGraphAssertionV1, ...],
        intelligence_items: tuple[Mapping[str, object], ...] = (),
        opportunities: tuple[Mapping[str, object], ...] = (),
        action_candidates: tuple[FounderActionCandidateV1, ...] = (),
        source_grants: tuple[IntelligenceSourceGrantV1, ...] = (),
        now_ms: Callable[[], int],
        allowed_sensitivities: tuple[str, ...] = ("public", "internal"),
    ) -> None:
        super().__init__()
        _text(workspace_id, field="workspace_id", maximum=256)
        _text(principal_id, field="principal_id", maximum=256)
        if type(projector) is not CompanyGraphProjectorV1:
            raise GovernanceV1ContractError("exact A10 projector is required")
        if type(founder) is not FounderCommandGeneratorV1:
            raise GovernanceV1ContractError("exact A11 founder generator is required")
        if type(ingestion) is not IntelligenceIngestionSessionV1:
            raise GovernanceV1ContractError("exact A12 ingestion session is required")
        if type(scoring) is not OpportunityScoringSessionV1:
            raise GovernanceV1ContractError("exact A12 scoring session is required")
        if not callable(now_ms):
            raise GovernanceV1ContractError("injected clock is required")
        if projector.workspace_id != workspace_id or projector.principal_id != principal_id:
            raise GovernanceV1Denied("A10 workspace or principal binding mismatch")
        if founder.workspace_id != workspace_id or founder.principal_id != principal_id:
            raise GovernanceV1Denied("A11 workspace or principal binding mismatch")
        if type(assertions) is not tuple or len(assertions) > MAX_INPUT_ITEMS or any(
            type(item) is not CompanyGraphAssertionV1 for item in assertions
        ):
            raise GovernanceV1ContractError("assertion input is not closed")
        if any(type(item) is not FounderActionCandidateV1 for item in action_candidates):
            raise GovernanceV1ContractError("action candidate input is not closed")
        if any(not isinstance(item, Mapping) for item in (*intelligence_items, *opportunities)):
            raise GovernanceV1ContractError("A12 inputs must be mappings")
        if len(intelligence_items) > MAX_INPUT_ITEMS or len(opportunities) > MAX_INPUT_ITEMS:
            raise GovernanceV1ContractError("A12 input exceeds its bound")
        if any(type(item) is not IntelligenceSourceGrantV1 for item in source_grants):
            raise GovernanceV1ContractError("exact source grants are required")
        grants = {item.source_id: item for item in source_grants}
        if len(grants) != len(source_grants):
            raise GovernanceV1ContractError("duplicate source grant")
        self._workspace_id = workspace_id
        self._principal_id = principal_id
        self._projector = projector
        self._founder = founder
        self._ingestion = ingestion
        self._scoring = scoring
        self._assertions = assertions
        self._intelligence_items = tuple(dict(item) for item in intelligence_items)
        self._opportunities = tuple(dict(item) for item in opportunities)
        self._actions = action_candidates
        self._grants = grants
        self._now_ms = now_ms
        self._allowed_sensitivities = allowed_sensitivities
        self._lock = RLock()
        self._killed = False

    def _scope(self, arguments: Mapping[str, object]) -> int:
        if set(arguments) != {"workspace_id", "principal_id"}:
            raise GovernanceV1ContractError("intelligence query fields mismatch")
        if arguments.get("workspace_id") != self._workspace_id or arguments.get("principal_id") != self._principal_id:
            raise GovernanceV1Denied("cross-workspace or cross-principal intelligence access denied")
        with self._lock:
            if self._killed:
                raise GovernanceV1Denied("intelligence port kill is latched")
        now = self._now_ms()
        if type(now) is not int or now < 0:
            raise GovernanceV1ContractError("clock result is invalid")
        return now

    def _validate_sources(self, *, now_ms: int) -> None:
        for raw in self._intelligence_items:
            source_id = _text(raw.get("source_id"), field="source_id", maximum=256)
            citation = _canonical_https(_text(raw.get("url"), field="url"))
            grant = self._grants.get(source_id)
            if (
                grant is None
                or grant.workspace_id != self._workspace_id
                or grant.principal_id != self._principal_id
                or grant.rights not in APPROVED_RIGHTS
                or grant.revoked
                or grant.fresh_until_ms < now_ms
                or grant.citation != citation
            ):
                raise GovernanceV1Denied("source rights, provenance, route, or freshness denied")

    @staticmethod
    def _base(*, count: int, digest: str, truncated: bool = False) -> dict[str, object]:
        return {
            "schema": "OnyxIntelligenceProjection.v1",
            "count": min(count, MAX_OUTPUT_ITEMS),
            "truncated": truncated or count > MAX_OUTPUT_ITEMS,
            "projection_digest": digest,
            "redacted": True,
            "read_only": True,
            "advisory_only": True,
            "action_authorized": False,
            "write_authorized": False,
            "dispatch_authorized": False,
            "schedule_authorized": False,
            "provider_dispatch": False,
        }

    def _graph(self, now_ms: int):
        return self._projector.project(
            self._assertions, now_ms=now_ms, allowed_sensitivities=self._allowed_sensitivities
        )

    def _brief(self, now_ms: int, cadence: str) -> FounderCommandBriefV1:
        return self._founder.generate(
            self._assertions,
            now_ms=now_ms,
            allowed_sensitivities=self._allowed_sensitivities,
            cadence=cadence,
            action_candidates=self._actions,
        )

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object]) -> object:
        if operation not in OPERATIONS:
            raise GovernanceV1Denied("unknown intelligence operation")
        now = self._scope(arguments)
        self._validate_sources(now_ms=now)
        graph = self._graph(now)
        ingestion = self._ingestion.ingest(list(self._intelligence_items))
        scores = self._scoring.score_batch(list(self._opportunities))
        canonical_items = tuple(item for item in ingestion.items if item.duplicate_of is None)
        active_ids = {item.claim_id for item in graph.items}
        superseded_ids = {old for old, _new in graph.supersessions}
        conflicts = tuple(
            pair for pair in graph.contradictions if pair[0] in active_ids and pair[1] in active_ids
            and pair[0] not in superseded_ids and pair[1] not in superseded_ids
        )
        if operation == "claims.query":
            value = (graph.graph_sha256, tuple(item.item_id for item in canonical_items))
            return {**self._base(count=len(graph.items) + len(canonical_items), digest=_digest(value)), "empty": not value[1] and not graph.items}
        if operation == "conflicts.query":
            return {**self._base(count=len(conflicts), digest=_digest(conflicts)), "empty": not conflicts, "stale_conflicts_excluded": True}
        if operation == "opportunities.query":
            ranked = tuple(sorted(scores, key=lambda item: (item.rank, item.opportunity_id)))
            advisory = tuple((item.opportunity_id, item.rank, item.total_score, item.band) for item in ranked)
            return {**self._base(count=len(ranked), digest=_digest(advisory)), "empty": not ranked, "ranking": advisory[:MAX_OUTPUT_ITEMS]}
        cadence = "daily" if operation == "brief.daily" else "weekly"
        brief = self._brief(now, cadence)
        return {
            **self._base(count=len(brief.items), digest=brief.brief_sha256),
            "cadence": cadence,
            "empty": not brief.items,
            "abstained": bool(brief.abstentions),
            "recommended_count": min(len(brief.recommended_top_actions), 3),
        }

    def revoke(self, _binding_id: str) -> None:
        return None

    def kill(self) -> bool:
        with self._lock:
            self._killed = True
        return True


__all__ = [
    "APPROVED_RIGHTS",
    "IntelligenceCapabilityPortV1",
    "IntelligenceSourceGrantV1",
    "MAX_OUTPUT_ITEMS",
    "OPERATIONS",
]
