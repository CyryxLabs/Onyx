from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

import pytest

from core.missions import MissionStore
from core.phase5_integration_v3 import (
    CatalogSeedV3,
    IntegrationFlagsV3,
    Phase5IntegrationV3,
)
from core.phase5_runtime_v10 import RuntimeBindingV10
from core.phase6_agentic_core_v1 import (
    AdapterStatusV1,
    DataClassV1,
    GoalV1,
    MissionBudgetV1,
    PlanStateV1,
    WorkspaceScopeV1,
)
from core.phase6_agentic_core_v6 import (
    AgenticCoreV6,
    AgenticFeatureGateV6,
    AgenticStateStoreV6,
)
from core.phase6_live_integration_v1 import (
    CancellationTokenV1,
    CatalogReadRequestV1,
    CurrentTextProviderAdapterV1,
    IntegrationReceiptStoreV1,
    LiveIntegrationFeatureGateV1,
    LocalCatalogReadBindingV1,
    Phase6LiveIntegrationV1Denied,
    Phase6LiveIntegrationV1Error,
    TextProviderBudgetV1,
    TextProviderConfigV1,
    TextProviderRequestV1,
    create_phase6_live_integration_v1,
)
from core.phase6_agentic_core_v2 import artifact_root_v2


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = "workspace-integration"
FROZEN = {
    "core/phase6_agentic_core_v6.py": (
        "38f68d7dd8eb04fe7c9caa956db5a52d0a96426bab6a45f07b96e67e45d8001a"
    ),
    "core/phase5_integration_v3.py": (
        "52d48c121da485c024811e6cd3fafbabaed971175d7cb41ad23358c5c2879b0d"
    ),
    "core/llm_client.py": (
        "e5c0f805e0d10a07e38054316fb9c6423409190cfa0f48bc39694e65c6a4e417"
    ),
    "core/missions.py": (
        "fe2074eb132c09beecb9f13c5151659e745cf888676c4244c037e0a7ed7f2fe5"
    ),
    "main.py": ("6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712"),
    "ui.py": ("e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b"),
    "dashboard/server.py": (
        "4d3142dc9c6a78cfe76f804de2b154334da2d7790484783a993babc92300bae1"
    ),
}


def _success_text(
    prompt: str,
    system: str | None,
    model: str,
    timeout: int,
    provider: str,
    base_url: str,
) -> str:
    assert prompt
    assert model
    assert timeout >= 1
    assert provider in {"ollama", "openai"}
    assert base_url.startswith("http")
    del system
    return "bounded local result"


def _secret_failure(
    prompt: str,
    system: str | None,
    model: str,
    timeout: int,
    provider: str,
    base_url: str,
) -> str:
    del prompt, system, model, timeout, provider, base_url
    raise RuntimeError("SECRET-DO-NOT-LEAK")


def _slow_text(
    prompt: str,
    system: str | None,
    model: str,
    timeout: int,
    provider: str,
    base_url: str,
) -> str:
    del prompt, system, model, timeout, provider, base_url
    time.sleep(2)
    return "late"


class _InlineExecutor:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    def invoke(self, callback, timeout, *args):
        assert timeout > 0
        self.calls += 1
        return callback(*args)

    def close(self) -> None:
        self.closed = True


def _phase5(*, catalog_enabled: bool = True) -> Phase5IntegrationV3:
    return Phase5IntegrationV3(
        binding=RuntimeBindingV10(
            "trace-phase6-live-v1",
            "session-phase6-live-v1",
            WORKSPACE,
            "account-integration",
            "profile-integration",
        ),
        principal_id="owner-integration",
        flags=IntegrationFlagsV3(
            integration=True,
            runtime=True,
            low_risk=True,
            local_catalog_read=catalog_enabled,
        ),
        catalog=(
            CatalogSeedV3("system_status", "System Status"),
            CatalogSeedV3("memory_search", "Memory Search"),
        ),
    )


def _goal(
    *,
    goal_id: str = "goal_phase6_live_v1",
    correlation_id: str = "corr_phase6_live_v1",
    data_class: DataClassV1 = DataClassV1.INTERNAL,
) -> GoalV1:
    return GoalV1(
        goal_id,
        correlation_id,
        WORKSPACE,
        "Read local capability metadata",
        ("catalog_receipt_observed",),
        ("local_catalog",),
        ("no_network",),
        data_class,
        MissionBudgetV1(
            max_steps=1,
            wall_seconds=30.0,
            max_retries_per_step=0,
            max_repair_cycles=0,
            max_compute_seconds=5.0,
        ),
    )


