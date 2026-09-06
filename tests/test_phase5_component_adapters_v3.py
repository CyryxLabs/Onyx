from __future__ import annotations

import dataclasses
import hashlib
import threading
import time
from pathlib import Path

import pytest

from core import approval_inbox_v15 as inbox_v15
from core import capability_nexus_v32 as nexus_v32
from core import phase5_component_adapters_v3 as adapters
from core import phase5_runtime_v5 as runtime
from core import session_grants_v11 as grants_v11


ROOT = Path(__file__).resolve().parents[1]
BINDING = runtime.RuntimeBindingV5(
    "trace-001", "session-local", "workspace-main", "account-local", "profile-main"
)


def host_item(number: int, **changes: object) -> inbox_v15.HostInboxItemV15:
    values: dict[str, object] = {
        "item_id": f"item-{number:03d}",
        "action_request_id": f"request-{number:03d}",
        "principal_id": "owner-primary",
        "session_id": BINDING.session_id,
        "workspace_id": BINDING.workspace_id,
        "workspace_display": "Cyryx Main",
        "mission_id": "mission-daily",
        "mission_display": "Daily operations",
        "account_id": BINDING.account_id,
        "account_display": "Local workspace account",
        "connector_id": "calendar-local",
        "connector_version": "1.0",
        "tool_id": "calendar-tool",
        "operation": "create-draft",
        "environment": "local-draft",
        "reason": f"Prepare reviewed item {number}",
        "target_display": f"Calendar draft {number}",
        "target_digest": f"{number + 10:064x}",
        "payload_summary": f"Create reversible draft {number}",
        "payload_digest": f"{number + 100:064x}",
        "attachment_set_digest": "3" * 64,
        "policy_version": "onyx-policy-1",
        "action_schema_version": "action-1",
        "data_class": "internal",
        "egress": "local-only",
        "effect_summary": "Creates a draft only",
        "reversibility": "reversible",
        "idempotency_summary": f"One draft for request {number}",
        "idempotency_key": f"{number + 200:064x}",
        "verification_plan": "Read the draft back and compare its digest",
        "rollback_plan": "Delete local draft before external action",
        "cost_micro": number,
        "currency": "USD",
        "risk": "low",
        "created_at_ms": 1_700_000_000_000 + number,
        "expires_at_ms": 1_700_000_100_000 + number,
        "always_explicit": False,
        "batch_eligible": True,
    }
    values.update(changes)
    return inbox_v15.HostInboxItemV15(**values)


class EpochReader:
    def __init__(self) -> None:
        self.value = 7

    def __call__(self) -> int:
        return self.value


class HostCapture:
    def __init__(self, count: int = 3) -> None:
        self.source_epoch = 1
        self.items = tuple(host_item(index) for index in range(1, count + 1))
        self.entered: threading.Event | None = None
        self.release: threading.Event | None = None

    def __call__(self) -> inbox_v15.HostInboxSnapshotV15:
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            assert self.release.wait(5)
        return inbox_v15.HostInboxSnapshotV15(
            self.source_epoch, 55_000, self.items
        )


class GrantMaterializer:
    def __call__(self, reference: str) -> runtime.ActionRequestV5:
        return runtime.ActionRequestV5(
            invocation_ref=reference,
            binding=BINDING,
            capability="local.catalog",
            operation="catalog_read",
            provider_free=True,
            read_only=True,
            effect="none",
            egress="none",
            metadata_allowlisted=True,
            cost_micro=0,
            risk="low",
            reversible=True,
        )


def grant_store() -> grants_v11.SessionGrantShadowStore:
    gate = grants_v11.MonotonicFeatureGate(enabled=False)

    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("unexpected host authority call")

    services = grants_v11.HostServices(
        "desktop-root", gate, fail, fail, fail, fail, fail, fail, fail, fail
    )
    return grants_v11.SessionGrantShadowStore(services)


