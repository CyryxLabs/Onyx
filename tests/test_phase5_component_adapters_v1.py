from __future__ import annotations

import dataclasses
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import approval_inbox_v15 as inbox_v15
from core import capability_nexus_v32 as nexus_v32
from core import phase5_component_adapters_v1 as adapters
from core import phase5_runtime_v5 as runtime
from core import session_grants_v11 as grants_v11


ROOT = Path(__file__).resolve().parents[1]
BINDING = runtime.RuntimeBindingV5(
    "trace-001", "session-local", "workspace-main", "account-local", "profile-main"
)
FLAGS = adapters.AdapterFlagsV1(True, True, True, True)
ACCEPTED = adapters.AcceptedComponentsV1(
    adapters.GRANTS_ACCEPTANCE_V1,
    adapters.NEXUS_ACCEPTANCE_V1,
    adapters.INBOX_ACCEPTANCE_V1,
)
DIGEST = "a" * 64


def action(**changes: object) -> runtime.ActionRequestV5:
    values: dict[str, object] = {
        "invocation_ref": "invoke-001",
        "binding": BINDING,
        "capability": "local.catalog",
        "operation": "catalog_read",
        "provider_free": True,
        "read_only": True,
        "effect": "none",
        "egress": "none",
        "metadata_allowlisted": True,
        "cost_micro": 0,
        "risk": "low",
        "reversible": True,
    }
    values.update(changes)
    return runtime.ActionRequestV5(**values)


class FakeGrantStore:
    def __init__(self, decision: object | None = None) -> None:
        self.references: list[str] = []
        self.kills = 0
        self.ends = 0
        self.decision = decision or SimpleNamespace(
            outcome="would-allow",
            reason="exact-session-grant",
            grant_id="grant-001",
            scope_digest=DIGEST,
            action_audit_digest="b" * 64,
            callback_required=True,
            authority_granted=False,
        )

    def evaluate(self, reference: str) -> object:
        self.references.append(reference)
        return self.decision

    def kill(self) -> None:
        self.kills += 1

    def end_session(self) -> None:
        self.ends += 1


def local_descriptor(**changes: object) -> nexus_v32.CapabilityDescriptorV32:
    operation = nexus_v32.OperationDescriptorV32(
        operation_id="catalog_read",
        kind=nexus_v32.OperationKindV32.READ,
        description="Read allowlisted metadata.",
        parameter_schema_json='{"properties":{},"type":"OBJECT"}',
        required_scopes=("catalog.metadata.read",),
        data_classes=("allowlisted_metadata",),
        risk_class="low",
        approval_class="host_policy_required",
        allowed_targets=("local_catalog",),
        cost="zero_local_micros",
        host_policy="always_confirm",
    )
    values: dict[str, object] = {
        "capability_id": "local.catalog",
        "capability_version": "v32",
        "provider": "onyx_local",
        "transport": nexus_v32.TransportKindV32.LOCAL,
        "api_name": "local_catalog",
        "api_version": nexus_v32.CATALOG_CONTRACT_VERSION_V32,
        "workspace_id": BINDING.workspace_id,
        "account_id": BINDING.account_id,
        "profile_id": BINDING.profile_id,
        "credential_alias": None,
        "operations": (operation,),
        "status": nexus_v32.CapabilityStatusV32.DISABLED,
        "status_reason": "candidate_not_activated",
        "limitations": ("metadata_only", "no_dispatch"),
    }
    values.update(changes)
    return nexus_v32.CapabilityDescriptorV32(**values)


def local_nexus(**descriptor_changes: object) -> nexus_v32.CapabilityNexusV32:
    nexus = nexus_v32.CapabilityNexusV32()
    nexus.register(local_descriptor(**descriptor_changes))
    return nexus


