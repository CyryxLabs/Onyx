"""Default-off Phase 6 agentic planning facade for Onyx.

This module deliberately does *not* introduce another mission executor.  It
validates provider/model proposals, persists a bounded plan/evidence projection
and delegates all executable provider-free work to :class:`MissionStore`.
Phase 5 remains the only future authority for ``local_catalog_read``.  External
model and coding-agent adapters are contracts only in V1: they make no network
or subprocess calls and cannot claim availability.

The module has no startup import or live wiring.  Construction requires the
strict ``ONYX_PHASE6_AGENTIC_CORE_V1=true`` opt-in plus an explicit sidecar path.
"""

from __future__ import annotations

import hashlib
import json
import math
import queue
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from core.missions import (
    InvalidTransition,
    Mission,
    MissionError,
    MissionStore,
    ToolRunner,
    redact,
)
from core.mission_tools import run as run_mission_tool
from core.permission_broker import MISSION_TOOL_POLICIES


FEATURE_FLAG = "ONYX_PHASE6_AGENTIC_CORE_V1"
SCHEMA_VERSION = 1
MAX_PLAN_BYTES = 128_000
MAX_ARGUMENT_BYTES = 32_000
MAX_STEPS = 50
MAX_EVENTS_PER_PLAN = 2_000
MAX_EVIDENCE_RECEIPTS = 500
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
_REQUEST_KEY = re.compile(r"^[A-Za-z0-9_.:-]{8,192}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SECRET_KEY = re.compile(
    r"(?i)^(api.?key|authorization|bearer|cookie|credential|password|private.?key|secret|token)$"
)


class AgenticCoreV1Error(RuntimeError):
    """Base error with intentionally non-sensitive messages."""


class AgenticCoreV1ContractError(ValueError):
    """A typed plan, route or adapter contract is invalid."""


class AgenticCoreV1Denied(PermissionError):
    """The host policy rejected a proposal or execution request."""


class AgenticCoreV1Unavailable(AgenticCoreV1Error):
    """A declared but unintegrated capability is unavailable."""


def _exact_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise AgenticCoreV1ContractError(f"{label} must be an exact boolean")
    return value


def _text(value: object, label: str, maximum: int, *, empty: bool = False) -> str:
    if type(value) is not str:
        raise AgenticCoreV1ContractError(f"{label} must be text")
    normalized = value.strip()
    if (not empty and not normalized) or len(normalized) > maximum or "\x00" in normalized:
        raise AgenticCoreV1ContractError(f"{label} is invalid")
    return normalized


def _identifier(value: object, label: str) -> str:
    normalized = _text(value, label, 128)
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise AgenticCoreV1ContractError(f"{label} is not canonical")
    return normalized


def _bounded_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise AgenticCoreV1ContractError(f"{label} is outside its bound")
    return value


def _bounded_float(value: object, label: str, minimum: float, maximum: float) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        raise AgenticCoreV1ContractError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise AgenticCoreV1ContractError(f"{label} is outside its bound")
    return result


def _canonical_json(value: object, label: str, maximum: int = MAX_ARGUMENT_BYTES) -> str:
    def validate(item: object, depth: int = 0) -> None:
        if depth > 16:
            raise AgenticCoreV1ContractError(f"{label} is too deeply nested")
        if item is None or type(item) in {bool, int, str}:
            if type(item) is str and (len(item) > 16_384 or "\x00" in item):
                raise AgenticCoreV1ContractError(f"{label} text is invalid")
            return
        if type(item) is float:
            if not math.isfinite(item):
                raise AgenticCoreV1ContractError(f"{label} contains a non-finite number")
            return
        if type(item) is list:
            if len(item) > 256:
                raise AgenticCoreV1ContractError(f"{label} contains too many items")
            for child in item:
                validate(child, depth + 1)
            return
        if type(item) is dict:
            if len(item) > 128:
                raise AgenticCoreV1ContractError(f"{label} contains too many fields")
            for key, child in item.items():
                if type(key) is not str or not key or len(key) > 128 or _SECRET_KEY.search(key):
                    raise AgenticCoreV1ContractError(f"{label} contains a forbidden field")
                validate(child, depth + 1)
            return
        raise AgenticCoreV1ContractError(f"{label} contains an unsupported value")

    validate(value)
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError):
        raise AgenticCoreV1ContractError(f"{label} is not canonical JSON") from None
    if len(encoded.encode("utf-8")) > maximum:
        raise AgenticCoreV1ContractError(f"{label} exceeds its byte budget")
    return encoded


def _canonical_arguments(value: object) -> str:
    if redact(value) != value:
        raise AgenticCoreV1ContractError(
            "arguments contain sensitive or untrusted instruction data"
        )
    return _canonical_json(value, "arguments")


def _non_sensitive_text(value: object, label: str, maximum: int) -> str:
    result = _text(value, label, maximum)
    if redact(result) != result:
        raise AgenticCoreV1ContractError(
            f"{label} contains sensitive or untrusted instruction data"
        )
    return result


