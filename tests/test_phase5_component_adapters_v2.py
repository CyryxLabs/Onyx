from __future__ import annotations

import dataclasses
import hashlib
import threading
import time
from pathlib import Path

import pytest

from core import approval_inbox_v15 as inbox_v15
from core import capability_nexus_v32 as nexus_v32
from core import phase5_component_adapters_v2 as adapters
from core import phase5_runtime_v5 as runtime
from core import session_grants_v11 as grants_v11


ROOT = Path(__file__).resolve().parents[1]
BINDING = runtime.RuntimeBindingV5(
    "trace-001", "session-local", "workspace-main", "account-local", "profile-main"
)
FLAGS = adapters.AdapterFlagsV2(True, True, True, True)
ACCEPTED = adapters.AcceptedComponentsV2(
    adapters.GRANTS_ACCEPTANCE_V2,
    adapters.NEXUS_ACCEPTANCE_V2,
    adapters.INBOX_ACCEPTANCE_V2,
)


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


class Materializer:
    def __init__(self) -> None:
        self.changes: dict[str, object] = {}
        self.entered: threading.Event | None = None
        self.release: threading.Event | None = None

    def __call__(self, reference: str) -> runtime.ActionRequestV5:
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            assert self.release.wait(5)
        return action(invocation_ref=reference, **self.changes)


class ProjectionSigner:
    def __init__(self, authority: adapters.HostAttestationAuthorityV2) -> None:
        self.authority = authority
        self.mutate = None

    def __call__(self, **payload: object) -> adapters.ProjectionAttestationV2:
        if self.mutate is not None:
            payload = self.mutate(dict(payload))
        return self.authority.issue_projection(**payload)  # type: ignore[arg-type]


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


def local_nexus(**changes: object) -> nexus_v32.CapabilityNexusV32:
    value = nexus_v32.CapabilityNexusV32()
    value.register(local_descriptor(**changes))
    return value


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


class InboxHarness:
    def __init__(self, count: int = 3, capture_hook=None) -> None:
        self.epoch = 7
        self.source_epoch = 1
        self.items = tuple(host_item(index) for index in range(1, count + 1))

        def capture() -> inbox_v15.HostInboxSnapshotV15:
            if capture_hook is not None:
                capture_hook()
            return inbox_v15.HostInboxSnapshotV15(
                self.source_epoch, 55_000, self.items
            )

        gate = inbox_v15.ApprovalInboxFeatureGateV15(
            environ={inbox_v15.APPROVAL_INBOX_V15_FLAG: "true"},
            epoch_reader=lambda: self.epoch,
        )
        source = inbox_v15.HostInboxSourceV15(
            principal_id="owner-primary",
            session_id=BINDING.session_id,
            capture_callback=capture,
        )
        self.projection = inbox_v15.ApprovalInboxProjectionV15(
            gate=gate,
            source=source,
            clock=inbox_v15.DeterministicInboxClockV15(1_000),
        )


def grant_store() -> grants_v11.SessionGrantShadowStore:
    gate = grants_v11.MonotonicFeatureGate(enabled=False)

    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("called")

    services = grants_v11.HostServices(
        "desktop-root", gate, fail, fail, fail, fail, fail, fail, fail, fail
    )
    return grants_v11.SessionGrantShadowStore(services)


