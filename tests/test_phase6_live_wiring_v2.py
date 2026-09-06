from __future__ import annotations

import hashlib
import inspect
import json
import multiprocessing
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import types
from unittest.mock import patch

import psutil
import pytest

import main
from core import onyx_live_activation_v7 as activation_v7
from core import phase6_live_wiring_v1 as wiring_v1
from core import phase6_live_wiring_v2 as wiring_v2
from core.live_model import DEFAULT_LIVE_MODEL
from core.missions import MissionStore
from core.phase6_agentic_core_v1 import DataClassV1
from core.phase6_disabled_external_agent_descriptor_v1 import (
    DisabledExternalAgentDescriptorCatalogV1,
)
from core.phase6_local_mcp_v1 import LocalMCPIdentityV1
from core.phase6_provider_registry_v1 import (
    ProviderRoutePlanStatusV1,
    ProviderRegistryV1,
)
from core.phase6_research_cells_v1 import ResearchVerifierPipelineV1
from core.phase6_unified_command_router_v1 import (
    CommandBudgetV1,
    CommandIntentV1,
    CommandPlanStatusV1,
    UnifiedCommandRouterV1,
    UnifiedCommandRouterV1Conflict,
    UserCommandV1,
)


ROOT = Path(__file__).resolve().parents[1]


class Snapshot:
    display_name = None
    reconciled = True
    state = types.SimpleNamespace(value="unknown")
    name_known = False


class Authority:
    def __init__(self) -> None:
        self.snapshot = Snapshot()

    def reconcile(self):
        return self.snapshot

    def begin_contact(self):
        return "Before we continue, what name should I use for you?"

    def prompt_directive(self):
        return "owner-directive"


class FakeUI:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.states: list[str] = []
        self.prompt_count = 0
        self.muted = False
        self._win = types.SimpleNamespace(_hud_v5_live=True)

    def write_log(self, value: str) -> None:
        self.logs.append(value)

    def set_state(self, value: str) -> None:
        self.states.append(value)

    def prompt_reconfig(self) -> None:
        self.prompt_count += 1


@pytest.fixture
def ready_v2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    for name in activation_v7.CONTROL_FLAGS:
        monkeypatch.delenv(name, raising=False)
    environment = activation_v7.exact_activation_environment()
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    contract = activation_v7.preflight_host(main, environment)
    activation = activation_v7.OnyxLiveActivationV7(
        activation_v7.ActivationFlagsV7.from_canonical_environ(environment),
        contract,
        authority_factory=Authority,
    )
    activation.install()
    assert activation.start() is activation_v7.v6.ActivationV6State.READY
    host_type = contract.base.onyx_live
    v1 = wiring_v1.create_phase6_live_wiring_v1(
        gate=wiring_v1.LiveWiringFeatureGateV1(True),
        activation=activation,
        state_root=tmp_path / "phase6-state",
    )
    assert type(v1) is wiring_v1.Phase6LiveWiringV1
    v1.install()
    host_seams = {
        name: getattr(host_type, name)
        for name in (
            *wiring_v1.Phase6LiveWiringV1.PATCHED_SEAMS,
            *wiring_v1.Phase6LiveWiringV1.PROTECTED_SEAMS,
        )
    }
    original_controller_seams = {
        name: getattr(v1, name)
        for name in wiring_v2.Phase6LiveWiringV2.PATCHED_CONTROLLER_SEAMS
    }
    v2 = wiring_v2.create_phase6_live_wiring_v2(
        gate=wiring_v2.LiveWiringV2FeatureGate(True),
        wiring_v1=v1,
        project_root=ROOT,
        model_id=DEFAULT_LIVE_MODEL,
    )
    assert type(v2) is wiring_v2.Phase6LiveWiringV2

    yield types.SimpleNamespace(
        activation=activation,
        host_type=host_type,
        host_seams=host_seams,
        original_controller_seams=original_controller_seams,
        v1=v1,
        v2=v2,
    )

    if v2.installed:
        v2.rollback_installation()
    if v1.installed:
        v1.rollback_installation()
    activation.rollback_installation()


def _budget() -> CommandBudgetV1:
    return CommandBudgetV1(
        maximum_latency_millis=3_600_000,
        maximum_cost_micro=1_000_000_000,
        minimum_reliability_milli=0,
        page_size=10,
        maximum_sources=8,
        maximum_spans=64,
        maximum_evidence_bytes=100_000,
        maximum_evidence_age_ms=5_000,
    )


