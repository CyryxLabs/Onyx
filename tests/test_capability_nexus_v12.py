from __future__ import annotations

import ast
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
import hashlib
from pathlib import Path
import threading
import tempfile
from urllib.parse import quote

import pytest

from core.capability_nexus_v12 import (
    CATALOG_CONTRACT_VERSION_V12,
    LOCK_ORDER_V12,
    CancellationTokenV12,
    CapabilityDescriptorV12,
    CapabilityNexusV12,
    CapabilityProjectionV12,
    CapabilityStatusV12,
    CapabilityV12ContractError,
    CapabilityV12DeniedError,
    CatalogItemV12,
    CatalogReadRequestV12,
    LocalCatalogReadAdapterV12,
    NexusFeatureGateV12,
    OperationDescriptorV12,
    OperationKindV12,
    ReadFailureClassV12,
    ReadStateV12,
    TransportKindV12,
    build_legacy_descriptors_v12,
)
import core.capability_nexus_v12 as nexus_v12_module
import scripts.verify_phase5_capability_nexus_v12 as verifier_v12


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
V4_HASHES = {
    "core/capability_nexus_v4.py": "587040b0b4e31ddb24ad51791232af3b731e8a525a63c715f26d6dfcdb97cd7b",
    "tests/test_capability_nexus_v4.py": "51f49438f264134af7fda251158ab96c1aa35714ec4f02d5601058f9e697f0b2",
    "scripts/verify_phase5_capability_nexus_v4.py": "02aa36cbfe01428e123818685802d5e9febef995c4ea2831a0f3c83937b4e7ef",
    "scripts/check_phase5_capability_nexus_v4_whitespace.py": "891281226e2cd58f077a6ac0114eaeabf718fca7c04dc341690a362d218dd733",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V4-001.sha256": "476508f1b33497eae86b53699fcdb53ce8a5d0557c2b28a07ba9b4eff297805d",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V4-001.sha256": "3eec7517108ba2d1ad202be9bc08835703ebea24f13091c11958ca7decbcd054",
}
V5_HASHES = {
    "core/capability_nexus_v5.py": "cd3330522c275a88641884d9eb20c0448a3dd1a0b9051f3ea0a8c8983ee752f4",
    "tests/test_capability_nexus_v5.py": "f75be0cb1c9124a3fa329945de5a2b949b5598bbf9b6c181746eb5461df63e65",
    "scripts/verify_phase5_capability_nexus_v5.py": "890177d93e360726607b4e4093742bfe22cba09dbd588db251312b1129e7fc09",
    "scripts/check_phase5_capability_nexus_v5_whitespace.py": "450e54b0d7966682c4b83efc39dc44642f764201c9629e25b9e4e2a8b08ce301",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V5-001.sha256": "edc93fe63291f83e09115f4e383e1998b80f456497193bfce3654525ebf3e58d",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V5-001.sha256": "1b2868ea7f526c83651d28e50e4bd533ffd8d2f0515ffdecdd5e353a93c8527a",
}
V6_HASHES = {
    "core/capability_nexus_v6.py": "cc87b4d201ded06ad8fae44aaf295d40b279e329b981ee4e79368555fdc4f09f",
    "tests/test_capability_nexus_v6.py": "8b56668d27140eca0cdf0b2b78b1525401e388bdc67155b4fb9737793d06b312",
    "scripts/verify_phase5_capability_nexus_v6.py": "21a3c31fc1f7f18fd4e336365c499f6a81b1f6fa9929b5300b3d81ce16498ad1",
    "scripts/check_phase5_capability_nexus_v6_whitespace.py": "ca463e53b812f1fb5fec92b71c66d8e9c5c9e35e9970032b8df42eaa09be1db5",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V6-001.sha256": "76917c2516ccb000d0b5bfc351d405e365759badbfffd4c5d2b9c1599070b2d3",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V6-001.sha256": "5e356381370ce275fe2a3800f87bd144ad21cc96339040e4d6e976afb0b4e26b",
}
V7_HASHES = {
    "core/capability_nexus_v7.py": "8f2b8a7f0cfbf05712d9f4a339f4f0617dd35c20dda5dac2ba1df7bc614b4559",
    "tests/test_capability_nexus_v7.py": "e6979f4d07c032229b87aa3d27138471afc2a80b0e504a93b68be87594a7a96c",
    "scripts/verify_phase5_capability_nexus_v7.py": "19fdda417b1927c2c3ea8a9861973c2d2ec1e5e364e7b50a00c8fdbbf043c4b7",
    "scripts/check_phase5_capability_nexus_v7_whitespace.py": "e43e07f203bd871f1e9e1435e30897def2eae46614b9cef65c18de824ae8ce0f",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V7-001.sha256": "1421797efec725795d861d1d374329158e745af475e56bfde7d298863c872eca",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V7-001.sha256": "1de50b43ee4143e6de396102e080983ea0c004453db5ca70e2debbb900b78d00",
}
V8_HASHES = {
    "core/capability_nexus_v8.py": "225071341b59e4acafb0f2fa35e19175c84620b268e5d26598ca224beef20c4c",
    "tests/test_capability_nexus_v8.py": "59ee46547dbfe5b6f8790ca68b602495ddac2b3d51bab6d67193b2b0a0e441b9",
    "scripts/verify_phase5_capability_nexus_v8.py": "c630b3620e84e19d515a6d04db7040e6a4d97a0560b2529dc93ad1132735130c",
    "scripts/check_phase5_capability_nexus_v8_whitespace.py": "46506a67cf12cd9f67d5eccba62a86bbd4412f11043c38c15789ca54cee165e4",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V8-001.sha256": "8f12047f2632f61d62417201fff9fcbf0e926ffbfde11a9a760ed4b907377aaa",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V8-001.sha256": "712ddc1e02f7b57945fcf7b83238dc7efd14da809d735ab5276440867f589970",
}
V9_HASHES = {
    "core/capability_nexus_v9.py": "36c281c8dcaf522b0d52ffbdcd28a55e6145f5cc08bf8370ae206da86464c7f8",
    "tests/test_capability_nexus_v9.py": "3111f403eff79d911547cd54675502b148958926a44732f58749c33102f3de0c",
    "scripts/verify_phase5_capability_nexus_v9.py": "28d279c6c86811df3b0d0ff5c8c5824eb1391335f78bbc95ffca43a43de474f6",
    "scripts/check_phase5_capability_nexus_v9_whitespace.py": "99af22dd17ce948f5937a13e9c070a70f569dc80552ec78b7efdf452e94c97af",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V9-001.sha256": "d55419e2841634f91a1c71b5f70ade61b17dac2d3799da8d757252decb94e4f9",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V9-001.sha256": "018e5bfde1f749bcba64ad0520dabc83460c62fced34f326dfe603f066547c8f",
}
V10_HASHES = {
    "core/capability_nexus_v10.py": "74401ce43f11d544b2b6059c101702386e0e0bfec9fd2fd517f030cf21e699c0",
    "tests/test_capability_nexus_v10.py": "be8197b10b095aaaafb5e58d9daab9f60dec15155fcb1359662dae4f819b458d",
    "scripts/verify_phase5_capability_nexus_v10.py": "3241ad5ae3a2919d1642c2dd0ecc8ee85fd0a7e26be813ac44b461408121a873",
    "scripts/check_phase5_capability_nexus_v10_whitespace.py": "0903471515fb3f14827b7c7bb3d67ec0e68bd8341fa51ec5d4d966014eadb578",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V10-001.sha256": "48b962b42c9705b4bc2ea376a50617f791b72d53fe5335ec9f58420280aae293",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V10-001.sha256": "2f8f37b4dd94cb217cfea35f6c236454342e9864cef1972cc94ad3d2992351a1",
}
V11_HASHES = {
    "core/capability_nexus_v11.py": "c3b43708c10f28e23f03ef15a5dd3cbd7c8315c45beb22314be75e0ce7e7f5c1",
    "tests/test_capability_nexus_v11.py": "817e8db14f480bbb35b543f9587552205e4ba2a6ba1bf2611b8566aef008f029",
    "scripts/verify_phase5_capability_nexus_v11.py": "01f9bb77c358e3bee1c8e357c214e572b55e134e40ace54367c939bf245d795c",
    "scripts/check_phase5_capability_nexus_v11_whitespace.py": "aa3c2b969cce11bf35406e07e7cfe488de7dcdaca7e6618b2c684d73396153b8",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V11-001.sha256": "472b6a1ae970cb4d2bd5ac7228f5d6716509aa9220f4f04218e30444ea9452f1",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V11-001.sha256": "46238e447361e320b1d46ef92b40d717ca91abcc238d7e35b0f83df957db2419",
}


