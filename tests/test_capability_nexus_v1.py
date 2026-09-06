from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import hashlib
from pathlib import Path
import threading

import pytest

from core.capability_nexus_v1 import (
    CATALOG_CONTRACT_VERSION,
    CAPABILITY_SCHEMA_VERSION,
    NEXUS_CONTRACT_VERSION,
    CancellationTokenV1,
    CapabilityContractError,
    CapabilityDeniedError,
    CapabilityDescriptor,
    CapabilityNexusV1,
    CapabilityStatus,
    CatalogItem,
    CatalogReadRequest,
    LocalReadOnlyCatalogAdapterV1,
    NexusFeatureGateV1,
    OperationDescriptor,
    OperationKind,
    ReconcileState,
    TransportKind,
    build_legacy_descriptors,
)


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = "workspace-alpha"
ACCOUNT = "account-alpha"
PROFILE = "profile-alpha"
KEY = b"k" * 32


def _ast_assignment(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found")


def _legacy_inputs():
    declarations = _ast_assignment(ROOT / "main.py", "TOOL_DECLARATIONS")
    policies = _ast_assignment(ROOT / "core" / "permission_broker.py", "MODEL_TOOL_POLICIES")
    return declarations, policies


def _operation(**changes) -> OperationDescriptor:
    values = {
        "operation_id": "catalog_read",
        "kind": OperationKind.READ,
        "description": "Read allowlisted catalog metadata.",
        "parameter_schema_json": '{"properties":{},"type":"OBJECT"}',
        "required_scopes": ("catalog.metadata.read",),
        "data_classes": ("allowlisted_metadata",),
        "risk_class": "low",
        "approval_class": "host_policy_required",
        "allowed_targets": ("local_catalog",),
        "allowed_domains": (),
    }
    values.update(changes)
    return OperationDescriptor(**values)


def _descriptor(**changes) -> CapabilityDescriptor:
    values = {
        "capability_id": "local.catalog",
        "capability_version": "v1",
        "provider": "onyx_local",
        "transport": TransportKind.LOCAL,
        "api_name": "local_catalog",
        "api_version": CATALOG_CONTRACT_VERSION,
        "workspace_id": WORKSPACE,
        "account_id": ACCOUNT,
        "profile_id": PROFILE,
        "credential_alias": None,
        "operations": (_operation(),),
        "status": CapabilityStatus.DISABLED,
        "status_reason": "candidate_not_activated",
        "limitations": ("no_dispatch",),
    }
    values.update(changes)
    return CapabilityDescriptor(**values)


def _items(count: int = 5) -> tuple[CatalogItem, ...]:
    return tuple(
        CatalogItem(f"item-{index:02d}", f"Item {index}", "fixture", "v1", ("safe",))
        for index in range(count)
    )


def _adapter(**changes) -> LocalReadOnlyCatalogAdapterV1:
    values = {
        "items": _items(),
        "workspace_id": WORKSPACE,
        "account_id": ACCOUNT,
        "profile_id": PROFILE,
        "cursor_signing_key": KEY,
        "status": CapabilityStatus.AVAILABLE_READ_ONLY,
        "status_reason": "healthy",
    }
    values.update(changes)
    return LocalReadOnlyCatalogAdapterV1(**values)


def _request(**changes) -> CatalogReadRequest:
    values = {
        "workspace_id": WORKSPACE,
        "account_id": ACCOUNT,
        "profile_id": PROFILE,
        "target": "local_catalog",
        "correlation_id": "corr-001",
        "page_size": 2,
    }
    values.update(changes)
    return CatalogReadRequest(**values)


def test_versions_are_explicit_and_v1():
    assert CAPABILITY_SCHEMA_VERSION == "onyx.capability.v1"
    assert NEXUS_CONTRACT_VERSION == "onyx.capability-nexus.v1"
    assert CATALOG_CONTRACT_VERSION == "onyx.local-catalog.v1"


def test_descriptor_is_immutable_and_detaches_aliases():
    scopes = ["b.scope", "a.scope"]
    operation = _operation(required_scopes=scopes)
    scopes.append("later.scope")
    assert operation.required_scopes == ("a.scope", "b.scope")
    with pytest.raises(FrozenInstanceError):
        operation.operation_id = "changed"  # type: ignore[misc]
    descriptor = _descriptor(operations=[operation])
    with pytest.raises(FrozenInstanceError):
        descriptor.status = CapabilityStatus.DEGRADED  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("capability_id", "Bad ID"),
        ("capability_version", ""),
        ("workspace_id", "../../escape"),
        ("account_id", "bad account"),
        ("profile_id", "bad\nprofile"),
        ("schema_version", "v2"),
        ("credential_alias", "raw-secret-value"),
        ("status_reason", "not canonical"),
    ],
)
def test_descriptor_rejects_malformed_bounds(field, value):
    with pytest.raises(CapabilityContractError):
        _descriptor(**{field: value})


