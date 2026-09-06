from scripts import verify_phase7_document_ingestion_v1_acceptance as acceptance


def test_phase7_document_ingestion_v1_external_acceptance() -> None:
    result = acceptance.verify(run_tests=False)
    assert result["decision"] == "accepted"
    assert result["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    claims = result["claims"]
    assert claims["document_ingestion_v1_accepted"] is True
    assert claims["required_formats"] is True
    assert claims["granular_citations"] is True
    assert claims["version_comparison"] is True
    assert claims["render_visual_qa"] is True
    assert claims["persistent_writes"] is False
    assert claims["instruction_authority"] is False
    assert claims["live_wiring"] is False
    assert claims["phase7_exit"] is False
