"""Reconcile exact release, SBOM, bundle, legal-evidence and installed bytes.

This verifier is deliberately technical.  It proves that evidence is present and
byte-bound to the candidate; it never makes a legal conclusion or grants public
release approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_release_eligibility import _validate_sbom  # noqa: E402
from scripts.generate_release_sbom import (  # noqa: E402
    INVENTORY_COMMENT_PREFIX,
    ReleaseSbomError,
    load_release_artifacts,
    sha256_file,
)


CONTRACT = "onyx.release-compliance-reconciliation.v1"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
REQUIRED_LEGAL_FILES = {
    "LICENSE.txt": "LICENSE",
    "THIRD_PARTY_NOTICES.md": "THIRD_PARTY_NOTICES.md",
    "THIRD_PARTY_LICENSES/LGPL-3.0.txt": "packaging/licenses/LGPL-3.0.txt",
}


class ComplianceReconciliationError(RuntimeError):
    """Exact technical release evidence could not be reconciled."""


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ComplianceReconciliationError(f"{label} is unavailable: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ComplianceReconciliationError(
            f"{label} is invalid JSON: {path.name}"
        ) from exc
    if type(value) is not dict:
        raise ComplianceReconciliationError(
            f"{label} must be a JSON object: {path.name}"
        )
    return value


def _canonical_path(value: object, label: str) -> str:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        raise ComplianceReconciliationError(f"{label} path is not canonical")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ComplianceReconciliationError(f"{label} path is not canonical: {value!r}")
    return value


def _file_map(inventory: dict[str, Any]) -> dict[str, dict[str, Any]]:
    files = inventory.get("files")
    if type(files) is not list:
        raise ComplianceReconciliationError("bundle inventory file list is absent")
    records: dict[str, dict[str, Any]] = {}
    for item in files:
        if type(item) is not dict:
            raise ComplianceReconciliationError(
                "bundle inventory file record is malformed"
            )
        path = _canonical_path(item.get("path"), "bundle inventory")
        size = item.get("size")
        digest = item.get("sha256")
        if (
            path in records
            or type(size) is not int
            or isinstance(size, bool)
            or size < 0
            or type(digest) is not str
            or not SHA256_RE.fullmatch(digest)
        ):
            raise ComplianceReconciliationError(
                f"bundle inventory file record is invalid: {path}"
            )
        records[path] = item
    if inventory.get("fileCount") != len(records):
        raise ComplianceReconciliationError("bundle inventory file count mismatch")
    return records


def _technical_inventory(sbom: dict[str, Any]) -> dict[str, Any]:
    comment = sbom.get("comment")
    if type(comment) is not str or not comment.startswith(INVENTORY_COMMENT_PREFIX):
        raise ComplianceReconciliationError("SBOM exact technical inventory is absent")
    try:
        value = json.loads(comment.removeprefix(INVENTORY_COMMENT_PREFIX))
    except json.JSONDecodeError as exc:
        raise ComplianceReconciliationError(
            "SBOM technical inventory is malformed"
        ) from exc
    if type(value) is not dict:
        raise ComplianceReconciliationError(
            "SBOM technical inventory must be an object"
        )
    return value


def _portable_member_map(
    technical: dict[str, Any], bundle_files: dict[str, dict[str, Any]]
) -> tuple[str, dict[str, dict[str, Any]]]:
    artifacts = technical.get("artifacts")
    if type(artifacts) is not list:
        raise ComplianceReconciliationError("SBOM artifact inventory is absent")
    matches: list[tuple[str, dict[str, dict[str, Any]]]] = []
    expected_paths = set(bundle_files)
    for artifact in artifacts:
        if type(artifact) is not dict or type(artifact.get("members")) is not list:
            continue
        members: dict[str, dict[str, Any]] = {}
        valid = True
        for item in artifact["members"]:
            if type(item) is not dict:
                valid = False
                break
            raw_path = _canonical_path(item.get("path"), "SBOM archive member")
            if not raw_path.startswith("Onyx/"):
                valid = False
                break
            path = raw_path.removeprefix("Onyx/")
            if path in members:
                raise ComplianceReconciliationError(
                    f"duplicate SBOM portable member: {raw_path}"
                )
            members[path] = item
        if valid and set(members) == expected_paths:
            name = artifact.get("name")
            if type(name) is not str:
                raise ComplianceReconciliationError(
                    "SBOM portable artifact name is absent"
                )
            matches.append((name, members))
    if len(matches) != 1:
        raise ComplianceReconciliationError(
            "exactly one portable artifact must close over the bundle inventory"
        )
    return matches[0]


def _assert_bytes(
    record: dict[str, Any], *, size: object, digest: object, label: str
) -> None:
    if record.get("size") != size or record.get("sha256") != digest:
        raise ComplianceReconciliationError(f"byte mismatch: {label}")


def _validate_supplemental_inventories(
    bundle_files: dict[str, dict[str, Any]],
    bundle_root: Path | None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    prefixes = (
        "THIRD_PARTY_LICENSES/missing-distribution-evidence-v1/inventory.json",
        "THIRD_PARTY_LICENSES/primp-1.3.1-native-crates/inventory.json",
    )
    for inventory_path in prefixes:
        item = bundle_files.get(inventory_path)
        if item is None:
            raise ComplianceReconciliationError(
                f"supplemental legal inventory is absent: {inventory_path}"
            )
        record: dict[str, Any] = {
            "path": inventory_path,
            "size": item["size"],
            "sha256": item["sha256"],
        }
        if bundle_root is not None:
            document = _load_json(
                bundle_root / Path(inventory_path), "supplemental legal inventory"
            )
            if document.get("legalDecision") != "REQUIRED":
                raise ComplianceReconciliationError(
                    f"supplemental legal decision must remain REQUIRED: {inventory_path}"
                )
            packages = document.get("packages")
            if type(packages) is not list or not packages:
                raise ComplianceReconciliationError(
                    f"supplemental package inventory is absent: {inventory_path}"
                )
            legal_file_count = 0
            inventory_base = PurePosixPath(inventory_path).parent
            for package in packages:
                if type(package) is not dict:
                    raise ComplianceReconciliationError(
                        f"supplemental package record is malformed: {inventory_path}"
                    )
                legal_files = package.get("legalFiles", package.get("files"))
                if type(legal_files) is not list:
                    raise ComplianceReconciliationError(
                        f"supplemental legal-file list is malformed: {inventory_path}"
                    )
                legal_file_count += len(legal_files)
                for legal_file in legal_files:
                    if type(legal_file) is not dict:
                        raise ComplianceReconciliationError(
                            f"supplemental legal-file record is malformed: {inventory_path}"
                        )
                    if document.get("contract") == "OnyxPrimpNativeLicenseBundle.v1":
                        relative = _canonical_path(
                            legal_file.get("path"), "primp legal evidence"
                        )
                    else:
                        name = package.get("name")
                        version = package.get("version")
                        file_name = _canonical_path(
                            legal_file.get("name"), "distribution legal evidence"
                        )
                        if type(name) is not str or type(version) is not str:
                            raise ComplianceReconciliationError(
                                f"supplemental package identity is absent: {inventory_path}"
                            )
                        relative = PurePosixPath(
                            f"{name}-{version}", file_name
                        ).as_posix()
                    bundled_path = (inventory_base / relative).as_posix()
                    bundled = bundle_files.get(bundled_path)
                    if bundled is None:
                        raise ComplianceReconciliationError(
                            f"supplemental legal evidence is absent: {bundled_path}"
                        )
                    expected_size = legal_file.get("size", bundled["size"])
                    _assert_bytes(
                        bundled,
                        size=expected_size,
                        digest=legal_file.get("sha256"),
                        label=bundled_path,
                    )
            declared_package_count = document.get("packageCount", len(packages))
            declared_legal_count = document.get("legalFileCount", legal_file_count)
            if (
                declared_package_count != len(packages)
                or declared_legal_count != legal_file_count
            ):
                raise ComplianceReconciliationError(
                    f"supplemental inventory count mismatch: {inventory_path}"
                )
            record.update(
                {
                    "contract": document.get("contract"),
                    "packageCount": len(packages),
                    "legalFileCount": legal_file_count,
                    "legalDecision": "REQUIRED",
                }
            )
        records.append(record)
    return records


def _verify_installed(
    installed_root: Path, bundle_files: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    if not installed_root.is_dir() or installed_root.is_symlink():
        raise ComplianceReconciliationError("installed root is unavailable")
    missing: list[str] = []
    mismatched: list[str] = []
    for relative, record in bundle_files.items():
        candidate = installed_root / Path(relative)
        if not candidate.is_file() or candidate.is_symlink():
            missing.append(relative)
        elif (
            candidate.stat().st_size != record["size"]
            or sha256_file(candidate) != record["sha256"]
        ):
            mismatched.append(relative)
    if missing or mismatched:
        raise ComplianceReconciliationError(
            f"installed bundle drifted: missing={len(missing)}, mismatched={len(mismatched)}"
        )
    actual_files = sum(1 for path in installed_root.rglob("*") if path.is_file())
    return {
        "verified": True,
        "expectedFileCount": len(bundle_files),
        "exactFileCount": len(bundle_files),
        "extraFileCount": actual_files - len(bundle_files),
    }


def reconcile_release_compliance(
    *,
    root: Path,
    release_dir: Path,
    version: str,
    bundle_root: Path | None = None,
    installed_root: Path | None = None,
) -> dict[str, Any]:
    """Return a deterministic technical receipt or raise on any byte gap."""

    root = root.resolve()
    release_dir = release_dir.resolve()
    bundle_root = bundle_root.resolve() if bundle_root is not None else None
    installed_root = installed_root.resolve() if installed_root is not None else None
    try:
        artifact_records = load_release_artifacts(release_dir, version)
    except ReleaseSbomError as exc:
        raise ComplianceReconciliationError(str(exc)) from exc
    artifacts = {item["name"]: item for item in artifact_records}
    sbom_errors: list[str] = []
    _validate_sbom(root, release_dir, version, artifacts, sbom_errors)
    if sbom_errors:
        raise ComplianceReconciliationError("; ".join(sorted(set(sbom_errors))))

    sbom_path = release_dir / "SBOM.spdx.json"
    sbom = _load_json(sbom_path, "SPDX SBOM")
    technical = _technical_inventory(sbom)
    bundle_bindings = technical.get("bundleInventories")
    if type(bundle_bindings) is not list or len(bundle_bindings) != 1:
        raise ComplianceReconciliationError(
            "this receipt requires exactly one platform bundle inventory"
        )
    binding = bundle_bindings[0]
    if type(binding) is not dict or type(binding.get("name")) is not str:
        raise ComplianceReconciliationError("bundle inventory binding is malformed")
    inventory = _load_json(release_dir / binding["name"], "bundle inventory")
    bundle_files = _file_map(inventory)
    portable_name, portable_members = _portable_member_map(technical, bundle_files)
    for relative, record in bundle_files.items():
        member = portable_members[relative]
        _assert_bytes(
            record,
            size=member.get("size"),
            digest=member.get("sha256"),
            label=f"portable member {relative}",
        )

    legal_payload: list[dict[str, Any]] = []
    for bundled_path, source_path in REQUIRED_LEGAL_FILES.items():
        bundled = bundle_files.get(bundled_path)
        if bundled is None:
            raise ComplianceReconciliationError(
                f"required legal payload is absent: {bundled_path}"
            )
        source = root / Path(source_path)
        if not source.is_file() or source.is_symlink():
            raise ComplianceReconciliationError(
                f"legal source is absent: {source_path}"
            )
        source_hash = sha256_file(source)
        _assert_bytes(
            bundled,
            size=source.stat().st_size,
            digest=source_hash,
            label=bundled_path,
        )
        legal_payload.append(
            {
                "bundlePath": bundled_path,
                "sourcePath": source_path,
                "size": bundled["size"],
                "sha256": bundled["sha256"],
            }
        )

    distributions = inventory.get("runtimeDistributions")
    if type(distributions) is not list or len(distributions) != inventory.get(
        "runtimeDistributionCount"
    ):
        raise ComplianceReconciliationError(
            "runtime distribution inventory is malformed"
        )
    without_legal: list[str] = []
    noassertion: list[str] = []
    legal_file_total = 0
    for distribution in distributions:
        if type(distribution) is not dict:
            raise ComplianceReconciliationError(
                "runtime distribution record is malformed"
            )
        identity = (
            f"{distribution.get('normalizedName')}=={distribution.get('version')}"
        )
        legal_files = distribution.get("legalFiles")
        if type(legal_files) is not list or not legal_files:
            without_legal.append(identity)
            continue
        legal_file_total += len(legal_files)
        if distribution.get("licenseDeclared") == "NOASSERTION":
            noassertion.append(identity)
        for legal_file in legal_files:
            if type(legal_file) is not dict:
                raise ComplianceReconciliationError(
                    f"runtime legal file record is malformed: {identity}"
                )
            path = _canonical_path(legal_file.get("path"), "runtime legal file")
            bundled = bundle_files.get(path)
            if bundled is None:
                raise ComplianceReconciliationError(
                    f"runtime legal file is absent from bundle: {path}"
                )
            _assert_bytes(
                bundled,
                size=legal_file.get("size"),
                digest=legal_file.get("sha256"),
                label=path,
            )
    if without_legal:
        raise ComplianceReconciliationError(
            "runtime distributions lack legal evidence: "
            + ", ".join(sorted(without_legal))
        )

    if bundle_root is not None:
        for relative, record in bundle_files.items():
            candidate = bundle_root / Path(relative)
            if not candidate.is_file() or candidate.is_symlink():
                raise ComplianceReconciliationError(
                    f"bundle root file is absent: {relative}"
                )
            _assert_bytes(
                record,
                size=candidate.stat().st_size,
                digest=sha256_file(candidate),
                label=f"bundle root {relative}",
            )
    supplemental = _validate_supplemental_inventories(bundle_files, bundle_root)
    installed = (
        _verify_installed(installed_root, bundle_files)
        if installed_root is not None
        else {"verified": False, "reason": "installed root not supplied"}
    )

    return {
        "contract": CONTRACT,
        "product": "Onyx",
        "version": version,
        "scope": "exact-technical-evidence-only",
        "status": "passed",
        "publicReleaseEligible": False,
        "legalApproval": {
            "required": True,
            "granted": False,
            "decision": "not-asserted-by-technical-verifier",
        },
        "release": {
            "artifacts": [
                {key: item[key] for key in ("name", "size", "sha256")}
                for item in artifact_records
            ],
            "artifactSetSha256": technical.get("artifactSetSha256"),
            "sbom": {
                "path": sbom_path.name,
                "size": sbom_path.stat().st_size,
                "sha256": sha256_file(sbom_path),
            },
            "portableArtifact": portable_name,
        },
        "bundle": {
            "inventory": binding["name"],
            "inventorySha256": binding.get("sha256"),
            "rootSha256": inventory.get("bundleRootSha256"),
            "fileCount": len(bundle_files),
            "portableMemberCount": len(portable_members),
            "installed": installed,
        },
        "legalEvidence": {
            "requiredPayload": legal_payload,
            "runtimeDistributionCount": len(distributions),
            "runtimeDistributionsWithLegalFiles": len(distributions),
            "runtimeLegalFileCount": legal_file_total,
            "noAssertionCount": len(noassertion),
            "noAssertionPackages": sorted(noassertion),
            "supplementalInventories": supplemental,
        },
    }


def _receipt_sha256(receipt: dict[str, Any]) -> str:
    payload = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile exact Onyx release and legal-evidence bytes"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--release-dir", type=Path, default=Path("release"))
    parser.add_argument("--version", required=True)
    parser.add_argument("--bundle-root", type=Path)
    parser.add_argument("--installed-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    release_dir = args.release_dir
    if not release_dir.is_absolute():
        release_dir = root / release_dir
    try:
        receipt = reconcile_release_compliance(
            root=root,
            release_dir=release_dir,
            version=args.version,
            bundle_root=args.bundle_root,
            installed_root=args.installed_root,
        )
    except ComplianceReconciliationError as exc:
        print(f"Release compliance reconciliation: BLOCKED: {exc}", file=sys.stderr)
        return 1
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    print(
        "Release compliance reconciliation: PASS: "
        f"receipt-sha256={_receipt_sha256(receipt)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
