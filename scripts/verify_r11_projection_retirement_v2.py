"""Additive R11 retirement materializer for authenticated missing HEAD edges.

V1 remains the authority for the retirement record, historical blob pack,
projection closure, and post-materialization verification.  V2 adds only the
historical ``actions/desktop.py`` blob that was absent from the V1 HEAD index.
"""

from __future__ import annotations

import functools
import hashlib
import json
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Callable

from scripts import verify_r11_projection_retirement_v1 as v1


PROJECT = Path(__file__).resolve().parents[1]
SUPPLEMENT_MANIFEST = PROJECT / "tests/fixtures/r11_historical_blob_supplement_v2.json"
SUPPLEMENT_ARCHIVE = PROJECT / "tests/fixtures/r11_historical_blobs_supplement_v2.zip"
SUPPLEMENT_MANIFEST_SHA256 = "9192457c367b271d82083b063ee623edc2e10369f6eb69c8986ef0803ddc2c5e"
SUPPLEMENT_ARCHIVE_SHA256 = "b26e177a8cab0929b492fa7d9509458b7143ce486470b636ad8f400e98b41455"
SUPPLEMENTAL_HEAD_FILES = {
    "actions/desktop.py": (
        "f53ba13d83fb8127ea8c656f812db1ee3323c9ec",
        "5f580d36ed42baef4d6a063d287e612578a18fb61ccb0de503b153163afa7b0f",
        12265,
    ),
    "actions/file_controller.py": (
        "31cce83d336bbb969ca8d8dbd24cad0cc3513879",
        "34bbf200fd7779972470ad28653ac1279034a188d7610a6735c97b6271104b1e",
        32997,
    ),
    "actions/flight_finder.py": (
        "297adcc5bc33093df20cb20816d5930bb9c97547",
        "72a33ac8b28cd189a427e9dc0153010452c79c8578cee379bfd0a754fb1d2b5a",
        12653,
    ),
    "actions/reminder.py": (
        "0c350e4a4fd9bfc07ff54aafba67c752d6fa9ee4",
        "a386dfe5ce6b8539877486c0e2ce842d07c9687a5b46c5359371b45dd535e2fa",
        10488,
    ),
}

R11ProjectionRetirementError = v1.R11ProjectionRetirementError
load_retirement_record = v1.load_retirement_record
registered_test_ids = v1.registered_test_ids
require_registered_tests_collected = v1.require_registered_tests_collected
historical_blob = v1.historical_blob
historical_head_file = v1.historical_head_file
verify_r11 = v1.verify_r11


@functools.lru_cache(maxsize=1)
def _supplemental_head_files() -> dict[str, bytes]:
    manifest_raw = SUPPLEMENT_MANIFEST.read_bytes()
    if v1._sha(manifest_raw) != SUPPLEMENT_MANIFEST_SHA256:
        raise R11ProjectionRetirementError("R11 V2 supplement manifest digest drifted")
    if (
        manifest_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in manifest_raw
        or not manifest_raw.endswith(b"\n")
    ):
        raise R11ProjectionRetirementError("R11 V2 supplement manifest is not canonical")
    try:
        manifest = json.loads(manifest_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise R11ProjectionRetirementError("R11 V2 supplement manifest is invalid") from exc
    expected = {
        "schema": "onyx.test.r11-historical-blob-supplement.v2",
        "predecessor_manifest_sha256": v1.BLOB_PACK_MANIFEST_SHA256,
        "archive": {
            "path": "tests/fixtures/r11_historical_blobs_supplement_v2.zip",
            "sha256": SUPPLEMENT_ARCHIVE_SHA256,
            "size": SUPPLEMENT_ARCHIVE.stat().st_size,
        },
        "head_files": [
            {"path": path, "oid": oid, "sha256": digest, "size": size}
            for path, (oid, digest, size) in sorted(SUPPLEMENTAL_HEAD_FILES.items())
        ],
    }
    if manifest != expected or v1._sha(SUPPLEMENT_ARCHIVE.read_bytes()) != SUPPLEMENT_ARCHIVE_SHA256:
        raise R11ProjectionRetirementError("R11 V2 supplement contract drifted")
    members = [
        f"blobs/{oid}.blob"
        for oid, _digest, _size in sorted(SUPPLEMENTAL_HEAD_FILES.values())
    ]
    blobs: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(SUPPLEMENT_ARCHIVE, "r") as packed:
            if packed.namelist() != members:
                raise R11ProjectionRetirementError("R11 V2 supplement membership drifted")
            for path, (expected_oid, expected_sha, expected_size) in SUPPLEMENTAL_HEAD_FILES.items():
                data = packed.read(f"blobs/{expected_oid}.blob")
                oid = hashlib.sha1(
                    f"blob {len(data)}\0".encode("ascii") + data,
                    usedforsecurity=False,
                ).hexdigest()
                if len(data) != expected_size or v1._sha(data) != expected_sha or oid != expected_oid:
                    raise R11ProjectionRetirementError("R11 V2 supplemental blob drifted")
                blobs[path] = data
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise R11ProjectionRetirementError("R11 V2 supplement archive is invalid") from exc
    return blobs


def _historical_head_file(relative: str, expected_sha256: str) -> bytes:
    supplement = SUPPLEMENTAL_HEAD_FILES.get(relative)
    if supplement is not None:
        if expected_sha256 != supplement[1]:
            raise R11ProjectionRetirementError("R11 V2 supplemental manifest edge drifted")
        return _supplemental_head_files()[relative]
    return v1.historical_head_file(relative, expected_sha256)


def materialize_r11(
    module: ModuleType,
    destination: Path,
    *,
    write: Callable[[Path, str, bytes], None] | None = None,
) -> tuple[str, ...]:
    """Materialize V1's projection plus the authenticated desktop successor."""

    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    projections = v1._projection_entries()
    roots = (module.R11_ROOT, module.R11_ACCEPTANCE_MANIFEST, *module.R11_EXTRA_LIVE)
    root_digests = dict(module.R11_SHA256)
    root_digests.update(v1.WORKFLOW_PROJECTION)
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
            data, role = v1._projection_bytes(relative, entry)
        elif relative in v1.WORKFLOW_PROJECTION:
            digest = v1.WORKFLOW_PROJECTION[relative]
            data = (v1.SNAPSHOT_ROOT / f"{digest}.snapshot").read_bytes()
            role = "historical-authoritative"
        else:
            data = v1._read(PROJECT, relative)
            role = "historical-authoritative"
        actual = v1._sha(data)
        if role == "historical-authoritative" and expected is not None and actual != expected and entry is None:
            try:
                data = _historical_head_file(relative, expected)
            except (OSError, R11ProjectionRetirementError) as exc:
                raise R11ProjectionRetirementError(
                    f"R11 historical bytes are unavailable: {relative}"
                ) from exc
            actual = v1._sha(data)
        if role == "historical-authoritative" and expected is not None and actual != expected:
            raise R11ProjectionRetirementError(
                f"R11 historical materialization drifted: {relative}"
            )
        if write is None:
            target = destination / v1._relative_path(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        else:
            write(destination, relative, data)
        copied.add(relative)
        baseline[relative] = (actual, role)
        if relative.endswith(".sha256"):
            queue.extend(v1._manifest_entries(data, relative))
    v1._MATERIALIZED[str(destination.resolve())] = baseline
    return tuple(sorted(copied))