def _assignment(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(item, ast.Name) and item.id == name for item in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(name)


def _operation(**changes) -> OperationDescriptorV12:
    values = {
        "operation_id": "catalog_read", "kind": OperationKindV12.READ,
        "description": "Read allowlisted metadata.",
        "parameter_schema_json": '{"properties":{},"type":"OBJECT"}',
        "required_scopes": ("catalog.metadata.read",), "data_classes": ("allowlisted_metadata",),
        "risk_class": "low", "approval_class": "host_policy_required",
        "allowed_targets": ("local_catalog",),
    }
    values.update(changes)
    return OperationDescriptorV12(**values)


def _descriptor(**changes) -> CapabilityDescriptorV12:
    values = {
        "capability_id": "local.catalog", "capability_version": "v12", "provider": "onyx_local",
        "transport": TransportKindV12.LOCAL, "api_name": "local_catalog",
        "api_version": CATALOG_CONTRACT_VERSION_V12, "workspace_id": WORKSPACE,
        "account_id": ACCOUNT, "profile_id": PROFILE, "credential_alias": None,
        "operations": (_operation(),), "status": CapabilityStatusV12.DISABLED,
        "status_reason": "candidate_not_activated", "limitations": ("no_dispatch",),
    }
    values.update(changes)
    return CapabilityDescriptorV12(**values)


def _items(count: int = 5) -> tuple[CatalogItemV12, ...]:
    return tuple(CatalogItemV12(f"item-{i:02d}", f"Item {i}", "fixture", "v12", ("safe",)) for i in range(count))


def _adapter(hook=lambda: None, **changes) -> LocalCatalogReadAdapterV12:
    values = {
        "items": _items(), "workspace_id": WORKSPACE, "account_id": ACCOUNT,
        "profile_id": PROFILE, "cursor_signing_key": KEY, "read_hook": hook,
        "status": CapabilityStatusV12.AVAILABLE_READ_ONLY, "status_reason": "healthy",
    }
    values.update(changes)
    return LocalCatalogReadAdapterV12(**values)


def _request(**changes) -> CatalogReadRequestV12:
    values = {
        "workspace_id": WORKSPACE, "account_id": ACCOUNT, "profile_id": PROFILE,
        "target": "local_catalog", "correlation_id": "corr-001", "page_size": 2,
    }
    values.update(changes)
    return CatalogReadRequestV12(**values)


def test_v1_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V1_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v2_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V2_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v3_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V3_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v4_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V4_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v5_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V5_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v6_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V6_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v7_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V7_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v8_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V8_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v9_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V9_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v10_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V10_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v11_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V11_HASHES.items():
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
    nexus = CapabilityNexusV12()
    descriptor = _descriptor()
    nexus.register(descriptor)
    with pytest.raises(TypeError):
        nexus.discover(
            descriptor.capability_id, workspace_id=WORKSPACE, account_id=ACCOUNT,
            expected_version="v12", expected_digest=descriptor.digest,
        )
    for profile in ("profile-other", "PROFILE-alpha"):
        with pytest.raises(CapabilityV12DeniedError):
            nexus.discover(
                descriptor.capability_id, workspace_id=WORKSPACE, account_id=ACCOUNT,
                profile_id=profile, expected_version="v12", expected_digest=descriptor.digest,
            )


def test_snapshot_is_profile_bound_and_digest_changes_by_profile():
    nexus = CapabilityNexusV12()
    nexus.register(_descriptor())
    first = nexus.snapshot(workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE)
    other = nexus.snapshot(workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id="profile-other")
    assert len(first.entries) == 1 and other.entries == ()
    assert first.snapshot_digest != other.snapshot_digest
    with pytest.raises(FrozenInstanceError):
        first.profile_id = "changed"  # type: ignore[misc]


def test_projection_constructor_rejects_cross_profile_and_authority():
    descriptor = _descriptor()
    with pytest.raises(CapabilityV12ContractError):
        CapabilityProjectionV12(
            descriptor, descriptor.digest, WORKSPACE, ACCOUNT, "profile-other",
            CapabilityStatusV12.DISABLED, "disabled",
        )
    with pytest.raises(CapabilityV12ContractError):
        CapabilityProjectionV12(
            descriptor, descriptor.digest, WORKSPACE, ACCOUNT, PROFILE,
            CapabilityStatusV12.DISABLED, "disabled", authority_granted=True,
        )


class _GateSubclass(NexusFeatureGateV12):
    pass


class _FakeGate:
    nexus_enabled = False
    shadow_mode = True
    dispatch_enabled = False


@pytest.mark.parametrize("gate", [_GateSubclass(), _FakeGate(), object()])
def test_registry_rejects_gate_subclasses_fakes_and_duck_types(gate):
    with pytest.raises(CapabilityV12ContractError, match="exact concrete"):
        CapabilityNexusV12(gate)  # type: ignore[arg-type]


def test_exact_gate_is_frozen_default_off_and_lock_order_is_declared():
    gate = NexusFeatureGateV12()
    nexus = CapabilityNexusV12(gate)
    assert nexus.gate is gate and nexus.lock_order == LOCK_ORDER_V12
    with pytest.raises(FrozenInstanceError):
        gate.shadow_mode = False  # type: ignore[misc]
    for values in ({"nexus_enabled": True}, {"shadow_mode": False}, {"dispatch_enabled": True}):
        with pytest.raises(CapabilityV12ContractError):
            NexusFeatureGateV12(**values)


@pytest.mark.parametrize(
    "key",
    ["api_key", "Api-Key", "TOKEN", "pass.word", "Secret", "authorization", "cookie", "private-key", "%61pi_key"],
)
def test_metadata_rejects_secret_names_and_normalization_bypasses(key):
    with pytest.raises(CapabilityV12ContractError):
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
    with pytest.raises(CapabilityV12ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize("layers", [2, 3])
def test_metadata_rejects_double_and_triple_percent_secret(layers):
    with pytest.raises(CapabilityV12ContractError):
        _descriptor(metadata=(("data_source", _percent_layers("token=abcd1234", layers)),))


@pytest.mark.parametrize("layers", [2, 3])
def test_metadata_rejects_double_and_triple_base64_secret(layers):
    with pytest.raises(CapabilityV12ContractError):
        _descriptor(metadata=(("data_source", _base64_layers("api_key=abcd1234", layers)),))


def test_metadata_rejects_mixed_percent_base64_secret():
    encoded = _percent_layers(_base64_layers("password=abcd1234", 2), 2)
    with pytest.raises(CapabilityV12ContractError):
        _descriptor(metadata=(("data_source", encoded),))


@pytest.mark.parametrize("unpadded", [False, True])
def test_metadata_rejects_urlsafe_padded_and_unpadded_secret(unpadded):
    encoded = _base64_layers("authorization=Bearer1234", 2, urlsafe=True, unpadded=unpadded)
    with pytest.raises(CapabilityV12ContractError):
        _descriptor(metadata=(("data_source", encoded),))


@pytest.mark.parametrize(
    "value",
    ["ＴＯＫＥＮ＝abcd1234", "ToKeN=abcd1234", "to\u200bken=abcd1234", "token\x00=abcd1234"],
)
def test_metadata_rejects_case_unicode_and_control_canaries(value):
    with pytest.raises(CapabilityV12ContractError):
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
        "github_pat_" + "K" * 30,
        "xoxb-" + "1234567890-abcdefghijklmnop",
        "npm_" + "L" * 36,
        "SG." + "M" * 22 + "." + "N" * 43,
        "SK" + "a1" * 16,
        "Ab3_defGHIjklMNopQRstuVWxyz0123456789-_aBCDefGhijkLmnop",
    ],
)
def test_metadata_rejects_bounded_raw_credential_families(value):
    with pytest.raises(CapabilityV12ContractError, match="secret"):
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
        "sk-documentation-reference-2026",
        "github_pat_example",
        "xoxb-documentation",
        "npm_short",
        "SG.example.reference",
        "SK" + "a" * 31,
        "BuildArtifact_2026-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890",
        "Aa1" * 10 + "A",
    ],
)
def test_metadata_raw_credential_near_misses_remain_valid(value):
    assert dict(_descriptor(metadata=(("data_source", value),)).metadata)["data_source"] == value