def local_nexus() -> nexus_v32.CapabilityNexusV32:
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
    descriptor = nexus_v32.CapabilityDescriptorV32(
        capability_id="local.catalog",
        capability_version="v32",
        provider="onyx_local",
        transport=nexus_v32.TransportKindV32.LOCAL,
        api_name="local_catalog",
        api_version=nexus_v32.CATALOG_CONTRACT_VERSION_V32,
        workspace_id=BINDING.workspace_id,
        account_id=BINDING.account_id,
        profile_id=BINDING.profile_id,
        credential_alias=None,
        operations=(operation,),
        status=nexus_v32.CapabilityStatusV32.DISABLED,
        status_reason="candidate_not_activated",
        limitations=("metadata_only", "no_dispatch"),
    )
    value = nexus_v32.CapabilityNexusV32()
    value.register(descriptor)
    return value


@dataclasses.dataclass
class Fixture:
    authority: adapters.HostAttestationAuthorityV3
    capture: HostCapture
    epoch: EpochReader
    binding: runtime.RuntimeBindingV5 = BINDING

    @classmethod
    def create(cls, count: int = 3) -> "Fixture":
        return cls(
            adapters.HostAttestationAuthorityV3(b"k" * 32),
            HostCapture(count),
            EpochReader(),
        )

    def attestations(self) -> dict[str, adapters.ComponentAttestationV3]:
        return {
            role: self.authority.issue_component(value, role=role, generation=0)
            for role, value in {
                "batch_factory": runtime.ProjectionBatchV5,
                "components_factory": runtime.RuntimeComponentsV5,
            }.items()
        }

    def build(
        self,
        *,
        binding: object | None = None,
        binding_attestor=None,
        capture: HostCapture | None = None,
        attestations: dict[str, adapters.ComponentAttestationV3] | None = None,
    ) -> adapters.ComponentAdapterBundleV3:
        selected = self.binding if binding is None else binding
        return adapters.build_component_adapters_v3(
            flags=adapters.AdapterFlagsV3(True, approval_inbox=True),
            acceptance=adapters.AcceptedComponentsV3(
                inbox=adapters.INBOX_ACCEPTANCE_V3
            ),
            binding=selected,
            binding_attestor=binding_attestor or (lambda: selected),
            authority=self.authority,
            attestations=self.attestations() if attestations is None else attestations,
            batch_factory=runtime.ProjectionBatchV5,
            components_factory=runtime.RuntimeComponentsV5,
            inbox_construction=adapters.InboxConstructionInputsV3(
                "owner-primary",
                capture or self.capture,
                self.epoch,
                inbox_v15.DeterministicInboxClockV15(1_000),
            ),
        )


