from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError

import pytest

import core.phase6_provider_registry_v1 as registry_module
from core.phase6_agentic_core_v1 import (
    AdapterStatusV1,
    DataClassV1,
    ModelDescriptorV1,
    ModelRouterV1,
    RouteRequestV1,
)
from core.phase6_provider_registry_v1 import (
    CANDIDATE,
    FEATURE_FLAG,
    ZERO_DIGEST,
    ProviderHealthStatusV1,
    ProviderRecordV1,
    ProviderRegistryFeatureGateV1,
    ProviderRegistryV1,
    ProviderRegistryV1ContractError,
    ProviderRegistryV1Denied,
    ProviderRoutePlanStatusV1,
    create_provider_health_observation_v1,
    create_provider_registry_v1,
)

KEY = b"health-authentication-key-v1...."
PROMPT_DIGEST = "1" * 64
EVAL_DIGEST = "2" * 64


def descriptor(
    adapter_id: str,
    *,
    local: bool,
    modalities: tuple[str, ...] = ("text",),
    workspaces: tuple[str, ...] = ("workspace_a",),
    maximum_data_class: DataClassV1 = DataClassV1.RESTRICTED,
    structured: bool = True,
    cost: int = 10,
    latency: int = 100,
    reliability: int = 990,
    status: AdapterStatusV1 = AdapterStatusV1.AVAILABLE_LOCAL,
) -> ModelDescriptorV1:
    return ModelDescriptorV1(
        adapter_id,
        status,
        modalities,
        maximum_data_class,
        workspaces,
        local,
        not local,
        structured,
        reliability,
        latency,
        cost,
    )


def record(
    adapter_id: str,
    *,
    provider_id: str | None = None,
    local: bool = True,
    **descriptor_overrides,
) -> ProviderRecordV1:
    return ProviderRecordV1(
        provider_id or adapter_id,
        "v1",
        f"models/{adapter_id}",
        1,
        PROMPT_DIGEST,
        EVAL_DIGEST,
        descriptor(adapter_id, local=local, **descriptor_overrides),
    )


def registry(*records: ProviderRecordV1) -> ProviderRegistryV1:
    result = create_provider_registry_v1(
        gate=ProviderRegistryFeatureGateV1(True),
        records=records,
        health_authentication_key=KEY,
    )
    assert type(result) is ProviderRegistryV1
    return result


def observation(
    item: ProviderRecordV1,
    *,
    sequence: int = 1,
    observed_at_ms: int = 1_000,
    expires_at_ms: int = 2_000,
    status: ProviderHealthStatusV1 = ProviderHealthStatusV1.AVAILABLE,
    previous_digest: str = ZERO_DIGEST,
    key: bytes = KEY,
):
    return create_provider_health_observation_v1(
        adapter_id=item.adapter_id,
        record_version=item.record_version,
        sequence=sequence,
        observed_at_ms=observed_at_ms,
        expires_at_ms=expires_at_ms,
        status=status,
        previous_digest=previous_digest,
        authentication_key=key,
    )


def request(
    *,
    data_class: DataClassV1 = DataClassV1.INTERNAL,
    modality: str = "text",
    local: bool = False,
    structured: bool = False,
    latency: int = 10_000,
    cost: int = 10_000,
    reliability: int = 0,
    workspace: str = "workspace_a",
) -> RouteRequestV1:
    return RouteRequestV1(
        workspace,
        data_class,
        modality,
        local,
        structured,
        latency,
        cost,
        reliability,
    )


@pytest.mark.parametrize("value", [None, "", "1", "TRUE", " true", "true "])
def test_exact_flag_is_default_off(value):
    env = {} if value is None else {FEATURE_FLAG: value}
    gate = ProviderRegistryFeatureGateV1.from_environ(env)
    assert gate.enabled is False
    assert (
        create_provider_registry_v1(
            gate=gate,
            records=(),
            health_authentication_key=b"",
        )
        is None
    )
    assert (
        ProviderRegistryFeatureGateV1.from_environ({FEATURE_FLAG: "true"}).enabled
        is True
    )


def test_factory_only_immutable_versioned_records_and_exact_core_types():
    item = record("local_a")
    with pytest.raises(ProviderRegistryV1Denied):
        ProviderRegistryV1(_key=object(), records=(item,), authentication_key=KEY)
    catalog = registry(item)
    assert CANDIDATE == "phase6-provider-registry-candidate-001"
    assert registry_module._MODEL_DESCRIPTOR_TYPE is ModelDescriptorV1
    assert registry_module._ROUTE_REQUEST_TYPE is RouteRequestV1
    assert registry_module._MODEL_ROUTER_TYPE is ModelRouterV1
    assert catalog.records == (item,)
    assert item.record_version == 1
    assert item.prompt_metadata_digest == PROMPT_DIGEST
    assert item.evaluation_metadata_digest == EVAL_DIGEST
    with pytest.raises(FrozenInstanceError):
        item.record_version = 2


