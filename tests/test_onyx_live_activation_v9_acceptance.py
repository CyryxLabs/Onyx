from scripts import verify_onyx_live_activation_v9_acceptance as acceptance


def test_v9_external_acceptance():
    result = acceptance.verify()
    assert result["decision"] == "accepted"
    assert result["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
