from __future__ import annotations

import inspect
import json
import time
from pathlib import Path

import pytest

from core import phase6_network_text_provider_v1 as network_text
from core.phase6_agentic_core_v1 import (
    AdapterStatusV1,
    DataClassV1,
    ModelDescriptorV1,
)
from core.phase6_network_text_provider_v1 import (
    NetworkTextBudgetV1,
    NetworkTextCancellationV1,
    NetworkTextClientV1,
    NetworkTextConfigV1,
    NetworkTextContractError,
    NetworkTextDenied,
    NetworkTextFeatureGateV1,
    NetworkTextHttpResponseV1,
    NetworkTextMessageV1,
    NetworkTextNotDispatched,
    NetworkTextProviderV1,
    NetworkTextReconciliationDecisionV1,
    NetworkTextRequestV1,
    NetworkTextToolV1,
    ROUTES,
    SqliteNetworkTextAttemptStoreV1,
    create_network_text_authority_issuer_v1,
    create_network_text_client_v1,
    create_network_text_pool_v1,
)
from core.phase6_provider_registry_v1 import (
    ZERO_DIGEST,
    ProviderHealthStatusV1,
    ProviderRecordV1,
    ProviderRegistryFeatureGateV1,
    create_provider_health_observation_v1,
    create_provider_registry_v1,
)


ROOT = Path(__file__).resolve().parents[1]
ZERO = "0" * 64
REGISTRY_KEY = b"r" * 32
SECRET = b"sk-vault-only-secret"


class Vault:
    def __init__(self, value=SECRET, error: Exception | None = None):
        self.value = value
        self.error = error
        self.aliases: list[str] = []

    def resolve(self, alias: str):
        self.aliases.append(alias)
        if self.error:
            raise self.error
        return self.value


class FakeHttp:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def post(self, request, cancellation):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if callable(outcome):
            outcome = outcome()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class LiveAccountCapability:
    """Test double for the capability the future live activation must own."""

    def __init__(
        self,
        owner_id="owner-1",
        workspace_id="workspace-1",
        account_id="account-1",
    ):
        self.owner_id = owner_id
        self.workspace_id = workspace_id
        self.account_id = account_id

    def resolve_current_account(self, provider):
        assert type(provider) is NetworkTextProviderV1
        return self.owner_id, self.workspace_id, self.account_id


def route(provider):
    return next(item for item in ROUTES if item.provider is provider)


def registry_for(
    configs,
    *,
    key=REGISTRY_KEY,
    adapter_status=AdapterStatusV1.AVAILABLE_LOCAL,
    modalities=("text",),
    workspaces=("workspace-1",),
    maximum_data_class=DataClassV1.INTERNAL,
    local_private=False,
    structured=True,
    health_status=ProviderHealthStatusV1.AVAILABLE,
    observe_health=True,
    provider_id=None,
    health_epoch_ms=None,
):
    records = []
    for config in configs:
        policy = route(config.provider)
        descriptor = ModelDescriptorV1(
            policy.adapter_id,
            adapter_status,
            modalities,
            maximum_data_class,
            workspaces,
            local_private,
            not local_private,
            structured,
            900,
            10,
            1,
        )
        records.append(
            ProviderRecordV1(
                config.provider.value if provider_id is None else provider_id,
                policy.api_version,
                config.model,
                1,
                ZERO,
                ZERO,
                descriptor,
            )
        )
    result = create_provider_registry_v1(
        gate=ProviderRegistryFeatureGateV1(True),
        records=tuple(records),
        health_authentication_key=key,
    )
    assert result is not None
    if observe_health:
        if health_epoch_ms is None:
            health_epoch_ms = time.time_ns() // 1_000_000
        for item in records:
            observation = create_provider_health_observation_v1(
                adapter_id=item.adapter_id,
                record_version=item.record_version,
                sequence=1,
                observed_at_ms=health_epoch_ms - 1,
                expires_at_ms=health_epoch_ms + 299_999,
                status=health_status,
                previous_digest=ZERO_DIGEST,
                authentication_key=key,
            )
            result.observe_health(observation, received_at_ms=health_epoch_ms)
    return result


def host_bindings(_tmp_path):
    return LiveAccountCapability()


