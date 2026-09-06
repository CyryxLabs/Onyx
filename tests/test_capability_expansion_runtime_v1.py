import json

import pytest

from core import permission_broker, tool_audit
from core.capability_expansion_runtime_v1 import (
    CAPABILITIES,
    CapabilityExpansionAuditError,
    CapabilityExpansionDenied,
    CapabilityExpansionRuntimeV1,
)


@pytest.fixture(autouse=True)
def canonical_authority(tmp_path, monkeypatch):
    monkeypatch.setattr(tool_audit, "AUDIT_PATH", tmp_path / "audit.sqlite3")
    monkeypatch.setattr(permission_broker, "_audit_healthy", True)
    permission_broker.set_permission_callback(lambda request: request["digest"])
    yield
    permission_broker.set_permission_callback(None)
    permission_broker._audit_healthy = True


def runtime():
    flags = {name: True for name in CAPABILITIES}
    return CapabilityExpansionRuntimeV1(enabled=flags, available=flags)


def test_exact_operation_is_broker_authorized_then_content_free_receipt_is_appended(monkeypatch):
    seen = []

    def owner(request):
        seen.append(request)
        return request["digest"]

    permission_broker.set_permission_callback(owner)
    bridge = runtime()
    result, receipt = bridge.dispatch(
        "social",
        "dispatch",
        lambda: "sent",
        binding={"request_digest": "a" * 64},
        trace_id="trace-safe",
    )

    assert result == "sent"
    assert seen[0]["action"] == "capability.social.dispatch"
    assert seen[0]["details"]["binding"] == {"operation_digest": receipt.operation_digest}
    assert tool_audit.verify_audit_reference(
        trace_id=receipt.trace_id, event_hash=receipt.audit_event_hash
    )
    with tool_audit._connect() as connection:
        event = connection.execute("SELECT * FROM events").fetchone()
    encoded = json.dumps(event)
    assert "request_digest" not in encoded
    assert "sent" not in encoded


def test_audit_unhealthy_fails_before_authorization_or_dispatch(monkeypatch):
    calls = []
    permission_broker.mark_audit_unhealthy()
    permission_broker.set_permission_callback(lambda request: calls.append(request))

    with pytest.raises(CapabilityExpansionDenied, match="audit is unhealthy"):
        runtime().dispatch("plugin", "execute", lambda: calls.append("dispatch"))
    assert calls == []


def test_kill_and_revoke_latches_block_before_dispatch():
    calls = []
    killed = runtime()
    killed.kill()
    with pytest.raises(CapabilityExpansionDenied, match="kill is latched"):
        killed.dispatch("clipboard", "preview", lambda: calls.append("clipboard"))

    revoked = runtime()
    revoked.revoke("wellness")
    with pytest.raises(CapabilityExpansionDenied, match="revoked"):
        revoked.dispatch("wellness", "create", lambda: calls.append("wellness"))
    assert calls == []


def test_latch_changed_during_authorization_is_rechecked_before_dispatch():
    bridge = runtime()

    def owner(request):
        bridge.revoke("plugin")
        return request["digest"]

    permission_broker.set_permission_callback(owner)
    with pytest.raises(CapabilityExpansionDenied, match="revoked"):
        bridge.dispatch("plugin", "execute", lambda: pytest.fail("dispatched"))


def test_audit_append_failure_marks_authority_unhealthy(monkeypatch):
    bridge = runtime()
    monkeypatch.setattr(
        "core.capability_expansion_runtime_v1.append_tool_audit_reference",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(CapabilityExpansionAuditError, match="audit append failed"):
        bridge.dispatch("social", "dispatch", lambda: "attempted")
    assert permission_broker.audit_healthy() is False


def test_authoritative_status_covers_all_expansion_domains():
    bridge = CapabilityExpansionRuntimeV1(
        enabled={"plugin": True, "clipboard": True, "wellness": True},
        available={"plugin": True, "clipboard": False, "wellness": True},
    )
    bridge.revoke("wellness")
    status = bridge.status()

    assert set(status) == CAPABILITIES
    assert status["plugin"]["status"] == "approved"
    assert status["clipboard"]["status"] == "unavailable"
    assert status["wellness"]["status"] == "disabled"
    assert status["personalization"]["status"] == "disabled"
    assert status["social"]["status"] == "disabled"
    assert all(item["authority"] == "core.permission_broker" for item in status.values())


def test_unknown_capability_or_operation_fails_closed():
    bridge = runtime()
    with pytest.raises(CapabilityExpansionDenied, match="unknown capability operation"):
        bridge.dispatch("social", "delete_everything", lambda: None)
    with pytest.raises(CapabilityExpansionDenied, match="unknown capability operation"):
        bridge.dispatch("email", "dispatch", lambda: None)
