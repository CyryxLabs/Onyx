from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

import core.phase6_unified_command_router_v1 as router_module
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
    ModelDescriptorV1,
    WorkspaceScopeV1,
)
from core.phase6_agentic_core_v6 import (
    AgenticCoreV6,
    AgenticFeatureGateV6,
    AgenticStateStoreV6,
)
from core.phase6_live_integration_v2 import (
    HostIdentityBindingV2,
    LiveIntegrationFeatureGateV2,
    Phase6LiveIntegrationV2,
    create_phase6_live_integration_v2,
)
from core.phase6_local_mcp_v1 import TOOL_NAME, LocalMCPIdentityV1
from core.phase6_provider_registry_v1 import (
    ProviderHealthStatusV1,
    ProviderRecordV1,
    ProviderRegistryFeatureGateV1,
    ProviderRoutePlanStatusV1,
    create_provider_health_observation_v1,
    create_provider_registry_v1,
)
from core.phase6_research_cells_v1 import (
    EvidenceSpanV1,
    ResearchCellsFeatureGateV1,
    VerificationDecisionV1,
    create_authorized_evidence_source_v1,
    create_evidence_bundle_v1,
    create_research_verifier_pipeline_v1,
)
from core.phase6_unified_command_router_v1 import (
    COMPONENT_ACCEPTANCE_ROOTS,
    CommandBudgetV1,
    CommandIntentV1,
    CommandPlanStatusV1,
    CommandReceiptV1,
    UnifiedCommandRouterFeatureGateV1,
    UnifiedCommandRouterV1,
    UnifiedCommandRouterV1Conflict,
    UnifiedCommandRouterV1ContractError,
    UnifiedCommandRouterV1Denied,
    UserCommandV1,
    create_unified_command_router_v1,
)


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = "workspace-router"
ACCOUNT = "account-router"
PROFILE = "profile-router"
PRINCIPAL = "principal-router"
PROVIDER_KEY = b"p" * 32
EVIDENCE_KEY = b"e" * 32
RESEARCH_RECEIPT_KEY = b"r" * 32
ROUTER_RECEIPT_KEY = b"u" * 32


def _identity(
    *,
    workspace_id: str = WORKSPACE,
    account_id: str = ACCOUNT,
    profile_id: str = PROFILE,
    principal_id: str = PRINCIPAL,
) -> HostIdentityBindingV2:
    return HostIdentityBindingV2(
        workspace_id,
        account_id,
        profile_id,
        principal_id,
    )


def _phase5() -> Phase5IntegrationV3:
    return Phase5IntegrationV3(
        binding=RuntimeBindingV10(
            "trace-router-v1",
            "session-router-v1",
            WORKSPACE,
            ACCOUNT,
            PROFILE,
        ),
        principal_id=PRINCIPAL,
        flags=IntegrationFlagsV3(
            integration=True,
            runtime=True,
            low_risk=True,
            local_catalog_read=True,
        ),
        catalog=(CatalogSeedV3("system_status", "System Status"),),
    )


def _provider_record(
    *,
    adapter_id: str = "local-router",
    cost: int = 10,
    latency: int = 100,
    reliability: int = 990,
) -> ProviderRecordV1:
    descriptor = ModelDescriptorV1(
        adapter_id,
        AdapterStatusV1.AVAILABLE_LOCAL,
        ("text",),
        DataClassV1.RESTRICTED,
        (WORKSPACE,),
        True,
        False,
        True,
        reliability,
        latency,
        cost,
    )
    return ProviderRecordV1(
        "provider-router",
        "v1",
        "models/router",
        1,
        "1" * 64,
        "2" * 64,
        descriptor,
    )


def _registry(*, observe_health: bool = True):
    record = _provider_record()
    registry = create_provider_registry_v1(
        gate=ProviderRegistryFeatureGateV1(True),
        records=(record,),
        health_authentication_key=PROVIDER_KEY,
    )
    assert registry is not None
    if observe_health:
        health = create_provider_health_observation_v1(
            adapter_id=record.adapter_id,
            record_version=record.record_version,
            sequence=1,
            observed_at_ms=1_000,
            expires_at_ms=10_000,
            status=ProviderHealthStatusV1.AVAILABLE,
            authentication_key=PROVIDER_KEY,
        )
        registry.observe_health(health, received_at_ms=1_000)
    return registry


