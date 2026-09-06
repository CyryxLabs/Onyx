from dataclasses import dataclass

import pytest

from core.capability_ports.graph_v1 import (
    GRAPH_MAIL_SCOPES,
    GraphCapabilityPortV1,
    GraphCapabilityPortV1Denied,
    GraphOperationV1,
)


@dataclass(frozen=True)
class _Result:
    operation: str
    content: str
    token: str


class _Resource:
    def __init__(self, calls, operation="send_mail"):
        self.calls = calls
        self.operation = operation

    def send(self, **arguments):
        self.calls.append(arguments)
        return _Result(self.operation, "private message body", "bearer-secret")

    def disconnect(self, **arguments):
        self.calls.append(arguments)
        return {"deleted": True}

    def close(self):
        self.calls.append("closed")


def _port(calls, *, enabled=True, observed="send_mail"):
    return GraphCapabilityPortV1(
        enabled=enabled,
        operations={
            "send_mail": GraphOperationV1(
                lambda: _Resource(calls, observed), "send", "external-mutation",
                GRAPH_MAIL_SCOPES,
            )
        },
    )


def test_default_off_status_and_construction_are_provider_free():
    calls = []
    port = _port(calls, enabled=False)
    assert port.status()["provider_dispatch"] is False
    assert calls == []
    with pytest.raises(GraphCapabilityPortV1Denied, match="disabled"):
        port._dispatch_authorized("send_mail", {})
    assert calls == []


def test_external_mutation_is_exact_and_receipt_redacts_content_and_token():
    calls = []
    receipt = _port(calls)._dispatch_authorized("send_mail", {"draft": "digest-only"})
    assert receipt["effect"] == "external-mutation"
    assert receipt["scopes"] == GRAPH_MAIL_SCOPES
    assert receipt["redacted"] is True
    assert "private message body" not in repr(receipt)
    assert "bearer-secret" not in repr(receipt)
    assert calls == [{"draft": "digest-only"}, "closed"]


def test_provider_fence_authority_fields_unknown_and_operation_mismatch():
    calls = []
    port = _port(calls)
    for arguments in (
        {"workspace_id": "wrong"}, {"principal_id": "wrong"},
        {"access_token": "secret"},
    ):
        with pytest.raises(GraphCapabilityPortV1Denied, match="host-owned"):
            port._dispatch_authorized("send_mail", arguments)
    with pytest.raises(GraphCapabilityPortV1Denied, match="unknown"):
        port._dispatch_authorized("delete_mail", {})
    with pytest.raises(GraphCapabilityPortV1Denied, match="operation mismatch"):
        _port(calls, observed="create_event")._dispatch_authorized("send_mail", {})
    assert all("secret" not in repr(call) for call in calls)


def test_revoke_is_local_and_kill_closes_resources_without_model_result():
    calls = []
    port = _port(calls)
    assert port.revoke("binding-one") is None
    assert calls == []
    assert port.kill() is True
    with pytest.raises(GraphCapabilityPortV1Denied, match="killed"):
        port._dispatch_authorized("send_mail", {})
    assert calls == []