def _catalog_step(page_size: int = 1) -> dict[str, object]:
    return {
        "step_id": "step_catalog_read",
        "capability": "local_catalog_read",
        "arguments": {"page_size": page_size},
        "dependencies": [],
        "timeout_seconds": 2.0,
        "max_retries": 0,
        "postconditions": ["catalog_receipt_observed"],
    }


def _text_request(
    *,
    request_id: str = "request_text_local",
    workspace: str = WORKSPACE,
    data_class: DataClassV1 = DataClassV1.INTERNAL,
    wall_seconds: float = 2.0,
    prompt: str = "private prompt SECRET-PROMPT",
    system: str | None = "private system SECRET-SYSTEM",
) -> TextProviderRequestV1:
    return TextProviderRequestV1(
        request_id,
        workspace,
        data_class,
        prompt,
        system,
        TextProviderBudgetV1(wall_seconds),
    )


def _facade(
    tmp_path: Path,
    *,
    phase5: Phase5IntegrationV3 | None = None,
    text_max: DataClassV1 = DataClassV1.CONFIDENTIAL,
):
    state = AgenticStateStoreV6(tmp_path / "phase6.sqlite3", AgenticFeatureGateV6(True))
    missions = MissionStore(tmp_path / "missions.sqlite3")
    scope = WorkspaceScopeV1(
        WORKSPACE, (str(tmp_path.resolve()),), DataClassV1.CONFIDENTIAL
    )
    core = AgenticCoreV6(state, missions, scope)
    bridge = phase5 or _phase5()
    receipt_store = IntegrationReceiptStoreV1(tmp_path / "receipts.sqlite3")
    catalog = LocalCatalogReadBindingV1(
        phase5=bridge,
        receipt_store=receipt_store,
        maximum_data_class=DataClassV1.CONFIDENTIAL,
    )
    inline = _InlineExecutor()
    text = CurrentTextProviderAdapterV1(
        workspace_id=WORKSPACE,
        config=TextProviderConfigV1("ollama", "http://127.0.0.1:11434", "test-model"),
        invoke=_success_text,
        maximum_data_class=text_max,
        latency_millis=0,
        executor=inline,  # type: ignore[arg-type]
    )
    facade = create_phase6_live_integration_v1(
        gate=LiveIntegrationFeatureGateV1(True),
        agentic_core=core,
        agentic_state=state,
        catalog=catalog,
        text=text,
    )
    assert facade is not None
    return facade, state, receipt_store, inline


def test_frozen_dependencies_and_live_surfaces_remain_exact() -> None:
    for relative, digest in FROZEN.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest


def test_feature_gate_is_strict_and_factory_off_is_true_noop() -> None:
    assert not LiveIntegrationFeatureGateV1.from_environ({}).enabled
    assert not LiveIntegrationFeatureGateV1.from_environ(
        {"ONYX_PHASE6_LIVE_INTEGRATION_V1": "TRUE"}
    ).enabled
    assert LiveIntegrationFeatureGateV1.from_environ(
        {"ONYX_PHASE6_LIVE_INTEGRATION_V1": "true"}
    ).enabled
    assert (
        create_phase6_live_integration_v1(
            gate=LiveIntegrationFeatureGateV1(False),
        )
        is None
    )


def test_extension_is_not_imported_by_live_surfaces() -> None:
    marker = "phase6_live_integration_v1"
    for relative in ("main.py", "ui.py", "dashboard/server.py"):
        assert marker not in (ROOT / relative).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://localhost:11434", AdapterStatusV1.AVAILABLE_LOCAL),
        ("http://127.0.0.1:11434", AdapterStatusV1.AVAILABLE_LOCAL),
        ("http://[::1]:11434", AdapterStatusV1.AVAILABLE_LOCAL),
        ("https://models.example.test", AdapterStatusV1.BLOCKED_BY_POLICY),
        ("http://user:secret@localhost:11434", AdapterStatusV1.BLOCKED_BY_POLICY),
    ],
)
def test_text_descriptor_blocks_every_nonlocal_or_credentialed_route(
    url: str, expected: AdapterStatusV1
) -> None:
    adapter = CurrentTextProviderAdapterV1(
        workspace_id=WORKSPACE,
        config=TextProviderConfigV1("ollama", url, "test-model"),
        executor=_InlineExecutor(),  # type: ignore[arg-type]
    )
    try:
        assert adapter.descriptor.status is expected
        assert adapter.descriptor.local_private is (
            expected is AdapterStatusV1.AVAILABLE_LOCAL
        )
    finally:
        adapter.close()