@pytest.fixture
def system(tmp_path: Path):
    state = AgenticStateStoreV6(
        tmp_path / "agentic.sqlite3",
        AgenticFeatureGateV6(True),
    )
    core = AgenticCoreV6(
        state,
        MissionStore(tmp_path / "missions.sqlite3"),
        WorkspaceScopeV1(
            WORKSPACE,
            (str(tmp_path.resolve()),),
            DataClassV1.CONFIDENTIAL,
        ),
    )
    identity = _identity()
    live = create_phase6_live_integration_v2(
        gate=LiveIntegrationFeatureGateV2(True),
        identity=identity,
        agentic_core=core,
        agentic_state=state,
        phase5=_phase5(),
        receipt_path=tmp_path / "live-receipts.sqlite3",
    )
    assert live is not None
    research = create_research_verifier_pipeline_v1(
        gate=ResearchCellsFeatureGateV1(True),
        core=core,
        evidence_authority_key=EVIDENCE_KEY,
        receipt_authentication_key=RESEARCH_RECEIPT_KEY,
    )
    assert research is not None
    local_identity = LocalMCPIdentityV1(WORKSPACE, PRINCIPAL)
    registry = _registry()
    router = create_unified_command_router_v1(
        gate=UnifiedCommandRouterFeatureGateV1(True),
        core=core,
        provider_registry=registry,
        research_pipeline=research,
        local_mcp_identity=local_identity,
        live_integration=live,
        project_root=ROOT,
        receipt_authentication_key=ROUTER_RECEIPT_KEY,
    )
    assert router is not None
    yield {
        "router": router,
        "core": core,
        "state": state,
        "identity": identity,
        "live": live,
        "research": research,
        "local_identity": local_identity,
        "registry": registry,
        "tmp_path": tmp_path,
    }
    if not live.closed:
        live.close()


def _budget(**changes: int) -> CommandBudgetV1:
    values = {
        "maximum_latency_millis": 1_000,
        "maximum_cost_micro": 1_000,
        "minimum_reliability_milli": 900,
        "page_size": 10,
        "maximum_sources": 8,
        "maximum_spans": 64,
        "maximum_evidence_bytes": 100_000,
        "maximum_evidence_age_ms": 5_000,
    }
    values.update(changes)
    return CommandBudgetV1(**values)


def _source(
    source_id: str,
    value: str,
    *,
    workspace_id: str = WORKSPACE,
    data_class: DataClassV1 = DataClassV1.INTERNAL,
):
    return create_authorized_evidence_source_v1(
        source_id=source_id,
        source_uri=f"urn:router:{source_id}",
        captured_at_ms=1_000,
        data_class=data_class,
        workspace_id=workspace_id,
        spans=(
            EvidenceSpanV1(
                f"span-{source_id}",
                "fact.answer",
                value,
                f"ignored prose {value}",
            ),
        ),
        evidence_authority_key=EVIDENCE_KEY,
    )


def _bundle(*sources, workspace_id: str = WORKSPACE):
    return create_evidence_bundle_v1(
        bundle_id="bundle-router",
        workspace_id=workspace_id,
        sources=tuple(sorted(sources, key=lambda item: item.source_id)),
        evidence_authority_key=EVIDENCE_KEY,
    )