@pytest.mark.parametrize(
    "value",
    [
        "Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8St1Uv3Wx5",
        "Aa1Bb2Cc3Dd4Ee5Ff6Gg7Hh8Ii9Jj0Kk1Ll2Mm3Nn4Oo5Pp6Qq7Rr8Ss9Tt0Uu1",
    ],
)
def test_metadata_rejects_compact_opaque_tokens_at_32_and_64_plus(value):
    with pytest.raises(CapabilityV12ContractError, match="secret"):
        _descriptor(metadata=(("data_source", value),))


def test_hashes_are_allowed_only_in_explicit_typed_hash_field():
    digest = "0123456789abcdef" * 4
    assert dict(_descriptor(metadata=(("declaration_sha256", digest),)).metadata)["declaration_sha256"] == digest
    with pytest.raises(CapabilityV12ContractError, match="secret"):
        _descriptor(metadata=(("data_source", digest),))


@pytest.mark.parametrize(
    "prefix",
    ["token", "secret", "password", "auth", "api_key", "TOKEN", "tоken", "tᴏken", "credential"],
)
def test_opaque_semantic_exemption_never_allows_protected_prefixes(prefix):
    value = prefix + "_" + "Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8St1Uv3Wx5"
    with pytest.raises(CapabilityV12ContractError, match="secret"):
        _descriptor(metadata=(("data_source", value),))


def test_protected_opaque_prefixes_are_rejected_after_encoding_layers():
    value = "api_key_" + "Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8St1Uv3Wx5"
    for encoded in (_percent_layers(value, 2), _base64_layers(value, 2)):
        with pytest.raises(CapabilityV12ContractError):
            _descriptor(metadata=(("data_source", encoded),))


def test_unknown_prefix_with_opaque_tail_is_rejected():
    with pytest.raises(CapabilityV12ContractError):
        _descriptor(metadata=(("data_source", "unknown_Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8St1Uv3Wx5"),))


@pytest.mark.parametrize(
    "value",
    [
        "BuildArtifact_2026-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890",
        "documentation_2026-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890",
        "reference_2026-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890",
        "release_2026-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890",
    ],
)
def test_explicit_safe_semantic_prefixes_preserve_wordlike_identifiers(value):
    assert dict(_descriptor(metadata=(("data_source", value),)).metadata)["data_source"] == value


def test_protected_prefix_tail_boundary_is_bounded():
    for size in (16, 25, 26):
        with pytest.raises(CapabilityV12ContractError):
            _descriptor(metadata=(("data_source", "token_" + "A" * size),))


@pytest.mark.parametrize("prefix", sorted(nexus_v12_module._SECRET_NAMES))
def test_every_canonical_secret_name_rejects_compact_opaque_suffix(prefix):
    with pytest.raises(CapabilityV12ContractError):
        _descriptor(metadata=(("data_source", prefix + "_" + "Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8St1Uv3Wx5"),))


@pytest.mark.parametrize(
    "prefix",
    ["access_token", "refresh_token", "ACCESS_TOKEN", "Refresh_Token", "access_tоken", "refresh_tᴏken"],
)
def test_access_and_refresh_token_prefix_spans_reject_case_and_confusables(prefix):
    value = prefix + "_" + "Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8St1Uv3Wx5"
    with pytest.raises(CapabilityV12ContractError):
        _descriptor(metadata=(("data_source", value),))


def test_access_refresh_prefixes_reject_after_percent_and_base64_layers():
    for prefix in ("access_token", "refresh_token"):
        value = prefix + "_" + "Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8St1Uv3Wx5"
        for encoded in (_percent_layers(value, 2), _base64_layers(value, 2)):
            with pytest.raises(CapabilityV12ContractError):
                _descriptor(metadata=(("data_source", encoded),))


def test_multi_segment_secret_prefix_and_31_32_total_boundaries():
    for size in (16, 18, 19):
        with pytest.raises(CapabilityV12ContractError):
            _descriptor(metadata=(("data_source", "access_token_" + "A" * size),))


@pytest.mark.parametrize("name", sorted(nexus_v12_module._SECRET_NAMES))
@pytest.mark.parametrize("position", ["leading", "middle", "trailing"])
def test_every_secret_name_is_rejected_at_every_span_position(name, position):
    opaque = "Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8"
    values = {
        "leading": f"__{name}__{opaque}",
        "middle": f"source__{name}__{opaque}",
        "trailing": f"{opaque}__{name}__",
    }
    with pytest.raises(CapabilityV12ContractError):
        _descriptor(metadata=(("data_source", values[position]),))