@dataclasses.dataclass
class Fixture:
    authority: adapters.HostAttestationAuthorityV2
    materializer: Materializer
    store: grants_v11.SessionGrantShadowStore
    nexus: nexus_v32.CapabilityNexusV32
    inbox: InboxHarness
    signer: ProjectionSigner

    @classmethod
    def create(cls, *, inbox: InboxHarness | None = None) -> "Fixture":
        authority = adapters.HostAttestationAuthorityV2(b"k" * 32)
        return cls(
            authority,
            Materializer(),
            grant_store(),
            local_nexus(),
            inbox or InboxHarness(),
            ProjectionSigner(authority),
        )

    def attestations(self) -> dict[str, adapters.ComponentAttestationV2]:
        values = {
            "batch_factory": runtime.ProjectionBatchV5,
            "components_factory": runtime.RuntimeComponentsV5,
            "grant_store": self.store,
            "grant_materializer": self.materializer,
            "action_request_type": runtime.ActionRequestV5,
            "nexus": self.nexus,
            "inbox": self.inbox.projection,
            "inbox_projection_attestor": self.signer,
        }
        return {
            role: self.authority.issue_component(
                value,
                role=role,
                generation=0,
                binding=(
                    adapters.AdapterBindingV2.from_runtime(BINDING)
                    if role == "inbox_projection_attestor"
                    else None
                ),
            )
            for role, value in values.items()
        }

    def build(
        self,
        *,
        flags: adapters.AdapterFlagsV2 = FLAGS,
        acceptance: adapters.AcceptedComponentsV2 = ACCEPTED,
        binding: object = BINDING,
        binding_attestor=None,
        attestations: dict[str, adapters.ComponentAttestationV2] | None = None,
    ) -> adapters.ComponentAdapterBundleV2:
        return adapters.build_component_adapters_v2(
            flags=flags,
            acceptance=acceptance,
            binding=binding,
            binding_attestor=binding_attestor or (lambda: BINDING),
            authority=self.authority,
            attestations=self.attestations() if attestations is None else attestations,
            batch_factory=runtime.ProjectionBatchV5,
            components_factory=runtime.RuntimeComponentsV5,
            action_request_type=runtime.ActionRequestV5,
            grant_store=self.store if flags.grant_shadow else None,
            materialize_grant_request=(
                self.materializer if flags.grant_shadow else None
            ),
            nexus=self.nexus if flags.nexus_projection else None,
            inbox_projection=(
                self.inbox.projection if flags.approval_inbox else None
            ),
            inbox_projection_attestor=(
                self.signer if flags.approval_inbox else None
            ),
        )


def test_v1_bytes_are_preserved() -> None:
    assert hashlib.sha256(
        (ROOT / "core/phase5_component_adapters_v1.py").read_bytes()
    ).hexdigest() == "e1b916b07c563ec8de136a21dee711ad5ad0d8c1a6dc6e40c5129ed9b8e91f48"
    assert hashlib.sha256(
        (ROOT / "tests/test_phase5_component_adapters_v1.py").read_bytes()
    ).hexdigest() == "04fe571426d14e5660186ae7f0788d1e1ed91f989093b73f126aa42755019757"


def test_default_off_has_no_components_or_attestations() -> None:
    fixture = Fixture.create()
    bundle = adapters.build_component_adapters_v2(
        flags=adapters.AdapterFlagsV2(),
        acceptance=adapters.AcceptedComponentsV2(),
        binding=BINDING,
        binding_attestor=lambda: (_ for _ in ()).throw(AssertionError("called")),
        authority=fixture.authority,
        attestations={},
        batch_factory=runtime.ProjectionBatchV5,
        components_factory=runtime.RuntimeComponentsV5,
    )
    assert bundle.runtime_components == runtime.RuntimeComponentsV5()
    assert bundle.grant is bundle.nexus is bundle.inbox is None


def test_all_concrete_accepted_components_are_attested_and_project() -> None:
    fixture = Fixture.create()
    bundle = fixture.build()
    assert bundle.runtime_components.grant_evaluator("invoke-001")["outcome"] == "disabled"
    capabilities = bundle.runtime_components.nexus_projector(BINDING)
    assert len(capabilities.items) == 1
    assert capabilities.items[0]["capability_id"] == "local.catalog"
    reader = bundle.runtime_components.inbox_factory(BINDING)
    first = reader.read_page(binding=BINDING, page_size=2, cursor=None)
    assert len(first.items) == 2 and first.next_cursor is not None
    second = reader.read_page(
        binding=BINDING, page_size=2, cursor=first.next_cursor
    )
    assert len(second.items) == 1 and second.next_cursor is None