def _command(
    *,
    request_id: str = "request-router",
    identity: HostIdentityBindingV2 | None = None,
    workspace_id: str = WORKSPACE,
    data_class: DataClassV1 = DataClassV1.INTERNAL,
    intent: CommandIntentV1 = CommandIntentV1.TEXT_PLAN,
    modality: str | None = None,
    budget: CommandBudgetV1 | None = None,
    deadline_at_ms: int = 5_000,
    cancelled: bool = False,
    input_digest: str = "9" * 64,
    evidence_bundle=None,
    catalog_cursor: str | None = None,
) -> UserCommandV1:
    modalities = {
        CommandIntentV1.LOCAL_CATALOG: "catalog",
        CommandIntentV1.RESEARCH_VERIFY: "research",
        CommandIntentV1.TEXT_PLAN: "text",
    }
    return UserCommandV1(
        request_id=request_id,
        identity=identity or _identity(workspace_id=workspace_id),
        workspace_id=workspace_id,
        data_class=data_class,
        modality=modality or modalities[intent],
        budget=budget or _budget(),
        deadline_at_ms=deadline_at_ms,
        cancelled=cancelled,
        intent=intent,
        input_digest=input_digest,
        evidence_bundle=evidence_bundle,
        catalog_cursor=catalog_cursor,
    )


@pytest.mark.parametrize("value", [None, "", "1", "TRUE", " true", "true "])
def test_exact_flag_is_strict_default_off(value):
    environ = {} if value is None else {router_module.FEATURE_FLAG: value}
    gate = UnifiedCommandRouterFeatureGateV1.from_environ(environ)
    assert gate.enabled is False
    assert create_unified_command_router_v1(gate=gate) is None
    assert UnifiedCommandRouterFeatureGateV1.from_environ(
        {router_module.FEATURE_FLAG: "true"}
    ).enabled


def test_factory_only_exact_components_and_accepted_roots(system):
    router = system["router"]
    assert type(router) is UnifiedCommandRouterV1
    assert len(COMPONENT_ACCEPTANCE_ROOTS) == 14
    assert {component for component, _path, _digest in COMPONENT_ACCEPTANCE_ROOTS} == {
        "agentic_core_v6",
        "provider_registry_v1",
        "research_cells_v1",
        "local_mcp_v1",
        "live_integration_v2",
    }
    with pytest.raises(UnifiedCommandRouterV1Denied):
        UnifiedCommandRouterV1(
            _key=object(),
            core=system["core"],
            registry=system["registry"],
            research=system["research"],
            local_identity=system["local_identity"],
            live=system["live"],
            project_root=ROOT,
            receipt_authentication_key=ROUTER_RECEIPT_KEY,
        )