@pytest.mark.parametrize(
    "secret_value",
    [
        "api_key=abcdef0123456789",
        "Bearer=abcdef0123456789",
        "-----BEGIN PRIVATE KEY-----",
        "eyJabcdefghijk.abcdefghijk.abcdefghijk",
    ],
)
def test_descriptor_rejects_secret_shapes(secret_value):
    with pytest.raises(CapabilityContractError):
        _descriptor(metadata=(("note", secret_value),))


def test_parameter_schema_rejects_secret_bearing_fields_and_noncanonical_json():
    with pytest.raises(CapabilityContractError):
        _operation(parameter_schema_json='{"token":"abcdefghijk"}')
    with pytest.raises(CapabilityContractError):
        _operation(parameter_schema_json='{ "type": "OBJECT", "properties": {} }')


def test_operation_kinds_are_explicit_and_duplicate_operations_fail():
    assert {item.value for item in OperationKind} == {"read", "draft", "mutate", "verify", "reconcile"}
    with pytest.raises(CapabilityContractError):
        _descriptor(operations=(_operation(), _operation()))
    with pytest.raises(CapabilityContractError):
        _operation(kind="read")  # type: ignore[arg-type]


def test_browser_transport_must_be_a_distinct_explicit_fallback():
    with pytest.raises(CapabilityContractError):
        _descriptor(transport=TransportKind.BROWSER)
    descriptor = _descriptor(
        transport=TransportKind.BROWSER,
        metadata=(("fallback_class", "explicit_browser_fallback"),),
    )
    assert descriptor.allowed_browser_fallback_declared


@pytest.mark.parametrize(
    "gate",
    [
        {"nexus_enabled": True},
        {"shadow_mode": False},
        {"dispatch_enabled": True},
        {"nexus_enabled": 0},
        {"contract_version": "v2"},
    ],
)
def test_v1_gate_cannot_be_enabled_or_leave_shadow(gate):
    with pytest.raises(CapabilityContractError):
        NexusFeatureGateV1(**gate)


def test_registry_registers_projection_only_and_never_grants_authority():
    nexus = CapabilityNexusV1()
    descriptor = _descriptor()
    digest = nexus.register(descriptor)
    projection = nexus.discover(
        descriptor.capability_id,
        workspace_id=WORKSPACE,
        account_id=ACCOUNT,
        expected_version="v1",
        expected_digest=digest,
    )
    assert not projection.runtime_available
    assert not projection.authority_granted
    assert projection.projection_status is CapabilityStatus.DISABLED
    assert not hasattr(nexus, "execute")
    assert not hasattr(nexus, "dispatch")


@pytest.mark.parametrize(
    "changes",
    [
        {"capability_id": "missing.capability"},
        {"workspace_id": "workspace-other"},
        {"account_id": "account-other"},
        {"expected_version": "v2"},
        {"expected_digest": "0" * 64},
    ],
)
def test_registry_unknown_binding_version_and_drift_fail_closed(changes):
    nexus = CapabilityNexusV1()
    descriptor = _descriptor()
    nexus.register(descriptor)
    args = {
        "capability_id": descriptor.capability_id,
        "workspace_id": WORKSPACE,
        "account_id": ACCOUNT,
        "expected_version": "v1",
        "expected_digest": descriptor.digest,
    }
    args.update(changes)
    with pytest.raises(CapabilityDeniedError):
        nexus.discover(**args)


def test_registry_duplicate_registration_fails_even_when_identical():
    nexus = CapabilityNexusV1()
    descriptor = _descriptor()
    nexus.register(descriptor)
    with pytest.raises(CapabilityContractError):
        nexus.register(descriptor)