def _sha(value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def _now() -> float:
    return time.time()


class RiskLevelV1(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EffectClassV1(str, Enum):
    DATA_ONLY = "data_only"
    LOCAL_READ = "local_read"
    EXTERNAL_READ = "external_read"
    LOCAL_WRITE = "local_write"
    EXTERNAL_MUTATION = "external_mutation"
    DESTRUCTIVE = "destructive"


class DataClassV1(str, Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class PlanStateV1(str, Enum):
    PLANNED = "planned"
    WAITING_FOR_PHASE5 = "waiting_for_phase5"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    VERIFYING = "verifying"
    COMPLETE = "complete"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AdapterStatusV1(str, Enum):
    AVAILABLE_LOCAL = "available_local"
    DECLARED_DISABLED = "declared_disabled"
    BLOCKED_BY_ACCESS = "blocked_by_access"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    UNAVAILABLE = "unavailable"


_DATA_RANK = {
    DataClassV1.PUBLIC: 0,
    DataClassV1.INTERNAL: 1,
    DataClassV1.CONFIDENTIAL: 2,
    DataClassV1.RESTRICTED: 3,
}


@dataclass(frozen=True)
class AgenticFeatureGateV1:
    enabled: bool = False

    def __post_init__(self) -> None:
        _exact_bool(self.enabled, "feature gate")

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> "AgenticFeatureGateV1":
        source = {} if environ is None else environ
        value = source.get(FEATURE_FLAG, "")
        return cls(type(value) is str and value.strip().lower() == "true")


@dataclass(frozen=True)
class MissionBudgetV1:
    max_steps: int = 25
    wall_seconds: float = 900.0
    max_retries_per_step: int = 2
    max_repair_cycles: int = 2
    max_tokens: int = 0
    max_api_calls: int = 0
    max_compute_seconds: float = 900.0
    max_cost_micro: int = 0

    def __post_init__(self) -> None:
        _bounded_int(self.max_steps, "max_steps", 1, MAX_STEPS)
        _bounded_float(self.wall_seconds, "wall_seconds", 0.01, 86_400.0)
        _bounded_int(self.max_retries_per_step, "max_retries_per_step", 0, 20)
        _bounded_int(self.max_repair_cycles, "max_repair_cycles", 0, 3)
        _bounded_int(self.max_tokens, "max_tokens", 0, 10_000_000)
        _bounded_int(self.max_api_calls, "max_api_calls", 0, 10_000)
        _bounded_float(self.max_compute_seconds, "max_compute_seconds", 0.01, 86_400.0)
        _bounded_int(self.max_cost_micro, "max_cost_micro", 0, 1_000_000_000)
        if self.max_cost_micro != 0 or self.max_api_calls != 0 or self.max_tokens != 0:
            raise AgenticCoreV1ContractError(
                "V1 executes provider-free plans only; paid/token/API budgets must be zero"
            )

    def payload(self) -> dict[str, object]:
        return {
            "max_steps": self.max_steps,
            "wall_seconds": self.wall_seconds,
            "max_retries_per_step": self.max_retries_per_step,
            "max_repair_cycles": self.max_repair_cycles,
            "max_tokens": self.max_tokens,
            "max_api_calls": self.max_api_calls,
            "max_compute_seconds": self.max_compute_seconds,
            "max_cost_micro": self.max_cost_micro,
        }


@dataclass(frozen=True)
class GoalV1:
    goal_id: str
    correlation_id: str
    workspace_id: str
    objective: str
    definition_of_done: tuple[str, ...]
    scope: tuple[str, ...]
    exclusions: tuple[str, ...]
    data_class: DataClassV1
    budget: MissionBudgetV1

    def __post_init__(self) -> None:
        _identifier(self.goal_id, "goal_id")
        _identifier(self.correlation_id, "correlation_id")
        _identifier(self.workspace_id, "workspace_id")
        _non_sensitive_text(self.objective, "objective", 2_000)
        if type(self.data_class) is not DataClassV1 or type(self.budget) is not MissionBudgetV1:
            raise AgenticCoreV1ContractError("goal classification or budget is invalid")
        for label, values, maximum in (
            ("definition_of_done", self.definition_of_done, 32),
            ("scope", self.scope, 64),
            ("exclusions", self.exclusions, 64),
        ):
            if type(values) is not tuple or not values or len(values) > maximum:
                raise AgenticCoreV1ContractError(f"{label} is invalid")
            normalized = tuple(_non_sensitive_text(item, label, 512) for item in values)
            if normalized != values or len(set(values)) != len(values):
                raise AgenticCoreV1ContractError(f"{label} is not canonical")

    def payload(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "correlation_id": self.correlation_id,
            "workspace_id": self.workspace_id,
            "objective": self.objective,
            "definition_of_done": list(self.definition_of_done),
            "scope": list(self.scope),
            "exclusions": list(self.exclusions),
            "data_class": self.data_class.value,
            "budget": self.budget.payload(),
        }


@dataclass(frozen=True)
class WorkspaceScopeV1:
    workspace_id: str
    allowed_roots: tuple[str, ...]
    maximum_data_class: DataClassV1

    def __post_init__(self) -> None:
        _identifier(self.workspace_id, "workspace_id")
        if type(self.allowed_roots) is not tuple or not self.allowed_roots or len(self.allowed_roots) > 32:
            raise AgenticCoreV1ContractError("workspace root allowlist is invalid")
        normalized: list[str] = []
        for item in self.allowed_roots:
            value = _text(item, "workspace root", 2_048)
            if not Path(value).is_absolute():
                raise AgenticCoreV1ContractError("workspace root must be absolute")
            normalized.append(value)
        if tuple(normalized) != self.allowed_roots or len(set(normalized)) != len(normalized):
            raise AgenticCoreV1ContractError("workspace roots are not canonical")
        if type(self.maximum_data_class) is not DataClassV1:
            raise AgenticCoreV1ContractError("workspace data class is invalid")


@dataclass(frozen=True)
class CapabilityPolicyV1:
    capability_id: str
    mission_tool: str | None
    operation: str
    executor: str
    risk: RiskLevelV1
    effect: EffectClassV1
    approval_required: bool
    provider_free: bool

    def __post_init__(self) -> None:
        _identifier(self.capability_id, "capability_id")
        _identifier(self.operation, "operation")
        if self.mission_tool is not None:
            _identifier(self.mission_tool, "mission_tool")
        if self.executor not in {"mission_store", "phase5"}:
            raise AgenticCoreV1ContractError("capability executor is invalid")
        if type(self.risk) is not RiskLevelV1 or type(self.effect) is not EffectClassV1:
            raise AgenticCoreV1ContractError("capability labels are invalid")
        _exact_bool(self.approval_required, "approval_required")
        _exact_bool(self.provider_free, "provider_free")


_CAPABILITIES: dict[str, CapabilityPolicyV1] = {
    name: CapabilityPolicyV1(
        capability_id=f"local.{name}",
        mission_tool=name,
        operation="read",
        executor="mission_store",
        risk=RiskLevelV1.LOW,
        effect=EffectClassV1.LOCAL_READ,
        approval_required=False,
        provider_free=True,
    )
    for name in (
        "workspace_inventory",
        "workspace_text_search",
        "workspace_read_text",
        "workspace_hash",
        "local_system_status",
        "readiness_summary",
    )
}
_CAPABILITIES["local_catalog_read"] = CapabilityPolicyV1(
    capability_id="local.catalog",
    mission_tool=None,
    operation="catalog_read",
    executor="phase5",
    risk=RiskLevelV1.LOW,
    effect=EffectClassV1.LOCAL_READ,
    approval_required=False,
    provider_free=True,
)


def capability_policy_v1(name: str) -> CapabilityPolicyV1:
    canonical = _identifier(name, "capability")
    policy = _CAPABILITIES.get(canonical)
    if policy is None:
        raise AgenticCoreV1Denied("capability is not admitted by Phase 6 V1")
    if policy.mission_tool is not None and policy.mission_tool not in MISSION_TOOL_POLICIES:
        raise AgenticCoreV1Unavailable("stable mission-tool policy is unavailable")
    return policy


@dataclass(frozen=True)
class StepV1:
    step_id: str
    capability: str
    operation: str
    arguments_json: str
    dependencies: tuple[str, ...]
    operator_id: str
    risk: RiskLevelV1
    effect: EffectClassV1
    approval_required: bool
    timeout_seconds: float
    max_retries: int
    postconditions: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.step_id, "step_id")
        policy = capability_policy_v1(self.capability)
        if self.operation != policy.operation:
            raise AgenticCoreV1Denied("operation does not match host capability policy")
        if type(self.arguments_json) is not str or _canonical_arguments(
            json.loads(self.arguments_json)
        ) != self.arguments_json:
            raise AgenticCoreV1ContractError("step arguments are not canonical")
        if type(self.dependencies) is not tuple or len(self.dependencies) > MAX_STEPS:
            raise AgenticCoreV1ContractError("step dependencies are invalid")
        for item in self.dependencies:
            _identifier(item, "dependency")
        if len(set(self.dependencies)) != len(self.dependencies) or self.step_id in self.dependencies:
            raise AgenticCoreV1ContractError("step dependencies are not canonical")
        _identifier(self.operator_id, "operator_id")
        if self.risk is not policy.risk or self.effect is not policy.effect:
            raise AgenticCoreV1Denied("model-provided risk or effect label cannot change host policy")
        if self.approval_required is not policy.approval_required:
            raise AgenticCoreV1Denied("model-provided approval label cannot change host policy")
        _bounded_float(self.timeout_seconds, "timeout_seconds", 0.01, 3_600.0)
        _bounded_int(self.max_retries, "max_retries", 0, 20)
        if type(self.postconditions) is not tuple or not self.postconditions or len(self.postconditions) > 16:
            raise AgenticCoreV1ContractError("postconditions are invalid")
        for item in self.postconditions:
            _identifier(item, "postcondition")
        if len(set(self.postconditions)) != len(self.postconditions):
            raise AgenticCoreV1ContractError("postconditions are not canonical")

    @property
    def arguments(self) -> dict[str, object]:
        value = json.loads(self.arguments_json)
        assert isinstance(value, dict)
        return value

    def payload(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "capability": self.capability,
            "operation": self.operation,
            "arguments": self.arguments,
            "dependencies": list(self.dependencies),
            "operator_id": self.operator_id,
            "risk": self.risk.value,
            "effect": self.effect.value,
            "approval_required": self.approval_required,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "postconditions": list(self.postconditions),
        }


@dataclass(frozen=True)
class PlanV1:
    plan_id: str
    request_key: str
    goal: GoalV1
    steps: tuple[StepV1, ...]
    planner_adapter_id: str
    planner_prompt_version: str
    repair_cycle: int = 0
    supersedes_plan_id: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.plan_id, "plan_id")
        if type(self.request_key) is not str or _REQUEST_KEY.fullmatch(self.request_key) is None:
            raise AgenticCoreV1ContractError("request_key is invalid")
        if type(self.goal) is not GoalV1 or type(self.steps) is not tuple:
            raise AgenticCoreV1ContractError("plan goal or steps are invalid")
        if not self.steps or len(self.steps) > self.goal.budget.max_steps:
            raise AgenticCoreV1ContractError("plan exceeds its step budget")
        if any(type(step) is not StepV1 for step in self.steps):
            raise AgenticCoreV1ContractError("plan steps must be exact StepV1 values")
        _identifier(self.planner_adapter_id, "planner_adapter_id")
        _identifier(self.planner_prompt_version, "planner_prompt_version")
        _bounded_int(self.repair_cycle, "repair_cycle", 0, self.goal.budget.max_repair_cycles)
        if self.supersedes_plan_id is not None:
            _identifier(self.supersedes_plan_id, "supersedes_plan_id")
        ids = [step.step_id for step in self.steps]
        if len(set(ids)) != len(ids):
            raise AgenticCoreV1ContractError("step identifiers are not unique")
        known = set(ids)
        graph = {step.step_id: set(step.dependencies) for step in self.steps}
        if any(not dependencies <= known for dependencies in graph.values()):
            raise AgenticCoreV1ContractError("plan has an unknown dependency")
        ready = sorted(node for node, dependencies in graph.items() if not dependencies)
        visited: list[str] = []
        while ready:
            node = ready.pop(0)
            visited.append(node)
            for candidate in sorted(graph):
                if node in graph[candidate]:
                    graph[candidate].remove(node)
                    if not graph[candidate] and candidate not in visited and candidate not in ready:
                        ready.append(candidate)
                        ready.sort()
        if len(visited) != len(ids):
            raise AgenticCoreV1ContractError("plan dependency graph contains a cycle")
        if max((step.max_retries for step in self.steps), default=0) > self.goal.budget.max_retries_per_step:
            raise AgenticCoreV1ContractError("step retries exceed the mission budget")
        if sum(step.timeout_seconds for step in self.steps) > self.goal.budget.wall_seconds:
            raise AgenticCoreV1ContractError("step timeouts exceed the mission wall-clock budget")
        payload_size = len(_canonical_json(self.payload(), "plan", MAX_PLAN_BYTES).encode("utf-8"))
        if payload_size > MAX_PLAN_BYTES:
            raise AgenticCoreV1ContractError("plan exceeds its byte budget")

    def ordered_steps(self) -> tuple[StepV1, ...]:
        remaining = {step.step_id: step for step in self.steps}
        complete: set[str] = set()
        output: list[StepV1] = []
        while remaining:
            ready = sorted(
                (step for step in remaining.values() if set(step.dependencies) <= complete),
                key=lambda step: step.step_id,
            )
            if not ready:
                raise AgenticCoreV1ContractError("plan dependency graph cannot be ordered")
            for step in ready:
                output.append(step)
                complete.add(step.step_id)
                remaining.pop(step.step_id)
        return tuple(output)

    def payload(self) -> dict[str, object]:
        return {
            "schema": "OnyxAgenticPlan.v1",
            "plan_id": self.plan_id,
            "request_key": self.request_key,
            "goal": self.goal.payload(),
            "steps": [step.payload() for step in self.steps],
            "planner_adapter_id": self.planner_adapter_id,
            "planner_prompt_version": self.planner_prompt_version,
            "repair_cycle": self.repair_cycle,
            "supersedes_plan_id": self.supersedes_plan_id,
        }

    @property
    def digest(self) -> str:
        return _sha(_canonical_json(self.payload(), "plan", MAX_PLAN_BYTES))


@dataclass(frozen=True)
class OperatorCellProfileV1:
    operator_id: str
    version: str
    allowed_capabilities: tuple[str, ...]
    maximum_data_class: DataClassV1
    independent_verifier_required: bool

    def __post_init__(self) -> None:
        _identifier(self.operator_id, "operator_id")
        _identifier(self.version, "operator version")
        if type(self.allowed_capabilities) is not tuple or not self.allowed_capabilities:
            raise AgenticCoreV1ContractError("operator capability set is invalid")
        for item in self.allowed_capabilities:
            capability_policy_v1(item)
        if len(set(self.allowed_capabilities)) != len(self.allowed_capabilities):
            raise AgenticCoreV1ContractError("operator capability set is not canonical")
        if type(self.maximum_data_class) is not DataClassV1:
            raise AgenticCoreV1ContractError("operator data class is invalid")
        _exact_bool(self.independent_verifier_required, "independent_verifier_required")


RESEARCH_OPERATOR_V1 = OperatorCellProfileV1(
    "provider_free_research", "v1", tuple(sorted(_CAPABILITIES)), DataClassV1.CONFIDENTIAL, True
)
VERIFIER_OPERATOR_V1 = OperatorCellProfileV1(
    "independent_verifier", "v1", tuple(sorted(_CAPABILITIES)), DataClassV1.CONFIDENTIAL, False
)


@dataclass(frozen=True)
class ModelDescriptorV1:
    adapter_id: str
    status: AdapterStatusV1
    modalities: tuple[str, ...]
    maximum_data_class: DataClassV1
    workspace_allowlist: tuple[str, ...]
    local_private: bool
    network_required: bool
    structured_output: bool
    reliability_milli: int
    latency_millis: int
    cost_micro_per_call: int

    def __post_init__(self) -> None:
        _identifier(self.adapter_id, "adapter_id")
        if type(self.status) is not AdapterStatusV1 or type(self.maximum_data_class) is not DataClassV1:
            raise AgenticCoreV1ContractError("model descriptor classification is invalid")
        if type(self.modalities) is not tuple or not self.modalities or len(self.modalities) > 16:
            raise AgenticCoreV1ContractError("model modalities are invalid")
        for modality in self.modalities:
            _identifier(modality, "modality")
        if type(self.workspace_allowlist) is not tuple or not self.workspace_allowlist:
            raise AgenticCoreV1ContractError("model workspace allowlist is invalid")
        for workspace in self.workspace_allowlist:
            _identifier(workspace, "workspace")
        _exact_bool(self.local_private, "local_private")
        _exact_bool(self.network_required, "network_required")
        _exact_bool(self.structured_output, "structured_output")
        _bounded_int(self.reliability_milli, "reliability_milli", 0, 1_000)
        _bounded_int(self.latency_millis, "latency_millis", 0, 3_600_000)
        _bounded_int(self.cost_micro_per_call, "cost_micro_per_call", 0, 1_000_000_000)


@dataclass(frozen=True)
class RouteRequestV1:
    workspace_id: str
    data_class: DataClassV1
    modality: str
    require_local_private: bool
    require_structured_output: bool
    maximum_latency_millis: int
    maximum_cost_micro: int
    minimum_reliability_milli: int

    def __post_init__(self) -> None:
        _identifier(self.workspace_id, "workspace_id")
        if type(self.data_class) is not DataClassV1:
            raise AgenticCoreV1ContractError("route data class is invalid")
        _identifier(self.modality, "modality")
        _exact_bool(self.require_local_private, "require_local_private")
        _exact_bool(self.require_structured_output, "require_structured_output")
        _bounded_int(self.maximum_latency_millis, "maximum_latency_millis", 0, 3_600_000)
        _bounded_int(self.maximum_cost_micro, "maximum_cost_micro", 0, 1_000_000_000)
        _bounded_int(self.minimum_reliability_milli, "minimum_reliability_milli", 0, 1_000)


@dataclass(frozen=True)
class RouteDecisionV1:
    adapter_id: str | None
    status: str
    reason: str
    considered: tuple[str, ...]


class ModelRouterV1:
    """Policy-owned router; prompt/model content never participates in filtering."""

    def __init__(self, descriptors: Sequence[ModelDescriptorV1]) -> None:
        if type(descriptors) not in {tuple, list} or not descriptors or len(descriptors) > 64:
            raise AgenticCoreV1ContractError("model descriptor set is invalid")
        exact = tuple(descriptors)
        if any(type(item) is not ModelDescriptorV1 for item in exact):
            raise AgenticCoreV1ContractError("exact ModelDescriptorV1 values are required")
        ids = [item.adapter_id for item in exact]
        if len(set(ids)) != len(ids):
            raise AgenticCoreV1ContractError("model adapter identifiers are not unique")
        self._descriptors = exact

    def route(self, request: RouteRequestV1) -> RouteDecisionV1:
        if type(request) is not RouteRequestV1:
            raise AgenticCoreV1ContractError("exact RouteRequestV1 required")
        considered = tuple(sorted(item.adapter_id for item in self._descriptors))
        candidates: list[ModelDescriptorV1] = []
        for item in self._descriptors:
            if item.status is not AdapterStatusV1.AVAILABLE_LOCAL:
                continue
            if request.workspace_id not in item.workspace_allowlist:
                continue
            if _DATA_RANK[request.data_class] > _DATA_RANK[item.maximum_data_class]:
                continue
            if request.modality not in item.modalities:
                continue
            if request.require_local_private and not item.local_private:
                continue
            if request.require_structured_output and not item.structured_output:
                continue
            if item.latency_millis > request.maximum_latency_millis:
                continue
            if item.cost_micro_per_call > request.maximum_cost_micro:
                continue
            if item.reliability_milli < request.minimum_reliability_milli:
                continue
            candidates.append(item)
        if not candidates:
            return RouteDecisionV1(None, "blocked", "no_policy_eligible_adapter", considered)
        selected = min(
            candidates,
            key=lambda item: (
                item.cost_micro_per_call,
                -item.reliability_milli,
                item.latency_millis,
                item.adapter_id,
            ),
        )
        return RouteDecisionV1(selected.adapter_id, "selected", "hard_policy_filters_passed", considered)


@dataclass(frozen=True)
class PlanningProposalV1:
    steps: tuple[Mapping[str, object], ...]
    adapter_id: str
    prompt_version: str

    def __post_init__(self) -> None:
        if type(self.steps) is not tuple or not self.steps or len(self.steps) > MAX_STEPS:
            raise AgenticCoreV1ContractError("planning proposal steps are invalid")
        if any(type(step) is not dict for step in self.steps):
            raise AgenticCoreV1ContractError("planning proposal must contain plain mappings")
        _identifier(self.adapter_id, "adapter_id")
        _identifier(self.prompt_version, "prompt_version")


@runtime_checkable
class PlannerAdapterV1(Protocol):
    @property
    def descriptor(self) -> ModelDescriptorV1: ...

    def propose(self, goal: GoalV1) -> PlanningProposalV1: ...


class DeclarationOnlyPlannerAdapterV1:
    """A truthful descriptor for a future provider; it can never invoke V1."""

    def __init__(self, descriptor: ModelDescriptorV1) -> None:
        if descriptor.status is AdapterStatusV1.AVAILABLE_LOCAL:
            raise AgenticCoreV1ContractError("declaration-only adapter cannot be available")
        self._descriptor = descriptor

    @property
    def descriptor(self) -> ModelDescriptorV1:
        return self._descriptor

    def propose(self, goal: GoalV1) -> PlanningProposalV1:
        del goal
        raise AgenticCoreV1Unavailable("provider adapter is declaration-only in V1")


class DeterministicPlannerAdapterV1:
    """Provider-free adapter over host-supplied typed candidate steps."""

    def __init__(self, workspace_id: str, proposed_steps: Sequence[Mapping[str, object]]) -> None:
        _identifier(workspace_id, "workspace_id")
        if type(proposed_steps) not in {tuple, list} or not proposed_steps or len(proposed_steps) > MAX_STEPS:
            raise AgenticCoreV1ContractError("proposed steps are invalid")
        if any(type(step) is not dict for step in proposed_steps):
            raise AgenticCoreV1ContractError("proposed steps must be plain mappings")
        self._steps = tuple(dict(step) for step in proposed_steps)
        self._descriptor = ModelDescriptorV1(
            "local_deterministic_planner",
            AdapterStatusV1.AVAILABLE_LOCAL,
            ("structured_plan",),
            DataClassV1.CONFIDENTIAL,
            (workspace_id,),
            True,
            False,
            True,
            1_000,
            0,
            0,
        )

    @property
    def descriptor(self) -> ModelDescriptorV1:
        return self._descriptor

    def propose(self, goal: GoalV1) -> PlanningProposalV1:
        if goal.workspace_id not in self._descriptor.workspace_allowlist:
            raise AgenticCoreV1Denied("planner workspace binding does not match the goal")
        return PlanningProposalV1(self._steps, self._descriptor.adapter_id, "phase6_planner_v1")


class PlannerV1:
    """Treat model/provider output as an untrusted proposal and relabel by policy."""

    def __init__(self, router: ModelRouterV1, adapter: PlannerAdapterV1) -> None:
        if not isinstance(adapter, PlannerAdapterV1):
            raise AgenticCoreV1ContractError("planner adapter contract is invalid")
        self._router = router
        self._adapter = adapter

    def plan(self, goal: GoalV1, request_key: str, *, repair_cycle: int = 0,
             supersedes_plan_id: str | None = None) -> PlanV1:
        if type(goal) is not GoalV1:
            raise AgenticCoreV1ContractError("exact GoalV1 required")
        decision = self._router.route(
            RouteRequestV1(
                goal.workspace_id,
                goal.data_class,
                "structured_plan",
                True,
                True,
                60_000,
                0,
                900,
            )
        )
        if decision.adapter_id != self._adapter.descriptor.adapter_id:
            raise AgenticCoreV1Unavailable("planner route is unavailable under host policy")
        proposal = self._adapter.propose(goal)
        steps: list[StepV1] = []
        for position, raw in enumerate(proposal.steps):
            capability = _identifier(raw.get("capability"), "capability")
            policy = capability_policy_v1(capability)
            arguments = raw.get("arguments", {})
            if type(arguments) is not dict:
                raise AgenticCoreV1ContractError("step arguments must be a plain mapping")
            dependencies_raw = raw.get("dependencies", ())
            if type(dependencies_raw) not in {tuple, list}:
                raise AgenticCoreV1ContractError("step dependencies are invalid")
            post_raw = raw.get("postconditions", ())
            if type(post_raw) not in {tuple, list} or not post_raw:
                raise AgenticCoreV1ContractError("explicit postconditions are required")
            proposed_operator = raw.get("operator_id", RESEARCH_OPERATOR_V1.operator_id)
            if proposed_operator != RESEARCH_OPERATOR_V1.operator_id:
                raise AgenticCoreV1Denied("V1 allows only the provider-free research operator")
            timeout = raw.get("timeout_seconds", 10.0)
            retries = raw.get("max_retries", goal.budget.max_retries_per_step)
            step_id = raw.get("step_id", f"step_{position + 1:03d}")
            steps.append(
                StepV1(
                    _identifier(step_id, "step_id"),
                    capability,
                    policy.operation,
                    _canonical_arguments(arguments),
                    tuple(_identifier(item, "dependency") for item in dependencies_raw),
                    RESEARCH_OPERATOR_V1.operator_id,
                    policy.risk,
                    policy.effect,
                    policy.approval_required,
                    _bounded_float(timeout, "timeout_seconds", 0.01, 3_600.0),
                    _bounded_int(retries, "max_retries", 0, goal.budget.max_retries_per_step),
                    tuple(_identifier(item, "postcondition") for item in post_raw),
                )
            )
        provisional = {
            "request_key": request_key,
            "goal": goal.payload(),
            "steps": [step.payload() for step in steps],
            "adapter": proposal.adapter_id,
            "prompt": proposal.prompt_version,
            "repair_cycle": repair_cycle,
            "supersedes": supersedes_plan_id,
        }
        plan_id = f"plan_{_sha(_canonical_json(provisional, 'plan seed', MAX_PLAN_BYTES))[:32]}"
        return PlanV1(
            plan_id,
            request_key,
            goal,
            tuple(steps),
            proposal.adapter_id,
            proposal.prompt_version,
            repair_cycle,
            supersedes_plan_id,
        )


def _budget_from_payload(value: object) -> MissionBudgetV1:
    if type(value) is not dict:
        raise AgenticCoreV1ContractError("stored budget is invalid")
    return MissionBudgetV1(
        value.get("max_steps"),
        value.get("wall_seconds"),
        value.get("max_retries_per_step"),
        value.get("max_repair_cycles"),
        value.get("max_tokens"),
        value.get("max_api_calls"),
        value.get("max_compute_seconds"),
        value.get("max_cost_micro"),
    )


def _goal_from_payload(value: object) -> GoalV1:
    if type(value) is not dict:
        raise AgenticCoreV1ContractError("stored goal is invalid")
    try:
        return GoalV1(
            value["goal_id"],
            value["correlation_id"],
            value["workspace_id"],
            value["objective"],
            tuple(value["definition_of_done"]),
            tuple(value["scope"]),
            tuple(value["exclusions"]),
            DataClassV1(value["data_class"]),
            _budget_from_payload(value["budget"]),
        )
    except (KeyError, TypeError, ValueError):
        raise AgenticCoreV1ContractError("stored goal is invalid") from None


def _step_from_payload(value: object) -> StepV1:
    if type(value) is not dict:
        raise AgenticCoreV1ContractError("stored step is invalid")
    try:
        return StepV1(
            value["step_id"],
            value["capability"],
            value["operation"],
            _canonical_arguments(value["arguments"]),
            tuple(value["dependencies"]),
            value["operator_id"],
            RiskLevelV1(value["risk"]),
            EffectClassV1(value["effect"]),
            value["approval_required"],
            value["timeout_seconds"],
            value["max_retries"],
            tuple(value["postconditions"]),
        )
    except (KeyError, TypeError, ValueError):
        raise AgenticCoreV1ContractError("stored step is invalid") from None


def _plan_from_json(value: str) -> PlanV1:
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        raise AgenticCoreV1ContractError("stored plan JSON is invalid") from None
    if type(payload) is not dict or payload.get("schema") != "OnyxAgenticPlan.v1":
        raise AgenticCoreV1ContractError("stored plan schema is invalid")
    try:
        plan = PlanV1(
            payload["plan_id"],
            payload["request_key"],
            _goal_from_payload(payload["goal"]),
            tuple(_step_from_payload(step) for step in payload["steps"]),
            payload["planner_adapter_id"],
            payload["planner_prompt_version"],
            payload["repair_cycle"],
            payload["supersedes_plan_id"],
        )
    except (KeyError, TypeError, ValueError):
        raise AgenticCoreV1ContractError("stored plan is invalid") from None
    if _canonical_json(plan.payload(), "stored plan", MAX_PLAN_BYTES) != value:
        raise AgenticCoreV1ContractError("stored plan is not canonical")
    return plan


@dataclass(frozen=True)
class PlanProjectionV1:
    plan_id: str
    request_key: str
    plan_digest: str
    state: PlanStateV1
    mission_id: str | None
    mission_plan_digest: str | None
    updated_at: float


@dataclass(frozen=True)
class EvidenceReceiptV1:
    receipt_id: str
    plan_id: str
    mission_id: str
    step_id: str
    operator_id: str
    verifier_id: str
    status: str
    observed_digest: str
    authority_snapshot_hash: str
    event_hash: str
    postconditions: tuple[str, ...]

    def __post_init__(self) -> None:
        for value, label in (
            (self.receipt_id, "receipt_id"),
            (self.plan_id, "plan_id"),
            (self.mission_id, "mission_id"),
            (self.step_id, "step_id"),
            (self.operator_id, "operator_id"),
            (self.verifier_id, "verifier_id"),
        ):
            _identifier(value, label)
        if self.status not in {"verified", "rejected"}:
            raise AgenticCoreV1ContractError("receipt status is invalid")
        for value in (self.observed_digest, self.authority_snapshot_hash, self.event_hash):
            if type(value) is not str or _SHA256.fullmatch(value) is None:
                raise AgenticCoreV1ContractError("receipt digest is invalid")
        if type(self.postconditions) is not tuple or len(self.postconditions) > 16:
            raise AgenticCoreV1ContractError("receipt postconditions are invalid")
        for condition in self.postconditions:
            _identifier(condition, "postcondition")

    def payload(self) -> dict[str, object]:
        return {
            "receipt_id": self.receipt_id,
            "plan_id": self.plan_id,
            "mission_id": self.mission_id,
            "step_id": self.step_id,
            "operator_id": self.operator_id,
            "verifier_id": self.verifier_id,
            "status": self.status,
            "observed_digest": self.observed_digest,
            "authority_snapshot_hash": self.authority_snapshot_hash,
            "event_hash": self.event_hash,
            "postconditions": list(self.postconditions),
        }


@dataclass(frozen=True)
class VerificationReportV1:
    plan_id: str
    mission_id: str
    status: str
    findings: tuple[str, ...]
    receipts: tuple[EvidenceReceiptV1, ...]
    authority_snapshot_hash: str


@dataclass(frozen=True)
class AdmissionResultV1:
    plan_id: str
    state: PlanStateV1
    mission_id: str | None
    reason: str


@dataclass(frozen=True)
class RecoveryRecordV1:
    plan_id: str
    mission_id: str | None
    state: PlanStateV1
    reason: str


class AgenticStateStoreV1:
    """Plan/evidence sidecar only; it never claims or executes work."""

    _DDL = """
    CREATE TABLE metadata(schema_version INTEGER NOT NULL, kill_latched INTEGER NOT NULL);
    CREATE TABLE plans(
      plan_id TEXT PRIMARY KEY,
      request_key TEXT NOT NULL UNIQUE,
      plan_json TEXT NOT NULL,
      plan_digest TEXT NOT NULL,
      state TEXT NOT NULL,
      mission_id TEXT UNIQUE,
      mission_plan_digest TEXT,
      created_at REAL NOT NULL,
      updated_at REAL NOT NULL
    );
    CREATE TABLE events(
      seq INTEGER PRIMARY KEY AUTOINCREMENT,
      plan_id TEXT NOT NULL REFERENCES plans(plan_id),
      occurred_at REAL NOT NULL,
      event TEXT NOT NULL,
      detail_json TEXT NOT NULL,
      prev_hash TEXT NOT NULL,
      event_hash TEXT NOT NULL
    );
    CREATE INDEX events_plan_seq ON events(plan_id,seq);
    CREATE TRIGGER events_no_update BEFORE UPDATE ON events
      BEGIN SELECT RAISE(ABORT,'phase6 events are immutable'); END;
    CREATE TRIGGER events_no_delete BEFORE DELETE ON events
      BEGIN SELECT RAISE(ABORT,'phase6 events are immutable'); END;
    CREATE TRIGGER metadata_no_delete BEFORE DELETE ON metadata
      BEGIN SELECT RAISE(ABORT,'phase6 metadata is immutable'); END;
    CREATE TRIGGER metadata_no_insert BEFORE INSERT ON metadata
      WHEN (SELECT COUNT(*) FROM metadata) >= 1
      BEGIN SELECT RAISE(ABORT,'phase6 metadata is singleton'); END;
    CREATE TRIGGER kill_no_reset BEFORE UPDATE OF kill_latched ON metadata
      WHEN OLD.kill_latched=1 AND NEW.kill_latched<>1
      BEGIN SELECT RAISE(ABORT,'phase6 kill latch cannot be reset'); END;
    CREATE TRIGGER plans_core_no_update BEFORE UPDATE OF
      plan_id,request_key,plan_json,plan_digest,created_at ON plans
      BEGIN SELECT RAISE(ABORT,'phase6 plan identity is immutable'); END;
    CREATE TRIGGER plans_binding_no_update BEFORE UPDATE OF
      mission_id,mission_plan_digest ON plans
      WHEN OLD.mission_id IS NOT NULL OR OLD.mission_plan_digest IS NOT NULL
      BEGIN SELECT RAISE(ABORT,'phase6 mission binding is immutable'); END;
    CREATE TRIGGER plans_no_delete BEFORE DELETE ON plans
      BEGIN SELECT RAISE(ABORT,'phase6 plans are immutable'); END;
    CREATE TABLE receipts(
      receipt_id TEXT PRIMARY KEY,
      plan_id TEXT NOT NULL REFERENCES plans(plan_id),
      receipt_json TEXT NOT NULL,
      receipt_digest TEXT NOT NULL,
      created_at REAL NOT NULL
    );
    CREATE INDEX receipts_plan ON receipts(plan_id,receipt_id);
    CREATE TRIGGER receipts_no_update BEFORE UPDATE ON receipts
      BEGIN SELECT RAISE(ABORT,'phase6 receipts are immutable'); END;
    CREATE TRIGGER receipts_no_delete BEFORE DELETE ON receipts
      BEGIN SELECT RAISE(ABORT,'phase6 receipts are immutable'); END;
    """

    def __init__(self, path: Path | str, gate: AgenticFeatureGateV1) -> None:
        if type(gate) is not AgenticFeatureGateV1 or not gate.enabled:
            raise AgenticCoreV1Denied("Phase 6 agentic core is disabled")
        self._path = Path(path)
        if not self._path.is_absolute() or self._path.name in {"", ".", ".."}:
            raise AgenticCoreV1ContractError("an explicit absolute sidecar path is required")
        self._lock = threading.RLock()
        self.initialize()

    @property
    def path(self) -> Path:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def initialize(self) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            existed = self._path.exists()
            connection = self._connect()
            try:
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                }
                if not existed or (version == 0 and not tables):
                    connection.executescript(
                        "BEGIN IMMEDIATE;\n"
                        + self._DDL
                        + f"\nINSERT INTO metadata VALUES({SCHEMA_VERSION},0);"
                        + f"\nPRAGMA user_version={SCHEMA_VERSION};\nCOMMIT;"
                    )
                elif version != SCHEMA_VERSION or tables != {"metadata", "plans", "events", "receipts"}:
                    raise AgenticCoreV1Error("Phase 6 sidecar schema is unsupported")
                required_triggers = {
                    "events_no_update",
                    "events_no_delete",
                    "metadata_no_delete",
                    "metadata_no_insert",
                    "kill_no_reset",
                    "plans_core_no_update",
                    "plans_binding_no_update",
                    "plans_no_delete",
                    "receipts_no_update",
                    "receipts_no_delete",
                }
                triggers = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='trigger'"
                    )
                }
                if triggers != required_triggers:
                    raise AgenticCoreV1Error("Phase 6 sidecar trigger contract diverges")
                row = connection.execute("SELECT * FROM metadata").fetchall()
                if (
                    len(row) != 1
                    or row[0]["schema_version"] != SCHEMA_VERSION
                    or row[0]["kill_latched"] not in {0, 1}
                ):
                    raise AgenticCoreV1Error("Phase 6 metadata is invalid")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def _event(
        self,
        connection: sqlite3.Connection,
        plan_id: str,
        event: str,
        detail: Mapping[str, object],
    ) -> None:
        count = int(
            connection.execute("SELECT COUNT(*) FROM events WHERE plan_id=?", (plan_id,)).fetchone()[0]
        )
        if count >= MAX_EVENTS_PER_PLAN:
            raise AgenticCoreV1Error("Phase 6 event budget is exhausted")
        previous = connection.execute(
            "SELECT event_hash FROM events WHERE plan_id=? ORDER BY seq DESC LIMIT 1", (plan_id,)
        ).fetchone()
        prev_hash = previous[0] if previous else ""
        occurred = _now()
        name = _identifier(event, "event")
        detail_json = _canonical_json(dict(detail), "event detail")
        event_hash = _sha(
            f"{plan_id}\0{occurred:.9f}\0{name}\0{detail_json}\0{prev_hash}"
        )
        connection.execute(
            "INSERT INTO events(plan_id,occurred_at,event,detail_json,prev_hash,event_hash) "
            "VALUES(?,?,?,?,?,?)",
            (plan_id, occurred, name, detail_json, prev_hash, event_hash),
        )

    def create_plan(self, plan: PlanV1) -> PlanProjectionV1:
        if type(plan) is not PlanV1:
            raise AgenticCoreV1ContractError("exact PlanV1 required")
        plan_json = _canonical_json(plan.payload(), "plan", MAX_PLAN_BYTES)
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM plans WHERE request_key=?", (plan.request_key,)
                ).fetchone()
                if existing is not None:
                    if existing["plan_id"] != plan.plan_id or existing["plan_digest"] != plan.digest:
                        raise AgenticCoreV1Denied("request key is already bound to another immutable plan")
                    connection.execute("COMMIT")
                    return self.get_projection(str(existing["plan_id"]))
                now = _now()
                connection.execute(
                    "INSERT INTO plans VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        plan.plan_id,
                        plan.request_key,
                        plan_json,
                        plan.digest,
                        PlanStateV1.PLANNED.value,
                        None,
                        None,
                        now,
                        now,
                    ),
                )
                self._event(
                    connection,
                    plan.plan_id,
                    "plan.created",
                    {"plan_digest": plan.digest, "repair_cycle": plan.repair_cycle},
                )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return self.get_projection(plan.plan_id)

    @staticmethod
    def _projection(row: Mapping[str, object]) -> PlanProjectionV1:
        try:
            state = PlanStateV1(row["state"])
        except (KeyError, ValueError):
            raise AgenticCoreV1Error("Phase 6 plan state is invalid") from None
        plan_id = _identifier(row["plan_id"], "stored plan_id")
        request_key = row["request_key"]
        plan_digest = row["plan_digest"]
        mission_id = row["mission_id"]
        mission_digest = row["mission_plan_digest"]
        if type(request_key) is not str or _REQUEST_KEY.fullmatch(request_key) is None:
            raise AgenticCoreV1Error("Phase 6 stored request key is invalid")
        if type(plan_digest) is not str or _SHA256.fullmatch(plan_digest) is None:
            raise AgenticCoreV1Error("Phase 6 stored plan digest is invalid")
        if (mission_id is None) != (mission_digest is None):
            raise AgenticCoreV1Error("Phase 6 mission binding is partial")
        if mission_id is not None:
            _identifier(mission_id, "stored mission_id")
            if type(mission_digest) is not str or _SHA256.fullmatch(mission_digest) is None:
                raise AgenticCoreV1Error("Phase 6 mission binding digest is invalid")
        updated_at = row["updated_at"]
        if type(updated_at) is not float or not math.isfinite(updated_at) or updated_at <= 0:
            raise AgenticCoreV1Error("Phase 6 projection timestamp is invalid")
        return PlanProjectionV1(
            plan_id,
            request_key,
            plan_digest,
            state,
            (str(mission_id) if mission_id is not None else None),
            (str(mission_digest) if mission_digest is not None else None),
            updated_at,
        )

    def get_plan(self, plan_id: str) -> PlanV1:
        canonical = _identifier(plan_id, "plan_id")
        connection = self._connect()
        try:
            row = connection.execute("SELECT * FROM plans WHERE plan_id=?", (canonical,)).fetchone()
            if row is None:
                raise KeyError(canonical)
            plan = _plan_from_json(row["plan_json"])
            if plan.plan_id != canonical or plan.digest != row["plan_digest"]:
                raise AgenticCoreV1Error("Phase 6 immutable plan digest diverges")
            self.get_projection(canonical)
            return plan
        finally:
            connection.close()

    def get_projection(self, plan_id: str) -> PlanProjectionV1:
        canonical = _identifier(plan_id, "plan_id")
        connection = self._connect()
        try:
            row = connection.execute("SELECT * FROM plans WHERE plan_id=?", (canonical,)).fetchone()
            if row is None:
                raise KeyError(canonical)
            projection = self._projection(row)
            plan = _plan_from_json(row["plan_json"])
            if plan.digest != projection.plan_digest:
                raise AgenticCoreV1Error("Phase 6 immutable plan digest diverges")
            history = self.events(canonical)
            if not history or history[0]["event"] != "plan.created":
                raise AgenticCoreV1Error("Phase 6 plan creation evidence is missing")
            derived = PlanStateV1.PLANNED
            bound = False
            for event in history:
                if event["event"] == "mission.bound":
                    detail = event["detail"]
                    if (
                        bound
                        or detail.get("mission_id") != projection.mission_id
                        or detail.get("mission_plan_digest") != projection.mission_plan_digest
                    ):
                        raise AgenticCoreV1Error("Phase 6 mission binding evidence diverges")
                    bound = True
                    derived = PlanStateV1.AWAITING_APPROVAL
                elif event["event"] == "plan.state":
                    try:
                        derived = PlanStateV1(event["detail"]["state"])
                    except (KeyError, ValueError, TypeError):
                        raise AgenticCoreV1Error("Phase 6 state evidence is invalid") from None
            if bound != (projection.mission_id is not None) or derived is not projection.state:
                raise AgenticCoreV1Error("Phase 6 state projection diverges from evidence")
            return projection
        finally:
            connection.close()

    def list_projections(self) -> tuple[PlanProjectionV1, ...]:
        connection = self._connect()
        try:
            identifiers = [
                row[0]
                for row in connection.execute(
                    "SELECT plan_id FROM plans ORDER BY created_at,plan_id"
                ).fetchall()
            ]
        finally:
            connection.close()
        return tuple(self.get_projection(identifier) for identifier in identifiers)

    def bind_mission(self, plan_id: str, mission_id: str, mission_plan_digest: str) -> PlanProjectionV1:
        canonical = _identifier(plan_id, "plan_id")
        _identifier(mission_id, "mission_id")
        if _SHA256.fullmatch(mission_plan_digest) is None:
            raise AgenticCoreV1ContractError("mission plan digest is invalid")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute("SELECT * FROM plans WHERE plan_id=?", (canonical,)).fetchone()
                if row is None:
                    raise KeyError(canonical)
                if row["mission_id"] is not None:
                    if row["mission_id"] != mission_id or row["mission_plan_digest"] != mission_plan_digest:
                        raise AgenticCoreV1Denied("plan is already bound to another mission")
                    connection.execute("COMMIT")
                    return self._projection(row)
                connection.execute(
                    "UPDATE plans SET mission_id=?,mission_plan_digest=?,state=?,updated_at=? WHERE plan_id=?",
                    (
                        mission_id,
                        mission_plan_digest,
                        PlanStateV1.AWAITING_APPROVAL.value,
                        _now(),
                        canonical,
                    ),
                )
                self._event(
                    connection,
                    canonical,
                    "mission.bound",
                    {"mission_id": mission_id, "mission_plan_digest": mission_plan_digest},
                )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return self.get_projection(canonical)

    def set_state(self, plan_id: str, state: PlanStateV1, reason: str) -> PlanProjectionV1:
        canonical = _identifier(plan_id, "plan_id")
        if type(state) is not PlanStateV1:
            raise AgenticCoreV1ContractError("exact PlanStateV1 required")
        safe_reason = str(redact(_text(reason, "state reason", 512)))
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute("SELECT state FROM plans WHERE plan_id=?", (canonical,)).fetchone()
                if row is None:
                    raise KeyError(canonical)
                if row["state"] != state.value:
                    try:
                        previous = PlanStateV1(row["state"])
                    except ValueError:
                        raise AgenticCoreV1Error("Phase 6 prior state is invalid") from None
                    if state not in _PLAN_TRANSITIONS[previous]:
                        raise AgenticCoreV1Denied(
                            f"invalid Phase 6 state transition: {previous.value} -> {state.value}"
                        )
                    connection.execute(
                        "UPDATE plans SET state=?,updated_at=? WHERE plan_id=?",
                        (state.value, _now(), canonical),
                    )
                    self._event(
                        connection,
                        canonical,
                        "plan.state",
                        {"state": state.value, "reason": safe_reason},
                    )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()
        return self.get_projection(canonical)

    def events(self, plan_id: str) -> tuple[dict[str, object], ...]:
        canonical = _identifier(plan_id, "plan_id")
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM events WHERE plan_id=? ORDER BY seq", (canonical,)
            ).fetchall()
            previous = ""
            output: list[dict[str, object]] = []
            for row in rows:
                expected = _sha(
                    f"{canonical}\0{float(row['occurred_at']):.9f}\0{row['event']}\0"
                    f"{row['detail_json']}\0{previous}"
                )
                if row["prev_hash"] != previous or row["event_hash"] != expected:
                    raise AgenticCoreV1Error("Phase 6 event chain integrity failed")
                output.append(
                    {
                        "seq": int(row["seq"]),
                        "occurred_at": float(row["occurred_at"]),
                        "event": str(row["event"]),
                        "detail": json.loads(row["detail_json"]),
                        "event_hash": str(row["event_hash"]),
                    }
                )
                previous = str(row["event_hash"])
            return tuple(output)
        finally:
            connection.close()

    def record_receipts(self, receipts: Sequence[EvidenceReceiptV1]) -> None:
        if type(receipts) not in {tuple, list} or len(receipts) > MAX_EVIDENCE_RECEIPTS:
            raise AgenticCoreV1ContractError("receipt batch is invalid")
        if any(type(receipt) is not EvidenceReceiptV1 for receipt in receipts):
            raise AgenticCoreV1ContractError("exact evidence receipts are required")
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                for receipt in receipts:
                    payload = _canonical_json(receipt.payload(), "evidence receipt")
                    digest = _sha(payload)
                    existing = connection.execute(
                        "SELECT receipt_digest FROM receipts WHERE receipt_id=?", (receipt.receipt_id,)
                    ).fetchone()
                    if existing is not None:
                        if existing[0] != digest:
                            raise AgenticCoreV1Denied("receipt identifier is already bound")
                        continue
                    count = int(
                        connection.execute(
                            "SELECT COUNT(*) FROM receipts WHERE plan_id=?", (receipt.plan_id,)
                        ).fetchone()[0]
                    )
                    if count >= MAX_EVIDENCE_RECEIPTS:
                        raise AgenticCoreV1Error("evidence receipt budget is exhausted")
                    connection.execute(
                        "INSERT INTO receipts VALUES(?,?,?,?,?)",
                        (receipt.receipt_id, receipt.plan_id, payload, digest, _now()),
                    )
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    def receipts(self, plan_id: str) -> tuple[EvidenceReceiptV1, ...]:
        canonical = _identifier(plan_id, "plan_id")
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT * FROM receipts WHERE plan_id=? ORDER BY receipt_id", (canonical,)
            ).fetchall()
            output: list[EvidenceReceiptV1] = []
            for row in rows:
                if _sha(row["receipt_json"]) != row["receipt_digest"]:
                    raise AgenticCoreV1Error("evidence receipt digest diverges")
                value = json.loads(row["receipt_json"])
                output.append(
                    EvidenceReceiptV1(
                        value["receipt_id"],
                        value["plan_id"],
                        value["mission_id"],
                        value["step_id"],
                        value["operator_id"],
                        value["verifier_id"],
                        value["status"],
                        value["observed_digest"],
                        value["authority_snapshot_hash"],
                        value["event_hash"],
                        tuple(value["postconditions"]),
                    )
                )
            return tuple(output)
        finally:
            connection.close()

    def latch_kill(self) -> bool:
        with self._lock:
            connection = self._connect()
            try:
                with connection:
                    previous = int(connection.execute("SELECT kill_latched FROM metadata").fetchone()[0])
                    connection.execute("UPDATE metadata SET kill_latched=1")
                return previous == 0
            finally:
                connection.close()

    @property
    def kill_latched(self) -> bool:
        connection = self._connect()
        try:
            return bool(connection.execute("SELECT kill_latched FROM metadata").fetchone()[0])
        finally:
            connection.close()


