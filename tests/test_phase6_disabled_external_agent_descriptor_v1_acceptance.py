from __future__ import annotations

from scripts import (
    verify_phase6_disabled_external_agent_descriptor_v1_acceptance as gate,
)


def test_e6_acceptance_is_exact() -> None:
    result = gate.verify(run_candidate=False)
    assert result["decision"] == "accepted"
    assert result["artifacts"] == 5
    assert result["component_roots"] == 5
    assert result["focused"] == 40
    assert result["cumulative"] == 74
    assert result["live_files_checked"] == 205
    assert result["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert result["provider_calls"] == 0
    assert result["process_calls"] == 0
    assert result["network_calls"] == 0
    assert result["live_calls"] == 0
    assert result["authority_granted"] is False
    assert result["live_activation"] is False
    assert result["phase6_exit"] is False
