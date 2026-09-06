from scripts import verify_onyx_live_activation_v8_acceptance as acceptance


def test_v8_external_acceptance() -> None:
    result = acceptance.verify()
    assert result["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert (
        result["scope"]
        == "windows-source-shortcut-bootstrap-default-off-no-live-activation"
    )
