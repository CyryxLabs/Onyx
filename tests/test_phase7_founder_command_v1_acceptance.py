from scripts import verify_phase7_founder_command_v1_acceptance as acceptance


def test_phase7_founder_command_v1_external_acceptance() -> None:
    result = acceptance.verify(run_tests=False)
    assert result["decision"] == "accepted"
    assert result["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    claims = result["claims"]
    assert claims["founder_command_v1_accepted"] is True
    assert claims["daily_founder_brief"] is True
    assert claims["weekly_operating_review"] is True
    assert claims["portfolio_view"] is True
    assert claims["semantic_freshness_analysis"] is True
    assert claims["structured_status_conflict_detection"] is True
    assert claims["general_nlp_contradiction_discovery"] is False
    assert claims["invented_revenue_or_traction"] is False
    assert claims["persistent_writes"] is False
    assert claims["live_wiring"] is False
    assert claims["phase7_exit"] is False
    assert claims["full_onyx_prd_complete"] is False
