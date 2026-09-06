"""Build supplemental legal evidence for distributions missing license files.

The exact PyPI artifacts and any untagged repository supplements are hash
pinned. Conflicts and incomplete texts remain explicit and require legal
decision; this generator only ensures that final packages carry the available
primary-source evidence instead of silently omitting it.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import urlsplit


CONTRACT = "OnyxMissingDistributionLicenseBundle.v1"
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_MEMBER_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024


class MissingDistributionLicenseError(RuntimeError):
    pass


@dataclass(frozen=True)
class LicenseEvidenceSpecV1:
    name: str
    version: str
    filename: str
    artifact_sha256: str
    members: tuple[str, ...]
    decision: str
    supplemental_url: str | None = None
    supplemental_sha256: str | None = None
    supplemental_filename: str = "UNTAGGED-REPOSITORY-LICENSE-SUPPLEMENT.txt"
    supplemental_exact_version_binding: bool = False
    include_artifact: bool = False
    local_supplemental_path: str | None = None


SPECS = (
    LicenseEvidenceSpecV1(
        "odfpy",
        "1.4.1",
        "odfpy-1.4.1.tar.gz",
        "db766a6e59c5103212f3cc92ec8dd50a0f3a02790233ed0b52148b70d3c438ec",
        (
            "odfpy-1.4.1/APACHE-LICENSE-2.0.txt",
            "odfpy-1.4.1/GPL-LICENSE-2.txt",
            "odfpy-1.4.1/README.md",
            "odfpy-1.4.1/odf/element.py",
            "odfpy-1.4.1/odf/grammar.py",
        ),
        "DUAL_LICENSE_AND_LGPL_HEADERS_WITH_OASIS_NOTICE_REQUIRE_LEGAL_APPROVAL",
        "https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt",
        "20e50fe7aae3e56378ebf0417d9de904f55a0e61e4df315333e632a4d3555d95",
        "LGPL-2.1.txt",
        False,
        True,
        "packaging/legal-supplements/LGPL-2.1.txt",
    ),
    LicenseEvidenceSpecV1(
        "WMI",
        "1.5.1",
        "WMI-1.5.1.tar.gz",
        "b6a6be5711b1b6c8d55bda7a8befd75c48c12b770b9d227d31c1737dbf0d40a6",
        ("WMI-1.5.1/PKG-INFO", "WMI-1.5.1/readme.rst"),
        "DECLARED_MIT_BUT_FULL_PERMISSION_TEXT_ABSENT",
    ),
    LicenseEvidenceSpecV1(
        "PyGetWindow",
        "0.0.9",
        "PyGetWindow-0.0.9.tar.gz",
        "17894355e7d2b305cd832d717708384017c1698a90ce24f6f7fbf0242dd0a688",
        (
            "PyGetWindow-0.0.9/PKG-INFO",
            "PyGetWindow-0.0.9/README.md",
            "PyGetWindow-0.0.9/setup.py",
        ),
        "EXACT_SDIST_SAYS_BSD_UNTAGGED_REPOSITORY_TEXT_REQUIRES_APPROVAL",
        (
            "https://raw.githubusercontent.com/asweigart/PyGetWindow/"
            "c5f3070324609e682d082ed53122a36002a3e293/LICENSE.txt"
        ),
        "f8c2193c7e92df1a8335548a69653fa56b0ea3536586d93932f8c79c206df9fd",
    ),
    LicenseEvidenceSpecV1(
        "win10toast",
        "0.9",
        "win10toast-0.9-py2.py3-none-any.whl",
        "44e5afa1001de88a0ee533872231521fa67c7d144f39974089af242d9c4620a4",
        (
            "win10toast-0.9.dist-info/METADATA",
            "win10toast-0.9.dist-info/metadata.json",
        ),
        "EXACT_METADATA_BSD_MIT_CONFLICT_REQUIRES_APPROVAL",
        (
            "https://raw.githubusercontent.com/jithurjacob/"
            "Windows-10-Toast-Notifications/"
            "9d52b73f1af6c60162cf09b99269c4f7b13cdb00/LICENSE"
        ),
        "70849267b734d1170fc0af40b9eec056bb45e2ef59478cddd1984dc32183f5f4",
    ),
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_url(url: str, maximum: int) -> bytes:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname
        not in {
            "pypi.org",
            "files.pythonhosted.org",
            "raw.githubusercontent.com",
            "www.gnu.org",
        }
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or bool(parsed.fragment)
    ):
        raise MissingDistributionLicenseError("upstream URL is not approved HTTPS")
    request = urllib.request.Request(  # noqa: S310 -- validated exact HTTPS host above
        url, headers={"User-Agent": "Cyryx-Onyx-License-Evidence/1"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        declared = response.headers.get("Content-Length", "").strip()
        if declared and int(declared) > maximum:
            raise MissingDistributionLicenseError("upstream response is oversized")
        payload = response.read(maximum + 1)
    if len(payload) > maximum:
        raise MissingDistributionLicenseError("upstream response is oversized")
    return payload


def _artifact(spec: LicenseEvidenceSpecV1, fetch: Callable[[str, int], bytes]) -> bytes:
    metadata_url = f"https://pypi.org/pypi/{spec.name}/{spec.version}/json"
    try:
        metadata = json.loads(fetch(metadata_url, MAX_METADATA_BYTES))
        matches = [
            item for item in metadata["urls"] if item.get("filename") == spec.filename
        ]
        if len(matches) != 1:
            raise MissingDistributionLicenseError("PyPI artifact identity is ambiguous")
        candidate = matches[0]
        if candidate.get("digests", {}).get("sha256") != spec.artifact_sha256:
            raise MissingDistributionLicenseError("PyPI artifact digest drifted")
        url = str(candidate["url"])
        if not url.startswith("https://files.pythonhosted.org/"):
            raise MissingDistributionLicenseError(
                "PyPI artifact URL is not authoritative"
            )
        payload = fetch(url, MAX_ARTIFACT_BYTES)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MissingDistributionLicenseError("PyPI metadata is malformed") from exc
    if _sha(payload) != spec.artifact_sha256:
        raise MissingDistributionLicenseError("downloaded PyPI artifact digest drifted")
    return payload


def _canonical_member(name: str) -> str:
    parsed = PurePosixPath(name)
    if (
        not name
        or parsed.is_absolute()
        or str(parsed) != name
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise MissingDistributionLicenseError("archive contains an unsafe path")
    return name


def _tar_members(payload: bytes) -> dict[str, bytes]:
    selected: dict[str, bytes] = {}
    seen: set[str] = set()
    total = 0
    try:
        archive = tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz")
    except tarfile.TarError as exc:
        raise MissingDistributionLicenseError(
            "source artifact is not a gzip TAR"
        ) from exc
    with archive:
        for member in archive.getmembers():
            name = _canonical_member(member.name)
            folded = name.casefold()
            if folded in seen:
                raise MissingDistributionLicenseError(
                    "archive contains duplicate paths"
                )
            seen.add(folded)
            if member.isdir():
                continue
            if not member.isfile() or member.size < 0:
                raise MissingDistributionLicenseError(
                    "archive contains links or special entries"
                )
            total += member.size
            if total > MAX_ARCHIVE_BYTES:
                raise MissingDistributionLicenseError(
                    "archive extraction budget exceeded"
                )
            if member.size > MAX_MEMBER_BYTES:
                continue
            source = archive.extractfile(member)
            if source is None:
                raise MissingDistributionLicenseError("archive member is unreadable")
            data = source.read(member.size + 1)
            if len(data) != member.size:
                raise MissingDistributionLicenseError("archive member size drifted")
            selected[name] = data
    return selected


def _zip_members(payload: bytes) -> dict[str, bytes]:
    selected: dict[str, bytes] = {}
    total = 0
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise MissingDistributionLicenseError(
            "wheel artifact is not a valid ZIP"
        ) from exc
    with archive:
        seen: set[str] = set()
        for info in archive.infolist():
            name = _canonical_member(info.filename)
            folded = name.casefold()
            if folded in seen:
                raise MissingDistributionLicenseError(
                    "archive contains duplicate paths"
                )
            seen.add(folded)
            total += info.file_size
            if total > MAX_ARCHIVE_BYTES or info.file_size > MAX_MEMBER_BYTES:
                raise MissingDistributionLicenseError(
                    "wheel extraction budget exceeded"
                )
            if not info.is_dir():
                selected[name] = archive.read(info)
    return selected


def _safe_name(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    if not result:
        raise MissingDistributionLicenseError("distribution name is unsafe")
    return result


def generate_missing_distribution_license_bundle(
    output_dir: Path,
    *,
    fetch: Callable[[str, int], bytes] = _read_url,
) -> dict[str, object]:
    if output_dir.exists() or output_dir.is_symlink():
        raise MissingDistributionLicenseError("license evidence output must be new")
    output_dir.mkdir(parents=True)
    packages: list[dict[str, object]] = []
    for spec in SPECS:
        payload = _artifact(spec, fetch)
        members = (
            _zip_members(payload)
            if spec.filename.endswith(".whl")
            else _tar_members(payload)
        )
        package_dir = output_dir / f"{_safe_name(spec.name)}-{spec.version}"
        package_dir.mkdir()
        files: list[dict[str, object]] = []
        if spec.include_artifact:
            artifact_target = package_dir / spec.filename
            artifact_target.write_bytes(payload)
            files.append(
                {
                    "name": artifact_target.name,
                    "sha256": spec.artifact_sha256,
                    "source": f"PyPI exact release artifact for {spec.name} {spec.version}",
                    "exactVersionBinding": True,
                    "correspondingSource": True,
                }
            )
        for member in spec.members:
            try:
                data = members[member]
            except KeyError as exc:
                raise MissingDistributionLicenseError(
                    f"required legal evidence member is absent: {member}"
                ) from exc
            target = package_dir / Path(member).name
            target.write_bytes(data)
            files.append({"name": target.name, "sha256": _sha(data), "source": member})
        if spec.supplemental_url is not None:
            assert spec.supplemental_sha256 is not None
            if spec.local_supplemental_path is None:
                supplemental = fetch(spec.supplemental_url, MAX_MEMBER_BYTES)
                supplemental_source = spec.supplemental_url
            else:
                local_path = Path(__file__).resolve().parents[1] / spec.local_supplemental_path
                supplemental = (
                    local_path.read_bytes() if local_path.is_file() else b""
                )
                if (
                    local_path.is_symlink()
                    or not local_path.is_file()
                    or len(supplemental) > MAX_MEMBER_BYTES
                ):
                    raise MissingDistributionLicenseError(
                        "local repository supplement is absent or unsafe"
                    )
                supplemental_source = (
                    f"{spec.supplemental_url} (hash-pinned local release input: "
                    f"{spec.local_supplemental_path})"
                )
            if _sha(supplemental) != spec.supplemental_sha256:
                raise MissingDistributionLicenseError(
                    "repository supplement digest drifted"
                )
            target = package_dir / spec.supplemental_filename
            target.write_bytes(supplemental)
            files.append(
                {
                    "name": target.name,
                    "sha256": _sha(supplemental),
                    "source": supplemental_source,
                    "exactVersionBinding": spec.supplemental_exact_version_binding,
                }
            )
        packages.append(
            {
                "name": spec.name,
                "version": spec.version,
                "artifact": spec.filename,
                "artifactSha256": spec.artifact_sha256,
                "decision": spec.decision,
                "legalDecision": "REQUIRED",
                "files": files,
            }
        )
    report: dict[str, object] = {
        "contract": CONTRACT,
        "legalDecision": "REQUIRED",
        "packages": packages,
    }
    (output_dir / "inventory.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


__all__ = [
    "CONTRACT",
    "MissingDistributionLicenseError",
    "SPECS",
    "generate_missing_distribution_license_bundle",
]
