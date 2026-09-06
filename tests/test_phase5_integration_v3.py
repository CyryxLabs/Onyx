from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from core import phase5_integration_v3 as integration_v3
from core.phase5_integration_v3 import (
    LOCAL_CATALOG_TOOL,
    CatalogSeedV3,
    IntegrationFlagsV3,
    NormalizedCatalogDispatchV3,
    Phase5IntegrationV3,
    Phase5IntegrationV3ContractError,
    Phase5IntegrationV3Error,
    create_phase5_integration_v3,
)
from core.phase5_runtime_v10 import RuntimeBindingV10


ROOT = Path(__file__).resolve().parents[1]
BINDING = RuntimeBindingV10(
    "trace-integration-v2",
    "session-integration-v2",
    "workspace-integration",
    "account-integration",
    "profile-integration",
)
CATALOG = (
    CatalogSeedV3("system_status", "System Status"),
    CatalogSeedV3("memory_search", "Memory Search"),
    CatalogSeedV3("weather_report", "Weather Report"),
)


def active_flags(**changes: bool) -> IntegrationFlagsV3:
    values = {
        "integration": True,
        "runtime": True,
        "grant_shadow": False,
        "approval_inbox": False,
        "low_risk": True,
        "nexus_projection": False,
        "local_catalog_read": True,
        "dashboard_projection": True,
    }
    values.update(changes)
    return IntegrationFlagsV3(**values)


def integration(**changes: bool) -> Phase5IntegrationV3:
    return Phase5IntegrationV3(
        binding=BINDING,
        principal_id="owner-integration",
        flags=active_flags(**changes),
        catalog=CATALOG,
    )


def authorize(
    bridge: Phase5IntegrationV3, reference: str, **arguments: object
) -> None:
    allowed, reason = bridge.permission_hook(
        LOCAL_CATALOG_TOOL,
        {**arguments, "_phase5_invocation_ref": reference},
    )
    assert allowed, reason


def test_v2_flags_are_strictly_default_off() -> None:
    flags = IntegrationFlagsV3.from_environ({})
    assert not any(getattr(flags, name) for name in flags.__dataclass_fields__)
    assert create_phase5_integration_v3(
        session_id="session-off", trace_id="trace-off", catalog=(), environ={}
    ) is None
    with pytest.raises(Phase5IntegrationV3ContractError):
        IntegrationFlagsV3(integration=True, local_catalog_read=True)


def test_normalization_is_immutable_canonical_and_closed() -> None:
    implicit = NormalizedCatalogDispatchV3.from_arguments(
        {}, permission_stage=False
    )
    explicit = NormalizedCatalogDispatchV3.from_arguments(
        {"page_size": 25, "cursor": None}, permission_stage=False
    )
    assert implicit == explicit
    assert implicit.digest() == explicit.digest()
    assert implicit.page_size == 25
    with pytest.raises(Phase5IntegrationV3ContractError):
        NormalizedCatalogDispatchV3.from_arguments(
            {"page_size": 1, "future_material_arg": True},
            permission_stage=False,
        )


@pytest.mark.parametrize(
    ("authorized", "dispatched"),
    (
        ({"page_size": 1}, {"page_size": 2}),
        ({"page_size": 2}, {"page_size": 1}),
        ({"page_size": 1}, {"page_size": 1, "cursor": "cursor-a"}),
        ({"page_size": 1, "cursor": "cursor-a"}, {"page_size": 1}),
        (
            {"page_size": 1, "cursor": "cursor-a"},
            {"page_size": 1, "cursor": "cursor-b"},
        ),
    ),
)
def test_any_material_argument_mutation_burns_authorization_and_never_reads(
    monkeypatch: pytest.MonkeyPatch,
    authorized: dict[str, object],
    dispatched: dict[str, object],
) -> None:
    bridge = integration()
    reference = "mutation-test"
    authorize(bridge, reference, **authorized)
    reads = 0
    audits: list[dict[str, object]] = []

    original = type(bridge._catalog).read_page

    def counted(adapter, request):
        nonlocal reads
        reads += 1
        return original(adapter, request)

    monkeypatch.setattr(type(bridge._catalog), "read_page", counted)
    monkeypatch.setattr(
        integration_v3,
        "append_tool_audit",
        lambda **values: audits.append(values) or "a" * 64,
    )

    with pytest.raises(Phase5IntegrationV3Error, match="immutable authorization"):
        bridge.catalog_read(reference, dispatched)
    assert reads == 0
    assert bridge._seal_key(reference) not in bridge._prepared
    assert reference not in bridge._runtime_actions
    assert reference not in bridge._grant_actions
    assert audits and audits[0]["decision"] == "deny"
    with pytest.raises(Phase5IntegrationV3Error, match="unavailable"):
        bridge.catalog_read(reference, authorized)
    assert reads == 0