@pytest.mark.parametrize(
    "value",
    [
        "token" + "A" * 40,
        "source_token_" + "A" * 20,
        "documentation_access_token_" + "A" * 20,
        "source__token__" + "A" * 20,
        "___token___" + "A" * 20,
    ],
)
def test_protected_names_ignore_namespace_and_separator_bypasses(value):
    with pytest.raises(CapabilityV12ContractError):
        _descriptor(metadata=(("data_source", value),))


def test_short_protected_names_reject_after_base64_layers():
    for value in ("token_" + "A" * 16, "access_token_" + "A" * 16):
        with pytest.raises(CapabilityV12ContractError):
            _descriptor(metadata=(("data_source", _base64_layers(value, 2)),))


@pytest.mark.parametrize(
    "value",
    ["tokenization", "authentication", "source_documentation", "reference_identifier", "documentation_reference_2026"],
)
def test_wordlike_non_secret_identifiers_remain_valid(value):
    assert dict(_descriptor(metadata=(("data_source", value),)).metadata)["data_source"] == value


@pytest.mark.parametrize(
    "value",
    [
        "sourceToken" + "A" * 20,
        "sourceAccessToken" + "A" * 20,
        "sourceApiKey" + "A" * 20,
        "sourceCredential" + "A" * 20,
        "A" * 20 + "TokenSource",
        "prefixTokenMiddle" + "A" * 20,
        "prefixAccessTokenMiddle" + "A" * 20,
        "prefixApiKeyMiddle" + "A" * 20,
        "prefixCredentialMiddle" + "A" * 20,
        "sourcetoken" + "a" * 20,
        "sourceaccesstoken" + "a" * 20,
        "sourceapikey" + "a" * 20,
        "sourcecredential" + "a" * 20,
    ],
)
def test_camel_pascal_and_case_free_protected_names_reject_at_any_offset(value):
    with pytest.raises(CapabilityV12ContractError, match="secret"):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize("separator", ["_", "-", ".", "/", " ", "__", "--", "..", "//", " \t "])
@pytest.mark.parametrize("name", ["token", "access_token", "api_key", "credential"])
def test_mixed_repeated_namespace_separators_cannot_hide_protected_names(separator, name):
    rendered_name = separator.join(name.split("_"))
    value = separator.join(("source", rendered_name, "A" * 20))
    with pytest.raises(CapabilityV12ContractError, match="secret"):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize("name", sorted(nexus_v12_module._SECRET_NAMES | nexus_v12_module._CREDENTIAL_OPAQUE_NAMES))
@pytest.mark.parametrize("position", ["leading", "middle", "trailing"])
def test_every_canonical_protected_table_name_rejects_at_every_position(name, position):
    opaque = "Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8"
    values = {
        "leading": f"..{name}//{opaque}",
        "middle": f"source/{name}..{opaque}",
        "trailing": f"{opaque}  {name}/source",
    }
    with pytest.raises(CapabilityV12ContractError, match="secret"):
        _descriptor(metadata=(("data_source", values[position]),))


@pytest.mark.parametrize("layers", [1, 2, 3])
@pytest.mark.parametrize(
    "value",
    [
        "sourceTоken" + "A" * 20,
        "sourceAccesѕToken" + "A" * 20,
        "sourceApiKεy" + "A" * 20,
        "sourceCredеntial" + "A" * 20,
    ],
)
def test_camel_confusable_bypasses_reject_after_every_base64_layer(value, layers):
    with pytest.raises(CapabilityV12ContractError, match="secret"):
        _descriptor(metadata=(("data_source", _base64_layers(value, layers)),))


@pytest.mark.parametrize(
    "value",
    [
        "tokenization",
        "authentication",
        "source.tokenization.reference",
        "source/authentication/reference",
        "TokenizationReference",
        "AuthenticationReference",
    ],
)
def test_benign_wordlike_identifiers_remain_valid_across_namespace_and_camel_forms(value):
    assert dict(_descriptor(metadata=(("data_source", value),)).metadata)["data_source"] == value


@pytest.mark.parametrize(
    "tail",
    [
        ("abcd", "efgh", "ijkl", "mnop"),
        ("ab12", "cd34", "ef56", "gh78"),
        ("abcdef", "ghijkl", "mnop"),
        ("abcdefgh", "ijklmnop"),
    ],
)
@pytest.mark.parametrize("separator", ["_", "-", ".", "/", " ", "__", ".//.", "_ / "])
@pytest.mark.parametrize("name", ["token", "access_token", "auth", "api_key", "credential"])
def test_generated_chunked_opaque_tails_reject_across_namespaces(name, separator, tail):
    rendered_name = separator.join(name.split("_"))
    value = separator.join(("namespace", rendered_name, *tail))
    with pytest.raises(CapabilityV12ContractError, match="secret"):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize("name", sorted(nexus_v12_module._SECRET_NAMES | nexus_v12_module._CREDENTIAL_OPAQUE_NAMES))
@pytest.mark.parametrize("position", ["leading", "middle", "trailing"])
def test_every_protected_name_rejects_chunked_tail_at_every_generated_position(name, position):
    chunks = ("ab12", "cd34", "ef56", "gh78")
    values = {
        "leading": ".".join((name, *chunks, "namespace")),
        "middle": "/".join(("namespace", name, *chunks)),
        "trailing": "_".join((*chunks, name, "namespace")),
    }
    with pytest.raises(CapabilityV12ContractError, match="secret"):
        _descriptor(metadata=(("data_source", values[position]),))


@pytest.mark.parametrize("layers", [1, 2, 3])
@pytest.mark.parametrize(
    "value",
    [
        "namespace.tоken.abcd.efgh.ijkl.mnop",
        "namespace.access.tоken.ab12.cd34.ef56.gh78",
        "namespace.аuth.abcdef.ghijkl.mnop",
        "namespace.credеntial.abcdefgh.ijklmnop",
    ],
)
def test_chunked_confusable_credentials_reject_after_base64_layers(value, layers):
    with pytest.raises(CapabilityV12ContractError, match="secret"):
        _descriptor(metadata=(("data_source", _base64_layers(value, layers)),))


@pytest.mark.parametrize("layers", [1, 2, 3])
def test_chunked_credentials_reject_after_percent_layers(layers):
    value = "access token abcd efgh ijkl mnop"
    with pytest.raises(CapabilityV12ContractError, match="secret"):
        _descriptor(metadata=(("data_source", _percent_layers(value, layers)),))


