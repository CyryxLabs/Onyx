from scripts import verify_phase7_exit_candidate_v1_acceptance as acceptance


def test_phase7_exit_candidate_v1_external_acceptance() -> None:
    result = acceptance.verify(run_tests=False)
    assert result["decision"] == "accepted"
    assert result["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    claims = result["claims"]
    assert claims["phase7_default_off_implementation_complete"] is True
    assert claims["phase8_may_begin"] is True
    assert claims["live_wiring"] is False
    assert claims["runtime_authority_added"] is False
    assert claims["full_onyx_prd_complete"] is False
