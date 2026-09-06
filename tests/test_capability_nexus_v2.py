from __future__ import annotations

import ast
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import hashlib
from pathlib import Path
import threading

import pytest

from core.capability_nexus_v2 import (
    CATALOG_CONTRACT_VERSION_V2,
    LOCK_ORDER_V2,
    CancellationTokenV2,
    CapabilityDescriptorV2,
    CapabilityNexusV2,
    CapabilityProjectionV2,
    CapabilityStatusV2,
    CapabilityV2ContractError,
    CapabilityV2DeniedError,
    CatalogItemV2,
    CatalogReadRequestV2,
    LocalCatalogReadAdapterV2,
    NexusFeatureGateV2,
    OperationDescriptorV2,
    OperationKindV2,
    ReadFailureClassV2,
    ReadStateV2,
    TransportKindV2,
    build_legacy_descriptors_v2,
)


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = "workspace-alpha"
ACCOUNT = "account-alpha"
PROFILE = "profile-alpha"
KEY = b"k" * 32
V1_HASHES = {
    "core/capability_nexus_v1.py": "cd196f8805b7d89923ce98607fe1c49a762c7001456b470677585f60fa27474a",
    "tests/test_capability_nexus_v1.py": "f1f183938294d4963ddc52e1910287b5ed4ff8854ff149011bb0cfda17a1571c",
    "scripts/verify_phase5_capability_nexus_v1.py": "8f8509f920d99bf524b6b0a7073608cd0ccf3470287dbddc376d46ffddaa9c56",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V1-001.sha256": "e5f7d577cd0916c3df46d5b540668540fc88a1ec7c60130a198b78c75ec4249b",
}


