from scripts import verify_hud_orb_v6_c003_acceptance as acceptance


def test_hud_v6_c003_external_acceptance() -> None:
    result = acceptance.verify()
    assert result["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert result["scope"] == "windows-d3d11-default-off-no-live-activation"
