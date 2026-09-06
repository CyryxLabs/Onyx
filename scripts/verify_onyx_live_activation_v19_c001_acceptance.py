"""Verify the bounded Onyx Live V19.1 installed-host E6 record."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Final
import zipfile


ROOT: Final = Path(__file__).resolve().parents[1]
EVIDENCE_ID: Final = "VE-ONYX-LIVE-ACTIVATION-V19-C001-E6-001"
RECORD: Final = ROOT / f"docs/onyx/acceptance/{EVIDENCE_ID}.md"
METADATA: Final = RECORD.with_suffix(".manifest.json")
OBSERVATION: Final = (
    ROOT
    / "docs/onyx/checkpoints/onyx-live-activation-v19-c001/"
    "installed-host-observation.json"
)
OPERATIONS: Final = (
    ROOT / "docs/onyx/operations/ONYX_V19_1_OPERATIONAL_CLOSURE_2026-08-01.md"
)
HISTORICAL_RELEASE: Final = ROOT / "rollback/releases/onyx-1.0.0-v19.1"
RELEASE_MANIFEST: Final = HISTORICAL_RELEASE / "release-manifest-Windows-x64.json"
EXPECTED_ACTIVATION: Final = {
    "contract": "OnyxHostActivation.v1",
    "normal_activation": "v19",
    "smoke_activation": "v19",
    "activation_profile": "current-windows",
    "capability_limited": False,
    "v15_v19_parity": True,
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise AssertionError(f"object JSON required: {path}")
    return value


def canonical_install_root() -> Path:
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if not local:
        raise AssertionError("LOCALAPPDATA is required for installed-host verification")
    return Path(local) / "Programs/Cyryx Labs/Onyx"


def _verify_file(path: Path, record: dict[str, object]) -> None:
    assert path.is_file(), path
    assert path.stat().st_size == record["size"], path
    assert digest(path) == record["sha256"], path


def _verify_zip_member(
    archive: zipfile.ZipFile,
    member_name: str,
    record: dict[str, object],
) -> None:
    info = archive.getinfo(member_name)
    assert info.file_size == record["size"], member_name
    value = hashlib.sha256()
    with archive.open(info, "r") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    assert value.hexdigest() == record["sha256"], member_name


def verify(*, require_installed: bool = False) -> dict[str, object]:
    metadata = _load(METADATA)
    evidence = _load(OBSERVATION)
    release = _load(RELEASE_MANIFEST)

    assert metadata["schema"] == "onyx.operational-acceptance.v1"
    assert metadata["acceptance_id"] == EVIDENCE_ID
    assert metadata["decision"] == "accepted_bounded_windows_owner_host"
    assert metadata["runtime_changed"] is False
    assert metadata["accepted"] == {
        "build": True,
        "install": True,
        "preflight": True,
        "native_startup_smoke": True,
        "responsive_process": True,
        "command_response": "owner_observed_manual",
    }
    assert metadata["pending"] == {
        "microsoft_graph_live": True,
        "clean_machine": True,
        "authenticode_signing": True,
        "macos_linux_current_parity": True,
    }
    assert release["product"] == "Onyx"
    assert release["publisher"] == "Cyryx Labs"
    assert release["system"] == "Windows"
    assert release["architecture"] == "x64"
    assert release["activation_contract"] == EXPECTED_ACTIVATION

    release_evidence = evidence["release"]
    assert type(release_evidence) is dict
    for key in ("manifest", "checksums"):
        item = release_evidence[key]
        assert type(item) is dict
        _verify_file(ROOT / str(item["path"]), item)
    artifacts = release_evidence["artifacts"]
    assert type(artifacts) is list and len(artifacts) == 2
    for item in artifacts:
        assert type(item) is dict
        _verify_file(ROOT / str(item["path"]), item)

    artifact_rows = {item["name"]: item for item in release["artifacts"]}
    assert set(artifact_rows) == {Path(str(item["path"])).name for item in artifacts}
    for item in artifacts:
        row = artifact_rows[Path(str(item["path"])).name]
        assert row["size"] == item["size"]
        assert row["sha256"] == item["sha256"]

    command = evidence["command_response"]
    assert command == {
        "evidence_class": "owner_observed_manual",
        "prompt": "Responda apenas: ONYX ONLINE.",
        "observed_response": "ONYX ONLINE.",
        "durable_receipt": False,
        "machine_replayable": False,
    }
    assert evidence["explicitly_not_verified"] == metadata["pending"]
    assert evidence["signing_observation"] == {
        "setup": "NotSigned",
        "installed_executable": "NotSigned",
    }
    native = evidence["installed_validation"]["native_startup_smoke"]
    assert native == {
        "contract": "OnyxNativeStartupSmoke.v1",
        "status": "passed",
        "activation": "v19",
        "activation_profile": "current-windows",
        "renderer": "cinematic-v5",
        "capability_limited": False,
        "v15_v19_parity": True,
        "host_constructed": True,
        "callbacks_bound": True,
        "real_ui": True,
        "network_calls": 0,
        "provider_calls": 0,
        "process_calls": 0,
    }

    portable = next(
        ROOT / str(item["path"])
        for item in artifacts
        if str(item["path"]).endswith("-Portable.zip")
    )
    installed_verified = portable.is_file()
    if require_installed and not installed_verified:
        raise AssertionError(f"historical portable payload is missing: {portable}")
    if installed_verified:
        with zipfile.ZipFile(portable, "r") as archive:
            names = set(archive.namelist())
            for item in evidence["canonical_install"]["installed_files"]:
                assert type(item) is dict and item["bundle_match"] is True
                member_name = f"Onyx/{Path(str(item['path'])).as_posix()}"
                assert member_name in names, member_name
                _verify_zip_member(archive, member_name, item)

    record = RECORD.read_text(encoding="utf-8")
    operations = OPERATIONS.read_text(encoding="utf-8")
    for required in (
        "owner_observed_manual",
        "real Microsoft Graph",
        "clean-machine",
        "Authenticode",
        "macOS/Linux",
    ):
        assert required in record or required in operations

    for item in metadata["new_artifacts"]:
        assert type(item) is dict
        _verify_file(ROOT / str(item["path"]), item)

    return {
        "acceptance_id": EVIDENCE_ID,
        "decision": metadata["decision"],
        "installed_payload_verified": installed_verified,
        "release_artifacts_verified": len(artifacts),
        "historical_release_verified": True,
        "runtime_changed": False,
        "microsoft_graph_live": False,
        "clean_machine": False,
        "signed": False,
        "command_response": "owner_observed_manual",
    }


if __name__ == "__main__":
    print(
        "ONYX_LIVE_ACTIVATION_V19_C001_ACCEPTANCE_OK",
        json.dumps(verify(require_installed=True), sort_keys=True),
    )