def test_registry_snapshot_is_deterministic_sorted_and_workspace_isolated():
    nexus = CapabilityNexusV1()
    nexus.register(_descriptor(capability_id="zeta.capability"))
    nexus.register(_descriptor(capability_id="alpha.capability"))
    first = nexus.snapshot(workspace_id=WORKSPACE, account_id=ACCOUNT)
    second = nexus.snapshot(workspace_id=WORKSPACE, account_id=ACCOUNT)
    assert first == second
    assert [entry.descriptor.capability_id for entry in first.entries] == [
        "alpha.capability", "zeta.capability"
    ]
    assert nexus.snapshot(workspace_id="workspace-other", account_id=ACCOUNT).entries == ()


def test_registry_revoke_and_kill_are_truthful_projection_states():
    descriptor = _descriptor(credential_alias="alias:catalog/account")
    nexus = CapabilityNexusV1()
    nexus.register(descriptor)
    nexus.revoke_alias("alias:catalog/account")
    projection = nexus.discover(
        descriptor.capability_id, workspace_id=WORKSPACE, account_id=ACCOUNT,
        expected_version="v1", expected_digest=descriptor.digest,
    )
    assert projection.projection_status is CapabilityStatus.BLOCKED_BY_ACCESS
    nexus.set_kill(True)
    killed = nexus.discover(
        descriptor.capability_id, workspace_id=WORKSPACE, account_id=ACCOUNT,
        expected_version="v1", expected_digest=descriptor.digest,
    )
    assert killed.projection_reason == "global_kill_active"


def test_registry_registration_is_thread_safe_and_no_entries_are_lost():
    nexus = CapabilityNexusV1()
    descriptors = [_descriptor(capability_id=f"fixture.capability-{index}") for index in range(24)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(nexus.register, descriptors))
    snapshot = nexus.snapshot(workspace_id=WORKSPACE, account_id=ACCOUNT)
    assert len(snapshot.entries) == 24


def test_legacy_builder_parity_against_current_main_and_host_policy_data():
    declarations, policies = _legacy_inputs()
    before_main = hashlib.sha256((ROOT / "main.py").read_bytes()).hexdigest()
    before_broker = hashlib.sha256((ROOT / "core" / "permission_broker.py").read_bytes()).hexdigest()
    built = build_legacy_descriptors(
        declarations,
        policies,
        workspace_id=WORKSPACE,
        account_id=ACCOUNT,
        profile_id=PROFILE,
    )
    rebuilt_by_name = {item["name"]: item for item in built.declarations()}
    assert rebuilt_by_name == {item["name"]: item for item in declarations}
    assert dict(built.policy_mapping()) == policies
    assert len(built.descriptors) == len(declarations) == len(policies) == 32
    assert {item.capability_id for item in built.descriptors} == {
        f"legacy.{item['name']}" for item in declarations
    }
    assert all(item.status is CapabilityStatus.DISABLED for item in built.descriptors)
    assert all(item.operations[0].kind is OperationKind.MUTATE for item in built.descriptors)
    assert hashlib.sha256((ROOT / "main.py").read_bytes()).hexdigest() == before_main
    assert hashlib.sha256((ROOT / "core" / "permission_broker.py").read_bytes()).hexdigest() == before_broker


@pytest.mark.parametrize("missing", ["open_app", "mission_run"])
def test_legacy_builder_missing_policy_fails_closed(missing):
    declarations, policies = _legacy_inputs()
    policies.pop(missing)
    with pytest.raises(CapabilityContractError):
        build_legacy_descriptors(
            declarations, policies, workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE
        )


def test_legacy_builder_extra_policy_duplicate_or_unknown_kind_fails_closed():
    declarations, policies = _legacy_inputs()
    with pytest.raises(CapabilityContractError):
        build_legacy_descriptors(
            declarations, {**policies, "extra": "always_confirm"},
            workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
        )
    with pytest.raises(CapabilityContractError):
        build_legacy_descriptors(
            declarations + [declarations[0]], policies,
            workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
        )
    kinds = {name: OperationKind.READ for name in policies}
    kinds["open_app"] = "read"  # type: ignore[assignment]
    with pytest.raises(CapabilityContractError):
        build_legacy_descriptors(
            declarations, policies, workspace_id=WORKSPACE, account_id=ACCOUNT,
            profile_id=PROFILE, operation_kinds=kinds,
        )


