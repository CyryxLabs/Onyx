from scripts import (
    verify_phase7_approved_sources_company_graph_v1_acceptance as acceptance,
)


def test_phase7_sources_graph_v1_external_acceptance() -> None:
    result = acceptance.verify(run_tests=False)
    assert result["decision"] == "accepted"
    assert result["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    claims = result["claims"]
    assert claims["approved_sources_v1_accepted"] is True
    assert claims["company_graph_v1_accepted"] is True
    assert claims["source_rights_scoring_freshness"] is True
    assert claims["all_prd_knowledge_semantics"] is True
    assert claims["artifact_only_completion_denied"] is True
    assert claims["source_content_instruction_authority"] is False
    assert claims["url_fetch"] is False
    assert claims["artifact_content_read"] is False
    assert claims["graph_persistent_writes"] is False
    assert claims["automatic_contradiction_discovery"] is False
    assert claims["founder_brief_implemented"] is False
    assert claims["live_wiring"] is False
    assert claims["phase7_exit"] is False
    assert claims["full_onyx_prd_complete"] is False
