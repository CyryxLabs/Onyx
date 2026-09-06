"""Verify exact Advanced Operations V24 selection and append-only lineage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from scripts.generate_advanced_operations_source_acceptance_v24 import (
    PREDECESSOR_RELATIVE,
    SELECTED_PATHS,
)


PROJECT = Path(__file__).resolve().parents[1]
MANIFEST_RELATIVE = "docs/onyx/acceptance/VE-ADVANCED-OPS-V24-001.manifest.json"
MARKER = "ADVANCED_OPERATIONS_SOURCE_ACCEPTANCE_V24_OK"
PREDECESSOR_SHA256 = "3b719d4ad59bb19bc23ffad083419352fcf2b8ea5d0049cae51336c1ea034b8c"
MANIFEST_SHA256 = "e3fce0dc583b1cd13285ae535a47bc952ab0cb1b4abf6a258488cdc0901a7d1e"


class AdvancedOperationsSourceAcceptanceV24Error(RuntimeError):
    """The V24 manifest, selection, or source bytes drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    raw = (root / MANIFEST_RELATIVE).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise AdvancedOperationsSourceAcceptanceV24Error("V24 manifest is not canonical")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AdvancedOperationsSourceAcceptanceV24Error("V24 manifest is invalid") from error
    if type(manifest) is not dict or set(manifest) != {
        "schema", "evidence_id", "status", "predecessor", "domain",
        "root_sha256", "selection", "files"
    }:
        raise AdvancedOperationsSourceAcceptanceV24Error("V24 contract drifted")
    if (
        manifest["schema"] != "onyx.advanced-operations-source-acceptance.v4"
        or manifest["evidence_id"] != "VE-ADVANCED-OPS-V24-001"
        or manifest["status"] != "source_candidate"
        or manifest["domain"] != "ONYX-ADVANCED-OPS-SOURCE-V24"
    ):
        raise AdvancedOperationsSourceAcceptanceV24Error("V24 identity drifted")
    expected_predecessor = {
        "path": PREDECESSOR_RELATIVE,
        "sha256": PREDECESSOR_SHA256,
    }
    if manifest["predecessor"] != expected_predecessor or _sha256(root / PREDECESSOR_RELATIVE) != PREDECESSOR_SHA256:
        raise AdvancedOperationsSourceAcceptanceV24Error("V23 predecessor drifted")
    expected_selection = {
        "mode": "closed_exact_successor_set",
        "count": len(SELECTED_PATHS),
        "predecessor_manifest_is_immutable": True,
        "historical_hashes_are_rebound": False,
    }
    if manifest["selection"] != expected_selection:
        raise AdvancedOperationsSourceAcceptanceV24Error("V24 selection policy drifted")
    files = manifest["files"]
    if type(files) is not list or [item.get("path") for item in files if type(item) is dict] != list(SELECTED_PATHS):
        raise AdvancedOperationsSourceAcceptanceV24Error("V24 selected paths drifted")
    payload = bytearray(
        f"{manifest['domain']}\0{expected_predecessor['sha256']}\n".encode()
    )
    for item in files:
        if type(item) is not dict or set(item) != {"path", "sha256"}:
            raise AdvancedOperationsSourceAcceptanceV24Error("V24 file binding malformed")
        relative = item["path"]
        parsed = PurePosixPath(relative)
        if parsed.is_absolute() or parsed.as_posix() != relative or ".." in parsed.parts:
            raise AdvancedOperationsSourceAcceptanceV24Error("V24 path is not canonical")
        path = root.joinpath(*parsed.parts)
        expected = item["sha256"]
        if path.is_symlink() or not path.is_file() or path.resolve() != path.absolute() or _sha256(path) != expected:
            raise AdvancedOperationsSourceAcceptanceV24Error(f"V24 source drifted: {relative}")
        payload.extend(f"{relative}\0{expected}\n".encode())
    if hashlib.sha256(payload).hexdigest() != manifest["root_sha256"]:
        raise AdvancedOperationsSourceAcceptanceV24Error("V24 root drifted")
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise AdvancedOperationsSourceAcceptanceV24Error("V24 manifest drifted")
    return manifest


if __name__ == "__main__":
    result = verify()
    print(MARKER, f"files={len(result['files'])}", f"root={result['root_sha256']}")
