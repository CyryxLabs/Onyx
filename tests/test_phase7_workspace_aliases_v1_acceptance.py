from scripts import verify_phase7_workspace_aliases_v1_acceptance as acceptance


def test_phase7_workspace_aliases_v1_external_acceptance() -> None:
    result = acceptance.verify(run_tests=False)
    assert result["decision"] == "accepted"
    assert result["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert result["claims"]["workspace_aliases_v1_accepted"] is True
    assert result["claims"]["credential_aliases"] is True
    assert result["claims"]["profile_aliases"] is True
    assert result["claims"]["artifact_aliases"] is True
    assert result["claims"]["secret_storage"] is False
    assert result["claims"]["secret_resolution"] is False
    assert result["claims"]["live_wiring"] is False
    assert result["claims"]["phase7_exit"] is False
    assert result["claims"]["full_onyx_prd_complete"] is False
