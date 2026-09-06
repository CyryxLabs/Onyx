"""Default-off content draft and provenance contract for Phase 10.

Fourth Phase 10 (Social organic operating system) slice. It implements the PRD
content-pipeline gates as a pure deterministic, hermetic contract over content
drafts: asset provenance, claim validation, accessibility and a brand/policy
review gate. It calls no model, opens no network, persists nothing and takes no
action.

Governance is structural, not advisory:

* **Asset provenance.** Every asset declares an `AssetKind` and a `source`
  (`original`, `licensed` or `authorized`); a `licensed`/`authorized` asset must
  carry a `rights_ref`. Onyx never uses an asset without a declared right.
* **Claim validation.** A claim marked `validated` must cite an `evidence_ref`.
  A draft can only reach `approved` when every claim is validated — the
  anti-fabrication gate (no fabricated testimonials/stats).
* **Accessibility.** Every visual asset (image/video) must carry `alt_text`.
* **Brand/policy review gate.** A draft reaches `approved` only with an explicit
  positive policy-review record.
* **No publishing.** The status lifecycle stops at `approved`; `published` is not
  representable and there is no publish method. `is_ready_for_calendar` is a
  readiness predicate only — publishing/scheduling is a later gated slice.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

from core.phase10_brand_passport_v1 import PLATFORMS

FEATURE_FLAG: Final = "ONYX_PHASE10_CONTENT_DRAFT_V1"
ENABLED_VALUE: Final = "true"
MAX_ITEMS: Final = 2_000
MAX_ID_BYTES: Final = 256
MAX_TEXT_BYTES: Final = 20_000
ASSET_KINDS: Final = frozenset({"image", "video", "text"})
VISUAL_KINDS: Final = frozenset({"image", "video"})
ASSET_SOURCES: Final = frozenset({"original", "licensed", "authorized"})
RIGHTS_REQUIRED_SOURCES: Final = frozenset({"licensed", "authorized"})
STATUSES: Final = ("draft", "in_review", "approved")
_CONSTRUCTION_KEY = object()

# The accepted Phase 10 provider-connector four-file acceptance tuple. Building a
# draft set is denied unless this frozen predecessor evidence is byte-exact.
ACCEPTED_PROVIDER_CONNECTOR_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase10-provider-connector-v1/manifest.json",
        "87b3ed60dd533f29e3b42447ada20846dda231f8b5f5478da59c9d7e1d822d0c",
    ),
    (
        "docs/onyx/acceptance/VE-P10-PROVIDER-CONNECTOR-V1-E6-001.md",
        "c5a68dc99acb0c102de42c9434907ab6619423efa04e87ab5299bba195043cfe",
    ),
    (
        "docs/onyx/acceptance/VE-P10-PROVIDER-CONNECTOR-V1-E6-001.manifest.json",
        "e84e22f6af91a32a70ee3cb8464aa471c7fada3ab30d5a74ce6cb54bfb77535e",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P10-PROVIDER-CONNECTOR-V1-E6-001.sha256",
        "b2d49c458659af647e844663f470e0510b9f837954f9a358161c7618eb1be6ab",
    ),
)


class ContentDraftV1Error(RuntimeError):
    pass


class ContentDraftV1ContractError(ValueError):
    pass


class ContentDraftV1Denied(PermissionError):
    pass


def _text(value: object, maximum: int, *, field_name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise ContentDraftV1ContractError(f"{field_name} contract violation")
    if len(value.encode("utf-8")) > maximum:
        raise ContentDraftV1ContractError(f"{field_name} contract violation")
    return value


def _optional_text(value: object, maximum: int, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, maximum, field_name=field_name)


def _bool(value: object, *, field_name: str) -> bool:
    if type(value) is not bool:
        raise ContentDraftV1ContractError(f"{field_name} must be exact bool")
    return value


@dataclass(frozen=True, slots=True)
class ContentDraftFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ContentDraftV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ContentDraftFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class AssetProvenanceV1:
    asset_id: str
    kind: str
    source: str
    rights_ref: str | None
    alt_text: str | None


@dataclass(frozen=True, slots=True)
class ContentClaimV1:
    claim_id: str
    claim_text: str
    validated: bool
    evidence_ref: str | None


@dataclass(frozen=True, slots=True)
class ContentDraftV1:
    draft_id: str
    brand_id: str
    platform: str
    body_text: str
    status: str
    disclosure_included: bool
    assets: tuple[AssetProvenanceV1, ...]
    claims: tuple[ContentClaimV1, ...]


@dataclass(frozen=True, slots=True)
class PolicyReviewRecordV1:
    draft_id: str
    approved: bool
    reviewer: str


@dataclass(frozen=True, slots=True)
class ContentDraftSetSnapshotV1:
    drafts: tuple[ContentDraftV1, ...]
    reviews: tuple[PolicyReviewRecordV1, ...]


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_PROVIDER_CONNECTOR_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise ContentDraftV1Denied(
                "accepted provider-connector evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise ContentDraftV1Denied("accepted provider-connector evidence drift")


class ContentDraftSetV1:
    """Deterministic, hermetic content-draft set with provenance/claim/policy gates."""

    __slots__ = ("_drafts", "_reviews")

    def __init__(self, *, construction_key: object) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise ContentDraftV1ContractError("use create_content_draft_set_v1")
        self._drafts: dict[str, ContentDraftV1] = {}
        self._reviews: dict[str, PolicyReviewRecordV1] = {}

    def _load_asset(self, raw: object) -> AssetProvenanceV1:
        if type(raw) is not dict or set(raw) != {
            "asset_id",
            "kind",
            "source",
            "rights_ref",
            "alt_text",
        }:
            raise ContentDraftV1ContractError("asset keys contract violation")
        kind = _text(raw["kind"], MAX_ID_BYTES, field_name="kind")
        if kind not in ASSET_KINDS:
            raise ContentDraftV1ContractError("asset kind is unknown")
        source = _text(raw["source"], MAX_ID_BYTES, field_name="source")
        if source not in ASSET_SOURCES:
            raise ContentDraftV1ContractError("asset source is unknown")
        rights_ref = _optional_text(raw["rights_ref"], MAX_ID_BYTES, field_name="rights_ref")
        if source in RIGHTS_REQUIRED_SOURCES and rights_ref is None:
            raise ContentDraftV1ContractError(
                "licensed/authorized asset requires a rights_ref"
            )
        alt_text = _optional_text(raw["alt_text"], MAX_TEXT_BYTES, field_name="alt_text")
        if kind in VISUAL_KINDS and alt_text is None:
            raise ContentDraftV1ContractError("visual asset requires alt_text")
        return AssetProvenanceV1(
            asset_id=_text(raw["asset_id"], MAX_ID_BYTES, field_name="asset_id"),
            kind=kind,
            source=source,
            rights_ref=rights_ref,
            alt_text=alt_text,
        )

    def _load_claim(self, raw: object) -> ContentClaimV1:
        if type(raw) is not dict or set(raw) != {
            "claim_id",
            "claim_text",
            "validated",
            "evidence_ref",
        }:
            raise ContentDraftV1ContractError("claim keys contract violation")
        validated = _bool(raw["validated"], field_name="validated")
        evidence_ref = _optional_text(
            raw["evidence_ref"], MAX_ID_BYTES, field_name="evidence_ref"
        )
        if validated and evidence_ref is None:
            raise ContentDraftV1ContractError(
                "validated claim requires an evidence_ref"
            )
        return ContentClaimV1(
            claim_id=_text(raw["claim_id"], MAX_ID_BYTES, field_name="claim_id"),
            claim_text=_text(raw["claim_text"], MAX_TEXT_BYTES, field_name="claim_text"),
            validated=validated,
            evidence_ref=evidence_ref,
        )

    def _load_draft(self, raw: object) -> ContentDraftV1:
        if type(raw) is not dict or set(raw) != {
            "draft_id",
            "brand_id",
            "platform",
            "body_text",
            "status",
            "disclosure_included",
            "assets",
            "claims",
        }:
            raise ContentDraftV1ContractError("draft keys contract violation")
        platform = _text(raw["platform"], MAX_ID_BYTES, field_name="platform")
        if platform not in PLATFORMS:
            raise ContentDraftV1ContractError("draft platform is unknown")
        status = _text(raw["status"], MAX_ID_BYTES, field_name="status")
        if status not in STATUSES:
            raise ContentDraftV1ContractError("draft status is unknown")
        assets_raw = raw["assets"]
        claims_raw = raw["claims"]
        if type(assets_raw) not in (list, tuple) or type(claims_raw) not in (list, tuple):
            raise ContentDraftV1ContractError("draft sections must be sequences")
        if len(assets_raw) > MAX_ITEMS or len(claims_raw) > MAX_ITEMS:
            raise ContentDraftV1ContractError("draft exceeds item cap")
        assets: list[AssetProvenanceV1] = []
        seen_assets: set[str] = set()
        for a in assets_raw:
            asset = self._load_asset(a)
            if asset.asset_id in seen_assets:
                raise ContentDraftV1ContractError("duplicate asset_id in draft")
            seen_assets.add(asset.asset_id)
            assets.append(asset)
        claims: list[ContentClaimV1] = []
        seen_claims: set[str] = set()
        for c in claims_raw:
            claim = self._load_claim(c)
            if claim.claim_id in seen_claims:
                raise ContentDraftV1ContractError("duplicate claim_id in draft")
            seen_claims.add(claim.claim_id)
            claims.append(claim)
        return ContentDraftV1(
            draft_id=_text(raw["draft_id"], MAX_ID_BYTES, field_name="draft_id"),
            brand_id=_text(raw["brand_id"], MAX_ID_BYTES, field_name="brand_id"),
            platform=platform,
            body_text=_text(raw["body_text"], MAX_TEXT_BYTES, field_name="body_text"),
            status=status,
            disclosure_included=_bool(
                raw["disclosure_included"], field_name="disclosure_included"
            ),
            assets=tuple(assets),
            claims=tuple(claims),
        )

    def _load_review(self, raw: object) -> PolicyReviewRecordV1:
        if type(raw) is not dict or set(raw) != {"draft_id", "approved", "reviewer"}:
            raise ContentDraftV1ContractError("review keys contract violation")
        return PolicyReviewRecordV1(
            draft_id=_text(raw["draft_id"], MAX_ID_BYTES, field_name="draft_id"),
            approved=_bool(raw["approved"], field_name="approved"),
            reviewer=_text(raw["reviewer"], MAX_TEXT_BYTES, field_name="reviewer"),
        )

    def build(self, plan: object) -> ContentDraftSetSnapshotV1:
        if type(plan) is not dict or set(plan) != {"drafts", "reviews"}:
            raise ContentDraftV1ContractError("plan keys contract violation")
        drafts_raw = plan["drafts"]
        reviews_raw = plan["reviews"]
        if type(drafts_raw) not in (list, tuple) or type(reviews_raw) not in (list, tuple):
            raise ContentDraftV1ContractError("plan sections must be sequences")
        if len(drafts_raw) > MAX_ITEMS or len(reviews_raw) > MAX_ITEMS:
            raise ContentDraftV1ContractError("plan exceeds item cap")

        for raw in drafts_raw:
            draft = self._load_draft(raw)
            if draft.draft_id in self._drafts:
                raise ContentDraftV1ContractError("duplicate draft_id")
            self._drafts[draft.draft_id] = draft

        for raw in reviews_raw:
            review = self._load_review(raw)
            if review.draft_id not in self._drafts:
                raise ContentDraftV1ContractError("review references unknown draft")
            if review.draft_id in self._reviews:
                raise ContentDraftV1ContractError("duplicate review")
            self._reviews[review.draft_id] = review

        # An `approved` draft must have a positive policy review AND every claim
        # validated: the brand/policy review + anti-fabrication gate.
        for draft in self._drafts.values():
            if draft.status == "approved":
                review = self._reviews.get(draft.draft_id)
                if review is None or review.approved is not True:
                    raise ContentDraftV1ContractError(
                        "approved draft without a positive policy review"
                    )
                if any(not claim.validated for claim in draft.claims):
                    raise ContentDraftV1ContractError(
                        "approved draft has an unvalidated claim"
                    )

        return ContentDraftSetSnapshotV1(
            drafts=tuple(self._drafts[key] for key in sorted(self._drafts)),
            reviews=tuple(self._reviews[key] for key in sorted(self._reviews)),
        )

    def is_policy_approved(self, draft_id: str) -> bool:
        review = self._reviews.get(draft_id)
        return review is not None and review.approved is True

    def is_ready_for_calendar(self, draft_id: str) -> bool:
        # Readiness only — this contract never publishes or schedules. A draft is
        # ready to hand to the (separately accepted) editorial calendar when it is
        # approved, policy-reviewed, discloses, every claim is validated and every
        # visual asset has alt text.
        draft = self._drafts.get(draft_id)
        if draft is None:
            return False
        if draft.status != "approved" or not self.is_policy_approved(draft_id):
            return False
        if not draft.disclosure_included:
            return False
        if any(not claim.validated for claim in draft.claims):
            return False
        return all(
            asset.alt_text is not None
            for asset in draft.assets
            if asset.kind in VISUAL_KINDS
        )


def create_content_draft_set_v1(project_root: Path | str) -> ContentDraftSetV1:
    _verify_entry(project_root)
    return ContentDraftSetV1(construction_key=_CONSTRUCTION_KEY)


__all__ = [
    "FEATURE_FLAG",
    "ENABLED_VALUE",
    "ASSET_KINDS",
    "ASSET_SOURCES",
    "STATUSES",
    "ContentDraftFeatureGateV1",
    "AssetProvenanceV1",
    "ContentClaimV1",
    "ContentDraftV1",
    "PolicyReviewRecordV1",
    "ContentDraftSetSnapshotV1",
    "ContentDraftSetV1",
    "ContentDraftV1Error",
    "ContentDraftV1ContractError",
    "ContentDraftV1Denied",
    "create_content_draft_set_v1",
]