def host_item(number: int) -> inbox_v15.HostInboxItemV15:
    return inbox_v15.HostInboxItemV15(
        item_id=f"item-{number:03d}",
        action_request_id=f"request-{number:03d}",
        principal_id="owner-primary",
        session_id=BINDING.session_id,
        workspace_id=BINDING.workspace_id,
        workspace_display="Cyryx Main",
        mission_id="mission-daily",
        mission_display="Daily operations",
        account_id=BINDING.account_id,
        account_display="Local workspace account",
        connector_id="calendar-local",
        connector_version="1.0",
        tool_id="calendar-tool",
        operation="create-draft",
        environment="local-draft",
        reason=f"Prepare reviewed item {number}",
        target_display=f"Calendar draft {number}",
        target_digest=f"{number + 10:064x}",
        payload_summary=f"Create a reversible draft for item {number}",
        payload_digest=f"{number + 100:064x}",
        attachment_set_digest="3" * 64,
        policy_version="onyx-policy-1",
        action_schema_version="action-1",
        data_class="internal",
        egress="local-only",
        effect_summary="Creates a draft only",
        reversibility="reversible",
        idempotency_summary=f"One draft for request {number}",
        idempotency_key=f"{number + 200:064x}",
        verification_plan="Read the draft back and compare its digest",
        rollback_plan="Delete the local draft before any external action",
        cost_micro=number,
        currency="USD",
        risk="low",
        created_at_ms=1_700_000_000_000 + number,
        expires_at_ms=1_700_000_100_000 + number,
        always_explicit=False,
        batch_eligible=True,
    )


class InboxHarness:
    def __init__(self, count: int = 3) -> None:
        self.epoch = 7
        self.source_epoch = 1
        self.items = tuple(host_item(index) for index in range(1, count + 1))
        gate = inbox_v15.ApprovalInboxFeatureGateV15(
            environ={inbox_v15.APPROVAL_INBOX_V15_FLAG: "true"},
            epoch_reader=lambda: self.epoch,
        )
        source = inbox_v15.HostInboxSourceV15(
            principal_id="owner-primary",
            session_id=BINDING.session_id,
            capture_callback=lambda: inbox_v15.HostInboxSnapshotV15(
                self.source_epoch, 55_000, self.items
            ),
        )
        self.projection = inbox_v15.ApprovalInboxProjectionV15(
            gate=gate,
            source=source,
            clock=inbox_v15.DeterministicInboxClockV15(1_000),
        )


def build(
    *,
    flags: adapters.AdapterFlagsV1 = FLAGS,
    acceptance: adapters.AcceptedComponentsV1 = ACCEPTED,
    binding_attestor=lambda: BINDING,
    grant_store: object | None = None,
    materializer=None,
    nexus: object | None = None,
    inbox: object | None = None,
) -> adapters.ComponentAdapterBundleV1:
    return adapters.build_component_adapters_v1(
        flags=flags,
        acceptance=acceptance,
        binding=BINDING,
        binding_attestor=binding_attestor,
        batch_factory=runtime.ProjectionBatchV5,
        components_factory=runtime.RuntimeComponentsV5,
        grant_store=grant_store,
        materialize_grant_request=materializer,
        nexus=nexus,
        inbox_projection=inbox,
    )


def test_default_off_builds_no_components_and_never_attests() -> None:
    touched: list[str] = []
    bundle = build(
        flags=adapters.AdapterFlagsV1(),
        acceptance=adapters.AcceptedComponentsV1(),
        binding_attestor=lambda: touched.append("attested"),
    )
    assert bundle.grant is bundle.nexus is bundle.inbox is None
    assert bundle.runtime_components == runtime.RuntimeComponentsV5()
    assert touched == []


def test_child_flag_requires_master_and_disabled_component_supply_is_rejected() -> None:
    with pytest.raises(adapters.Phase5ComponentAdapterV1ContractError):
        adapters.AdapterFlagsV1(False, grant_shadow=True)
    with pytest.raises(
        adapters.Phase5ComponentAdapterV1ContractError,
        match="supplied while its flag is off",
    ):
        build(
            flags=adapters.AdapterFlagsV1(),
            acceptance=adapters.AcceptedComponentsV1(),
            grant_store=FakeGrantStore(),
        )


@pytest.mark.parametrize(
    ("flags", "acceptance", "dependency"),
    [
        (
            adapters.AdapterFlagsV1(True, grant_shadow=True),
            adapters.AcceptedComponentsV1(),
            {"grant_store": FakeGrantStore(), "materializer": action},
        ),
        (
            adapters.AdapterFlagsV1(True, nexus_projection=True),
            adapters.AcceptedComponentsV1(),
            {"nexus": local_nexus()},
        ),
        (
            adapters.AdapterFlagsV1(True, approval_inbox=True),
            adapters.AcceptedComponentsV1(),
            {"inbox": InboxHarness().projection},
        ),
    ],
)
def test_each_enabled_component_requires_exact_external_acceptance(
    flags: adapters.AdapterFlagsV1,
    acceptance: adapters.AcceptedComponentsV1,
    dependency: dict[str, object],
) -> None:
    with pytest.raises(
        adapters.Phase5ComponentAdapterV1ContractError, match="accepted"
    ):
        build(flags=flags, acceptance=acceptance, **dependency)