class IndependentVerifierV1:
    """Deterministically verifies MissionStore's persisted authority/evidence."""

    verifier_id = VERIFIER_OPERATOR_V1.operator_id

    def verify(
        self,
        plan: PlanV1,
        mission_store: MissionStore,
        mission_id: str,
        mission_plan_digest: str,
    ) -> VerificationReportV1:
        if type(plan) is not PlanV1 or type(mission_store) is not MissionStore:
            raise AgenticCoreV1ContractError("exact plan and MissionStore are required")
        _identifier(mission_id, "mission_id")
        if _SHA256.fullmatch(mission_plan_digest) is None:
            raise AgenticCoreV1ContractError("mission plan digest is invalid")
        mission = mission_store.get(mission_id)
        snapshot = mission_store.authority_snapshot(mission_id)
        mission_events = mission_store.events(mission_id)
        summary = mission_store.plan_summary(mission_id)
        findings: list[str] = []
        receipts: list[EvidenceReceiptV1] = []
        if summary["plan_digest"] != mission_plan_digest:
            findings.append("mission_plan_digest_mismatch")
        ordered = plan.ordered_steps()
        expected_steps = []
        for step in ordered:
            policy = capability_policy_v1(step.capability)
            if policy.executor != "mission_store" or policy.mission_tool is None:
                findings.append("non_mission_store_step_present")
                continue
            expected_steps.append(
                {"tool": policy.mission_tool, "args": step.arguments}
            )
        observed_steps = [
            {"tool": item["tool"], "args": item["args"]}
            for item in summary["plan"]["steps"]
        ]
        if expected_steps != observed_steps:
            findings.append("mission_plan_projection_mismatch")
        success_events = [event for event in mission_events if event["event"] == "step.succeeded"]
        if mission.state != "succeeded":
            findings.append(f"mission_not_succeeded:{mission.state}")
        if not mission_events or mission_events[-1]["event"] != "mission.succeeded":
            findings.append("terminal_success_event_missing")
        if len(success_events) != len(ordered):
            findings.append("step_success_cardinality_mismatch")
        for position, step in enumerate(ordered):
            if position >= len(success_events):
                break
            event = success_events[position]
            detail = event["detail"]
            observed_postconditions = tuple(detail.get("postconditions", ()))
            if observed_postconditions != step.postconditions:
                findings.append(f"postconditions_mismatch:{step.step_id}")
            event_hash = str(event["event_hash"])
            receipt_id = f"receipt_{_sha(f'{plan.plan_id}:{step.step_id}:{event_hash}')[:32]}"
            receipts.append(
                EvidenceReceiptV1(
                    receipt_id,
                    plan.plan_id,
                    mission_id,
                    step.step_id,
                    step.operator_id,
                    self.verifier_id,
                    "verified" if observed_postconditions == step.postconditions else "rejected",
                    _sha(_canonical_json(detail, "mission evidence")),
                    snapshot.snapshot_hash,
                    event_hash,
                    observed_postconditions,
                )
            )
        status = "verified" if not findings else "rejected"
        return VerificationReportV1(
            plan.plan_id,
            mission_id,
            status,
            tuple(findings),
            tuple(receipts),
            snapshot.snapshot_hash,
        )