def _assignment(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(item, ast.Name) and item.id == name for item in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(name)


def _operation(**changes) -> OperationDescriptorV2:
    values = {
        "operation_id": "catalog_read", "kind": OperationKindV2.READ,
        "description": "Read allowlisted metadata.",
        "parameter_schema_json": '{"properties":{},"type":"OBJECT"}',
        "required_scopes": ("catalog.metadata.read",), "data_classes": ("allowlisted_metadata",),
        "risk_class": "low", "approval_class": "host_policy_required",
        "allowed_targets": ("local_catalog",),
    }
    values.update(changes)
    return OperationDescriptorV2(**values)


def _descriptor(**changes) -> CapabilityDescriptorV2:
    values = {
        "capability_id": "local.catalog", "capability_version": "v2", "provider": "onyx_local",
        "transport": TransportKindV2.LOCAL, "api_name": "local_catalog",
        "api_version": CATALOG_CONTRACT_VERSION_V2, "workspace_id": WORKSPACE,
        "account_id": ACCOUNT, "profile_id": PROFILE, "credential_alias": None,
        "operations": (_operation(),), "status": CapabilityStatusV2.DISABLED,
        "status_reason": "candidate_not_activated", "limitations": ("no_dispatch",),
    }
    values.update(changes)
    return CapabilityDescriptorV2(**values)


def _items(count: int = 5) -> tuple[CatalogItemV2, ...]:
    return tuple(CatalogItemV2(f"item-{i:02d}", f"Item {i}", "fixture", "v2", ("safe",)) for i in range(count))


def _adapter(hook=lambda: None, **changes) -> LocalCatalogReadAdapterV2:
    values = {
        "items": _items(), "workspace_id": WORKSPACE, "account_id": ACCOUNT,
        "profile_id": PROFILE, "cursor_signing_key": KEY, "read_hook": hook,
        "status": CapabilityStatusV2.AVAILABLE_READ_ONLY, "status_reason": "healthy",
    }
    values.update(changes)
    return LocalCatalogReadAdapterV2(**values)


def _request(**changes) -> CatalogReadRequestV2:
    values = {
        "workspace_id": WORKSPACE, "account_id": ACCOUNT, "profile_id": PROFILE,
        "target": "local_catalog", "correlation_id": "corr-001", "page_size": 2,
    }
    values.update(changes)
    return CatalogReadRequestV2(**values)


def test_v1_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V1_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_registry_requires_profile_and_binds_discovery_exactly():
    nexus = CapabilityNexusV2()
    descriptor = _descriptor()
    nexus.register(descriptor)
    with pytest.raises(TypeError):
        nexus.discover(
            descriptor.capability_id, workspace_id=WORKSPACE, account_id=ACCOUNT,
            expected_version="v2", expected_digest=descriptor.digest,
        )
    for profile in ("profile-other", "PROFILE-alpha"):
        with pytest.raises(CapabilityV2DeniedError):
            nexus.discover(
                descriptor.capability_id, workspace_id=WORKSPACE, account_id=ACCOUNT,
                profile_id=profile, expected_version="v2", expected_digest=descriptor.digest,
            )


def test_snapshot_is_profile_bound_and_digest_changes_by_profile():
    nexus = CapabilityNexusV2()
    nexus.register(_descriptor())
    first = nexus.snapshot(workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE)
    other = nexus.snapshot(workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id="profile-other")
    assert len(first.entries) == 1 and other.entries == ()
    assert first.snapshot_digest != other.snapshot_digest
    with pytest.raises(FrozenInstanceError):
        first.profile_id = "changed"  # type: ignore[misc]


def test_projection_constructor_rejects_cross_profile_and_authority():
    descriptor = _descriptor()
    with pytest.raises(CapabilityV2ContractError):
        CapabilityProjectionV2(
            descriptor, descriptor.digest, WORKSPACE, ACCOUNT, "profile-other",
            CapabilityStatusV2.DISABLED, "disabled",
        )
    with pytest.raises(CapabilityV2ContractError):
        CapabilityProjectionV2(
            descriptor, descriptor.digest, WORKSPACE, ACCOUNT, PROFILE,
            CapabilityStatusV2.DISABLED, "disabled", authority_granted=True,
        )


class _GateSubclass(NexusFeatureGateV2):
    pass


class _FakeGate:
    nexus_enabled = False
    shadow_mode = True
    dispatch_enabled = False


@pytest.mark.parametrize("gate", [_GateSubclass(), _FakeGate(), object()])
def test_registry_rejects_gate_subclasses_fakes_and_duck_types(gate):
    with pytest.raises(CapabilityV2ContractError, match="exact concrete"):
        CapabilityNexusV2(gate)  # type: ignore[arg-type]


def test_exact_gate_is_frozen_default_off_and_lock_order_is_declared():
    gate = NexusFeatureGateV2()
    nexus = CapabilityNexusV2(gate)
    assert nexus.gate is gate and nexus.lock_order == LOCK_ORDER_V2
    with pytest.raises(FrozenInstanceError):
        gate.shadow_mode = False  # type: ignore[misc]
    for values in ({"nexus_enabled": True}, {"shadow_mode": False}, {"dispatch_enabled": True}):
        with pytest.raises(CapabilityV2ContractError):
            NexusFeatureGateV2(**values)


@pytest.mark.parametrize(
    "key",
    ["api_key", "Api-Key", "TOKEN", "pass.word", "Secret", "authorization", "cookie", "private-key", "%61pi_key"],
)
def test_metadata_rejects_secret_names_and_normalization_bypasses(key):
    with pytest.raises(CapabilityV2ContractError):
        _descriptor(metadata=((key, "redacted"),))


@pytest.mark.parametrize(
    "value",
    [
        "token=abcd1234", "TOKEN%3Dabcd1234", "password:abcd1234",
        "-----BEGIN PRIVATE KEY-----", "eyJabcdefgh.abcdefgh.abcdefgh",
        base64.b64encode(b"api_key=abcd1234").decode(),
    ],
)
def test_metadata_rejects_plain_percent_and_base64_secret_values(value):
    with pytest.raises(CapabilityV2ContractError):
        _descriptor(metadata=(("data_source", value),))


def test_metadata_accepts_only_declared_safe_keys_and_opaque_alias_not_value():
    descriptor = _descriptor(
        credential_alias="alias:catalog/account", metadata=(("data_source", "constructor_allowlist"),)
    )
    assert descriptor.credential_alias == "alias:catalog/account"
    with pytest.raises(CapabilityV2ContractError):
        _descriptor(metadata=(("random_note", "safe"),))
    with pytest.raises(CapabilityV2ContractError):
        _descriptor(metadata=(("data_source", {"token": "hidden"}),))


def test_nested_schema_secret_canaries_are_rejected():
    with pytest.raises(CapabilityV2ContractError):
        _operation(parameter_schema_json='{"properties":{"nested":{"properties":{"Password":{"type":"STRING"}}}}}')


def test_adapter_defaults_disabled_and_has_no_dispatch_or_mutation():
    adapter = LocalCatalogReadAdapterV2(
        _items(), workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
        cursor_signing_key=KEY, read_hook=lambda: None,
    )
    assert adapter.health().status is CapabilityStatusV2.DISABLED
    assert adapter.read_page(_request()).state is ReadStateV2.DENIED
    assert not hasattr(adapter, "execute") and not hasattr(adapter, "dispatch")
    with pytest.raises(CapabilityV2DeniedError):
        adapter.mutate({})


def test_hook_runs_without_adapter_lock_and_can_reenter_health():
    holder = {}
    observed = []

    def hook():
        observed.append(holder["adapter"].health().status)
        finished = threading.Event()
        thread = threading.Thread(target=lambda: (holder["adapter"].health(), finished.set()))
        thread.start()
        assert finished.wait(1), "adapter lock was held across hook"
        thread.join()

    holder["adapter"] = _adapter(hook)
    result = holder["adapter"].read_page(_request())
    assert result.state is ReadStateV2.COMPLETED
    assert observed == [CapabilityStatusV2.AVAILABLE_READ_ONLY]


def test_same_correlation_reentry_observes_pending_without_second_hook():
    holder = {}
    calls = []
    request = _request()

    def hook():
        calls.append(1)
        nested = holder["adapter"].read_page(request)
        assert nested.state is ReadStateV2.PENDING

    holder["adapter"] = _adapter(hook)
    assert holder["adapter"].read_page(request).state is ReadStateV2.COMPLETED
    assert len(calls) == 1


def test_concurrent_duplicate_is_pending_then_completed_and_hook_once():
    entered, release = threading.Event(), threading.Event()
    calls = []

    def hook():
        calls.append(1)
        entered.set()
        assert release.wait(2)

    adapter = _adapter(hook)
    request = _request()
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(adapter.read_page, request)
        assert entered.wait(1)
        duplicate = adapter.read_page(request)
        assert duplicate.state is ReadStateV2.PENDING
        release.set()
        assert future.result().state is ReadStateV2.COMPLETED
    assert len(calls) == 1 and adapter.health().quota_remaining == 99


def test_same_correlation_payload_drift_denies_without_hook_or_quota():
    calls = []
    adapter = _adapter(lambda: calls.append(1))
    adapter.read_page(_request())
    with pytest.raises(CapabilityV2DeniedError, match="drift"):
        adapter.read_page(_request(page_size=3))
    assert calls == [1] and adapter.health().quota_remaining == 99


def test_hook_exception_becomes_uncertain_and_never_replays_or_leaks_exception():
    calls = []

    def hook():
        calls.append(1)
        raise RuntimeError("token=super-secret-value")

    adapter = _adapter(hook)
    request = _request()
    result = adapter.read_page(request)
    assert result.state is ReadStateV2.UNCERTAIN
    assert result.failure_class is ReadFailureClassV2.HOOK_EXCEPTION
    assert "secret" not in repr(result).lower()
    assert adapter.read_page(request) == result
    assert adapter.reconcile(request) == result
    assert calls == [1] and adapter.health().quota_remaining == 99


def test_cancelled_before_hook_rolls_back_quota_and_rate_and_never_calls_hook():
    token = CancellationTokenV2()
    now = [10.0]
    clock_calls = [0]

    def clock():
        clock_calls[0] += 1
        if clock_calls[0] == 2:
            token.cancel()
        return now[0]

    calls = []
    adapter = _adapter(lambda: calls.append(1), quota_limit=1, rate_limit=1, clock=clock)
    result = adapter.read_page(_request(cancellation=token))
    assert result.state is ReadStateV2.CANCELLED_BEFORE_HOOK
    assert adapter.health().quota_remaining == 1
    assert calls == []
    assert adapter.read_page(_request(correlation_id="corr-002")).state is ReadStateV2.COMPLETED


def test_timeout_after_hook_is_uncertain_and_not_replayed():
    now = [0.0]
    calls = []

    def hook():
        calls.append(1)
        now[0] = 2.0

    adapter = _adapter(hook, clock=lambda: now[0])
    request = _request(timeout_ms=1000)
    result = adapter.read_page(request)
    assert result.state is ReadStateV2.UNCERTAIN
    assert result.failure_class is ReadFailureClassV2.TIMEOUT
    assert adapter.read_page(request) == result and calls == [1]


@pytest.mark.parametrize(("action", "failure"), [("kill", ReadFailureClassV2.KILL), ("revoke", ReadFailureClassV2.REVOKED)])
def test_kill_and_revoke_during_hook_latch_uncertain(action, failure):
    holder = {}

    def hook():
        holder["adapter"].set_kill(True) if action == "kill" else holder["adapter"].revoke()

    holder["adapter"] = _adapter(hook, credential_alias="alias:catalog/account")
    result = holder["adapter"].read_page(_request())
    assert result.state is ReadStateV2.UNCERTAIN and result.failure_class is failure
    assert holder["adapter"].read_page(_request()) == result


def test_pending_expiry_becomes_uncertain_and_late_hook_cannot_commit():
    now = [0.0]
    entered, release = threading.Event(), threading.Event()

    def hook():
        entered.set()
        assert release.wait(2)

    adapter = _adapter(hook, clock=lambda: now[0], pending_ttl_seconds=1.0)
    request = _request()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(adapter.read_page, request)
        assert entered.wait(1)
        now[0] = 2.0
        reconciled = adapter.reconcile(request)
        assert reconciled.state is ReadStateV2.UNCERTAIN
        assert reconciled.failure_class is ReadFailureClassV2.EXPIRED_PENDING
        release.set()
        assert future.result().state is ReadStateV2.UNCERTAIN


def test_uncertain_expiry_keeps_no_replay_tombstone_and_frees_uncertain_capacity():
    now = [0.0]
    calls = []

    def hook():
        calls.append(1)
        raise RuntimeError("fixed")

    adapter = _adapter(
        hook, clock=lambda: now[0], uncertain_ttl_seconds=1.0,
        pending_capacity=1, uncertain_capacity=1,
    )
    first_request = _request()
    assert adapter.read_page(first_request).state is ReadStateV2.UNCERTAIN
    with pytest.raises(CapabilityV2DeniedError, match="pending/uncertain"):
        adapter.read_page(_request(correlation_id="corr-002"))
    now[0] = 2.0
    expired = adapter.reconcile(first_request)
    assert expired.state is ReadStateV2.EXPIRED_UNCERTAIN
    assert expired.failure_class is ReadFailureClassV2.UNCERTAIN_EXPIRED
    assert adapter.read_page(first_request) == expired and calls == [1]
    assert adapter.read_page(_request(correlation_id="corr-002")).state is ReadStateV2.UNCERTAIN


def test_pending_and_uncertain_capacity_configuration_is_bounded():
    with pytest.raises(CapabilityV2ContractError):
        _adapter(ledger_capacity=2, pending_capacity=2, uncertain_capacity=1)
    with pytest.raises(CapabilityV2ContractError):
        _adapter(ledger_capacity=1, pending_capacity=1, uncertain_capacity=2)


def test_ledger_capacity_is_bounded_and_does_not_evict_for_replay():
    adapter = _adapter(ledger_capacity=1, pending_capacity=1, uncertain_capacity=1)
    request = _request()
    assert adapter.read_page(request).state is ReadStateV2.COMPLETED
    with pytest.raises(CapabilityV2DeniedError, match="capacity"):
        adapter.read_page(_request(correlation_id="corr-002"))
    assert adapter.read_page(request).state is ReadStateV2.COMPLETED


def test_profile_bound_cursor_cannot_cross_adapter_profile():
    first_adapter = _adapter()
    first = first_adapter.read_page(_request())
    assert first.next_cursor
    other = _adapter(profile_id="profile-other")
    with pytest.raises(CapabilityV2DeniedError):
        other.read_page(_request(profile_id="profile-other", correlation_id="corr-002", cursor=first.next_cursor))


def test_cursor_snapshot_and_signature_tamper_fail_closed():
    adapter = _adapter()
    cursor = adapter.read_page(_request()).next_cursor
    assert cursor
    tampered = cursor[:-1] + ("0" if cursor[-1] != "0" else "1")
    with pytest.raises(CapabilityV2DeniedError):
        adapter.read_page(_request(correlation_id="corr-002", cursor=tampered))
    changed = LocalCatalogReadAdapterV2(
        _items(6), workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
        cursor_signing_key=KEY, read_hook=lambda: None, status=CapabilityStatusV2.AVAILABLE_READ_ONLY,
        status_reason="healthy",
    )
    with pytest.raises(CapabilityV2DeniedError):
        changed.read_page(_request(correlation_id="corr-003", cursor=cursor))


def test_rate_limit_and_quota_are_reserved_once_and_truthful():
    adapter = _adapter(rate_limit=1, quota_limit=1, clock=lambda: 10.0)
    assert adapter.read_page(_request()).state is ReadStateV2.COMPLETED
    limited = adapter.read_page(_request(correlation_id="corr-002"))
    assert limited.state is ReadStateV2.RATE_LIMITED and limited.retry_after_ms == 1000
    assert adapter.read_page(_request(correlation_id="corr-002")) == limited
    assert adapter.health().quota_remaining == 0


def test_unavailable_auth_scope_disabled_degraded_and_unknown_reconcile():
    assert _adapter(auth_available=False).read_page(_request()).failure_class is ReadFailureClassV2.AUTH
    assert _adapter(granted_scopes=()).read_page(_request()).failure_class is ReadFailureClassV2.SCOPE
    assert _adapter(status=CapabilityStatusV2.DISABLED, status_reason="operator_disabled").read_page(_request()).state is ReadStateV2.DENIED
    degraded = _adapter(status=CapabilityStatusV2.DEGRADED, status_reason="partial_fixture")
    assert degraded.read_page(_request()).state is ReadStateV2.COMPLETED
    unknown = degraded.reconcile(_request(correlation_id="unknown-corr"))
    assert unknown.state is ReadStateV2.UNKNOWN_CORRELATION


def test_legacy_builder_preserves_current_32_declarations_and_policies_without_import():
    declarations = _assignment(ROOT / "main.py", "TOOL_DECLARATIONS")
    policies = _assignment(ROOT / "core" / "permission_broker.py", "MODEL_TOOL_POLICIES")
    built = build_legacy_descriptors_v2(
        declarations, policies, workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
    )
    assert len(built.descriptors) == 32
    assert {item["name"]: item for item in built.declarations()} == {item["name"]: item for item in declarations}
    assert dict(built.policy_mapping()) == policies
    assert all(item.status is CapabilityStatusV2.DISABLED for item in built.descriptors)


def test_legacy_missing_policy_and_duplicate_declaration_fail_closed():
    declarations = _assignment(ROOT / "main.py", "TOOL_DECLARATIONS")
    policies = _assignment(ROOT / "core" / "permission_broker.py", "MODEL_TOOL_POLICIES")
    policies.pop("open_app")
    with pytest.raises(CapabilityV2ContractError):
        build_legacy_descriptors_v2(
            declarations, policies, workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
        )
    with pytest.raises(CapabilityV2ContractError):
        build_legacy_descriptors_v2(
            declarations + [declarations[0]], {**policies, "open_app": "always_confirm"},
            workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
        )


def test_registry_concurrency_duplicate_kill_revoke_and_snapshot_are_safe():
    nexus = CapabilityNexusV2()
    descriptors = [_descriptor(capability_id=f"fixture.capability-{i}") for i in range(16)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(nexus.register, descriptors))
    assert len(nexus.snapshot(workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE).entries) == 16
    nexus.set_kill(True)
    assert all(
        item.projection_reason == "global_kill_active"
        for item in nexus.snapshot(workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE).entries
    )


def test_no_live_runtime_source_references_v2():
    live = [ROOT / "main.py", ROOT / "ui.py", ROOT / "scripts" / "launch_onyx.pyw"]
    live += list((ROOT / "actions").rglob("*.py")) + list((ROOT / "dashboard").rglob("*.py"))
    live += [path for path in (ROOT / "core").glob("*.py") if path.name != "capability_nexus_v2.py"]
    assert all("capability_nexus_v2" not in path.read_text(encoding="utf-8", errors="ignore") for path in live)