def test_grant_adapter_materializes_exact_request_and_maps_no_authority() -> None:
    store = FakeGrantStore()
    materialized: list[str] = []
    bundle = build(
        flags=adapters.AdapterFlagsV1(True, grant_shadow=True),
        acceptance=adapters.AcceptedComponentsV1(grants=adapters.GRANTS_ACCEPTANCE_V1),
        grant_store=store,
        materializer=lambda reference: materialized.append(reference) or action(),
    )
    assert bundle.grant is not None
    advisory = bundle.runtime_components.grant_evaluator("invoke-001")
    assert materialized == ["invoke-001"]
    assert store.references == ["invoke-001"]
    assert advisory == {
        "outcome": "would-allow",
        "reason": "exact-session-grant",
        "grant_id": "grant-001",
        "scope_digest": DIGEST,
        "action_digest": "b" * 64,
    }
    assert not hasattr(bundle.grant, "reserve")
    assert not hasattr(bundle.grant, "dispatch")


@pytest.mark.parametrize(
    "bad_action",
    [
        action(binding=dataclasses.replace(BINDING, profile_id="profile-other")),
        action(provider_free=False),
        action(operation="catalog_write"),
        action(cost_micro=1),
        action(action_classes=("send",)),
    ],
)
def test_grant_adapter_scope_and_action_drift_fail_before_r11(
    bad_action: runtime.ActionRequestV5,
) -> None:
    store = FakeGrantStore()
    bundle = build(
        flags=adapters.AdapterFlagsV1(True, grant_shadow=True),
        acceptance=adapters.AcceptedComponentsV1(grants=adapters.GRANTS_ACCEPTANCE_V1),
        grant_store=store,
        materializer=lambda _reference: bad_action,
    )
    with pytest.raises(adapters.Phase5ComponentAdapterV1ContractError):
        bundle.runtime_components.grant_evaluator("invoke-001")
    assert store.references == []


def test_grant_decision_authority_and_binding_attestation_fail_closed() -> None:
    bad = SimpleNamespace(
        outcome="would-allow",
        reason="exact-session-grant",
        grant_id="grant-001",
        scope_digest=DIGEST,
        action_audit_digest="b" * 64,
        callback_required=True,
        authority_granted=True,
    )
    bundle = build(
        flags=adapters.AdapterFlagsV1(True, grant_shadow=True),
        acceptance=adapters.AcceptedComponentsV1(grants=adapters.GRANTS_ACCEPTANCE_V1),
        grant_store=FakeGrantStore(bad),
        materializer=lambda _reference: action(),
    )
    with pytest.raises(
        adapters.Phase5ComponentAdapterV1ContractError, match="authority"
    ):
        bundle.runtime_components.grant_evaluator("invoke-001")

    drift = dataclasses.replace(BINDING, trace_id="trace-other")
    drifted = build(
        flags=adapters.AdapterFlagsV1(True, grant_shadow=True),
        acceptance=adapters.AcceptedComponentsV1(grants=adapters.GRANTS_ACCEPTANCE_V1),
        binding_attestor=lambda: drift,
        grant_store=FakeGrantStore(),
        materializer=lambda _reference: action(),
    )
    with pytest.raises(adapters.Phase5ComponentAdapterV1Error, match="mismatch"):
        drifted.runtime_components.grant_evaluator("invoke-001")


def test_grant_close_is_idempotent_and_routes_kill_or_end_session() -> None:
    killed = FakeGrantStore()
    bundle = build(
        flags=adapters.AdapterFlagsV1(True, grant_shadow=True),
        acceptance=adapters.AcceptedComponentsV1(grants=adapters.GRANTS_ACCEPTANCE_V1),
        grant_store=killed,
        materializer=lambda _reference: action(),
    )
    bundle.runtime_components.grant_terminator("kill")
    bundle.runtime_components.grant_terminator("kill")
    assert (killed.kills, killed.ends) == (1, 0)

    ended = FakeGrantStore()
    other = build(
        flags=adapters.AdapterFlagsV1(True, grant_shadow=True),
        acceptance=adapters.AcceptedComponentsV1(grants=adapters.GRANTS_ACCEPTANCE_V1),
        grant_store=ended,
        materializer=lambda _reference: action(),
    )
    other.runtime_components.grant_terminator("reconnect")
    other.runtime_components.grant_terminator("shutdown")
    assert (ended.kills, ended.ends) == (0, 1)


