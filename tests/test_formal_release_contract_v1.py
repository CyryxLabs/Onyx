from __future__ import annotations

import json
import hashlib
import zipfile
from pathlib import Path

import pytest

from scripts import build_release, windows_native_eligibility, windows_release


ROOT = Path(__file__).resolve().parents[1]


def test_windows_formal_environment_is_explicit_and_cyryx_bound() -> None:
    with pytest.raises(windows_release.WindowsReleaseError, match="incomplete"):
        windows_release.require_formal_environment({})
    valid = {
        "ONYX_WINDOWS_SIGN_CERT_THUMBPRINT": "a" * 40,
        "ONYX_WINDOWS_SIGN_EXPECTED_SUBJECT": "CN=Cyryx Labs LLC",
        "ONYX_WINDOWS_TIMESTAMP_URL": "https://timestamp.example.invalid",
    }
    assert windows_release.require_formal_environment(valid)[
        "ONYX_WINDOWS_SIGN_CERT_THUMBPRINT"
    ] == "A" * 40
    with pytest.raises(windows_release.WindowsReleaseError, match="Cyryx Labs"):
        windows_release.require_formal_environment(
            {**valid, "ONYX_WINDOWS_SIGN_EXPECTED_SUBJECT": "CN=Other Publisher"}
        )