def test_duplicate_adapter_and_provider_route_are_denied():
    first = record("local_a", provider_id="provider")
    duplicate_adapter = ProviderRecordV1(
        "other",
        "v1",
        "models/other",
        1,
        PROMPT_DIGEST,
        EVAL_DIGEST,
        first.descriptor,
    )
    duplicate_route = ProviderRecordV1(
        first.provider_id,
        first.api_version,
        first.model_id,
        2,
        PROMPT_DIGEST,
        EVAL_DIGEST,
        descriptor("local_b", local=True),
    )
    with pytest.raises(ProviderRegistryV1Denied):
        registry(first, duplicate_adapter)
    with pytest.raises(ProviderRegistryV1Denied):
        registry(first, duplicate_route)


def test_authenticated_health_is_monotonic_and_replay_out_of_order_forgery_denied():
    item = record("local_a")
    catalog = registry(item)
    first = observation(item)
    assert catalog.observe_health(first, received_at_ms=1_000) == first.digest
    with pytest.raises(ProviderRegistryV1Denied):
        catalog.observe_health(first, received_at_ms=1_001)
    skipped = observation(
        item,
        sequence=3,
        observed_at_ms=1_100,
        expires_at_ms=2_100,
        previous_digest=first.digest,
    )
    with pytest.raises(ProviderRegistryV1Denied):
        catalog.observe_health(skipped, received_at_ms=1_100)
    out_of_order = observation(
        item,
        sequence=2,
        observed_at_ms=1_000,
        expires_at_ms=2_000,
        previous_digest=first.digest,
    )
    with pytest.raises(ProviderRegistryV1Denied):
        catalog.observe_health(out_of_order, received_at_ms=1_001)
    forged = observation(
        item,
        sequence=2,
        observed_at_ms=1_100,
        expires_at_ms=2_100,
        previous_digest=first.digest,
        key=b"x" * 32,
    )
    with pytest.raises(ProviderRegistryV1Denied):
        catalog.observe_health(forged, received_at_ms=1_100)
    second = observation(
        item,
        sequence=2,
        observed_at_ms=1_100,
        expires_at_ms=2_100,
        previous_digest=first.digest,
    )
    assert catalog.observe_health(second, received_at_ms=1_100) == second.digest
    assert "prompt" not in repr(second).lower()
    assert "content" not in repr(second).lower()


def test_record_and_stored_health_drift_are_denied():
    item = record("local_a")
    catalog = registry(item)
    health = observation(item)
    catalog.observe_health(health, received_at_ms=1_000)
    object.__setattr__(item, "record_version", 2)
    with pytest.raises(ProviderRegistryV1Denied):
        catalog.plan_route(request(), now_ms=1_100)

    second_item = record("local_b")
    second_catalog = registry(second_item)
    second_health = observation(second_item)
    second_catalog.observe_health(second_health, received_at_ms=1_000)
    object.__setattr__(second_health, "status", ProviderHealthStatusV1.UNAVAILABLE)
    with pytest.raises(ProviderRegistryV1Denied):
        second_catalog.plan_route(request(), now_ms=1_100)


def test_health_authority_and_snapshot_membership_drift_are_denied():
    item = record("local_a")
    key_drift = registry(item)
    object.__setattr__(key_drift, "_authentication_key", b"x" * 32)
    forged = observation(item, key=b"x" * 32)
    with pytest.raises(ProviderRegistryV1Denied):
        key_drift.observe_health(forged, received_at_ms=1_000)

    snapshot_drift = registry(item)
    accepted = observation(item)
    snapshot_drift.observe_health(accepted, received_at_ms=1_000)
    snapshot_drift._health.pop(item.adapter_id)
    replay = observation(item)
    with pytest.raises(ProviderRegistryV1Denied):
        snapshot_drift.observe_health(replay, received_at_ms=1_001)


