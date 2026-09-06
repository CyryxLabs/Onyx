"""Verify E6 for the disabled external-agent descriptor V1."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
MARKER = "P6_DISABLED_EXTERNAL_AGENT_DESCRIPTOR_V1_ACCEPTANCE_OK"
ACCEPTANCE_ID = "VE-P6-DISABLED-EXTERNAL-AGENT-DESCRIPTOR-V1-E6-001"
CANDIDATE_MANIFEST = (
    "docs/onyx/checkpoints/phase6-disabled-external-agent-descriptor-v1/manifest.json"
)
CANDIDATE_MANIFEST_SHA256 = (
    "d0d356b808dfbb1996dd31c57cb9f9d95774a9c2d3ad7488d0a9bb81c4177293"
)
CANDIDATE_ROOT_SHA256 = (
    "d48984d1c568eaa1fcecb3ad906049905e62f138143b9d958b7ee7b3048ffab4"
)
RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
METADATA = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
SOURCE_MANIFEST = (
    "docs/onyx/VE-SOURCE-P6-DISABLED-EXTERNAL-AGENT-DESCRIPTOR-V1-E6-001.sha256"
)
ARTIFACT_MANIFEST = (
    "docs/onyx/VE-ARTIFACTS-P6-DISABLED-EXTERNAL-AGENT-DESCRIPTOR-V1-E6-001.sha256"
)
FINAL_MANIFEST = (
    "docs/onyx/VE-ACCEPTANCE-P6-DISABLED-EXTERNAL-AGENT-DESCRIPTOR-V1-E6-001.sha256"
)


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
    rows: dict[str, str] = {}
    for line in _path(relative).read_text(encoding="utf-8").splitlines():
        parts = line.split("  ", 1)
        if (
            len(parts) != 2
            or len(parts[0]) != 64
            or any(char not in "0123456789abcdef" for char in parts[0])
            or parts[1] in rows
        ):
            raise AcceptanceError(f"invalid SHA manifest: {relative}")
        _path(parts[1])
        rows[parts[1]] = parts[0]
    if not rows:
        raise AcceptanceError(f"empty SHA manifest: {relative}")
    return rows


def _run_candidate() -> None:
    completed = subprocess.run(
        [
            str(ROOT / ".venv/Scripts/python.exe"),
            "-B",
            "scripts/verify_phase6_disabled_external_agent_descriptor_v1.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if (
        completed.returncode
        or "P6_DISABLED_EXTERNAL_AGENT_DESCRIPTOR_V1_OK" not in completed.stdout
    ):
        raise AcceptanceError(completed.stdout + completed.stderr)


def verify(*, run_candidate: bool = True) -> dict[str, object]:
    if _digest(CANDIDATE_MANIFEST) != CANDIDATE_MANIFEST_SHA256:
        raise AcceptanceError("candidate manifest drift")
    candidate = json.loads(_path(CANDIDATE_MANIFEST).read_text(encoding="utf-8"))
    if (
        candidate.get("candidate")
        != "phase6-disabled-external-agent-descriptor-candidate-001"
        or candidate.get("artifact_root_sha256") != CANDIDATE_ROOT_SHA256
        or len(candidate.get("artifacts", ())) != 5
        or len(candidate.get("component_acceptance_roots", ())) != 5
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
        "scripts/verify_phase6_disabled_external_agent_descriptor_v1_acceptance.py",
        "tests/test_phase6_disabled_external_agent_descriptor_v1_acceptance.py",
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
        or metadata.get("focused") != {"passed": 40, "failed": 0}
        or metadata.get("cumulative") != {"passed": 74, "failed": 0}
        or metadata.get("live_files_checked") != 205
        or any(metadata.get(key) != 0 for key in (
            "provider_calls",
            "process_calls",
            "network_calls",
            "live_calls",
        ))
        or metadata.get("authority_granted") is not False
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
        "component_roots": 5,
        "focused": 40,
        "cumulative": 74,
        "live_files_checked": 205,
        "findings": findings,
        "provider_calls": 0,
        "process_calls": 0,
        "network_calls": 0,
        "live_calls": 0,
        "authority_granted": False,
        "live_activation": False,
        "phase6_exit": False,
    }


if __name__ == "__main__":
    print(MARKER, json.dumps(verify(), sort_keys=True))