def test_invalid_or_unknown_dispatch_argument_burns_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = integration()
    authorize(bridge, "invalid-dispatch", page_size=1)
    audits: list[dict[str, object]] = []
    monkeypatch.setattr(
        integration_v3,
        "append_tool_audit",
        lambda **values: audits.append(values) or "b" * 64,
    )
    with pytest.raises(Phase5IntegrationV3Error):
        bridge.catalog_read(
            "invalid-dispatch", {"page_size": 1, "unbound": "value"}
        )
    assert audits[0]["reason"] == "phase5-v3-invalid-dispatch"
    assert "value" not in repr(audits[0])


@pytest.mark.parametrize(
    "duplicate_arguments",
    (
        {"page_size": 1},
        {"page_size": 0},
        {"page_size": 1, "unknown": "field"},
    ),
)
def test_any_duplicate_burns_original_and_neither_request_may_read(
    monkeypatch: pytest.MonkeyPatch,
    duplicate_arguments: dict[str, object],
) -> None:
    bridge = integration()
    audits: list[dict[str, object]] = []
    reads = 0
    original_read = type(bridge._catalog).read_page

    def counted(adapter, request):
        nonlocal reads
        reads += 1
        return original_read(adapter, request)

    monkeypatch.setattr(type(bridge._catalog), "read_page", counted)
    monkeypatch.setattr(
        integration_v3,
        "append_tool_audit",
        lambda **values: audits.append(values) or "c" * 64,
    )
    authorize(bridge, "unique-ref", page_size=1)
    duplicate, duplicate_reason = bridge.permission_hook(
        LOCAL_CATALOG_TOOL,
        {**duplicate_arguments, "_phase5_invocation_ref": "unique-ref"},
    )
    assert duplicate is False
    assert "burned" in duplicate_reason
    assert audits[-1]["reason"] == "phase5-v3-invocation-collision-burned"
    seal_key = bridge._seal_key("unique-ref")
    assert seal_key not in bridge._prepared
    assert "unique-ref" not in bridge._runtime_actions
    assert "unique-ref" not in bridge._grant_actions
    assert bridge._seals[seal_key].state == "burned-collision"
    with pytest.raises(Phase5IntegrationV3Error, match="unavailable"):
        bridge.catalog_read("unique-ref", {"page_size": 1})
    with pytest.raises(Phase5IntegrationV3Error, match="unavailable"):
        bridge.catalog_read("unique-ref", duplicate_arguments)
    assert reads == 0


@pytest.mark.parametrize(
    "colliding_arguments",
    (
        ({"page_size": 1}, {"page_size": 2}),
        ({"page_size": 1}, {"page_size": 0}),
        ({"page_size": 1}, {"unknown": "field"}),
    ),
)
def test_concurrent_authorization_collision_never_reaches_adapter(
    monkeypatch: pytest.MonkeyPatch,
    colliding_arguments: tuple[dict[str, object], dict[str, object]],
) -> None:
    bridge = integration()
    reads = 0
    barrier = threading.Barrier(2)
    original_read = type(bridge._catalog).read_page

    def counted(adapter, request):
        nonlocal reads
        reads += 1
        return original_read(adapter, request)

    monkeypatch.setattr(type(bridge._catalog), "read_page", counted)
    monkeypatch.setattr(
        integration_v3, "append_tool_audit", lambda **_values: "d" * 64
    )

    def collide(arguments: dict[str, object]) -> bool:
        barrier.wait(timeout=2)
        allowed, _ = bridge.permission_hook(
            LOCAL_CATALOG_TOOL,
            {
                **arguments,
                "_phase5_invocation_ref": "concurrent-auth",
            },
        )
        return allowed

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(collide, colliding_arguments))
    assert results.count(True) <= 1
    seal_key = bridge._seal_key("concurrent-auth")
    assert seal_key not in bridge._prepared
    assert bridge._seals[seal_key].state.startswith("burned-")
    for page_size in (1, 2):
        with pytest.raises(Phase5IntegrationV3Error, match="unavailable"):
            bridge.catalog_read("concurrent-auth", {"page_size": page_size})
    assert reads == 0


@pytest.mark.parametrize(
    "first_arguments",
    ({"page_size": 0}, {"page_size": 1, "unknown": "field"}),
)
def test_invalid_first_observation_seals_reference_and_later_valid_duplicate_cannot_read(
    monkeypatch: pytest.MonkeyPatch,
    first_arguments: dict[str, object],
) -> None:
    bridge = integration()
    reads = 0
    original_read = type(bridge._catalog).read_page

    def counted(adapter, request):
        nonlocal reads
        reads += 1
        return original_read(adapter, request)

    monkeypatch.setattr(type(bridge._catalog), "read_page", counted)
    monkeypatch.setattr(
        integration_v3, "append_tool_audit", lambda **_values: "e" * 64
    )
    first, _ = bridge.permission_hook(
        LOCAL_CATALOG_TOOL,
        {**first_arguments, "_phase5_invocation_ref": "invalid-first"},
    )
    second, reason = bridge.permission_hook(
        LOCAL_CATALOG_TOOL,
        {"page_size": 1, "_phase5_invocation_ref": "invalid-first"},
    )
    assert first is False
    assert second is False
    assert "burned" in reason
    assert bridge._seals[bridge._seal_key("invalid-first")].state == (
        "burned-collision"
    )
    with pytest.raises(Phase5IntegrationV3Error, match="unavailable"):
        bridge.catalog_read("invalid-first", {"page_size": 1})
    assert reads == 0


