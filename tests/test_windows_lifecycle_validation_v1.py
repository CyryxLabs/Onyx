from __future__ import annotations

import hashlib
import json
from subprocess import CompletedProcess
from pathlib import Path

import pytest

from scripts import windows_lifecycle_validation as lifecycle


ROOT = Path(__file__).resolve().parents[1]


def test_disposable_host_requires_exact_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lifecycle.platform, "system", lambda: "Windows")
    monkeypatch.setattr(lifecycle.platform, "machine", lambda: "AMD64")
    environment = {"LOCALAPPDATA": r"C:\Users\owner\AppData\Local"}
    with pytest.raises(lifecycle.WindowsLifecycleError, match="disposable-host token"):
        lifecycle.require_disposable_host(environment)
    environment["ONYX_DISPOSABLE_WINDOWS_CONFIRM"] = lifecycle.CONFIRMATION
    lifecycle.require_disposable_host(environment)


def test_setup_requires_exact_name_version_and_hash(tmp_path: Path) -> None:
    setup = tmp_path / "Onyx-1.1.9-Windows-x86_64-Setup.exe"
    setup.write_bytes(b"sealed-setup")
    digest = hashlib.sha256(b"sealed-setup").hexdigest()
    assert lifecycle.require_regular_setup(setup, digest, "1.1.9") == setup
    with pytest.raises(lifecycle.WindowsLifecycleError, match="filename/version"):
        lifecycle.require_regular_setup(setup, digest, "1.1.8")
    with pytest.raises(lifecycle.WindowsLifecycleError, match="SHA-256 mismatch"):
        lifecycle.require_regular_setup(setup, "0" * 64, "1.1.9")


def test_authenticode_requires_exact_signer_and_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signer = "A" * 40
    timestamp = "B" * 40
    payload = {
        "Status": "Valid",
        "Thumbprint": signer,
        "Subject": "CN=Cyryx Labs",
        "TimestampThumbprint": timestamp,
        "TimestampSubject": "CN=Trusted Timestamp",
    }
    monkeypatch.setattr(lifecycle, "_powershell", lambda: Path("powershell.exe"))
    monkeypatch.setattr(
        lifecycle.subprocess,
        "run",
        lambda *_args, **_kwargs: CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(payload), stderr=""
        ),
    )
    evidence = lifecycle.authenticode_identity(Path("Onyx.exe"), signer)
    assert evidence["thumbprint"] == signer
    assert evidence["timestamp_thumbprint"] == timestamp

    payload["TimestampThumbprint"] = ""
    with pytest.raises(lifecycle.WindowsLifecycleError, match="Authenticode"):
        lifecycle.authenticode_identity(Path("Onyx.exe"), signer)


def test_windows_lifecycle_contract_is_fail_closed_and_complete() -> None:
    source = (ROOT / "scripts" / "windows_lifecycle_validation.py").read_text(
        encoding="utf-8"
    )
    for contract in (
        "ONYX_DISPOSABLE_WINDOWS_LIFECYCLE_V1",
        "production_app_id",
        "clean_install_current",
        "uninstall_app_only",
        "reinstall_current",
        "upgrade_prior_to_current",
        "rollback_current_to_prior",
        "final_uninstall_app_only",
        "Get-AuthenticodeSignature",
        "TimestampThumbprint",
        "pe_product_version",
        "onyx.windows-lifecycle-evidence.v1",
        "--native-startup-smoke-test",
    ):
        assert contract in source
    assert "shutil.rmtree(app)" not in source
    assert "shutil.rmtree(Path.home())" not in source


def test_macos_lifecycle_uses_real_frozen_smoke_argument() -> None:
    from scripts import macos_lifecycle_validation as macos
    from core.native_startup_smoke_v1 import NATIVE_STARTUP_SMOKE_ARGUMENT

    assert macos.SMOKE_ARGUMENT == NATIVE_STARTUP_SMOKE_ARGUMENT