def _command(
    session: wiring_v2.Phase6OperationalSessionV2,
    *,
    request_id: str,
    data_class: DataClassV1 = DataClassV1.INTERNAL,
    intent: CommandIntentV1 = CommandIntentV1.TEXT_PLAN,
    input_value: str = "prepare daily priorities",
    catalog_cursor: str | None = None,
) -> UserCommandV1:
    modality = {
        CommandIntentV1.TEXT_PLAN: "text",
        CommandIntentV1.LOCAL_CATALOG: "catalog",
        CommandIntentV1.RESEARCH_VERIFY: "research",
    }[intent]
    identity = session.base_session.facade.identity
    return UserCommandV1(
        request_id=request_id,
        identity=identity,
        workspace_id=identity.workspace_id,
        data_class=data_class,
        modality=modality,
        budget=_budget(),
        deadline_at_ms=10_000_000,
        cancelled=False,
        intent=intent,
        input_digest=hashlib.sha256(input_value.encode()).hexdigest(),
        evidence_bundle=None,
        catalog_cursor=catalog_cursor,
    )


def test_v2_is_exact_default_off_with_zero_construction_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    threads = tuple(threading.enumerate())
    children = tuple(multiprocessing.active_children())
    monkeypatch.setattr(
        wiring_v2,
        "_verify_component_roots",
        lambda _root: pytest.fail("disabled V2 verified component roots"),
    )
    assert (
        wiring_v2.create_phase6_live_wiring_v2(
            gate=wiring_v2.LiveWiringV2FeatureGate(False),
        )
        is None
    )
    assert tuple(threading.enumerate()) == threads
    assert tuple(multiprocessing.active_children()) == children
    for value in ("", "1", "TRUE", "True", "yes", " true "):
        assert (
            wiring_v2.LiveWiringV2FeatureGate.from_environ(
                {wiring_v2.FEATURE_FLAG: value}
            ).enabled
            is False
        )
    assert wiring_v2.LiveWiringV2FeatureGate.from_environ(
        {wiring_v2.FEATURE_FLAG: "true"}
    ).enabled


def test_v2_factory_surface_exposes_no_executor_or_adapter_authority() -> None:
    assert tuple(
        inspect.signature(wiring_v2.create_phase6_live_wiring_v2).parameters
    ) == ("gate", "wiring_v1", "project_root", "model_id")
    assert all(
        name not in inspect.signature(wiring_v2.create_phase6_live_wiring_v2).parameters
        for name in (
            "executor",
            "provider",
            "adapter",
            "mcp",
            "network",
            "phase5",
            "identity",
        )
    )


def test_component_acceptance_roots_are_exact_and_leaf_tamper_is_denied(
    tmp_path: Path,
) -> None:
    digest = wiring_v2._verify_component_roots(ROOT)
    assert len(digest) == 64
    for relative, expected in wiring_v2.COMPONENT_ACCEPTANCE_ROOTS:
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    tampered = tmp_path / wiring_v2.COMPONENT_ACCEPTANCE_ROOTS[0][0]
    tampered.write_bytes(tampered.read_bytes() + b"\ntamper")
    with pytest.raises(wiring_v2.Phase6LiveWiringV2Denied):
        wiring_v2._verify_component_roots(tmp_path.resolve())


@pytest.mark.parametrize("fail_after", (0, 1, 2))
def test_each_patch_failpoint_restores_exact_v1_instance(
    ready_v2,
    fail_after: int,
) -> None:
    with pytest.raises(wiring_v2.Phase6LiveWiringV2Error):
        ready_v2.v2.install(fail_after=fail_after)
    assert ready_v2.v2.installed is False
    assert ready_v2.v2._installed_values == {}
    for name, expected in ready_v2.original_controller_seams.items():
        assert getattr(ready_v2.v1, name) == expected
        assert name not in ready_v2.v1.__dict__
    assert all(
        getattr(ready_v2.host_type, name) is expected
        for name, expected in ready_v2.host_seams.items()
    )


def test_install_patches_only_v1_controller_and_rollback_is_exact(ready_v2) -> None:
    ready_v2.v2.install()
    assert ready_v2.v2.installed
    assert all(
        getattr(ready_v2.v1, name) is ready_v2.v2._installed_values[name]
        for name in wiring_v2.Phase6LiveWiringV2.PATCHED_CONTROLLER_SEAMS
    )
    assert all(
        getattr(ready_v2.host_type, name) is expected
        for name, expected in ready_v2.host_seams.items()
    )
    ready_v2.v2.rollback_installation()
    for name, expected in ready_v2.original_controller_seams.items():
        assert getattr(ready_v2.v1, name) == expected
        assert name not in ready_v2.v1.__dict__


