"""Generate version-bound native Rust license evidence for primp 1.3.1.

The Python wheel exposes only a top-level license label while its native module
links a Rust dependency graph. This generator retrieves the exact hash-pinned
source distribution, asks Cargo for the platform-filtered normal/build graph,
copies every shipped crate legal file, and writes a deterministic inventory.
It is engineering evidence, not a legal interpretation.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import urlsplit


PRIMP_VERSION = "1.3.1"
PRIMP_SDIST_SHA256 = "b04a5941bf9c876d011c5defaf5a25be093d56e7270b8da52c9788b9df2a829a"
PYPI_JSON_URL = f"https://pypi.org/pypi/primp/{PRIMP_VERSION}/json"
CONTRACT = "OnyxPrimpNativeLicenseBundle.v1"
MAX_SDIST_BYTES = 8 * 1024 * 1024
MAX_EXTRACTED_BYTES = 64 * 1024 * 1024
LEGAL_NAME = re.compile(
    r"^(?:licen[cs]e(?:[._-].*)?|copying(?:[._-].*)?|notice(?:[._-].*)?|copyright(?:[._-].*)?)$",
    re.IGNORECASE,
)


class PrimpLicenseBundleError(RuntimeError):
    """The native license dependency evidence could not be generated safely."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_url(url: str, *, maximum: int) -> bytes:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"pypi.org", "files.pythonhosted.org"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or bool(parsed.fragment)
    ):
        raise PrimpLicenseBundleError("upstream URL is not approved HTTPS")
    request = urllib.request.Request(  # noqa: S310 -- validated exact HTTPS host above
        url, headers={"User-Agent": "Cyryx-Onyx-License-Bundle/1"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        declared = response.headers.get("Content-Length", "").strip()
        if declared and int(declared) > maximum:
            raise PrimpLicenseBundleError("upstream response exceeds the size boundary")
        payload = response.read(maximum + 1)
    if len(payload) > maximum:
        raise PrimpLicenseBundleError("upstream response exceeds the size boundary")
    return payload


def download_exact_sdist() -> bytes:
    try:
        metadata = json.loads(_read_url(PYPI_JSON_URL, maximum=2 * 1024 * 1024))
        candidates = [
            item
            for item in metadata["urls"]
            if item.get("packagetype") == "sdist"
            and item.get("filename") == f"primp-{PRIMP_VERSION}.tar.gz"
        ]
        if len(candidates) != 1:
            raise PrimpLicenseBundleError("PyPI exposes no unique exact primp sdist")
        candidate = candidates[0]
        if candidate.get("digests", {}).get("sha256") != PRIMP_SDIST_SHA256:
            raise PrimpLicenseBundleError("PyPI primp sdist digest drifted")
        url = str(candidate["url"])
        if not url.startswith("https://files.pythonhosted.org/"):
            raise PrimpLicenseBundleError(
                "PyPI primp sdist URL is not authoritative HTTPS"
            )
        payload = _read_url(url, maximum=MAX_SDIST_BYTES)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PrimpLicenseBundleError("PyPI primp metadata is malformed") from exc
    if sha256_bytes(payload) != PRIMP_SDIST_SHA256:
        raise PrimpLicenseBundleError("downloaded primp sdist digest mismatched")
    return payload


def _safe_extract_sdist(payload: bytes, destination: Path) -> Path:
    expected_root = f"primp-{PRIMP_VERSION}"
    destination.mkdir(parents=True, exist_ok=False)
    seen: set[str] = set()
    total = 0
    try:
        archive = tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz")
    except tarfile.TarError as exc:
        raise PrimpLicenseBundleError("primp sdist is not a valid gzip TAR") from exc
    with archive:
        for member in archive.getmembers():
            parsed = PurePosixPath(member.name)
            if (
                not member.name
                or parsed.is_absolute()
                or str(parsed) != member.name
                or not parsed.parts
                or parsed.parts[0] != expected_root
                or any(part in {"", ".", ".."} for part in parsed.parts)
                or member.name.casefold() in seen
            ):
                raise PrimpLicenseBundleError("primp sdist contains an unsafe path")
            seen.add(member.name.casefold())
            target = destination.joinpath(*parsed.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise PrimpLicenseBundleError(
                    "primp sdist contains links or special entries"
                )
            total += member.size
            if member.size < 0 or total > MAX_EXTRACTED_BYTES:
                raise PrimpLicenseBundleError(
                    "primp sdist exceeds extraction boundaries"
                )
            source = archive.extractfile(member)
            if source is None:
                raise PrimpLicenseBundleError("primp sdist member is unreadable")
            data = source.read(member.size + 1)
            if len(data) != member.size:
                raise PrimpLicenseBundleError("primp sdist member size drifted")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    root = destination / expected_root
    if (
        not (root / "Cargo.lock").is_file()
        or not (root / "crates" / "primp-python" / "Cargo.toml").is_file()
    ):
        raise PrimpLicenseBundleError("primp sdist lacks its locked native workspace")
    return root


def target_triple(system: str, architecture: str) -> str:
    key = (system, architecture.casefold())
    targets = {
        ("Windows", "x64"): "x86_64-pc-windows-msvc",
        ("Windows", "x86_64"): "x86_64-pc-windows-msvc",
        ("Windows", "amd64"): "x86_64-pc-windows-msvc",
        ("Windows", "arm64"): "aarch64-pc-windows-msvc",
        ("Windows", "aarch64"): "aarch64-pc-windows-msvc",
        ("Linux", "x64"): "x86_64-unknown-linux-gnu",
        ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
        ("Linux", "amd64"): "x86_64-unknown-linux-gnu",
        ("Linux", "arm64"): "aarch64-unknown-linux-gnu",
        ("Linux", "aarch64"): "aarch64-unknown-linux-gnu",
        ("Darwin", "x64"): "x86_64-apple-darwin",
        ("Darwin", "x86_64"): "x86_64-apple-darwin",
        ("Darwin", "arm64"): "aarch64-apple-darwin",
        ("Darwin", "aarch64"): "aarch64-apple-darwin",
    }
    try:
        return targets[key]
    except KeyError as exc:
        raise PrimpLicenseBundleError(
            f"unsupported primp native license target: {system}/{architecture}"
        ) from exc


def _cargo_metadata(root: Path, cargo_home: Path, target: str) -> dict[str, Any]:
    cargo = shutil.which("cargo")
    if not cargo or not Path(cargo).is_file() or Path(cargo).is_symlink():
        raise PrimpLicenseBundleError("cargo is required for native license resolution")
    environment = os.environ.copy()
    environment["CARGO_HOME"] = str(cargo_home)
    result = subprocess.run(
        [
            str(Path(cargo).resolve(strict=True)),
            "metadata",
            "--locked",
            "--format-version",
            "1",
            "--filter-platform",
            target,
            "--manifest-path",
            str(root / "crates" / "primp-python" / "Cargo.toml"),
        ],
        check=False,
        cwd=root,
        env=environment,
        timeout=900,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="strict",
    )
    if result.returncode != 0:
        raise PrimpLicenseBundleError(
            f"cargo metadata failed with exit {result.returncode}: {result.stderr[-2000:]}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PrimpLicenseBundleError("cargo metadata returned invalid JSON") from exc
    if type(payload) is not dict or type(payload.get("packages")) is not list:
        raise PrimpLicenseBundleError("cargo metadata contract is malformed")
    return payload


def _selected_package_ids(metadata: dict[str, Any]) -> set[str]:
    packages = metadata.get("packages")
    resolve = metadata.get("resolve")
    if type(packages) is not list or type(resolve) is not dict:
        raise PrimpLicenseBundleError("cargo dependency graph is unavailable")
    roots = [
        str(item["id"])
        for item in packages
        if type(item) is dict
        and item.get("name") == "primp-python"
        and item.get("version") == PRIMP_VERSION
        and item.get("source") is None
    ]
    if len(roots) != 1:
        raise PrimpLicenseBundleError("cargo graph has no unique primp-python root")
    nodes = {
        str(node["id"]): node
        for node in resolve.get("nodes", [])
        if type(node) is dict and "id" in node
    }
    selected: set[str] = set()
    queued = roots[:]
    while queued:
        package_id = queued.pop()
        if package_id in selected:
            continue
        selected.add(package_id)
        try:
            node = nodes[package_id]
        except KeyError as exc:
            raise PrimpLicenseBundleError("cargo graph node is missing") from exc
        for dependency in node.get("deps", []):
            if type(dependency) is not dict:
                raise PrimpLicenseBundleError("cargo dependency edge is malformed")
            kinds = dependency.get("dep_kinds", [])
            if kinds and all(
                type(kind) is dict and kind.get("kind") == "dev" for kind in kinds
            ):
                continue
            queued.append(str(dependency["pkg"]))
    return selected


def _lock_checksums(lock_path: Path) -> dict[tuple[str, str, str], str]:
    payload = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    result: dict[tuple[str, str, str], str] = {}
    for item in payload.get("package", []):
        source = str(item.get("source", ""))
        checksum = str(item.get("checksum", ""))
        if source and checksum:
            result[(str(item["name"]), str(item["version"]), source)] = checksum
    return result


def _safe_component(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    if not result:
        raise PrimpLicenseBundleError("native package identity is not path-safe")
    return result


def _legal_files(package_root: Path) -> tuple[Path, ...]:
    files = tuple(
        sorted(
            (
                path
                for path in package_root.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and LEGAL_NAME.fullmatch(path.name)
            ),
            key=lambda path: path.relative_to(package_root).as_posix().casefold(),
        )
    )
    if len(files) > 128 or sum(path.stat().st_size for path in files) > 4 * 1024 * 1024:
        raise PrimpLicenseBundleError("native package legal-file boundary exceeded")
    return files


def _bundle_packages(
    metadata: dict[str, Any],
    *,
    lock_path: Path,
    output: Path,
) -> list[dict[str, Any]]:
    selected = _selected_package_ids(metadata)
    packages = {
        str(item["id"]): item for item in metadata["packages"] if type(item) is dict
    }
    checksums = _lock_checksums(lock_path)
    records: list[dict[str, Any]] = []
    for package_id in sorted(selected):
        try:
            package = packages[package_id]
        except KeyError as exc:
            raise PrimpLicenseBundleError("selected cargo package is missing") from exc
        name = str(package["name"])
        version = str(package["version"])
        raw_source = package.get("source")
        source = str(raw_source or "workspace-sdist")
        stable_id = (
            package_id
            if raw_source is not None
            else f"workspace-sdist:{name}@{version}"
        )
        manifest = Path(str(package["manifest_path"])).resolve(strict=True)
        root = manifest.parent
        key = f"{_safe_component(name)}-{_safe_component(version)}-{hashlib.sha256(stable_id.encode()).hexdigest()[:8]}"
        raw_license_file = package.get("license_file")
        license_file: str | None = None
        if raw_license_file:
            try:
                license_file = (
                    Path(str(raw_license_file))
                    .resolve(strict=True)
                    .relative_to(root)
                    .as_posix()
                )
            except (OSError, ValueError) as exc:
                raise PrimpLicenseBundleError(
                    f"declared native license file escapes package root: {name} {version}"
                ) from exc
        legal_records: list[dict[str, Any]] = []
        for legal in _legal_files(root):
            relative = legal.relative_to(root)
            destination = output / "packages" / key / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legal, destination)
            legal_records.append(
                {
                    "path": destination.relative_to(output).as_posix(),
                    "sourcePath": relative.as_posix(),
                    "sha256": sha256_file(destination),
                    "size": destination.stat().st_size,
                }
            )
        checksum = checksums.get((name, version, source), "")
        if source.startswith("registry+") and not checksum:
            raise PrimpLicenseBundleError(
                f"Cargo.lock checksum is absent: {name} {version}"
            )
        records.append(
            {
                "id": stable_id,
                "name": name,
                "version": version,
                "source": source,
                "cargoChecksum": checksum or None,
                "licenseDeclared": str(package.get("license") or "NOASSERTION"),
                "licenseFileDeclared": license_file,
                "legalFiles": legal_records,
            }
        )
    return sorted(records, key=lambda item: (item["name"], item["version"], item["id"]))


def _legal_root(records: Iterable[dict[str, Any]]) -> str:
    lines = []
    for record in records:
        for legal in record["legalFiles"]:
            lines.append(f"{legal['sha256']} {legal['size']} {legal['path']}\n")
    return hashlib.sha256("".join(sorted(lines)).encode("utf-8")).hexdigest()


def generate_primp_license_bundle(
    *,
    output_dir: Path,
    system: str | None = None,
    architecture: str | None = None,
) -> dict[str, Any]:
    selected_system = system or platform.system()
    selected_architecture = architecture or platform.machine()
    target = target_triple(selected_system, selected_architecture)
    output = output_dir.absolute()
    if output.exists() or output.is_symlink():
        raise PrimpLicenseBundleError("primp native license output already exists")
    payload = download_exact_sdist()
    with tempfile.TemporaryDirectory(prefix="onyx-primp-licenses-") as temporary:
        root = Path(temporary)
        source = _safe_extract_sdist(payload, root / "source")
        cargo_home = root / "cargo-home"
        metadata = _cargo_metadata(source, cargo_home, target)
        output.mkdir(parents=True)
        records = _bundle_packages(
            metadata,
            lock_path=source / "Cargo.lock",
            output=output,
        )
    missing = [
        f"{item['name']}=={item['version']}"
        for item in records
        if not item["legalFiles"]
    ]
    report = {
        "contract": CONTRACT,
        "primpVersion": PRIMP_VERSION,
        "primpSdistSha256": PRIMP_SDIST_SHA256,
        "target": target,
        "packageCount": len(records),
        "legalFileCount": sum(len(item["legalFiles"]) for item in records),
        "legalFileRootSha256": _legal_root(records),
        "packagesWithoutLegalFiles": missing,
        "packages": records,
        "legalDecision": "REQUIRED",
    }
    (output / "inventory.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


__all__ = [
    "CONTRACT",
    "PRIMP_SDIST_SHA256",
    "PRIMP_VERSION",
    "PrimpLicenseBundleError",
    "generate_primp_license_bundle",
    "target_triple",
]