def _native_fixture(tmp_path: Path, *, unsafe_member: str | None = None) -> Path:
    release = tmp_path / "release"
    release.mkdir(parents=True)
    setup = release / "Onyx-9.9.9-Windows-x64-Setup.exe"
    setup.write_bytes(b"MZ-signed-setup")
    portable = release / "Onyx-9.9.9-Windows-x64-Portable.zip"
    with zipfile.ZipFile(portable, "w") as archive:
        archive.writestr(unsafe_member or "Onyx/Onyx.exe", b"MZ-signed-app")
        archive.writestr("Onyx/_internal/native.dll", b"MZ-signed-dll")
    artifacts = []
    for path in (setup, portable):
        artifacts.append(
            {
                "name": path.name,
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    (release / "release-manifest-Windows-x64.json").write_text(
        json.dumps(
            {
                "product": "Onyx",
                "version": "9.9.9",
                "system": "Windows",
                "architecture": "x64",
                "release_class": "formal",
                "artifacts": artifacts,
            }
        ),
        encoding="utf-8",
    )
    return release


def _native_environment() -> dict[str, str]:
    return {
        "ONYX_WINDOWS_SIGN_CERT_THUMBPRINT": "A" * 40,
        "ONYX_WINDOWS_SIGN_EXPECTED_SUBJECT": "CN=Cyryx Labs LLC",
        "ONYX_WINDOWS_TIMESTAMP_URL": "https://timestamp.example.invalid",
    }


def _valid_native_signature(*args: object, **kwargs: object) -> dict[str, object]:
    return {
        "status": "Valid",
        "subject": "CN=Cyryx Labs LLC",
        "thumbprint": "A" * 40,
        "timestamp_subject": "CN=Timestamp Authority",
        "timestamp_thumbprint": "B" * 40,
    }


def test_formal_windows_eligibility_refuses_attestation_off_windows(tmp_path: Path) -> None:
    release = _native_fixture(tmp_path)
    (release / "windows-release-evidence-x64.json").write_text(
        json.dumps({"all_trusted": True, "authenticode_status": "Valid"}),
        encoding="utf-8",
    )
    with pytest.raises(
        windows_native_eligibility.WindowsNativeEligibilityRefusal,
        match="WINDOWS_NATIVE_VERIFICATION_REQUIRED",
    ):
        windows_native_eligibility.verify_formal_windows_release(
            release_dir=release,
            version="9.9.9",
            architecture="x64",
            system="Linux",
        )


def test_native_gate_verifies_setup_and_every_portable_pe(tmp_path: Path) -> None:
    release = _native_fixture(tmp_path)
    observed: list[bytes] = []

    def verifier(path: Path, **_: object) -> dict[str, object]:
        observed.append(path.read_bytes())
        return _valid_native_signature()

    receipt = windows_native_eligibility.verify_formal_windows_release(
        release_dir=release,
        version="9.9.9",
        architecture="x64",
        environment=_native_environment(),
        system="Windows",
        verifier=verifier,
        signtool=Path(__file__),
    )
    assert observed == [b"MZ-signed-setup", b"MZ-signed-app", b"MZ-signed-dll"]
    assert {item["path"] for item in receipt["verified_pe_files"]} == {
        "Onyx-9.9.9-Windows-x64-Setup.exe",
        "Onyx/Onyx.exe",
        "Onyx/_internal/native.dll",
    }


def test_forged_json_and_synthetic_pe_cannot_pass_native_gate(tmp_path: Path) -> None:
    release = _native_fixture(tmp_path)
    (release / "windows-release-evidence-x64.json").write_text(
        json.dumps(
            {
                "formal": True,
                "all_trusted": True,
                "authenticode_status": "Valid",
                "signer_subject": "CN=Cyryx Labs LLC",
            }
        ),
        encoding="utf-8",
    )

    def reject_synthetic(path: Path, **_: object) -> dict[str, object]:
        raise windows_release.WindowsReleaseError(
            f"WinVerifyTrust rejected synthetic PE: {path.name}"
        )

    with pytest.raises(windows_release.WindowsReleaseError, match="synthetic PE"):
        windows_native_eligibility.verify_formal_windows_release(
            release_dir=release,
            version="9.9.9",
            architecture="x64",
            environment=_native_environment(),
            system="Windows",
            verifier=reject_synthetic,
            signtool=Path(__file__),
        )


def test_native_gate_rejects_hash_drift_and_archive_escape(tmp_path: Path) -> None:
    release = _native_fixture(tmp_path)
    setup = release / "Onyx-9.9.9-Windows-x64-Setup.exe"
    setup.write_bytes(setup.read_bytes() + b"tamper")
    with pytest.raises(
        windows_native_eligibility.WindowsNativeEligibilityRefusal,
        match="WINDOWS_ARTIFACT_DRIFT",
    ):
        windows_native_eligibility.verify_formal_windows_release(
            release_dir=release,
            version="9.9.9",
            architecture="x64",
            environment=_native_environment(),
            system="Windows",
            verifier=_valid_native_signature,
            signtool=Path(__file__),
        )

    escaped = _native_fixture(tmp_path / "escaped", unsafe_member="../forged.exe")
    with pytest.raises(
        windows_native_eligibility.WindowsNativeEligibilityRefusal,
        match="WINDOWS_PORTABLE_PATH_UNSAFE",
    ):
        windows_native_eligibility.verify_formal_windows_release(
            release_dir=escaped,
            version="9.9.9",
            architecture="x64",
            environment=_native_environment(),
            system="Windows",
            verifier=_valid_native_signature,
            signtool=Path(__file__),
        )


def test_manifest_writer_never_labels_default_local_build_formal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = tmp_path / "release"
    release.mkdir()
    artifact = release / "artifact.bin"
    artifact.write_bytes(b"candidate")
    seal = tmp_path / "seal.json"
    seal.write_text("{}", encoding="utf-8")
    snapshot = {
        "contract": "OnyxPyInstallerFirstPartyInputs.v1",
        "file_count": 0,
        "root_sha256": "a" * 64,
    }
    monkeypatch.setattr(build_release, "RELEASE", release)
    monkeypatch.setattr(build_release, "load_verified_build_input_seal", lambda: (snapshot, seal))
    monkeypatch.setattr(build_release.platform, "system", lambda: "Windows")
    monkeypatch.setattr(build_release, "architecture", lambda: "x64")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    from scripts import runtime_distribution_inventory

    monkeypatch.setattr(
        runtime_distribution_inventory,
        "write_bundle_inventory",
        lambda **kwargs: _write_inventory(kwargs["output"]),
    )

    build_release.write_manifest("1.2.3", [artifact], bundle=bundle)

    manifest = json.loads(
        (release / "release-manifest-Windows-x64.json").read_text(encoding="utf-8")
    )
    assert manifest["release_class"] == "untrusted-candidate"
    assert manifest["release_trust"]["formal_requested"] is False


def _write_inventory(path: Path) -> dict[str, object]:
    payload = {
        "contract": "OnyxBundleInventory.v1",
        "bundleRootSha256": "b" * 64,
        "fileCount": 0,
        "runtimeDistributionCount": 0,
        "runtimeDistributionRootSha256": "c" * 64,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def test_tag_workflow_cannot_upload_or_publish_unsigned_windows() -> None:
    workflow = (ROOT / ".github/workflows/release-packages.yml").read_text(
        encoding="utf-8"
    )
    for required in (
        "WINDOWS_CODE_SIGNING_PFX_BASE64",
        "WINDOWS_CODE_SIGNING_PFX_PASSWORD",
        "--formal-release",
        "ONYX_LEGAL_RELEASE_APPROVED",
        "ONYX_LINUX_UNSIGNED_RELEASE_APPROVED",
        "--linux-signing-policy unsigned-approved",
        "--required-target Windows-x64",
        "--required-target Darwin-arm64",
        "--required-target Linux-x64",
        "--required-target Linux-arm64",
        "windows-formal-eligibility",
        "python -m scripts.windows_native_eligibility",
        "--trusted-windows-receipt-sha256",
        "publish_qualified",
        "qualified_build_run_id",
        "qualification_run_id",
        "WINDOWS_RECEIPT_SHA",
        "run-id: ${{ inputs.qualified_build_run_id }}",
    ):
        assert required in workflow
    windows_source = (ROOT / "scripts/windows_release.py").read_text(encoding="utf-8")
    assert "Get-AuthenticodeSignature" in windows_source
    assert '"verify", "/pa", "/all", "/v"' in windows_source
    windows_import = workflow.index("Require and import trusted Windows publisher certificate")
    build = workflow.index("Build native package and prove portable safe-unavailability boundary")
    upload = workflow.index("Upload native artifacts")
    eligibility = workflow.index("Enforce public release eligibility")
    publish = workflow.index("Publish GitHub release")
    assert windows_import < build < upload < eligibility < publish
    publish_job = workflow.index("  publish:")
    publish_gate = workflow.index(
        "inputs.publish_qualified == true",
        publish_job,
    )
    exact_download = workflow.index("Download exact qualified build artifacts")
    assert publish_job < publish_gate < exact_download < eligibility < publish