def test_real_session_composes_all_authorities_without_operational_calls(
    ready_v2,
) -> None:
    ready_v2.v2.install()
    instance = ready_v2.host_type(FakeUI())
    before_threads = tuple(threading.enumerate())
    before_children = tuple(multiprocessing.active_children())
    before_processes = tuple(
        child.pid for child in psutil.Process().children(recursive=True)
    )
    network_calls = 0
    process_calls = 0

    def refuse_network(*_args: object, **_kwargs: object) -> None:
        nonlocal network_calls
        network_calls += 1
        raise AssertionError("V2 attempted network")

    def refuse_process(*_args: object, **_kwargs: object) -> None:
        nonlocal process_calls
        process_calls += 1
        raise AssertionError("V2 attempted process creation")

    with (
        patch.object(socket.socket, "connect", refuse_network),
        patch.object(subprocess, "Popen", refuse_process),
    ):
        instance._start_phase5_session()
    session = ready_v2.v2.session_for(instance)
    assert type(session) is wiring_v2.Phase6OperationalSessionV2
    assert type(session.provider_registry) is ProviderRegistryV1
    assert type(session.research_pipeline) is ResearchVerifierPipelineV1
    assert type(session.local_mcp_identity) is LocalMCPIdentityV1
    assert type(session.router) is UnifiedCommandRouterV1
    assert type(session.external_descriptor) is DisabledExternalAgentDescriptorCatalogV1
    assert session.external_descriptor.descriptor.health.value == "blocked_by_access"
    assert type(instance._missions) is MissionStore
    assert network_calls == process_calls == 0
    assert tuple(threading.enumerate()) == before_threads
    assert tuple(multiprocessing.active_children()) == before_children
    assert (
        tuple(child.pid for child in psutil.Process().children(recursive=True))
        == before_processes
    )
    assert ready_v2.v1.active_sessions == ready_v2.v2.active_sessions == 1

    instance._stop_phase5_session("test")
    assert session.closed
    assert session.base_session.closed
    assert ready_v2.v1.active_sessions == ready_v2.v2.active_sessions == 0
    assert not hasattr(instance, wiring_v2.SESSION_ATTRIBUTE)


def test_provider_preview_is_authenticated_privacy_bound_and_replay_safe(
    ready_v2,
) -> None:
    ready_v2.v2.install()
    instance = ready_v2.host_type(FakeUI())
    instance._start_phase5_session()
    session = ready_v2.v2.session_for(instance)
    assert session is not None

    ready_command = _command(session, request_id="request-ready")
    plan, receipt = session.preview(
        ready_command,
        now_ms=1_000,
        provider_connected=True,
    )
    assert plan.status is CommandPlanStatusV1.BLOCKED
    assert plan.provider_route_plan is not None
    assert plan.provider_route_plan.status is ProviderRoutePlanStatusV1.BLOCKED
    assert plan.provider_route_plan.reason == "local_hard_filter"
    assert plan.provider_calls == plan.network_calls == plan.live_calls == 0
    assert plan.process_calls == 0
    session.router.attest_receipt(plan, receipt)

    replay_plan, replay_receipt = session.preview(
        ready_command,
        now_ms=2_000,
        provider_connected=True,
    )
    assert replay_plan is plan and replay_receipt is receipt

    with pytest.raises(UnifiedCommandRouterV1Conflict):
        session.preview(
            _command(
                session,
                request_id="request-ready",
                input_value="different input",
            ),
            now_ms=3_000,
            provider_connected=True,
        )

    disconnected, disconnected_receipt = session.preview(
        _command(session, request_id="request-disconnected"),
        now_ms=4_000,
        provider_connected=False,
    )
    assert disconnected.status is CommandPlanStatusV1.BLOCKED
    assert disconnected.provider_route_plan is not None
    assert disconnected.provider_route_plan.reason == "local_hard_filter"
    session.router.attest_receipt(disconnected, disconnected_receipt)

    confidential, confidential_receipt = session.preview(
        _command(
            session,
            request_id="request-confidential",
            data_class=DataClassV1.CONFIDENTIAL,
        ),
        now_ms=5_000,
        provider_connected=True,
    )
    assert confidential.status is CommandPlanStatusV1.BLOCKED
    assert confidential.provider_route_plan is not None
    assert confidential.provider_route_plan.reason == "privacy_hard_filter"
    session.router.attest_receipt(confidential, confidential_receipt)
    instance._stop_phase5_session("test")