def test_concrete_r11_disabled_shadow_decision_maps_without_resolvers() -> None:
    gate = grants_v11.MonotonicFeatureGate(enabled=False)
    def fail(*_args, **_kwargs):
        raise AssertionError("called")
    services = grants_v11.HostServices(
        "desktop-root",
        gate,
        fail,
        fail,
        fail,
        fail,
        fail,
        fail,
        fail,
        fail,
    )
    store = grants_v11.SessionGrantShadowStore(services)
    bundle = build(
        flags=adapters.AdapterFlagsV1(True, grant_shadow=True),
        acceptance=adapters.AcceptedComponentsV1(grants=adapters.GRANTS_ACCEPTANCE_V1),
        grant_store=store,
        materializer=lambda _reference: action(),
    )
    advisory = bundle.runtime_components.grant_evaluator("invoke-001")
    assert advisory["outcome"] == "disabled"
    assert advisory["reason"] == "feature-flag-off"
    assert "grant_id" not in advisory


def test_concrete_v32_projects_only_exact_local_catalog_status() -> None:
    nexus = local_nexus()
    bundle = build(
        flags=adapters.AdapterFlagsV1(True, nexus_projection=True),
        acceptance=adapters.AcceptedComponentsV1(nexus=adapters.NEXUS_ACCEPTANCE_V1),
        nexus=nexus,
    )
    batch = bundle.runtime_components.nexus_projector(BINDING)
    assert batch.replace is True
    assert batch.next_cursor is None
    assert len(batch.source_cursor) == 64
    assert len(batch.items) == 1
    item = dict(batch.items[0])
    assert item == {
        "capability_id": "local.catalog",
        "display_name": "Local catalog metadata",
        "provider": "onyx_local",
        "version": "v32",
        "status": "disabled",
        "operations": ("catalog_read",),
        "limitation": (
            "metadata_allowlisted;read_only;provider_free;effect_none;egress_none;"
            "cost_micro_0;dispatch_unavailable"
        ),
    }
    assert not hasattr(bundle.nexus, "dispatch")


def test_nexus_absent_cross_scope_and_nonexact_descriptor_fail_closed() -> None:
    empty = nexus_v32.CapabilityNexusV32()
    bundle = build(
        flags=adapters.AdapterFlagsV1(True, nexus_projection=True),
        acceptance=adapters.AcceptedComponentsV1(nexus=adapters.NEXUS_ACCEPTANCE_V1),
        nexus=empty,
    )
    with pytest.raises(adapters.Phase5ComponentAdapterV1Error, match="absent"):
        bundle.runtime_components.nexus_projector(BINDING)
    with pytest.raises(adapters.Phase5ComponentAdapterV1ContractError, match="binding"):
        bundle.runtime_components.nexus_projector(
            dataclasses.replace(BINDING, account_id="account-other")
        )

    wrong = local_nexus(credential_alias="alias:catalog/account")
    rejected = build(
        flags=adapters.AdapterFlagsV1(True, nexus_projection=True),
        acceptance=adapters.AcceptedComponentsV1(nexus=adapters.NEXUS_ACCEPTANCE_V1),
        nexus=wrong,
    )
    with pytest.raises(
        adapters.Phase5ComponentAdapterV1ContractError, match="read-only"
    ):
        rejected.runtime_components.nexus_projector(BINDING)


def test_concrete_v15_pagination_uses_short_one_shot_runtime_cursors() -> None:
    harness = InboxHarness(3)
    bundle = build(
        flags=adapters.AdapterFlagsV1(True, approval_inbox=True),
        acceptance=adapters.AcceptedComponentsV1(inbox=adapters.INBOX_ACCEPTANCE_V1),
        inbox=harness.projection,
    )
    reader = bundle.runtime_components.inbox_factory(BINDING)
    first = reader.read_page(binding=BINDING, page_size=2, cursor=None)
    assert first.replace is True
    assert first.source_cursor is None
    assert first.next_cursor is not None
    assert len(first.next_cursor) < 128
    assert len(first.items) == 2
    assert set(first.items[0]) == {
        "item_id",
        "request_ref",
        "capability",
        "operation",
        "risk",
        "state",
        "summary",
        "created_at",
    }
    assert first.items[0]["state"] == "pending"

    second = reader.read_page(binding=BINDING, page_size=2, cursor=first.next_cursor)
    assert second.replace is False
    assert second.source_cursor == first.next_cursor
    assert second.next_cursor is None
    assert len(second.items) == 1
    with pytest.raises(adapters.Phase5ComponentAdapterV1Error, match="unavailable"):
        reader.read_page(binding=BINDING, page_size=2, cursor=first.next_cursor)


