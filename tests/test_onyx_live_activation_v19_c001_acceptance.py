from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ID = "VE-ONYX-LIVE-ACTIVATION-V19-C001-E6-001"
RECORD = ROOT / f"docs/onyx/acceptance/{ID}.md"
METADATA = RECORD.with_suffix(".manifest.json")
OBSERVATION = (
    ROOT
    / "docs/onyx/checkpoints/onyx-live-activation-v19-c001/"
    "installed-host-observation.json"
)


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert type(value) is dict
    return value


def test_v19_c001_acceptance_is_narrow_and_runtime_unchanged() -> None:
    metadata = _load(METADATA)
    assert metadata["acceptance_id"] == ID
    assert metadata["decision"] == "accepted_bounded_windows_owner_host"
    assert metadata["runtime_changed"] is False
    assert metadata["pending"] == {
        "microsoft_graph_live": True,
        "clean_machine": True,
        "authenticode_signing": True,
        "macos_linux_current_parity": True,
    }
    assert all(
        not str(item["path"]).startswith(("core/", "scripts/bootstrap_", "ui.py"))
        for item in metadata["new_artifacts"]
    )


def test_v19_c001_command_response_remains_manual_only() -> None:
    command = _load(OBSERVATION)["command_response"]
    assert command["evidence_class"] == "owner_observed_manual"
    assert command["observed_response"] == "ONYX ONLINE."
    assert command["durable_receipt"] is False
    assert command["machine_replayable"] is False


def test_v19_c001_native_smoke_contract_is_provider_free() -> None:
    evidence = _load(OBSERVATION)
    native = evidence["installed_validation"]["native_startup_smoke"]
    assert native["contract"] == "OnyxNativeStartupSmoke.v1"
    assert native["activation"] == "v19"
    assert native["activation_profile"] == "current-windows"
    assert native["renderer"] == "cinematic-v5"
    assert native["host_constructed"] is True
    assert native["callbacks_bound"] is True
    assert native["real_ui"] is True
    assert native["network_calls"] == 0
    assert native["provider_calls"] == 0
    assert native["process_calls"] == 0


def test_v19_c001_record_refuses_release_and_provider_overclaim() -> None:
    content = RECORD.read_text(encoding="utf-8")
    for required in (
        "real Microsoft Graph",
        "clean-machine",
        "Authenticode",
        "macOS/Linux",
        "not a declaration that Onyx is complete",
    ):
        assert required in content


def test_v19_c001_acceptance_verifier_reproduces_historical_artifacts() -> None:
    result = subprocess.run(
        [
            str(ROOT / ".venv/Scripts/python.exe"),
            "-B",
            "scripts/verify_onyx_live_activation_v19_c001_acceptance.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ONYX_LIVE_ACTIVATION_V19_C001_ACCEPTANCE_OK" in result.stdout
    assert '"installed_payload_verified": true' in result.stdout
    assert '"historical_release_verified": true' in result.stdout
    assert '"microsoft_graph_live": false' in result.stdout
    assert '"command_response": "owner_observed_manual"' in result.stdout