def make_client(
    tmp_path,
    provider,
    model,
    outcomes,
    *,
    store=None,
    key=REGISTRY_KEY,
    health_epoch_ms=None,
):
    config = NetworkTextConfigV1(provider, model)
    registry = registry_for((config,), key=key, health_epoch_ms=health_epoch_ms)
    bindings = host_bindings(tmp_path)
    issuer = create_network_text_authority_issuer_v1(
        registry=registry, account_resolver=bindings
    )
    authority = issuer.issue(config)
    vault = Vault()
    http = FakeHttp(outcomes)
    selected_store = store or SqliteNetworkTextAttemptStoreV1(
        (tmp_path / f"{provider.value}.sqlite").resolve()
    )
    client = create_network_text_client_v1(
        gate=NetworkTextFeatureGateV1(True),
        config=config,
        authority=authority,
        authority_issuer=issuer,
        account_resolver=bindings,
        credential_resolver=vault,
        transport=http,
        attempt_store=selected_store,
    )
    assert client is not None
    return client, http, vault, issuer, authority, selected_store, bindings


def req(
    *,
    request_id="request-1",
    stream=False,
    tools=(),
    tokens=128,
    prompt="go",
    timeout=2.0,
    data_class=DataClassV1.INTERNAL,
):
    return NetworkTextRequestV1(
        request_id,
        (
            NetworkTextMessageV1("system", "Be precise."),
            NetworkTextMessageV1("user", prompt),
        ),
        tools,
        stream,
        NetworkTextBudgetV1(
            maximum_request_bytes=32_768,
            maximum_response_bytes=32_768,
            maximum_output_tokens=tokens,
            maximum_stream_events=32,
            timeout_seconds=timeout,
        ),
        data_class,
    )


def response(provider, body, status=200, final_url=None):
    policy = route(provider)
    return NetworkTextHttpResponseV1(
        status,
        final_url or f"https://{policy.origin}{policy.path}",
        body if type(body) is bytes else json.dumps(body).encode(),
    )


def test_default_off_has_no_dependencies() -> None:
    assert not NetworkTextFeatureGateV1().enabled
    assert create_network_text_client_v1(gate=NetworkTextFeatureGateV1(False)) is None
    assert create_network_text_pool_v1(gate=NetworkTextFeatureGateV1(False)) is None


def test_current_anthropic_pinned_ids_and_retired_ids_excluded() -> None:
    models = route(NetworkTextProviderV1.ANTHROPIC).models
    assert "claude-sonnet-5" in models
    assert "claude-opus-4-8" in models
    assert "claude-sonnet-4-6" in models
    assert "claude-haiku-4-5-20251001" in models
    assert "claude-sonnet-4-20250514" not in models
    assert "claude-3-5-haiku-20241022" not in models


def test_success_route_alias_and_groq_parameter_are_exact(tmp_path) -> None:
    provider = NetworkTextProviderV1.GROQ
    client, http, vault, *_ = make_client(
        tmp_path,
        provider,
        "llama-3.3-70b-versatile",
        [response(provider, {"choices": [{"message": {"content": "ok"}}]})],
    )
    result = client.invoke(req())
    assert result.status == "completed"
    assert vault.aliases == [
        "onyx/network-text/owner-1/workspace-1/groq/account-1"
    ]
    wire = http.requests[0]
    payload = json.loads(wire.body)
    assert payload["max_completion_tokens"] == 128
    assert "max_tokens" not in payload
    assert wire.url == "https://api.groq.com/openai/v1/chat/completions"
    assert SECRET not in wire.body


def test_anthropic_success_and_tool_call_schema_is_enforced(tmp_path) -> None:
    provider = NetworkTextProviderV1.ANTHROPIC
    schema = {
        "type": "object",
        "properties": {"id": {"type": "string", "pattern": "[0-9]+"}},
        "required": ["id"],
        "additionalProperties": False,
    }
    tool = NetworkTextToolV1("lookup", "Lookup", schema)
    client, _, _, *_ = make_client(
        tmp_path,
        provider,
        "claude-sonnet-4-6",
        [
            response(
                provider,
                {
                    "content": [
                        {"type": "text", "text": "done"},
                        {
                            "type": "tool_use",
                            "id": "call-1",
                            "name": "lookup",
                            "input": {"id": "42"},
                        },
                    ]
                },
            )
        ],
    )
    result = client.invoke(req(tools=(tool,)))
    assert result.status == "completed"
    assert result.tool_calls[0].arguments == {"id": "42"}
    assert result.tool_calls_digest == result.tool_calls[0].digest or result.tool_calls_digest
    assert result.receipt_payload()["tool_calls_digest"] == result.tool_calls_digest


