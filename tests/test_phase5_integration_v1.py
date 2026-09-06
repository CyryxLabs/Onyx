from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import permission_broker
from core.phase5_integration_v1 import (
    LOCAL_CATALOG_TOOL,
    CatalogSeedV1,
    IntegrationFlagsV1,
    Phase5IntegrationV1,
    Phase5IntegrationV1ContractError,
    Phase5IntegrationV1Error,
    create_phase5_integration_v1,
)
from core.phase5_runtime_v10 import RuntimeBindingV10


ROOT = Path(__file__).resolve().parents[1]
BINDING = RuntimeBindingV10(
    "trace-integration",
    "session-integration",
    "workspace-integration",
    "account-integration",
    "profile-integration",
)
CATALOG = (
    CatalogSeedV1("system_status", "System Status"),
    CatalogSeedV1("memory_search", "Memory Search"),
)


def active_flags(**changes: bool) -> IntegrationFlagsV1:
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
    return IntegrationFlagsV1(**values)


def integration(**changes: bool) -> Phase5IntegrationV1:
    return Phase5IntegrationV1(
        binding=BINDING,
        principal_id="owner-integration",
        flags=active_flags(**changes),
        catalog=CATALOG,
    )


def test_flags_are_strictly_default_off_and_factory_has_no_identity_side_effect() -> None:
    flags = IntegrationFlagsV1.from_environ({})
    assert not any(getattr(flags, name) for name in flags.__dataclass_fields__)
    assert create_phase5_integration_v1(
        session_id="session-off",
        trace_id="trace-off",
        catalog=(),
        environ={},
    ) is None


@pytest.mark.parametrize(
    "values",
    (
        {"runtime": True},
        {"integration": True, "low_risk": True},
        {
            "integration": True,
            "runtime": True,
            "local_catalog_read": True,
        },
    ),
)
def test_partial_or_widened_flag_sets_fail_closed(values: dict[str, bool]) -> None:
    with pytest.raises(Phase5IntegrationV1ContractError):
        IntegrationFlagsV1(**values)


def test_exact_local_catalog_read_consumes_one_decision_and_has_no_egress() -> None:
    bridge = integration()
    arguments = {
        "page_size": 1,
        "_phase5_invocation_ref": "invocation-one",
    }
    assert bridge.permission_hook(LOCAL_CATALOG_TOOL, arguments)[0] is True
    result = bridge.catalog_read("invocation-one", {"page_size": 1})
    assert result["state"] == "completed"
    assert result["cost_micro"] == 0
    assert result["egress"] == "none"
    assert len(result["items"]) == 1
    assert result["next_cursor"] is not None
    with pytest.raises(Phase5IntegrationV1Error):
        bridge.catalog_read("invocation-one", {"page_size": 1})


def test_permission_hook_is_closed_to_one_tool_and_bounded_arguments() -> None:
    bridge = integration()
    assert bridge.permission_hook("system_status", {}) is None
    for bad in (0, 51, True, "1"):
        allowed, _ = bridge.permission_hook(
            LOCAL_CATALOG_TOOL,
            {"page_size": bad, "_phase5_invocation_ref": "bad-page"},
        )
        assert allowed is False
    allowed, _ = bridge.permission_hook(
        LOCAL_CATALOG_TOOL,
        {"cursor": "x" * 2049, "_phase5_invocation_ref": "bad-cursor"},
    )
    assert allowed is False


def test_all_accepted_components_recover_to_ready_and_project_read_only() -> None:
    bridge = integration(
        grant_shadow=True,
        approval_inbox=True,
        nexus_projection=True,
    )
    status = bridge.status_payload()["data"]
    assert status["state"] == "READY"
    assert status["component_failures"] == []
    capabilities = bridge.dashboard_read("capabilities")["data"]
    assert capabilities["total"] == 1
    item = capabilities["items"][0]["payload_json"]
    assert "local.catalog" in item
    assert '"status":"disabled"' in item
    assert '"authority_granted"' not in item
    assert bridge.dashboard_read("inbox")["data"]["total"] == 0


@pytest.mark.parametrize(
    "reason", ("kill", "revoke", "rollback", "end_session", "reconnect", "shutdown")
)
def test_one_termination_boundary_closes_all_four_host_actions(reason: str) -> None:
    bridge = integration(
        grant_shadow=True,
        approval_inbox=True,
        nexus_projection=True,
    )
    result = bridge.terminate(reason)["data"]
    assert result["state"] == "TERMINATED"
    assert result["termination_failures"] == []
    assert result["termination_timeouts"] == []
    allowed, _ = bridge.permission_hook(
        LOCAL_CATALOG_TOOL,
        {"_phase5_invocation_ref": f"after-{reason}"},
    )
    assert allowed is False


def test_permission_broker_off_path_never_calls_phase5_for_legacy_tools(monkeypatch) -> None:
    called = False

    def forbidden(_tool: str, _arguments: object):
        nonlocal called
        called = True
        raise AssertionError("legacy tool reached Phase 5")

    monkeypatch.setattr(permission_broker, "_phase5_authorization_hook", forbidden)
    assert permission_broker.authorize_model_tool(
        "youtube_video", {"action": "summarize", "save": False}
    ) == (True, "")
    assert called is False


