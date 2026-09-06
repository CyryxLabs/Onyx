"""Disposable-host lifecycle acceptance for production Onyx Setups.

The harness is intentionally destructive only inside the exact per-user Onyx
application and owner-data paths. It refuses to run without an explicit
disposable-host token, trusted Authenticode signatures, exact artifact hashes,
the production Inno Setup AppId, and a clean Windows x64 host. Evidence is
written outside both managed paths.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

try:
    import winreg
except ImportError:  # pragma: no cover - unavailable on non-Windows test hosts
    winreg = None  # type: ignore[assignment]


PRODUCTION_APP_ID = "{8F04E3B8-E681-4E10-9AC7-58EC1605CA4D}"
UNINSTALL_KEY = (
    "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\"
    + PRODUCTION_APP_ID
    + "_is1"
)
CONFIRMATION = "ONYX_DISPOSABLE_WINDOWS_LIFECYCLE_V1"
SMOKE_ARGUMENT = "--native-startup-smoke-test"
SMOKE_OUTPUT_ENV = "ONYX_NATIVE_STARTUP_SMOKE_OUTPUT"
SETUP_NAME = re.compile(
    r"Onyx-(?P<version>[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?)"
    r"-Windows-(?P<architecture>[A-Za-z0-9._-]+)-Setup\.exe"
)
SHA256 = re.compile(r"[0-9a-f]{64}")
THUMBPRINT = re.compile(r"[0-9A-F]{40,64}")


class WindowsLifecycleError(RuntimeError):
    """The lifecycle host, artifact, install, or evidence failed closed."""


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _canonical_paths(environment: dict[str, str] | None = None) -> tuple[Path, Path]:
    env = os.environ if environment is None else environment
    local = env.get("LOCALAPPDATA", "").strip()
    if not local:
        raise WindowsLifecycleError("LOCALAPPDATA is unavailable")
    root = _absolute_lexical(Path(local))
    return (
        root / "Programs" / "Cyryx Labs" / "Onyx",
        root / "Cyryx Labs" / "Onyx",
    )


def _is_reparse(path: Path) -> bool:
    try:
        attributes = os.lstat(path).st_file_attributes
    except (AttributeError, FileNotFoundError):
        return False
    return bool(attributes & 0x400)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_disposable_host(environment: dict[str, str] | None = None) -> None:
    env = os.environ if environment is None else environment
    if platform.system() != "Windows":
        raise WindowsLifecycleError("native Windows host is required")
    if platform.machine().casefold() not in {"amd64", "x86_64"}:
        raise WindowsLifecycleError("Windows x64 host is required")
    if env.get("ONYX_DISPOSABLE_WINDOWS_CONFIRM") != CONFIRMATION:
        raise WindowsLifecycleError(
            "set ONYX_DISPOSABLE_WINDOWS_CONFIRM to the exact disposable-host token"
        )
    app, data = _canonical_paths(env)
    expected = _absolute_lexical(Path(env["LOCALAPPDATA"]))
    if app != expected / "Programs" / "Cyryx Labs" / "Onyx":
        raise WindowsLifecycleError("application target contract drifted")
    if data != expected / "Cyryx Labs" / "Onyx":
        raise WindowsLifecycleError("owner-data target contract drifted")


def require_regular_setup(
    path: Path,
    expected_sha256: str,
    expected_version: str,
) -> Path:
    candidate = _absolute_lexical(path)
    if (
        not candidate.is_file()
        or candidate.is_symlink()
        or _is_reparse(candidate)
    ):
        raise WindowsLifecycleError(f"Setup is not a regular file: {candidate}")
    match = SETUP_NAME.fullmatch(candidate.name)
    if match is None or match.group("version") != expected_version:
        raise WindowsLifecycleError(f"Setup filename/version mismatch: {candidate.name}")
    expected = expected_sha256.casefold()
    if SHA256.fullmatch(expected) is None:
        raise WindowsLifecycleError("expected Setup SHA-256 is malformed")
    if sha256_file(candidate) != expected:
        raise WindowsLifecycleError(f"Setup SHA-256 mismatch: {candidate.name}")
    return candidate


def require_evidence_directory(path: Path) -> Path:
    candidate = _absolute_lexical(path)
    app, data = _canonical_paths()
    for managed in (app, data):
        if candidate == managed or managed in candidate.parents:
            raise WindowsLifecycleError(
                "evidence must be outside application and owner-data paths"
            )
    if candidate.exists() and (
        candidate.is_symlink() or _is_reparse(candidate) or not candidate.is_dir()
    ):
        raise WindowsLifecycleError("evidence path is not a regular directory")
    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def _powershell() -> Path:
    system_root = os.environ.get("SystemRoot", "").strip()
    candidate = _absolute_lexical(
        Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )
    if not system_root or not candidate.is_file() or candidate.is_symlink():
        raise WindowsLifecycleError("trusted Windows PowerShell is unavailable")
    return candidate


def authenticode_identity(path: Path, expected_thumbprint: str) -> dict[str, str]:
    expected = expected_thumbprint.replace(" ", "").upper()
    if THUMBPRINT.fullmatch(expected) is None:
        raise WindowsLifecycleError("expected signer thumbprint is malformed")
    escaped = str(path).replace("'", "''")
    script = (
        "$ErrorActionPreference='Stop';"
        f"$s=Get-AuthenticodeSignature -LiteralPath '{escaped}';"
        "[pscustomobject]@{Status=[string]$s.Status;"
        "Thumbprint=[string]$s.SignerCertificate.Thumbprint;"
        "Subject=[string]$s.SignerCertificate.Subject;"
        "TimestampThumbprint=[string]$s.TimeStamperCertificate.Thumbprint;"
        "TimestampSubject=[string]$s.TimeStamperCertificate.Subject}"
        "|ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        [str(_powershell()), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False,
        timeout=60,
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise WindowsLifecycleError("Authenticode evidence is not valid JSON") from exc
    observed = str(payload.get("Thumbprint", "")).replace(" ", "").upper()
    timestamp = (
        str(payload.get("TimestampThumbprint", "")).replace(" ", "").upper()
    )
    if (
        result.returncode != 0
        or payload.get("Status") != "Valid"
        or observed != expected
        or THUMBPRINT.fullmatch(timestamp) is None
        or not str(payload.get("TimestampSubject", "")).strip()
    ):
        raise WindowsLifecycleError(f"trusted Authenticode validation failed: {path.name}")
    return {
        "status": "Valid",
        "thumbprint": observed,
        "subject": str(payload.get("Subject", "")),
        "timestamp_thumbprint": timestamp,
        "timestamp_subject": str(payload.get("TimestampSubject", "")),
    }


class _VS_FIXEDFILEINFO(ctypes.Structure):
    _fields_ = [
        ("dwSignature", wintypes.DWORD),
        ("dwStrucVersion", wintypes.DWORD),
        ("dwFileVersionMS", wintypes.DWORD),
        ("dwFileVersionLS", wintypes.DWORD),
        ("dwProductVersionMS", wintypes.DWORD),
        ("dwProductVersionLS", wintypes.DWORD),
        ("dwFileFlagsMask", wintypes.DWORD),
        ("dwFileFlags", wintypes.DWORD),
        ("dwFileOS", wintypes.DWORD),
        ("dwFileType", wintypes.DWORD),
        ("dwFileSubtype", wintypes.DWORD),
        ("dwFileDateMS", wintypes.DWORD),
        ("dwFileDateLS", wintypes.DWORD),
    ]


def pe_product_version(path: Path) -> str:
    if platform.system() != "Windows":
        raise WindowsLifecycleError("PE version validation requires Windows")
    version = ctypes.WinDLL("version", use_last_error=True)
    size = version.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        raise WindowsLifecycleError(f"PE version resource is unavailable: {path.name}")
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(str(path), 0, size, buffer):
        raise WindowsLifecycleError(f"PE version resource read failed: {path.name}")
    pointer = ctypes.c_void_p()
    length = wintypes.UINT()
    if not version.VerQueryValueW(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
        raise WindowsLifecycleError(f"PE product version query failed: {path.name}")
    fixed = ctypes.cast(pointer, ctypes.POINTER(_VS_FIXEDFILEINFO)).contents
    if fixed.dwSignature != 0xFEEF04BD:
        raise WindowsLifecycleError(f"PE version signature is invalid: {path.name}")
    values = (
        fixed.dwProductVersionMS >> 16,
        fixed.dwProductVersionMS & 0xFFFF,
        fixed.dwProductVersionLS >> 16,
        fixed.dwProductVersionLS & 0xFFFF,
    )
    return ".".join(str(value) for value in values[:3])


def _registry_values() -> dict[str, str] | None:
    if winreg is None:
        raise WindowsLifecycleError("Windows registry API is unavailable")
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY, 0, winreg.KEY_READ)
    except FileNotFoundError:
        return None
    with key:
        result: dict[str, str] = {}
        for name in ("DisplayName", "DisplayVersion", "Publisher", "InstallLocation"):
            try:
                value, _kind = winreg.QueryValueEx(key, name)
            except FileNotFoundError:
                value = ""
            result[name] = str(value)
        return result


def require_clean_host() -> None:
    app, data = _canonical_paths()
    if app.exists() or data.exists() or _registry_values() is not None:
        raise WindowsLifecycleError(
            "lifecycle host is not clean; app, owner data, or production AppId exists"
        )


def _run(argv: Sequence[str], *, environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        list(argv),
        check=False,
        timeout=900,
        env=environment,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise WindowsLifecycleError(
            f"command failed with exit {result.returncode}: {Path(argv[0]).name}: {result.stderr[-1000:]}"
        )
    return result


def _assert_installed(version: str, signer_thumbprint: str) -> dict[str, object]:
    app, _data = _canonical_paths()
    if not app.is_dir() or app.is_symlink() or _is_reparse(app):
        raise WindowsLifecycleError("installed Onyx directory is unsafe")
    executable = app / "Onyx.exe"
    if not executable.is_file() or executable.is_symlink() or _is_reparse(executable):
        raise WindowsLifecycleError("installed Onyx executable is unavailable")
    observed = pe_product_version(executable)
    if observed != version:
        raise WindowsLifecycleError(
            f"installed PE version mismatch: expected {version}, got {observed}"
        )
    registry = _registry_values()
    expected_location = str(app) + os.sep
    if registry is None or registry != {
        "DisplayName": "Onyx",
        "DisplayVersion": version,
        "Publisher": "Cyryx Labs",
        "InstallLocation": expected_location,
    }:
        raise WindowsLifecycleError("production AppId registry identity is invalid")
    return {
        "pe_product_version": observed,
        "registry": registry,
        "signature": authenticode_identity(executable, signer_thumbprint),
    }


def install_setup(
    setup: Path,
    version: str,
    signer_thumbprint: str,
    evidence: Path,
    label: str,
) -> dict[str, object]:
    log = evidence / f"setup-{label}.log"
    _run(
        [
            str(setup),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/SP-",
            "/CURRENTUSER",
            "/NOICONS",
            f"/LOG={log}",
        ]
    )
    if not log.is_file():
        raise WindowsLifecycleError(f"Setup log was not produced: {label}")
    return _assert_installed(version, signer_thumbprint)


def smoke_installed_app(evidence: Path, label: str) -> dict[str, object]:
    app, data = _canonical_paths()
    output = evidence / f"native-smoke-{label}.json"
    environment = os.environ.copy()
    environment["ONYX_DATA_DIR"] = str(data)
    environment[SMOKE_OUTPUT_ENV] = str(output)
    _run([str(app / "Onyx.exe"), SMOKE_ARGUMENT], environment=environment)
    try:
        payload = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WindowsLifecycleError(f"installed startup smoke is invalid: {label}") from exc
    if payload.get("status") != "passed" or payload.get("system") != "Windows":
        raise WindowsLifecycleError(f"installed startup smoke failed: {label}")
    return payload


def uninstall_app(evidence: Path, label: str) -> None:
    app, _data = _canonical_paths()
    if not app.is_dir() or app.is_symlink() or _is_reparse(app):
        raise WindowsLifecycleError("production Onyx application path is unsafe")
    uninstaller = app / "unins000.exe"
    if not uninstaller.is_file() or uninstaller.is_symlink() or _is_reparse(uninstaller):
        raise WindowsLifecycleError("production Onyx uninstaller is unavailable")
    log = evidence / f"uninstall-{label}.log"
    _run(
        [
            str(uninstaller),
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            f"/LOG={log}",
        ]
    )
    deadline = time.monotonic() + 45.0
    while app.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    if app.exists() or _registry_values() is not None:
        raise WindowsLifecycleError("app-only uninstall left payload or production AppId")


def _reset_disposable_owner_data() -> None:
    _app, data = _canonical_paths()
    if not data.exists():
        return
    if data.is_symlink() or _is_reparse(data) or not data.is_dir():
        raise WindowsLifecycleError("owner-data reset target is unsafe")
    shutil.rmtree(data)
    if data.exists():
        raise WindowsLifecycleError("owner-data reset left residual bytes")


def _write_marker(name: str, content: str) -> Path:
    _app, data = _canonical_paths()
    data.mkdir(parents=True, exist_ok=True)
    if data.is_symlink() or _is_reparse(data) or not data.is_dir():
        raise WindowsLifecycleError("owner-data marker target is unsafe")
    marker = data / name
    marker.write_text(content, encoding="utf-8")
    return marker


def _require_marker(marker: Path, content: str, gate: str) -> None:
    try:
        observed = marker.read_text(encoding="utf-8")
    except OSError as exc:
        raise WindowsLifecycleError(f"owner data missing after {gate}") from exc
    if observed != content:
        raise WindowsLifecycleError(f"owner data changed after {gate}")


def run_lifecycle(
    *,
    current_setup: Path,
    current_sha256: str,
    current_version: str,
    current_signer_thumbprint: str,
    prior_setup: Path,
    prior_sha256: str,
    prior_version: str,
    prior_signer_thumbprint: str,
    evidence_dir: Path,
) -> Path:
    require_disposable_host()
    if not current_version or not prior_version or current_version == prior_version:
        raise WindowsLifecycleError("current and prior release versions must be distinct")
    current = require_regular_setup(current_setup, current_sha256, current_version)
    prior = require_regular_setup(prior_setup, prior_sha256, prior_version)
    evidence = require_evidence_directory(evidence_dir)
    require_clean_host()
    current_signature = authenticode_identity(current, current_signer_thumbprint)
    prior_signature = authenticode_identity(prior, prior_signer_thumbprint)
    if pe_product_version(current) != current_version or pe_product_version(prior) != prior_version:
        raise WindowsLifecycleError("Setup PE ProductVersion does not match requested version")
    events: list[dict[str, object]] = []

    install = install_setup(current, current_version, current_signer_thumbprint, evidence, "clean-current")
    events.append({"gate": "clean_install_current", "install": install, "smoke": smoke_installed_app(evidence, "clean-current")})
    marker = _write_marker("lifecycle-owner-data-marker.txt", "owner-data-must-survive\n")

    uninstall_app(evidence, "current")
    _require_marker(marker, "owner-data-must-survive\n", "app-only uninstall")
    events.append({"gate": "uninstall_app_only", "owner_data_preserved": True})

    install_setup(current, current_version, current_signer_thumbprint, evidence, "reinstall-current")
    smoke_installed_app(evidence, "reinstall-current")
    _require_marker(marker, "owner-data-must-survive\n", "same-version reinstall")
    events.append({"gate": "reinstall_current", "owner_data_preserved": True})

    uninstall_app(evidence, "reset-current")
    _reset_disposable_owner_data()
    install_setup(prior, prior_version, prior_signer_thumbprint, evidence, "clean-prior")
    smoke_installed_app(evidence, "clean-prior")
    upgrade_marker = _write_marker("lifecycle-upgrade-marker.txt", "upgrade-data-must-survive\n")

    install_setup(current, current_version, current_signer_thumbprint, evidence, "upgrade-current")
    smoke_installed_app(evidence, "upgrade-current")
    _require_marker(upgrade_marker, "upgrade-data-must-survive\n", "upgrade")
    events.append({"gate": "upgrade_prior_to_current", "owner_data_preserved": True})

    uninstall_app(evidence, "rollback-current")
    _require_marker(upgrade_marker, "upgrade-data-must-survive\n", "rollback uninstall")
    install_setup(prior, prior_version, prior_signer_thumbprint, evidence, "rollback-prior")
    smoke_installed_app(evidence, "rollback-prior")
    _require_marker(upgrade_marker, "upgrade-data-must-survive\n", "rollback")
    events.append({"gate": "rollback_current_to_prior", "owner_data_preserved": True})

    uninstall_app(evidence, "final-prior")
    _require_marker(upgrade_marker, "upgrade-data-must-survive\n", "final uninstall")
    events.append({"gate": "final_uninstall_app_only", "owner_data_preserved": True})

    app, data = _canonical_paths()
    report = evidence / "windows-lifecycle-evidence.json"
    report.write_text(
        json.dumps(
            {
                "contract": "onyx.windows-lifecycle-evidence.v1",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "host": {
                    "system": platform.system(),
                    "architecture": platform.machine(),
                    "release": platform.release(),
                    "version": platform.version(),
                },
                "production_app_id": PRODUCTION_APP_ID,
                "current": {
                    "version": current_version,
                    "sha256": current_sha256.casefold(),
                    "signature": current_signature,
                },
                "prior": {
                    "version": prior_version,
                    "sha256": prior_sha256.casefold(),
                    "signature": prior_signature,
                },
                "events": events,
                "final_app_removed": not app.exists(),
                "final_registry_removed": _registry_values() is None,
                "final_owner_data_preserved": data.exists(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run signed Onyx lifecycle gates on a disposable Windows x64 host"
    )
    parser.add_argument("--current-setup", type=Path, required=True)
    parser.add_argument("--current-sha256", required=True)
    parser.add_argument("--current-version", required=True)
    parser.add_argument("--current-signer-thumbprint", required=True)
    parser.add_argument("--prior-setup", type=Path, required=True)
    parser.add_argument("--prior-sha256", required=True)
    parser.add_argument("--prior-version", required=True)
    parser.add_argument("--prior-signer-thumbprint", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    run_lifecycle(
        current_setup=args.current_setup,
        current_sha256=args.current_sha256,
        current_version=args.current_version,
        current_signer_thumbprint=args.current_signer_thumbprint,
        prior_setup=args.prior_setup,
        prior_sha256=args.prior_sha256,
        prior_version=args.prior_version,
        prior_signer_thumbprint=args.prior_signer_thumbprint,
        evidence_dir=args.evidence_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