def test_text_adapter_enforces_workspace_and_privacy_before_provider_call() -> None:
    executor = _InlineExecutor()
    adapter = CurrentTextProviderAdapterV1(
        workspace_id=WORKSPACE,
        config=TextProviderConfigV1("ollama", "http://localhost:11434", "test-model"),
        invoke=_success_text,
        maximum_data_class=DataClassV1.INTERNAL,
        latency_millis=0,
        executor=executor,  # type: ignore[arg-type]
    )
    try:
        wrong_workspace = adapter.invoke(_text_request(workspace="workspace-other"))
        too_sensitive = adapter.invoke(
            _text_request(
                request_id="request_text_secret",
                data_class=DataClassV1.CONFIDENTIAL,
            )
        )
        assert wrong_workspace.status == "blocked"
        assert too_sensitive.status == "blocked"
        assert executor.calls == 0
    finally:
        adapter.close()


def test_text_success_is_bounded_and_receipt_redacts_payloads() -> None:
    executor = _InlineExecutor()
    adapter = CurrentTextProviderAdapterV1(
        workspace_id=WORKSPACE,
        config=TextProviderConfigV1("openai", "http://localhost:1234", "test-model"),
        invoke=_success_text,
        latency_millis=0,
        executor=executor,  # type: ignore[arg-type]
    )
    try:
        result = adapter.invoke(_text_request())
        assert result.status == "completed"
        assert result.content == "bounded local result"
        assert result.provider_calls == 1
        assert result.reserved_output_tokens == 600
        receipt = json.dumps(result.receipt_payload(), sort_keys=True)
        assert "SECRET-PROMPT" not in receipt
        assert "SECRET-SYSTEM" not in receipt
        assert "bounded local result" not in receipt
        assert "localhost" not in receipt
        assert "test-model" not in receipt
    finally:
        adapter.close()


def test_current_text_call_pins_authorized_config_against_later_drift(
    monkeypatch,
) -> None:
    from core import llm_client

    observed: list[str] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": "pinned local response"}}]}

    def _post(url, **_kwargs):
        observed.append(url)
        return _Response()

    monkeypatch.setattr(llm_client, "get_llm_provider", lambda: "openai")
    monkeypatch.setattr(
        llm_client,
        "get_llm_settings",
        lambda: ("https://remote.example.test", "drifted-model"),
    )
    monkeypatch.setattr(llm_client.requests, "post", _post)
    adapter = CurrentTextProviderAdapterV1(
        workspace_id=WORKSPACE,
        config=TextProviderConfigV1("openai", "http://127.0.0.1:1234", "pinned-model"),
        latency_millis=0,
        executor=_InlineExecutor(),  # type: ignore[arg-type]
    )
    try:
        result = adapter.invoke(_text_request(request_id="request_text_pinned"))
        assert result.status == "completed"
        assert result.content == "pinned local response"
        assert observed == ["http://127.0.0.1:1234/v1/chat/completions"]
        assert llm_client.get_llm_settings()[0] == "https://remote.example.test"
    finally:
        adapter.close()


def test_text_outage_returns_sanitized_explicit_fallback_boundary() -> None:
    executor = _InlineExecutor()
    adapter = CurrentTextProviderAdapterV1(
        workspace_id=WORKSPACE,
        config=TextProviderConfigV1("ollama", "http://localhost:11434", "test-model"),
        invoke=_secret_failure,
        latency_millis=0,
        executor=executor,  # type: ignore[arg-type]
    )
    try:
        result = adapter.invoke(_text_request())
        assert result.status == "unavailable"
        assert result.reason == "provider_call_unavailable"
        encoded = json.dumps(result.receipt_payload(), sort_keys=True)
        assert "SECRET-DO-NOT-LEAK" not in encoded
        assert result.provider_calls == 1
        # The adapter never cross-routes. Existing callers remain the explicit fallback.
        assert adapter.descriptor.workspace_allowlist == (WORKSPACE,)
    finally:
        adapter.close()


