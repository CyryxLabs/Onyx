from __future__ import annotations

import json
import socket
import subprocess
import webbrowser

import pytest

from scripts import onyx_capabilities_cli


def _forbidden(*args: object, **kwargs: object) -> object:
    del args, kwargs
    raise AssertionError("external boundary reached")


@pytest.mark.parametrize("command", ("status", "readiness", "list", "safe-test"))
def test_cli_is_deterministic_redacted_and_provider_free(
    command: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", _forbidden)
    monkeypatch.setattr(webbrowser, "open", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)

    assert onyx_capabilities_cli.main([command]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "OnyxCapabilitiesCLI.v1"
    assert payload["command"] == command
    assert payload["ok"] is True
    encoded = json.dumps(payload, sort_keys=True)
    assert "\\\\" not in encoded
    assert "C:" not in encoded
    assert "token" not in encoded.lower()
    if command == "safe-test":
        assert payload["result"]["families_denied"] == [
            "argos", "budget", "command_center", "evidence", "google_workspace", "graph",
            "guild", "intelligence", "knowledge_refinery", "mission_context", "model_router",
            "nexus", "plugin", "project_execution", "social", "strategy", "workspace"
        ]
        assert payload["result"]["kill_status"] == "kill-latched"
        assert payload["result"]["provider_dispatch"] is False
        assert payload["result"]["policy_only_families"] == [
            "budget", "command_center", "guild", "intelligence", "knowledge_refinery",
            "model_router", "project_execution", "strategy"
        ]
        assert payload["result"]["local_operational"]["families"] == [
            "clipboard", "personalization", "plugin", "social", "wellness"
        ]
        assert payload["result"]["local_operational"]["publishing"] == (
            "oauth-adapter-required"
        )
        receipts = payload["result"]["local_operational"]["receipts"]
        assert len(receipts) == 9
        assert all(
            receipt["decision"] == "allow"
            and receipt["outcome"] == "dispatched"
            for receipt in receipts
        )
