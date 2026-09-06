"""Native, hash-bound Authenticode eligibility for formal Windows releases.

JSON signing evidence is diagnostic only.  A formal decision is produced only
after Windows validates the exact Setup executable and every PE member of the
portable archive with both WinVerifyTrust (signtool) and PowerShell's native
Authenticode API.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping

from scripts import windows_release


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PE_SUFFIXES = {".exe", ".dll", ".pyd"}


class WindowsNativeEligibilityRefusal(windows_release.WindowsReleaseError):
    """Typed fail-closed refusal when native Windows trust is unavailable."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


def _safe_archive_member(name: str) -> PurePosixPath:
    parsed = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or parsed.is_absolute()
        or str(parsed) != name
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise WindowsNativeEligibilityRefusal(
            "WINDOWS_PORTABLE_PATH_UNSAFE", f"noncanonical archive member: {name!r}"
        )
    return parsed


def _artifact_record(manifest: Mapping[str, object], suffix: str) -> dict[str, object]:
    records = manifest.get("artifacts")
    if type(records) is not list:
        raise WindowsNativeEligibilityRefusal(
            "WINDOWS_MANIFEST_INVALID", "artifact inventory is absent"
        )
    selected = [
        item for item in records
        if type(item) is dict and str(item.get("name", "")).endswith(suffix)
    ]
    if len(selected) != 1:
        raise WindowsNativeEligibilityRefusal(
            "WINDOWS_ARTIFACT_SET_INVALID", f"expected exactly one {suffix}"
        )
    return selected[0]


def _bind_file(release_dir: Path, record: Mapping[str, object]) -> Path:
    name = record.get("name")
    expected_size = record.get("size")
    expected_sha = record.get("sha256")
    if (
        type(name) is not str
        or Path(name).name != name
        or type(expected_size) is not int
        or expected_size <= 0
        or type(expected_sha) is not str
        or not SHA256_RE.fullmatch(expected_sha)
    ):
        raise WindowsNativeEligibilityRefusal(
            "WINDOWS_MANIFEST_INVALID", "artifact record is malformed"
        )
    path = release_dir / name
    if not path.is_file() or path.is_symlink():
        raise WindowsNativeEligibilityRefusal(
            "WINDOWS_ARTIFACT_INVALID", f"artifact is not a regular file: {name}"
        )
    if path.stat().st_size != expected_size or windows_release.sha256_file(path) != expected_sha:
        raise WindowsNativeEligibilityRefusal(
            "WINDOWS_ARTIFACT_DRIFT", f"manifest bytes drifted: {name}"
        )
    return path


def _signature_record(
    path: Path,
    *,
    relative: str,
    verifier: Callable[..., dict[str, object]],
    signtool: Path,
    credentials: Mapping[str, str],
) -> dict[str, object]:
    signature = verifier(path, signtool=signtool, credentials=credentials)
    return {
        "path": relative,
        "size": path.stat().st_size,
        "sha256": windows_release.sha256_file(path),
        "authenticode_status": signature.get("status"),
        "signer_subject": signature.get("subject"),
        "signer_thumbprint": str(signature.get("thumbprint", "")).upper(),
        "timestamp_subject": signature.get("timestamp_subject"),
        "timestamp_thumbprint": signature.get("timestamp_thumbprint"),
    }


