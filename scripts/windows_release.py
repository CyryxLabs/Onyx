"""Native Windows Authenticode release signing and evidence.

Formal release operations are intentionally unavailable off Windows.  Evidence
contains only public certificate metadata and hashes; private key material is
never read by this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Mapping


THUMBPRINT_RE = re.compile(r"^[0-9A-F]{40}$")
FORMAL_ENVIRONMENT = (
    "ONYX_WINDOWS_SIGN_CERT_THUMBPRINT",
    "ONYX_WINDOWS_SIGN_EXPECTED_SUBJECT",
    "ONYX_WINDOWS_TIMESTAMP_URL",
)


class WindowsReleaseError(RuntimeError):
    """The Windows artifact cannot satisfy the formal release contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_formal_environment(
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    selected = dict(os.environ if environment is None else environment)
    values = {name: selected.get(name, "").strip() for name in FORMAL_ENVIRONMENT}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise WindowsReleaseError(
            "formal Windows signing environment is incomplete: " + ", ".join(missing)
        )
    thumbprint = values["ONYX_WINDOWS_SIGN_CERT_THUMBPRINT"].upper()
    if not THUMBPRINT_RE.fullmatch(thumbprint):
        raise WindowsReleaseError("Windows signing certificate thumbprint is malformed")
    subject = values["ONYX_WINDOWS_SIGN_EXPECTED_SUBJECT"]
    if "cyryx labs" not in subject.casefold():
        raise WindowsReleaseError("Windows signing subject is not a Cyryx Labs identity")
    timestamp_url = values["ONYX_WINDOWS_TIMESTAMP_URL"]
    if not timestamp_url.casefold().startswith("https://"):
        raise WindowsReleaseError("Windows timestamp URL must use HTTPS")
    values["ONYX_WINDOWS_SIGN_CERT_THUMBPRINT"] = thumbprint
    return values


def find_signtool() -> Path:
    explicit = os.environ.get("ONYX_SIGNTOOL", "").strip()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    located = shutil.which("signtool") or shutil.which("signtool.exe")
    if located:
        candidates.append(Path(located))
    kits = Path(os.environ.get("ProgramFiles(x86)", "")) / "Windows Kits" / "10" / "bin"
    if kits.is_dir():
        candidates.extend(sorted(kits.glob("*/x64/signtool.exe"), reverse=True))
    for candidate in candidates:
        if candidate.is_file() and not candidate.is_symlink():
            return candidate.resolve()
    raise WindowsReleaseError("signtool.exe is unavailable")


def _run(argv: list[str], *, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        check=True,
        capture_output=capture_output,
        text=True,
    )


def _powershell_signature(path: Path) -> dict[str, object]:
    escaped = str(path).replace("'", "''")
    command = (
        f"$s=Get-AuthenticodeSignature -LiteralPath '{escaped}'; "
        "[ordered]@{status=[string]$s.Status;status_message=$s.StatusMessage;"
        "subject=$s.SignerCertificate.Subject;thumbprint=$s.SignerCertificate.Thumbprint;"
        "timestamp_subject=$s.TimeStamperCertificate.Subject;"
        "timestamp_thumbprint=$s.TimeStamperCertificate.Thumbprint}|ConvertTo-Json -Compress"
    )
    completed = _run(
        ["powershell", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise WindowsReleaseError("Authenticode verification returned invalid evidence") from exc
    if type(payload) is not dict:
        raise WindowsReleaseError("Authenticode verification returned malformed evidence")
    return payload


def verify_authenticode(
    path: Path, *, signtool: Path, credentials: Mapping[str, str]
) -> dict[str, object]:
    """Verify exact file bytes through both native Windows trust providers."""

    if platform.system() != "Windows":
        raise WindowsReleaseError(
            "native Authenticode verification requires a native Windows host"
        )
    if not path.is_file() or path.is_symlink():
        raise WindowsReleaseError(f"Authenticode target is invalid: {path}")
    _run([str(signtool), "verify", "/pa", "/all", "/v", str(path)])
    evidence = _powershell_signature(path)
    if evidence.get("status") != "Valid":
        raise WindowsReleaseError(f"Authenticode trust verification failed: {path.name}")
    if str(evidence.get("thumbprint", "")).upper() != credentials[
        "ONYX_WINDOWS_SIGN_CERT_THUMBPRINT"
    ]:
        raise WindowsReleaseError(f"Authenticode signer thumbprint drifted: {path.name}")
    if str(evidence.get("subject", "")) != credentials[
        "ONYX_WINDOWS_SIGN_EXPECTED_SUBJECT"
    ]:
        raise WindowsReleaseError(f"Authenticode signer subject drifted: {path.name}")
    if not evidence.get("timestamp_thumbprint") or not evidence.get("timestamp_subject"):
        raise WindowsReleaseError(f"Authenticode timestamp is absent: {path.name}")
    return evidence


def sign_and_verify(path: Path, *, credentials: Mapping[str, str], signtool: Path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise WindowsReleaseError(f"Windows signing target is invalid: {path}")
    _run(
        [
            str(signtool),
            "sign",
            "/sha1",
            credentials["ONYX_WINDOWS_SIGN_CERT_THUMBPRINT"],
            "/fd",
            "SHA256",
            "/tr",
            credentials["ONYX_WINDOWS_TIMESTAMP_URL"],
            "/td",
            "SHA256",
            str(path),
        ]
    )
    signature = verify_authenticode(path, signtool=signtool, credentials=credentials)
    return {
        "name": path.name,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "authenticode_status": signature["status"],
        "signer_subject": signature["subject"],
        "signer_thumbprint": signature["thumbprint"],
        "timestamp_subject": signature["timestamp_subject"],
        "timestamp_thumbprint": signature["timestamp_thumbprint"],
    }


def sign_bundle(bundle: Path) -> tuple[dict[str, object], ...]:
    if platform.system() != "Windows":
        raise WindowsReleaseError("formal Windows signing requires a native Windows host")
    credentials = require_formal_environment()
    signtool = find_signtool()
    targets = sorted(
        (
            path
            for path in bundle.rglob("*")
            if path.is_file() and path.suffix.casefold() in {".exe", ".dll", ".pyd"}
        ),
        key=lambda path: path.relative_to(bundle).as_posix(),
    )
    if not targets:
        raise WindowsReleaseError("formal Windows bundle contains no PE signing targets")
    records: list[dict[str, object]] = []
    for target in targets:
        record = sign_and_verify(target, credentials=credentials, signtool=signtool)
        record["path"] = target.relative_to(bundle).as_posix()
        records.append(record)
    return tuple(records)


def sign_artifacts_and_write_evidence(
    *, version: str, architecture: str, release_dir: Path,
    artifacts: list[Path], bundle_records: tuple[dict[str, object], ...],
) -> Path:
    credentials = require_formal_environment()
    signtool = find_signtool()
    signed_artifacts: list[dict[str, object]] = []
    for artifact in artifacts:
        if artifact.suffix.casefold() == ".exe":
            signed_artifacts.append(
                sign_and_verify(artifact, credentials=credentials, signtool=signtool)
            )
    if not signed_artifacts:
        raise WindowsReleaseError("formal Windows release has no signed installer")
    evidence = release_dir / f"windows-release-evidence-{architecture}.json"
    payload = {
        "contract": "onyx.windows-release-evidence.v1",
        "version": version,
        "architecture": architecture,
        "formal": True,
        "trust_provider": "Windows Authenticode",
        "verification_policy": "signtool /pa /all /v and Get-AuthenticodeSignature Valid",
        "signer_subject": credentials["ONYX_WINDOWS_SIGN_EXPECTED_SUBJECT"],
        "signer_thumbprint": credentials["ONYX_WINDOWS_SIGN_CERT_THUMBPRINT"],
        "timestamp_url": credentials["ONYX_WINDOWS_TIMESTAMP_URL"],
        "all_trusted": True,
        "bundle_pe_files": list(bundle_records),
        "signed_installers": signed_artifacts,
    }
    evidence.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return evidence
