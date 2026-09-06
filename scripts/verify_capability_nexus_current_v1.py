"""Verify the current Capability Nexus closure without rebinding its history."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Final


PROJECT: Final = Path(__file__).resolve().parents[1]
ACCEPTANCE_ID: Final = "VE-CAPABILITY-NEXUS-CURRENT-V1-E6-001"
MANIFEST: Final = (
    "docs/onyx/acceptance/"
    "VE-CAPABILITY-NEXUS-CURRENT-V1-E6-001.manifest.json"
)
MANIFEST_SHA256: Final = (
    "cc14c769930b4c7e21d62b78d37c366474977fbb3d5a3652b42d0fcaac3aa1db"
)
CURRENT_DOMAIN: Final = b"onyx.capability-nexus.current.v1\0"
HISTORY_DOMAIN: Final = b"onyx.capability-nexus.history.v1\0"
CURRENT_ROOT_SHA256: Final = (
    "4b41d577d22b4cd6e01530e94a1f1b1cb4448e60d68ec1181ecc5bdc5ecfe4a1"
)
HISTORY_ROOT_SHA256: Final = (
    "8aeb1e9b6243cf7c8f7d09e8bdffd3b75cdb07468dbece1b0f40e4873dcbe311"
)
CATALOG_COUNT: Final = 32
CURRENT_INPUT_COUNT: Final = 67
PROJECTIONS: Final = (
    "docs/onyx/CAPABILITY_MATRIX.md",
    "docs/onyx/RELEASE_CUT_TODAY.md",
    "docs/onyx/VERIFICATION_EVIDENCE.md",
)
MARKER: Final = "CAPABILITY_NEXUS_CURRENT_V1_ACCEPTANCE_OK"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IMPLEMENTATION = re.compile(r"^core/capability_nexus_v([1-9][0-9]*)\.py$")
_TEST = re.compile(r"^tests/test_capability_nexus_v([1-9][0-9]*)\.py$")
_HISTORICAL = re.compile(
    r"^docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V([1-9][0-9]*)-001\.sha256$"
)
_REPARSE_ATTRIBUTE = 0x400


class CapabilityNexusCurrentV1Error(RuntimeError):
    """The current closure or preserved historical identity is invalid."""


def _relative(value: str) -> PurePosixPath:
    if type(value) is not str or not value or "\\" in value or "\x00" in value:
        raise CapabilityNexusCurrentV1Error("path is not canonical")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or str(parsed) != value or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise CapabilityNexusCurrentV1Error("path is not canonical")
    return parsed


def _file(project: Path, relative: str) -> Path:
    parsed = _relative(relative)
    current = project.resolve()
    for index, part in enumerate(parsed.parts):
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise CapabilityNexusCurrentV1Error(
                f"required file is unavailable: {relative}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        ):
            raise CapabilityNexusCurrentV1Error(
                f"required path uses a link/reparse point: {relative}"
            )
        if index < len(parsed.parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise CapabilityNexusCurrentV1Error(
                f"required path ancestor is not a directory: {relative}"
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        raise CapabilityNexusCurrentV1Error(
            f"required path is not a regular file: {relative}"
        )
    return current


def _bytes(project: Path, relative: str) -> bytes:
    try:
        return _file(project, relative).read_bytes()
    except OSError as exc:
        raise CapabilityNexusCurrentV1Error(
            f"required file cannot be read: {relative}"
        ) from exc


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_text(project: Path, relative: str) -> str:
    raw = _bytes(project, relative)
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise CapabilityNexusCurrentV1Error(f"text is not canonical: {relative}")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CapabilityNexusCurrentV1Error(f"text is not UTF-8: {relative}") from exc


def _strict_json(raw: bytes) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise CapabilityNexusCurrentV1Error(f"duplicate manifest key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CapabilityNexusCurrentV1Error("acceptance manifest is invalid") from exc
    if type(value) is not dict:
        raise CapabilityNexusCurrentV1Error("acceptance manifest must be an object")
    return value


def _current_root(records: list[dict[str, object]]) -> str:
    digest = hashlib.sha256(CURRENT_DOMAIN)
    for record in records:
        digest.update(f"{record['path']}\0{record['sha256']}\n".encode())
    return digest.hexdigest()


def _history_root(records: list[dict[str, object]]) -> str:
    digest = hashlib.sha256(HISTORY_DOMAIN)
    for record in records:
        digest.update(
            (
                f"{record['version']}\0{record['path']}\0{record['sha256']}\0"
                f"{record['records']}\n"
            ).encode()
        )
    return digest.hexdigest()


def _parse_historical_manifest(raw: bytes, relative: str) -> int:
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise CapabilityNexusCurrentV1Error(
            f"historical manifest is not canonical: {relative}"
        )
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise CapabilityNexusCurrentV1Error(
            f"historical manifest is not UTF-8: {relative}"
        ) from exc
    if not lines:
        raise CapabilityNexusCurrentV1Error("historical manifest is empty")
    seen: set[str] = set()
    for line in lines:
        if len(line) < 67 or line[64:66] != "  " or not _HEX64.fullmatch(line[:64]):
            raise CapabilityNexusCurrentV1Error(
                f"historical manifest record is malformed: {relative}"
            )
        embedded = line[66:]
        _relative(embedded)
        if embedded in seen:
            raise CapabilityNexusCurrentV1Error(
                f"historical manifest record is duplicated: {relative}"
            )
        seen.add(embedded)
    return len(lines)


def verify(project: Path = PROJECT) -> dict[str, object]:
    """Verify current bytes and parse predecessor manifests as history only."""

    project = Path(project)
    manifest_raw = _bytes(project, MANIFEST)
    if _digest(manifest_raw) != MANIFEST_SHA256:
        raise CapabilityNexusCurrentV1Error("acceptance manifest digest drifted")
    if (
        manifest_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in manifest_raw
        or not manifest_raw.endswith(b"\n")
    ):
        raise CapabilityNexusCurrentV1Error("acceptance manifest is not canonical")
    manifest = _strict_json(manifest_raw)
    required_keys = {
        "schema", "acceptance_id", "decision", "catalog_versions",
        "catalog_count", "current_inputs", "current_input_count",
        "current_root_algorithm", "current_root_sha256",
        "historical_tombstones", "historical_manifest_count",
        "historical_root_algorithm", "historical_root_sha256",
        "historical_policy", "mutable_projections", "runtime_effect",
    }
    if set(manifest) != required_keys or (
        manifest["schema"] != "onyx.capability-nexus.current.acceptance.v1"
        or manifest["acceptance_id"] != ACCEPTANCE_ID
        or manifest["decision"] != "accepted-current-source-integrity"
        or manifest["catalog_versions"] != [1, 32]
        or manifest["catalog_count"] != CATALOG_COUNT
        or manifest["current_input_count"] != CURRENT_INPUT_COUNT
        or manifest["historical_manifest_count"] != CATALOG_COUNT
        or manifest["runtime_effect"] != "none"
    ):
        raise CapabilityNexusCurrentV1Error("acceptance manifest contract drifted")
    if manifest["historical_policy"] != {
        "current_runtime_authority": False,
        "embedded_digests_rebound_to_live_bytes": False,
        "parse_mode": "canonical-historical-only",
        "status": "superseded-immutable-evidence",
    } or manifest["mutable_projections"] != list(PROJECTIONS):
        raise CapabilityNexusCurrentV1Error("historical/projection policy drifted")

    current = manifest["current_inputs"]
    history = manifest["historical_tombstones"]
    if type(current) is not list or type(history) is not list:
        raise CapabilityNexusCurrentV1Error("manifest records are invalid")
    if len(current) != CURRENT_INPUT_COUNT or len(history) != CATALOG_COUNT:
        raise CapabilityNexusCurrentV1Error("manifest record count drifted")
    current_paths: list[str] = []
    implementations: set[int] = set()
    tests: set[int] = set()
    for record in current:
        if type(record) is not dict or set(record) != {"path", "sha256"}:
            raise CapabilityNexusCurrentV1Error("current input record is malformed")
        relative = record["path"]
        expected = record["sha256"]
        if type(relative) is not str or type(expected) is not str or not _HEX64.fullmatch(expected):
            raise CapabilityNexusCurrentV1Error("current input record is invalid")
        _relative(relative)
        if current_paths and relative <= current_paths[-1]:
            raise CapabilityNexusCurrentV1Error("current inputs are not unique/sorted")
        current_paths.append(relative)
        implementation = _IMPLEMENTATION.fullmatch(relative)
        test = _TEST.fullmatch(relative)
        if implementation:
            implementations.add(int(implementation.group(1)))
        elif test:
            tests.add(int(test.group(1)))
        if _digest(_bytes(project, relative)) != expected:
            raise CapabilityNexusCurrentV1Error(f"current input drifted: {relative}")
    expected_versions = set(range(1, CATALOG_COUNT + 1))
    if implementations != expected_versions or tests != expected_versions:
        raise CapabilityNexusCurrentV1Error("current catalog membership drifted")
    discovered_current = {
        path.relative_to(project).as_posix()
        for base, pattern in (("core", "capability_nexus_v*.py"), ("tests", "test_capability_nexus_v*.py"))
        for path in (project / base).glob(pattern)
        if path.is_file()
        and (
            _IMPLEMENTATION.fullmatch(path.relative_to(project).as_posix())
            or _TEST.fullmatch(path.relative_to(project).as_posix())
        )
    }
    expected_current = {
        path
        for path in current_paths
        if _IMPLEMENTATION.fullmatch(path) or _TEST.fullmatch(path)
    }
    if discovered_current != expected_current:
        raise CapabilityNexusCurrentV1Error("unmanifested current catalog file")
    current_root = _current_root(current)
    if current_root != CURRENT_ROOT_SHA256 or manifest["current_root_sha256"] != current_root:
        raise CapabilityNexusCurrentV1Error("current root drifted")

    history_versions: list[int] = []
    history_paths: set[str] = set()
    for record in history:
        if type(record) is not dict or set(record) != {"version", "path", "sha256", "records"}:
            raise CapabilityNexusCurrentV1Error("historical tombstone is malformed")
        version, relative = record["version"], record["path"]
        expected, records = record["sha256"], record["records"]
        if (
            type(version) is not int or type(relative) is not str
            or type(expected) is not str or not _HEX64.fullmatch(expected)
            or type(records) is not int or records < 1
        ):
            raise CapabilityNexusCurrentV1Error("historical tombstone is invalid")
        match = _HISTORICAL.fullmatch(relative)
        if match is None or int(match.group(1)) != version:
            raise CapabilityNexusCurrentV1Error("historical version/path mismatch")
        raw = _bytes(project, relative)
        if _digest(raw) != expected or _parse_historical_manifest(raw, relative) != records:
            raise CapabilityNexusCurrentV1Error(f"historical manifest drifted: {relative}")
        history_versions.append(version)
        history_paths.add(relative)
    if history_versions != list(range(1, CATALOG_COUNT + 1)):
        raise CapabilityNexusCurrentV1Error("historical versions are not closed/ordered")
    discovered_history = {
        path.relative_to(project).as_posix()
        for path in (project / "docs/onyx").glob(
            "VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V*-001.sha256"
        )
        if path.is_file()
    }
    if discovered_history != history_paths:
        raise CapabilityNexusCurrentV1Error("historical manifest set drifted")
    history_root = _history_root(history)
    if history_root != HISTORY_ROOT_SHA256 or manifest["historical_root_sha256"] != history_root:
        raise CapabilityNexusCurrentV1Error("historical root drifted")

    projection_reference = MANIFEST
    for relative in PROJECTIONS:
        text = _canonical_text(project, relative)
        if ACCEPTANCE_ID not in text or projection_reference not in text:
            raise CapabilityNexusCurrentV1Error(
                f"mutable projection omits current successor: {relative}"
            )
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "catalog_count": CATALOG_COUNT,
        "current_inputs": CURRENT_INPUT_COUNT,
        "current_root_sha256": current_root,
        "historical_manifests": CATALOG_COUNT,
        "historical_root_sha256": history_root,
        "historical_status": "superseded-immutable-evidence",
        "runtime_effect": "none",
    }


def main() -> int:
    print(MARKER + " " + json.dumps(verify(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