def test_legacy_builder_is_pure_and_does_not_import_main(monkeypatch):
    declarations, policies = _legacy_inputs()
    imported = []
    original = __import__

    def guarded(name, *args, **kwargs):
        imported.append(name)
        if name == "main":
            raise AssertionError("builder imported main")
        return original(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guarded)
    build_legacy_descriptors(
        declarations, policies, workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE
    )
    assert "main" not in imported


def test_local_descriptor_truthfully_declares_normalized_read_contract():
    descriptor = _adapter().descriptor
    operation = descriptor.operations[0]
    assert descriptor.status is CapabilityStatus.AVAILABLE_READ_ONLY
    assert descriptor.transport is TransportKind.LOCAL
    assert operation.kind is OperationKind.READ
    assert operation.pagination == "signed_bounded_cursor"
    assert operation.idempotency == "exact_correlation_request_binding"
    assert operation.receipt == "immutable_read_receipt"
    assert operation.reconciliation == "read_state_only"
    assert descriptor.credential_alias is None


def test_local_adapter_constructor_defaults_disabled():
    adapter = LocalReadOnlyCatalogAdapterV1(
        _items(), workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
        cursor_signing_key=KEY,
    )
    assert adapter.health().status is CapabilityStatus.DISABLED
    assert adapter.health().reason == "candidate_not_activated"
    with pytest.raises(CapabilityDeniedError, match="candidate_not_activated"):
        adapter.read_page(_request())


@pytest.mark.parametrize(
    ("adapter_changes", "expected_status", "expected_reason"),
    [
        ({"auth_available": False}, CapabilityStatus.BLOCKED_BY_ACCESS, "authentication_unavailable"),
        ({"granted_scopes": ()}, CapabilityStatus.BLOCKED_BY_SCOPE, "required_scope_missing"),
        ({"status": CapabilityStatus.DISABLED, "status_reason": "operator_disabled"}, CapabilityStatus.DISABLED, "operator_disabled"),
        ({"status": CapabilityStatus.DEGRADED, "status_reason": "partial_fixture"}, CapabilityStatus.DEGRADED, "partial_fixture"),
    ],
)
def test_health_reports_auth_scope_disabled_and_degraded_truth(adapter_changes, expected_status, expected_reason):
    health = _adapter(**adapter_changes).health()
    assert health.status is expected_status
    assert health.reason == expected_reason
    assert health.read_only and not health.authority_granted
    assert health.cost_micros == 0


@pytest.mark.parametrize(
    "request_changes",
    [
        {"workspace_id": "workspace-other"},
        {"account_id": "account-other"},
        {"profile_id": "profile-other"},
        {"target": "other_target"},
    ],
)
def test_read_wrong_workspace_account_profile_or_target_denies(request_changes):
    with pytest.raises(CapabilityDeniedError):
        _adapter().read_page(_request(**request_changes))


def test_read_paginates_with_integrity_bound_cursor_and_metadata_only():
    adapter = _adapter()
    first = adapter.read_page(_request())
    assert first.outcome == "succeeded"
    assert [item.item_id for item in first.items] == ["item-00", "item-01"]
    assert first.next_cursor
    second = adapter.read_page(_request(correlation_id="corr-002", cursor=first.next_cursor))
    assert [item.item_id for item in second.items] == ["item-02", "item-03"]
    assert second.cost_micros == 0
    assert second.receipt_digest


def test_cursor_tamper_wrong_key_snapshot_and_bounds_fail_closed():
    adapter = _adapter()
    cursor = adapter.read_page(_request()).next_cursor
    assert cursor
    with pytest.raises(CapabilityDeniedError):
        adapter.read_page(_request(correlation_id="corr-002", cursor=cursor[:-1] + "0"))
    other_key = _adapter(cursor_signing_key=b"x" * 32)
    with pytest.raises(CapabilityDeniedError):
        other_key.read_page(_request(correlation_id="corr-003", cursor=cursor))
    other_snapshot = LocalReadOnlyCatalogAdapterV1(
        _items(6), workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
        cursor_signing_key=KEY,
    )
    with pytest.raises(CapabilityDeniedError):
        other_snapshot.read_page(_request(correlation_id="corr-004", cursor=cursor))


def test_duplicate_correlation_is_idempotent_and_payload_drift_denies():
    adapter = _adapter()
    request = _request()
    first = adapter.read_page(request)
    assert adapter.read_page(request) is first
    with pytest.raises(CapabilityDeniedError):
        adapter.read_page(_request(page_size=3))


