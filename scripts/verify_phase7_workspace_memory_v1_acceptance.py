"""Independently reproduce E6 acceptance of Workspace Memory V1."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
ID = "VE-P7-WORKSPACE-MEMORY-V1-E6-001"
CANDIDATE = PROJECT / "docs/onyx/checkpoints/phase7-workspace-memory-v1/manifest.json"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P7-WORKSPACE-MEMORY-V1-E6-001.sha256"
VERIFIER = PROJECT / "scripts/verify_phase7_workspace_memory_v1.py"
EXPECTED_CANDIDATE = "59ed88abd6967a73f3050d1215fed0c278b21b5c6e5335814abe8267576c9cd7"
EXPECTED_ROOT = "fafe2c2fb2c0d0f55f0ce6fc6824b71a93c42f3527565449986e90ba1fb09f95"
EXPECTED_RECORD = "3490c0f89ba37c81c67f7e76dc2daedac91622e8386efe668e259d4819848825"
EXPECTED_METADATA = "c6497c644f447a1bc83b63446c25c8be4071dcf103b5dfbf2a5de7b809edf43a"
MARKER = "P7_WORKSPACE_MEMORY_V1_ACCEPTANCE_OK"
MATRIX_MARKER = "## Phase 7 Workspace Memory V1 accepted default-off checkpoint"


class Phase7WorkspaceMemoryV1AcceptanceError(RuntimeError):
    """The Workspace Memory V1 acceptance cannot be reproduced."""


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise Phase7WorkspaceMemoryV1AcceptanceError(
            f"acceptance path unavailable: {path.relative_to(PROJECT)}"
        )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase7WorkspaceMemoryV1AcceptanceError(
                    f"duplicate JSON key: {key}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Phase7WorkspaceMemoryV1AcceptanceError("acceptance JSON invalid") from exc
    if type(value) is not dict:
        raise Phase7WorkspaceMemoryV1AcceptanceError("acceptance JSON object required")
    return value


def _root(records: dict[str, str]) -> str:
    rows = [f"{path}\0{digest}\n" for path, digest in records.items()]
    return hashlib.sha256("".join(sorted(rows)).encode("utf-8")).hexdigest()


def _verify_candidate() -> dict[str, Any]:
    if _digest(CANDIDATE) != EXPECTED_CANDIDATE:
        raise Phase7WorkspaceMemoryV1AcceptanceError("candidate manifest drift")
    candidate = _strict_json(CANDIDATE)
    if (
        candidate.get("candidate") != "phase7-workspace-memory-v1"
        or candidate.get("status") != "candidate_e1_e5_e6_pending"
        or candidate.get("artifact_root_sha256") != EXPECTED_ROOT
        or candidate.get("claims", {}).get("external_e6_accepted") is not False
        or candidate.get("claims", {}).get("phase7_exit") is not False
    ):
        raise Phase7WorkspaceMemoryV1AcceptanceError("candidate contract drift")
    artifacts = candidate.get("artifacts")
    if type(artifacts) is not list or len(artifacts) != 7:
        raise Phase7WorkspaceMemoryV1AcceptanceError("candidate artifacts drift")
    observed: dict[str, str] = {}
    for item in artifacts:
        if (
            type(item) is not dict
            or set(item) != {"path", "bytes", "sha256"}
            or type(item["path"]) is not str
            or type(item["bytes"]) is not int
            or type(item["sha256"]) is not str
        ):
            raise Phase7WorkspaceMemoryV1AcceptanceError(
                "candidate artifact record drift"
            )
        path = PROJECT / item["path"]
        if path.stat().st_size != item["bytes"] or _digest(path) != item["sha256"]:
            raise Phase7WorkspaceMemoryV1AcceptanceError(
                f"candidate artifact hash drift: {item['path']}"
            )
        observed[item["path"]] = item["sha256"]
    if _root(observed) != EXPECTED_ROOT:
        raise Phase7WorkspaceMemoryV1AcceptanceError("artifact root recompute drift")
    return candidate


def _verify_envelope() -> dict[str, Any]:
    if _digest(RECORD) != EXPECTED_RECORD or _digest(METADATA) != EXPECTED_METADATA:
        raise Phase7WorkspaceMemoryV1AcceptanceError("acceptance envelope drift")
    metadata = _strict_json(METADATA)
    expected_claims = {
        "workspace_memory_v1_accepted": True,
        "pre_ranking_hard_filters": True,
        "read_only": True,
        "live_wiring": False,
        "runtime_authority_added": False,
        "phase7_exit": False,
        "company_graph_implemented": False,
        "founder_brief_implemented": False,
        "full_onyx_prd_complete": False,
    }
    if (
        metadata.get("schema") != "onyx.external-acceptance.v1"
        or metadata.get("acceptance_id") != ID
        or metadata.get("decision") != "accepted"
        or metadata.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata.get("candidate_manifest_sha256") != EXPECTED_CANDIDATE
        or metadata.get("artifact_root_sha256") != EXPECTED_ROOT
        or metadata.get("artifacts") != 7
        or metadata.get("phase6_entry_roots") != 4
        or metadata.get("results")
        != {
            "test_files": 5,
            "passed": 77,
            "failed": 0,
            "errors": 0,
            "skipped": 1,
            "explained_platform_skips": 1,
            "subtests_passed": 73,
        }
        or metadata.get("claims") != expected_claims
    ):
        raise Phase7WorkspaceMemoryV1AcceptanceError(
            "acceptance metadata contract drift"
        )
    anchors: dict[str, str] = {}
    for line in ANCHOR.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        anchors[relative] = digest
    if anchors != {
        f"docs/onyx/acceptance/{ID}.md": EXPECTED_RECORD,
        f"docs/onyx/acceptance/{ID}.manifest.json": EXPECTED_METADATA,
    }:
        raise Phase7WorkspaceMemoryV1AcceptanceError("acceptance anchor drift")
    matrix = (PROJECT / "docs/onyx/CAPABILITY_MATRIX.md").read_text(encoding="utf-8")
    if MATRIX_MARKER not in matrix or ID not in matrix.split(MATRIX_MARKER, 1)[1]:
        raise Phase7WorkspaceMemoryV1AcceptanceError("accepted matrix delta absent")
    return metadata


def _run_candidate() -> dict[str, Any]:
    process = subprocess.run(
        [sys.executable, str(VERIFIER), "--run-tests"],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    prefix = "P7_WORKSPACE_MEMORY_V1_OK "
    if process.returncode != 0 or not process.stdout.startswith(prefix):
        raise Phase7WorkspaceMemoryV1AcceptanceError("candidate verifier failed")
    try:
        payload = json.loads(process.stdout[len(prefix) :])
    except json.JSONDecodeError as exc:
        raise Phase7WorkspaceMemoryV1AcceptanceError(
            "candidate verifier output invalid"
        ) from exc
    if (
        payload.get("artifact_root_sha256") != EXPECTED_ROOT
        or payload.get("tests_executed") is not True
        or payload.get("selection")
        != {
            "errors": 0,
            "failed": 0,
            "passed": 77,
            "skipped": 1,
            "subtests_passed": 73,
            "test_files": 5,
        }
        or payload.get("external_e6_accepted") is not False
        or payload.get("phase7_exit") is not False
        or payload.get("live_wiring") is not False
        or payload.get("persistent_writes") != 0
    ):
        raise Phase7WorkspaceMemoryV1AcceptanceError(
            "candidate verifier contract drift"
        )
    return payload


def verify() -> dict[str, Any]:
    _verify_candidate()
    metadata = _verify_envelope()
    _run_candidate()
    return metadata


def main() -> int:
    result = verify()
    print(f"{MARKER} {json.dumps(result, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
