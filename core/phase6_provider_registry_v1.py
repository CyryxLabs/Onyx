"""Isolated Provider Registry + authenticated health route-plan Candidate 001."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Mapping

from core.phase6_agentic_core_v1 import (
    AdapterStatusV1,
    DataClassV1,
    ModelDescriptorV1,
    ModelRouterV1,
    RouteRequestV1,
)

FEATURE_FLAG: Final = "ONYX_PHASE6_PROVIDER_REGISTRY_V1"
CANDIDATE: Final = "phase6-provider-registry-candidate-001"
SCHEMA_VERSION: Final = 1
MAX_HEALTH_TTL_MS: Final = 300_000
ZERO_DIGEST: Final = "0" * 64
_CONSTRUCTION_KEY = object()
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}\Z")
_ROUTE_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}\Z")
_MODEL_DESCRIPTOR_TYPE = ModelDescriptorV1
_ROUTE_REQUEST_TYPE = RouteRequestV1
_MODEL_ROUTER_TYPE = ModelRouterV1
_DATA_RANK = {
    DataClassV1.PUBLIC: 0,
    DataClassV1.INTERNAL: 1,
    DataClassV1.CONFIDENTIAL: 2,
    DataClassV1.RESTRICTED: 3,
}
_SENSITIVE = frozenset({DataClassV1.CONFIDENTIAL, DataClassV1.RESTRICTED})
_BLOCK_REASONS = frozenset(
    {
        "request_cancelled",
        "registry_empty",
        "privacy_hard_filter",
        "workspace_hard_filter",
        "modality_hard_filter",
        "local_hard_filter",
        "structured_hard_filter",
        "budget_hard_filter",
        "health_unavailable",
        "router_blocked",
    }
)


class ProviderRegistryV1Error(RuntimeError):
    """The isolated provider registry failed safely."""


class ProviderRegistryV1ContractError(ValueError):
    """A registry contract is not exact or canonical."""


class ProviderRegistryV1Denied(PermissionError):
    """Registry authority, lineage or health authentication was denied."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(
        value if isinstance(value, bytes) else _canonical(value)
    ).hexdigest()


def _require_digest(value: object, label: str) -> str:
    if type(value) is not str or _HEX.fullmatch(value) is None:
        raise ProviderRegistryV1ContractError(f"{label} must be a lowercase SHA-256")
    return value


def _require_identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ProviderRegistryV1ContractError(f"{label} is not canonical")
    return value


def _require_route_value(value: object, label: str) -> str:
    if type(value) is not str or _ROUTE_VALUE.fullmatch(value) is None:
        raise ProviderRegistryV1ContractError(f"{label} is not canonical")
    return value


def _require_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProviderRegistryV1ContractError(f"{label} is outside its bound")
    return value


def _authentication_key(value: object) -> bytes:
    if type(value) is not bytes or len(value) != 32:
        raise ProviderRegistryV1ContractError(
            "health authentication key must be exactly 32 bytes"
        )
    return bytes(value)


def _descriptor_payload(descriptor: ModelDescriptorV1) -> dict[str, object]:
    return {
        "adapter_id": descriptor.adapter_id,
        "status": descriptor.status.value,
        "modalities": descriptor.modalities,
        "maximum_data_class": descriptor.maximum_data_class.value,
        "workspace_allowlist": descriptor.workspace_allowlist,
        "local_private": descriptor.local_private,
        "network_required": descriptor.network_required,
        "structured_output": descriptor.structured_output,
        "reliability_milli": descriptor.reliability_milli,
        "latency_millis": descriptor.latency_millis,
        "cost_micro_per_call": descriptor.cost_micro_per_call,
    }


