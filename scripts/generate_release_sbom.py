"""Generate a deterministic, technical SPDX inventory for Onyx releases.

The inventory deliberately records ``NOASSERTION`` for third-party license
fields.  It proves bytes and coverage; it is not a legal license conclusion or
a substitute for reviewed THIRD_PARTY_NOTICES.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SBOM_NAME = "SBOM.spdx.json"
SBOM_DIGEST_NAME = f"{SBOM_NAME}.sha256"
INVENTORY_SCHEMA = "onyx.release-inventory.v1"
INVENTORY_COMMENT_PREFIX = "ONYX_RELEASE_INVENTORY_V1\n"
LOCK_LINE_RE = re.compile(
    r"^([A-Za-z0-9_.-]+)==([^ ;\\]+)(?:\s*;\s*([^\\]+?))?\s*\\?$"
)
SPDX_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ReleaseSbomError(RuntimeError):
    """The release inputs cannot produce an exact technical inventory."""


@dataclass(frozen=True, order=True)
class LockedPackage:
    name: str
    version: str
    marker: str

    @property
    def normalized_name(self) -> str:
        return re.sub(r"[-_.]+", "-", self.name).lower()

    @property
    def spdx_id(self) -> str:
        token = f"{self.normalized_name}\0{self.version}\0{self.marker}"
        suffix = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        return f"SPDXRef-Package-Lock-{suffix}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_requirements_lock(path: Path) -> tuple[LockedPackage, ...]:
    """Return the exact name/version/marker records in a uv pip lock."""

    if not path.is_file() or path.is_symlink():
        raise ReleaseSbomError(f"dependency lock is unavailable: {path}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ReleaseSbomError("dependency lock is not readable UTF-8") from exc
    packages: list[LockedPackage] = []
    seen: set[tuple[str, str, str]] = set()
    for line in lines:
        if not line or line[0].isspace() or line.startswith("#"):
            continue
        match = LOCK_LINE_RE.fullmatch(line)
        if match is None:
            raise ReleaseSbomError(f"unsupported dependency lock record: {line}")
        name, version, marker = match.groups()
        record = LockedPackage(name=name, version=version, marker=(marker or "").strip())
        key = (record.normalized_name, record.version, record.marker)
        if key in seen:
            raise ReleaseSbomError(f"duplicate dependency lock record: {name}=={version}")
        seen.add(key)
        packages.append(record)
    if not packages:
        raise ReleaseSbomError("dependency lock contains no packages")
    return tuple(sorted(packages, key=lambda item: (
        item.normalized_name, item.version, item.marker
    )))


def load_release_artifacts(release_dir: Path, version: str) -> tuple[dict[str, Any], ...]:
    """Load the exact artifact records from every current release manifest."""

    records: list[dict[str, Any]] = []
    names: set[str] = set()
    manifests = sorted(release_dir.glob("release-manifest-*.json"), key=lambda p: p.name)
    if not manifests:
        raise ReleaseSbomError("no release manifests are available")
    for manifest_path in manifests:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ReleaseSbomError(
                f"release manifest is invalid: {manifest_path.name}"
            ) from exc
        if type(manifest) is not dict or manifest.get("version") != version:
            raise ReleaseSbomError(
                f"release manifest version mismatch: {manifest_path.name}"
            )
        artifacts = manifest.get("artifacts")
        if type(artifacts) is not list or not artifacts:
            raise ReleaseSbomError(
                f"release manifest has no artifacts: {manifest_path.name}"
            )
        for item in artifacts:
            if type(item) is not dict or set(item) != {"name", "size", "sha256"}:
                raise ReleaseSbomError(
                    f"release artifact record is malformed: {manifest_path.name}"
                )
            name = item["name"]
            if (
                type(name) is not str
                or not name
                or Path(name).name != name
                or name in names
                or type(item["size"]) is not int
                or isinstance(item["size"], bool)
                or item["size"] <= 0
                or type(item["sha256"]) is not str
                or not SHA256_RE.fullmatch(item["sha256"])
            ):
                raise ReleaseSbomError(f"release artifact record is invalid: {name!r}")
            artifact = release_dir / name
            if not artifact.is_file() or artifact.is_symlink():
                raise ReleaseSbomError(f"release artifact is unavailable: {name}")
            if artifact.stat().st_size != item["size"] or sha256_file(artifact) != item["sha256"]:
                raise ReleaseSbomError(f"release artifact drifted: {name}")
            names.add(name)
            records.append(
                {
                    **item,
                    "manifest": manifest_path.name,
                    "manifestSha256": sha256_file(manifest_path),
                }
            )
    return tuple(sorted(records, key=lambda item: item["name"]))


def load_bundle_inventories(
    release_dir: Path, version: str
) -> tuple[dict[str, Any], ...]:
    """Load and byte-verify the bundle inventory bound by every host manifest."""

    from scripts.runtime_distribution_inventory import INVENTORY_CONTRACT

    records: list[dict[str, Any]] = []
    names: set[str] = set()
    manifests = sorted(release_dir.glob("release-manifest-*.json"), key=lambda p: p.name)
    if not manifests:
        raise ReleaseSbomError("no release manifests are available")
    for manifest_path in manifests:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ReleaseSbomError(
                f"release manifest is invalid: {manifest_path.name}"
            ) from exc
        if type(manifest) is not dict or manifest.get("version") != version:
            raise ReleaseSbomError(
                f"release manifest version mismatch: {manifest_path.name}"
            )
        binding = manifest.get("bundle_inventory")
        required = {
            "name",
            "size",
            "sha256",
            "contract",
            "bundle_root_sha256",
            "file_count",
            "runtime_distribution_count",
            "runtime_distribution_root_sha256",
        }
        if type(binding) is not dict or set(binding) != required:
            raise ReleaseSbomError(
                f"release manifest bundle inventory is absent: {manifest_path.name}"
            )
        name = binding.get("name")
        if (
            type(name) is not str
            or Path(name).name != name
            or name in names
            or type(binding.get("size")) is not int
            or isinstance(binding.get("size"), bool)
            or binding.get("size", 0) <= 0
            or type(binding.get("sha256")) is not str
            or not SHA256_RE.fullmatch(binding["sha256"])
            or binding.get("contract") != INVENTORY_CONTRACT
        ):
            raise ReleaseSbomError(
                f"release manifest bundle inventory is invalid: {manifest_path.name}"
            )
        inventory_path = release_dir / name
        if not inventory_path.is_file() or inventory_path.is_symlink():
            raise ReleaseSbomError(f"bundle inventory is unavailable: {name}")
        if (
            inventory_path.stat().st_size != binding["size"]
            or sha256_file(inventory_path) != binding["sha256"]
        ):
            raise ReleaseSbomError(f"bundle inventory drifted: {name}")
        try:
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ReleaseSbomError(f"bundle inventory is invalid JSON: {name}") from exc
        if (
            type(inventory) is not dict
            or inventory.get("contract") != INVENTORY_CONTRACT
            or inventory.get("product") != "Onyx"
            or inventory.get("version") != version
            or inventory.get("system") != manifest.get("system")
            or inventory.get("architecture") != manifest.get("architecture")
            or inventory.get("bundleRootSha256") != binding["bundle_root_sha256"]
            or inventory.get("fileCount") != binding["file_count"]
            or inventory.get("runtimeDistributionCount")
            != binding["runtime_distribution_count"]
            or inventory.get("runtimeDistributionRootSha256")
            != binding["runtime_distribution_root_sha256"]
            or type(inventory.get("runtimeDistributions")) is not list
            or len(inventory["runtimeDistributions"])
            != binding["runtime_distribution_count"]
        ):
            raise ReleaseSbomError(f"bundle inventory binding mismatch: {name}")
        for distribution in inventory["runtimeDistributions"]:
            if (
                type(distribution) is not dict
                or type(distribution.get("name")) is not str
                or type(distribution.get("normalizedName")) is not str
                or type(distribution.get("version")) is not str
                or not distribution["name"]
                or not distribution["normalizedName"]
                or not distribution["version"]
                or type(distribution.get("metadataSha256")) is not str
                or not SHA256_RE.fullmatch(distribution["metadataSha256"])
            ):
                raise ReleaseSbomError(
                    f"bundle runtime distribution record is invalid: {name}"
                )
        names.add(name)
        records.append(
            {
                "name": name,
                "size": binding["size"],
                "sha256": binding["sha256"],
                "manifest": manifest_path.name,
                "system": manifest["system"],
                "architecture": manifest["architecture"],
                "bundleRootSha256": inventory["bundleRootSha256"],
                "runtimeDistributionRootSha256": inventory[
                    "runtimeDistributionRootSha256"
                ],
                "runtimeDistributions": inventory["runtimeDistributions"],
            }
        )
    return tuple(sorted(records, key=lambda item: item["name"]))


def _canonical_member(name: str) -> str:
    if not name or "\\" in name or "\x00" in name:
        raise ReleaseSbomError("archive member path is not canonical")
    value = PurePosixPath(name)
    if (
        value.is_absolute()
        or value.as_posix() != name
        or any(part in {"", ".", ".."} for part in value.parts)
    ):
        raise ReleaseSbomError(f"archive member path is unsafe: {name}")
    return value.as_posix()


def _file_id(scope: str, name: str) -> str:
    suffix = hashlib.sha256(f"{scope}\0{name}".encode("utf-8")).hexdigest()[:24]
    return f"SPDXRef-File-{suffix}"


def _zip_members(path: Path) -> tuple[dict[str, Any], ...]:
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = _canonical_member(info.filename)
                if name in seen:
                    raise ReleaseSbomError(
                        f"duplicate archive member in {path.name}: {name}"
                    )
                seen.add(name)
                digest = hashlib.sha256()
                with archive.open(info, "r") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                members.append(
                    {
                        "path": name,
                        "size": info.file_size,
                        "sha256": digest.hexdigest(),
                    }
                )
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        if isinstance(exc, ReleaseSbomError):
            raise
        raise ReleaseSbomError(f"ZIP inventory failed: {path.name}") from exc
    return tuple(sorted(members, key=lambda item: item["path"]))


def _tar_members(path: Path) -> tuple[dict[str, Any], ...]:
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        with tarfile.open(path, "r:*") as archive:
            for info in archive.getmembers():
                if not info.isfile():
                    continue
                name = _canonical_member(info.name)
                if name in seen:
                    raise ReleaseSbomError(
                        f"duplicate archive member in {path.name}: {name}"
                    )
                seen.add(name)
                handle = archive.extractfile(info)
                if handle is None:
                    raise ReleaseSbomError(
                        f"TAR member cannot be read in {path.name}: {name}"
                    )
                digest = hashlib.sha256()
                with handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                members.append(
                    {
                        "path": name,
                        "size": info.size,
                        "sha256": digest.hexdigest(),
                    }
                )
    except (OSError, tarfile.TarError, RuntimeError) as exc:
        if isinstance(exc, ReleaseSbomError):
            raise
        raise ReleaseSbomError(f"TAR inventory failed: {path.name}") from exc
    return tuple(sorted(members, key=lambda item: item["path"]))


def _member_root(members: Iterable[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for member in members:
        digest.update(
            f"{member['sha256']} {member['size']} {member['path']}\n".encode("utf-8")
        )
    return digest.hexdigest()


def inventory_artifact(path: Path) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    """Inventory the outer artifact and every member of supported archives."""

    if path.suffix.casefold() == ".zip":
        members = _zip_members(path)
        kind = "zip-members-v1"
    elif path.name.casefold().endswith((".tar", ".tar.gz", ".tar.xz", ".tgz")):
        members = _tar_members(path)
        kind = "tar-members-v1"
    else:
        members = ()
        kind = "opaque-artifact-v1"
    return (
        {
            "kind": kind,
            "memberCount": len(members),
            "memberRootSha256": _member_root(members),
        },
        members,
    )


def _spdx_file(spdx_id: str, file_name: str, sha256: str) -> dict[str, Any]:
    return {
        "SPDXID": spdx_id,
        "fileName": file_name,
        "checksums": [{"algorithm": "SHA256", "checksumValue": sha256}],
        "licenseConcluded": "NOASSERTION",
        "copyrightText": "NOASSERTION",
    }


def build_sbom(
    *, root: Path, release_dir: Path, version: str, created: str
) -> dict[str, Any]:
    """Build a stable SPDX document from exact manifests, bytes and lock input."""

    if not SPDX_TIME_RE.fullmatch(created):
        raise ReleaseSbomError("created must be a canonical UTC SPDX timestamp")
    lock_path = root / "requirements.lock"
    locked = parse_requirements_lock(lock_path)
    artifacts = load_release_artifacts(release_dir, version)
    bundle_inventories = load_bundle_inventories(release_dir, version)
    locked_identities = {
        (item.normalized_name, item.version) for item in locked
    }
    shipped_identities: set[tuple[str, str]] = set()
    for inventory in bundle_inventories:
        for distribution in inventory["runtimeDistributions"]:
            identity = (
                distribution["normalizedName"],
                distribution["version"],
            )
            if identity not in locked_identities:
                raise ReleaseSbomError(
                    "bundle runtime distribution is absent from dependency lock: "
                    f"{identity[0]}=={identity[1]}"
                )
            shipped_identities.add(identity)
    artifact_fingerprint = hashlib.sha256(
        "".join(f"{item['sha256']} {item['name']}\n" for item in artifacts).encode(
            "utf-8"
        )
    ).hexdigest()

    files: list[dict[str, Any]] = []
    inventory_artifacts: list[dict[str, Any]] = []
    relationships: list[dict[str, str]] = []
    for artifact in artifacts:
        artifact_path = release_dir / artifact["name"]
        coverage, members = inventory_artifact(artifact_path)
        artifact_id = _file_id("artifact", artifact["name"])
        files.append(
            _spdx_file(
                artifact_id,
                f"./release/{artifact['name']}",
                artifact["sha256"],
            )
        )
        relationships.append(
            {
                "spdxElementId": "SPDXRef-Package-Onyx",
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": artifact_id,
            }
        )
        member_records: list[dict[str, Any]] = []
        for member in members:
            member_id = _file_id(artifact["name"], member["path"])
            files.append(
                _spdx_file(
                    member_id,
                    f"./contents/{artifact['name']}/{member['path']}",
                    member["sha256"],
                )
            )
            relationships.append(
                {
                    "spdxElementId": "SPDXRef-Package-Onyx",
                    "relationshipType": "CONTAINS",
                    "relatedSpdxElement": member_id,
                }
            )
            member_records.append({**member, "spdxId": member_id})
        inventory_artifacts.append(
            {
                **artifact,
                **coverage,
                "artifactSpdxId": artifact_id,
                "members": member_records,
            }
        )

    packages: list[dict[str, Any]] = [
        {
            "name": "Onyx",
            "SPDXID": "SPDXRef-Package-Onyx",
            "versionInfo": version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": True,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "copyrightText": "NOASSERTION",
            "comment": "Technical byte inventory only; legal review is external.",
        }
    ]
    lock_records: list[dict[str, str]] = []
    for package in locked:
        packages.append(
            {
                "name": package.name,
                "SPDXID": package.spdx_id,
                "versionInfo": package.version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "copyrightText": "NOASSERTION",
                "comment": (
                    "Hash-locked resolution input; distribution and license "
                    f"status not asserted. Environment marker: {package.marker or '<none>'}"
                ),
            }
        )
        relationships.append(
            {
                "spdxElementId": "SPDXRef-Package-Onyx",
                "relationshipType": "OTHER",
                "relatedSpdxElement": package.spdx_id,
                "comment": (
                    "LOCK_INPUT_FOR: universal hash-locked resolution record; "
                    "not a claim that this marker applies to every artifact."
                ),
            }
        )
        lock_records.append(
            {
                "name": package.name,
                "normalizedName": package.normalized_name,
                "version": package.version,
                "marker": package.marker,
                "spdxId": package.spdx_id,
            }
        )

    technical_inventory = {
        "schema": INVENTORY_SCHEMA,
        "artifactSetSha256": artifact_fingerprint,
        "dependencyLock": {
            "path": "requirements.lock",
            "sha256": sha256_file(lock_path),
            "packageCount": len(lock_records),
            "packages": lock_records,
        },
        "artifactCount": len(inventory_artifacts),
        "artifacts": inventory_artifacts,
        "bundleInventoryCount": len(bundle_inventories),
        "bundleInventories": bundle_inventories,
        "shippedRuntimeDistributionCount": len(shipped_identities),
        "shippedRuntimeDistributions": [
            {"normalizedName": name, "version": package_version}
            for name, package_version in sorted(shipped_identities)
        ],
        "technicalOnly": True,
        "licenseReviewComplete": False,
    }
    namespace = f"https://cyryxlabs.com/spdx/onyx/{version}/{artifact_fingerprint}"
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"Onyx-{version}-{artifact_fingerprint[:12]}",
        "documentNamespace": namespace,
        "creationInfo": {
            "created": created,
            "creators": ["Tool: scripts/generate_release_sbom.py"],
        },
        "comment": INVENTORY_COMMENT_PREFIX
        + json.dumps(technical_inventory, sort_keys=True, separators=(",", ":")),
        "documentDescribes": ["SPDXRef-Package-Onyx"],
        "packages": packages,
        "files": sorted(files, key=lambda item: item["fileName"]),
        "relationships": sorted(
            relationships,
            key=lambda item: (
                item["spdxElementId"],
                item["relationshipType"],
                item["relatedSpdxElement"],
            ),
        ),
    }


def write_sbom(
    *, root: Path, release_dir: Path, version: str, created: str
) -> tuple[Path, Path]:
    document = build_sbom(
        root=root.resolve(),
        release_dir=release_dir.resolve(),
        version=version,
        created=created,
    )
    sbom_path = release_dir / SBOM_NAME
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    sbom_path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    digest_path = release_dir / SBOM_DIGEST_NAME
    digest_path.write_text(f"{digest}  {SBOM_NAME}\n", encoding="utf-8", newline="\n")
    return sbom_path, digest_path


def _created_from_epoch(value: str) -> str:
    try:
        epoch = int(value)
        moment = datetime.fromtimestamp(epoch, tz=timezone.utc)
    except (ValueError, OverflowError, OSError) as exc:
        raise ReleaseSbomError("SOURCE_DATE_EPOCH must be an integer timestamp") from exc
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the deterministic technical SPDX release inventory"
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--release-dir", type=Path, default=Path("release"))
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--source-date-epoch",
        required=True,
        help="stable release commit timestamp used for SPDX creationInfo.created",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    release_dir = args.release_dir
    if not release_dir.is_absolute():
        release_dir = root / release_dir
    try:
        sbom, digest = write_sbom(
            root=root,
            release_dir=release_dir,
            version=args.version,
            created=_created_from_epoch(args.source_date_epoch),
        )
    except ReleaseSbomError as exc:
        print(f"Release SBOM generation: BLOCKED: {exc}", file=sys.stderr)
        return 1
    print(f"Release SBOM generation: PASS: {sbom.name}, {digest.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