@dataclass(frozen=True)
class CritiqueV1:
    plan_id: str
    repair_cycle: int
    findings: tuple[str, ...]
    repair_allowed: bool
    reason: str


class BoundedCriticV1:
    def critique(self, plan: PlanV1, findings: Sequence[str]) -> CritiqueV1:
        if type(plan) is not PlanV1 or type(findings) not in {tuple, list}:
            raise AgenticCoreV1ContractError("critique inputs are invalid")
        normalized = tuple(_text(item, "finding", 512) for item in findings[:32])
        allowed = bool(normalized) and plan.repair_cycle < plan.goal.budget.max_repair_cycles
        return CritiqueV1(
            plan.plan_id,
            plan.repair_cycle,
            normalized,
            allowed,
            "bounded_repair_available" if allowed else "repair_budget_exhausted_or_no_findings",
        )


@dataclass(frozen=True)
class ExternalAgentBudgetV1:
    wall_seconds: int
    max_followups: int
    max_tokens: int
    max_cost_micro: int

    def __post_init__(self) -> None:
        _bounded_int(self.wall_seconds, "external wall_seconds", 1, 86_400)
        _bounded_int(self.max_followups, "external max_followups", 0, 32)
        _bounded_int(self.max_tokens, "external max_tokens", 0, 10_000_000)
        _bounded_int(self.max_cost_micro, "external max_cost_micro", 0, 1_000_000_000)


