from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from core import phase5_integration_v2 as integration_v2
from core.phase5_integration_v2 import (
    LOCAL_CATALOG_TOOL,
    CatalogSeedV2,
    IntegrationFlagsV2,
    NormalizedCatalogDispatchV2,
    Phase5IntegrationV2,
    Phase5IntegrationV2ContractError,
    Phase5IntegrationV2Error,
    create_phase5_integration_v2,
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
    CatalogSeedV2("system_status", "System Status"),
    CatalogSeedV2("memory_search", "Memory Search"),
    CatalogSeedV2("weather_report", "Weather Report"),
)


def active_flags(**changes: bool) -> IntegrationFlagsV2:
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
    return IntegrationFlagsV2(**values)


def integration(**changes: bool) -> Phase5IntegrationV2:
    return Phase5IntegrationV2(
        binding=BINDING,
        principal_id="owner-integration",
        flags=active_flags(**changes),
        catalog=CATALOG,
    )


def authorize(
    bridge: Phase5IntegrationV2, reference: str, **arguments: object
) -> None:
    allowed, reason = bridge.permission_hook(
        LOCAL_CATALOG_TOOL,
        {**arguments, "_phase5_invocation_ref": reference},
    )
    assert allowed, reason


def test_v2_flags_are_strictly_default_off() -> None:
    flags = IntegrationFlagsV2.from_environ({})
    assert not any(getattr(flags, name) for name in flags.__dataclass_fields__)
    assert create_phase5_integration_v2(
        session_id="session-off", trace_id="trace-off", catalog=(), environ={}
    ) is None
    with pytest.raises(Phase5IntegrationV2ContractError):
        IntegrationFlagsV2(integration=True, local_catalog_read=True)


def test_normalization_is_immutable_canonical_and_closed() -> None:
    implicit = NormalizedCatalogDispatchV2.from_arguments(
        {}, permission_stage=False
    )
    explicit = NormalizedCatalogDispatchV2.from_arguments(
        {"page_size": 25, "cursor": None}, permission_stage=False
    )
    assert implicit == explicit
    assert implicit.digest() == explicit.digest()
    assert implicit.page_size == 25
    with pytest.raises(Phase5IntegrationV2ContractError):
        NormalizedCatalogDispatchV2.from_arguments(
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
        integration_v2,
        "append_tool_audit",
        lambda **values: audits.append(values) or "a" * 64,
    )

    with pytest.raises(Phase5IntegrationV2Error, match="immutable authorization"):
        bridge.catalog_read(reference, dispatched)
    assert reads == 0
    assert reference not in bridge._prepared
    assert reference not in bridge._runtime_actions
    assert reference not in bridge._grant_actions
    assert audits and audits[0]["decision"] == "deny"
    with pytest.raises(Phase5IntegrationV2Error, match="unavailable"):
        bridge.catalog_read(reference, authorized)
    assert reads == 0


def test_invalid_or_unknown_dispatch_argument_burns_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = integration()
    authorize(bridge, "invalid-dispatch", page_size=1)
    audits: list[dict[str, object]] = []
    monkeypatch.setattr(
        integration_v2,
        "append_tool_audit",
        lambda **values: audits.append(values) or "b" * 64,
    )
    with pytest.raises(Phase5IntegrationV2Error):
        bridge.catalog_read(
            "invalid-dispatch", {"page_size": 1, "unbound": "value"}
        )
    assert audits[0]["reason"] == "phase5-v2-invalid-dispatch"
    assert "value" not in repr(audits[0])


def test_duplicate_collision_and_post_consume_replay_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bridge = integration()
    audits: list[dict[str, object]] = []
    monkeypatch.setattr(
        integration_v2,
        "append_tool_audit",
        lambda **values: audits.append(values) or "c" * 64,
    )
    authorize(bridge, "unique-ref", page_size=1)
    duplicate, duplicate_reason = bridge.permission_hook(
        LOCAL_CATALOG_TOOL,
        {"page_size": 2, "_phase5_invocation_ref": "unique-ref"},
    )
    assert duplicate is False
    assert "already used" in duplicate_reason
    assert audits[-1]["reason"] == "phase5-v2-invocation-reference-replay"
    assert audits[-1]["arguments"]["expected_digest"] != (
        audits[-1]["arguments"]["observed_digest"]
    )

    result = bridge.catalog_read("unique-ref", {"page_size": 1})
    assert result["state"] == "completed"
    replay, replay_reason = bridge.permission_hook(
        LOCAL_CATALOG_TOOL,
        {"page_size": 1, "_phase5_invocation_ref": "unique-ref"},
    )
    assert replay is False
    assert "already used" in replay_reason


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
        except Phase5IntegrationV2Error:
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
        except Phase5IntegrationV2Error:
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


def test_v1_v10_and_in_scope_accepted_anchors_remain_exact() -> None:
    expected = {
        "core/phase5_integration_v1.py": "234ba11fb9ce5336297c27951c97e0c9c63a34bf4841b6980b58cff026687cdc",
        "tests/test_phase5_integration_v1.py": "4d5a3432ee90009266cf57a33d098f57430aca1831f1ab07b354e0797e775fef",
        "core/phase5_runtime_v10.py": "f80fd636e145e669cc1ea76cfc024fcc5d385451cc1ef8624f7c9d8e0ac3f439",
        "tests/test_phase5_runtime_v10.py": "b2a6d9524d2d5d1b85af3325462f7bd28793180cee0ea4295d6600750615cfff",
        "scripts/verify_phase5_runtime_v10_acceptance.py": "71d7db0b01c1fb2c3b133302a1b3877bd04b549f136f7a06e8f2f26371fc3a2c",
        "tests/test_phase5_runtime_v10_acceptance.py": "3d8b2c2d8be5f19adb8be681ec6267d7d631acd22115bf0fa6c53ad95b8d2883",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest


def test_live_host_references_v2_only_and_generic_hooks_stay_exact() -> None:
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "core.phase5_integration_v2" in main
    assert "core.phase5_integration_v1" not in main
    expected = {
        "core/permission_broker.py": "e37fb092410ba0843036dbdc779342c4d24a811bbfcf0de8812f2f6144e7d250",
        "dashboard/server.py": "4d3142dc9c6a78cfe76f804de2b154334da2d7790484783a993babc92300bae1",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
