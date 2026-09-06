"""Verify exact Advanced Operations V23 selection and append-only lineage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from scripts.generate_advanced_operations_source_acceptance_v23 import (
    PREDECESSOR_RELATIVE,
    SELECTED_PATHS,
)


PROJECT = Path(__file__).resolve().parents[1]
MANIFEST_RELATIVE = "docs/onyx/acceptance/VE-ADVANCED-OPS-V23-001.manifest.json"
MARKER = "ADVANCED_OPERATIONS_SOURCE_ACCEPTANCE_V23_OK"


class AdvancedOperationsSourceAcceptanceV23Error(RuntimeError):
    """The V23 manifest, selection, or source bytes drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(project: Path = PROJECT) -> dict[str, object]:
    root = Path(project).resolve(strict=True)
    raw = (root / MANIFEST_RELATIVE).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise AdvancedOperationsSourceAcceptanceV23Error("V23 manifest is not canonical")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise AdvancedOperationsSourceAcceptanceV23Error("V23 manifest is invalid") from error
    if type(manifest) is not dict or set(manifest) != {
        "schema", "evidence_id", "status", "predecessor", "domain",
        "root_sha256", "selection", "files"
    }:
        raise AdvancedOperationsSourceAcceptanceV23Error("V23 contract drifted")
    if (
        manifest["schema"] != "onyx.advanced-operations-source-acceptance.v4"
        or manifest["evidence_id"] != "VE-ADVANCED-OPS-V23-001"
        or manifest["status"] != "source_candidate"
        or manifest["domain"] != "ONYX-ADVANCED-OPS-SOURCE-V23"
    ):
        raise AdvancedOperationsSourceAcceptanceV23Error("V23 identity drifted")
    expected_predecessor = {
        "path": PREDECESSOR_RELATIVE,
        "sha256": _sha256(root / PREDECESSOR_RELATIVE),
    }
    if manifest["predecessor"] != expected_predecessor:
        raise AdvancedOperationsSourceAcceptanceV23Error("V22 predecessor drifted")
    expected_selection = {
        "mode": "closed_exact_successor_set",
        "count": len(SELECTED_PATHS),
        "predecessor_manifest_is_immutable": True,
        "historical_hashes_are_rebound": False,
    }
    if manifest["selection"] != expected_selection:
        raise AdvancedOperationsSourceAcceptanceV23Error("V23 selection policy drifted")
    files = manifest["files"]
    if type(files) is not list or [item.get("path") for item in files if type(item) is dict] != list(SELECTED_PATHS):
        raise AdvancedOperationsSourceAcceptanceV23Error("V23 selected paths drifted")
    payload = bytearray(
        f"{manifest['domain']}\0{expected_predecessor['sha256']}\n".encode()
    )
    for item in files:
        if type(item) is not dict or set(item) != {"path", "sha256"}:
            raise AdvancedOperationsSourceAcceptanceV23Error("V23 file binding malformed")
        relative = item["path"]
        parsed = PurePosixPath(relative)
        if parsed.is_absolute() or parsed.as_posix() != relative or ".." in parsed.parts:
            raise AdvancedOperationsSourceAcceptanceV23Error("V23 path is not canonical")
        path = root.joinpath(*parsed.parts)
        expected = item["sha256"]
        if path.is_symlink() or not path.is_file() or path.resolve() != path.absolute() or _sha256(path) != expected:
            raise AdvancedOperationsSourceAcceptanceV23Error(f"V23 source drifted: {relative}")
        payload.extend(f"{relative}\0{expected}\n".encode())
    if hashlib.sha256(payload).hexdigest() != manifest["root_sha256"]:
        raise AdvancedOperationsSourceAcceptanceV23Error("V23 root drifted")
    return manifest


if __name__ == "__main__":
    result = verify()
    print(MARKER, f"files={len(result['files'])}", f"root={result['root_sha256']}")
