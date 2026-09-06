from __future__ import annotations

import ast
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import hashlib
from pathlib import Path
import threading
from urllib.parse import quote

import pytest

from core.capability_nexus_v4 import (
    CATALOG_CONTRACT_VERSION_V4,
    LOCK_ORDER_V4,
    CancellationTokenV4,
    CapabilityDescriptorV4,
    CapabilityNexusV4,
    CapabilityProjectionV4,
    CapabilityStatusV4,
    CapabilityV4ContractError,
    CapabilityV4DeniedError,
    CatalogItemV4,
    CatalogReadRequestV4,
    LocalCatalogReadAdapterV4,
    NexusFeatureGateV4,
    OperationDescriptorV4,
    OperationKindV4,
    ReadFailureClassV4,
    ReadStateV4,
    TransportKindV4,
    build_legacy_descriptors_v4,
)
import core.capability_nexus_v4 as nexus_v4_module


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
V2_HASHES = {
    "core/capability_nexus_v2.py": "4493fddc3d1d17da99db08aa98395ae14f0b9050c1d7238b59261e503424235a",
    "tests/test_capability_nexus_v2.py": "61e0b9256e3397b16fed985a7c0f39e9ff8b66dd42e1420e3bb79f37fa5b7b52",
    "scripts/verify_phase5_capability_nexus_v2.py": "20c9a5638f8612cd03a0ceb098af263b9b0f67361d38f0e452877235cc27553b",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V2-001.sha256": "668c5ced47eb6c1b654fcc5fb11c372e36b279e5a4af9f83121ebd806a7d8e7b",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V2-001.sha256": "72ddcefff3bb5c99ab7850156f9ec108e64237ca32b17d582e3a8669d8087759",
}
V3_HASHES = {
    "core/capability_nexus_v3.py": "4fed38cc65ecdce2aa4a352465cd91e4c5e36ab2ff4413333531957afa386aa2",
    "tests/test_capability_nexus_v3.py": "64b2a6c2fd252b4f30bc9bb04afad021757ea1980b4d020d7b38e99748aee035",
    "scripts/verify_phase5_capability_nexus_v3.py": "bbfacc680cdc12bc6e201b4e57317a19a2926eb457c6138b7f29aa6c332ddae7",
    "scripts/check_phase5_capability_nexus_v3_whitespace.py": "ef9a907cc340847afb97b34fbfc2a300e5972a7730c83214dfa15e8a1b94e150",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V3-001.sha256": "270f2dd2ad0249e33bc0d04fff50ff150e74d75d687cd76fe2a16fae436b32a6",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V3-001.sha256": "071aa8e114db52e13f7381dade398b92bda6e1466514e49298c9b4a7efb91251",
}


