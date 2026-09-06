"""Verify E6 acceptance for Unified Command Router V1 candidate 002."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
MARKER = "P6_UNIFIED_COMMAND_ROUTER_V1_C002_ACCEPTANCE_OK"
ACCEPTANCE_ID = "VE-P6-UNIFIED-ROUTER-V1-C002-E6-001"
CANDIDATE_MANIFEST = (
    "docs/onyx/checkpoints/phase6-unified-command-router-v1/manifest.json"
)
CANDIDATE_MANIFEST_SHA256 = (
    "e78d887f87922290e19e1427fa030e276152b14acb5a72be1c5b53cb645d7abe"
)
CANDIDATE_ROOT_SHA256 = (
    "3b01eac328b6fd64ad602079adf216d54aa3d56e6997ccff37f3f7db40dabc21"
)
RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
METADATA = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
SOURCE_MANIFEST = "docs/onyx/VE-SOURCE-P6-UNIFIED-ROUTER-V1-C002-E6-001.sha256"
ARTIFACT_MANIFEST = (
    "docs/onyx/VE-ARTIFACTS-P6-UNIFIED-ROUTER-V1-C002-E6-001.sha256"
)
FINAL_MANIFEST = "docs/onyx/VE-ACCEPTANCE-P6-UNIFIED-ROUTER-V1-C002-E6-001.sha256"


class AcceptanceError(RuntimeError):
    pass


def _path(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or pure.is_absolute()
        or str(pure) != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise AcceptanceError("noncanonical path")
    path = ROOT.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise AcceptanceError(f"non-regular path: {relative}")
    path.resolve(strict=True).relative_to(ROOT.resolve(strict=True))
    return path


def _digest(relative: str) -> str:
    return hashlib.sha256(_path(relative).read_bytes()).hexdigest()


def _rows(relative: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in _path(relative).read_text(encoding="utf-8").splitlines():
        parts = line.split("  ", 1)
        if len(parts) != 2 or len(parts[0]) != 64 or parts[1] in result:
            raise AcceptanceError(f"invalid SHA manifest: {relative}")
        if any(char not in "0123456789abcdef" for char in parts[0]):
            raise AcceptanceError(f"invalid digest: {relative}")
        _path(parts[1])
        result[parts[1]] = parts[0]
    if not result:
        raise AcceptanceError(f"empty SHA manifest: {relative}")
    return result


def _run_candidate() -> None:
    completed = subprocess.run(
        [
            str(ROOT / ".venv/Scripts/python.exe"),
            "-B",
            "scripts/verify_phase6_unified_command_router_v1.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    if completed.returncode or "P6_UNIFIED_COMMAND_ROUTER_V1_OK" not in completed.stdout:
        raise AcceptanceError(completed.stdout + completed.stderr)


def verify(*, run_candidate: bool = True) -> dict[str, object]:
    if _digest(CANDIDATE_MANIFEST) != CANDIDATE_MANIFEST_SHA256:
        raise AcceptanceError("candidate manifest drift")
    candidate = json.loads(_path(CANDIDATE_MANIFEST).read_text(encoding="utf-8"))
    if (
        candidate.get("candidate")
        != "phase6-unified-command-router-candidate-002"
        or candidate.get("artifact_root_sha256") != CANDIDATE_ROOT_SHA256
        or candidate.get("status") != "candidate-ready-external-gate"
        or len(candidate.get("artifacts", ())) != 5
        or len(candidate.get("component_acceptance_roots", ())) != 14
    ):
        raise AcceptanceError("candidate identity drift")
    for item in (
        *candidate["artifacts"],
        *candidate["component_acceptance_roots"],
    ):
        if _digest(item["path"]) != item["sha256"]:
            raise AcceptanceError(f"bound artifact drift: {item['path']}")

    sources = _rows(SOURCE_MANIFEST)
    expected_sources = {
        "scripts/verify_phase6_unified_command_router_v1_c002_acceptance.py",
        "tests/test_phase6_unified_command_router_v1_c002_acceptance.py",
    }
    if set(sources) != expected_sources or any(
        _digest(path) != digest for path, digest in sources.items()
    ):
        raise AcceptanceError("acceptance source drift")
    artifacts = _rows(ARTIFACT_MANIFEST)
    if set(artifacts) != {RECORD, METADATA} or any(
        _digest(path) != digest for path, digest in artifacts.items()
    ):
        raise AcceptanceError("acceptance artifact drift")
    if _rows(FINAL_MANIFEST) != {RECORD: artifacts[RECORD]}:
        raise AcceptanceError("final decision drift")

    metadata = json.loads(_path(METADATA).read_text(encoding="utf-8"))
    findings = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    if (
        metadata.get("acceptance_id") != ACCEPTANCE_ID
        or metadata.get("decision") != "accepted"
        or metadata.get("findings") != findings
        or metadata.get("candidate_manifest_sha256") != CANDIDATE_MANIFEST_SHA256
        or metadata.get("artifact_root_sha256") != CANDIDATE_ROOT_SHA256
        or metadata.get("focused") != {"passed": 27, "failed": 0}
        or metadata.get("cumulative") != {"passed": 154, "failed": 0}
        or any(metadata.get(key) != 0 for key in (
            "network_calls",
            "process_calls",
            "provider_calls",
            "live_calls",
        ))
        or metadata.get("live_activation") is not False
        or metadata.get("phase6_exit") is not False
    ):
        raise AcceptanceError("acceptance metadata drift")
    if run_candidate:
        _run_candidate()
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "decision": "accepted",
        "candidate_manifest_sha256": CANDIDATE_MANIFEST_SHA256,
        "artifact_root_sha256": CANDIDATE_ROOT_SHA256,
        "artifacts": 5,
        "component_roots": 14,
        "focused": 27,
        "cumulative": 154,
        "findings": findings,
        "network_calls": 0,
        "process_calls": 0,
        "provider_calls": 0,
        "live_calls": 0,
        "default_off": True,
        "live_activation": False,
        "phase6_exit": False,
    }


if __name__ == "__main__":
    print(MARKER, json.dumps(verify(), sort_keys=True))