def test_text_plan_is_ordered_provider_metadata_only(system, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("operational seam was invoked")

    monkeypatch.setattr(Phase6LiveIntegrationV2, "submit", forbidden)
    monkeypatch.setattr(Phase6LiveIntegrationV2, "generate_text", forbidden)
    monkeypatch.setattr(
        Phase6LiveIntegrationV2,
        "execute_local_catalog_plan",
        forbidden,
    )
    plan, receipt = system["router"].plan(_command(), now_ms=2_000)
    assert plan.status is CommandPlanStatusV1.READY
    assert plan.provider_route_plan is not None
    assert plan.provider_route_plan.status is ProviderRoutePlanStatusV1.READY
    assert tuple(
        target.adapter_id for target in plan.provider_route_plan.ordered_targets
    ) == ("local-router",)
    assert plan.provider_calls == plan.process_calls == 0
    assert plan.network_calls == plan.live_calls == 0
    assert plan.mcp_request is None
    system["router"].attest_receipt(plan, receipt)


def test_provider_registry_block_is_preserved_without_fallback(system):
    blocked_registry = _registry(observe_health=False)
    router = create_unified_command_router_v1(
        gate=UnifiedCommandRouterFeatureGateV1(True),
        core=system["core"],
        provider_registry=blocked_registry,
        research_pipeline=system["research"],
        local_mcp_identity=system["local_identity"],
        live_integration=system["live"],
        project_root=ROOT,
        receipt_authentication_key=b"b" * 32,
    )
    assert router is not None
    plan, receipt = router.plan(_command(request_id="request-blocked"), now_ms=2_000)
    assert plan.status is CommandPlanStatusV1.BLOCKED
    assert plan.provider_route_plan is not None
    assert plan.provider_route_plan.reason == "health_unavailable"
    assert plan.provider_route_plan.ordered_targets == ()
    router.attest_receipt(plan, receipt)


def test_local_catalog_projects_exact_request_without_opening_mcp_process(system):
    command = _command(
        request_id="request-catalog",
        intent=CommandIntentV1.LOCAL_CATALOG,
        catalog_cursor="opaque-cursor",
    )
    plan, receipt = system["router"].plan(command, now_ms=2_000)
    assert plan.status is CommandPlanStatusV1.READY
    assert plan.tool_name == TOOL_NAME == "local_catalog_read"
    assert plan.mcp_request is not None
    assert plan.mcp_request.identity is system["local_identity"]
    assert plan.mcp_request.page_size == command.budget.page_size
    assert plan.mcp_request.cursor == "opaque-cursor"
    assert plan.process_calls == 0
    assert plan.provider_route_plan is None
    system["router"].attest_receipt(plan, receipt)


def test_research_requires_authenticated_evidence_and_independent_accept(system):
    evidence = _bundle(_source("source-a", "42"))
    command = _command(
        request_id="request-research",
        intent=CommandIntentV1.RESEARCH_VERIFY,
        evidence_bundle=evidence,
    )
    plan, receipt = system["router"].plan(command, now_ms=2_000)
    assert plan.status is CommandPlanStatusV1.READY
    assert plan.verification_decision is VerificationDecisionV1.ACCEPT
    assert plan.finalized_research is not None
    assert plan.research_bundle_digest == evidence.digest
    assert plan.finalized_research.verification_report_digest == (
        plan.verification_report_digest
    )
    assert plan.provider_route_plan is None
    assert plan.mcp_request is None
    system["router"].attest_receipt(plan, receipt)


def test_research_contradiction_is_blocked_and_never_finalized(system):
    evidence = _bundle(
        _source("source-a", "42"),
        _source("source-b", "43"),
    )
    command = _command(
        request_id="request-contradiction",
        intent=CommandIntentV1.RESEARCH_VERIFY,
        evidence_bundle=evidence,
    )
    plan, receipt = system["router"].plan(command, now_ms=2_000)
    assert plan.status is CommandPlanStatusV1.BLOCKED
    assert plan.verification_decision is VerificationDecisionV1.REVISE
    assert plan.finalized_research is None
    assert plan.finalized_research_digest == router_module.ZERO_DIGEST
    system["router"].attest_receipt(plan, receipt)


@pytest.mark.parametrize(
    ("intent", "modality"),
    [
        (CommandIntentV1.LOCAL_CATALOG, "text"),
        (CommandIntentV1.RESEARCH_VERIFY, "catalog"),
        (CommandIntentV1.TEXT_PLAN, "research"),
    ],
)
def test_intent_modality_crossing_is_denied(intent, modality):
    evidence = (
        _bundle(_source("source-a", "42"))
        if intent is CommandIntentV1.RESEARCH_VERIFY
        else None
    )
    with pytest.raises(UnifiedCommandRouterV1Denied):
        _command(intent=intent, modality=modality, evidence_bundle=evidence)


def test_tool_and_evidence_crossing_are_denied():
    evidence = _bundle(_source("source-a", "42"))
    with pytest.raises(UnifiedCommandRouterV1Denied):
        _command(evidence_bundle=evidence)
    with pytest.raises(UnifiedCommandRouterV1Denied):
        _command(
            intent=CommandIntentV1.RESEARCH_VERIFY,
            evidence_bundle=evidence,
            catalog_cursor="crossing",
        )
    with pytest.raises(UnifiedCommandRouterV1Denied):
        _command(catalog_cursor="crossing")


def test_cancellation_identity_and_deadline_fail_before_component_routes(
    system, monkeypatch
):
    calls = {"registry": 0, "research": 0}

    def registry_call(*_args, **_kwargs):
        calls["registry"] += 1
        raise AssertionError("registry should not be reached")

    def research_call(*_args, **_kwargs):
        calls["research"] += 1
        raise AssertionError("research should not be reached")

    monkeypatch.setattr(type(system["registry"]), "plan_route", registry_call)
    monkeypatch.setattr(type(system["research"]), "research", research_call)
    with pytest.raises(UnifiedCommandRouterV1Denied, match="cancellation"):
        system["router"].plan(_command(cancelled=True), now_ms=2_000)
    other_identity = _identity(
        account_id="account-other",
        profile_id="profile-other",
        principal_id="principal-other",
    )
    with pytest.raises(UnifiedCommandRouterV1Denied, match="identity"):
        system["router"].plan(
            _command(request_id="request-identity", identity=other_identity),
            now_ms=2_000,
        )
    with pytest.raises(UnifiedCommandRouterV1Denied, match="deadline"):
        system["router"].plan(
            _command(request_id="request-deadline", deadline_at_ms=1_999),
            now_ms=2_000,
        )
    assert calls == {"registry": 0, "research": 0}


def test_privacy_underdeclaration_and_workspace_crossing_fail_before_pipeline(
    system, monkeypatch
):
    calls = 0

    def research_call(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("pipeline should not be reached")

    monkeypatch.setattr(type(system["research"]), "research", research_call)
    sensitive = _bundle(
        _source(
            "source-sensitive",
            "classified",
            data_class=DataClassV1.CONFIDENTIAL,
        )
    )
    with pytest.raises(UnifiedCommandRouterV1Denied, match="underdeclaration"):
        system["router"].plan(
            _command(
                request_id="request-underclass",
                data_class=DataClassV1.INTERNAL,
                intent=CommandIntentV1.RESEARCH_VERIFY,
                evidence_bundle=sensitive,
            ),
            now_ms=2_000,
        )
    other_source = _source(
        "source-other",
        "42",
        workspace_id="workspace-other",
    )
    other_bundle = _bundle(other_source, workspace_id="workspace-other")
    with pytest.raises(UnifiedCommandRouterV1Denied, match="cross-workspace"):
        system["router"].plan(
            _command(
                request_id="request-cross-workspace",
                intent=CommandIntentV1.RESEARCH_VERIFY,
                evidence_bundle=other_bundle,
            ),
            now_ms=2_000,
        )
    assert calls == 0


def test_latency_budget_is_hard_and_provider_plan_forces_local_private(system):
    with pytest.raises(UnifiedCommandRouterV1Denied, match="latency"):
        system["router"].plan(
            _command(
                request_id="request-latency",
                budget=_budget(maximum_latency_millis=4_000),
                deadline_at_ms=5_000,
            ),
            now_ms=2_000,
        )
    command = _command(request_id="request-private")
    plan, _receipt = system["router"].plan(command, now_ms=2_000)
    assert plan.provider_route_plan is not None
    assert all(
        target.adapter_id == "local-router"
        for target in plan.provider_route_plan.ordered_targets
    )


def test_idempotent_replay_returns_same_objects_and_conflict_is_denied(system):
    command = _command(request_id="request-replay")
    first = system["router"].plan(command, now_ms=2_000)
    second = system["router"].plan(command, now_ms=2_000)
    assert second[0] is first[0]
    assert second[1] is first[1]
    with pytest.raises(UnifiedCommandRouterV1Conflict):
        system["router"].plan(
            replace(command, input_digest="8" * 64),
            now_ms=2_000,
        )


def test_research_replay_does_not_reinvoke_cells(system, monkeypatch):
    command = _command(
        request_id="request-research-replay",
        intent=CommandIntentV1.RESEARCH_VERIFY,
        evidence_bundle=_bundle(_source("source-a", "42")),
    )
    first = system["router"].plan(command, now_ms=2_000)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("research replay was re-executed")

    monkeypatch.setattr(type(system["research"]), "research", forbidden)
    second = system["router"].plan(command, now_ms=2_000)
    assert second[0] is first[0]
    assert second[1] is first[1]


def test_forged_receipt_and_plan_are_denied(system):
    plan, receipt = system["router"].plan(
        _command(request_id="request-forge"),
        now_ms=2_000,
    )
    forged_receipt = replace(receipt, authentication_tag="0" * 64)
    with pytest.raises(UnifiedCommandRouterV1Denied, match="forged"):
        system["router"].attest_receipt(plan, forged_receipt)
    forged_plan = replace(plan, reason="forged_reason")
    with pytest.raises(UnifiedCommandRouterV1Denied, match="forged"):
        system["router"].attest_receipt(forged_plan, receipt)


def test_component_and_dependency_drift_are_denied(system, monkeypatch):
    original = router_module._sha_file
    monkeypatch.setattr(router_module, "_sha_file", lambda _path: "0" * 64)
    with pytest.raises(UnifiedCommandRouterV1Denied, match="acceptance drift"):
        system["router"].plan(
            _command(request_id="request-component-drift"),
            now_ms=2_000,
        )
    monkeypatch.setattr(router_module, "_sha_file", original)
    monkeypatch.setattr(
        router_module.provider_v1,
        "ProviderRegistryV1",
        object,
    )
    with pytest.raises(UnifiedCommandRouterV1Denied, match="authority drift"):
        system["router"].plan(
            _command(request_id="request-type-drift"),
            now_ms=2_000,
        )


def test_receipt_and_rationale_are_content_free(system):
    secret = "private-payroll-number-7742"
    evidence = _bundle(_source("source-secret", secret))
    command = _command(
        request_id="request-content-free",
        intent=CommandIntentV1.RESEARCH_VERIFY,
        evidence_bundle=evidence,
        input_digest=router_module._digest(secret.encode("utf-8")),
    )
    plan, receipt = system["router"].plan(command, now_ms=2_000)
    projected = repr(plan.payload()) + repr(receipt.unsigned_payload())
    assert secret not in projected
    assert "ignored prose" not in projected
    assert all(router_module._CODE.fullmatch(code) for code in plan.rationale_codes)


def test_contracts_are_immutable_and_exact_subclasses_are_rejected(system):
    command = _command(request_id="request-immutable")
    with pytest.raises((FrozenInstanceError, AttributeError)):
        command.workspace_id = "workspace-other"

    class CommandSubclass(UserCommandV1):
        pass

    subclass = CommandSubclass(
        command.request_id,
        command.identity,
        command.workspace_id,
        command.data_class,
        command.modality,
        command.budget,
        command.deadline_at_ms,
        command.cancelled,
        command.intent,
        command.input_digest,
        command.evidence_bundle,
        command.catalog_cursor,
    )
    with pytest.raises(UnifiedCommandRouterV1ContractError, match="exact UserCommand"):
        system["router"].plan(subclass, now_ms=2_000)


def test_receipt_requires_exact_type(system):
    plan, receipt = system["router"].plan(
        _command(request_id="request-exact-receipt"),
        now_ms=2_000,
    )

    class ReceiptSubclass(CommandReceiptV1):
        pass

    forged = ReceiptSubclass(
        *[getattr(receipt, field) for field in receipt.__dataclass_fields__]
    )
    with pytest.raises(UnifiedCommandRouterV1ContractError):
        system["router"].attest_receipt(plan, forged)


def test_source_has_no_live_network_process_or_implicit_intent_surface():
    source = (ROOT / "core/phase6_unified_command_router_v1.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert (
        not {
            "requests",
            "httpx",
            "socket",
            "subprocess",
            "google.genai",
            "openai",
        }
        & imports
    )
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert (
        not {
            "generate_text",
            "execute_local_catalog_plan",
            "call_catalog",
            "submit",
            "Popen",
        }
        & called
    )
    command_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "UserCommandV1"
    )
    field_names = {
        node.target.id
        for node in command_class.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert {"intent", "input_digest", "evidence_bundle"} <= field_names
    assert not {"prompt", "content", "instructions", "provider", "tool"} & field_names
    for relative in ("main.py", "ui.py", "dashboard/server.py"):
        assert "phase6_unified_command_router_v1" not in (ROOT / relative).read_text(
            encoding="utf-8"
        )
