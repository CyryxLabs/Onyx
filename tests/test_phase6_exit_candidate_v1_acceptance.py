from scripts import verify_phase6_exit_candidate_v1_acceptance as acceptance


def test_phase6_exit_candidate_v1_external_e6_acceptance() -> None:
    result = acceptance.verify()
    assert result["decision"] == "accepted"
    assert result["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert result["claims"]["phase6_exit_complete"] is True
    assert result["claims"]["phase7_default_off_implementation_unlocked"] is True
    assert result["claims"]["runtime_authority_added"] is False
    assert result["claims"]["full_onyx_prd_complete"] is False