def test_local_catalog_preview_never_opens_mcp_or_live_execution(ready_v2) -> None:
    ready_v2.v2.install()
    instance = ready_v2.host_type(FakeUI())
    instance._start_phase5_session()
    session = ready_v2.v2.session_for(instance)
    assert session is not None
    command = _command(
        session,
        request_id="request-catalog",
        intent=CommandIntentV1.LOCAL_CATALOG,
        catalog_cursor="opaque-cursor",
    )
    plan, receipt = session.preview(
        command,
        now_ms=1_000,
        provider_connected=False,
    )
    assert plan.status is CommandPlanStatusV1.READY
    assert plan.tool_name == "local_catalog_read"
    assert plan.mcp_request is not None
    assert plan.mcp_request.identity is session.local_mcp_identity
    assert plan.mcp_request.cursor == "opaque-cursor"
    assert plan.provider_calls == plan.process_calls == 0
    assert plan.network_calls == plan.live_calls == 0
    assert plan.provider_route_plan is None
    session.router.attest_receipt(plan, receipt)
    instance._stop_phase5_session("test")


def test_operational_factory_failure_revokes_base_session_and_phase5(
    ready_v2,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready_v2.v2.install()
    instance = ready_v2.host_type(FakeUI())

    def fail(_base: object) -> wiring_v2.Phase6OperationalSessionV2:
        raise wiring_v2.Phase6LiveWiringV2Denied("injected operational failure")

    monkeypatch.setattr(ready_v2.v2, "_create_operational_session", fail)
    with pytest.raises(wiring_v1.Phase6LiveWiringV1Denied):
        instance._start_phase5_session()
    assert instance._phase5 is None
    assert getattr(instance, wiring_v1.SESSION_ATTRIBUTE) is None
    assert not hasattr(instance, wiring_v2.SESSION_ATTRIBUTE)
    assert ready_v2.v1.active_sessions == ready_v2.v2.active_sessions == 0


def test_attribute_drift_still_closes_both_sessions_and_phase5(ready_v2) -> None:
    ready_v2.v2.install()
    instance = ready_v2.host_type(FakeUI())
    instance._start_phase5_session()
    operational = ready_v2.v2.session_for(instance)
    assert operational is not None
    base = operational.base_session
    setattr(instance, wiring_v2.SESSION_ATTRIBUTE, object())
    with pytest.raises(wiring_v1.Phase6LiveWiringV1Error):
        instance._stop_phase5_session("drift")
    assert operational.closed
    assert base.closed
    assert instance._phase5 is None
    assert getattr(instance, wiring_v1.SESSION_ATTRIBUTE) is None
    assert not hasattr(instance, wiring_v2.SESSION_ATTRIBUTE)
    assert ready_v2.v1.active_sessions == ready_v2.v2.active_sessions == 0


def test_key_drift_is_denied_before_new_session(ready_v2) -> None:
    ready_v2.v2.install()
    original = ready_v2.v2._health_key
    ready_v2.v2._health_key = b"x" * 32
    instance = ready_v2.host_type(FakeUI())
    try:
        with pytest.raises(wiring_v1.Phase6LiveWiringV1Denied):
            instance._start_phase5_session()
    finally:
        ready_v2.v2._health_key = original
    assert instance._phase5 is None
    assert ready_v2.v1.active_sessions == ready_v2.v2.active_sessions == 0


def test_rollback_active_v2_session_leaves_v1_operational(ready_v2) -> None:
    ready_v2.v2.install()
    instance = ready_v2.host_type(FakeUI())
    instance._start_phase5_session()
    operational = ready_v2.v2.session_for(instance)
    assert operational is not None
    base = operational.base_session
    ready_v2.v2.rollback_installation()
    assert operational.closed
    assert not base.closed
    assert ready_v2.v1.installed
    assert getattr(instance, wiring_v1.SESSION_ATTRIBUTE) is base
    assert not hasattr(instance, wiring_v2.SESSION_ATTRIBUTE)
    instance._stop_phase5_session("v1-remains")
    assert base.closed
    assert instance._phase5 is None


def test_candidate_manifest_recomputes_exact_artifact_root() -> None:
    manifest_path = ROOT / "docs/onyx/checkpoints/phase6-live-wiring-v2/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = {item["path"]: item["sha256"] for item in manifest["artifacts"]}
    rows = [f"{path}\0{digest}" for path, digest in artifacts.items()]
    observed_root = hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()
    assert len(artifacts) == len(manifest["artifacts"]) == 5
    assert all(
        hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
        for path, digest in artifacts.items()
    )
    assert observed_root == manifest["artifact_root_sha256"]