def test_text_cancellation_before_dispatch_consumes_no_budget() -> None:
    executor = _InlineExecutor()
    adapter = CurrentTextProviderAdapterV1(
        workspace_id=WORKSPACE,
        config=TextProviderConfigV1("ollama", "http://localhost:11434", "test-model"),
        invoke=_success_text,
        latency_millis=0,
        executor=executor,  # type: ignore[arg-type]
    )
    token = CancellationTokenV1()
    token.cancel()
    try:
        result = adapter.invoke(_text_request(), token)
        assert result.status == "cancelled"
        assert result.provider_calls == 0
        assert result.reserved_output_tokens == 0
        assert executor.calls == 0
    finally:
        adapter.close()


def test_text_timeout_terminates_provider_process() -> None:
    adapter = CurrentTextProviderAdapterV1(
        workspace_id=WORKSPACE,
        config=TextProviderConfigV1("ollama", "http://localhost:11434", "test-model"),
        invoke=_slow_text,
        latency_millis=0,
    )
    try:
        started = time.monotonic()
        result = adapter.invoke(
            _text_request(request_id="request_text_timeout", wall_seconds=0.1)
        )
        assert result.status == "timed_out"
        assert time.monotonic() - started < 1.5
        assert result.provider_calls == 1
    finally:
        adapter.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"max_api_calls": 2},
        {"max_output_tokens": 599},
        {"max_cost_micro": 1},
        {"wall_seconds": float("nan")},
        {"wall_seconds": float("inf")},
        {"wall_seconds": True},
    ],
)
def test_text_budget_rejects_unenforceable_or_nonfinite_values(changes) -> None:
    values = {
        "wall_seconds": 1.0,
        "max_api_calls": 1,
        "max_output_tokens": 600,
        "max_cost_micro": 0,
    }
    values.update(changes)
    with pytest.raises(ValueError):
        TextProviderBudgetV1(**values)


def test_catalog_binding_executes_only_exact_phase5_read_and_redacts_cursor(
    tmp_path: Path,
) -> None:
    bridge = _phase5()
    store = IntegrationReceiptStoreV1(tmp_path / "receipts.sqlite3")
    binding = LocalCatalogReadBindingV1(phase5=bridge, receipt_store=store)
    request = CatalogReadRequestV1(
        "request_catalog_page",
        WORKSPACE,
        DataClassV1.INTERNAL,
        {"page_size": 1, "cursor": None},
    )
    result, receipt = binding.execute(request)
    assert result["state"] == "completed"
    assert len(result["items"]) == 1
    assert receipt.phase5_receipt_digest == result["receipt_digest"]
    assert receipt.cost_micro == 0
    assert receipt.egress == "none"
    encoded = json.dumps(receipt.payload(), sort_keys=True)
    assert str(result["next_cursor"]) not in encoded


def test_catalog_receipt_is_durable_idempotent_and_conflicts_fail_closed(
    tmp_path: Path,
) -> None:
    bridge = _phase5()
    store = IntegrationReceiptStoreV1(tmp_path / "receipts.sqlite3")
    binding = LocalCatalogReadBindingV1(phase5=bridge, receipt_store=store)
    request = CatalogReadRequestV1(
        "request_catalog_idempotent",
        WORKSPACE,
        DataClassV1.INTERNAL,
        {"page_size": 1},
    )
    first_result, first = binding.execute(request)
    replay_result, replay = binding.execute(request)
    assert first_result["state"] == "completed"
    assert replay_result == {"replayed": True}
    assert replay == first
    reopened = IntegrationReceiptStoreV1(tmp_path / "receipts.sqlite3")
    assert reopened.get(request.request_id) == first
    with pytest.raises(Phase6LiveIntegrationV1Denied):
        binding.execute(
            CatalogReadRequestV1(
                request.request_id,
                WORKSPACE,
                DataClassV1.INTERNAL,
                {"page_size": 2},
            )
        )


