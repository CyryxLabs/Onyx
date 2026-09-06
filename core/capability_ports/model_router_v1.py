"""Provider-free A8 shadow evaluator for model routing policy."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from core.governance_nucleus_v1 import GovernanceV1ContractError

MODALITIES = frozenset({"live", "text"})
PRIVACY_CLASSES = frozenset({"public", "internal", "private"})
DECISION_STATUSES = frozenset({"allowed", "denied", "outage"})
MAX_ROUTES = 32
MAX_FALLBACKS = 8
MAX_IDENTIFIER_LENGTH = 128
OPERATIONS = frozenset({"route.evaluate"})


def _identifier(value: object, field: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_IDENTIFIER_LENGTH
        or value.strip() != value
    ):
        raise GovernanceV1ContractError(f"model router {field} is invalid")
    return value


def _canonical_digest(value: object) -> str:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise GovernanceV1ContractError(
            "model router value is not canonical JSON"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ModelRouteV1:
    """One authority-bearing provider/model route in a sealed policy."""

    provider_id: str
    model_id: str
    modalities: tuple[str, ...]
    privacy_classes: tuple[str, ...]
    max_tokens: int
    max_cost_micro_usd: int

    def __post_init__(self) -> None:
        _identifier(self.provider_id, "provider_id")
        _identifier(self.model_id, "model_id")
        if (
            type(self.modalities) is not tuple
            or not self.modalities
            or len(set(self.modalities)) != len(self.modalities)
            or not set(self.modalities) <= MODALITIES
        ):
            raise GovernanceV1ContractError("model route modalities are invalid")
        if (
            type(self.privacy_classes) is not tuple
            or not self.privacy_classes
            or len(set(self.privacy_classes)) != len(self.privacy_classes)
            or not set(self.privacy_classes) <= PRIVACY_CLASSES
        ):
            raise GovernanceV1ContractError("model route privacy classes are invalid")
        if type(self.max_tokens) is not int or self.max_tokens < 1:
            raise GovernanceV1ContractError("model route token ceiling is invalid")
        if type(self.max_cost_micro_usd) is not int or self.max_cost_micro_usd < 0:
            raise GovernanceV1ContractError("model route cost ceiling is invalid")

    @property
    def key(self) -> tuple[str, str]:
        return self.provider_id, self.model_id


@dataclass(frozen=True, slots=True)
class ModelRoutingPolicyV1:
    """Sealed routing authority; descriptive metadata is intentionally absent."""

    principal_id: str
    workspace_id: str
    generation: int
    routes: tuple[ModelRouteV1, ...]
    max_tokens: int
    max_cost_micro_usd: int

    def __post_init__(self) -> None:
        _identifier(self.principal_id, "principal_id")
        _identifier(self.workspace_id, "workspace_id")
        if type(self.generation) is not int or self.generation < 1:
            raise GovernanceV1ContractError("model policy generation is invalid")
        if (
            type(self.routes) is not tuple
            or not self.routes
            or len(self.routes) > MAX_ROUTES
            or any(type(route) is not ModelRouteV1 for route in self.routes)
            or len({route.key for route in self.routes}) != len(self.routes)
        ):
            raise GovernanceV1ContractError("model policy routes are invalid")
        if type(self.max_tokens) is not int or self.max_tokens < 1:
            raise GovernanceV1ContractError("model policy token ceiling is invalid")
        if type(self.max_cost_micro_usd) is not int or self.max_cost_micro_usd < 0:
            raise GovernanceV1ContractError("model policy cost ceiling is invalid")


@dataclass(frozen=True, slots=True)
class ModelRouteRequestV1:
    """An exact shadow evaluation request containing no prompt content."""

    principal_id: str
    workspace_id: str
    generation: int
    privacy_class: str
    modality: str
    provider_id: str
    model_id: str
    requested_tokens: int
    estimated_cost_micro_usd: int
    explicit_fallbacks: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.principal_id, "principal_id")
        _identifier(self.workspace_id, "workspace_id")
        _identifier(self.provider_id, "provider_id")
        _identifier(self.model_id, "model_id")
        if type(self.generation) is not int or self.generation < 1:
            raise GovernanceV1ContractError("model request generation is invalid")
        if self.privacy_class not in PRIVACY_CLASSES:
            raise GovernanceV1ContractError("model request privacy class is invalid")
        if self.modality not in MODALITIES:
            raise GovernanceV1ContractError("model request modality is invalid")
        if type(self.requested_tokens) is not int or self.requested_tokens < 1:
            raise GovernanceV1ContractError("model request token estimate is invalid")
        if (
            type(self.estimated_cost_micro_usd) is not int
            or self.estimated_cost_micro_usd < 0
        ):
            raise GovernanceV1ContractError("model request cost estimate is invalid")
        if (
            type(self.explicit_fallbacks) is not tuple
            or len(self.explicit_fallbacks) > MAX_FALLBACKS
        ):
            raise GovernanceV1ContractError("model request fallback chain is invalid")
        seen = {(self.provider_id, self.model_id)}
        for fallback in self.explicit_fallbacks:
            if type(fallback) is not tuple or len(fallback) != 2:
                raise GovernanceV1ContractError("model request fallback is invalid")
            key = (
                _identifier(fallback[0], "fallback provider_id"),
                _identifier(fallback[1], "fallback model_id"),
            )
            if key in seen:
                raise GovernanceV1ContractError("model request fallback is duplicated")
            seen.add(key)


@dataclass(frozen=True, slots=True)
class ModelRouteDecisionV1:
    """Bounded, redacted result shared by Live and text evaluations."""

    status: str
    reason_code: str
    modality: str
    selected_provider_id: str | None
    selected_model_id: str | None
    policy_generation: int
    used_explicit_fallback: bool
    policy_digest: str
    request_digest: str
    decision_digest: str
    redacted: bool = True
    shadow_only: bool = True
    provider_called: bool = False


class ModelRouterCapabilityPortV1:
    """Evaluate sealed A8 routing policy without dispatching model providers."""

    def __init__(
        self,
        policy: ModelRoutingPolicyV1,
        *,
        descriptive_config: Mapping[str, object] | None = None,
    ) -> None:
        if type(policy) is not ModelRoutingPolicyV1:
            raise GovernanceV1ContractError("exact ModelRoutingPolicyV1 is required")
        if descriptive_config is not None and not isinstance(
            descriptive_config, Mapping
        ):
            raise GovernanceV1ContractError("descriptive model config must be a mapping")
        self._policy = policy
        self._routes = {route.key: route for route in policy.routes}
        self._policy_digest = _canonical_digest(asdict(policy))
        # Descriptive configuration is validated for shape but deliberately not
        # retained or consulted. It cannot add a provider, model, or authority.

    @property
    def policy_digest(self) -> str:
        return self._policy_digest

    def evaluate(
        self,
        request: ModelRouteRequestV1,
        *,
        available_routes: Sequence[tuple[str, str]],
    ) -> ModelRouteDecisionV1:
        """Return a deterministic shadow decision from an injected snapshot."""

        if type(request) is not ModelRouteRequestV1:
            raise GovernanceV1ContractError("exact ModelRouteRequestV1 is required")
        availability = self._availability(available_routes)
        request_digest = _canonical_digest(asdict(request))
        reason = self._validate_request(request)
        if reason is not None:
            return self._decision(request, request_digest, "denied", reason, None)

        chain = ((request.provider_id, request.model_id),) + request.explicit_fallbacks
        selected = next((key for key in chain if key in availability), None)
        if selected is None:
            return self._decision(
                request, request_digest, "outage", "provider_unavailable", None
            )
        return self._decision(
            request, request_digest, "allowed", "policy_matched", selected
        )

    def _availability(
        self, available_routes: Sequence[tuple[str, str]]
    ) -> frozenset[tuple[str, str]]:
        if isinstance(available_routes, (str, bytes)) or not isinstance(
            available_routes, Sequence
        ):
            raise GovernanceV1ContractError("availability snapshot is invalid")
        if len(available_routes) > MAX_ROUTES:
            raise GovernanceV1ContractError("availability snapshot is too large")
        values: set[tuple[str, str]] = set()
        for item in available_routes:
            if type(item) is not tuple or len(item) != 2:
                raise GovernanceV1ContractError("availability route is invalid")
            values.add(
                (
                    _identifier(item[0], "available provider_id"),
                    _identifier(item[1], "available model_id"),
                )
            )
        return frozenset(values)

    def _validate_request(self, request: ModelRouteRequestV1) -> str | None:
        policy = self._policy
        if (
            request.principal_id != policy.principal_id
            or request.workspace_id != policy.workspace_id
        ):
            return "scope_binding_mismatch"
        if request.generation != policy.generation:
            return "stale_generation"
        chain = ((request.provider_id, request.model_id),) + request.explicit_fallbacks
        routes = [self._routes.get(key) for key in chain]
        if any(route is None for route in routes):
            return "route_not_allowed"
        if any(request.modality not in route.modalities for route in routes if route):
            return "modality_not_allowed"
        if any(
            request.privacy_class not in route.privacy_classes
            for route in routes
            if route
        ):
            return "privacy_not_allowed"
        token_ceiling = min(
            policy.max_tokens, *(route.max_tokens for route in routes if route)
        )
        if request.requested_tokens > token_ceiling:
            return "token_ceiling_exceeded"
        cost_ceiling = min(
            policy.max_cost_micro_usd,
            *(route.max_cost_micro_usd for route in routes if route),
        )
        if request.estimated_cost_micro_usd > cost_ceiling:
            return "cost_ceiling_exceeded"
        return None

    def _decision(
        self,
        request: ModelRouteRequestV1,
        request_digest: str,
        status: str,
        reason_code: str,
        selected: tuple[str, str] | None,
    ) -> ModelRouteDecisionV1:
        if status not in DECISION_STATUSES:
            raise GovernanceV1ContractError("model decision status is invalid")
        public = {
            "status": status,
            "reason_code": reason_code,
            "modality": request.modality,
            "selected_provider_id": None if selected is None else selected[0],
            "selected_model_id": None if selected is None else selected[1],
            "policy_generation": self._policy.generation,
            "used_explicit_fallback": selected is not None
            and selected != (request.provider_id, request.model_id),
            "policy_digest": self._policy_digest,
            "request_digest": request_digest,
            "redacted": True,
            "shadow_only": True,
            "provider_called": False,
        }
        return ModelRouteDecisionV1(
            **public, decision_digest=_canonical_digest(public)
        )


# Short compatibility name for consumers that call the pure evaluator an adapter.
ModelRouterShadowAdapterV1 = ModelRouterCapabilityPortV1

__all__ = [
    "DECISION_STATUSES",
    "MODALITIES",
    "OPERATIONS",
    "PRIVACY_CLASSES",
    "ModelRouteDecisionV1",
    "ModelRouteRequestV1",
    "ModelRouteV1",
    "ModelRouterCapabilityPortV1",
    "ModelRouterShadowAdapterV1",
    "ModelRoutingPolicyV1",
]