@pytest.mark.parametrize(
    "call,status",
    [
        (
            {"id": "x", "function": {"name": "delete", "arguments": "{}"}},
            "blocked",
        ),
        (
            {
                "id": "x",
                "function": {"name": "lookup", "arguments": '{"id":7}'},
            },
            "malformed",
        ),
    ],
)
def test_unoffered_or_schema_invalid_tool_call_fails_closed(tmp_path, call, status) -> None:
    provider = NetworkTextProviderV1.OPENAI
    tool = NetworkTextToolV1(
        "lookup",
        "Lookup",
        {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    )
    client, *_ = make_client(
        tmp_path,
        provider,
        "gpt-4.1",
        [response(provider, {"choices": [{"message": {"tool_calls": [call]}}]})],
    )
    assert client.invoke(req(tools=(tool,))).status == status


def test_schema_and_arguments_are_deep_frozen(tmp_path) -> None:
    original = {
        "type": "object",
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
        "additionalProperties": False,
    }
    tool = NetworkTextToolV1("lookup", "", original)
    original["properties"]["id"]["type"] = "integer"
    with pytest.raises(TypeError):
        tool.input_schema["properties"]["id"]["type"] = "integer"
    assert tool.input_schema["properties"]["id"]["type"] == "string"


def test_stream_with_tools_fails_before_vault_store_or_dispatch(tmp_path) -> None:
    tool = NetworkTextToolV1(
        "lookup",
        "",
        {"type": "object", "properties": {}, "additionalProperties": False},
    )
    client, http, vault, *_ = make_client(
        tmp_path, NetworkTextProviderV1.OPENAI, "gpt-4.1", []
    )
    events = list(client.stream(req(stream=True, tools=(tool,))))
    assert events[-1]["result"].reason == "stream_tools_unsupported"
    assert not vault.aliases
    assert not http.requests


def test_durable_completed_replay_survives_new_store_and_issuer(tmp_path) -> None:
    provider = NetworkTextProviderV1.OPENAI
    health_epoch_ms = time.time_ns() // 1_000_000
    path = (tmp_path / "durable.sqlite").resolve()
    store = SqliteNetworkTextAttemptStoreV1(path)
    first, first_http, *_ = make_client(
        tmp_path,
        provider,
        "gpt-4.1",
        [response(provider, {"choices": [{"message": {"content": "once"}}]})],
        store=store,
        health_epoch_ms=health_epoch_ms,
    )
    original = first.invoke(req())
    assert len(first_http.requests) == 1
    reopened = SqliteNetworkTextAttemptStoreV1(path)
    second, second_http, second_vault, *_ = make_client(
        tmp_path,
        provider,
        "gpt-4.1",
        [],
        store=reopened,
        health_epoch_ms=health_epoch_ms,
    )
    second_vault.value = None
    replay = second.invoke(req())
    assert replay == original
    assert not second_http.requests
    assert not second_vault.aliases


def test_timeout_is_durable_unknown_and_never_resent(tmp_path) -> None:
    provider = NetworkTextProviderV1.OPENAI
    client, http, *_ = make_client(
        tmp_path, provider, "gpt-4.1", [TimeoutError("secret detail")]
    )
    first = client.invoke(req())
    second = client.invoke(req())
    assert first.status == second.status == "reconciliation_required"
    assert first.reason == "dispatch_outcome_unknown"
    assert second.reason == "prior_dispatch_unknown"
    assert len(http.requests) == 1
    assert "secret detail" not in repr(first)


def test_explicit_reconciliation_can_confirm_not_dispatched_then_retry(tmp_path) -> None:
    provider = NetworkTextProviderV1.OPENAI
    client, http, *_ = make_client(
        tmp_path,
        provider,
        "gpt-4.1",
        [
            TimeoutError("unknown"),
            response(provider, {"choices": [{"message": {"content": "after-proof"}}]}),
        ],
    )
    request = req()
    assert client.invoke(request).status == "reconciliation_required"
    client.reconcile(
        request, NetworkTextReconciliationDecisionV1.CONFIRMED_NOT_DISPATCHED
    )
    assert client.invoke(request).content == "after-proof"
    assert len(http.requests) == 2


def test_same_request_id_with_different_digest_is_blocked(tmp_path) -> None:
    provider = NetworkTextProviderV1.OPENAI
    client, http, *_ = make_client(
        tmp_path,
        provider,
        "gpt-4.1",
        [response(provider, {"choices": [{"message": {"content": "one"}}]})],
    )
    assert client.invoke(req(prompt="one")).status == "completed"
    assert client.invoke(req(prompt="two")).status == "blocked"
    assert len(http.requests) == 1


def test_only_explicit_not_dispatched_can_fallback(tmp_path) -> None:
    configs = (
        NetworkTextConfigV1(NetworkTextProviderV1.OPENAI, "gpt-4.1"),
        NetworkTextConfigV1(
            NetworkTextProviderV1.GROQ, "llama-3.3-70b-versatile"
        ),
    )
    registry = registry_for(configs)
    bindings = host_bindings(tmp_path)
    issuer = create_network_text_authority_issuer_v1(
        registry=registry, account_resolver=bindings
    )
    store = SqliteNetworkTextAttemptStoreV1((tmp_path / "pool.sqlite").resolve())
    clients = []
    https = []
    for config, outcomes in zip(
        configs,
        (
            [NetworkTextNotDispatched("proof")],
            [
                response(
                    NetworkTextProviderV1.GROQ,
                    {"choices": [{"message": {"content": "fallback"}}]},
                )
            ],
        ),
        strict=True,
    ):
        http = FakeHttp(outcomes)
        https.append(http)
        item = create_network_text_client_v1(
            gate=NetworkTextFeatureGateV1(True),
            config=config,
            authority=issuer.issue(config),
            authority_issuer=issuer,
            account_resolver=bindings,
            credential_resolver=Vault(),
            transport=http,
            attempt_store=store,
        )
        assert item is not None
        clients.append(item)
    pool = create_network_text_pool_v1(
        gate=NetworkTextFeatureGateV1(True), clients=tuple(clients)
    )
    assert pool is not None
    result = pool.invoke(req())
    assert result.content == "fallback"
    assert [len(http.requests) for http in https] == [1, 1]

    # Reopen the durable store and rebuild the whole pool.  The pool-level
    # claim must replay the terminal Groq result exactly; the leading OpenAI
    # route must neither reinterpret it nor send a second request.
    replay_store = SqliteNetworkTextAttemptStoreV1(
        (tmp_path / "pool.sqlite").resolve()
    )
    replay_https = [FakeHttp([]), FakeHttp([])]
    replay_clients = tuple(
        create_network_text_client_v1(
            gate=NetworkTextFeatureGateV1(True),
            config=config,
            authority=issuer.issue(config),
            authority_issuer=issuer,
            account_resolver=bindings,
            credential_resolver=Vault(),
            transport=http,
            attempt_store=replay_store,
        )
        for config, http in zip(configs, replay_https, strict=True)
    )
    assert all(item is not None for item in replay_clients)
    replay_pool = create_network_text_pool_v1(
        gate=NetworkTextFeatureGateV1(True), clients=replay_clients
    )
    assert replay_pool is not None
    assert replay_pool.invoke(req()) == result
    assert [len(http.requests) for http in replay_https] == [0, 0]


def test_public_factories_expose_no_identity_or_alias_minting_surface() -> None:
    forbidden = {
        "owner",
        "owner_id",
        "workspace",
        "workspace_id",
        "account",
        "account_id",
        "alias",
        "credential_alias",
        "identity",
    }
    for factory in (
        create_network_text_authority_issuer_v1,
        create_network_text_client_v1,
        create_network_text_pool_v1,
    ):
        assert forbidden.isdisjoint(inspect.signature(factory).parameters)
    assert forbidden.isdisjoint(inspect.signature(NetworkTextRequestV1).parameters)
    assert not hasattr(network_text, "_FACTORY_KEY")
    assert not hasattr(network_text, "create_network_text_host_binding_resolver_v1")
    assert "part of the TCB" in (network_text.__doc__ or "")


def test_enabled_authority_and_client_fail_closed_without_live_capability(
    tmp_path,
) -> None:
    config = NetworkTextConfigV1(NetworkTextProviderV1.OPENAI, "gpt-4.1")
    registry = registry_for((config,))
    with pytest.raises(NetworkTextContractError, match="account resolver required"):
        create_network_text_authority_issuer_v1(registry=registry)

    resolver = LiveAccountCapability()
    issuer = create_network_text_authority_issuer_v1(
        registry=registry, account_resolver=resolver
    )
    with pytest.raises(NetworkTextContractError, match="injected dependencies"):
        create_network_text_client_v1(
            gate=NetworkTextFeatureGateV1(True),
            config=config,
            authority=issuer.issue(config),
            authority_issuer=issuer,
            credential_resolver=Vault(),
            transport=FakeHttp([]),
            attempt_store=SqliteNetworkTextAttemptStoreV1(
                (tmp_path / "missing-capability.sqlite").resolve()
            ),
        )


@pytest.mark.parametrize(
    "registry_options",
    (
        {"workspaces": ("victim-workspace",)},
        {"adapter_status": AdapterStatusV1.DECLARED_DISABLED},
        {"health_status": ProviderHealthStatusV1.UNAVAILABLE},
        {"observe_health": False},
        {"maximum_data_class": DataClassV1.PUBLIC},
        {"modalities": ("vision",)},
        {"local_private": True},
        {"provider_id": "victim_provider"},
    ),
    ids=(
        "workspace",
        "status",
        "unhealthy",
        "missing-health",
        "privacy",
        "modality",
        "network-policy",
        "provider-identity",
    ),
)
def test_authority_requires_registry_ready_exact_network_route(
    registry_options,
) -> None:
    config = NetworkTextConfigV1(NetworkTextProviderV1.OPENAI, "gpt-4.1")
    registry = registry_for((config,), **registry_options)
    issuer = create_network_text_authority_issuer_v1(
        registry=registry, account_resolver=LiveAccountCapability()
    )
    with pytest.raises(NetworkTextDenied):
        issuer.issue(config)


def test_registry_authoritative_degraded_ready_route_can_be_issued() -> None:
    config = NetworkTextConfigV1(NetworkTextProviderV1.OPENAI, "gpt-4.1")
    registry = registry_for(
        (config,), health_status=ProviderHealthStatusV1.DEGRADED
    )
    issuer = create_network_text_authority_issuer_v1(
        registry=registry, account_resolver=LiveAccountCapability()
    )
    assert issuer.issue(config).digest


def test_request_privacy_is_revalidated_immediately_before_dispatch(tmp_path) -> None:
    client, http, *_ = make_client(
        tmp_path,
        NetworkTextProviderV1.OPENAI,
        "gpt-4.1",
        [
            response(
                NetworkTextProviderV1.OPENAI,
                {"choices": [{"message": {"content": "must-not-send"}}]},
            )
        ],
    )
    result = client.invoke(req(data_class=DataClassV1.CONFIDENTIAL))
    assert result.status == "blocked"
    assert http.requests == []


def test_account_and_health_drift_are_revalidated_before_dispatch(tmp_path) -> None:
    client, http, _, issuer, _, _, resolver = make_client(
        tmp_path,
        NetworkTextProviderV1.OPENAI,
        "gpt-4.1",
        [
            response(
                NetworkTextProviderV1.OPENAI,
                {"choices": [{"message": {"content": "must-not-send"}}]},
            )
        ],
    )
    resolver.workspace_id = "victim-workspace"
    assert client.invoke(req(request_id="account-drift")).status == "blocked"
    assert http.requests == []

    resolver.workspace_id = "workspace-1"
    registry = issuer._registry
    adapter_id = route(NetworkTextProviderV1.OPENAI).adapter_id
    prior = registry._health[adapter_id]
    now_ms = time.time_ns() // 1_000_000
    unavailable = create_provider_health_observation_v1(
        adapter_id=adapter_id,
        record_version=1,
        sequence=2,
        observed_at_ms=max(prior.observed_at_ms + 1, now_ms - 1),
        expires_at_ms=now_ms + 120_000,
        status=ProviderHealthStatusV1.UNAVAILABLE,
        previous_digest=prior.digest,
        authentication_key=REGISTRY_KEY,
    )
    registry.observe_health(unavailable, received_at_ms=now_ms)
    assert client.invoke(req(request_id="health-drift")).status == "blocked"
    assert http.requests == []


def test_resolver_mutation_during_vault_lookup_is_proven_not_dispatched(
    tmp_path,
) -> None:
    client, http, _, _, _, _, resolver = make_client(
        tmp_path,
        NetworkTextProviderV1.OPENAI,
        "gpt-4.1",
        [
            response(
                NetworkTextProviderV1.OPENAI,
                {"choices": [{"message": {"content": "fresh"}}]},
            )
        ],
    )

    class MutatingVault(Vault):
        def resolve(self, alias):
            credential = super().resolve(alias)
            resolver.workspace_id = "victim-workspace"
            return credential

    client._resolver = MutatingVault(b"stale-secret")
    request = req(request_id="vault-toctou")
    denied = client.invoke(request)
    assert denied.status == "unavailable"
    assert denied.reason == "safe_not_dispatched"
    assert http.requests == []

    resolver.workspace_id = "workspace-1"
    client._resolver = Vault(b"fresh-secret")
    completed = client.invoke(request)
    assert completed.status == "completed"
    assert len(http.requests) == 1
    assert http.requests[0].headers["Authorization"] == "Bearer fresh-secret"
    assert "stale-secret" not in str(http.requests[0].headers)


def test_vault_capability_mutation_during_wire_build_has_zero_http_and_retries(
    tmp_path, monkeypatch
) -> None:
    client, http, vault, *_ = make_client(
        tmp_path,
        NetworkTextProviderV1.OPENAI,
        "gpt-4.1",
        [
            response(
                NetworkTextProviderV1.OPENAI,
                {"choices": [{"message": {"content": "fresh"}}]},
            )
        ],
    )
    vault.value = b"stale-secret"
    fresh_vault = Vault(b"fresh-secret")
    original_wire = NetworkTextClientV1._wire_request

    def mutate_after_wire(self, request, credential, remaining_seconds):
        wire = original_wire(self, request, credential, remaining_seconds)
        self._resolver = fresh_vault
        return wire

    monkeypatch.setattr(NetworkTextClientV1, "_wire_request", mutate_after_wire)
    request = req(request_id="wire-toctou")
    denied = client.invoke(request)
    assert denied.status == "unavailable"
    assert denied.reason == "safe_not_dispatched"
    assert http.requests == []

    monkeypatch.setattr(NetworkTextClientV1, "_wire_request", original_wire)
    completed = client.invoke(request)
    assert completed.status == "completed"
    assert len(http.requests) == 1
    assert http.requests[0].headers["Authorization"] == "Bearer fresh-secret"
    assert "stale-secret" not in str(http.requests[0].headers)


def test_sqlite_attempt_store_releases_windows_file_handles(tmp_path) -> None:
    store_dir = tmp_path / "attempt-handles"
    store = SqliteNetworkTextAttemptStoreV1(
        (store_dir / "attempts.sqlite").resolve()
    )
    client, http, *_ = make_client(
        tmp_path,
        NetworkTextProviderV1.OPENAI,
        "gpt-4.1",
        [
            response(
                NetworkTextProviderV1.OPENAI,
                {"choices": [{"message": {"content": "closed"}}]},
            )
        ],
        store=store,
    )
    assert client.invoke(req(request_id="handle-cleanup")).status == "completed"
    assert len(http.requests) == 1

    # Windows refuses this rename while SQLite still owns any file in the
    # directory.  Running it on every platform keeps the invariant portable.
    moved = tmp_path / "attempt-handles-moved"
    store_dir.rename(moved)
    moved.rename(store_dir)


def test_forged_authority_or_different_registry_key_is_rejected(tmp_path) -> None:
    config = NetworkTextConfigV1(NetworkTextProviderV1.OPENAI, "gpt-4.1")
    registry = registry_for((config,))
    bindings = host_bindings(tmp_path)
    issuer = create_network_text_authority_issuer_v1(
        registry=registry, account_resolver=bindings
    )
    authority = issuer.issue(config)
    object.__setattr__(authority, "_seal", ZERO)
    with pytest.raises(NetworkTextDenied, match="forged"):
        create_network_text_client_v1(
            gate=NetworkTextFeatureGateV1(True),
            config=config,
            authority=authority,
            authority_issuer=issuer,
            account_resolver=bindings,
            credential_resolver=Vault(),
            transport=FakeHttp([]),
            attempt_store=SqliteNetworkTextAttemptStoreV1(
                (tmp_path / "forged.sqlite").resolve()
            ),
        )


def test_origin_spoof_is_known_blocked_and_replayed_without_resend(tmp_path) -> None:
    provider = NetworkTextProviderV1.OPENAI
    client, http, *_ = make_client(
        tmp_path,
        provider,
        "gpt-4.1",
        [
            response(
                provider,
                {"choices": [{"message": {"content": "bad"}}]},
                final_url="https://evil.example/v1/chat/completions",
            )
        ],
    )
    first = client.invoke(req())
    second = client.invoke(req())
    assert first.status == "blocked"
    assert second == first
    assert len(http.requests) == 1


def test_local_monotonic_deadline_after_blocking_transport_is_unknown(tmp_path) -> None:
    provider = NetworkTextProviderV1.OPENAI

    def slow():
        time.sleep(0.15)
        return response(provider, {"choices": [{"message": {"content": "late"}}]})

    client, http, *_ = make_client(tmp_path, provider, "gpt-4.1", [slow])
    result = client.invoke(req(timeout=0.1))
    assert result.status == "reconciliation_required"
    assert len(http.requests) == 1


def test_conservative_local_output_budget_is_enforced(tmp_path) -> None:
    provider = NetworkTextProviderV1.OPENAI
    client, *_ = make_client(
        tmp_path,
        provider,
        "gpt-4.1",
        [response(provider, {"choices": [{"message": {"content": "0123456789"}}]})],
    )
    assert client.invoke(req(tokens=1)).status == "budget_exceeded"


def test_stream_success_chunking_and_partial_cancel_never_resend(tmp_path) -> None:
    provider = NetworkTextProviderV1.OPENAI
    cancellation = NetworkTextCancellationV1()

    def body():
        yield b'data: {"choices":[{"delta":{"content":"fi'
        yield b'rst"},"finish_reason":null}]}\n'
        cancellation.cancel()
        yield b'data: [DONE]\n'

    stream_response = NetworkTextHttpResponseV1(
        200, "https://api.openai.com/v1/chat/completions", body()
    )
    client, http, *_ = make_client(
        tmp_path, provider, "gpt-4.1", [stream_response]
    )
    request = req(stream=True)
    events = list(client.stream(request, cancellation))
    assert events[0] == {"type": "text", "text": "first"}
    assert events[-1]["result"].status == "partial_failure"
    assert list(client.stream(request))[-1]["result"].reason == "prior_dispatch_unknown"
    assert len(http.requests) == 1


def test_receipt_has_hashes_only_and_voice_is_untouched(tmp_path) -> None:
    provider = NetworkTextProviderV1.OPENAI
    client, *_ = make_client(
        tmp_path,
        provider,
        "gpt-4.1",
        [response(provider, {"choices": [{"message": {"content": "private-output"}}]})],
    )
    result = client.invoke(req(prompt="private-prompt"))
    receipt = json.dumps(result.receipt_payload())
    for forbidden in (
        "private-output",
        "private-prompt",
        SECRET.decode(),
        "api.openai.com",
        "onyx/network-text",
    ):
        assert forbidden not in receipt
    source = (ROOT / "core/phase6_network_text_provider_v1.py").read_text("utf-8").lower()
    for forbidden in ("gemini", "charon", "native audio", "import main", "phase6_live_wiring"):
        assert forbidden not in source


def test_invalid_schema_constraints_and_secret_fields_fail_early() -> None:
    with pytest.raises(NetworkTextContractError):
        NetworkTextToolV1(
            "bad", "", {"type": "string", "minLength": "one"}
        )
    with pytest.raises(NetworkTextDenied):
        NetworkTextToolV1(
            "bad",
            "",
            {
                "type": "object",
                "properties": {"api_key": {"type": "string"}},
                "additionalProperties": False,
            },
        )