def test_rate_limit_and_quota_are_fail_closed_and_telemetry_is_exact():
    adapter = _adapter(rate_limit=1, quota_limit=2, clock=lambda: 100.0)
    first = adapter.read_page(_request())
    assert first.quota_remaining == 1
    limited = adapter.read_page(_request(correlation_id="corr-002"))
    assert limited.outcome == "rate_limited" and limited.retry_after_ms == 1000
    assert adapter.health().quota_remaining == 1


def test_cancellation_before_and_after_read_has_truthful_reconcile_state():
    before = CancellationTokenV1()
    before.cancel()
    adapter = _adapter()
    result = adapter.read_page(_request(cancellation=before))
    assert result.outcome == "cancelled_before_read"
    assert result.reconciliation is ReconcileState.VERIFIED_NO_EXTERNAL_EFFECT
    after = CancellationTokenV1()
    adapter2 = _adapter(read_hook=after.cancel)
    result2 = adapter2.read_page(_request(correlation_id="corr-002", cancellation=after))
    assert result2.outcome == "cancelled_after_read"
    assert result2.reconciliation is ReconcileState.OBSERVED_READ


def test_timeout_before_and_after_read_semantics_are_distinct():
    values = iter([0.0, 2.0])
    before = _adapter(clock=lambda: next(values))
    first = before.read_page(_request(timeout_ms=1000))
    assert first.outcome == "timeout_before_read"
    now = [0.0]
    after = _adapter(clock=lambda: now[0], read_hook=lambda: now.__setitem__(0, 2.0))
    second = after.read_page(_request(correlation_id="corr-002", timeout_ms=1000))
    assert second.outcome == "timeout_after_read"
    assert second.reconciliation is ReconcileState.OBSERVED_READ


def test_reconcile_known_unknown_and_read_only_mutation_denial():
    adapter = _adapter()
    assert adapter.reconcile("never-seen") is ReconcileState.UNKNOWN_CORRELATION
    result = adapter.read_page(_request())
    assert adapter.reconcile(result.correlation_id) is ReconcileState.OBSERVED_READ
    with pytest.raises(CapabilityDeniedError):
        adapter.draft({"unsafe": True})
    with pytest.raises(CapabilityDeniedError):
        adapter.mutate({"unsafe": True})


def test_kill_switch_stops_new_reads_without_invalidating_observed_reconcile():
    adapter = _adapter()
    result = adapter.read_page(_request())
    adapter.set_kill(True)
    assert adapter.health().reason == "global_kill_active"
    with pytest.raises(CapabilityDeniedError):
        adapter.read_page(_request(correlation_id="corr-002"))
    assert adapter.reconcile(result.correlation_id) is ReconcileState.OBSERVED_READ


def test_degraded_read_is_labeled_and_disabled_read_denies():
    degraded = _adapter(status=CapabilityStatus.DEGRADED, status_reason="partial_fixture")
    assert degraded.read_page(_request()).outcome == "degraded_success"
    disabled = _adapter(status=CapabilityStatus.DISABLED, status_reason="operator_disabled")
    with pytest.raises(CapabilityDeniedError, match="operator_disabled"):
        disabled.read_page(_request())


def test_concurrent_duplicate_read_returns_one_immutable_result():
    adapter = _adapter()
    request = _request()
    start = threading.Barrier(8)

    def read_once(_index):
        start.wait()
        return adapter.read_page(request)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(read_once, range(8)))
    assert all(result is results[0] for result in results)
    assert adapter.health().quota_remaining == 99


def test_no_live_runtime_file_imports_or_wires_v1():
    forbidden = "capability_nexus_v1"
    live_files = [ROOT / "main.py", ROOT / "ui.py", ROOT / "scripts" / "launch_onyx.pyw"]
    live_files += list((ROOT / "dashboard").rglob("*.py"))
    live_files += [
        path for path in (ROOT / "core").glob("*.py")
        if path.name != "capability_nexus_v1.py"
    ]
    assert all(forbidden not in path.read_text(encoding="utf-8", errors="ignore") for path in live_files)


def test_default_off_parity_main_declarations_remain_byte_exact():
    before = (ROOT / "main.py").read_bytes()
    declarations, policies = _legacy_inputs()
    build_legacy_descriptors(
        declarations, policies, workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE
    )
    assert (ROOT / "main.py").read_bytes() == before
    assert NexusFeatureGateV1() == NexusFeatureGateV1(False, True, False)