@dataclass(frozen=True, slots=True)
class ProviderRegistryFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ProviderRegistryV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ProviderRegistryFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True, slots=True)
class ProviderRecordV1:
    provider_id: str
    api_version: str
    model_id: str
    record_version: int
    prompt_metadata_digest: str
    evaluation_metadata_digest: str
    descriptor: ModelDescriptorV1

    def __post_init__(self) -> None:
        _require_identifier(self.provider_id, "provider_id")
        _require_route_value(self.api_version, "api_version")
        _require_route_value(self.model_id, "model_id")
        _require_int(self.record_version, "record_version", 1, 2_147_483_647)
        _require_digest(self.prompt_metadata_digest, "prompt_metadata_digest")
        _require_digest(self.evaluation_metadata_digest, "evaluation_metadata_digest")
        if type(self.descriptor) is not _MODEL_DESCRIPTOR_TYPE:
            raise ProviderRegistryV1ContractError("exact ModelDescriptorV1 is required")
        if self.descriptor.modalities != tuple(
            sorted(set(self.descriptor.modalities))
        ) or self.descriptor.workspace_allowlist != tuple(
            sorted(set(self.descriptor.workspace_allowlist))
        ):
            raise ProviderRegistryV1ContractError(
                "descriptor policy tuples must be unique and sorted"
            )
        if self.descriptor.local_private == self.descriptor.network_required:
            raise ProviderRegistryV1ContractError(
                "provider must be exactly local-private or network-backed"
            )

    @property
    def adapter_id(self) -> str:
        return self.descriptor.adapter_id

    @property
    def digest(self) -> str:
        return _digest(
            {
                "schema": "OnyxProviderRecord.v1",
                "provider_id": self.provider_id,
                "api_version": self.api_version,
                "model_id": self.model_id,
                "record_version": self.record_version,
                "prompt_metadata_digest": self.prompt_metadata_digest,
                "evaluation_metadata_digest": self.evaluation_metadata_digest,
                "descriptor": _descriptor_payload(self.descriptor),
            }
        )