@pytest.mark.parametrize("safe", ["tokenization", "authentication"])
@pytest.mark.parametrize("position", ["prefix", "suffix"])
@pytest.mark.parametrize("opaque", ["A" * 20, "abcd_efgh_ijkl_mnop", "ab12.cd34.ef56.gh78"])
def test_benign_word_exemption_never_hides_appended_or_prepended_opaque_material(safe, position, opaque):
    value = safe + opaque if position == "prefix" else opaque + safe
    with pytest.raises(CapabilityV12ContractError, match="secret"):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    ("protected_phrase", "natural_word"),
    [
        ("authorization", "interoperability"),
        ("token", "characterization"),
        ("auth", "internationalization"),
        ("access token", "standardization"),
        ("authorization", "collaboration"),
        ("token", "configuration"),
        ("auth", "identification"),
        ("access token", "documentation"),
    ],
)
@pytest.mark.parametrize("form", ["space", "camel", "namespace"])
def test_generated_natural_language_words_are_not_opaque_credentials(protected_phrase, natural_word, form):
    words = protected_phrase.split()
    if form == "space":
        value = " ".join((*words, natural_word))
    elif form == "camel":
        value = words[0].title() + "".join(word.title() for word in (*words[1:], natural_word))
    else:
        value = ".".join((*words, natural_word))
    assert dict(_descriptor(metadata=(("data_source", value),)).metadata)["data_source"] == value


@pytest.mark.parametrize(
    "value",
    [
        "auth access control policies",
        "auth_access_control_policies",
        "authorization interoperability standards",
        "token characterization reference",
        "access token interoperability policy",
    ],
)
def test_multiword_benign_prose_is_not_aggregated_as_an_opaque_tail(value):
    assert dict(_descriptor(metadata=(("data_source", value),)).metadata)["data_source"] == value


@pytest.mark.parametrize("split", range(1, 16))
@pytest.mark.parametrize("delimiter", ["|", ",", "@", ":", ";", "!", "?", "+", "=", "~", "•", "—", "、", "§", "→"])
def test_every_two_chunk_partition_at_threshold_rejects_across_unicode_delimiters(split, delimiter):
    opaque = "z9x8c7v6b5n4m3q2"
    value = delimiter.join(("namespace", "token", opaque[:split], opaque[split:]))
    with pytest.raises(CapabilityV12ContractError, match="secret"):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize("split", range(1, 16))
@pytest.mark.parametrize(
    "opaque",
    ["z9x8c7v6b5n4m3q2", "bcdfghjklmnpqrst", "aaaaaaaaaaaaaaaa", "Ab3Cd5Ef7Gh9Jk2L"],
)
def test_generated_opaque_families_reject_independent_of_partition_size(split, opaque):
    value = "namespace|auth|" + opaque[:split] + "@" + opaque[split:]
    with pytest.raises(CapabilityV12ContractError, match="secret"):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize("name", sorted(nexus_v12_module._SECRET_NAMES | nexus_v12_module._CREDENTIAL_OPAQUE_NAMES))
@pytest.mark.parametrize("position", ["leading", "middle", "trailing"])
@pytest.mark.parametrize("delimiter", ["|", ",", "@", "•", "—", "、", "→"])
def test_all_canonical_names_reject_at_all_positions_across_punctuation_categories(name, position, delimiter):
    chunks = ("z9x8c7v6b5n4m", "3q2")
    values = {
        "leading": delimiter.join((name, *chunks, "namespace")),
        "middle": delimiter.join(("namespace", name, *chunks)),
        "trailing": delimiter.join((*chunks, name, "namespace")),
    }
    with pytest.raises(CapabilityV12ContractError, match="secret"):
        _descriptor(metadata=(("data_source", values[position]),))


@pytest.mark.parametrize("layers", [1, 2, 3])
@pytest.mark.parametrize("encoding", ["base64", "percent"])
@pytest.mark.parametrize(
    "value",
    [
        "namespace|tоken|z9x8c7v6b5n4m|3q2",
        "namespace,access,tоken,z9x8c7v6b5n4m,3q2",
        "namespace@аuth@z9x8c7v6b5n4m@3q2",
        "namespace•credеntial•z9x8c7v6b5n4m•3q2",
    ],
)
def test_unicode_delimiter_confusables_reject_after_every_encoding_layer(value, encoding, layers):
    encoded = _base64_layers(value, layers) if encoding == "base64" else _percent_layers(value, layers)
    with pytest.raises(CapabilityV12ContractError, match="secret"):
        _descriptor(metadata=(("data_source", encoded),))


@pytest.mark.parametrize("safe", ["tokenization", "authentication"])
@pytest.mark.parametrize("delimiter", ["|", ",", "@", "•", "—", "、", "→"])
def test_exact_safe_word_boundaries_survive_arbitrary_unicode_punctuation(safe, delimiter):
    value = delimiter.join(("namespace", safe, "responsibilities"))
    assert dict(_descriptor(metadata=(("data_source", value),)).metadata)["data_source"] == value


@pytest.mark.parametrize("safe", ["tokenization", "authentication"])
@pytest.mark.parametrize("delimiter", ["|", ",", "@", "•", "—", "、", "→"])
@pytest.mark.parametrize("split", [1, 3, 8, 13, 15])
def test_safe_words_never_exempt_partitioned_opaque_material(safe, delimiter, split):
    opaque = "z9x8c7v6b5n4m3q2"
    value = delimiter.join((safe, opaque[:split], opaque[split:]))
    with pytest.raises(CapabilityV12ContractError, match="secret"):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    ("protected_phrase", "natural_word"),
    [
        ("authorization", "responsibilities"),
        ("token", "telecommunications"),
        ("auth", "microarchitecture"),
        ("access token", "multidisciplinary"),
        ("authorization", "interoperability"),
        ("token", "characterization"),
        ("auth", "internationalization"),
        ("access token", "standardization"),
        ("authorization", "collaboration"),
        ("token", "configuration"),
        ("auth", "identification"),
        ("access token", "documentation"),
        ("authorization", "observability"),
        ("token", "extensibility"),
        ("auth", "portability"),
        ("access token", "maintainability"),
        ("authorization", "governance"),
    ],
)
@pytest.mark.parametrize("form", ["space", "camel", "pascal", "punctuation"])
def test_broad_generated_natural_technical_families_remain_valid(protected_phrase, natural_word, form):
    words = protected_phrase.split()
    if form == "space":
        value = " ".join((*words, natural_word))
    elif form == "camel":
        value = words[0] + "".join(word.title() for word in (*words[1:], natural_word))
    elif form == "pascal":
        value = "".join(word.title() for word in (*words, natural_word))
    else:
        value = "|".join((*words, natural_word))
    assert dict(_descriptor(metadata=(("data_source", value),)).metadata)["data_source"] == value


@pytest.mark.parametrize(
    "value",
    [
        "authorization responsibilities for distributed systems",
        "token telecommunications standards and governance",
        "auth microarchitecture documentation reference",
        "access token multidisciplinary policy review",
        "AuthorizationResponsibilities",
        "TokenTelecommunications",
        "AuthMicroarchitecture",
        "AccessTokenMultidisciplinary",
    ],
)
def test_natural_technical_sentences_and_camel_compounds_are_not_opaque(value):
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
    with pytest.raises(CapabilityV12ContractError):
        _descriptor(metadata=(("data_source", value),))


def test_metadata_confusables_are_scanned_after_mixed_decoding_layers():
    encoded = _percent_layers(_base64_layers("tоken=abcd1234", 2), 2)
    with pytest.raises(CapabilityV12ContractError):
        _descriptor(metadata=(("data_source", encoded),))


