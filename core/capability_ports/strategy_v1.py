"""Provider-free governed projection over the accepted Phase 10 contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, MutableMapping
from dataclasses import asdict, dataclass
from threading import RLock

from core.governance_nucleus_v1 import GovernanceV1ContractError, GovernanceV1Denied
from core.governed_capability_host_v1 import HostBoundCapabilityPortV1
from core.phase10_audience_strategy_v1 import (
    EXPERIMENT_MIN_SAMPLE_FLOOR,
    STRATEGY_HORIZONS,
    AudienceStrategySnapshotV1,
)
from core.phase10_brand_passport_v1 import BrandInventoryV1
from core.phase10_content_draft_v1 import ContentDraftSetSnapshotV1
from core.phase10_editorial_calendar_v1 import EditorialCalendarSnapshotV1

OPERATIONS = frozenset(
    {
        "binding.query",
        "calendar.query",
        "draft.query",
        "audience.query",
        "funnel.query",
        "kpi.query",
        "experiment.query",
        "observation.append",
        "observation.query",
    }
)
MAX_OUTPUT_ITEMS = 100
MAX_ID_BYTES = 256
MAX_SOURCE_BYTES = 8_192
MAX_OBSERVED_VALUE = 1_000_000_000


def _canonical_digest(value: object) -> str:
    def normalize(item: object) -> object:
        if isinstance(item, Mapping):
            return {key: normalize(child) for key, child in item.items()}
        if type(item) in (list, tuple):
            return [normalize(child) for child in item]
        if type(item) in (set, frozenset):
            return sorted(normalize(child) for child in item)
        return item

    try:
        payload = json.dumps(
            normalize(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise GovernanceV1ContractError("strategy source is not canonical JSON") from exc
    return hashlib.sha256(payload).hexdigest()


def _text(value: object, *, field: str, maximum: int = MAX_ID_BYTES) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise GovernanceV1ContractError(f"{field} is invalid")
    if len(value.encode("utf-8")) > maximum:
        raise GovernanceV1ContractError(f"{field} exceeds its bound")
    return value


def _integer(value: object, *, field: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum or value > MAX_OBSERVED_VALUE:
        raise GovernanceV1ContractError(f"{field} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class StrategyAccountBindingV1:
    workspace_id: str
    principal_id: str
    brand_id: str
    account_id: str
    platform: str
    handle: str


class StrategyCapabilityPortV1(HostBoundCapabilityPortV1):
    """Read projections and record evidence; never infer or perform an action."""

    def __init__(
        self,
        *,
        binding: StrategyAccountBindingV1,
        inventory: BrandInventoryV1,
        calendar: EditorialCalendarSnapshotV1,
        drafts: ContentDraftSetSnapshotV1,
        strategy: AudienceStrategySnapshotV1,
        source_digest: str,
        observation_store: MutableMapping[str, Mapping[str, object]],
    ) -> None:
        super().__init__()
        if type(binding) is not StrategyAccountBindingV1:
            raise GovernanceV1ContractError("exact strategy account binding is required")
        exact = (
            (inventory, BrandInventoryV1),
            (calendar, EditorialCalendarSnapshotV1),
            (drafts, ContentDraftSetSnapshotV1),
            (strategy, AudienceStrategySnapshotV1),
        )
        if any(type(value) is not expected for value, expected in exact):
            raise GovernanceV1ContractError("exact Phase 10 snapshots are required")
        if not isinstance(observation_store, MutableMapping):
            raise GovernanceV1ContractError("injected mutable observation store is required")
        for value, field in (
            (binding.workspace_id, "workspace_id"),
            (binding.principal_id, "principal_id"),
            (binding.brand_id, "brand_id"),
            (binding.account_id, "account_id"),
            (binding.platform, "platform"),
            (binding.handle, "handle"),
        ):
            _text(value, field=field)
        supplied_digest = _text(source_digest, field="source_digest")
        computed_digest = _canonical_digest(
            {
                "inventory": asdict(inventory),
                "calendar": asdict(calendar),
                "drafts": asdict(drafts),
                "strategy": asdict(strategy),
            }
        )
        if supplied_digest != computed_digest:
            raise GovernanceV1Denied("Phase 10 source provenance digest mismatch")

        accounts = {account.account_id: account for account in inventory.accounts}
        passports = {passport.brand_id: passport for passport in inventory.passports}
        account = accounts.get(binding.account_id)
        passport = passports.get(binding.brand_id)
        if (
            account is None
            or passport is None
            or account.brand_id != binding.brand_id
            or account.platform != binding.platform
            or account.handle != binding.handle
        ):
            raise GovernanceV1Denied("strategy route and account binding mismatch")
        if not account.authorized or not passport.authorized:
            raise GovernanceV1Denied("strategy account binding is unauthorized")

        self._validate_contract_closure(binding, calendar, drafts, strategy)
        self._binding = binding
        self._calendar = calendar
        self._drafts = drafts
        self._strategy = strategy
        self._source_digest = computed_digest
        self._store = observation_store
        self._lock = RLock()
        self._killed = False

    @staticmethod
    def source_digest(
        inventory: BrandInventoryV1,
        calendar: EditorialCalendarSnapshotV1,
        drafts: ContentDraftSetSnapshotV1,
        strategy: AudienceStrategySnapshotV1,
    ) -> str:
        """Produce the digest callers persist beside the exact source tuple."""
        return _canonical_digest(
            {
                "inventory": asdict(inventory),
                "calendar": asdict(calendar),
                "drafts": asdict(drafts),
                "strategy": asdict(strategy),
            }
        )

    @staticmethod
    def _validate_contract_closure(
        binding: StrategyAccountBindingV1,
        calendar: EditorialCalendarSnapshotV1,
        drafts: ContentDraftSetSnapshotV1,
        strategy: AudienceStrategySnapshotV1,
    ) -> None:
        approvals = {item.post_id: item for item in calendar.approvals}
        seen_orders: set[int] = set()
        kpis = {item.kpi_id: item for item in strategy.kpis}
        if len(kpis) != len(strategy.kpis):
            raise GovernanceV1ContractError("duplicate KPI key")
        for post in calendar.posts:
            if post.account_id != binding.account_id or post.platform != binding.platform:
                raise GovernanceV1Denied("calendar route and account mismatch")
            if post.status in {"approved", "scheduled"}:
                approval = approvals.get(post.post_id)
                if approval is None or approval.approved is not True:
                    raise GovernanceV1Denied("approval-required calendar state is unapproved")
        reviews = {item.draft_id: item for item in drafts.reviews}
        for draft in drafts.drafts:
            if draft.brand_id != binding.brand_id or draft.platform != binding.platform:
                raise GovernanceV1Denied("draft route and account mismatch")
            if any(claim.validated and not claim.evidence_ref for claim in draft.claims):
                raise GovernanceV1ContractError("validated claim lacks provenance")
            if draft.status == "approved":
                review = reviews.get(draft.draft_id)
                if review is None or review.approved is not True:
                    raise GovernanceV1Denied("approved draft lacks policy approval")
        for segment in strategy.segments:
            if segment.brand_id != binding.brand_id or segment.platform != binding.platform:
                raise GovernanceV1Denied("audience route and account mismatch")
            if not segment.claims or any(
                claim.platform != segment.platform or not claim.source_ref
                for claim in segment.claims
            ):
                raise GovernanceV1ContractError("audience research provenance is not closed")
        for kpi in strategy.kpis:
            if kpi.platform != binding.platform or kpi.horizon_days not in STRATEGY_HORIZONS:
                raise GovernanceV1ContractError("KPI key or horizon is not closed")
        for stage in strategy.funnel:
            if stage.order in seen_orders or any(key not in kpis for key in stage.kpi_ids):
                raise GovernanceV1ContractError("funnel ordering or KPI closure violation")
            seen_orders.add(stage.order)
        if tuple(item.order for item in strategy.funnel) != tuple(sorted(seen_orders)):
            raise GovernanceV1ContractError("funnel projection is not ordered")
        for experiment in strategy.experiments:
            if experiment.platform != binding.platform:
                raise GovernanceV1Denied("experiment route and account mismatch")
            if experiment.min_sample < EXPERIMENT_MIN_SAMPLE_FLOOR:
                raise GovernanceV1ContractError("experiment sample floor violation")
            if experiment.winner_declared and experiment.observed_sample < experiment.min_sample:
                raise GovernanceV1ContractError("unsupported experiment winner")

    def _authorize_scope(self, arguments: Mapping[str, object]) -> None:
        if (
            arguments.get("workspace_id") != self._binding.workspace_id
            or arguments.get("principal_id") != self._binding.principal_id
        ):
            raise GovernanceV1Denied("cross-workspace or cross-principal strategy access denied")
        if self._killed:
            raise GovernanceV1Denied("strategy port kill is latched")

    def _base_result(self, *, count: int) -> dict[str, object]:
        return {
            "schema": "OnyxStrategyProjection.v1",
            "count": min(count, MAX_OUTPUT_ITEMS),
            "truncated": count > MAX_OUTPUT_ITEMS,
            "source_digest": self._source_digest,
            "redacted": True,
            "action_authorized": False,
            "publication_authorized": False,
            "spend_authorized": False,
        }

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object]) -> object:
        self._authorize_scope(arguments)
        if operation not in OPERATIONS:
            raise GovernanceV1Denied("unknown strategy operation")
        if operation == "observation.append":
            return self._append_observation(arguments)
        if operation == "observation.query":
            return self._query_observations(arguments)
        allowed = {"workspace_id", "principal_id"}
        if operation in {"calendar.query", "draft.query", "kpi.query", "experiment.query"}:
            allowed.add({
                "calendar.query": "post_id",
                "draft.query": "draft_id",
                "kpi.query": "kpi_id",
                "experiment.query": "experiment_id",
            }[operation])
        if set(arguments) != allowed:
            raise GovernanceV1ContractError("strategy query fields mismatch")
        if operation == "binding.query":
            return {**self._base_result(count=1), "bound": True}
        if operation == "audience.query":
            return self._base_result(count=len(self._strategy.segments))
        if operation == "funnel.query":
            return {**self._base_result(count=len(self._strategy.funnel)), "ordered": True}
        key_name, values = {
            "calendar.query": ("post_id", self._calendar.posts),
            "draft.query": ("draft_id", self._drafts.drafts),
            "kpi.query": ("kpi_id", self._strategy.kpis),
            "experiment.query": ("experiment_id", self._strategy.experiments),
        }[operation]
        requested = _text(arguments[key_name], field=key_name)
        found = next((item for item in values if getattr(item, key_name) == requested), None)
        result = {**self._base_result(count=int(found is not None)), "found": found is not None}
        if operation == "calendar.query" and found is not None:
            approval = next((a for a in self._calendar.approvals if a.post_id == found.post_id), None)
            result["calendar_ready"] = bool(
                found.status == "scheduled"
                and found.disclosure_included
                and approval is not None
                and approval.approved is True
            )
        if operation == "draft.query" and found is not None:
            review = next((r for r in self._drafts.reviews if r.draft_id == found.draft_id), None)
            result["draft_valid"] = bool(
                found.status == "approved"
                and found.disclosure_included
                and review is not None
                and review.approved is True
                and all(claim.validated and claim.evidence_ref for claim in found.claims)
            )
        if operation == "experiment.query" and found is not None:
            result["sample_floor_met"] = found.observed_sample >= found.min_sample
        return result

    def _append_observation(self, arguments: Mapping[str, object]) -> dict[str, object]:
        expected = {
            "workspace_id", "principal_id", "observation_id", "account_id",
            "kpi_id", "horizon_days", "observed_value", "sample_size",
            "observed_at", "source_ref", "source_payload", "source_digest",
        }
        if set(arguments) != expected:
            raise GovernanceV1ContractError("observation fields mismatch")
        observation_id = _text(arguments["observation_id"], field="observation_id")
        if arguments["account_id"] != self._binding.account_id:
            raise GovernanceV1Denied("observation account route mismatch")
        kpi_id = _text(arguments["kpi_id"], field="kpi_id")
        kpi = next((item for item in self._strategy.kpis if item.kpi_id == kpi_id), None)
        horizon = _integer(arguments["horizon_days"], field="horizon_days")
        if kpi is None or horizon != kpi.horizon_days:
            raise GovernanceV1ContractError("observation KPI key or horizon is not closed")
        sample_size = _integer(arguments["sample_size"], field="sample_size")
        if sample_size < EXPERIMENT_MIN_SAMPLE_FLOOR:
            raise GovernanceV1ContractError("observation sample floor violation")
        source_ref = _text(arguments["source_ref"], field="source_ref")
        source_payload = _text(
            arguments["source_payload"], field="source_payload", maximum=MAX_SOURCE_BYTES
        )
        source_digest = _text(arguments["source_digest"], field="source_digest")
        if source_digest != hashlib.sha256(source_payload.encode("utf-8")).hexdigest():
            raise GovernanceV1Denied("observation source provenance digest mismatch")
        record = {
            "workspace_id": self._binding.workspace_id,
            "principal_id": self._binding.principal_id,
            "observation_id": observation_id,
            "account_id": self._binding.account_id,
            "kpi_id": kpi_id,
            "horizon_days": horizon,
            "observed_value": _integer(arguments["observed_value"], field="observed_value"),
            "sample_size": sample_size,
            "observed_at": _integer(arguments["observed_at"], field="observed_at"),
            "source_ref": source_ref,
            "source_digest": source_digest,
        }
        record_digest = _canonical_digest(record)
        store_key = f"{self._binding.workspace_id}:{self._binding.principal_id}:{observation_id}"
        with self._lock:
            existing = self._store.get(store_key)
            if existing is not None:
                if existing.get("record_digest") == record_digest:
                    return {**self._base_result(count=1), "status": "replayed"}
                raise GovernanceV1Denied("observation replay payload mismatch")
            for saved in self._store.values():
                if (
                    saved.get("workspace_id") == self._binding.workspace_id
                    and saved.get("principal_id") == self._binding.principal_id
                    and saved.get("account_id") == self._binding.account_id
                    and saved.get("kpi_id") == kpi_id
                    and int(saved.get("observed_at", -1)) >= record["observed_at"]
                ):
                    raise GovernanceV1Denied("stale observation append denied")
            self._store[store_key] = {**record, "record_digest": record_digest}
        return {**self._base_result(count=1), "status": "appended"}

    def _query_observations(self, arguments: Mapping[str, object]) -> dict[str, object]:
        if set(arguments) != {"workspace_id", "principal_id", "kpi_id"}:
            raise GovernanceV1ContractError("observation query fields mismatch")
        kpi_id = _text(arguments["kpi_id"], field="kpi_id")
        if not any(item.kpi_id == kpi_id for item in self._strategy.kpis):
            raise GovernanceV1ContractError("unknown KPI key")
        with self._lock:
            count = sum(
                1 for item in self._store.values()
                if item.get("workspace_id") == self._binding.workspace_id
                and item.get("principal_id") == self._binding.principal_id
                and item.get("account_id") == self._binding.account_id
                and item.get("kpi_id") == kpi_id
            )
        return {**self._base_result(count=count), "has_metric": count > 0}

    def revoke(self, binding_id: str) -> None:
        _text(binding_id, field="binding_id")

    def kill(self) -> bool:
        with self._lock:
            self._killed = True
        return True


__all__ = ["OPERATIONS", "StrategyAccountBindingV1", "StrategyCapabilityPortV1"]
