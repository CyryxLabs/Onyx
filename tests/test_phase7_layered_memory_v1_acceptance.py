from scripts import verify_phase7_layered_memory_v1_acceptance as acceptance


def test_phase7_layered_memory_v1_external_acceptance() -> None:
    result = acceptance.verify(run_tests=False)
    assert result["decision"] == "accepted"
    assert result["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    claims = result["claims"]
    assert claims["layered_memory_v1_accepted"] is True
    assert claims["seven_typed_layers"] is True
    assert claims["workspace_principal_isolation"] is True
    assert claims["pre_ranking_hard_filters"] is True
    assert claims["correction_supersession_contradiction"] is True
    assert claims["retention_export_delete"] is True
    assert claims["source_deletion"] is True
    assert claims["poisoning_defenses"] is True
    assert claims["instruction_authority"] is False
    assert claims["global_vector_index"] is False
    assert claims["general_nlp_entity_extraction"] is False
    assert claims["accepted_workspace_memory_modified"] is False
    assert claims["live_wiring"] is False
    assert claims["phase7_exit"] is False
    assert claims["full_onyx_prd_complete"] is False
