"""Standard-library verifier for the isolated Phase 6 local MCP V1 candidate."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[1]
MANIFEST = (
    PROJECT / "docs" / "onyx" / "checkpoints" / "phase6-local-mcp-v1" / "manifest.json"
)
SUCCESS = "P6_LOCAL_MCP_V1_OK"


class VerificationError(RuntimeError):
    pass


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def regular(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or pure.is_absolute()
        or ".." in pure.parts
        or str(pure) != relative
    ):
        raise VerificationError(f"noncanonical path: {relative!r}")
    path = PROJECT.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise VerificationError(f"not a regular file: {relative}")
    try:
        path.resolve().relative_to(PROJECT.resolve())
    except ValueError as exc:
        raise VerificationError(f"path escapes repository: {relative}") from exc
    return path


def root(records: list[dict[str, object]]) -> str:
    lines = []
    for record in sorted(records, key=lambda value: str(value["path"])):
        lines.append(f"{record['path']}\0{record['sha256']}\n")
    return sha("".join(lines).encode("utf-8"))


def verify() -> dict[str, object]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if (
        manifest.get("schema") != "OnyxPhase6LocalMCP.v1"
        or manifest.get("candidate") != "phase6-local-mcp-candidate-001"
        or manifest.get("status") != "candidate_default_off_not_live"
        or manifest.get("protocol_version") != "2025-11-25"
    ):
        raise VerificationError("candidate identity is invalid")
    activation = manifest.get("activation")
    if activation != {
        "flag": "ONYX_PHASE6_LOCAL_MCP_V1",
        "enabled_value": "true",
        "exact": "ONYX_PHASE6_LOCAL_MCP_V1=true",
        "default": "off",
        "live_wiring": False,
    }:
        raise VerificationError("activation boundary is invalid")
    artifacts = manifest.get("artifacts")
    if type(artifacts) is not list or len(artifacts) != 6:
        raise VerificationError("candidate closure must contain six artifacts")
    for record in artifacts:
        if type(record) is not dict:
            raise VerificationError("artifact record must be an object")
        path = regular(str(record.get("path", "")))
        payload = path.read_bytes()
        if len(payload) != record.get("bytes") or sha(payload) != record.get("sha256"):
            raise VerificationError(f"artifact drift: {record.get('path')}")
    observed_root = root(artifacts)
    if observed_root != manifest.get("artifact_root_sha256"):
        raise VerificationError("artifact root drift")
    anchors = manifest.get("frozen_anchors")
    if type(anchors) is not dict or len(anchors) != 5:
        raise VerificationError("five frozen anchors are required")
    for relative, expected in anchors.items():
        if sha(regular(relative).read_bytes()) != expected:
            raise VerificationError(f"frozen anchor drift: {relative}")

    source_path = regular("core/phase6_local_mcp_v1.py")
    source_text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(source_path))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    if any(
        name == "socket"
        or name.startswith("urllib")
        or name in {"requests", "httpx", "aiohttp"}
        for name in imported
    ):
        raise VerificationError("network library imported")
    for token in (
        'FEATURE_FLAG: Final = "ONYX_PHASE6_LOCAL_MCP_V1"',
        'PROTOCOL_VERSION: Final = "2025-11-25"',
        'TOOL_NAME: Final = "local_catalog_read"',
        '"notifications/initialized"',
        '"tools/list"',
        '"tools/call"',
        "shell=False",
        '"egress": "none"',
        '"mutation": "none"',
    ):
        if token not in source_text:
            raise VerificationError(f"missing protocol anchor: {token}")
    lowered = source_text.lower()
    for forbidden in ("import main", "onyx_live_activation_v9", "http://", "https://"):
        if forbidden in lowered:
            raise VerificationError(f"forbidden live/network anchor: {forbidden}")

    verification = manifest.get("verification")
    if not isinstance(verification, dict) or verification != {
        "focused": "27 passed",
        "cumulative": "59 passed",
        "network_calls": 0,
        "provider_calls": 0,
        "live_activation": False,
        "e6": "not_performed",
        "independent_verifier": SUCCESS,
    }:
        raise VerificationError("verification boundary is invalid")
    return {
        "artifacts": len(artifacts),
        "anchors": len(anchors),
        "artifact_root_sha256": observed_root,
        "protocol_version": manifest["protocol_version"],
        "focused_passed": 27,
        "cumulative_passed": 59,
        "network_calls": 0,
        "live": False,
        "e6": False,
    }


def main() -> int:
    print(SUCCESS, json.dumps(verify(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