class ProviderHealthStatusV1(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"


def _health_payload(
    *,
    adapter_id: str,
    record_version: int,
    sequence: int,
    observed_at_ms: int,
    expires_at_ms: int,
    status: ProviderHealthStatusV1,
    previous_digest: str,
) -> dict[str, object]:
    return {
        "schema": "OnyxProviderHealthObservation.v1",
        "adapter_id": adapter_id,
        "record_version": record_version,
        "sequence": sequence,
        "observed_at_ms": observed_at_ms,
        "expires_at_ms": expires_at_ms,
        "status": status.value,
        "previous_digest": previous_digest,
    }


@dataclass(frozen=True, slots=True)
class ProviderHealthObservationV1:
    adapter_id: str
    record_version: int
    sequence: int
    observed_at_ms: int
    expires_at_ms: int
    status: ProviderHealthStatusV1
    previous_digest: str
    authentication_tag: str

    def __post_init__(self) -> None:
        _require_identifier(self.adapter_id, "adapter_id")
        _require_int(self.record_version, "record_version", 1, 2_147_483_647)
        _require_int(self.sequence, "sequence", 1, 9_223_372_036_854_775_807)
        _require_int(
            self.observed_at_ms, "observed_at_ms", 0, 9_223_372_036_854_775_807
        )
        _require_int(self.expires_at_ms, "expires_at_ms", 1, 9_223_372_036_854_775_807)
        if type(self.status) is not ProviderHealthStatusV1:
            raise ProviderRegistryV1ContractError(
                "exact ProviderHealthStatusV1 is required"
            )
        _require_digest(self.previous_digest, "previous_digest")
        _require_digest(self.authentication_tag, "authentication_tag")
        ttl = self.expires_at_ms - self.observed_at_ms
        if not 1 <= ttl <= MAX_HEALTH_TTL_MS:
            raise ProviderRegistryV1ContractError("health freshness window is invalid")

    @property
    def payload(self) -> dict[str, object]:
        return _health_payload(
            adapter_id=self.adapter_id,
            record_version=self.record_version,
            sequence=self.sequence,
            observed_at_ms=self.observed_at_ms,
            expires_at_ms=self.expires_at_ms,
            status=self.status,
            previous_digest=self.previous_digest,
        )

    @property
    def payload_digest(self) -> str:
        return _digest(self.payload)

    @property
    def digest(self) -> str:
        return _digest(
            {
                "schema": "OnyxAuthenticatedProviderHealth.v1",
                "payload_digest": self.payload_digest,
                "authentication_tag": self.authentication_tag,
            }
        )


def create_provider_health_observation_v1(
    *,
    adapter_id: str,
    record_version: int,
    sequence: int,
    observed_at_ms: int,
    expires_at_ms: int,
    status: ProviderHealthStatusV1,
    previous_digest: str = ZERO_DIGEST,
    authentication_key: bytes,
) -> ProviderHealthObservationV1:
    _require_identifier(adapter_id, "adapter_id")
    _require_int(record_version, "record_version", 1, 2_147_483_647)
    _require_int(sequence, "sequence", 1, 9_223_372_036_854_775_807)
    _require_int(observed_at_ms, "observed_at_ms", 0, 9_223_372_036_854_775_807)
    _require_int(expires_at_ms, "expires_at_ms", 1, 9_223_372_036_854_775_807)
    if type(status) is not ProviderHealthStatusV1:
        raise ProviderRegistryV1ContractError(
            "exact ProviderHealthStatusV1 is required"
        )
    _require_digest(previous_digest, "previous_digest")
    key = _authentication_key(authentication_key)
    payload = _health_payload(
        adapter_id=adapter_id,
        record_version=record_version,
        sequence=sequence,
        observed_at_ms=observed_at_ms,
        expires_at_ms=expires_at_ms,
        status=status,
        previous_digest=previous_digest,
    )
    tag = hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()
    return ProviderHealthObservationV1(
        adapter_id,
        record_version,
        sequence,
        observed_at_ms,
        expires_at_ms,
        status,
        previous_digest,
        tag,
    )


class ProviderRoutePlanStatusV1(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ProviderRouteTargetV1:
    adapter_id: str
    provider_id: str
    api_version: str
    model_id: str
    record_version: int
    provider_record_digest: str
    health_digest: str
    health_status: ProviderHealthStatusV1

    def __post_init__(self) -> None:
        _require_identifier(self.adapter_id, "adapter_id")
        _require_identifier(self.provider_id, "provider_id")
        _require_route_value(self.api_version, "api_version")
        _require_route_value(self.model_id, "model_id")
        _require_int(self.record_version, "record_version", 1, 2_147_483_647)
        _require_digest(self.provider_record_digest, "provider_record_digest")
        _require_digest(self.health_digest, "health_digest")
        if type(self.health_status) is not ProviderHealthStatusV1:
            raise ProviderRegistryV1ContractError(
                "exact ProviderHealthStatusV1 is required"
            )
        if self.health_status not in {
            ProviderHealthStatusV1.AVAILABLE,
            ProviderHealthStatusV1.DEGRADED,
        }:
            raise ProviderRegistryV1ContractError("route target health is not eligible")


@dataclass(frozen=True, slots=True)
class ProviderRoutePlanV1:
    status: ProviderRoutePlanStatusV1
    reason: str
    request_digest: str
    primary: ProviderRouteTargetV1 | None
    fallbacks: tuple[ProviderRouteTargetV1, ...]
    considered: tuple[str, ...]
    exclusion_digest: str

    def __post_init__(self) -> None:
        if type(self.status) is not ProviderRoutePlanStatusV1:
            raise ProviderRegistryV1ContractError(
                "exact ProviderRoutePlanStatusV1 is required"
            )
        _require_identifier(self.reason, "reason")
        _require_digest(self.request_digest, "request_digest")
        _require_digest(self.exclusion_digest, "exclusion_digest")
        if type(self.fallbacks) is not tuple or type(self.considered) is not tuple:
            raise ProviderRegistryV1ContractError(
                "route plan collections must be tuples"
            )
        if tuple(sorted(set(self.considered))) != self.considered:
            raise ProviderRegistryV1ContractError(
                "considered adapters must be unique and sorted"
            )
        if self.status is ProviderRoutePlanStatusV1.READY:
            if type(self.primary) is not ProviderRouteTargetV1:
                raise ProviderRegistryV1ContractError(
                    "ready route plan requires an exact primary target"
                )
            if self.reason != "eligible_routes_ranked":
                raise ProviderRegistryV1ContractError("ready route reason is invalid")
            targets = (self.primary, *self.fallbacks)
            if any(type(item) is not ProviderRouteTargetV1 for item in targets):
                raise ProviderRegistryV1ContractError(
                    "route plan targets must be exact"
                )
            ids = tuple(item.adapter_id for item in targets)
            if len(set(ids)) != len(ids):
                raise ProviderRegistryV1ContractError(
                    "route plan targets are duplicated"
                )
        else:
            if (
                self.primary is not None
                or self.fallbacks
                or self.reason not in _BLOCK_REASONS
            ):
                raise ProviderRegistryV1ContractError(
                    "blocked route plan must not expose a target"
                )

    @property
    def ordered_targets(self) -> tuple[ProviderRouteTargetV1, ...]:
        return () if self.primary is None else (self.primary, *self.fallbacks)


def _request_digest(request: RouteRequestV1) -> str:
    return _digest(
        {
            "schema": "OnyxProviderRouteRequest.v1",
            "workspace_id": request.workspace_id,
            "data_class": request.data_class.value,
            "modality": request.modality,
            "require_local_private": request.require_local_private,
            "require_structured_output": request.require_structured_output,
            "maximum_latency_millis": request.maximum_latency_millis,
            "maximum_cost_micro": request.maximum_cost_micro,
            "minimum_reliability_milli": request.minimum_reliability_milli,
        }
    )


class ProviderRegistryV1:
    """Immutable catalog and pure route planner; never invokes a provider."""

    __slots__ = (
        "_records",
        "_by_adapter",
        "_records_digest",
        "_authentication_key",
        "_authentication_key_digest",
        "_health",
        "_health_snapshots",
    )

    def __init__(
        self,
        *,
        _key: object,
        records: tuple[ProviderRecordV1, ...],
        authentication_key: bytes,
    ) -> None:
        if _key is not _CONSTRUCTION_KEY:
            raise ProviderRegistryV1Denied("registry construction is factory-only")
        if (
            type(records) is not tuple
            or not records
            or len(records) > 64
            or any(type(item) is not ProviderRecordV1 for item in records)
        ):
            raise ProviderRegistryV1ContractError(
                "exact immutable provider record tuple is required"
            )
        adapters = [item.adapter_id for item in records]
        identities = [
            (item.provider_id, item.api_version, item.model_id) for item in records
        ]
        if len(set(adapters)) != len(adapters) or len(set(identities)) != len(
            identities
        ):
            raise ProviderRegistryV1Denied("duplicate provider route is denied")
        self._records = records
        self._by_adapter = {item.adapter_id: item for item in records}
        self._records_digest = self._catalog_digest()
        self._authentication_key = _authentication_key(authentication_key)
        self._authentication_key_digest = _digest(self._authentication_key)
        self._health: dict[str, ProviderHealthObservationV1] = {}
        self._health_snapshots: dict[str, str] = {}

    @property
    def records(self) -> tuple[ProviderRecordV1, ...]:
        self._attest_registry()
        return self._records

    @property
    def digest(self) -> str:
        self._attest_registry()
        return self._records_digest

    def _catalog_digest(self) -> str:
        return _digest(
            {
                "schema": "OnyxProviderRegistry.v1",
                "records": [
                    {"adapter_id": item.adapter_id, "digest": item.digest}
                    for item in self._records
                ],
            }
        )

    def _expected_tag(self, observation: ProviderHealthObservationV1) -> str:
        return hmac.new(
            self._authentication_key,
            _canonical(observation.payload),
            hashlib.sha256,
        ).hexdigest()

    def _attest_registry(self) -> None:
        if (
            ModelDescriptorV1 is not _MODEL_DESCRIPTOR_TYPE
            or RouteRequestV1 is not _ROUTE_REQUEST_TYPE
            or ModelRouterV1 is not _MODEL_ROUTER_TYPE
            or type(self._records) is not tuple
            or any(type(item) is not ProviderRecordV1 for item in self._records)
            or self._catalog_digest() != self._records_digest
            or {item.adapter_id: item for item in self._records} != self._by_adapter
            or type(self._authentication_key) is not bytes
            or len(self._authentication_key) != 32
            or not hmac.compare_digest(
                _digest(self._authentication_key), self._authentication_key_digest
            )
            or type(self._health) is not dict
            or type(self._health_snapshots) is not dict
            or set(self._health) != set(self._health_snapshots)
        ):
            raise ProviderRegistryV1Denied("provider registry drift is denied")
        for adapter_id, observation in self._health.items():
            record = self._by_adapter.get(adapter_id)
            if (
                type(observation) is not ProviderHealthObservationV1
                or record is None
                or observation.record_version != record.record_version
                or not hmac.compare_digest(
                    observation.authentication_tag,
                    self._expected_tag(observation),
                )
                or observation.digest != self._health_snapshots.get(adapter_id)
            ):
                raise ProviderRegistryV1Denied("provider health drift is denied")

    def observe_health(
        self, observation: ProviderHealthObservationV1, *, received_at_ms: int
    ) -> str:
        self._attest_registry()
        if type(observation) is not ProviderHealthObservationV1:
            raise ProviderRegistryV1ContractError(
                "exact ProviderHealthObservationV1 is required"
            )
        _require_int(received_at_ms, "received_at_ms", 0, 9_223_372_036_854_775_807)
        record = self._by_adapter.get(observation.adapter_id)
        if record is None or observation.record_version != record.record_version:
            raise ProviderRegistryV1Denied("health record lineage is unknown")
        if not (
            observation.observed_at_ms <= received_at_ms <= observation.expires_at_ms
        ):
            raise ProviderRegistryV1Denied("stale or future health is denied")
        if not hmac.compare_digest(
            observation.authentication_tag, self._expected_tag(observation)
        ):
            raise ProviderRegistryV1Denied("forged provider health is denied")
        previous = self._health.get(observation.adapter_id)
        expected_sequence = 1 if previous is None else previous.sequence + 1
        expected_previous = ZERO_DIGEST if previous is None else previous.digest
        minimum_time = -1 if previous is None else previous.observed_at_ms
        if (
            observation.sequence != expected_sequence
            or observation.previous_digest != expected_previous
            or observation.observed_at_ms <= minimum_time
        ):
            raise ProviderRegistryV1Denied(
                "replayed or out-of-order provider health is denied"
            )
        self._health[observation.adapter_id] = observation
        self._health_snapshots[observation.adapter_id] = observation.digest
        return observation.digest

    def _blocked(
        self,
        request: RouteRequestV1,
        reason: str,
        considered: tuple[str, ...],
        excluded: Mapping[str, tuple[str, ...]],
    ) -> ProviderRoutePlanV1:
        return ProviderRoutePlanV1(
            ProviderRoutePlanStatusV1.BLOCKED,
            reason,
            _request_digest(request),
            None,
            (),
            considered,
            _digest(
                {
                    "schema": "OnyxProviderRouteExclusions.v1",
                    "reason": reason,
                    "excluded": excluded,
                }
            ),
        )

    def plan_route(
        self,
        request: RouteRequestV1,
        *,
        now_ms: int,
        cancelled: bool = False,
    ) -> ProviderRoutePlanV1:
        self._attest_registry()
        if type(request) is not _ROUTE_REQUEST_TYPE:
            raise ProviderRegistryV1ContractError("exact RouteRequestV1 is required")
        _require_int(now_ms, "now_ms", 0, 9_223_372_036_854_775_807)
        if type(cancelled) is not bool:
            raise ProviderRegistryV1ContractError("cancelled must be exact bool")
        considered = tuple(sorted(self._by_adapter))
        excluded: dict[str, tuple[str, ...]] = {}
        if cancelled:
            return self._blocked(request, "request_cancelled", considered, excluded)
        if not considered:
            return self._blocked(request, "registry_empty", considered, excluded)

        candidates = list(self._records)

        def apply(reason: str, predicate: object) -> ProviderRoutePlanV1 | None:
            nonlocal candidates
            accepted = [item for item in candidates if predicate(item)]
            rejected = tuple(
                sorted(item.adapter_id for item in candidates if item not in accepted)
            )
            if rejected:
                excluded[reason] = rejected
            candidates = accepted
            if not candidates:
                return self._blocked(request, reason, considered, excluded)
            return None

        blocked = apply(
            "privacy_hard_filter",
            lambda item: (
                _DATA_RANK[request.data_class]
                <= _DATA_RANK[item.descriptor.maximum_data_class]
                and (
                    request.data_class not in _SENSITIVE
                    or (
                        item.descriptor.local_private
                        and not item.descriptor.network_required
                    )
                )
            ),
        )
        if blocked:
            return blocked
        blocked = apply(
            "workspace_hard_filter",
            lambda item: request.workspace_id in item.descriptor.workspace_allowlist,
        )
        if blocked:
            return blocked
        blocked = apply(
            "modality_hard_filter",
            lambda item: request.modality in item.descriptor.modalities,
        )
        if blocked:
            return blocked
        blocked = apply(
            "local_hard_filter",
            lambda item: (
                not request.require_local_private
                or (
                    item.descriptor.local_private
                    and not item.descriptor.network_required
                )
            ),
        )
        if blocked:
            return blocked
        blocked = apply(
            "structured_hard_filter",
            lambda item: (
                not request.require_structured_output
                or item.descriptor.structured_output
            ),
        )
        if blocked:
            return blocked
        blocked = apply(
            "budget_hard_filter",
            lambda item: (
                item.descriptor.latency_millis <= request.maximum_latency_millis
                and item.descriptor.cost_micro_per_call <= request.maximum_cost_micro
                and item.descriptor.reliability_milli
                >= request.minimum_reliability_milli
            ),
        )
        if blocked:
            return blocked

        healthy: list[ProviderRecordV1] = []
        rejected_health: list[str] = []
        for item in candidates:
            observation = self._health.get(item.adapter_id)
            if (
                item.descriptor.status is AdapterStatusV1.AVAILABLE_LOCAL
                and observation is not None
                and observation.observed_at_ms <= now_ms <= observation.expires_at_ms
                and observation.status
                in {
                    ProviderHealthStatusV1.AVAILABLE,
                    ProviderHealthStatusV1.DEGRADED,
                }
            ):
                healthy.append(item)
            else:
                rejected_health.append(item.adapter_id)
        if rejected_health:
            excluded["health_unavailable"] = tuple(sorted(rejected_health))
        if not healthy:
            return self._blocked(request, "health_unavailable", considered, excluded)

        remaining = list(healthy)
        ordered: list[ProviderRouteTargetV1] = []
        while remaining:
            decision = _MODEL_ROUTER_TYPE(
                tuple(item.descriptor for item in remaining)
            ).route(request)
            if decision.status != "selected" or decision.adapter_id is None:
                return self._blocked(request, "router_blocked", considered, excluded)
            record = next(
                item for item in remaining if item.adapter_id == decision.adapter_id
            )
            observation = self._health[record.adapter_id]
            ordered.append(
                ProviderRouteTargetV1(
                    record.adapter_id,
                    record.provider_id,
                    record.api_version,
                    record.model_id,
                    record.record_version,
                    record.digest,
                    observation.digest,
                    observation.status,
                )
            )
            remaining.remove(record)
        return ProviderRoutePlanV1(
            ProviderRoutePlanStatusV1.READY,
            "eligible_routes_ranked",
            _request_digest(request),
            ordered[0],
            tuple(ordered[1:]),
            considered,
            _digest(
                {
                    "schema": "OnyxProviderRouteExclusions.v1",
                    "reason": "eligible_routes_ranked",
                    "excluded": excluded,
                }
            ),
        )


def create_provider_registry_v1(
    *,
    gate: ProviderRegistryFeatureGateV1,
    records: tuple[ProviderRecordV1, ...] = (),
    health_authentication_key: bytes = b"",
) -> ProviderRegistryV1 | None:
    if type(gate) is not ProviderRegistryFeatureGateV1:
        raise ProviderRegistryV1ContractError(
            "exact ProviderRegistryFeatureGateV1 is required"
        )
    if not gate.enabled:
        return None
    return ProviderRegistryV1(
        _key=_CONSTRUCTION_KEY,
        records=records,
        authentication_key=health_authentication_key,
    )


__all__ = [
    "CANDIDATE",
    "FEATURE_FLAG",
    "MAX_HEALTH_TTL_MS",
    "ZERO_DIGEST",
    "ProviderHealthObservationV1",
    "ProviderHealthStatusV1",
    "ProviderRecordV1",
    "ProviderRegistryFeatureGateV1",
    "ProviderRegistryV1",
    "ProviderRegistryV1ContractError",
    "ProviderRegistryV1Denied",
    "ProviderRegistryV1Error",
    "ProviderRoutePlanStatusV1",
    "ProviderRoutePlanV1",
    "ProviderRouteTargetV1",
    "create_provider_health_observation_v1",
    "create_provider_registry_v1",
]