@dataclass(frozen=True)
class ExternalAgentRequestV1:
    request_id: str
    workspace_id: str
    repository_root: str
    objective: str
    allowed_relative_paths: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    budget: ExternalAgentBudgetV1
    kill_token_id: str
    evidence_requirements: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        _identifier(self.workspace_id, "workspace_id")
        root = Path(_text(self.repository_root, "repository_root", 2_048))
        if not root.is_absolute():
            raise AgenticCoreV1ContractError("external-agent repository root must be absolute")
        _non_sensitive_text(self.objective, "objective", 2_000)
        if type(self.allowed_relative_paths) is not tuple or not self.allowed_relative_paths:
            raise AgenticCoreV1ContractError("external-agent path allowlist is required")
        for item in self.allowed_relative_paths:
            path = Path(_text(item, "allowed path", 512))
            if path.is_absolute() or ".." in path.parts:
                raise AgenticCoreV1ContractError("external-agent allowed path is unsafe")
        required_forbidden = {
            "deploy_production",
            "merge_protected_branch",
            "delete_repository",
            "rotate_credentials",
            "incur_spend",
        }
        if type(self.forbidden_actions) is not tuple or not required_forbidden <= set(self.forbidden_actions):
            raise AgenticCoreV1ContractError("external-agent forbidden actions are incomplete")
        if type(self.budget) is not ExternalAgentBudgetV1:
            raise AgenticCoreV1ContractError("external-agent budget is invalid")
        _identifier(self.kill_token_id, "kill_token_id")
        if type(self.evidence_requirements) is not tuple or not self.evidence_requirements:
            raise AgenticCoreV1ContractError("external-agent evidence requirements are required")
        for item in self.evidence_requirements:
            _identifier(item, "evidence requirement")


