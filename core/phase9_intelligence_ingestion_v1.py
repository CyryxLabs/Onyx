"""Default-off deterministic intelligence ingestion contract for Phase 9.

This first Phase 9 slice implements the PRD ingestion-normalization contract: it
records publication and event time separately, deduplicates recycled stories,
separates each claim into fact/inference/scenario/recommendation, tags source
health, computes temporal freshness, and flags consequential claims that lack
independent corroboration. It is a pure deterministic transform — it fetches no
source, opens no network, calls no model, persists nothing, executes no
recommendation and takes no trading or other action. Live source ingestion,
opportunity scoring, conflicting-claim detection and the licence-gated World
Monitor connector are deliberately out of scope for later gated successors.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Final, Mapping

FEATURE_FLAG: Final = "ONYX_PHASE9_INTELLIGENCE_INGESTION_V1"
ENABLED_VALUE: Final = "true"
CATEGORIES: Final = frozenset(
    {
        "geopolitics",
        "finance_macro",
        "ai_tech_cyber",
        "startups_markets",
        "api_changes",
        "creator_economy",
        "cyryx_opportunity",
    }
)
CLAIM_TYPES: Final = frozenset(
    {"fact", "inference", "scenario", "recommendation"}
)
# Source-health tiers, most to least trusted; the tuple order is the health rank.
SOURCE_TIERS: Final = ("primary", "official", "reputable", "community", "unverified")
MAX_ITEMS: Final = 1_000
MAX_CLAIMS_PER_ITEM: Final = 50
MAX_SOURCE_IDS: Final = 20
MAX_TEXT_BYTES: Final = 4_000
MAX_URL_BYTES: Final = 2_048
MAX_ID_BYTES: Final = 256
_EPOCH0: Final = datetime(1970, 1, 1, tzinfo=timezone.utc)
# Unicode word tokens so non-Latin-script headlines (Cyrillic, CJK, Arabic, …)
# tokenise to their own content instead of collapsing to an empty signature.
_TOKEN = re.compile(r"\w+", re.UNICODE)
_CONSTRUCTION_KEY = object()
ACCEPTED_P8_EXIT_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase8-exit-candidate-v1/manifest.json",
        "8b23754d1d0cbc6f5ec613a5b454ed66cb933cd007fb0c4524f8d92cd8bdfd46",
    ),
    (
        "docs/onyx/acceptance/VE-P8-EXIT-CANDIDATE-V1-E6-001.md",
        "14d680c58ecc5521e2ba902dfc340dc7ad0cf4fed264c5d3bf71a667a208e2d3",
    ),
    (
        "docs/onyx/acceptance/VE-P8-EXIT-CANDIDATE-V1-E6-001.manifest.json",
        "8e1f6fd7b448a6d7a4777d073ec4038a8405a32e0f81b2da6ee871c7a8357204",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P8-EXIT-CANDIDATE-V1-E6-001.sha256",
        "13ea98542ab41bedc59da2261cbf456b1b5bb4c6f8512559c2047b1b7035968b",
    ),
)


class IntelligenceIngestionV1Error(RuntimeError):
    pass


class IntelligenceIngestionV1ContractError(ValueError):
    pass


class IntelligenceIngestionV1Denied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class IntelligenceIngestionFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise IntelligenceIngestionV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "IntelligenceIngestionFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class ClaimV1:
    text: str
    claim_type: str
    consequential: bool
    corroborating_source_ids: tuple[str, ...]
    corroborated: bool


@dataclass(frozen=True, slots=True)
class IntelligenceItemV1:
    item_id: str
    category: str
    source_id: str
    source_tier: str
    url: str
    publication_utc: str
    event_utc: str
    freshness_hours: int
    content_signature: str
    claims: tuple[ClaimV1, ...]
    duplicate_of: str | None


@dataclass(frozen=True, slots=True)
class IngestionResultV1:
    items: tuple[IntelligenceItemV1, ...]
    canonical_count: int
    duplicate_count: int
    uncorroborated_consequential: tuple[tuple[str, int], ...]
    unverified_source_count: int
    by_category: Mapping[str, int]
    generated_at_utc: str


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_P8_EXIT_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise IntelligenceIngestionV1Denied(
                "accepted Phase 8 exit evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise IntelligenceIngestionV1Denied("accepted Phase 8 exit evidence drift")


def _text(value: object, maximum: int, *, field: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise IntelligenceIngestionV1ContractError(f"{field} contract violation")
    if len(value.encode("utf-8")) > maximum:
        raise IntelligenceIngestionV1ContractError(f"{field} contract violation")
    return value


def _utc(value: object, *, field: str) -> tuple[str, int]:
    text = _text(value, 64, field=field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IntelligenceIngestionV1ContractError(f"{field} is not ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    epoch = int((parsed - _EPOCH0).total_seconds())
    return parsed.isoformat(), epoch


def _signature(category: str, title: str) -> str:
    folded = title.casefold()
    tokens = _TOKEN.findall(folded)
    # Fall back to the whitespace-collapsed title when a headline is pure
    # punctuation/emoji, so distinct symbol-only titles do not collapse.
    normalized_title = " ".join(tokens) if tokens else " ".join(folded.split())
    normalized = f"{category}\0{normalized_title}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _claim(raw: object) -> tuple[ClaimV1, tuple[str, ...]]:
    if type(raw) is not dict:
        raise IntelligenceIngestionV1ContractError("claim must be an object")
    text = _text(raw.get("text"), MAX_TEXT_BYTES, field="claim text")
    claim_type = raw.get("claim_type")
    if claim_type not in CLAIM_TYPES:
        raise IntelligenceIngestionV1ContractError("claim_type is not a known type")
    consequential = raw.get("consequential", False)
    if type(consequential) is not bool:
        raise IntelligenceIngestionV1ContractError("consequential must be exact bool")
    raw_sources = raw.get("corroborating_source_ids", [])
    if type(raw_sources) is not list or len(raw_sources) > MAX_SOURCE_IDS:
        raise IntelligenceIngestionV1ContractError("corroborating_source_ids invalid")
    seen: list[str] = []
    for source in raw_sources:
        value = _text(source, MAX_ID_BYTES, field="corroborating source id")
        if value not in seen:
            seen.append(value)
    return (
        ClaimV1(text, claim_type, consequential, tuple(seen), False),
        tuple(seen),
    )


class IntelligenceIngestionSessionV1:
    """Deterministic ingestion normaliser: temporal, dedup, claim typing."""

    __slots__ = ("_now_epoch_s",)

    def __init__(
        self, *, construction_key: object, now_epoch_s: Callable[[], int]
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise IntelligenceIngestionV1ContractError(
                "use create_intelligence_ingestion_v1"
            )
        self._now_epoch_s = now_epoch_s

    def ingest(self, raw_items: object) -> IngestionResultV1:
        if type(raw_items) is not list or len(raw_items) > MAX_ITEMS:
            raise IntelligenceIngestionV1ContractError("raw item batch is invalid")
        now = self._now_epoch_s()
        if type(now) is not int:
            raise IntelligenceIngestionV1ContractError("clock result is invalid")

        parsed: list[dict[str, object]] = []
        seen_ids: set[str] = set()
        for raw in raw_items:
            if type(raw) is not dict:
                raise IntelligenceIngestionV1ContractError("item must be an object")
            item_id = _text(raw.get("item_id"), MAX_ID_BYTES, field="item_id")
            if item_id in seen_ids:
                raise IntelligenceIngestionV1ContractError("duplicate item_id")
            seen_ids.add(item_id)
            category = raw.get("category")
            if category not in CATEGORIES:
                raise IntelligenceIngestionV1ContractError("category is not recognised")
            source_id = _text(raw.get("source_id"), MAX_ID_BYTES, field="source_id")
            source_tier = raw.get("source_tier")
            if source_tier not in SOURCE_TIERS:
                raise IntelligenceIngestionV1ContractError("source_tier is unknown")
            url = _text(raw.get("url"), MAX_URL_BYTES, field="url")
            title = _text(raw.get("title"), MAX_TEXT_BYTES, field="title")
            publication_utc, pub_epoch = _utc(
                raw.get("publication_datetime"), field="publication_datetime"
            )
            if pub_epoch > now:
                raise IntelligenceIngestionV1Denied("publication time is in the future")
            event_utc, _event_epoch = _utc(
                raw.get("event_datetime"), field="event_datetime"
            )
            raw_claims = raw.get("claims", [])
            if type(raw_claims) is not list or len(raw_claims) > MAX_CLAIMS_PER_ITEM:
                raise IntelligenceIngestionV1ContractError("claims block is invalid")
            claims = tuple(_claim(entry)[0] for entry in raw_claims)
            parsed.append(
                {
                    "item_id": item_id,
                    "category": category,
                    "source_id": source_id,
                    "source_tier": source_tier,
                    "url": url,
                    "publication_utc": publication_utc,
                    "pub_epoch": pub_epoch,
                    "event_utc": event_utc,
                    "freshness_hours": (now - pub_epoch) // 3600,
                    "signature": _signature(category, title),
                    "claims": claims,
                }
            )

        by_id = {entry["item_id"]: entry for entry in parsed}
        canonical: dict[str, str] = {}
        for entry in parsed:
            signature = entry["signature"]
            current = canonical.get(signature)
            if current is None:
                canonical[signature] = entry["item_id"]
                continue
            incumbent = by_id[current]
            if (entry["pub_epoch"], entry["item_id"]) < (
                incumbent["pub_epoch"],
                incumbent["item_id"],
            ):
                canonical[signature] = entry["item_id"]

        items: list[IntelligenceItemV1] = []
        uncorroborated: list[tuple[str, int]] = []
        by_category: dict[str, int] = {}
        duplicate_count = 0
        unverified = 0
        for entry in parsed:
            canonical_id = canonical[entry["signature"]]
            duplicate_of = None if canonical_id == entry["item_id"] else canonical_id
            if duplicate_of is not None:
                duplicate_count += 1
            if entry["source_tier"] == "unverified":
                unverified += 1
            by_category[entry["category"]] = by_category.get(entry["category"], 0) + 1
            resolved_claims: list[ClaimV1] = []
            for index, claim in enumerate(entry["claims"]):
                corroborated = any(
                    source != entry["source_id"]
                    for source in claim.corroborating_source_ids
                )
                if claim.consequential and not corroborated:
                    uncorroborated.append((entry["item_id"], index))
                resolved_claims.append(
                    ClaimV1(
                        claim.text,
                        claim.claim_type,
                        claim.consequential,
                        claim.corroborating_source_ids,
                        corroborated,
                    )
                )
            items.append(
                IntelligenceItemV1(
                    entry["item_id"],
                    entry["category"],
                    entry["source_id"],
                    entry["source_tier"],
                    entry["url"],
                    entry["publication_utc"],
                    entry["event_utc"],
                    entry["freshness_hours"],
                    entry["signature"],
                    tuple(resolved_claims),
                    duplicate_of,
                )
            )

        generated = (_EPOCH0 + timedelta(seconds=now)).isoformat()
        return IngestionResultV1(
            tuple(items),
            len(items) - duplicate_count,
            duplicate_count,
            tuple(uncorroborated),
            unverified,
            dict(sorted(by_category.items())),
            generated,
        )


def create_intelligence_ingestion_v1(
    *,
    gate: IntelligenceIngestionFeatureGateV1 | None = None,
    now_epoch_s: Callable[[], int] | None = None,
    project_root: Path | str | None = None,
) -> IntelligenceIngestionSessionV1 | None:
    selected = (
        IntelligenceIngestionFeatureGateV1.from_environ() if gate is None else gate
    )
    if type(selected) is not IntelligenceIngestionFeatureGateV1:
        raise IntelligenceIngestionV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    _verify_entry(
        Path(__file__).resolve().parents[1] if project_root is None else project_root
    )
    if now_epoch_s is None or not callable(now_epoch_s):
        raise IntelligenceIngestionV1ContractError("enabled session requires a clock")
    return IntelligenceIngestionSessionV1(
        construction_key=_CONSTRUCTION_KEY, now_epoch_s=now_epoch_s
    )


__all__ = [
    "CATEGORIES",
    "CLAIM_TYPES",
    "ClaimV1",
    "FEATURE_FLAG",
    "IngestionResultV1",
    "IntelligenceIngestionFeatureGateV1",
    "IntelligenceIngestionSessionV1",
    "IntelligenceIngestionV1ContractError",
    "IntelligenceIngestionV1Denied",
    "IntelligenceIngestionV1Error",
    "IntelligenceItemV1",
    "SOURCE_TIERS",
    "create_intelligence_ingestion_v1",
]