def test_implicit_and_explicit_defaults_are_same_canonical_dispatch() -> None:
    bridge = integration()
    authorize(bridge, "default-equivalence")
    result = bridge.catalog_read(
        "default-equivalence", {"page_size": 25, "cursor": None}
    )
    assert result["state"] == "completed"
    assert len(result["items"]) == len(CATALOG)


def test_exact_dispatch_is_single_consumer_under_concurrency() -> None:
    bridge = integration()
    reference = "concurrent-read"
    authorize(bridge, reference, page_size=1)
    barrier = threading.Barrier(2)

    def dispatch() -> str:
        barrier.wait(timeout=2)
        try:
            bridge.catalog_read(reference, {"page_size": 1})
        except Phase5IntegrationV3Error:
            return "denied"
        return "completed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _index: dispatch(), range(2)))
    assert sorted(results) == ["completed", "denied"]


def test_termination_race_never_allows_more_than_one_dispatch() -> None:
    bridge = integration()
    reference = "terminate-race"
    authorize(bridge, reference, page_size=1)
    barrier = threading.Barrier(2)

    def read() -> str:
        barrier.wait(timeout=2)
        try:
            bridge.catalog_read(reference, {"page_size": 1})
        except Phase5IntegrationV3Error:
            return "denied"
        return "completed"

    def terminate() -> str:
        barrier.wait(timeout=2)
        return str(bridge.terminate("kill")["data"]["state"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        read_future = pool.submit(read)
        terminate_future = pool.submit(terminate)
        assert terminate_future.result() == "TERMINATED"
        assert read_future.result() in {"completed", "denied"}
    assert not bridge.local_catalog_enabled
    assert not bridge._prepared


def test_permission_contract_rejects_unknown_fields_and_non_exact_types() -> None:
    bridge = integration()
    for index, arguments in enumerate(
        (
            {"page_size": True},
            {"page_size": 0},
            {"page_size": 51},
            {"cursor": 5},
            {"unknown": "field"},
        )
    ):
        allowed, _ = bridge.permission_hook(
            LOCAL_CATALOG_TOOL,
            {**arguments, "_phase5_invocation_ref": f"bad-{index}"},
        )
        assert allowed is False
    assert bridge.permission_hook("system_status", {}) is None


def test_v1_v2_v10_and_in_scope_accepted_anchors_remain_exact() -> None:
    expected = {
        "core/phase5_integration_v1.py": "234ba11fb9ce5336297c27951c97e0c9c63a34bf4841b6980b58cff026687cdc",
        "tests/test_phase5_integration_v1.py": "4d5a3432ee90009266cf57a33d098f57430aca1831f1ab07b354e0797e775fef",
        "core/phase5_runtime_v10.py": "f80fd636e145e669cc1ea76cfc024fcc5d385451cc1ef8624f7c9d8e0ac3f439",
        "tests/test_phase5_runtime_v10.py": "b2a6d9524d2d5d1b85af3325462f7bd28793180cee0ea4295d6600750615cfff",
        "scripts/verify_phase5_runtime_v10_acceptance.py": "71d7db0b01c1fb2c3b133302a1b3877bd04b549f136f7a06e8f2f26371fc3a2c",
        "tests/test_phase5_runtime_v10_acceptance.py": "3d8b2c2d8be5f19adb8be681ec6267d7d631acd22115bf0fa6c53ad95b8d2883",
        "core/phase5_integration_v2.py": "ae035c4be1364d87f23c308ca42d33c938a29d6181680de62b5d9de5fe5f285d",
        "tests/test_phase5_integration_v2.py": "cb9ec992e08c5b47c51a7aac4a57b813fd6648526c22a488dfff4b51fe3a1217",
        "scripts/verify_phase5_integration_v2_transition.py": "9eacbe19c29d58ff1890b0a50b48bfa37c7ba681c28c640115264a5627dca1b0",
        "tests/test_phase5_integration_v2_transition.py": "2efe373bf0740d32384929ab3ade7aabbcce16388d7d0063b33ef9ce3b3a1f9e",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest


def test_v3_is_independent_and_live_host_references_v3_only() -> None:
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    v3 = (ROOT / "core/phase5_integration_v3.py").read_text(encoding="utf-8")
    assert "core.phase5_integration_v3" in main
    assert "core.phase5_integration_v1" not in main
    assert "core.phase5_integration_v2" not in main
    assert "phase5_integration_v1" not in v3
    assert "phase5_integration_v2" not in v3
    assert "Phase5IntegrationV1" not in v3
    assert "Phase5IntegrationV2" not in v3
    expected = {
        "core/permission_broker.py": "e37fb092410ba0843036dbdc779342c4d24a811bbfcf0de8812f2f6144e7d250",
        "dashboard/server.py": "4d3142dc9c6a78cfe76f804de2b154334da2d7790484783a993babc92300bae1",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