def test_inbox_bounds_scope_unhealthy_and_lifecycle_fail_closed() -> None:
    harness = InboxHarness(1)
    bundle = build(
        flags=adapters.AdapterFlagsV1(True, approval_inbox=True),
        acceptance=adapters.AcceptedComponentsV1(inbox=adapters.INBOX_ACCEPTANCE_V1),
        inbox=harness.projection,
    )
    with pytest.raises(adapters.Phase5ComponentAdapterV1ContractError):
        bundle.runtime_components.inbox_factory(
            dataclasses.replace(BINDING, session_id="session-other")
        )
    reader = bundle.runtime_components.inbox_factory(BINDING)
    with pytest.raises(adapters.Phase5ComponentAdapterV1ContractError):
        reader.read_page(binding=BINDING, page_size=51, cursor=None)
    harness.epoch += 1
    with pytest.raises(adapters.Phase5ComponentAdapterV1Error, match="read failed"):
        reader.read_page(binding=BINDING, page_size=1, cursor=None)
    bundle.runtime_components.inbox_terminator("revoke")
    bundle.runtime_components.inbox_terminator("revoke")
    with pytest.raises(adapters.Phase5ComponentAdapterV1Error, match="closed"):
        bundle.runtime_components.inbox_factory(BINDING)


def test_all_components_integrate_with_runtime_v5_without_granting_dispatch() -> None:
    bundle = build(
        grant_store=FakeGrantStore(),
        materializer=lambda reference: action(invocation_ref=reference),
        nexus=local_nexus(),
        inbox=InboxHarness(2).projection,
    )
    core = runtime.Phase5RuntimeV5(
        binding=BINDING,
        flags=runtime.RuntimeFlagsV5(
            runtime=True,
            grant_shadow=True,
            approval_inbox=True,
            low_risk=True,
            nexus_projection=True,
            local_catalog_read=True,
        ),
        components=bundle.runtime_components,
    )
    for component in ("grant_shadow", "nexus", "inbox"):
        core.recover_component(component)
    assert core.status().state is runtime.RuntimeStateV5.READY
    assert core.refresh_capabilities().total == 1
    assert core.refresh_inbox(page_size=2).total == 2
    decision = core.evaluate(action())
    assert decision.disposition is runtime.RuntimeDispositionV5.ALLOW_LOCAL_CATALOG_READ
    assert core.decision_is_current(decision, action()) is True
    assert core.consume_decision(decision, action()) is True
    assert core.consume_decision(decision, action()) is False


def test_no_live_surface_imports_component_adapters_or_accepted_candidates() -> None:
    forbidden = (
        "phase5_component_adapters_v1",
        "session_grants_v11",
        "capability_nexus_v32",
        "approval_inbox_v15",
    )
    for relative in (
        "main.py",
        "ui.py",
        "dashboard/server.py",
        "core/permission_broker.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert all(name not in source for name in forbidden), relative


def test_projection_path_has_no_polling_threads_or_remote_mutation_surface() -> None:
    source = (ROOT / "core/phase5_component_adapters_v1.py").read_text(encoding="utf-8")
    assert "threading.Thread" not in source
    assert "sleep(" not in source
    assert "requests." not in source
    assert "httpx." not in source
    for name in ("approve", "deny", "dispatch", "execute", "mutate"):
        assert not hasattr(adapters.ApprovalInboxAdapterV1, name)
        assert not hasattr(adapters.CapabilityNexusAdapterV1, name)


def test_nexus_projection_p95_is_below_runtime_budget() -> None:
    bundle = build(
        flags=adapters.AdapterFlagsV1(True, nexus_projection=True),
        acceptance=adapters.AcceptedComponentsV1(nexus=adapters.NEXUS_ACCEPTANCE_V1),
        nexus=local_nexus(),
    )
    samples: list[float] = []
    for _ in range(200):
        started = time.perf_counter_ns()
        bundle.runtime_components.nexus_projector(BINDING)
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    samples.sort()
    p95 = samples[int(len(samples) * 0.95) - 1]
    assert p95 < 25.0