@dataclass(frozen=True)
class ExternalAgentStatusV1:
    request_id: str
    status: AdapterStatusV1
    provider_session_id: str | None
    evidence_digests: tuple[str, ...]
    reason: str


@runtime_checkable
class ExternalAgentAdapterV1(Protocol):
    """No implementation is accepted in V1; this is the integration contract."""

    @property
    def adapter_id(self) -> str: ...

    @property
    def status(self) -> AdapterStatusV1: ...

    def start(self, request: ExternalAgentRequestV1) -> ExternalAgentStatusV1: ...

    def inspect(self, request_id: str) -> ExternalAgentStatusV1: ...

    def follow_up(self, request_id: str, instruction: str) -> ExternalAgentStatusV1: ...

    def cancel(self, request_id: str, kill_token_id: str) -> ExternalAgentStatusV1: ...


class DisabledExternalAgentAdapterV1:
    adapter_id = "external_agent_disabled"
    status = AdapterStatusV1.BLOCKED_BY_ACCESS

    @staticmethod
    def _blocked(request_id: str) -> ExternalAgentStatusV1:
        _identifier(request_id, "request_id")
        return ExternalAgentStatusV1(
            request_id,
            AdapterStatusV1.BLOCKED_BY_ACCESS,
            None,
            (),
            "no accepted installed/authenticated external-agent adapter",
        )

    def start(self, request: ExternalAgentRequestV1) -> ExternalAgentStatusV1:
        if type(request) is not ExternalAgentRequestV1:
            raise AgenticCoreV1ContractError("exact ExternalAgentRequestV1 required")
        return self._blocked(request.request_id)

    def inspect(self, request_id: str) -> ExternalAgentStatusV1:
        return self._blocked(request_id)

    def follow_up(self, request_id: str, instruction: str) -> ExternalAgentStatusV1:
        _non_sensitive_text(instruction, "follow-up instruction", 2_000)
        return self._blocked(request_id)

    def cancel(self, request_id: str, kill_token_id: str) -> ExternalAgentStatusV1:
        _identifier(kill_token_id, "kill_token_id")
        return self._blocked(request_id)


