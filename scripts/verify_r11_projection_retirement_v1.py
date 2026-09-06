"""Execute retired R11 integrity scenarios without rebinding historical bytes.

Recoverable files are materialized from an authenticated hermetic Git-blob
pack. Files whose
historical bytes are unavailable are copied from the live tree only as an
explicitly non-authoritative projection.  Their digest is captured per
temporary tree so fixture tampering still fails closed without pretending the
current bytes satisfy a historical manifest edge.
"""

from __future__ import annotations

import functools
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Callable, Iterable


PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "tests/fixtures/r11_projection_retirement_v1.json"
RECORD_SHA256 = "4b87a75f4a4e882823b523d7a190d1eda91a034b295d48a6f0208dadc6f2bb07"
SNAPSHOT_ROOT = (
    PROJECT / "docs/onyx/checkpoints/phase5-approval-inbox-v9/mutable-projections"
)
WORKFLOW_PROJECTION = {
    ".github/workflows/release-packages.yml": (
        "84409f0bc2a24ce7c0a6db11419b07d680674df7e77836b51b7cd5509aa03cab"
    ),
    "packaging/linux/onyx.desktop": (
        "0fc6da87140a3f5455eab5995ab5736edf998fd63f98d860359da850efe61724"
    ),
}
BLOB_PACK_MANIFEST = PROJECT / "tests/fixtures/r11_historical_blob_pack_v1.json"
BLOB_PACK_MANIFEST_SHA256 = (
    "f0573e9e38b7a7717e6eaf0d6fc4833894a9c9339bfef1376e309f8f5f1e0ba3"
)
BLOB_PACK_ARCHIVE = PROJECT / "tests/fixtures/r11_historical_blobs_v1.zip"
BLOB_PACK_ARCHIVE_SHA256 = (
    "13279cf6ce44fefb00789bb19387c625a2eabe3ca2ef1829a37462271c8b5004"
)
PHASE5_EXIT_RETIREMENT_RECORD_SHA256 = (
    "23562c773b5e1acceadc6ba873b802eebc1d48bafd61ae40d4a9a23aa0635997"
)


