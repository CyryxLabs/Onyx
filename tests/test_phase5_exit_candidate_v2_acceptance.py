from scripts import verify_phase5_exit_candidate_v2_acceptance as acceptance


def test_phase5_exit_candidate_v2_external_acceptance() -> None:
    result = acceptance.verify()
    assert result["decision"] == "accepted"
    assert result["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert result["phase6_unlocked"] is False