_MISSION_STATE_MAP = {
    "awaiting_approval": PlanStateV1.AWAITING_APPROVAL,
    "running": PlanStateV1.RUNNING,
    "waiting": PlanStateV1.WAITING,
    "paused": PlanStateV1.PAUSED,
    "succeeded": PlanStateV1.VERIFYING,
    "failed": PlanStateV1.FAILED,
    "cancelled": PlanStateV1.CANCELLED,
}

_PLAN_TRANSITIONS = {
    PlanStateV1.PLANNED: {
        PlanStateV1.WAITING_FOR_PHASE5,
        PlanStateV1.AWAITING_APPROVAL,
        PlanStateV1.BLOCKED,
        PlanStateV1.CANCELLED,
    },
    PlanStateV1.WAITING_FOR_PHASE5: {PlanStateV1.BLOCKED, PlanStateV1.CANCELLED},
    PlanStateV1.AWAITING_APPROVAL: {
        PlanStateV1.RUNNING,
        PlanStateV1.WAITING,
        PlanStateV1.PAUSED,
        PlanStateV1.VERIFYING,
        PlanStateV1.BLOCKED,
        PlanStateV1.FAILED,
        PlanStateV1.CANCELLED,
    },
    PlanStateV1.RUNNING: {
        PlanStateV1.WAITING,
        PlanStateV1.PAUSED,
        PlanStateV1.VERIFYING,
        PlanStateV1.BLOCKED,
        PlanStateV1.FAILED,
        PlanStateV1.CANCELLED,
    },
    PlanStateV1.WAITING: {
        PlanStateV1.RUNNING,
        PlanStateV1.BLOCKED,
        PlanStateV1.FAILED,
        PlanStateV1.CANCELLED,
    },
    PlanStateV1.PAUSED: {
        PlanStateV1.RUNNING,
        PlanStateV1.WAITING,
        PlanStateV1.BLOCKED,
        PlanStateV1.FAILED,
        PlanStateV1.CANCELLED,
    },
    PlanStateV1.VERIFYING: {
        PlanStateV1.COMPLETE,
        PlanStateV1.BLOCKED,
    },
    PlanStateV1.BLOCKED: {PlanStateV1.CANCELLED},
    PlanStateV1.COMPLETE: set(),
    PlanStateV1.FAILED: set(),
    PlanStateV1.CANCELLED: set(),
}