class R11ProjectionRetirementError(RuntimeError):
    """The authenticated retirement or its executable projection drifted."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _relative_path(relative: str) -> Path:
    if type(relative) is not str or not relative or "\\" in relative or "\x00" in relative:
        raise R11ProjectionRetirementError("R11 projection path is not canonical")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or str(parsed) != relative or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise R11ProjectionRetirementError("R11 projection path is not canonical")
    return Path(*parsed.parts)


def _read(root: Path, relative: str) -> bytes:
    base = Path(root).resolve(strict=True)
    path = (base / _relative_path(relative)).resolve(strict=True)
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise R11ProjectionRetirementError(
            f"R11 projection escapes its root: {relative}"
        ) from exc
    if not path.is_file():
        raise R11ProjectionRetirementError(f"R11 projection is not a file: {relative}")
    return path.read_bytes()


def load_retirement_record() -> dict[str, object]:
    raw = RECORD.read_bytes()
    if _sha(raw) != RECORD_SHA256:
        raise R11ProjectionRetirementError("R11 retirement record digest drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise R11ProjectionRetirementError("R11 retirement record is not canonical")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise R11ProjectionRetirementError("R11 retirement record is invalid") from exc
    if type(record) is not dict or set(record) != {
        "schema",
        "issued_at",
        "disposition",
        "policy",
        "lineage",
        "witness",
        "counts",
        "successor",
        "implementation_successors",
        "retired_tests",
        "projections",
    }:
        raise R11ProjectionRetirementError("R11 retirement contract drifted")
    if (
        record["schema"] != "onyx.test.r11-projection-retirement.v1"
        or record["disposition"] != "superseded-unreproducible-not-rebound"
        or record["policy"]
        != {
            "current_tamper_coverage_required": True,
            "historical_hashes_are_rebound_to_live_bytes": False,
            "historical_manifests_remain_immutable": True,
            "live_mutable_targets_are_historical_authority": False,
            "missing_historical_bytes_may_be_fabricated": False,
        }
        or record["counts"]
        != {"total": 35, "recoverable_exact": 23, "unavailable_tombstoned": 12}
    ):
        raise R11ProjectionRetirementError("R11 retirement policy drifted")
    projections = record["projections"]
    implementation_successors = record["implementation_successors"]
    retired_tests = record["retired_tests"]
    if (
        type(projections) is not list
        or len(projections) != 35
        or type(implementation_successors) is not list
        or len(implementation_successors) != 3
        or type(retired_tests) is not list
        or len(retired_tests) != 8
        or len(set(retired_tests)) != len(retired_tests)
        or any(type(test_id) is not str for test_id in retired_tests)
    ):
        raise R11ProjectionRetirementError("R11 retirement entries drifted")
    successor_keys = {
        "path",
        "historical_sha256",
        "git_blob_oid",
        "current_sha256",
        "original_claim",
        "successor_contract",
    }
    successor_paths: list[str] = []
    for entry in implementation_successors:
        if type(entry) is not dict or set(entry) != successor_keys:
            raise R11ProjectionRetirementError("R11 implementation successor is malformed")
        relative = entry["path"]
        historical = entry["historical_sha256"]
        current = entry["current_sha256"]
        oid = entry["git_blob_oid"]
        if (
            type(relative) is not str
            or type(historical) is not str
            or type(current) is not str
            or type(oid) is not str
            or len(historical) != 64
            or len(current) != 64
            or len(oid) != 40
            or historical == current
            or type(entry["original_claim"]) is not str
            or not entry["original_claim"]
            or entry["successor_contract"]
            != "R11ProjectionRetirement.v1 materialize_r11 and verify_r11"
        ):
            raise R11ProjectionRetirementError("R11 implementation successor is invalid")
        _relative_path(relative)
        if _sha(_read(PROJECT, relative)) != current:
            raise R11ProjectionRetirementError("R11 implementation successor drifted")
        _git_blob(oid, historical)
        successor_paths.append(relative)
    if successor_paths != sorted(successor_paths) or len(set(successor_paths)) != 3:
        raise R11ProjectionRetirementError("R11 implementation successor paths drifted")
    states = [entry.get("state") for entry in projections if type(entry) is dict]
    if (
        len(states) != 35
        or states.count("recoverable-exact") != 23
        or states.count("unavailable-tombstoned") != 12
    ):
        raise R11ProjectionRetirementError("R11 retirement counts drifted")
    return record


def registered_test_ids() -> frozenset[str]:
    return frozenset(load_retirement_record()["retired_tests"])


def require_registered_tests_collected(
    collected_nodeids: Iterable[str], *, covered_sources: Iterable[str]
) -> None:
    """Fail when a registered node vanished from a source collected as a suite."""

    collected = frozenset(collected_nodeids)
    sources = frozenset(covered_sources)
    required = frozenset(
        nodeid for nodeid in registered_test_ids() if nodeid.split("::", 1)[0] in sources
    )
    missing = sorted(required - collected)
    if missing:
        raise R11ProjectionRetirementError(
            f"registered R11 test is no longer collected: {missing}"
        )


@functools.lru_cache(maxsize=64)
def _git_blob(oid: str, expected_sha256: str) -> bytes:
    blobs, _head_files = _load_blob_pack()
    data = blobs.get(oid)
    if data is None or _sha(data) != expected_sha256:
        raise R11ProjectionRetirementError("authenticated R11 blob-pack entry drifted")
    return data


def historical_blob(oid: str, expected_sha256: str) -> bytes:
    """Return exact historical bytes without requiring a Git object database."""

    return _git_blob(oid, expected_sha256)


@functools.lru_cache(maxsize=64)
def _git_head_file(relative: str, expected_sha256: str) -> bytes:
    """Recover an exact historical HEAD edge from the authenticated blob pack."""

    _relative_path(relative)
    _blobs, head_files = _load_blob_pack()
    entry = head_files.get(relative)
    if entry is None or entry[1] != expected_sha256:
        raise R11ProjectionRetirementError(
            f"authenticated R11 HEAD edge is unavailable: {relative}"
        )
    oid = entry[0]
    return _git_blob(oid, expected_sha256)


def historical_head_file(relative: str, expected_sha256: str) -> bytes:
    """Return an exact historical HEAD edge without requiring a Git checkout."""

    return _git_head_file(relative, expected_sha256)


@functools.lru_cache(maxsize=1)
def _load_blob_pack() -> tuple[dict[str, bytes], dict[str, tuple[str, str]]]:
    raw = BLOB_PACK_MANIFEST.read_bytes()
    if _sha(raw) != BLOB_PACK_MANIFEST_SHA256:
        raise R11ProjectionRetirementError("R11 blob-pack manifest digest drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise R11ProjectionRetirementError("R11 blob-pack manifest is not canonical")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise R11ProjectionRetirementError("R11 blob-pack manifest is invalid") from exc
    if type(manifest) is not dict or set(manifest) != {
        "schema",
        "retirement_record_sha256",
        "phase5_exit_retirement_record_sha256",
        "archive",
        "blobs",
        "head_files",
    }:
        raise R11ProjectionRetirementError("R11 blob-pack contract drifted")
    archive = manifest["archive"]
    if (
        manifest["schema"] != "onyx.test.r11-historical-blob-pack.v1"
        or manifest["retirement_record_sha256"] != RECORD_SHA256
        or manifest["phase5_exit_retirement_record_sha256"]
        != PHASE5_EXIT_RETIREMENT_RECORD_SHA256
        or type(archive) is not dict
        or archive
        != {
            "path": "tests/fixtures/r11_historical_blobs_v1.zip",
            "sha256": BLOB_PACK_ARCHIVE_SHA256,
            "size": BLOB_PACK_ARCHIVE.stat().st_size,
        }
        or _sha(BLOB_PACK_ARCHIVE.read_bytes()) != BLOB_PACK_ARCHIVE_SHA256
    ):
        raise R11ProjectionRetirementError("R11 blob-pack archive drifted")
    blob_entries = manifest["blobs"]
    head_entries = manifest["head_files"]
    if (
        type(blob_entries) is not list
        or len(blob_entries) != 49
        or type(head_entries) is not list
        or len(head_entries) != 26
        or [entry.get("oid") for entry in blob_entries] != sorted(
            entry.get("oid") for entry in blob_entries if type(entry) is dict
        )
        or [entry.get("path") for entry in head_entries] != sorted(
            entry.get("path") for entry in head_entries if type(entry) is dict
        )
    ):
        raise R11ProjectionRetirementError("R11 blob-pack membership drifted")
    expected_names = [f"blobs/{entry['oid']}.blob" for entry in blob_entries]
    blobs: dict[str, bytes] = {}
    with zipfile.ZipFile(BLOB_PACK_ARCHIVE, "r") as packed:
        if packed.namelist() != expected_names:
            raise R11ProjectionRetirementError("R11 blob-pack ZIP membership drifted")
        for entry in blob_entries:
            if type(entry) is not dict or set(entry) != {"oid", "sha256", "size"}:
                raise R11ProjectionRetirementError("R11 blob-pack entry is malformed")
            oid = entry["oid"]
            data = packed.read(f"blobs/{oid}.blob")
            computed_oid = hashlib.sha1(
                f"blob {len(data)}\0".encode("ascii") + data,
                usedforsecurity=False,
            ).hexdigest()
            if (
                type(oid) is not str
                or len(oid) != 40
                or computed_oid != oid
                or len(data) != entry["size"]
                or _sha(data) != entry["sha256"]
            ):
                raise R11ProjectionRetirementError("R11 blob-pack entry drifted")
            blobs[oid] = data
    head_files: dict[str, tuple[str, str]] = {}
    for entry in head_entries:
        if type(entry) is not dict or set(entry) != {"path", "oid", "sha256"}:
            raise R11ProjectionRetirementError("R11 blob-pack HEAD entry is malformed")
        relative = entry["path"]
        _relative_path(relative)
        if entry["oid"] not in blobs or _sha(blobs[entry["oid"]]) != entry["sha256"]:
            raise R11ProjectionRetirementError("R11 blob-pack HEAD entry drifted")
        head_files[relative] = (entry["oid"], entry["sha256"])
    if len(head_files) != len(head_entries):
        raise R11ProjectionRetirementError("R11 blob-pack HEAD paths are duplicated")
    return blobs, head_files


def _projection_entries() -> dict[str, dict[str, object]]:
    record = load_retirement_record()
    entries = {entry["path"]: entry for entry in record["projections"]}
    if len(entries) != 35:
        raise R11ProjectionRetirementError("R11 projection paths are duplicated")
    return entries


def _projection_bytes(relative: str, entry: dict[str, object]) -> tuple[bytes, str]:
    historical = entry["historical_sha256"]
    if entry["state"] == "recoverable-exact":
        data = _git_blob(entry["git_blob_oid"], historical)
        return data, "historical-authoritative"
    if entry["state"] != "unavailable-tombstoned" or entry["git_blob_oid"] is not None:
        raise R11ProjectionRetirementError(f"invalid R11 projection state: {relative}")
    data = _read(PROJECT, relative)
    if _sha(data) == historical:
        raise R11ProjectionRetirementError(
            f"retired R11 bytes unexpectedly became historical: {relative}"
        )
    return data, "current-non-authoritative"


def _manifest_entries(data: bytes, relative: str) -> tuple[tuple[str, str], ...]:
    if b"\r" in data or not data.endswith(b"\n"):
        raise R11ProjectionRetirementError(f"R11 manifest is noncanonical: {relative}")
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise R11ProjectionRetirementError(f"R11 manifest is not UTF-8: {relative}") from exc
    for line in lines:
        digest, separator, child = line.partition("  ")
        _relative_path(child)
        if (
            not separator
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or child in seen
        ):
            raise R11ProjectionRetirementError(f"R11 manifest is malformed: {relative}")
        seen.add(child)
        entries.append((digest, child))
    if not entries:
        raise R11ProjectionRetirementError(f"R11 manifest is empty: {relative}")
    return tuple(entries)


# destination -> path -> (fixture digest, projection role)
_MATERIALIZED: dict[str, dict[str, tuple[str, str]]] = {}


def materialize_r11(
    module: ModuleType,
    destination: Path,
    *,
    write: Callable[[Path, str, bytes], None] | None = None,
) -> tuple[str, ...]:
    """Materialize the mixed historical/current R11 test projection."""

    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    projections = _projection_entries()
    roots = (module.R11_ROOT, module.R11_ACCEPTANCE_MANIFEST, *module.R11_EXTRA_LIVE)
    root_digests = dict(module.R11_SHA256)
    root_digests.update(WORKFLOW_PROJECTION)
    queue: list[tuple[str | None, str]] = [
        (root_digests.get(relative), relative) for relative in roots
    ]
    copied: set[str] = set()
    baseline: dict[str, tuple[str, str]] = {}
    while queue:
        expected, relative = queue.pop(0)
        if relative in copied:
            continue
        entry = projections.get(relative)
        if entry is not None:
            if expected != entry["historical_sha256"]:
                raise R11ProjectionRetirementError(
                    f"R11 historical manifest edge drifted: {relative}"
                )
            data, role = _projection_bytes(relative, entry)
        elif relative in WORKFLOW_PROJECTION:
            digest = WORKFLOW_PROJECTION[relative]
            data = (SNAPSHOT_ROOT / f"{digest}.snapshot").read_bytes()
            role = "historical-authoritative"
        else:
            data = _read(PROJECT, relative)
            role = "historical-authoritative"
        actual = _sha(data)
        if (
            role == "historical-authoritative"
            and expected is not None
            and actual != expected
            and entry is None
        ):
            try:
                data = _git_head_file(relative, expected)
            except (OSError, R11ProjectionRetirementError) as exc:
                raise R11ProjectionRetirementError(
                    f"R11 historical bytes are unavailable: {relative}"
                ) from exc
            actual = _sha(data)
        if role == "historical-authoritative" and expected is not None and actual != expected:
            raise R11ProjectionRetirementError(
                f"R11 historical materialization drifted: {relative}"
            )
        if write is None:
            target = destination / _relative_path(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        else:
            write(destination, relative, data)
        copied.add(relative)
        baseline[relative] = (actual, role)
        if relative.endswith(".sha256"):
            queue.extend(_manifest_entries(data, relative))
    _MATERIALIZED[str(destination.resolve())] = baseline
    return tuple(sorted(copied))


def verify_r11(
    module: ModuleType,
    root: Path,
    roots: tuple[str, ...],
) -> tuple[str, ...]:
    """Verify every edge while keeping unavailable bytes non-authoritative."""

    root = Path(root)
    baseline = _MATERIALIZED.get(str(root.resolve()))
    if baseline is None:
        raise R11ProjectionRetirementError("R11 projection was not materialized")
    projections = _projection_entries()
    queue: list[tuple[str | None, str]] = [(None, relative) for relative in roots]
    visited_manifests: set[str] = set()
    verified: set[str] = set()
    while queue:
        expected, relative = queue.pop(0)
        try:
            data = _read(root, relative)
        except (OSError, R11ProjectionRetirementError) as exc:
            raise R11ProjectionRetirementError(
                f"historical artifact missing: {relative}"
            ) from exc
        actual = _sha(data)
        materialized = baseline.get(relative)
        if materialized is None or actual != materialized[0]:
            raise R11ProjectionRetirementError(
                f"historical artifact digest drifted: {relative}"
            )
        entry = projections.get(relative)
        if expected is not None:
            if entry is None and actual != expected:
                raise R11ProjectionRetirementError(
                    f"historical artifact digest drifted: {relative}"
                )
            if entry is not None and expected != entry["historical_sha256"]:
                raise R11ProjectionRetirementError(
                    f"historical manifest edge drifted: {relative}"
                )
            if entry is not None and entry["state"] == "recoverable-exact" and actual != expected:
                raise R11ProjectionRetirementError(
                    f"historical artifact digest drifted: {relative}"
                )
            if (
                entry is not None
                and entry["state"] == "unavailable-tombstoned"
                and materialized[1] != "current-non-authoritative"
            ):
                raise R11ProjectionRetirementError(
                    f"retired R11 projection gained authority: {relative}"
                )
        verified.add(relative)
        if relative.endswith(".sha256") and relative not in visited_manifests:
            visited_manifests.add(relative)
            queue.extend(_manifest_entries(data, relative))
    missing = sorted(set(projections) - verified)
    if missing:
        raise R11ProjectionRetirementError(
            f"R11 retirement projection is outside manifest closure: {missing}"
        )
    return tuple(sorted(verified))
