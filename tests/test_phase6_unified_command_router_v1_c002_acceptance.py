from __future__ import annotations

from scripts import verify_phase6_unified_command_router_v1_c002_acceptance as gate


def test_e6_acceptance_is_exact() -> None:
    result = gate.verify(run_candidate=False)
    assert result["decision"] == "accepted"
    assert result["artifacts"] == 5
    assert result["component_roots"] == 14
    assert result["focused"] == 27
    assert result["cumulative"] == 154
    assert result["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert result["network_calls"] == 0
    assert result["process_calls"] == 0
    assert result["provider_calls"] == 0
    assert result["live_calls"] == 0
    assert result["live_activation"] is False
    assert result["phase6_exit"] is False