def test_permission_broker_local_path_fails_closed_without_session_hook(monkeypatch) -> None:
    monkeypatch.setattr(permission_broker, "_phase5_authorization_hook", None)
    allowed, reason = permission_broker.authorize_model_tool(
        LOCAL_CATALOG_TOOL,
        {"page_size": 1, "_phase5_invocation_ref": "no-session"},
    )
    assert allowed is False
    assert "disabled" in reason


def test_dashboard_routes_are_absent_off_and_authenticated_when_enabled(
    monkeypatch, tmp_path: Path
) -> None:
    from dashboard import server as dashboard_server

    monkeypatch.setattr(dashboard_server, "_ensure_local_certificate", lambda *_: None)
    off = dashboard_server.DashboardServer(
        local_ip="127.0.0.1",
        cert_dir=tmp_path / "off-cert",
        uploads_dir=tmp_path / "off-uploads",
        static_dir=dashboard_server.STATIC_DIR,
    )
    off_paths = {route.path for route in off.app.routes}
    assert not any(path.startswith("/api/phase5/") for path in off_paths)

    on = dashboard_server.DashboardServer(
        local_ip="127.0.0.1",
        cert_dir=tmp_path / "on-cert",
        uploads_dir=tmp_path / "on-uploads",
        static_dir=dashboard_server.STATIC_DIR,
        phase5_enabled=True,
    )
    client = TestClient(on.app)
    assert client.get("/api/phase5/status").status_code == 401
    bridge = integration()
    on.set_phase5_bridge(bridge)
    token = on._issue_token("ABCDEF")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/phase5/status", headers=headers)
    assert response.status_code == 200
    assert response.json()["data"]["state"] == "READY"
    killed = client.post("/api/phase5/kill", headers=headers)
    assert killed.status_code == 200
    assert killed.json()["data"]["state"] == "TERMINATED"
    paths = {route.path for route in on.app.routes}
    assert "/api/phase5/status" in paths
    assert "/api/phase5/inbox" in paths
    assert "/api/phase5/capabilities" in paths
    assert "/api/phase5/kill" in paths
    assert not any(
        word in path for path in paths for word in ("approve", "grant", "dispatch")
    )


def test_factory_requires_explicit_five_dimension_identity() -> None:
    environment = {
        "ONYX_PHASE5_INTEGRATION_V1": "true",
        "ONYX_PHASE5_RUNTIME_V1": "true",
    }
    with pytest.raises(Phase5IntegrationV1ContractError):
        create_phase5_integration_v1(
            session_id="session-factory",
            trace_id="trace-factory",
            catalog=(),
            environ=environment,
        )
    environment.update(
        ONYX_PHASE5_PRINCIPAL_ID="owner-factory",
        ONYX_PHASE5_WORKSPACE_ID="workspace-factory",
        ONYX_PHASE5_ACCOUNT_ID="account-factory",
        ONYX_PHASE5_PROFILE_ID="profile-factory",
    )
    bridge = create_phase5_integration_v1(
        session_id="session-factory",
        trace_id="trace-factory",
        catalog=(),
        environ=environment,
    )
    assert bridge is not None
    assert bridge.binding.workspace_id == "workspace-factory"


def test_no_background_thread_and_authorize_read_p95_under_25ms() -> None:
    before = len(threading.enumerate())
    bridge = integration()
    elapsed = []
    for index in range(100):
        reference = f"perf-{index:03d}"
        started = time.perf_counter_ns()
        allowed, _ = bridge.permission_hook(
            LOCAL_CATALOG_TOOL,
            {"page_size": 2, "_phase5_invocation_ref": reference},
        )
        assert allowed
        bridge.catalog_read(reference, {"page_size": 2})
        elapsed.append((time.perf_counter_ns() - started) / 1_000_000)
    elapsed.sort()
    p95 = elapsed[int(len(elapsed) * 0.95) - 1]
    assert p95 < 25.0
    assert len(threading.enumerate()) == before


def test_accepted_anchors_and_reserved_ui_are_byte_preserved() -> None:
    expected = {
        "core/session_grants_v11.py": "0f4ad25b72a9c64064dfc946afab6d2515edff1f91171d46d54e36e38c6cd159",
        "core/approval_inbox_v15.py": "f9627e6b9e840dbca8e098a047e56da4647d24ef80f201c5585a41d405d52061",
        "core/capability_nexus_v32.py": "576eed0bda063945d33f8bcb79b338e64976ca5252af793633fe3ab667ed1fc9",
        "core/phase5_component_adapters_v3.py": "9c570d40a410e57a18f82a4ee2c30eddfe515a0cc7798d13607d020e573e3239",
        "core/phase5_runtime_v10.py": "f80fd636e145e669cc1ea76cfc024fcc5d385451cc1ef8624f7c9d8e0ac3f439",
        "ui.py": "60bea0ac313efa7c77dfbc1e3bffec885a0dad010b6f3e9e332761d6cd0de043",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest


def test_live_wiring_has_no_remote_authority_or_orb_changes() -> None:
    dashboard = (ROOT / "dashboard/server.py").read_text(encoding="utf-8")
    integration_source = (ROOT / "core/phase5_integration_v1.py").read_text(
        encoding="utf-8"
    )
    assert "@app.post(\"/api/phase5/approve\")" not in dashboard
    assert "@app.post(\"/api/phase5/grant\")" not in dashboard
    assert "@app.post(\"/api/phase5/dispatch\")" not in dashboard
    assert "from ui" not in integration_source
    assert "OnyxOrb" not in integration_source