def test_sensitive_data_cannot_fall_back_to_remote():
    remote = record("remote_a", local=False)
    catalog = registry(remote)
    catalog.observe_health(observation(remote), received_at_ms=1_000)
    plan = catalog.plan_route(
        request(data_class=DataClassV1.CONFIDENTIAL), now_ms=1_100
    )
    assert plan.status is ProviderRoutePlanStatusV1.BLOCKED
    assert plan.reason == "privacy_hard_filter"
    assert plan.ordered_targets == ()


def test_hard_filters_precede_health_and_budget_is_explicitly_blocked():
    expensive = record("local_a", cost=100)
    catalog = registry(expensive)
    plan = catalog.plan_route(request(cost=99), now_ms=1_100)
    assert plan.status is ProviderRoutePlanStatusV1.BLOCKED
    assert plan.reason == "budget_hard_filter"
    assert plan.primary is None
    assert plan.fallbacks == ()


@pytest.mark.parametrize(
    ("item", "route_request", "reason"),
    [
        (
            record("workspace", workspaces=("workspace_b",)),
            request(),
            "workspace_hard_filter",
        ),
        (
            record("modality", modalities=("audio",)),
            request(),
            "modality_hard_filter",
        ),
        (
            record("remote", local=False),
            request(local=True),
            "local_hard_filter",
        ),
        (
            record("plain", structured=False),
            request(structured=True),
            "structured_hard_filter",
        ),
    ],
)
def test_workspace_modality_local_and_structured_filters_are_explicit(
    item, route_request, reason
):
    catalog = registry(item)
    assert catalog.plan_route(route_request, now_ms=1_100).reason == reason


@pytest.mark.parametrize(
    "status",
    [ProviderHealthStatusV1.UNAVAILABLE, ProviderHealthStatusV1.RATE_LIMITED],
)
def test_unavailable_rate_limited_and_stale_health_block(status):
    item = record("local_a")
    catalog = registry(item)
    catalog.observe_health(observation(item, status=status), received_at_ms=1_000)
    blocked = catalog.plan_route(request(), now_ms=1_100)
    assert blocked.status is ProviderRoutePlanStatusV1.BLOCKED
    assert blocked.reason == "health_unavailable"

    fresh_catalog = registry(item)
    fresh_catalog.observe_health(observation(item), received_at_ms=1_000)
    stale = fresh_catalog.plan_route(request(), now_ms=2_001)
    assert stale.status is ProviderRoutePlanStatusV1.BLOCKED
    assert stale.reason == "health_unavailable"


def test_existing_router_ranking_produces_ordered_primary_and_fallback_only():
    local = record("local", local=True, cost=20, reliability=999, latency=20)
    remote = record("remote", local=False, cost=10, reliability=990, latency=10)
    degraded = record("degraded", local=True, cost=30, reliability=980, latency=30)
    catalog = registry(local, remote, degraded)
    for item, status in (
        (local, ProviderHealthStatusV1.AVAILABLE),
        (remote, ProviderHealthStatusV1.AVAILABLE),
        (degraded, ProviderHealthStatusV1.DEGRADED),
    ):
        catalog.observe_health(observation(item, status=status), received_at_ms=1_000)
    plan = catalog.plan_route(request(data_class=DataClassV1.INTERNAL), now_ms=1_100)
    assert plan.status is ProviderRoutePlanStatusV1.READY
    assert tuple(item.adapter_id for item in plan.ordered_targets) == (
        "remote",
        "local",
        "degraded",
    )
    assert plan.primary is plan.ordered_targets[0]
    assert plan.fallbacks == plan.ordered_targets[1:]
    assert not hasattr(plan, "invoke")
    assert not hasattr(plan, "send")


def test_cancel_is_explicit_blocked_and_never_exposes_route():
    item = record("local_a")
    catalog = registry(item)
    plan = catalog.plan_route(request(), now_ms=1_000, cancelled=True)
    assert plan.status is ProviderRoutePlanStatusV1.BLOCKED
    assert plan.reason == "request_cancelled"
    assert plan.ordered_targets == ()
    with pytest.raises(ProviderRegistryV1ContractError):
        catalog.plan_route(request(), now_ms=1_000, cancelled=1)


def test_ast_has_no_provider_invocation_or_network_surface():
    source = open(registry_module.__file__, encoding="utf-8").read()
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "core.phase6_agentic_core_v1"
        for alias in node.names
    }
    assert {"ModelDescriptorV1", "RouteRequestV1", "ModelRouterV1"} <= imported
    forbidden_imports = {
        "requests",
        "httpx",
        "aiohttp",
        "google.genai",
        "openai",
        "socket",
    }
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not forbidden_imports & imports
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not {"invoke", "send", "connect", "generate_content"} & calls