@pytest.mark.parametrize("role", ["grant_store", "nexus", "inbox"])
def test_wrong_type_module_path_hash_instance_or_root_is_rejected(role: str) -> None:
    fixture = Fixture.create()
    attestations = fixture.attestations()
    original = attestations[role]
    for changed in (
        dataclasses.replace(original, module_name="core.forged"),
        dataclasses.replace(original, canonical_module_path=str(ROOT / "main.py")),
        dataclasses.replace(original, source_sha256="0" * 64),
        dataclasses.replace(original, instance_identity="1" * 64),
        dataclasses.replace(original, accepted_root="2" * 64),
    ):
        forged = dict(attestations)
        forged[role] = changed
        with pytest.raises(adapters.Phase5ComponentAdapterV2Error, match="attestation"):
            fixture.build(attestations=forged)


def test_component_swap_after_build_fails_closed() -> None:
    fixture = Fixture.create()
    bundle = fixture.build(
        flags=adapters.AdapterFlagsV2(True, nexus_projection=True),
        acceptance=adapters.AcceptedComponentsV2(nexus=adapters.NEXUS_ACCEPTANCE_V2),
    )
    assert bundle.nexus is not None
    object.__setattr__(bundle.nexus, "_nexus", local_nexus())
    with pytest.raises(adapters.Phase5ComponentAdapterV2Error, match="attestation"):
        bundle.runtime_components.nexus_projector(BINDING)

    fixture = Fixture.create()
    grant = fixture.build(
        flags=adapters.AdapterFlagsV2(True, grant_shadow=True),
        acceptance=adapters.AcceptedComponentsV2(
            grants=adapters.GRANTS_ACCEPTANCE_V2
        ),
    )
    fixture.store.evaluate = lambda _reference: None  # type: ignore[method-assign]
    with pytest.raises(adapters.Phase5ComponentAdapterV2Error, match="attestation"):
        grant.runtime_components.grant_evaluator("invoke-001")


def test_missing_component_attestation_fails_closed() -> None:
    fixture = Fixture.create()
    attestations = fixture.attestations()
    attestations.pop("inbox_projection_attestor")
    with pytest.raises(adapters.Phase5ComponentAdapterV2ContractError):
        fixture.build(
            flags=adapters.AdapterFlagsV2(True, approval_inbox=True),
            acceptance=adapters.AcceptedComponentsV2(
                inbox=adapters.INBOX_ACCEPTANCE_V2
            ),
            attestations=attestations,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"provider_free": 1},
        {"read_only": 1},
        {"metadata_allowlisted": 1},
        {"cost_micro": True},
        {"capability": ""},
        {"operation": "catalog_write"},
        {"action_classes": ["send"]},
    ],
)
def test_materializer_rejects_truthy_coercions_and_nonexact_values(
    changes: dict[str, object],
) -> None:
    fixture = Fixture.create()
    fixture.materializer.changes = changes
    bundle = fixture.build(
        flags=adapters.AdapterFlagsV2(True, grant_shadow=True),
        acceptance=adapters.AcceptedComponentsV2(grants=adapters.GRANTS_ACCEPTANCE_V2),
    )
    with pytest.raises(
        (
            TypeError,
            ValueError,
            adapters.Phase5ComponentAdapterV2ContractError,
            adapters.Phase5ComponentAdapterV2Error,
        )
    ):
        bundle.runtime_components.grant_evaluator("invoke-001")


