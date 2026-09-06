from pathlib import Path

import pytest

from core.argos_v1 import create_argos_registry_v1
from core.capability_ports.argos_v1 import ArgosCapabilityPortV1
from core.governance_nucleus_v1 import GovernanceV1Denied


def _port() -> ArgosCapabilityPortV1:
    registry = create_argos_registry_v1(Path(__file__).parents[1])
    registry.build({
        "sources": [{"source_id": "local-a", "kind": "official", "origin": "local-fixture", "rights_note": "test fixture"}],
        "signals": [{"signal_id": "signal-a", "category": "markets", "region": "ca", "headline": "Untrusted fixture", "source_id": "local-a", "observed_at": 1, "severity": 2, "confidence": 3}],
    })
    return ArgosCapabilityPortV1(registry)


def test_argos_only_returns_untrusted_non_actionable_local_state() -> None:
    result = _port()._dispatch_authorized("read.brief", {"limit": 1})
    assert result["source"] == "local-state-only"
    assert result["trust"] == "untrusted-content"
    assert result["actionable"] is False
    assert result["signals"][0]["headline"] == "Untrusted fixture"


def test_argos_rejects_actions_and_kill_is_distinct_from_close() -> None:
    port = _port()
    with pytest.raises(GovernanceV1Denied, match="local read"):
        port._dispatch_authorized("act.alert", {})
    assert port.close() == {"status": "closed", "killed": False}
    assert port.kill() == {"status": "kill-latched"}