def verify_formal_windows_release(
    *,
    release_dir: Path,
    version: str,
    architecture: str,
    environment: Mapping[str, str] | None = None,
    system: str | None = None,
    verifier: Callable[..., dict[str, object]] | None = None,
    signtool: Path | None = None,
) -> dict[str, object]:
    """Run the native formal gate and return a receipt bound to verified bytes."""

    if (platform.system() if system is None else system) != "Windows":
        raise WindowsNativeEligibilityRefusal(
            "WINDOWS_NATIVE_VERIFICATION_REQUIRED",
            "formal Authenticode eligibility must execute on a native Windows host",
        )
    release_dir = release_dir.resolve(strict=True)
    manifest_path = release_dir / f"release-manifest-Windows-{architecture}.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise WindowsNativeEligibilityRefusal(
            "WINDOWS_MANIFEST_INVALID", "exact Windows release manifest is absent"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WindowsNativeEligibilityRefusal(
            "WINDOWS_MANIFEST_INVALID", "Windows manifest is unreadable"
        ) from exc
    if (
        type(manifest) is not dict
        or manifest.get("version") != version
        or manifest.get("system") != "Windows"
        or manifest.get("architecture") != architecture
        or manifest.get("release_class") != "formal"
    ):
        raise WindowsNativeEligibilityRefusal(
            "WINDOWS_MANIFEST_INVALID", "formal Windows identity drifted"
        )

    credentials = windows_release.require_formal_environment(environment)
    native_signtool = windows_release.find_signtool() if signtool is None else signtool
    native_verifier = windows_release.verify_authenticode if verifier is None else verifier
    setup_record = _artifact_record(manifest, "-Setup.exe")
    portable_record = _artifact_record(manifest, "-Portable.zip")
    setup = _bind_file(release_dir, setup_record)
    portable = _bind_file(release_dir, portable_record)

    verified: list[dict[str, object]] = [
        _signature_record(
            setup,
            relative=setup.name,
            verifier=native_verifier,
            signtool=native_signtool,
            credentials=credentials,
        )
    ]
    with tempfile.TemporaryDirectory(prefix="onyx-authenticode-") as temporary:
        temp_root = Path(temporary)
        try:
            with zipfile.ZipFile(portable) as archive:
                names = archive.namelist()
                if len(names) != len(set(names)):
                    raise WindowsNativeEligibilityRefusal(
                        "WINDOWS_PORTABLE_PATH_UNSAFE", "duplicate archive member"
                    )
                pe_names: list[str] = []
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    parsed = _safe_archive_member(info.filename)
                    if (info.external_attr >> 16) & 0o170000 == 0o120000:
                        raise WindowsNativeEligibilityRefusal(
                            "WINDOWS_PORTABLE_PATH_UNSAFE", "linked archive member"
                        )
                    if parsed.suffix.casefold() in PE_SUFFIXES:
                        pe_names.append(info.filename)
                if not pe_names:
                    raise WindowsNativeEligibilityRefusal(
                        "WINDOWS_PORTABLE_PE_ABSENT", "portable archive contains no PE images"
                    )
                for index, name in enumerate(sorted(pe_names)):
                    raw = archive.read(name)
                    target = temp_root / f"{index:05d}-{PurePosixPath(name).name}"
                    target.write_bytes(raw)
                    verified.append(
                        _signature_record(
                            target,
                            relative=name,
                            verifier=native_verifier,
                            signtool=native_signtool,
                            credentials=credentials,
                        )
                    )
        except zipfile.BadZipFile as exc:
            raise WindowsNativeEligibilityRefusal(
                "WINDOWS_PORTABLE_INVALID", "portable archive is unreadable"
            ) from exc

    return {
        "contract": "onyx.windows-native-eligibility-receipt.v1",
        "decision": "eligible",
        "version": version,
        "architecture": architecture,
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "workflow_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "workflow_sha": os.environ.get("GITHUB_SHA", ""),
        "manifest": {
            "name": manifest_path.name,
            "size": manifest_path.stat().st_size,
            "sha256": windows_release.sha256_file(manifest_path),
        },
        "setup": {
            "name": setup.name,
            "size": setup.stat().st_size,
            "sha256": windows_release.sha256_file(setup),
        },
        "portable": {
            "name": portable.name,
            "size": portable.stat().st_size,
            "sha256": windows_release.sha256_file(portable),
        },
        "signer_subject": credentials["ONYX_WINDOWS_SIGN_EXPECTED_SUBJECT"],
        "signer_thumbprint": credentials["ONYX_WINDOWS_SIGN_CERT_THUMBPRINT"],
        "verified_pe_files": verified,
    }


def write_receipt(path: Path, receipt: Mapping[str, object]) -> str:
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return windows_release.sha256_file(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run native Windows Authenticode eligibility")
    parser.add_argument("--release-dir", type=Path, default=Path("release"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--architecture", default="x64")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt_path = args.receipt or (
        args.release_dir / f"windows-native-eligibility-receipt-{args.architecture}.json"
    )
    try:
        receipt = verify_formal_windows_release(
            release_dir=args.release_dir,
            version=args.version,
            architecture=args.architecture,
        )
        digest = write_receipt(receipt_path, receipt)
    except WindowsNativeEligibilityRefusal as exc:
        print(f"Windows native eligibility: REFUSED [{exc.code}] {exc}")
        return 2
    except windows_release.WindowsReleaseError as exc:
        print(f"Windows native eligibility: BLOCKED {exc}")
        return 1
    print(f"Windows native eligibility: PASS {digest}")
    output = os.environ.get("GITHUB_OUTPUT", "").strip()
    if output:
        with Path(output).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"receipt_sha256={digest}\n")
            handle.write(f"setup_sha256={receipt['setup']['sha256']}\n")
            handle.write(f"portable_sha256={receipt['portable']['sha256']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
