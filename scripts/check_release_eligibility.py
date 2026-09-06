"""Fail-closed eligibility gate for public Onyx releases.

This checker validates evidence; it does not generate, approve, or repair legal
artifacts. Local package builds do not call it. Public-release automation must.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

APPROVAL_ENV = "ONYX_PUBLIC_RELEASE_APPROVED"
LEGAL_APPROVAL_ENV = "ONYX_LEGAL_RELEASE_APPROVED"
LICENSE_FILE = "LICENSE"
NOTICES_FILE = "THIRD_PARTY_NOTICES.md"
SBOM_FILE = "SBOM.spdx.json"
SBOM_DIGEST_FILE = "SBOM.spdx.json.sha256"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SPDX_VERSION_RE = re.compile(r"^SPDX-2\.\d+$")
SPDX_CREATED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
PLACEHOLDER_RE = re.compile(
    r"(?:\bTODO\b|\bTBD\b|\bCHANGEME\b|\bPLACEHOLDER\b|INSERT (?:THE )?LICENSE)",
    re.IGNORECASE,
)
NOTARY_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
FORMAL_SIGNING_POLICIES = {
    "Windows": "authenticode-trusted",
    "Darwin": "developer-id-notarized",
    "Linux": "unsigned-approved",
}

WINDOWS_NATIVE_RECEIPT_PREFIX = "windows-native-eligibility-receipt-"


def _bound_record(path: Path) -> dict[str, object]:
    return {"name": path.name, "size": path.stat().st_size, "sha256": _sha256(path)}


def _validate_windows_native_receipt(
    *,
    release_dir: Path,
    manifest: dict[str, Any],
    receipt: object,
    trusted_receipt_sha256: str,
    require_ci_binding: bool,
    workflow_run_id: str,
    workflow_sha: str,
    errors: list[str],
) -> None:
    """Bind a native Windows decision to the exact manifest and artifact bytes."""

    architecture = manifest.get("architecture")
    receipt_path = release_dir / f"{WINDOWS_NATIVE_RECEIPT_PREFIX}{architecture}.json"
    if receipt is None:
        receipt = _load_json(receipt_path, "Windows native eligibility receipt", errors)
    if type(receipt) is not dict:
        errors.append(
            "WINDOWS_NATIVE_VERIFICATION_REQUIRED: native Windows eligibility receipt is absent"
        )
        return
    if require_ci_binding:
        if os.environ.get("GITHUB_ACTIONS", "").casefold() != "true":
            errors.append(
                "WINDOWS_NATIVE_VERIFICATION_REQUIRED: a local attestation cannot authorize formal Windows eligibility"
            )
            return
        if not SHA256_RE.fullmatch(trusted_receipt_sha256):
            errors.append(
                "WINDOWS_NATIVE_RECEIPT_UNTRUSTED: trusted Windows job receipt digest is absent"
            )
            return
        if (
            not receipt_path.is_file()
            or receipt_path.is_symlink()
            or _sha256(receipt_path) != trusted_receipt_sha256
        ):
            errors.append(
                "WINDOWS_NATIVE_RECEIPT_DRIFT: Windows job receipt hash does not match downloaded bytes"
            )
        if receipt.get("workflow_run_id") != workflow_run_id or receipt.get("workflow_sha") != workflow_sha:
            errors.append(
                "WINDOWS_NATIVE_RECEIPT_DRIFT: Windows job receipt workflow identity drifted"
            )
    required = {
        "contract", "decision", "version", "architecture", "workflow_run_id",
        "workflow_run_attempt", "workflow_sha", "manifest", "setup", "portable",
        "signer_subject", "signer_thumbprint", "verified_pe_files",
    }
    if set(receipt) != required:
        errors.append("WINDOWS_NATIVE_RECEIPT_INVALID: receipt fields drifted")
    if (
        receipt.get("contract") != "onyx.windows-native-eligibility-receipt.v1"
        or receipt.get("decision") != "eligible"
        or receipt.get("version") != manifest.get("version")
        or receipt.get("architecture") != architecture
    ):
        errors.append("WINDOWS_NATIVE_RECEIPT_INVALID: formal decision identity drifted")
    subject = receipt.get("signer_subject")
    thumbprint = str(receipt.get("signer_thumbprint", ""))
    if type(subject) is not str or "cyryx labs" not in subject.casefold():
        errors.append("WINDOWS_NATIVE_RECEIPT_INVALID: Cyryx Labs signer is absent")
    if not re.fullmatch(r"[0-9A-F]{40}", thumbprint):
        errors.append("WINDOWS_NATIVE_RECEIPT_INVALID: signer thumbprint is malformed")

    manifest_path = release_dir / f"release-manifest-Windows-{architecture}.json"
    records = manifest.get("artifacts") if type(manifest.get("artifacts")) is list else []
    setups = [item for item in records if type(item) is dict and str(item.get("name", "")).endswith("-Setup.exe")]
    archives = [item for item in records if type(item) is dict and str(item.get("name", "")).endswith("-Portable.zip")]
    if len(setups) != 1 or len(archives) != 1:
        errors.append("WINDOWS_NATIVE_RECEIPT_INVALID: formal Windows artifacts are incomplete")
        return
    setup_path = release_dir / str(setups[0]["name"])
    archive_path = release_dir / str(archives[0]["name"])
    for field, path in (("manifest", manifest_path), ("setup", setup_path), ("portable", archive_path)):
        if not path.is_file() or path.is_symlink() or receipt.get(field) != _bound_record(path):
            errors.append(f"WINDOWS_NATIVE_RECEIPT_DRIFT: {field} binding mismatch")

    verified = receipt.get("verified_pe_files")
    if type(verified) is not list:
        errors.append("WINDOWS_NATIVE_RECEIPT_INVALID: verified PE inventory is absent")
        return
    actual: dict[str, tuple[int, str]] = {
        setup_path.name: (setup_path.stat().st_size, _sha256(setup_path))
    }
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for name in archive.namelist():
                if Path(name).suffix.casefold() in {".exe", ".dll", ".pyd"}:
                    raw = archive.read(name)
                    actual[name] = (len(raw), hashlib.sha256(raw).hexdigest())
    except (OSError, zipfile.BadZipFile, KeyError):
        errors.append("WINDOWS_NATIVE_RECEIPT_INVALID: portable archive is unreadable")
        return
    observed: dict[str, tuple[object, object]] = {}
    for item in verified:
        if type(item) is not dict or type(item.get("path")) is not str or item["path"] in observed:
            errors.append("WINDOWS_NATIVE_RECEIPT_INVALID: verified PE record is malformed")
            continue
        observed[item["path"]] = (item.get("size"), item.get("sha256"))
        if (
            item.get("authenticode_status") != "Valid"
            or item.get("signer_subject") != subject
            or str(item.get("signer_thumbprint", "")).upper() != thumbprint
            or not item.get("timestamp_subject")
            or not item.get("timestamp_thumbprint")
        ):
            errors.append(f"WINDOWS_NATIVE_RECEIPT_INVALID: native trust fields invalid for {item.get('path')}")
    if observed != actual:
        errors.append("WINDOWS_NATIVE_RECEIPT_DRIFT: verified PE inventory does not match exact artifact bytes")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(path: Path, label: str, errors: list[str]) -> bool:
    if not path.exists():
        errors.append(f"missing {label}: {path}")
        return False
    if path.is_symlink() or not path.is_file():
        errors.append(f"invalid {label}: must be a regular non-symlink file: {path}")
        return False
    return True


def _legal_text(
    path: Path,
    label: str,
    required_terms: tuple[str, ...],
    errors: list[str],
) -> None:
    if not _regular_file(path, label, errors):
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"invalid {label}: unreadable UTF-8 file ({type(exc).__name__})")
        return
    normalized = " ".join(text.split())
    if len(normalized) < 40:
        errors.append(f"invalid {label}: content is too short")
    if PLACEHOLDER_RE.search(text):
        errors.append(f"invalid {label}: unresolved placeholder marker")
    lowered = text.casefold()
    if not any(term in lowered for term in required_terms):
        errors.append(f"invalid {label}: expected legal notice language is absent")


def _load_json(path: Path, label: str, errors: list[str]) -> Any | None:
    if not _regular_file(path, label, errors):
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"invalid {label}: JSON parse failed ({type(exc).__name__})")
        return None


def _pe_has_authenticode(data: bytes) -> bool:
    """Return whether a PE image has a bounded certificate table."""

    try:
        if len(data) < 0x40 or data[:2] != b"MZ":
            return False
        pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
        if pe_offset + 24 > len(data) or data[pe_offset : pe_offset + 4] != b"PE\0\0":
            return False
        optional = pe_offset + 24
        magic = struct.unpack_from("<H", data, optional)[0]
        directory = optional + (96 if magic == 0x10B else 112 if magic == 0x20B else -1)
        if directory < optional:
            return False
        certificate_offset, certificate_size = struct.unpack_from(
            "<II", data, directory + (8 * 4)
        )
        return (
            certificate_offset > 0
            and certificate_size >= 8
            and certificate_offset + certificate_size <= len(data)
        )
    except (IndexError, struct.error):
        return False


def _validate_signature_record(
    record: object,
    *,
    expected_name: str,
    expected_data: bytes,
    signer_subject: str,
    signer_thumbprint: str,
    label: str,
    errors: list[str],
) -> None:
    if type(record) is not dict:
        errors.append(f"invalid {label}: signature record is absent")
        return
    required = {
        "name", "size", "sha256", "authenticode_status", "signer_subject",
        "signer_thumbprint", "timestamp_subject", "timestamp_thumbprint",
    }
    allowed = required | {"path"}
    if not required.issubset(record) or not set(record).issubset(allowed):
        errors.append(f"invalid {label}: signature record fields are incomplete")
    if record.get("name") != expected_name:
        errors.append(f"invalid {label}: signed filename mismatch")
    if record.get("size") != len(expected_data):
        errors.append(f"invalid {label}: signed size mismatch")
    if record.get("sha256") != hashlib.sha256(expected_data).hexdigest():
        errors.append(f"invalid {label}: signed SHA-256 mismatch")
    if record.get("authenticode_status") != "Valid":
        errors.append(f"invalid {label}: Authenticode status is not Valid")
    if record.get("signer_subject") != signer_subject:
        errors.append(f"invalid {label}: signer subject mismatch")
    if str(record.get("signer_thumbprint", "")).upper() != signer_thumbprint:
        errors.append(f"invalid {label}: signer thumbprint mismatch")
    for field in ("timestamp_subject", "timestamp_thumbprint"):
        if type(record.get(field)) is not str or not record[field].strip():
            errors.append(f"invalid {label}: {field} is absent")
    if not _pe_has_authenticode(expected_data):
        errors.append(f"invalid {label}: PE Authenticode certificate table is absent")


def _validate_windows_formal_evidence(
    release_dir: Path,
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    label: str,
    errors: list[str],
) -> None:
    architecture = manifest.get("architecture")
    evidence_name = f"windows-release-evidence-{architecture}.json"
    evidence = _load_json(release_dir / evidence_name, "Windows trust evidence", errors)
    record_names = {item.get("name") for item in records if type(item) is dict}
    if evidence_name not in record_names:
        errors.append(f"invalid {label}: Windows trust evidence is not manifest-bound")
    if type(evidence) is not dict:
        return
    required = {
        "contract", "version", "architecture", "formal", "trust_provider",
        "verification_policy", "signer_subject", "signer_thumbprint",
        "timestamp_url", "all_trusted", "bundle_pe_files", "signed_installers",
    }
    if set(evidence) != required:
        errors.append("invalid Windows trust evidence: contract fields drifted")
    if (
        evidence.get("contract") != "onyx.windows-release-evidence.v1"
        or evidence.get("version") != manifest.get("version")
        or evidence.get("architecture") != architecture
        or evidence.get("formal") is not True
        or evidence.get("all_trusted") is not True
        or evidence.get("trust_provider") != "Windows Authenticode"
    ):
        errors.append("invalid Windows trust evidence: formal trust claim is absent")
    subject = evidence.get("signer_subject")
    thumbprint = str(evidence.get("signer_thumbprint", "")).upper()
    if type(subject) is not str or "cyryx labs" not in subject.casefold():
        errors.append("invalid Windows trust evidence: Cyryx Labs signer is absent")
        subject = ""
    if not re.fullmatch(r"[0-9A-F]{40}", thumbprint):
        errors.append("invalid Windows trust evidence: signer thumbprint is malformed")
    if not str(evidence.get("timestamp_url", "")).casefold().startswith("https://"):
        errors.append("invalid Windows trust evidence: timestamp policy is absent")

    setups = [item for item in records if str(item.get("name", "")).endswith("-Setup.exe")]
    archives = [item for item in records if str(item.get("name", "")).endswith("-Portable.zip")]
    if len(setups) != 1 or len(archives) != 1:
        errors.append(f"invalid {label}: formal Windows formats must be Setup.exe and Portable.zip")
        return
    installers = evidence.get("signed_installers")
    if type(installers) is not list or len(installers) != 1:
        errors.append("invalid Windows trust evidence: one signed installer is required")
    else:
        setup_path = release_dir / setups[0]["name"]
        if setup_path.is_file():
            _validate_signature_record(
                installers[0], expected_name=setup_path.name,
                expected_data=setup_path.read_bytes(), signer_subject=subject,
                signer_thumbprint=thumbprint, label="Windows installer evidence",
                errors=errors,
            )
    bundle_records = evidence.get("bundle_pe_files")
    if type(bundle_records) is not list or not bundle_records:
        errors.append("invalid Windows trust evidence: signed bundle PE inventory is absent")
        return
    by_path = {
        item.get("path"): item
        for item in bundle_records
        if type(item) is dict and type(item.get("path")) is str
    }
    if len(by_path) != len(bundle_records):
        errors.append("invalid Windows trust evidence: bundle PE paths are duplicated")
    archive_path = release_dir / archives[0]["name"]
    try:
        with zipfile.ZipFile(archive_path) as archive:
            pe_names = sorted(
                name for name in archive.namelist()
                if name.startswith("Onyx/") and Path(name).suffix.casefold() in {".exe", ".dll", ".pyd"}
            )
            expected_paths = sorted(name.removeprefix("Onyx/") for name in pe_names)
            if sorted(by_path) != expected_paths:
                errors.append("invalid Windows trust evidence: bundle PE inventory coverage mismatch")
            for name in pe_names:
                relative = name.removeprefix("Onyx/")
                _validate_signature_record(
                    by_path.get(relative), expected_name=Path(relative).name,
                    expected_data=archive.read(name), signer_subject=subject,
                    signer_thumbprint=thumbprint,
                    label=f"Windows portable PE evidence {relative}", errors=errors,
                )
    except (OSError, zipfile.BadZipFile):
        errors.append("invalid Windows trust evidence: portable archive is unreadable")


def _validate_macos_formal_evidence(
    release_dir: Path, manifest: dict[str, Any], records: list[dict[str, Any]],
    label: str, errors: list[str],
) -> None:
    architecture = manifest.get("architecture")
    evidence_name = f"macos-release-evidence-{architecture}.json"
    evidence = _load_json(release_dir / evidence_name, "macOS trust evidence", errors)
    record_names = {item.get("name") for item in records if type(item) is dict}
    required_names = {
        evidence_name,
        f"notary-submit-app-macOS-{architecture}.json",
        f"notary-log-app-macOS-{architecture}.json",
        f"notary-submit-dmg-macOS-{architecture}.json",
        f"notary-log-dmg-macOS-{architecture}.json",
    }
    if not required_names.issubset(record_names):
        errors.append(f"invalid {label}: macOS notary evidence set is incomplete")
    if type(evidence) is not dict:
        return
    if (
        evidence.get("contract") != "onyx.macos-release-evidence.v1"
        or evidence.get("version") != manifest.get("version")
        or evidence.get("architecture") != architecture
        or any(evidence.get(field) is not True for field in (
            "formal", "developer_id_signed", "hardened_runtime", "notarized",
            "stapled", "gatekeeper_assessed",
        ))
    ):
        errors.append("invalid macOS trust evidence: formal trust gates are incomplete")
    if not NOTARY_ID_RE.fullmatch(str(evidence.get("app_notary_id", ""))):
        errors.append("invalid macOS trust evidence: app notary id is absent")
    if not NOTARY_ID_RE.fullmatch(str(evidence.get("dmg_notary_id", ""))):
        errors.append("invalid macOS trust evidence: dmg notary id is absent")
    team_id = str(evidence.get("team_id", ""))
    identity = str(evidence.get("developer_id_identity", ""))
    if not re.fullmatch(r"[A-Z0-9]{10}", team_id):
        errors.append("invalid macOS trust evidence: Apple team id is absent")
    if (
        not identity.startswith("Developer ID Application: ")
        or f"({team_id})" not in identity
    ):
        errors.append("invalid macOS trust evidence: Developer ID identity is absent or unbound")
    dmgs = [item for item in records if str(item.get("name", "")).endswith(".dmg")]
    if len(dmgs) != 1:
        errors.append(f"invalid {label}: exactly one formal DMG is required")
    elif evidence.get("dmg") != {
        "name": dmgs[0].get("name"), "size": dmgs[0].get("size"),
        "sha256": dmgs[0].get("sha256"),
    }:
        errors.append("invalid macOS trust evidence: DMG binding mismatch")
    for name in required_names - {evidence_name}:
        payload = _load_json(release_dir / name, f"macOS notary evidence {name}", errors)
        if type(payload) is not dict:
            continue
        if name.startswith("notary-submit-"):
            if payload.get("status") != "Accepted":
                errors.append(f"invalid macOS notary evidence {name}: status is not Accepted")
            expected_id = (
                evidence.get("app_notary_id")
                if "-app-" in name
                else evidence.get("dmg_notary_id")
            )
            if payload.get("id") != expected_id:
                errors.append(f"invalid macOS notary evidence {name}: submission id mismatch")
        if name.startswith("notary-log-") and payload.get("issues") not in ([], None):
            errors.append(f"invalid macOS notary evidence {name}: unresolved issues")


def _validate_linux_formal_contract(
    manifest: dict[str, Any], records: list[dict[str, Any]], label: str,
    errors: list[str],
) -> None:
    names = [str(item.get("name", "")) for item in records]
    suffixes = (".deb", ".tar.gz", ".AppImage")
    for suffix in suffixes:
        if sum(name.endswith(suffix) for name in names) != 1:
            errors.append(f"invalid {label}: formal Linux release requires exactly one {suffix}")
    if len(records) != 3:
        errors.append(f"invalid {label}: formal Linux artifact set contains extras")


def _validate_platform_checksums(
    release_dir: Path,
    manifest: dict[str, Any],
    records: list[dict[str, Any]],
    label: str,
    errors: list[str],
) -> None:
    name = f"SHA256SUMS-{manifest.get('system')}-{manifest.get('architecture')}.txt"
    path = release_dir / name
    if not _regular_file(path, f"platform checksum manifest {name}", errors):
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"invalid platform checksum manifest {name}: unreadable ({type(exc).__name__})")
        return
    expected: dict[str, str] = {
        str(record.get("name")): str(record.get("sha256")) for record in records
    }
    for source in (manifest.get("build_input_seal"), manifest.get("bundle_inventory")):
        if type(source) is not dict:
            errors.append(f"invalid {label}: checksum-bound manifest input is absent")
            continue
        source_name = source.get("manifest", source.get("name"))
        source_hash = source.get("manifest_sha256", source.get("sha256"))
        if type(source_name) is not str or type(source_hash) is not str:
            errors.append(f"invalid {label}: checksum-bound manifest input is malformed")
            continue
        expected[source_name] = source_hash
    actual: dict[str, str] = {}
    for line in text.splitlines():
        digest, separator, filename = line.partition("  ")
        if (
            not separator or not SHA256_RE.fullmatch(digest)
            or not filename or Path(filename).name != filename or filename in actual
        ):
            errors.append(f"invalid platform checksum manifest {name}: malformed record")
            continue
        actual[filename] = digest
    if actual != expected:
        errors.append(f"invalid platform checksum manifest {name}: exact coverage mismatch")
    for filename, digest in actual.items():
        target = release_dir / filename
        if not target.is_file() or target.is_symlink() or _sha256(target) != digest:
            errors.append(f"invalid platform checksum manifest {name}: byte mismatch for {filename}")


def _validate_formal_manifest(
    release_dir: Path, manifest: dict[str, Any], records: list[dict[str, Any]],
    label: str, errors: list[str], *,
    windows_native_verifier: Callable[..., dict[str, object]] | None,
    trusted_windows_receipt_sha256: str,
    workflow_run_id: str,
    workflow_sha: str,
) -> None:
    system = manifest.get("system")
    if manifest.get("release_class") != "formal":
        errors.append(f"invalid {label}: release_class must be formal")
    if manifest.get("diagnostic_exceptions") != []:
        errors.append(f"invalid {label}: diagnostic exceptions must be empty")
    trust = manifest.get("release_trust")
    expected_policy = FORMAL_SIGNING_POLICIES.get(system)
    if trust != {
        "contract": "onyx.release-trust.v1",
        "formal_requested": True,
        "platform": system,
        "signing_policy": expected_policy,
    }:
        errors.append(f"invalid {label}: formal release trust contract is absent")
    _validate_platform_checksums(release_dir, manifest, records, label, errors)
    if system == "Windows":
        # Certificate-table and JSON evidence remain diagnostic, never authority.
        _validate_windows_formal_evidence(release_dir, manifest, records, label, errors)
        native_receipt: object | None = None
        if os.name == "nt":
            try:
                if windows_native_verifier is None:
                    from scripts.windows_native_eligibility import (
                        verify_formal_windows_release,
                    )

                    native_receipt = verify_formal_windows_release(
                        release_dir=release_dir,
                        version=str(manifest.get("version", "")),
                        architecture=str(manifest.get("architecture", "")),
                    )
                else:
                    native_receipt = windows_native_verifier(
                        release_dir=release_dir,
                        version=str(manifest.get("version", "")),
                        architecture=str(manifest.get("architecture", "")),
                    )
            except Exception as exc:
                errors.append(f"WINDOWS_NATIVE_VERIFICATION_FAILED: {exc}")
        _validate_windows_native_receipt(
            release_dir=release_dir,
            manifest=manifest,
            receipt=native_receipt,
            trusted_receipt_sha256=trusted_windows_receipt_sha256,
            require_ci_binding=os.name != "nt",
            workflow_run_id=workflow_run_id,
            workflow_sha=workflow_sha,
            errors=errors,
        )
    elif system == "Darwin":
        _validate_macos_formal_evidence(release_dir, manifest, records, label, errors)
    elif system == "Linux":
        _validate_linux_formal_contract(manifest, records, label, errors)
    else:
        errors.append(f"invalid {label}: unsupported formal platform")


def _spdx_sha256(value: object) -> str | None:
    if type(value) is not list or len(value) != 1:
        return None
    checksum = value[0]
    if type(checksum) is not dict or set(checksum) != {
        "algorithm", "checksumValue"
    }:
        return None
    digest = checksum.get("checksumValue")
    if checksum.get("algorithm") != "SHA256" or type(digest) is not str:
        return None
    return digest if SHA256_RE.fullmatch(digest) else None


def _validate_technical_inventory(
    *,
    root: Path,
    release_dir: Path,
    version: str,
    sbom: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    """Prove that SPDX packages/files close over exact lock and artifact bytes."""

    from scripts.generate_release_sbom import (
        INVENTORY_COMMENT_PREFIX,
        INVENTORY_SCHEMA,
        ReleaseSbomError,
        inventory_artifact,
        load_bundle_inventories,
        parse_requirements_lock,
        sha256_file,
    )

    comment = sbom.get("comment")
    if type(comment) is not str or not comment.startswith(INVENTORY_COMMENT_PREFIX):
        errors.append("invalid SPDX SBOM: exact technical inventory is absent")
        return
    try:
        inventory = json.loads(comment.removeprefix(INVENTORY_COMMENT_PREFIX))
    except json.JSONDecodeError:
        errors.append("invalid SPDX SBOM: exact technical inventory is malformed")
        return
    if type(inventory) is not dict:
        errors.append("invalid SPDX SBOM: exact technical inventory is malformed")
        return
    if inventory.get("schema") != INVENTORY_SCHEMA:
        errors.append("invalid SPDX SBOM: technical inventory schema is unsupported")
    if inventory.get("technicalOnly") is not True:
        errors.append("invalid SPDX SBOM: technical-only scope is not explicit")
    if inventory.get("licenseReviewComplete") is not False:
        errors.append("invalid SPDX SBOM: legal review must remain independently gated")

    lock_path = root / "requirements.lock"
    try:
        locked = parse_requirements_lock(lock_path)
    except ReleaseSbomError as exc:
        errors.append(f"invalid SPDX SBOM: {exc}")
        return
    lock_inventory = inventory.get("dependencyLock")
    expected_lock_records = [
        {
            "name": item.name,
            "normalizedName": item.normalized_name,
            "version": item.version,
            "marker": item.marker,
            "spdxId": item.spdx_id,
        }
        for item in locked
    ]
    if type(lock_inventory) is not dict:
        errors.append("invalid SPDX SBOM: dependency lock inventory is absent")
    else:
        if lock_inventory.get("path") != "requirements.lock":
            errors.append("invalid SPDX SBOM: dependency lock path drifted")
        if lock_inventory.get("sha256") != sha256_file(lock_path):
            errors.append("invalid SPDX SBOM: dependency lock SHA-256 mismatch")
        if lock_inventory.get("packageCount") != len(expected_lock_records):
            errors.append("invalid SPDX SBOM: dependency lock package count mismatch")
        if lock_inventory.get("packages") != expected_lock_records:
            errors.append("invalid SPDX SBOM: dependency lock package coverage mismatch")

    try:
        actual_bundle_inventories = list(load_bundle_inventories(release_dir, version))
    except ReleaseSbomError as exc:
        errors.append(f"invalid SPDX SBOM: {exc}")
        actual_bundle_inventories = []
    recorded_bundle_inventories = inventory.get("bundleInventories")
    if inventory.get("bundleInventoryCount") != len(actual_bundle_inventories):
        errors.append("invalid SPDX SBOM: bundle inventory count mismatch")
    if recorded_bundle_inventories != actual_bundle_inventories:
        errors.append("invalid SPDX SBOM: bundle inventory coverage mismatch")
    shipped_identities = sorted(
        {
            (distribution["normalizedName"], distribution["version"])
            for bundle_inventory in actual_bundle_inventories
            for distribution in bundle_inventory["runtimeDistributions"]
        }
    )
    expected_shipped_records = [
        {"normalizedName": name, "version": package_version}
        for name, package_version in shipped_identities
    ]
    if inventory.get("shippedRuntimeDistributionCount") != len(shipped_identities):
        errors.append("invalid SPDX SBOM: shipped distribution count mismatch")
    if inventory.get("shippedRuntimeDistributions") != expected_shipped_records:
        errors.append("invalid SPDX SBOM: shipped distribution coverage mismatch")

    packages = sbom.get("packages")
    packages_by_id: dict[str, dict[str, Any]] = {}
    if type(packages) is not list:
        errors.append("invalid SPDX SBOM: packages must be a list")
    else:
        for package in packages:
            if type(package) is not dict or type(package.get("SPDXID")) is not str:
                errors.append("invalid SPDX SBOM: package record is malformed")
                continue
            spdx_id = package["SPDXID"]
            if spdx_id in packages_by_id:
                errors.append(f"invalid SPDX SBOM: duplicate package SPDXID {spdx_id}")
                continue
            packages_by_id[spdx_id] = package
    expected_package_ids = {"SPDXRef-Package-Onyx", *(item.spdx_id for item in locked)}
    if set(packages_by_id) != expected_package_ids:
        errors.append("invalid SPDX SBOM: package records do not exactly cover the lock")
    for item in locked:
        package = packages_by_id.get(item.spdx_id, {})
        if package.get("name") != item.name or package.get("versionInfo") != item.version:
            errors.append(
                f"invalid SPDX SBOM: locked package identity mismatch: {item.name}"
            )
        if (
            package.get("licenseConcluded") != "NOASSERTION"
            or package.get("licenseDeclared") != "NOASSERTION"
        ):
            errors.append(
                f"invalid SPDX SBOM: unreviewed license assertion: {item.name}"
            )
    product = packages_by_id.get("SPDXRef-Package-Onyx", {})
    if (
        product.get("licenseConcluded") != "NOASSERTION"
        or product.get("licenseDeclared") != "NOASSERTION"
        or product.get("filesAnalyzed") is not True
    ):
        errors.append("invalid SPDX SBOM: Onyx technical package scope drifted")

    files = sbom.get("files")
    files_by_id: dict[str, dict[str, Any]] = {}
    if type(files) is not list:
        errors.append("invalid SPDX SBOM: files must be a list")
    else:
        for item in files:
            if type(item) is not dict or type(item.get("SPDXID")) is not str:
                errors.append("invalid SPDX SBOM: file record is malformed")
                continue
            spdx_id = item["SPDXID"]
            if spdx_id in files_by_id:
                errors.append(f"invalid SPDX SBOM: duplicate file SPDXID {spdx_id}")
                continue
            files_by_id[spdx_id] = item
            if (
                item.get("licenseConcluded") != "NOASSERTION"
                or item.get("copyrightText") != "NOASSERTION"
            ):
                errors.append(
                    f"invalid SPDX SBOM: unreviewed file rights assertion: {spdx_id}"
                )

    artifact_inventory = inventory.get("artifacts")
    if type(artifact_inventory) is not list:
        errors.append("invalid SPDX SBOM: artifact inventory is absent")
        return
    if inventory.get("artifactCount") != len(artifact_inventory):
        errors.append("invalid SPDX SBOM: artifact inventory count mismatch")
    artifact_set = hashlib.sha256(
        "".join(
            f"{item['sha256']} {item['name']}\n"
            for item in sorted(artifacts.values(), key=lambda value: value["name"])
        ).encode("utf-8")
    ).hexdigest()
    if inventory.get("artifactSetSha256") != artifact_set:
        errors.append("invalid SPDX SBOM: artifact set SHA-256 mismatch")
    expected_namespace = (
        f"https://cyryxlabs.com/spdx/onyx/{version}/{artifact_set}"
    )
    if sbom.get("documentNamespace") != expected_namespace:
        errors.append("invalid SPDX SBOM: document namespace is not artifact-bound")
    if sbom.get("name") != f"Onyx-{version}-{artifact_set[:12]}":
        errors.append("invalid SPDX SBOM: document name is not artifact-bound")
    if sbom.get("documentDescribes") != ["SPDXRef-Package-Onyx"]:
        errors.append("invalid SPDX SBOM: documentDescribes must name only Onyx")

    inventory_by_name: dict[str, dict[str, Any]] = {}
    for item in artifact_inventory:
        if type(item) is not dict or type(item.get("name")) is not str:
            errors.append("invalid SPDX SBOM: artifact inventory record is malformed")
            continue
        name = item["name"]
        if name in inventory_by_name:
            errors.append(f"invalid SPDX SBOM: duplicate artifact inventory: {name}")
            continue
        inventory_by_name[name] = item
    if set(inventory_by_name) != set(artifacts):
        errors.append("invalid SPDX SBOM: artifact inventory does not match manifests")

    expected_file_ids: set[str] = set()
    for name, expected in artifacts.items():
        item = inventory_by_name.get(name)
        if item is None:
            continue
        for field in ("name", "size", "sha256", "manifest", "manifestSha256"):
            if item.get(field) != expected[field]:
                errors.append(
                    f"invalid SPDX SBOM: artifact inventory mismatch for {name}: {field}"
                )
        artifact_id = item.get("artifactSpdxId")
        if type(artifact_id) is not str:
            errors.append(f"invalid SPDX SBOM: artifact SPDXID absent for {name}")
        else:
            expected_file_ids.add(artifact_id)
            file_record = files_by_id.get(artifact_id, {})
            if (
                file_record.get("fileName") != f"./release/{name}"
                or _spdx_sha256(file_record.get("checksums")) != expected["sha256"]
            ):
                errors.append(
                    f"invalid SPDX SBOM: outer artifact file coverage mismatch: {name}"
                )
        try:
            coverage, actual_members = inventory_artifact(release_dir / name)
        except ReleaseSbomError as exc:
            errors.append(f"invalid SPDX SBOM: {exc}")
            continue
        for field in ("kind", "memberCount", "memberRootSha256"):
            if item.get(field) != coverage[field]:
                errors.append(
                    f"invalid SPDX SBOM: member coverage mismatch for {name}: {field}"
                )
        member_inventory = item.get("members")
        if type(member_inventory) is not list:
            errors.append(f"invalid SPDX SBOM: member inventory absent for {name}")
            continue
        actual_by_path = {member["path"]: member for member in actual_members}
        inventory_members: dict[str, dict[str, Any]] = {}
        for member in member_inventory:
            if type(member) is not dict or type(member.get("path")) is not str:
                errors.append(
                    f"invalid SPDX SBOM: malformed member inventory for {name}"
                )
                continue
            path = member["path"]
            if path in inventory_members:
                errors.append(
                    f"invalid SPDX SBOM: duplicate member inventory for {name}: {path}"
                )
                continue
            inventory_members[path] = member
        if set(inventory_members) != set(actual_by_path):
            errors.append(f"invalid SPDX SBOM: member file coverage mismatch for {name}")
        for path, actual in actual_by_path.items():
            member = inventory_members.get(path)
            if member is None:
                continue
            if member.get("size") != actual["size"] or member.get("sha256") != actual["sha256"]:
                errors.append(
                    f"invalid SPDX SBOM: member byte mismatch for {name}: {path}"
                )
            member_id = member.get("spdxId")
            if type(member_id) is not str:
                errors.append(
                    f"invalid SPDX SBOM: member SPDXID absent for {name}: {path}"
                )
                continue
            expected_file_ids.add(member_id)
            file_record = files_by_id.get(member_id, {})
            if (
                file_record.get("fileName") != f"./contents/{name}/{path}"
                or _spdx_sha256(file_record.get("checksums")) != actual["sha256"]
            ):
                errors.append(
                    f"invalid SPDX SBOM: member SPDX coverage mismatch for {name}: {path}"
                )
    if set(files_by_id) != expected_file_ids:
        errors.append("invalid SPDX SBOM: SPDX file set is incomplete or contains extras")

    relationships = sbom.get("relationships")
    relationship_set: set[tuple[str, str, str]] = set()
    if type(relationships) is list:
        for item in relationships:
            if type(item) is dict:
                values = (
                    item.get("spdxElementId"),
                    item.get("relationshipType"),
                    item.get("relatedSpdxElement"),
                )
                if all(type(value) is str for value in values):
                    relationship_set.add(values)  # type: ignore[arg-type]
    expected_relationships = {
        ("SPDXRef-Package-Onyx", "CONTAINS", spdx_id)
        for spdx_id in expected_file_ids
    } | {
        ("SPDXRef-Package-Onyx", "OTHER", item.spdx_id)
        for item in locked
    }
    if relationship_set != expected_relationships:
        errors.append("invalid SPDX SBOM: package/file relationships are incomplete")


def _validate_sbom(
    root: Path,
    release_dir: Path,
    version: str,
    artifacts: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    sbom_path = release_dir / SBOM_FILE
    sbom = _load_json(sbom_path, "SPDX SBOM", errors)
    if isinstance(sbom, dict):
        if not SPDX_VERSION_RE.fullmatch(str(sbom.get("spdxVersion", ""))):
            errors.append("invalid SPDX SBOM: spdxVersion is absent or unsupported")
        if sbom.get("SPDXID") != "SPDXRef-DOCUMENT":
            errors.append("invalid SPDX SBOM: document SPDXID is not SPDXRef-DOCUMENT")
        if sbom.get("dataLicense") != "CC0-1.0":
            errors.append("invalid SPDX SBOM: dataLicense must be CC0-1.0")
        namespace = sbom.get("documentNamespace")
        if not isinstance(namespace, str) or not namespace.startswith(("https://", "urn:")):
            errors.append("invalid SPDX SBOM: documentNamespace must be an absolute URI")

        creation = sbom.get("creationInfo")
        if not isinstance(creation, dict):
            errors.append("invalid SPDX SBOM: creationInfo is absent")
        else:
            if not SPDX_CREATED_RE.fullmatch(str(creation.get("created", ""))):
                errors.append("invalid SPDX SBOM: creationInfo.created is not UTC SPDX time")
            creators = creation.get("creators")
            if not isinstance(creators, list) or not creators or not all(
                isinstance(item, str)
                and item.startswith(("Person: ", "Organization: ", "Tool: "))
                for item in creators
            ):
                errors.append("invalid SPDX SBOM: creationInfo.creators is absent or malformed")

        packages = sbom.get("packages")
        product_packages = []
        if isinstance(packages, list):
            product_packages = [
                item
                for item in packages
                if isinstance(item, dict)
                and str(item.get("name", "")).casefold() == "onyx"
                and item.get("versionInfo") == version
                and isinstance(item.get("SPDXID"), str)
            ]
        if not product_packages:
            errors.append(f"invalid SPDX SBOM: no Onyx package matches release version {version}")
        else:
            described = sbom.get("documentDescribes")
            described_ids = set(described) if isinstance(described, list) else set()
            if not any(item["SPDXID"] in described_ids for item in product_packages):
                errors.append("invalid SPDX SBOM: versioned Onyx package is not documentDescribes")
        _validate_technical_inventory(
            root=root,
            release_dir=release_dir,
            version=version,
            sbom=sbom,
            artifacts=artifacts,
            errors=errors,
        )
    elif sbom is not None:
        errors.append("invalid SPDX SBOM: top-level JSON value must be an object")

    digest_path = release_dir / SBOM_DIGEST_FILE
    if not _regular_file(digest_path, "SBOM digest manifest", errors):
        return
    try:
        digest_text = digest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(
            f"invalid SBOM digest manifest: unreadable UTF-8 file ({type(exc).__name__})"
        )
        return
    match = re.fullmatch(rf"([0-9a-f]{{64}})  {re.escape(SBOM_FILE)}\n?", digest_text)
    if not match:
        errors.append("invalid SBOM digest manifest: expected one canonical SHA-256 record")
    elif sbom_path.is_file() and not sbom_path.is_symlink():
        actual = _sha256(sbom_path)
        if match.group(1) != actual:
            errors.append("invalid SBOM digest manifest: SBOM SHA-256 mismatch")


def _validate_release_manifests(
    release_dir: Path,
    version: str,
    errors: list[str],
    *,
    required_targets: tuple[str, ...] = (),
    windows_native_verifier: Callable[..., dict[str, object]] | None = None,
    trusted_windows_receipt_sha256: str = "",
    workflow_run_id: str = "",
    workflow_sha: str = "",
) -> dict[str, dict[str, Any]]:
    artifact_records: dict[str, dict[str, Any]] = {}
    if not release_dir.is_dir():
        errors.append(f"missing release directory: {release_dir}")
        return artifact_records
    manifests = sorted(release_dir.glob("release-manifest-*.json"), key=lambda p: p.name)
    if not manifests:
        errors.append("missing current release manifest: release-manifest-*.json")
        return artifact_records

    seen_artifacts: set[str] = set()
    seen_targets: set[str] = set()
    valid_records = 0
    for manifest_path in manifests:
        label = f"release manifest {manifest_path.name}"
        manifest = _load_json(manifest_path, label, errors)
        if not isinstance(manifest, dict):
            if manifest is not None:
                errors.append(f"invalid {label}: top-level JSON value must be an object")
            continue
        if manifest.get("product") != "Onyx":
            errors.append(f"invalid {label}: product must be Onyx")
        if manifest.get("version") != version:
            errors.append(f"invalid {label}: version does not match {version}")
        if not isinstance(manifest.get("system"), str) or not manifest["system"].strip():
            errors.append(f"invalid {label}: system is absent")
        else:
            from core.native_activation_contract_v1 import (
                NativeActivationContractError,
                activation_contract_for_system_v1,
            )

            try:
                expected_activation = activation_contract_for_system_v1(
                    manifest["system"]
                )
            except NativeActivationContractError:
                errors.append(
                    f"invalid {label}: system has no native activation contract"
                )
            else:
                if manifest.get("activation_contract") != expected_activation:
                    errors.append(
                        f"invalid {label}: activation contract is absent or mismatched"
                    )
        if not isinstance(manifest.get("architecture"), str) or not manifest[
            "architecture"
        ].strip():
            errors.append(f"invalid {label}: architecture is absent")
        elif isinstance(manifest.get("system"), str):
            target = f"{manifest['system']}-{manifest['architecture']}"
            if target in seen_targets:
                errors.append(f"invalid {label}: duplicate release target {target}")
            seen_targets.add(target)
        records = manifest.get("artifacts")
        if not isinstance(records, list) or not records:
            errors.append(f"invalid {label}: artifacts must be a non-empty list")
            continue
        _validate_formal_manifest(
            release_dir,
            manifest,
            [item for item in records if type(item) is dict],
            label,
            errors,
            windows_native_verifier=windows_native_verifier,
            trusted_windows_receipt_sha256=trusted_windows_receipt_sha256,
            workflow_run_id=workflow_run_id,
            workflow_sha=workflow_sha,
        )
        for index, record in enumerate(records):
            record_label = f"{label} artifact[{index}]"
            if not isinstance(record, dict):
                errors.append(f"invalid {record_label}: record must be an object")
                continue
            name = record.get("name")
            size = record.get("size")
            expected_hash = record.get("sha256")
            if (
                not isinstance(name, str)
                or not name
                or Path(name).name != name
                or "/" in name
                or "\\" in name
            ):
                errors.append(f"invalid {record_label}: artifact name is unsafe")
                continue
            if name in seen_artifacts:
                errors.append(f"invalid {record_label}: duplicate artifact name {name}")
                continue
            seen_artifacts.add(name)
            if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
                errors.append(f"invalid {record_label}: size must be a positive integer")
                continue
            if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
                errors.append(f"invalid {record_label}: sha256 must be canonical lowercase hex")
                continue
            artifact_path = release_dir / name
            if not _regular_file(artifact_path, f"release artifact {name}", errors):
                continue
            if artifact_path.stat().st_size != size:
                errors.append(f"invalid release artifact {name}: size mismatch")
                continue
            if _sha256(artifact_path) != expected_hash:
                errors.append(f"invalid release artifact {name}: SHA-256 mismatch")
                continue
            valid_records += 1
            artifact_records[name] = {
                "name": name,
                "size": size,
                "sha256": expected_hash,
                "manifest": manifest_path.name,
                "manifestSha256": _sha256(manifest_path),
            }
    if valid_records == 0:
        errors.append("no release artifact has a valid current manifest record")
    missing_targets = sorted(set(required_targets) - seen_targets)
    unexpected_targets = sorted(seen_targets - set(required_targets)) if required_targets else []
    if missing_targets:
        errors.append(f"missing required release targets: {', '.join(missing_targets)}")
    if unexpected_targets:
        errors.append(f"unexpected release targets: {', '.join(unexpected_targets)}")
    return artifact_records


def check_release_eligibility(
    *,
    root: Path,
    release_dir: Path,
    version: str,
    repository_approval: str,
    legal_approval: str = "",
    required_targets: tuple[str, ...] = (),
    windows_native_verifier: Callable[..., dict[str, object]] | None = None,
    trusted_windows_receipt_sha256: str = "",
    workflow_run_id: str = "",
    workflow_sha: str = "",
) -> tuple[str, ...]:
    """Return deterministic blocking reasons; an empty tuple means eligible."""
    errors: list[str] = []
    if repository_approval.strip().casefold() != "true":
        errors.append(f"repository approval variable {APPROVAL_ENV} is not true")
    if legal_approval.strip().casefold() != "true":
        errors.append(f"legal approval variable {LEGAL_APPROVAL_ENV} is not true")
    if not version or version.strip() != version or any(char.isspace() for char in version):
        errors.append("release version is absent or malformed")

    _legal_text(
        root / LICENSE_FILE,
        "product license",
        ("license", "copyright", "creative commons", "permission"),
        errors,
    )
    _legal_text(
        root / NOTICES_FILE,
        "third-party notices",
        ("third-party", "third party", "license", "copyright", "notice"),
        errors,
    )
    artifacts = _validate_release_manifests(
        release_dir,
        version,
        errors,
        required_targets=required_targets,
        windows_native_verifier=windows_native_verifier,
        trusted_windows_receipt_sha256=trusted_windows_receipt_sha256,
        workflow_run_id=workflow_run_id,
        workflow_sha=workflow_sha,
    )
    _validate_sbom(root, release_dir, version, artifacts, errors)
    return tuple(sorted(set(errors)))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate fail-closed eligibility for a public Onyx release"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--release-dir", type=Path, default=Path("release"))
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--repository-approval",
        default=os.environ.get(APPROVAL_ENV, ""),
        help=f"must be true; normally sourced from repository variable {APPROVAL_ENV}",
    )
    parser.add_argument(
        "--legal-approval",
        default=os.environ.get(LEGAL_APPROVAL_ENV, ""),
        help=f"must be true; normally sourced from repository variable {LEGAL_APPROVAL_ENV}",
    )
    parser.add_argument(
        "--required-target",
        action="append",
        default=[],
        help="required exact manifest target such as Windows-x64; may be repeated",
    )
    parser.add_argument(
        "--trusted-windows-receipt-sha256",
        default="",
        help="digest exported by the prerequisite native Windows verification job",
    )
    parser.add_argument("--workflow-run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--workflow-sha", default=os.environ.get("GITHUB_SHA", ""))
    args = parser.parse_args()
    root = args.root.resolve()
    release_dir = args.release_dir
    if not release_dir.is_absolute():
        release_dir = root / release_dir
    errors = check_release_eligibility(
        root=root,
        release_dir=release_dir,
        version=args.version,
        repository_approval=args.repository_approval,
        legal_approval=args.legal_approval,
        required_targets=tuple(args.required_target),
        trusted_windows_receipt_sha256=args.trusted_windows_receipt_sha256,
        workflow_run_id=args.workflow_run_id,
        workflow_sha=args.workflow_sha,
    )
    if errors:
        print("Public release eligibility: BLOCKED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Public release eligibility: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