def _assignment(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(item, ast.Name) and item.id == name for item in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(name)


def _operation(**changes) -> OperationDescriptorV4:
    values = {
        "operation_id": "catalog_read", "kind": OperationKindV4.READ,
        "description": "Read allowlisted metadata.",
        "parameter_schema_json": '{"properties":{},"type":"OBJECT"}',
        "required_scopes": ("catalog.metadata.read",), "data_classes": ("allowlisted_metadata",),
        "risk_class": "low", "approval_class": "host_policy_required",
        "allowed_targets": ("local_catalog",),
    }
    values.update(changes)
    return OperationDescriptorV4(**values)


def _descriptor(**changes) -> CapabilityDescriptorV4:
    values = {
        "capability_id": "local.catalog", "capability_version": "v4", "provider": "onyx_local",
        "transport": TransportKindV4.LOCAL, "api_name": "local_catalog",
        "api_version": CATALOG_CONTRACT_VERSION_V4, "workspace_id": WORKSPACE,
        "account_id": ACCOUNT, "profile_id": PROFILE, "credential_alias": None,
        "operations": (_operation(),), "status": CapabilityStatusV4.DISABLED,
        "status_reason": "candidate_not_activated", "limitations": ("no_dispatch",),
    }
    values.update(changes)
    return CapabilityDescriptorV4(**values)


def _items(count: int = 5) -> tuple[CatalogItemV4, ...]:
    return tuple(CatalogItemV4(f"item-{i:02d}", f"Item {i}", "fixture", "v4", ("safe",)) for i in range(count))


def _adapter(hook=lambda: None, **changes) -> LocalCatalogReadAdapterV4:
    values = {
        "items": _items(), "workspace_id": WORKSPACE, "account_id": ACCOUNT,
        "profile_id": PROFILE, "cursor_signing_key": KEY, "read_hook": hook,
        "status": CapabilityStatusV4.AVAILABLE_READ_ONLY, "status_reason": "healthy",
    }
    values.update(changes)
    return LocalCatalogReadAdapterV4(**values)


def _request(**changes) -> CatalogReadRequestV4:
    values = {
        "workspace_id": WORKSPACE, "account_id": ACCOUNT, "profile_id": PROFILE,
        "target": "local_catalog", "correlation_id": "corr-001", "page_size": 2,
    }
    values.update(changes)
    return CatalogReadRequestV4(**values)


def test_v1_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V1_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v2_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V2_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v3_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V3_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def _percent_layers(value: str, layers: int) -> str:
    for _ in range(layers):
        value = quote(value, safe="-._~/:@")
    return value


def _base64_layers(value: str, layers: int, *, urlsafe: bool = False, unpadded: bool = False) -> str:
    for _ in range(layers):
        encoder = base64.urlsafe_b64encode if urlsafe else base64.b64encode
        value = encoder(value.encode()).decode()
        if unpadded:
            value = value.rstrip("=")
    return value


def test_registry_requires_profile_and_binds_discovery_exactly():
    nexus = CapabilityNexusV4()
    descriptor = _descriptor()
    nexus.register(descriptor)
    with pytest.raises(TypeError):
        nexus.discover(
            descriptor.capability_id, workspace_id=WORKSPACE, account_id=ACCOUNT,
            expected_version="v4", expected_digest=descriptor.digest,
        )
    for profile in ("profile-other", "PROFILE-alpha"):
        with pytest.raises(CapabilityV4DeniedError):
            nexus.discover(
                descriptor.capability_id, workspace_id=WORKSPACE, account_id=ACCOUNT,
                profile_id=profile, expected_version="v4", expected_digest=descriptor.digest,
            )


def test_snapshot_is_profile_bound_and_digest_changes_by_profile():
    nexus = CapabilityNexusV4()
    nexus.register(_descriptor())
    first = nexus.snapshot(workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE)
    other = nexus.snapshot(workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id="profile-other")
    assert len(first.entries) == 1 and other.entries == ()
    assert first.snapshot_digest != other.snapshot_digest
    with pytest.raises(FrozenInstanceError):
        first.profile_id = "changed"  # type: ignore[misc]


def test_projection_constructor_rejects_cross_profile_and_authority():
    descriptor = _descriptor()
    with pytest.raises(CapabilityV4ContractError):
        CapabilityProjectionV4(
            descriptor, descriptor.digest, WORKSPACE, ACCOUNT, "profile-other",
            CapabilityStatusV4.DISABLED, "disabled",
        )
    with pytest.raises(CapabilityV4ContractError):
        CapabilityProjectionV4(
            descriptor, descriptor.digest, WORKSPACE, ACCOUNT, PROFILE,
            CapabilityStatusV4.DISABLED, "disabled", authority_granted=True,
        )


class _GateSubclass(NexusFeatureGateV4):
    pass


class _FakeGate:
    nexus_enabled = False
    shadow_mode = True
    dispatch_enabled = False


@pytest.mark.parametrize("gate", [_GateSubclass(), _FakeGate(), object()])
def test_registry_rejects_gate_subclasses_fakes_and_duck_types(gate):
    with pytest.raises(CapabilityV4ContractError, match="exact concrete"):
        CapabilityNexusV4(gate)  # type: ignore[arg-type]


def test_exact_gate_is_frozen_default_off_and_lock_order_is_declared():
    gate = NexusFeatureGateV4()
    nexus = CapabilityNexusV4(gate)
    assert nexus.gate is gate and nexus.lock_order == LOCK_ORDER_V4
    with pytest.raises(FrozenInstanceError):
        gate.shadow_mode = False  # type: ignore[misc]
    for values in ({"nexus_enabled": True}, {"shadow_mode": False}, {"dispatch_enabled": True}):
        with pytest.raises(CapabilityV4ContractError):
            NexusFeatureGateV4(**values)


@pytest.mark.parametrize(
    "key",
    ["api_key", "Api-Key", "TOKEN", "pass.word", "Secret", "authorization", "cookie", "private-key", "%61pi_key"],
)
def test_metadata_rejects_secret_names_and_normalization_bypasses(key):
    with pytest.raises(CapabilityV4ContractError):
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
    with pytest.raises(CapabilityV4ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize("layers", [2, 3])
def test_metadata_rejects_double_and_triple_percent_secret(layers):
    with pytest.raises(CapabilityV4ContractError):
        _descriptor(metadata=(("data_source", _percent_layers("token=abcd1234", layers)),))


@pytest.mark.parametrize("layers", [2, 3])
def test_metadata_rejects_double_and_triple_base64_secret(layers):
    with pytest.raises(CapabilityV4ContractError):
        _descriptor(metadata=(("data_source", _base64_layers("api_key=abcd1234", layers)),))


def test_metadata_rejects_mixed_percent_base64_secret():
    encoded = _percent_layers(_base64_layers("password=abcd1234", 2), 2)
    with pytest.raises(CapabilityV4ContractError):
        _descriptor(metadata=(("data_source", encoded),))


@pytest.mark.parametrize("unpadded", [False, True])
def test_metadata_rejects_urlsafe_padded_and_unpadded_secret(unpadded):
    encoded = _base64_layers("authorization=Bearer1234", 2, urlsafe=True, unpadded=unpadded)
    with pytest.raises(CapabilityV4ContractError):
        _descriptor(metadata=(("data_source", encoded),))


@pytest.mark.parametrize(
    "value",
    ["ＴＯＫＥＮ＝abcd1234", "ToKeN=abcd1234", "to\u200bken=abcd1234", "token\x00=abcd1234"],
)
def test_metadata_rejects_case_unicode_and_control_canaries(value):
    with pytest.raises(CapabilityV4ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "value",
    [
        "sk-" + "A" * 32,
        "sk-proj-" + "B" * 40,
        "ghp_" + "c" * 36,
        "gho_" + "D" * 40,
        "AKIA" + "E" * 16,
        "ASIA" + "F" * 16,
        "sk_live_" + "g" * 24,
        "sk_test_" + "H" * 24,
        "AIza" + "i" * 35,
        "Bearer " + "j" * 32,
        "Basic " + base64.b64encode(b"user:password").decode(),
    ],
)
def test_metadata_rejects_bounded_raw_credential_families(value):
    with pytest.raises(CapabilityV4ContractError, match="secret"):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "value",
    [
        "sk-short",
        "ghp_short",
        "AKIA" + "A" * 15,
        "BKIA" + "A" * 16,
        "pk_live_" + "a" * 24,
        "AIza" + "a" * 34,
        "bearer_policy",
        "Basic authentication",
    ],
)
def test_metadata_raw_credential_near_misses_remain_valid(value):
    assert dict(_descriptor(metadata=(("data_source", value),)).metadata)["data_source"] == value


@pytest.mark.parametrize(
    "value",
    [
        "арі_кеу=abcd1234",
        "tоken=abcd1234",
        "раssword=abcd1234",
        "sεcret=abcd1234",
        "аuth=abcd1234",
        "cοοkie=abcd1234",
        "рrivate=abcd1234",
        "вearer=abcd1234",
    ],
)
def test_metadata_rejects_cyrillic_and_greek_secret_confusables(value):
    with pytest.raises(CapabilityV4ContractError):
        _descriptor(metadata=(("data_source", value),))


def test_metadata_confusables_are_scanned_after_mixed_decoding_layers():
    encoded = _percent_layers(_base64_layers("tоken=abcd1234", 2), 2)
    with pytest.raises(CapabilityV4ContractError):
        _descriptor(metadata=(("data_source", encoded),))


@pytest.mark.parametrize(
    "value",
    ["token\u202e=abcd1234", "to\u0338ken=abcd1234", "mode=локальный", '{"mode":"локальный"}'],
)
def test_metadata_rejects_bidi_combining_and_structured_script_mixing(value):
    with pytest.raises(CapabilityV4ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize("value", ["東京カタログ", "каталогданных", "Δεδομένα"])
def test_metadata_preserves_benign_unstructured_international_display(value):
    assert dict(_descriptor(metadata=(("data_source", value),)).metadata)["data_source"] == value


@pytest.mark.parametrize(
    "key,value",
    [
        ("data_source", "constructor_allowlist"),
        ("dispatch_path", "legacy_unchanged"),
        ("policy_source", "trusted_host_mapping"),
        ("fallback_class", "explicit_browser_fallback"),
        ("declaration_sha256", "a" * 64),
        ("data_source", "healthy"),
        ("data_source", "local_catalog"),
    ],
)
def test_benign_metadata_fixtures_remain_valid(key, value):
    assert dict(_descriptor(metadata=((key, value),)).metadata)[key] == value


def test_metadata_rejects_malformed_ambiguous_and_residual_encodings():
    for value in ("safe%ZZvalue", "abcd+_==", "safe\\u0074oken"):
        with pytest.raises(CapabilityV4ContractError):
            _descriptor(metadata=(("data_source", value),))


def test_metadata_rejects_depth_and_expansion_bombs():
    too_deep = _base64_layers("token=abcd1234", 8)
    with pytest.raises(CapabilityV4ContractError, match="depth"):
        _descriptor(metadata=(("data_source", too_deep),))
    expansion = "\ufdfa" * 500
    with pytest.raises(CapabilityV4ContractError, match="expansion"):
        _descriptor(metadata=(("data_source", expansion),))


def test_metadata_cycle_detection_fails_closed(monkeypatch):
    transitions = {"cycle_a": "cycle_b", "cycle_b": "cycle_a"}
    monkeypatch.setattr(
        nexus_v4_module, "_canonical_percent_decode", lambda value: transitions.get(value)
    )
    with pytest.raises(CapabilityV4ContractError, match="cycle"):
        nexus_v4_module._validate_metadata_decoding_closure("cycle_a")


def test_metadata_accepts_only_declared_safe_keys_and_opaque_alias_not_value():
    descriptor = _descriptor(
        credential_alias="alias:catalog/account", metadata=(("data_source", "constructor_allowlist"),)
    )
    assert descriptor.credential_alias == "alias:catalog/account"
    with pytest.raises(CapabilityV4ContractError):
        _descriptor(metadata=(("random_note", "safe"),))
    with pytest.raises(CapabilityV4ContractError):
        _descriptor(metadata=(("data_source", {"token": "hidden"}),))


def test_nested_schema_secret_canaries_are_rejected():
    with pytest.raises(CapabilityV4ContractError):
        _operation(parameter_schema_json='{"properties":{"nested":{"properties":{"Password":{"type":"STRING"}}}}}')


def test_adapter_defaults_disabled_and_has_no_dispatch_or_mutation():
    adapter = LocalCatalogReadAdapterV4(
        _items(), workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
        cursor_signing_key=KEY, read_hook=lambda: None,
    )
    assert adapter.health().status is CapabilityStatusV4.DISABLED
    assert adapter.read_page(_request()).state is ReadStateV4.DENIED
    assert not hasattr(adapter, "execute") and not hasattr(adapter, "dispatch")
    with pytest.raises(CapabilityV4DeniedError):
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
    assert result.state is ReadStateV4.COMPLETED
    assert observed == [CapabilityStatusV4.AVAILABLE_READ_ONLY]


def test_same_correlation_reentry_is_denied_before_second_hook_or_reservation():
    holder = {}
    calls = []
    request = _request()

    def hook():
        calls.append(1)
        with pytest.raises(CapabilityV4DeniedError, match="reentrancy"):
            holder["adapter"].read_page(request)

    holder["adapter"] = _adapter(hook)
    assert holder["adapter"].read_page(request).state is ReadStateV4.COMPLETED
    assert len(calls) == 1 and holder["adapter"].health().quota_remaining == 99


def test_new_correlation_and_indirect_hook_reentry_are_denied_without_quota_drift():
    holder = {}
    calls = []

    def indirect():
        holder["adapter"].read_page(_request(correlation_id="corr-nested"))

    def hook():
        calls.append(1)
        with pytest.raises(CapabilityV4DeniedError, match="reentrancy"):
            indirect()

    holder["adapter"] = _adapter(hook, quota_limit=1, rate_limit=1)
    assert holder["adapter"].read_page(_request()).state is ReadStateV4.COMPLETED
    limited = holder["adapter"].read_page(_request(correlation_id="corr-after"))
    assert limited.state is ReadStateV4.RATE_LIMITED
    assert calls == [1] and holder["adapter"].health().quota_remaining == 0


def test_hook_exception_cleans_reentrancy_guard_for_later_correlation():
    calls = []

    def hook():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("fixture")

    adapter = _adapter(hook)
    assert adapter.read_page(_request()).state is ReadStateV4.UNCERTAIN
    assert adapter.read_page(_request(correlation_id="corr-002")).state is ReadStateV4.COMPLETED
    assert calls == [1, 1]


def test_reentrancy_guard_is_per_thread_and_external_hook_runs_without_lock():
    holder = {}
    calls = []
    nested_result = []

    def hook():
        calls.append(threading.get_ident())
        if len(calls) == 1:
            with ThreadPoolExecutor(max_workers=1) as pool:
                nested_result.append(pool.submit(
                    holder["adapter"].read_page, _request(correlation_id="corr-thread")
                ).result(timeout=2))

    holder["adapter"] = _adapter(hook)
    outer = holder["adapter"].read_page(_request())
    assert outer.state is ReadStateV4.COMPLETED
    assert nested_result[0].state is ReadStateV4.COMPLETED
    assert len(calls) == 2 and calls[0] != calls[1]
    assert holder["adapter"].health().quota_remaining == 98


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
        assert duplicate.state is ReadStateV4.PENDING
        release.set()
        assert future.result().state is ReadStateV4.COMPLETED
    assert len(calls) == 1 and adapter.health().quota_remaining == 99


def test_same_correlation_payload_drift_denies_without_hook_or_quota():
    calls = []
    adapter = _adapter(lambda: calls.append(1))
    adapter.read_page(_request())
    with pytest.raises(CapabilityV4DeniedError, match="drift"):
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
    assert result.state is ReadStateV4.UNCERTAIN
    assert result.failure_class is ReadFailureClassV4.HOOK_EXCEPTION
    assert "secret" not in repr(result).lower()
    assert adapter.read_page(request) == result
    assert adapter.reconcile(request) == result
    assert calls == [1] and adapter.health().quota_remaining == 99


def test_cancelled_before_hook_rolls_back_quota_and_rate_and_never_calls_hook():
    token = CancellationTokenV4()
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
    assert result.state is ReadStateV4.CANCELLED_BEFORE_HOOK
    assert adapter.health().quota_remaining == 1
    assert calls == []
    assert adapter.read_page(_request(correlation_id="corr-002")).state is ReadStateV4.COMPLETED


def test_timeout_after_hook_is_uncertain_and_not_replayed():
    now = [0.0]
    calls = []

    def hook():
        calls.append(1)
        now[0] = 2.0

    adapter = _adapter(hook, clock=lambda: now[0])
    request = _request(timeout_ms=1000)
    result = adapter.read_page(request)
    assert result.state is ReadStateV4.UNCERTAIN
    assert result.failure_class is ReadFailureClassV4.TIMEOUT
    assert adapter.read_page(request) == result and calls == [1]


@pytest.mark.parametrize(("action", "failure"), [("kill", ReadFailureClassV4.KILL), ("revoke", ReadFailureClassV4.REVOKED)])
def test_kill_and_revoke_during_hook_latch_uncertain(action, failure):
    holder = {}

    def hook():
        holder["adapter"].set_kill(True) if action == "kill" else holder["adapter"].revoke()

    holder["adapter"] = _adapter(hook, credential_alias="alias:catalog/account")
    result = holder["adapter"].read_page(_request())
    assert result.state is ReadStateV4.UNCERTAIN and result.failure_class is failure
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
        assert reconciled.state is ReadStateV4.UNCERTAIN
        assert reconciled.failure_class is ReadFailureClassV4.EXPIRED_PENDING
        release.set()
        assert future.result().state is ReadStateV4.UNCERTAIN


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
    assert adapter.read_page(first_request).state is ReadStateV4.UNCERTAIN
    with pytest.raises(CapabilityV4DeniedError, match="pending/uncertain"):
        adapter.read_page(_request(correlation_id="corr-002"))
    now[0] = 2.0
    expired = adapter.reconcile(first_request)
    assert expired.state is ReadStateV4.EXPIRED_UNCERTAIN
    assert expired.failure_class is ReadFailureClassV4.UNCERTAIN_EXPIRED
    assert adapter.read_page(first_request) == expired and calls == [1]
    assert adapter.read_page(_request(correlation_id="corr-002")).state is ReadStateV4.UNCERTAIN


def test_pending_and_uncertain_capacity_configuration_is_bounded():
    with pytest.raises(CapabilityV4ContractError):
        _adapter(ledger_capacity=2, pending_capacity=2, uncertain_capacity=1)
    with pytest.raises(CapabilityV4ContractError):
        _adapter(ledger_capacity=1, pending_capacity=1, uncertain_capacity=2)


def test_ledger_capacity_is_bounded_and_does_not_evict_for_replay():
    adapter = _adapter(ledger_capacity=1, pending_capacity=1, uncertain_capacity=1)
    request = _request()
    assert adapter.read_page(request).state is ReadStateV4.COMPLETED
    with pytest.raises(CapabilityV4DeniedError, match="capacity"):
        adapter.read_page(_request(correlation_id="corr-002"))
    assert adapter.read_page(request).state is ReadStateV4.COMPLETED


def test_profile_bound_cursor_cannot_cross_adapter_profile():
    first_adapter = _adapter()
    first = first_adapter.read_page(_request())
    assert first.next_cursor
    other = _adapter(profile_id="profile-other")
    with pytest.raises(CapabilityV4DeniedError):
        other.read_page(_request(profile_id="profile-other", correlation_id="corr-002", cursor=first.next_cursor))


def test_cursor_snapshot_and_signature_tamper_fail_closed():
    adapter = _adapter()
    cursor = adapter.read_page(_request()).next_cursor
    assert cursor
    tampered = cursor[:-1] + ("0" if cursor[-1] != "0" else "1")
    with pytest.raises(CapabilityV4DeniedError):
        adapter.read_page(_request(correlation_id="corr-002", cursor=tampered))
    changed = LocalCatalogReadAdapterV4(
        _items(6), workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
        cursor_signing_key=KEY, read_hook=lambda: None, status=CapabilityStatusV4.AVAILABLE_READ_ONLY,
        status_reason="healthy",
    )
    with pytest.raises(CapabilityV4DeniedError):
        changed.read_page(_request(correlation_id="corr-003", cursor=cursor))


def test_rate_limit_and_quota_are_reserved_once_and_truthful():
    adapter = _adapter(rate_limit=1, quota_limit=1, clock=lambda: 10.0)
    assert adapter.read_page(_request()).state is ReadStateV4.COMPLETED
    limited = adapter.read_page(_request(correlation_id="corr-002"))
    assert limited.state is ReadStateV4.RATE_LIMITED and limited.retry_after_ms == 1000
    assert adapter.read_page(_request(correlation_id="corr-002")) == limited
    assert adapter.health().quota_remaining == 0


def test_unavailable_auth_scope_disabled_degraded_and_unknown_reconcile():
    assert _adapter(auth_available=False).read_page(_request()).failure_class is ReadFailureClassV4.AUTH
    assert _adapter(granted_scopes=()).read_page(_request()).failure_class is ReadFailureClassV4.SCOPE
    assert _adapter(status=CapabilityStatusV4.DISABLED, status_reason="operator_disabled").read_page(_request()).state is ReadStateV4.DENIED
    degraded = _adapter(status=CapabilityStatusV4.DEGRADED, status_reason="partial_fixture")
    assert degraded.read_page(_request()).state is ReadStateV4.COMPLETED
    unknown = degraded.reconcile(_request(correlation_id="unknown-corr"))
    assert unknown.state is ReadStateV4.UNKNOWN_CORRELATION


def test_legacy_builder_preserves_current_32_declarations_and_policies_without_import():
    declarations = _assignment(ROOT / "main.py", "TOOL_DECLARATIONS")
    policies = _assignment(ROOT / "core" / "permission_broker.py", "MODEL_TOOL_POLICIES")
    built = build_legacy_descriptors_v4(
        declarations, policies, workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
    )
    assert len(built.descriptors) == 32
    assert {item["name"]: item for item in built.declarations()} == {item["name"]: item for item in declarations}
    assert dict(built.policy_mapping()) == policies
    assert all(item.status is CapabilityStatusV4.DISABLED for item in built.descriptors)


def test_legacy_missing_policy_and_duplicate_declaration_fail_closed():
    declarations = _assignment(ROOT / "main.py", "TOOL_DECLARATIONS")
    policies = _assignment(ROOT / "core" / "permission_broker.py", "MODEL_TOOL_POLICIES")
    policies.pop("open_app")
    with pytest.raises(CapabilityV4ContractError):
        build_legacy_descriptors_v4(
            declarations, policies, workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
        )
    with pytest.raises(CapabilityV4ContractError):
        build_legacy_descriptors_v4(
            declarations + [declarations[0]], {**policies, "open_app": "always_confirm"},
            workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
        )


def test_registry_concurrency_duplicate_kill_revoke_and_snapshot_are_safe():
    nexus = CapabilityNexusV4()
    descriptors = [_descriptor(capability_id=f"fixture.capability-{i}") for i in range(16)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(nexus.register, descriptors))
    assert len(nexus.snapshot(workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE).entries) == 16
    nexus.set_kill(True)
    assert all(
        item.projection_reason == "global_kill_active"
        for item in nexus.snapshot(workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE).entries
    )


def test_no_live_runtime_source_references_v4():
    live = [ROOT / "main.py", ROOT / "ui.py", ROOT / "scripts" / "launch_onyx.pyw"]
    live += list((ROOT / "actions").rglob("*.py")) + list((ROOT / "dashboard").rglob("*.py"))
    live += [path for path in (ROOT / "core").glob("*.py") if path.name != "capability_nexus_v4.py"]
    assert all("capability_nexus_v4" not in path.read_text(encoding="utf-8", errors="ignore") for path in live)