def test_missing_forged_stale_and_replayed_page_attestation_fail_closed() -> None:
    fixture = Fixture.create()
    bundle = fixture.build(
        flags=adapters.AdapterFlagsV2(True, approval_inbox=True),
        acceptance=adapters.AcceptedComponentsV2(inbox=adapters.INBOX_ACCEPTANCE_V2),
    )
    assert bundle.inbox is not None

    fixture.signer.mutate = lambda payload: {**payload, "generation": 99}
    with pytest.raises(adapters.Phase5ComponentAdapterV2Error, match="attestation"):
        bundle.runtime_components.inbox_factory(BINDING).read_page(
            binding=BINDING, page_size=1, cursor=None
        )

    fixture = Fixture.create()
    saved: list[adapters.ProjectionAttestationV2] = []

    class ReplaySigner(ProjectionSigner):
        def __call__(self, **payload: object) -> adapters.ProjectionAttestationV2:
            if saved:
                return saved[0]
            result = super().__call__(**payload)
            saved.append(result)
            return result

    fixture.signer = ReplaySigner(fixture.authority)
    bundle = fixture.build(
        flags=adapters.AdapterFlagsV2(True, approval_inbox=True),
        acceptance=adapters.AcceptedComponentsV2(inbox=adapters.INBOX_ACCEPTANCE_V2),
    )
    with pytest.raises(adapters.Phase5ComponentAdapterV2Error, match="attestation"):
        bundle.runtime_components.inbox_factory(BINDING).read_page(
            binding=BINDING, page_size=1, cursor=None
        )


def test_same_workspace_cross_session_account_profile_and_trace_are_rejected() -> None:
    fixture = Fixture.create()
    bundle = fixture.build(
        flags=adapters.AdapterFlagsV2(True, approval_inbox=True),
        acceptance=adapters.AcceptedComponentsV2(inbox=adapters.INBOX_ACCEPTANCE_V2),
    )
    for name in ("trace_id", "session_id", "account_id", "profile_id"):
        wrong = dataclasses.replace(BINDING, **{name: f"{name}-other"})
        with pytest.raises(adapters.Phase5ComponentAdapterV2ContractError, match="binding"):
            bundle.runtime_components.inbox_factory(wrong)

    attestations = fixture.attestations()
    wrong_binding = adapters.AdapterBindingV2.from_runtime(
        dataclasses.replace(BINDING, account_id="account-other")
    )
    attestations["inbox_projection_attestor"] = fixture.authority.issue_component(
        fixture.signer,
        role="inbox_projection_attestor",
        generation=0,
        binding=wrong_binding,
    )
    with pytest.raises(adapters.Phase5ComponentAdapterV2Error, match="attestation"):
        fixture.build(
            flags=adapters.AdapterFlagsV2(True, approval_inbox=True),
            acceptance=adapters.AcceptedComponentsV2(
                inbox=adapters.INBOX_ACCEPTANCE_V2
            ),
            attestations=attestations,
        )


def test_close_during_inbox_component_call_discards_late_result() -> None:
    entered = threading.Event()
    release = threading.Event()

    def block() -> None:
        entered.set()
        assert release.wait(5)

    fixture = Fixture.create(inbox=InboxHarness(1, capture_hook=block))
    bundle = fixture.build(
        flags=adapters.AdapterFlagsV2(True, approval_inbox=True),
        acceptance=adapters.AcceptedComponentsV2(inbox=adapters.INBOX_ACCEPTANCE_V2),
    )
    reader = bundle.runtime_components.inbox_factory(BINDING)
    errors: list[BaseException] = []

    def read() -> None:
        try:
            reader.read_page(binding=BINDING, page_size=1, cursor=None)
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=read)
    worker.start()
    assert entered.wait(5)
    bundle.runtime_components.inbox_terminator("revoke")
    release.set()
    worker.join(5)
    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], adapters.Phase5ComponentAdapterV2Error)
    assert "lifecycle" in str(errors[0]) or "attestation" in str(errors[0])