class AgenticCoreV1:
    """Planner/operator/verifier facade around the single stable MissionStore."""

    def __init__(
        self,
        state_store: AgenticStateStoreV1,
        mission_store: MissionStore,
        workspace_scope: WorkspaceScopeV1,
        *,
        verifier: IndependentVerifierV1 | None = None,
        critic: BoundedCriticV1 | None = None,
    ) -> None:
        if (
            type(state_store) is not AgenticStateStoreV1
            or type(mission_store) is not MissionStore
            or type(workspace_scope) is not WorkspaceScopeV1
        ):
            raise AgenticCoreV1ContractError(
                "exact Phase 6, MissionStore and workspace scope instances are required"
            )
        self._state = state_store
        self._missions = mission_store
        self._workspace = workspace_scope
        self._verifier = verifier or IndependentVerifierV1()
        self._critic = critic or BoundedCriticV1()
        self._lock = threading.RLock()

    @property
    def kill_latched(self) -> bool:
        return self._state.kill_latched

    def _validate_plan_scope(self, plan: PlanV1) -> None:
        if plan.goal.workspace_id != self._workspace.workspace_id:
            raise AgenticCoreV1Denied("goal workspace does not match the host-owned scope")
        if _DATA_RANK[plan.goal.data_class] > _DATA_RANK[self._workspace.maximum_data_class]:
            raise AgenticCoreV1Denied("goal data class exceeds the workspace scope")
        for step in plan.steps:
            if step.capability.startswith("workspace_"):
                root = step.arguments.get("root")
                if type(root) is not str or root not in self._workspace.allowed_roots:
                    raise AgenticCoreV1Denied(
                        "workspace tool root is outside the host-owned workspace scope"
                    )

    def submit(
        self,
        goal: GoalV1,
        request_key: str,
        proposed_steps: Sequence[Mapping[str, object]],
    ) -> PlanProjectionV1:
        if self.kill_latched:
            raise AgenticCoreV1Denied("Phase 6 kill switch is latched")
        adapter = DeterministicPlannerAdapterV1(goal.workspace_id, proposed_steps)
        router = ModelRouterV1((adapter.descriptor,))
        plan = PlannerV1(router, adapter).plan(goal, request_key)
        self._validate_plan_scope(plan)
        return self._state.create_plan(plan)

    def repair(
        self,
        plan_id: str,
        request_key: str,
        proposed_steps: Sequence[Mapping[str, object]],
        findings: Sequence[str],
    ) -> PlanProjectionV1:
        if self.kill_latched:
            raise AgenticCoreV1Denied("Phase 6 kill switch is latched")
        source = self._state.get_plan(plan_id)
        projection = self._state.get_projection(plan_id)
        if projection.state not in {PlanStateV1.FAILED, PlanStateV1.BLOCKED}:
            raise AgenticCoreV1Denied("repair requires a failed or blocked source plan")
        critique = self._critic.critique(source, findings)
        if not critique.repair_allowed:
            raise AgenticCoreV1Denied("bounded repair budget is exhausted")
        adapter = DeterministicPlannerAdapterV1(source.goal.workspace_id, proposed_steps)
        router = ModelRouterV1((adapter.descriptor,))
        repaired = PlannerV1(router, adapter).plan(
            source.goal,
            request_key,
            repair_cycle=source.repair_cycle + 1,
            supersedes_plan_id=source.plan_id,
        )
        self._validate_plan_scope(repaired)
        return self._state.create_plan(repaired)

    def materialize(self, plan_id: str) -> AdmissionResultV1:
        with self._lock:
            if self.kill_latched:
                raise AgenticCoreV1Denied("Phase 6 kill switch is latched")
            plan = self._state.get_plan(plan_id)
            self._validate_plan_scope(plan)
            projection = self._state.get_projection(plan_id)
            if projection.mission_id is not None:
                return AdmissionResultV1(
                    plan.plan_id,
                    projection.state,
                    projection.mission_id,
                    "idempotent_existing_mission_binding",
                )
            ordered = plan.ordered_steps()
            policies = tuple(capability_policy_v1(step.capability) for step in ordered)
            if any(policy.executor == "phase5" for policy in policies):
                self._state.set_state(
                    plan.plan_id,
                    PlanStateV1.WAITING_FOR_PHASE5,
                    "local_catalog_read remains owned by accepted Phase 5 integration",
                )
                return AdmissionResultV1(
                    plan.plan_id,
                    PlanStateV1.WAITING_FOR_PHASE5,
                    None,
                    "phase5_catalog_dispatch_not_wired",
                )
            mission_steps: list[dict[str, object]] = []
            for step, policy in zip(ordered, policies, strict=True):
                if policy.mission_tool is None:
                    raise AgenticCoreV1Unavailable("mission tool binding is unavailable")
                mission_steps.append(
                    {
                        "tool": policy.mission_tool,
                        "args": step.arguments,
                        "estimated_provider_cost": 0.0,
                    }
                )
            mission = self._missions.create(
                plan.goal.objective,
                mission_steps,
                tool_allowlist=sorted({str(item["tool"]) for item in mission_steps}),
                max_steps=plan.goal.budget.max_steps,
                max_seconds=plan.goal.budget.wall_seconds,
                max_retries=plan.goal.budget.max_retries_per_step,
                provider_cost_limit=0.0,
            )
            summary = self._missions.plan_summary(mission.id)
            self._state.bind_mission(plan.plan_id, mission.id, summary["plan_digest"])
            return AdmissionResultV1(
                plan.plan_id,
                PlanStateV1.AWAITING_APPROVAL,
                mission.id,
                "delegated_to_stable_mission_store",
            )

    def _sync(self, plan_id: str, mission: Mission) -> PlanProjectionV1:
        current = self._state.get_projection(plan_id)
        if (
            mission.state == "succeeded"
            and current.state in {PlanStateV1.COMPLETE, PlanStateV1.BLOCKED}
        ):
            return current
        mapped = _MISSION_STATE_MAP.get(mission.state)
        if mapped is None:
            raise AgenticCoreV1Error("stable mission state cannot be projected")
        return self._state.set_state(plan_id, mapped, f"mission_store:{mission.state}")

    def execute_approved(
        self,
        plan_id: str,
        runner: ToolRunner | None = None,
    ) -> Mission:
        """Run only an already-approved MissionStore mission; never opens a new consent UI."""
        with self._lock:
            if self.kill_latched:
                raise AgenticCoreV1Denied("Phase 6 kill switch is latched")
            plan = self._state.get_plan(plan_id)
            self._validate_plan_scope(plan)
            projection = self._state.get_projection(plan_id)
            if projection.mission_id is None:
                raise AgenticCoreV1Denied("plan has no stable mission binding")
            mission = self._missions.get(projection.mission_id)
            if mission.state == "awaiting_approval":
                self._sync(plan_id, mission)
                return mission
            if mission.state not in {"running", "paused"}:
                self._sync(plan_id, mission)
                return mission
            ordered = plan.ordered_steps()
            expected: dict[str, StepV1] = {}
            summary = self._missions.plan_summary(mission.id)
            for position, (step, materialized) in enumerate(
                zip(ordered, summary["plan"]["steps"], strict=True)
            ):
                idem = _sha(
                    f"{mission.id}:{position}:{materialized['tool']}:"
                    f"{_canonical_arguments(materialized['args'])}"
                )
                expected[idem] = step
            selected_runner = runner or run_mission_tool

        def budgeted_runner(tool: str, arguments: dict[str, Any], key: str) -> Any:
            if self.kill_latched:
                raise AgenticCoreV1Denied("Phase 6 kill switch is latched")
            step = expected.get(key)
            if step is None:
                raise AgenticCoreV1Denied("mission idempotency key is not bound to the plan")
            policy = capability_policy_v1(step.capability)
            observed_arguments = _canonical_arguments(arguments)
            if policy.mission_tool != tool or step.arguments_json != observed_arguments:
                raise AgenticCoreV1Denied("mission dispatch diverges from the immutable plan")
            runner_arguments = json.loads(observed_arguments)
            started = time.monotonic()
            outcomes: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

            def invoke() -> None:
                try:
                    outcomes.put((True, selected_runner(tool, runner_arguments, key)))
                except BaseException as exc:
                    outcomes.put((False, exc))

            worker = threading.Thread(
                target=invoke,
                name="onyx-phase6-step-budget",
                daemon=True,
            )
            worker.start()
            try:
                completed, outcome = outcomes.get(timeout=step.timeout_seconds)
            except queue.Empty:
                return {
                    "status": "failed",
                    "data": {"timeout_seconds": step.timeout_seconds},
                    "evidence": [],
                    "postconditions": [
                        {"name": "step_timeout_respected", "satisfied": False}
                    ],
                    "waiting_for": None,
                }
            if not completed:
                assert isinstance(outcome, BaseException)
                raise outcome
            result = outcome
            elapsed = time.monotonic() - started
            if _canonical_arguments(runner_arguments) != observed_arguments:
                raise AgenticCoreV1Denied("runner mutated the immutable dispatch arguments")
            if elapsed > step.timeout_seconds:
                return {
                    "status": "failed",
                    "data": {"elapsed_seconds": elapsed},
                    "evidence": [],
                    "postconditions": [
                        {"name": "step_timeout_respected", "satisfied": False}
                    ],
                    "waiting_for": None,
                }
            if self.kill_latched:
                raise AgenticCoreV1Denied("Phase 6 kill switch latched before result commit")
            return result

        # MissionStore owns concurrent cancel/late-result rejection.  Do not
        # hold the Phase 6 projection lock while the stable executor is active.
        mission = self._missions.run(mission.id, budgeted_runner)
        with self._lock:
            projection = self._sync(plan_id, mission)
            if mission.state == "succeeded":
                if projection.mission_plan_digest is None:
                    raise AgenticCoreV1Error("mission plan digest binding is missing")
                report = self._verifier.verify(
                    plan,
                    self._missions,
                    mission.id,
                    projection.mission_plan_digest,
                )
                self._state.record_receipts(report.receipts)
                self._state.set_state(
                    plan_id,
                    PlanStateV1.COMPLETE if report.status == "verified" else PlanStateV1.BLOCKED,
                    "independent_verification_passed"
                    if report.status == "verified"
                    else "independent_verification_failed",
                )
            return mission

    def verify(self, plan_id: str) -> VerificationReportV1:
        plan = self._state.get_plan(plan_id)
        projection = self._state.get_projection(plan_id)
        if projection.mission_id is None or projection.mission_plan_digest is None:
            raise AgenticCoreV1Denied("plan has no stable mission evidence binding")
        report = self._verifier.verify(
            plan,
            self._missions,
            projection.mission_id,
            projection.mission_plan_digest,
        )
        self._state.record_receipts(report.receipts)
        self._state.set_state(
            plan_id,
            PlanStateV1.COMPLETE if report.status == "verified" else PlanStateV1.BLOCKED,
            "independent_verification_passed"
            if report.status == "verified"
            else "independent_verification_failed",
        )
        return report

    def cancel(self, plan_id: str, reason: str = "owner_cancelled") -> RecoveryRecordV1:
        safe_reason = _text(reason, "cancel reason", 512)
        with self._lock:
            projection = self._state.get_projection(plan_id)
            if projection.state in {
                PlanStateV1.COMPLETE,
                PlanStateV1.FAILED,
                PlanStateV1.CANCELLED,
            }:
                raise AgenticCoreV1Denied("terminal plan cannot be cancelled")
            if projection.mission_id is not None:
                mission = self._missions.get(projection.mission_id)
                if mission.state in {"awaiting_approval", "running", "waiting", "paused"}:
                    mission = self._missions.cancel(mission.id)
                    self._sync(plan_id, mission)
            self._state.set_state(plan_id, PlanStateV1.CANCELLED, safe_reason)
            return RecoveryRecordV1(
                plan_id,
                projection.mission_id,
                PlanStateV1.CANCELLED,
                safe_reason,
            )

    def kill(self, reason: str = "owner_kill") -> tuple[RecoveryRecordV1, ...]:
        safe_reason = _text(reason, "kill reason", 512)
        self._state.latch_kill()
        results: list[RecoveryRecordV1] = []
        for projection in self._state.list_projections():
            if projection.state in {PlanStateV1.COMPLETE, PlanStateV1.FAILED, PlanStateV1.CANCELLED}:
                continue
            try:
                results.append(self.cancel(projection.plan_id, safe_reason))
            except (MissionError, InvalidTransition, KeyError):
                self._state.set_state(
                    projection.plan_id,
                    PlanStateV1.BLOCKED,
                    "kill requires reconciliation",
                )
                results.append(
                    RecoveryRecordV1(
                        projection.plan_id,
                        projection.mission_id,
                        PlanStateV1.BLOCKED,
                        "kill_requires_reconciliation",
                    )
                )
        return tuple(results)

    def recover(self) -> tuple[RecoveryRecordV1, ...]:
        """Reconcile projections after restart; never auto-replays a mission step."""
        output: list[RecoveryRecordV1] = []
        for projection in self._state.list_projections():
            if projection.mission_id is None:
                state = (
                    PlanStateV1.CANCELLED
                    if self.kill_latched and projection.state is not PlanStateV1.COMPLETE
                    else projection.state
                )
                if state is not projection.state:
                    self._state.set_state(projection.plan_id, state, "restart kill reconciliation")
                output.append(
                    RecoveryRecordV1(
                        projection.plan_id,
                        None,
                        state,
                        "metadata_only_plan",
                    )
                )
                continue
            try:
                mission = self._missions.get(projection.mission_id)
            except KeyError:
                self._state.set_state(
                    projection.plan_id,
                    PlanStateV1.BLOCKED,
                    "bound MissionStore mission is unavailable",
                )
                output.append(
                    RecoveryRecordV1(
                        projection.plan_id,
                        projection.mission_id,
                        PlanStateV1.BLOCKED,
                        "mission_binding_missing",
                    )
                )
                continue
            projected = self._sync(projection.plan_id, mission)
            if self.kill_latched and mission.state in {"awaiting_approval", "running", "waiting", "paused"}:
                try:
                    mission = self._missions.cancel(mission.id)
                    projected = self._sync(projection.plan_id, mission)
                except (MissionError, InvalidTransition):
                    projected = self._state.set_state(
                        projection.plan_id,
                        PlanStateV1.BLOCKED,
                        "restart kill requires reconciliation",
                    )
            output.append(
                RecoveryRecordV1(
                    projection.plan_id,
                    projection.mission_id,
                    projected.state,
                    f"mission_store:{mission.state}",
                )
            )
        return tuple(output)


def create_phase6_agentic_core_v1(
    *,
    gate: AgenticFeatureGateV1,
    sidecar_path: Path | str,
    mission_store: MissionStore,
    workspace_scope: WorkspaceScopeV1,
) -> AgenticCoreV1:
    """Host-owned explicit factory; no environment lookup or live defaults."""
    if type(gate) is not AgenticFeatureGateV1 or not gate.enabled:
        raise AgenticCoreV1Denied("Phase 6 agentic core is disabled")
    state = AgenticStateStoreV1(sidecar_path, gate)
    return AgenticCoreV1(state, mission_store, workspace_scope)
