"""Default-off editorial calendar and approval ledger for Phase 10.

Second Phase 10 (Social organic operating system) slice. It implements the PRD
editorial-calendar contract as a pure deterministic, hermetic planner over
posts scheduled against already-authorized social accounts. It calls no model,
opens no network, persists nothing and takes no action.

Governance is structural, not advisory:

* A planned post can only target an account the caller has already vouched for as
  authorized (typically derived from the accepted Phase 10 brand-passport
  inventory's ``is_usable``). Unknown accounts are rejected.
* The status lifecycle stops before publishing. ``draft -> pending_approval ->
  approved -> scheduled`` are the only statuses; ``published`` is not a value
  this contract can represent, because publishing is a later owner-approved,
  access-gated slice.
* Reaching ``approved`` or ``scheduled`` requires an explicit approval record
  (``approved=True``) — this encodes the PRD rule that the first publish per
  account is explicitly approved. ``is_ready_to_publish`` is a *readiness
  predicate* only (approved + scheduled + disclosure + still in the future); it
  never publishes anything.

Time is injected (``now_utc``) rather than read from a clock, so the contract is
fully deterministic and reproducible.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

from core.phase10_brand_passport_v1 import PLATFORMS

FEATURE_FLAG: Final = "ONYX_PHASE10_EDITORIAL_CALENDAR_V1"
ENABLED_VALUE: Final = "true"
MAX_ITEMS: Final = 5_000
MAX_ID_BYTES: Final = 256
MAX_TEXT_BYTES: Final = 8_000
# Fixed status lifecycle. `published` is deliberately absent — this contract can
# plan and approve, but never publish.
STATUSES: Final = ("draft", "pending_approval", "approved", "scheduled")
APPROVAL_REQUIRED_STATUSES: Final = frozenset({"approved", "scheduled"})
_CONSTRUCTION_KEY = object()

# The accepted Phase 10 brand-passport four-file acceptance tuple. Constructing a
# calendar is denied unless this frozen predecessor evidence is byte-exact.
ACCEPTED_BRAND_PASSPORT_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase10-brand-passport-v1/manifest.json",
        "5d0a4bd6c6b3a15b112bb86a95da96a5008b784704f511e3df57ab7043b3af0e",
    ),
    (
        "docs/onyx/acceptance/VE-P10-BRAND-PASSPORT-V1-E6-001.md",
        "1e6f1c94963f8eedf3a362159650651cba789967ac8a4e1e54548f96599d246d",
    ),
    (
        "docs/onyx/acceptance/VE-P10-BRAND-PASSPORT-V1-E6-001.manifest.json",
        "3f21bf082f9f81a699d38fa5658528be94219490b4f894e05e3d2b5a05116cb9",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P10-BRAND-PASSPORT-V1-E6-001.sha256",
        "64dee786a9509c62981e11053da42be238fe1d2bd99765bc76deb8efc176a8bc",
    ),
)


class EditorialCalendarV1Error(RuntimeError):
    pass


class EditorialCalendarV1ContractError(ValueError):
    pass


class EditorialCalendarV1Denied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class EditorialCalendarFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise EditorialCalendarV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "EditorialCalendarFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class PlannedPostV1:
    post_id: str
    account_id: str
    platform: str
    scheduled_utc: int
    status: str
    idempotency_key: str
    disclosure_included: bool


@dataclass(frozen=True, slots=True)
class ApprovalRecordV1:
    post_id: str
    approved: bool
    approver: str


@dataclass(frozen=True, slots=True)
class EditorialCalendarSnapshotV1:
    posts: tuple[PlannedPostV1, ...]
    approvals: tuple[ApprovalRecordV1, ...]


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_BRAND_PASSPORT_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise EditorialCalendarV1Denied(
                "accepted brand-passport evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise EditorialCalendarV1Denied("accepted brand-passport evidence drift")


def _text(value: object, maximum: int, *, field: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise EditorialCalendarV1ContractError(f"{field} contract violation")
    if len(value.encode("utf-8")) > maximum:
        raise EditorialCalendarV1ContractError(f"{field} contract violation")
    return value


def _bool(value: object, *, field: str) -> bool:
    if type(value) is not bool:
        raise EditorialCalendarV1ContractError(f"{field} must be exact bool")
    return value


def _int(value: object, *, field: str) -> int:
    # Reject bool (a subclass of int) and non-ints.
    if type(value) is not int:
        raise EditorialCalendarV1ContractError(f"{field} must be exact int")
    return value


def _id_set(value: object, *, field: str) -> frozenset[str]:
    if type(value) not in (list, tuple, set, frozenset):
        raise EditorialCalendarV1ContractError(f"{field} must be a collection")
    out: set[str] = set()
    for element in value:
        out.add(_text(element, MAX_ID_BYTES, field=field))
    return frozenset(out)


class EditorialCalendarV1:
    """Deterministic, hermetic editorial calendar + approval ledger."""

    __slots__ = ("_authorized", "_now", "_posts", "_approvals")

    def __init__(self, *, construction_key: object) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise EditorialCalendarV1ContractError("use create_editorial_calendar_v1")
        self._authorized: frozenset[str] = frozenset()
        self._now: int = 0
        self._posts: dict[str, PlannedPostV1] = {}
        self._approvals: dict[str, ApprovalRecordV1] = {}

    def _load_post(self, raw: object) -> PlannedPostV1:
        if type(raw) is not dict:
            raise EditorialCalendarV1ContractError("post must be a mapping")
        allowed = {
            "post_id",
            "account_id",
            "platform",
            "scheduled_utc",
            "status",
            "idempotency_key",
            "disclosure_included",
        }
        if set(raw) != allowed:
            raise EditorialCalendarV1ContractError("post keys contract violation")
        platform = _text(raw["platform"], MAX_ID_BYTES, field="platform")
        if platform not in PLATFORMS:
            raise EditorialCalendarV1ContractError("post platform is unknown")
        status = _text(raw["status"], MAX_ID_BYTES, field="status")
        if status not in STATUSES:
            raise EditorialCalendarV1ContractError("post status is unknown")
        scheduled = _int(raw["scheduled_utc"], field="scheduled_utc")
        if scheduled <= self._now:
            raise EditorialCalendarV1ContractError("post is not scheduled in the future")
        return PlannedPostV1(
            post_id=_text(raw["post_id"], MAX_ID_BYTES, field="post_id"),
            account_id=_text(raw["account_id"], MAX_ID_BYTES, field="account_id"),
            platform=platform,
            scheduled_utc=scheduled,
            status=status,
            idempotency_key=_text(
                raw["idempotency_key"], MAX_ID_BYTES, field="idempotency_key"
            ),
            disclosure_included=_bool(
                raw["disclosure_included"], field="disclosure_included"
            ),
        )

    def _load_approval(self, raw: object) -> ApprovalRecordV1:
        if type(raw) is not dict:
            raise EditorialCalendarV1ContractError("approval must be a mapping")
        if set(raw) != {"post_id", "approved", "approver"}:
            raise EditorialCalendarV1ContractError("approval keys contract violation")
        return ApprovalRecordV1(
            post_id=_text(raw["post_id"], MAX_ID_BYTES, field="post_id"),
            approved=_bool(raw["approved"], field="approved"),
            approver=_text(raw["approver"], MAX_TEXT_BYTES, field="approver"),
        )

    def build(self, plan: object) -> EditorialCalendarSnapshotV1:
        if type(plan) is not dict or set(plan) != {
            "authorized_account_ids",
            "now_utc",
            "posts",
            "approvals",
        }:
            raise EditorialCalendarV1ContractError("plan keys contract violation")
        self._now = _int(plan["now_utc"], field="now_utc")
        if self._now < 0:
            raise EditorialCalendarV1ContractError("now_utc must be non-negative")
        self._authorized = _id_set(
            plan["authorized_account_ids"], field="authorized_account_ids"
        )
        posts_raw = plan["posts"]
        approvals_raw = plan["approvals"]
        if type(posts_raw) not in (list, tuple) or type(approvals_raw) not in (
            list,
            tuple,
        ):
            raise EditorialCalendarV1ContractError("plan sections must be sequences")
        if len(posts_raw) > MAX_ITEMS or len(approvals_raw) > MAX_ITEMS:
            raise EditorialCalendarV1ContractError("plan exceeds item cap")

        seen_idempotency: set[str] = set()
        for raw in posts_raw:
            post = self._load_post(raw)
            if post.post_id in self._posts:
                raise EditorialCalendarV1ContractError("duplicate post_id")
            if post.account_id not in self._authorized:
                raise EditorialCalendarV1ContractError(
                    "post targets an unauthorized account"
                )
            if post.idempotency_key in seen_idempotency:
                raise EditorialCalendarV1ContractError("duplicate idempotency_key")
            seen_idempotency.add(post.idempotency_key)
            self._posts[post.post_id] = post

        for raw in approvals_raw:
            approval = self._load_approval(raw)
            if approval.post_id not in self._posts:
                raise EditorialCalendarV1ContractError(
                    "approval references unknown post"
                )
            if approval.post_id in self._approvals:
                raise EditorialCalendarV1ContractError("duplicate approval")
            self._approvals[approval.post_id] = approval

        # A post that claims an approval-required status must carry an explicit
        # positive approval — the first-publish-per-account approval gate.
        for post in self._posts.values():
            if post.status in APPROVAL_REQUIRED_STATUSES:
                record = self._approvals.get(post.post_id)
                if record is None or record.approved is not True:
                    raise EditorialCalendarV1ContractError(
                        "approval-required status without a positive approval"
                    )

        return EditorialCalendarSnapshotV1(
            posts=tuple(self._posts[key] for key in sorted(self._posts)),
            approvals=tuple(
                self._approvals[key] for key in sorted(self._approvals)
            ),
        )

    def is_approved(self, post_id: str) -> bool:
        record = self._approvals.get(post_id)
        return record is not None and record.approved is True

    def is_ready_to_publish(self, post_id: str) -> bool:
        # Readiness only — this contract never publishes. Publishing is a later
        # owner-approved, access-gated slice.
        post = self._posts.get(post_id)
        if post is None:
            return False
        return (
            post.status == "scheduled"
            and self.is_approved(post_id)
            and post.disclosure_included is True
            and post.scheduled_utc > self._now
        )


def create_editorial_calendar_v1(project_root: Path | str) -> EditorialCalendarV1:
    _verify_entry(project_root)
    return EditorialCalendarV1(construction_key=_CONSTRUCTION_KEY)


__all__ = [
    "FEATURE_FLAG",
    "ENABLED_VALUE",
    "STATUSES",
    "APPROVAL_REQUIRED_STATUSES",
    "EditorialCalendarFeatureGateV1",
    "PlannedPostV1",
    "ApprovalRecordV1",
    "EditorialCalendarSnapshotV1",
    "EditorialCalendarV1",
    "EditorialCalendarV1Error",
    "EditorialCalendarV1ContractError",
    "EditorialCalendarV1Denied",
    "create_editorial_calendar_v1",
]