def test_close_during_grant_materialization_discards_late_result() -> None:
    fixture = Fixture.create()
    fixture.materializer.entered = threading.Event()
    fixture.materializer.release = threading.Event()
    bundle = fixture.build(
        flags=adapters.AdapterFlagsV2(True, grant_shadow=True),
        acceptance=adapters.AcceptedComponentsV2(
            grants=adapters.GRANTS_ACCEPTANCE_V2
        ),
    )
    errors: list[BaseException] = []

    def evaluate() -> None:
        try:
            bundle.runtime_components.grant_evaluator("invoke-001")
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=evaluate)
    worker.start()
    assert fixture.materializer.entered.wait(5)
    with pytest.raises(adapters.Phase5ComponentAdapterV2Error, match="local close"):
        bundle.runtime_components.grant_terminator("revoke")
    fixture.materializer.release.set()
    worker.join(5)
    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], adapters.Phase5ComponentAdapterV2Error)
    assert "lifecycle" in str(errors[0])


def test_close_during_nexus_snapshot_discards_late_result() -> None:
    fixture = Fixture.create()
    bundle = fixture.build(
        flags=adapters.AdapterFlagsV2(True, nexus_projection=True),
        acceptance=adapters.AcceptedComponentsV2(
            nexus=adapters.NEXUS_ACCEPTANCE_V2
        ),
    )
    errors: list[BaseException] = []

    def project() -> None:
        try:
            bundle.runtime_components.nexus_projector(BINDING)
        except BaseException as exc:
            errors.append(exc)

    with fixture.nexus._lock:
        worker = threading.Thread(target=project)
        worker.start()
        time.sleep(0.05)
        bundle.runtime_components.nexus_terminator("shutdown")
    worker.join(5)
    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], adapters.Phase5ComponentAdapterV2Error)
    assert "lifecycle" in str(errors[0])


def test_page_fingerprint_covers_items_digests_and_cursor() -> None:
    fixture = Fixture.create()
    original_issue = fixture.authority.issue_projection

    class WrongPageSigner(ProjectionSigner):
        def __call__(self, **payload: object) -> adapters.ProjectionAttestationV2:
            if payload["phase"] == "post":
                payload["page_digest"] = "f" * 64
            return original_issue(**payload)  # type: ignore[arg-type]

    fixture.signer = WrongPageSigner(fixture.authority)
    bundle = fixture.build(
        flags=adapters.AdapterFlagsV2(True, approval_inbox=True),
        acceptance=adapters.AcceptedComponentsV2(inbox=adapters.INBOX_ACCEPTANCE_V2),
    )
    with pytest.raises(adapters.Phase5ComponentAdapterV2Error, match="attestation"):
        bundle.runtime_components.inbox_factory(BINDING).read_page(
            binding=BINDING, page_size=2, cursor=None
        )


def test_no_live_wiring_authority_mutation_polling_or_threads() -> None:
    forbidden = (
        "phase5_component_adapters_v2",
        "session_grants_v11",
        "capability_nexus_v32",
        "approval_inbox_v15",
    )
    for relative in ("main.py", "ui.py", "dashboard/server.py", "core/permission_broker.py"):
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert all(name not in source for name in forbidden), relative
    source = (ROOT / "core/phase5_component_adapters_v2.py").read_text(encoding="utf-8")
    assert "threading.Thread" not in source
    assert "sleep(" not in source
    assert "requests." not in source
    for cls in (adapters.ApprovalInboxAdapterV2, adapters.CapabilityNexusAdapterV2):
        for name in ("approve", "deny", "dispatch", "execute", "mutate", "grant"):
            assert not hasattr(cls, name)


def test_nexus_projection_p95_under_25ms() -> None:
    fixture = Fixture.create()
    bundle = fixture.build(
        flags=adapters.AdapterFlagsV2(True, nexus_projection=True),
        acceptance=adapters.AcceptedComponentsV2(nexus=adapters.NEXUS_ACCEPTANCE_V2),
    )
    samples: list[float] = []
    for _ in range(100):
        started = time.perf_counter_ns()
        bundle.runtime_components.nexus_projector(BINDING)
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    samples.sort()
    assert samples[94] < 25.0