def test_catalog_cancel_wrong_workspace_and_privacy_never_reach_phase5(
    tmp_path: Path,
) -> None:
    bridge = _phase5()
    store = IntegrationReceiptStoreV1(tmp_path / "receipts.sqlite3")
    binding = LocalCatalogReadBindingV1(
        phase5=bridge,
        receipt_store=store,
        maximum_data_class=DataClassV1.INTERNAL,
    )
    token = CancellationTokenV1()
    token.cancel()
    with pytest.raises(Phase6LiveIntegrationV1Denied):
        binding.execute(
            CatalogReadRequestV1(
                "request_catalog_cancel",
                WORKSPACE,
                DataClassV1.INTERNAL,
                {},
            ),
            token,
        )
    with pytest.raises(Phase6LiveIntegrationV1Denied):
        binding.execute(
            CatalogReadRequestV1(
                "request_catalog_other",
                "workspace-other",
                DataClassV1.INTERNAL,
                {},
            )
        )
    with pytest.raises(Phase6LiveIntegrationV1Denied):
        binding.execute(
            CatalogReadRequestV1(
                "request_catalog_restricted",
                WORKSPACE,
                DataClassV1.RESTRICTED,
                {},
            )
        )
    assert store.get("request_catalog_cancel") is None


def test_receipt_store_schema_tamper_fails_closed_without_repair(
    tmp_path: Path,
) -> None:
    path = tmp_path / "receipts.sqlite3"
    IntegrationReceiptStoreV1(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TRIGGER catalog_receipts_no_delete")
        connection.commit()
    finally:
        connection.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(Phase6LiveIntegrationV1Error):
        IntegrationReceiptStoreV1(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_facade_connects_v6_plan_to_phase5_receipt_without_mission_execution(
    tmp_path: Path,
) -> None:
    facade, state, _store, _inline = _facade(tmp_path)
    try:
        projection = facade.submit(
            _goal(), "request_key_phase6_live_v1", [_catalog_step()]
        )
        assert projection.state is PlanStateV1.PLANNED
        outcome = facade.execute_local_catalog_plan(
            projection.plan_id, "request_catalog_plan"
        )
        assert outcome.state is PlanStateV1.WAITING_FOR_PHASE5
        assert outcome.receipt is not None
        assert outcome.result is not None
        assert outcome.reason == "phase5_authoritative_read_receipted"
        persisted = state.get_projection(projection.plan_id)
        assert persisted.mission_id is None
        assert persisted.state is PlanStateV1.WAITING_FOR_PHASE5
    finally:
        facade.close()


def test_facade_outage_stays_waiting_and_does_not_silently_fallback(
    tmp_path: Path,
) -> None:
    facade, state, _store, _inline = _facade(
        tmp_path, phase5=_phase5(catalog_enabled=False)
    )
    try:
        projection = facade.submit(
            _goal(
                goal_id="goal_phase6_outage",
                correlation_id="corr_phase6_outage",
            ),
            "request_key_phase6_outage",
            [_catalog_step()],
        )
        outcome = facade.execute_local_catalog_plan(
            projection.plan_id, "request_catalog_outage"
        )
        assert outcome.reason == "catalog_unavailable_no_silent_fallback"
        assert outcome.receipt is None
        assert state.get_projection(projection.plan_id).state is (
            PlanStateV1.WAITING_FOR_PHASE5
        )
    finally:
        facade.close()


def test_external_agent_descriptor_is_disabled_and_blocked_by_access(
    tmp_path: Path,
) -> None:
    facade, _state, _store, inline = _facade(tmp_path)
    try:
        assert facade.external_agent.adapter_id == "external_agent_disabled"
        assert facade.external_agent.status is AdapterStatusV1.BLOCKED_BY_ACCESS
    finally:
        facade.close()
    assert inline.closed


def test_checkpoint_manifest_recomputes_exact_artifact_root() -> None:
    manifest_path = (
        ROOT / "docs/onyx/checkpoints/phase6-live-integration-v1/manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = {item["path"]: item["sha256"] for item in manifest["artifacts"]}
    assert len(artifacts) == len(manifest["artifacts"])
    assert all(
        hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
        for relative, digest in artifacts.items()
    )
    assert artifact_root_v2(artifacts) == manifest["artifact_root_sha256"]
