import pytest

from core.capability_ports.google_workspace_v1 import (
    GOOGLE_WORKSPACE_OPERATIONS,
    GoogleWorkspaceCapabilityPortV1,
    GoogleWorkspaceCapabilityPortV1Denied,
)
from core.google_workspace_connector_v1 import READ_SCOPES


class _Adapter:
    def __init__(self, calls, observed=None):
        self.calls = calls
        self.observed = observed

    def execute(self, arguments, *, trace_id):
        self.calls.append((arguments, trace_id))
        action = self.observed or arguments["action"]
        return {
            "action": action,
            "items": [{"subject": "private calendar content", "token": "secret"}],
            "receipt": {"receipt_digest": "a" * 64},
        }

    def close(self):
        self.calls.append("closed")


def _port(calls, *, enabled=True, observed=None):
    return GoogleWorkspaceCapabilityPortV1(
        adapter_factory=lambda: _Adapter(calls, observed), enabled=enabled,
        trace_factory=lambda: "trace-redacted",
    )


def test_operations_are_exact_concrete_actions_and_default_off_is_provider_free():
    assert GOOGLE_WORKSPACE_OPERATIONS == {
        "status", "connect", "disconnect", "list_gmail_messages",
        "list_calendar_events",
    }
    calls = []
    port = _port(calls, enabled=False)
    with pytest.raises(GoogleWorkspaceCapabilityPortV1Denied, match="disabled"):
        port._dispatch_authorized("status", {})
    assert calls == []


def test_status_constructs_no_adapter_and_reads_return_redacted_receipt():
    calls = []
    port = _port(calls)
    status = port._dispatch_authorized("status", {})
    assert status["provider_dispatch"] is False and status["scopes"] == READ_SCOPES
    assert calls == []
    receipt = port._dispatch_authorized("list_gmail_messages", {"query": "is:unread"})
    assert receipt["effect"] == "provider-read" and receipt["redacted"] is True
    assert "private calendar content" not in repr(receipt)
    assert "secret" not in repr(receipt)
    assert calls[-1] == "closed"


def test_disconnect_is_explicit_provider_revoke_but_host_revoke_is_local():
    calls = []
    port = _port(calls)
    assert port.revoke("binding-local") is None
    assert calls == []
    receipt = port._dispatch_authorized("disconnect", {})
    assert receipt["operation"] == "disconnect"
    assert receipt["effect"] == "external-mutation"
    assert len(calls) == 2


def test_provider_fence_rejects_wrong_identity_secret_and_operation_mismatch():
    calls = []
    port = _port(calls)
    for arguments in (
        {"workspace_id": "wrong"}, {"principal_id": "wrong"},
        {"refresh_token": "secret"}, {"action": "connect"},
    ):
        with pytest.raises(GoogleWorkspaceCapabilityPortV1Denied):
            port._dispatch_authorized("list_calendar_events", arguments)
    with pytest.raises(GoogleWorkspaceCapabilityPortV1Denied, match="mismatch"):
        _port(calls, observed="connect")._dispatch_authorized("list_gmail_messages", {})
    assert all("secret" not in repr(call) for call in calls)