@pytest.mark.parametrize("value", ["token\u202e=abcd1234", "to\u0338ken=abcd1234"])
def test_metadata_rejects_bidi_and_combining_tricks(value):
    with pytest.raises(CapabilityV12ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "value",
    [
        "Status: operação concluída em 東京",
        "Описание: deployment concluído",
        "Δεδομένα: relatório final готов",
    ],
)
def test_metadata_allows_benign_mixed_script_human_descriptions_with_colon(value):
    assert dict(_descriptor(metadata=(("data_source", value),)).metadata)["data_source"] == value


@pytest.mark.parametrize("value", ['{"tоken":"abcd1234"}', "passwᴏrd:abcd1234", "аuth=abcd1234"])
def test_metadata_rejects_confusable_secret_assignments_and_json_fragments(value):
    with pytest.raises(CapabilityV12ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize("value", ["東京カタログ", "каталогданных", "Δεδομένα"])
def test_metadata_preserves_benign_unstructured_international_display(value):
    assert dict(_descriptor(metadata=(("data_source", value),)).metadata)["data_source"] == value


@pytest.mark.parametrize("field", ["tᴏken", "tօken", "passwᴏrd", "арі_кеу"])
def test_schema_rejects_non_ascii_and_confusable_structured_field_keys(field):
    schema = '{"properties":{"' + field + '":{"type":"STRING"}},"type":"OBJECT"}'
    with pytest.raises(CapabilityV12ContractError):
        _operation(parameter_schema_json=schema)


@pytest.mark.parametrize(
    "value",
    ["ghp_" + "A" * 30, "AKIA" + "B" * 16, "sk_test_" + "C" * 24],
)
def test_schema_rejects_raw_credentials_in_nested_defaults_examples_and_descriptions(value):
    for field in ("default", "example", "description"):
        schema = {
            "properties": {"safe_field": {field: value, "type": "STRING"}},
            "type": "OBJECT",
        }
        encoded = nexus_v12_module.json.dumps(schema, sort_keys=True, separators=(",", ":"))
        with pytest.raises(CapabilityV12ContractError):
            _operation(parameter_schema_json=encoded)


def test_recursive_schema_cycle_depth_node_and_scalar_budgets_fail_closed():
    cycle = {}
    cycle["safe"] = cycle
    with pytest.raises(CapabilityV12ContractError, match="cycle"):
        nexus_v12_module._reject_json_secrets(cycle, "fixture")
    deep = current = {}
    for index in range(26):
        current["safe"] = {}
        current = current["safe"]
    with pytest.raises(CapabilityV12ContractError, match="depth"):
        nexus_v12_module._reject_json_secrets(deep, "fixture")
    with pytest.raises(CapabilityV12ContractError, match="node"):
        nexus_v12_module._reject_json_secrets(0, "fixture", _budget=[4096, 0])
    with pytest.raises(CapabilityV12ContractError, match="scalar byte"):
        nexus_v12_module._reject_json_secrets(["a" * 4096] * 17, "fixture")


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
        with pytest.raises(CapabilityV12ContractError):
            _descriptor(metadata=(("data_source", value),))


def test_metadata_rejects_depth_and_expansion_bombs():
    too_deep = _base64_layers("token=abcd1234", 8)
    with pytest.raises(CapabilityV12ContractError, match="depth"):
        _descriptor(metadata=(("data_source", too_deep),))
    expansion = "\ufdfa" * 500
    with pytest.raises(CapabilityV12ContractError, match="expansion"):
        _descriptor(metadata=(("data_source", expansion),))


def test_metadata_cycle_detection_fails_closed(monkeypatch):
    transitions = {"cycle_a": "cycle_b", "cycle_b": "cycle_a"}
    monkeypatch.setattr(
        nexus_v12_module, "_canonical_percent_decode", lambda value: transitions.get(value)
    )
    with pytest.raises(CapabilityV12ContractError, match="cycle"):
        nexus_v12_module._validate_metadata_decoding_closure("cycle_a")


def test_metadata_accepts_only_declared_safe_keys_and_opaque_alias_not_value():
    descriptor = _descriptor(
        credential_alias="alias:catalog/account", metadata=(("data_source", "constructor_allowlist"),)
    )
    assert descriptor.credential_alias == "alias:catalog/account"
    with pytest.raises(CapabilityV12ContractError):
        _descriptor(metadata=(("random_note", "safe"),))
    with pytest.raises(CapabilityV12ContractError):
        _descriptor(metadata=(("data_source", {"token": "hidden"}),))


def test_nested_schema_secret_canaries_are_rejected():
    with pytest.raises(CapabilityV12ContractError):
        _operation(parameter_schema_json='{"properties":{"nested":{"properties":{"Password":{"type":"STRING"}}}}}')


def test_adapter_defaults_disabled_and_has_no_dispatch_or_mutation():
    adapter = LocalCatalogReadAdapterV12(
        _items(), workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
        cursor_signing_key=KEY, read_hook=lambda: None,
    )
    assert adapter.health().status is CapabilityStatusV12.DISABLED
    assert adapter.read_page(_request()).state is ReadStateV12.DENIED
    assert not hasattr(adapter, "execute") and not hasattr(adapter, "dispatch")
    with pytest.raises(CapabilityV12DeniedError):
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
    assert result.state is ReadStateV12.COMPLETED
    assert observed == [CapabilityStatusV12.AVAILABLE_READ_ONLY]


def test_same_correlation_reentry_is_denied_before_second_hook_or_reservation():
    holder = {}
    calls = []
    request = _request()

    def hook():
        calls.append(1)
        with pytest.raises(CapabilityV12DeniedError, match="reentrancy"):
            holder["adapter"].read_page(request)

    holder["adapter"] = _adapter(hook)
    assert holder["adapter"].read_page(request).state is ReadStateV12.COMPLETED
    assert len(calls) == 1 and holder["adapter"].health().quota_remaining == 99


def test_new_correlation_and_indirect_hook_reentry_are_denied_without_quota_drift():
    holder = {}
    calls = []

    def indirect():
        holder["adapter"].read_page(_request(correlation_id="corr-nested"))

    def hook():
        calls.append(1)
        with pytest.raises(CapabilityV12DeniedError, match="reentrancy"):
            indirect()

    holder["adapter"] = _adapter(hook, quota_limit=1, rate_limit=1)
    assert holder["adapter"].read_page(_request()).state is ReadStateV12.COMPLETED
    limited = holder["adapter"].read_page(_request(correlation_id="corr-after"))
    assert limited.state is ReadStateV12.RATE_LIMITED
    assert calls == [1] and holder["adapter"].health().quota_remaining == 0


def test_hook_exception_cleans_reentrancy_guard_for_later_correlation():
    calls = []

    def hook():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("fixture")

    adapter = _adapter(hook)
    assert adapter.read_page(_request()).state is ReadStateV12.UNCERTAIN
    assert adapter.read_page(_request(correlation_id="corr-002")).state is ReadStateV12.COMPLETED
    assert calls == [1, 1]


def test_reentrancy_guard_rejects_hook_spawned_thread_before_reservation():
    holder = {}
    calls = []
    nested_errors = []

    def hook():
        calls.append(threading.get_ident())
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(holder["adapter"].read_page, _request(correlation_id="corr-thread"))
            try:
                future.result(timeout=2)
            except CapabilityV12DeniedError as exc:
                nested_errors.append(str(exc))

    holder["adapter"] = _adapter(hook)
    outer = holder["adapter"].read_page(_request())
    assert outer.state is ReadStateV12.COMPLETED
    assert nested_errors == ["catalog read reentrancy is denied"]
    assert len(calls) == 1 and holder["adapter"].health().quota_remaining == 99
    assert holder["adapter"].read_page(_request(correlation_id="corr-after")).state is ReadStateV12.COMPLETED


def test_hook_guard_is_per_adapter_and_does_not_hold_lock_during_callback():
    second = _adapter()
    observed = []
    first = _adapter(lambda: observed.append(second.read_page(_request()).state))
    assert first.read_page(_request()).state is ReadStateV12.COMPLETED
    assert observed == [ReadStateV12.COMPLETED]


def test_historical_leaf_budget_exact_boundary_and_overflow():
    leaves = {f"leaf-{index}": "a" * 64 for index in range(4095)}
    verifier_v12._record_historical_leaf(leaves, "boundary", "b" * 64)
    assert len(leaves) == 4096
    with pytest.raises(verifier_v12.V12EvidenceError, match="leaf budget"):
        verifier_v12._record_historical_leaf(leaves, "overflow", "c" * 64)
    with pytest.raises(verifier_v12.V12EvidenceError, match="digest conflict"):
        verifier_v12._record_historical_leaf(leaves, "boundary", "d" * 64)


def test_wide_historical_manifest_and_cycle_fail_before_expansion(monkeypatch):
    wide = tuple(("a" * 64, f"leaf-{index}") for index in range(4097))
    monkeypatch.setattr(verifier_v12, "_historical_manifest", lambda relative: wide)
    monkeypatch.setattr(verifier_v12, "_verify_historical_path", lambda relative, digest: None)
    with pytest.raises(verifier_v12.V12EvidenceError, match="leaf budget"):
        verifier_v12._verify_manifest_tree("wide.sha256", set(), set(), {}, 0)

    graph = {
        "a.sha256": (("a" * 64, "b.sha256"),),
        "b.sha256": (("b" * 64, "a.sha256"),),
    }
    monkeypatch.setattr(verifier_v12, "_historical_manifest", graph.__getitem__)
    with pytest.raises(verifier_v12.V12EvidenceError, match="cycle"):
        verifier_v12._verify_manifest_tree("a.sha256", set(), set(), {}, 0)


def test_exact_4096_leaf_manifest_is_accepted(monkeypatch):
    entries = tuple(("a" * 64, f"leaf-{index}") for index in range(4096))
    monkeypatch.setattr(verifier_v12, "_historical_manifest", lambda relative: entries)
    monkeypatch.setattr(verifier_v12, "_verify_historical_path", lambda relative, digest: None)
    leaves = {}
    verifier_v12._verify_manifest_tree("boundary.sha256", set(), set(), leaves, 0)
    assert len(leaves) == 4096


def test_historical_manifest_rejects_path_traversal_and_symlink(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="p53-v12-path-", dir=ROOT) as directory:
        base = Path(directory)
        monkeypatch.setattr(verifier_v12, "PROJECT", base)
        manifest = base / "bad.sha256"
        manifest.write_text("" + "a" * 64 + "  ../escape\n", encoding="utf-8")
        with pytest.raises(verifier_v12.V12EvidenceError, match="unsafe"):
            verifier_v12._historical_manifest("bad.sha256")
        target = base / "target.txt"
        target.write_text("safe", encoding="utf-8")
        normal = base / "normal"
        normal.mkdir()
        normal_file = normal / "leaf.txt"
        normal_file.write_text("normal", encoding="utf-8")
        verifier_v12._verify_historical_path(
            "normal/leaf.txt", hashlib.sha256(normal_file.read_bytes()).hexdigest()
        )
        link = base / "link.txt"
        try:
            link.symlink_to(target)
        except OSError:
            pytest.skip("symlink creation is unavailable")
        with pytest.raises(verifier_v12.V12EvidenceError, match="reparse"):
            verifier_v12._verify_historical_path("link.txt", hashlib.sha256(target.read_bytes()).hexdigest())
        target_dir = base / "inside-target"
        target_dir.mkdir()
        ancestor_leaf = target_dir / "leaf.txt"
        ancestor_leaf.write_text("inside", encoding="utf-8")
        linked_dir = base / "linked-dir"
        linked_dir.symlink_to(target_dir, target_is_directory=True)
        with pytest.raises(verifier_v12.V12EvidenceError, match="reparse"):
            verifier_v12._verify_historical_path(
                "linked-dir/leaf.txt", hashlib.sha256(ancestor_leaf.read_bytes()).hexdigest()
            )


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
        with pytest.raises(CapabilityV12DeniedError, match="reentrancy"):
            adapter.read_page(request)
        release.set()
        assert future.result().state is ReadStateV12.COMPLETED
    health = adapter.health()
    assert len(calls) == 1 and health.quota_remaining == 99
    assert health.pending_entries == 0 and health.uncertain_entries == 0 and health.ledger_entries == 1


def test_validation_exception_releases_admission_claim():
    adapter = _adapter()
    with pytest.raises(CapabilityV12ContractError):
        adapter.read_page(object())  # type: ignore[arg-type]
    assert adapter.read_page(_request()).state is ReadStateV12.COMPLETED


def test_same_correlation_payload_drift_denies_without_hook_or_quota():
    calls = []
    adapter = _adapter(lambda: calls.append(1))
    adapter.read_page(_request())
    with pytest.raises(CapabilityV12DeniedError, match="drift"):
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
    assert result.state is ReadStateV12.UNCERTAIN
    assert result.failure_class is ReadFailureClassV12.HOOK_EXCEPTION
    assert "secret" not in repr(result).lower()
    assert adapter.read_page(request) == result
    assert adapter.reconcile(request) == result
    assert calls == [1] and adapter.health().quota_remaining == 99


def test_cancelled_before_hook_rolls_back_quota_and_rate_and_never_calls_hook():
    token = CancellationTokenV12()
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
    assert result.state is ReadStateV12.CANCELLED_BEFORE_HOOK
    assert adapter.health().quota_remaining == 1
    assert calls == []
    assert adapter.read_page(_request(correlation_id="corr-002")).state is ReadStateV12.COMPLETED


def test_timeout_after_hook_is_uncertain_and_not_replayed():
    now = [0.0]
    calls = []

    def hook():
        calls.append(1)
        now[0] = 2.0

    adapter = _adapter(hook, clock=lambda: now[0])
    request = _request(timeout_ms=1000)
    result = adapter.read_page(request)
    assert result.state is ReadStateV12.UNCERTAIN
    assert result.failure_class is ReadFailureClassV12.TIMEOUT
    assert adapter.read_page(request) == result and calls == [1]


@pytest.mark.parametrize(("action", "failure"), [("kill", ReadFailureClassV12.KILL), ("revoke", ReadFailureClassV12.REVOKED)])
def test_kill_and_revoke_during_hook_latch_uncertain(action, failure):
    holder = {}

    def hook():
        holder["adapter"].set_kill(True) if action == "kill" else holder["adapter"].revoke()

    holder["adapter"] = _adapter(hook, credential_alias="alias:catalog/account")
    result = holder["adapter"].read_page(_request())
    assert result.state is ReadStateV12.UNCERTAIN and result.failure_class is failure
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
        assert reconciled.state is ReadStateV12.UNCERTAIN
        assert reconciled.failure_class is ReadFailureClassV12.EXPIRED_PENDING
        release.set()
        assert future.result().state is ReadStateV12.UNCERTAIN


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
    assert adapter.read_page(first_request).state is ReadStateV12.UNCERTAIN
    with pytest.raises(CapabilityV12DeniedError, match="pending/uncertain"):
        adapter.read_page(_request(correlation_id="corr-002"))
    now[0] = 2.0
    expired = adapter.reconcile(first_request)
    assert expired.state is ReadStateV12.EXPIRED_UNCERTAIN
    assert expired.failure_class is ReadFailureClassV12.UNCERTAIN_EXPIRED
    assert adapter.read_page(first_request) == expired and calls == [1]
    assert adapter.read_page(_request(correlation_id="corr-002")).state is ReadStateV12.UNCERTAIN


def test_pending_and_uncertain_capacity_configuration_is_bounded():
    with pytest.raises(CapabilityV12ContractError):
        _adapter(ledger_capacity=2, pending_capacity=2, uncertain_capacity=1)
    with pytest.raises(CapabilityV12ContractError):
        _adapter(ledger_capacity=1, pending_capacity=1, uncertain_capacity=2)


def test_ledger_capacity_is_bounded_and_does_not_evict_for_replay():
    adapter = _adapter(ledger_capacity=1, pending_capacity=1, uncertain_capacity=1)
    request = _request()
    assert adapter.read_page(request).state is ReadStateV12.COMPLETED
    with pytest.raises(CapabilityV12DeniedError, match="capacity"):
        adapter.read_page(_request(correlation_id="corr-002"))
    assert adapter.read_page(request).state is ReadStateV12.COMPLETED


def test_profile_bound_cursor_cannot_cross_adapter_profile():
    first_adapter = _adapter()
    first = first_adapter.read_page(_request())
    assert first.next_cursor
    other = _adapter(profile_id="profile-other")
    with pytest.raises(CapabilityV12DeniedError):
        other.read_page(_request(profile_id="profile-other", correlation_id="corr-002", cursor=first.next_cursor))


def test_cursor_snapshot_and_signature_tamper_fail_closed():
    adapter = _adapter()
    cursor = adapter.read_page(_request()).next_cursor
    assert cursor
    tampered = cursor[:-1] + ("0" if cursor[-1] != "0" else "1")
    with pytest.raises(CapabilityV12DeniedError):
        adapter.read_page(_request(correlation_id="corr-002", cursor=tampered))
    changed = LocalCatalogReadAdapterV12(
        _items(6), workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
        cursor_signing_key=KEY, read_hook=lambda: None, status=CapabilityStatusV12.AVAILABLE_READ_ONLY,
        status_reason="healthy",
    )
    with pytest.raises(CapabilityV12DeniedError):
        changed.read_page(_request(correlation_id="corr-003", cursor=cursor))


def test_rate_limit_and_quota_are_reserved_once_and_truthful():
    adapter = _adapter(rate_limit=1, quota_limit=1, clock=lambda: 10.0)
    assert adapter.read_page(_request()).state is ReadStateV12.COMPLETED
    limited = adapter.read_page(_request(correlation_id="corr-002"))
    assert limited.state is ReadStateV12.RATE_LIMITED and limited.retry_after_ms == 1000
    assert adapter.read_page(_request(correlation_id="corr-002")) == limited
    assert adapter.health().quota_remaining == 0


def test_unavailable_auth_scope_disabled_degraded_and_unknown_reconcile():
    assert _adapter(auth_available=False).read_page(_request()).failure_class is ReadFailureClassV12.AUTH
    assert _adapter(granted_scopes=()).read_page(_request()).failure_class is ReadFailureClassV12.SCOPE
    assert _adapter(status=CapabilityStatusV12.DISABLED, status_reason="operator_disabled").read_page(_request()).state is ReadStateV12.DENIED
    degraded = _adapter(status=CapabilityStatusV12.DEGRADED, status_reason="partial_fixture")
    assert degraded.read_page(_request()).state is ReadStateV12.COMPLETED
    unknown = degraded.reconcile(_request(correlation_id="unknown-corr"))
    assert unknown.state is ReadStateV12.UNKNOWN_CORRELATION


def test_legacy_builder_preserves_current_32_declarations_and_policies_without_import():
    declarations = _assignment(ROOT / "main.py", "TOOL_DECLARATIONS")
    policies = _assignment(ROOT / "core" / "permission_broker.py", "MODEL_TOOL_POLICIES")
    built = build_legacy_descriptors_v12(
        declarations, policies, workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
    )
    assert len(built.descriptors) == 32
    assert {item["name"]: item for item in built.declarations()} == {item["name"]: item for item in declarations}
    assert dict(built.policy_mapping()) == policies
    assert all(item.status is CapabilityStatusV12.DISABLED for item in built.descriptors)


def test_legacy_missing_policy_and_duplicate_declaration_fail_closed():
    declarations = _assignment(ROOT / "main.py", "TOOL_DECLARATIONS")
    policies = _assignment(ROOT / "core" / "permission_broker.py", "MODEL_TOOL_POLICIES")
    policies.pop("open_app")
    with pytest.raises(CapabilityV12ContractError):
        build_legacy_descriptors_v12(
            declarations, policies, workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
        )
    with pytest.raises(CapabilityV12ContractError):
        build_legacy_descriptors_v12(
            declarations + [declarations[0]], {**policies, "open_app": "always_confirm"},
            workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE,
        )


def test_registry_concurrency_duplicate_kill_revoke_and_snapshot_are_safe():
    nexus = CapabilityNexusV12()
    descriptors = [_descriptor(capability_id=f"fixture.capability-{i}") for i in range(16)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(nexus.register, descriptors))
    assert len(nexus.snapshot(workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE).entries) == 16
    nexus.set_kill(True)
    assert all(
        item.projection_reason == "global_kill_active"
        for item in nexus.snapshot(workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE).entries
    )


def test_no_live_runtime_source_references_v12():
    live = [ROOT / "main.py", ROOT / "ui.py", ROOT / "scripts" / "launch_onyx.pyw"]
    live += list((ROOT / "actions").rglob("*.py")) + list((ROOT / "dashboard").rglob("*.py"))
    live += [path for path in (ROOT / "core").glob("*.py") if path.name != "capability_nexus_v12.py"]
    assert all("capability_nexus_v12" not in path.read_text(encoding="utf-8", errors="ignore") for path in live)
