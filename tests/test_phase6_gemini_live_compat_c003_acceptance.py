from scripts import verify_phase6_gemini_live_compat_c003_acceptance as acceptance


def test_gemini_live_compat_c003_external_acceptance() -> None:
    result = acceptance.verify()
    assert result["decision"] == "accepted"
    assert result["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert result["live_activated"] is False