def test_v1_and_v2_bytes_are_preserved() -> None:
    expected = {
        "core/phase5_component_adapters_v1.py": "e1b916b07c563ec8de136a21dee711ad5ad0d8c1a6dc6e40c5129ed9b8e91f48",
        "core/phase5_component_adapters_v2.py": "0bb3244a72162728e3e10770dc75e8cbab08ff80712045a95f68db5c2c4e7e7f",
        "tests/test_phase5_component_adapters_v1.py": "04fe571426d14e5660186ae7f0788d1e1ed91f989093b73f126aa42755019757",
        "tests/test_phase5_component_adapters_v2.py": "087afd82ab892c9446700b1533a0e2cab562f3277c1ebeb608cf6692d76441aa",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest


def test_default_off_has_no_construction_or_attestation_side_effect() -> None:
    fixture = Fixture.create()
    bundle = adapters.build_component_adapters_v3(
        flags=adapters.AdapterFlagsV3(),
        acceptance=adapters.AcceptedComponentsV3(),
        binding=BINDING,
        binding_attestor=lambda: (_ for _ in ()).throw(AssertionError("called")),
        authority=fixture.authority,
        attestations={},
        batch_factory=runtime.ProjectionBatchV5,
        components_factory=runtime.RuntimeComponentsV5,
    )
    assert bundle.runtime_components == runtime.RuntimeComponentsV5()
    assert bundle.inbox is None
    assert fixture.authority.active_inbox_state_size == 0


def test_real_v15_is_constructed_and_receipt_covers_exact_5d_scope() -> None:
    fixture = Fixture.create()
    bundle = fixture.build()
    assert bundle.inbox is not None
    adapter = bundle.inbox
    assert type(adapter._projection) is inbox_v15.ApprovalInboxProjectionV15
    assert type(adapter._source) is inbox_v15.HostInboxSourceV15
    assert adapter._projection._source is adapter._source
    receipt = adapter._construction_receipt
    assert tuple(getattr(receipt, name) for name in BINDING.__dataclass_fields__) == (
        BINDING.trace_id,
        BINDING.session_id,
        BINDING.workspace_id,
        BINDING.account_id,
        BINDING.profile_id,
    )
    reader = bundle.runtime_components.inbox_factory(BINDING)
    first = reader.read_page(binding=BINDING, page_size=2, cursor=None)
    assert len(first.items) == 2 and first.next_cursor is not None
    second = reader.read_page(
        binding=BINDING, page_size=2, cursor=first.next_cursor
    )
    assert len(second.items) == 1 and second.next_cursor is None
    assert fixture.authority.active_inbox_state_size == 1


def test_all_accepted_components_keep_strict_attestation_and_project() -> None:
    fixture = Fixture.create(1)
    store = grant_store()
    materializer = GrantMaterializer()
    nexus = local_nexus()
    values: dict[str, object] = {
        "batch_factory": runtime.ProjectionBatchV5,
        "components_factory": runtime.RuntimeComponentsV5,
        "grant_store": store,
        "grant_materializer": materializer,
        "action_request_type": runtime.ActionRequestV5,
        "nexus": nexus,
    }
    attestations = {
        role: fixture.authority.issue_component(value, role=role, generation=0)
        for role, value in values.items()
    }
    bundle = adapters.build_component_adapters_v3(
        flags=adapters.AdapterFlagsV3(True, True, True, True),
        acceptance=adapters.AcceptedComponentsV3(
            adapters.GRANTS_ACCEPTANCE_V3,
            adapters.NEXUS_ACCEPTANCE_V3,
            adapters.INBOX_ACCEPTANCE_V3,
        ),
        binding=BINDING,
        binding_attestor=lambda: BINDING,
        authority=fixture.authority,
        attestations=attestations,
        batch_factory=runtime.ProjectionBatchV5,
        components_factory=runtime.RuntimeComponentsV5,
        action_request_type=runtime.ActionRequestV5,
        grant_store=store,
        materialize_grant_request=materializer,
        nexus=nexus,
        inbox_construction=adapters.InboxConstructionInputsV3(
            "owner-primary",
            fixture.capture,
            fixture.epoch,
            inbox_v15.DeterministicInboxClockV15(1_000),
        ),
    )
    assert bundle.runtime_components.grant_evaluator("invoke-001")["outcome"] == "disabled"
    capabilities = bundle.runtime_components.nexus_projector(BINDING)
    assert len(capabilities.items) == 1
    assert capabilities.items[0]["capability_id"] == "local.catalog"
    page = bundle.runtime_components.inbox_factory(BINDING).read_page(
        binding=BINDING, page_size=1, cursor=None
    )
    assert len(page.items) == 1


@pytest.mark.parametrize("name", ["trace_id", "session_id", "account_id", "profile_id"])
def test_same_workspace_cross_dimension_runtime_binding_fails(name: str) -> None:
    fixture = Fixture.create()
    bundle = fixture.build()
    wrong = dataclasses.replace(BINDING, **{name: f"{name}-other"})
    with pytest.raises(adapters.Phase5ComponentAdapterV3ContractError, match="binding"):
        bundle.runtime_components.inbox_factory(wrong)


@pytest.mark.parametrize("name", ["session_id", "workspace_id", "account_id"])
def test_actual_snapshot_scope_is_derived_and_mismatch_fails(name: str) -> None:
    fixture = Fixture.create(1)
    fixture.capture.items = (
        host_item(1, **{name: f"{name}-other"}),
    )
    bundle = fixture.build()
    reader = bundle.runtime_components.inbox_factory(BINDING)
    with pytest.raises(adapters.Phase5ComponentAdapterV3Error, match="read failed"):
        reader.read_page(binding=BINDING, page_size=1, cursor=None)


def test_forged_construction_receipt_fails_before_read() -> None:
    fixture = Fixture.create(1)
    bundle = fixture.build()
    assert bundle.inbox is not None
    bundle.inbox._construction_receipt = dataclasses.replace(
        bundle.inbox._construction_receipt, profile_id="profile-forged"
    )
    with pytest.raises(adapters.Phase5ComponentAdapterV3Error, match="construction"):
        bundle.runtime_components.inbox_factory(BINDING)


def test_instance_swap_fails_exact_construction_identity() -> None:
    first = Fixture.create(1)
    second = Fixture.create(1)
    one = first.build()
    two = second.build()
    assert one.inbox is not None and two.inbox is not None
    one.inbox._projection = two.inbox._projection
    with pytest.raises(adapters.Phase5ComponentAdapterV3Error):
        one.runtime_components.inbox_factory(BINDING)


def test_forged_snapshot_scope_receipt_fails_on_continuation() -> None:
    fixture = Fixture.create(2)
    bundle = fixture.build()
    assert bundle.inbox is not None
    reader = bundle.runtime_components.inbox_factory(BINDING)
    first = reader.read_page(binding=BINDING, page_size=1, cursor=None)
    assert first.next_cursor is not None
    record = bundle.inbox._cursors[first.next_cursor]
    bundle.inbox._cursors[first.next_cursor] = dataclasses.replace(
        record,
        scope_receipt=dataclasses.replace(record.scope_receipt, mac="0" * 64),
    )
    with pytest.raises(adapters.Phase5ComponentAdapterV3Error, match="scope"):
        reader.read_page(
            binding=BINDING, page_size=1, cursor=first.next_cursor
        )


def test_page_envelope_replay_is_rejected_by_monotonic_window() -> None:
    fixture = Fixture.create(1)
    bundle = fixture.build()
    assert bundle.inbox is not None
    adapter = bundle.inbox
    construction_digest = adapters._receipt_digest(adapter._construction_receipt)
    projection_identity = adapters._instance_identity(adapter._projection)
    source_identity = adapters._instance_identity(adapter._source)
    request_digest = "1" * 64
    envelope = fixture.authority.issue_page_envelope(
        phase="pre",
        binding=adapters.AdapterBindingV3.from_runtime(BINDING),
        projection_identity=projection_identity,
        source_identity=source_identity,
        construction_digest=construction_digest,
        snapshot_scope_receipt_digest=None,
        journey=1,
        sequence=0,
        generation=0,
        request_digest=request_digest,
        page_digest=None,
    )
    kwargs = dict(
        binding=adapters.AdapterBindingV3.from_runtime(BINDING),
        projection_identity=projection_identity,
        source_identity=source_identity,
        construction_digest=construction_digest,
        snapshot_scope_receipt_digest=None,
        journey=1,
        sequence=0,
        generation=0,
        request_digest=request_digest,
        page_digest=None,
        journey_complete=False,
    )
    fixture.authority.verify_page_envelope(envelope, **kwargs)
    with pytest.raises(adapters.Phase5ComponentAdapterV3Error, match="replay"):
        fixture.authority.verify_page_envelope(envelope, **kwargs)


def test_over_10k_terminal_pages_do_not_exhaust_or_grow_state() -> None:
    fixture = Fixture.create(1)
    bundle = fixture.build()
    assert bundle.inbox is not None
    reader = bundle.runtime_components.inbox_factory(BINDING)
    for _ in range(10_001):
        page = reader.read_page(binding=BINDING, page_size=1, cursor=None)
        assert page.next_cursor is None
    assert fixture.authority.active_inbox_state_size == 1
    assert not bundle.inbox._cursors
    assert len(bundle.inbox._projection._snapshots) <= inbox_v15.MAX_SNAPSHOTS
    assert len(bundle.inbox._projection._views) <= inbox_v15.MAX_VIEWS


def test_close_reclaims_owner_and_blocks_late_publication() -> None:
    fixture = Fixture.create(1)
    fixture.capture.entered = threading.Event()
    fixture.capture.release = threading.Event()
    bundle = fixture.build()
    reader = bundle.runtime_components.inbox_factory(BINDING)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            reader.read_page(binding=BINDING, page_size=1, cursor=None)
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    assert fixture.capture.entered.wait(5)
    bundle.runtime_components.inbox_terminator("shutdown")
    fixture.capture.release.set()
    worker.join(5)
    assert not worker.is_alive()
    assert len(errors) == 1
    assert fixture.authority.active_inbox_state_size == 0
    with pytest.raises(adapters.Phase5ComponentAdapterV3Error, match="closed"):
        reader.read_page(binding=BINDING, page_size=1, cursor=None)


def test_arbitrary_projection_and_old_signer_contract_are_not_accepted() -> None:
    fixture = Fixture.create()
    attestations = fixture.attestations()
    attestations["inbox"] = fixture.authority.issue_component(
        inbox_v15.ApprovalInboxProjectionV15,
        role="inbox",
        generation=0,
    )
    with pytest.raises(
        adapters.Phase5ComponentAdapterV3ContractError,
        match="caller-supplied inbox",
    ):
        adapters.build_component_adapters_v3(
            flags=adapters.AdapterFlagsV3(True, approval_inbox=True),
            acceptance=adapters.AcceptedComponentsV3(
                inbox=adapters.INBOX_ACCEPTANCE_V3
            ),
            binding=BINDING,
            binding_attestor=lambda: BINDING,
            authority=fixture.authority,
            attestations=attestations,
            batch_factory=runtime.ProjectionBatchV5,
            components_factory=runtime.RuntimeComponentsV5,
            inbox_construction=adapters.InboxConstructionInputsV3(
                "owner-primary",
                fixture.capture,
                fixture.epoch,
                inbox_v15.DeterministicInboxClockV15(1_000),
            ),
        )


def test_failed_runtime_components_factory_reclaims_constructed_owner() -> None:
    fixture = Fixture.create()

    def rejecting_components_factory(**_components: object) -> object:
        raise RuntimeError("reject")

    attestations = fixture.attestations()
    attestations["components_factory"] = fixture.authority.issue_component(
        rejecting_components_factory, role="components_factory", generation=0
    )
    with pytest.raises(RuntimeError, match="reject"):
        adapters.build_component_adapters_v3(
            flags=adapters.AdapterFlagsV3(True, approval_inbox=True),
            acceptance=adapters.AcceptedComponentsV3(
                inbox=adapters.INBOX_ACCEPTANCE_V3
            ),
            binding=BINDING,
            binding_attestor=lambda: BINDING,
            authority=fixture.authority,
            attestations=attestations,
            batch_factory=runtime.ProjectionBatchV5,
            components_factory=rejecting_components_factory,
            inbox_construction=adapters.InboxConstructionInputsV3(
                "owner-primary",
                fixture.capture,
                fixture.epoch,
                inbox_v15.DeterministicInboxClockV15(1_000),
            ),
        )
    assert fixture.authority.active_inbox_state_size == 0


def test_page_projection_p95_under_25ms() -> None:
    fixture = Fixture.create(1)
    bundle = fixture.build()
    reader = bundle.runtime_components.inbox_factory(BINDING)
    samples: list[float] = []
    for _ in range(100):
        started = time.perf_counter_ns()
        reader.read_page(binding=BINDING, page_size=1, cursor=None)
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    samples.sort()
    assert samples[94] < 25.0


def test_no_live_wiring_polling_threads_or_authority_methods() -> None:
    forbidden = (
        "phase5_component_adapters_v3",
        "InboxConstructionInputsV3",
    )
    for relative in ("main.py", "ui.py", "dashboard/server.py", "core/permission_broker.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert all(name not in source for name in forbidden), relative
    source = (ROOT / "core/phase5_component_adapters_v3.py").read_text(
        encoding="utf-8"
    )
    assert "threading.Thread" not in source
    assert "sleep(" not in source
    for name in ("approve", "deny", "dispatch", "execute", "grant"):
        assert not hasattr(adapters.ApprovalInboxAdapterV3, name)
