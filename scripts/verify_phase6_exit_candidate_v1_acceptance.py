"""Independently reproduce E6 acceptance of Phase 6 Exit Candidate V1."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
ID = "VE-P6-EXIT-CANDIDATE-V1-E6-001"
CANDIDATE_MANIFEST = (
    PROJECT / "docs/onyx/checkpoints/phase6-exit-candidate-v1/manifest.json"
)
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P6-EXIT-CANDIDATE-V1-E6-001.sha256"
CANDIDATE_VERIFIER = PROJECT / "scripts/verify_phase6_exit_candidate_v1.py"
EXPECTED_CANDIDATE_MANIFEST = (
    "6c32277bcbf17130eb60103538de6b58966a43dcd6b30a12c2aaf1e2e4b6493d"
)
EXPECTED_ARTIFACT_ROOT = (
    "ab8d1465c375a6ff183d844b89cae247ce5cf846e35de15b142683fe9be1390f"
)
EXPECTED_COMPONENT_ROOT = (
    "98de22eb674d6a6a4465ca32ff8bb4bd1ab77ae76a80264d50742beab63e3ff3"
)
EXPECTED_RECORD = "6e3fa587a55be54dc9da3db03e56d01fa0ad8197284b9c1f012e2d4c80e75d21"
EXPECTED_METADATA = "148505d6f49cf297aa6cc55b5eee0a2ac2bde5a2d9ac81051d865de470c4501d"
MATRIX_MARKER = "## Phase 6 E6 accepted default-off implementation exit"
MARKER = "P6_EXIT_CANDIDATE_V1_ACCEPTANCE_OK"


class Phase6ExitCandidateV1AcceptanceError(RuntimeError):
    """The aggregate Phase 6 E6 decision cannot be reproduced."""


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise Phase6ExitCandidateV1AcceptanceError(
            f"acceptance path unavailable: {path.relative_to(PROJECT)}"
        )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase6ExitCandidateV1AcceptanceError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Phase6ExitCandidateV1AcceptanceError("acceptance JSON invalid") from exc
    if type(value) is not dict:
        raise Phase6ExitCandidateV1AcceptanceError("acceptance JSON object required")
    return value


def _root(records: dict[str, str]) -> str:
    rows = [f"{path}\0{digest}\n" for path, digest in records.items()]
    return hashlib.sha256("".join(sorted(rows)).encode("utf-8")).hexdigest()


def _verify_candidate_bytes() -> dict[str, Any]:
    if _digest(CANDIDATE_MANIFEST) != EXPECTED_CANDIDATE_MANIFEST:
        raise Phase6ExitCandidateV1AcceptanceError("candidate manifest drift")
    candidate = _strict_json(CANDIDATE_MANIFEST)
    if (
        candidate.get("candidate") != "phase6-exit-candidate-v1"
        or candidate.get("status") != "candidate_e1_e5_e6_pending"
        or candidate.get("artifact_root_sha256") != EXPECTED_ARTIFACT_ROOT
        or candidate.get("component_acceptance_root", {}).get("sha256")
        != EXPECTED_COMPONENT_ROOT
    ):
        raise Phase6ExitCandidateV1AcceptanceError("candidate contract drift")
    artifacts = candidate.get("artifacts")
    if type(artifacts) is not list or len(artifacts) != 7:
        raise Phase6ExitCandidateV1AcceptanceError("candidate artifact drift")
    observed: dict[str, str] = {}
    for item in artifacts:
        if (
            type(item) is not dict
            or set(item) != {"path", "bytes", "sha256"}
            or type(item["path"]) is not str
            or type(item["bytes"]) is not int
            or type(item["sha256"]) is not str
        ):
            raise Phase6ExitCandidateV1AcceptanceError(
                "candidate artifact record drift"
            )
        path = PROJECT / item["path"]
        if path.stat().st_size != item["bytes"] or _digest(path) != item["sha256"]:
            raise Phase6ExitCandidateV1AcceptanceError(
                f"candidate artifact hash drift: {item['path']}"
            )
        observed[item["path"]] = item["sha256"]
    if _root(observed) != EXPECTED_ARTIFACT_ROOT:
        raise Phase6ExitCandidateV1AcceptanceError("artifact root recompute drift")
    return candidate


def _verify_acceptance_envelope() -> dict[str, Any]:
    if _digest(RECORD) != EXPECTED_RECORD or _digest(METADATA) != EXPECTED_METADATA:
        raise Phase6ExitCandidateV1AcceptanceError("acceptance envelope drift")
    metadata = _strict_json(METADATA)
    expected_claims = {
        "phase6_exit_complete": True,
        "phase7_default_off_implementation_unlocked": True,
        "live_activation_changed": False,
        "runtime_authority_added": False,
        "remote_cross_route_authorized": False,
        "additional_provider_authorized": False,
        "external_agent_authority": False,
        "permanent_provider_availability": False,
        "local_mcp_process_observed": False,
        "full_onyx_prd_complete": False,
    }
    if (
        metadata.get("schema") != "onyx.external-acceptance.v1"
        or metadata.get("acceptance_id") != ID
        or metadata.get("decision") != "accepted"
        or metadata.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata.get("candidate_manifest_sha256") != EXPECTED_CANDIDATE_MANIFEST
        or metadata.get("candidate_artifact_root_sha256") != EXPECTED_ARTIFACT_ROOT
        or metadata.get("component_evidence_root_sha256") != EXPECTED_COMPONENT_ROOT
        or metadata.get("candidate_artifacts") != 7
        or metadata.get("component_evidence_roots") != 34
        or metadata.get("component_acceptances") != 8
        or metadata.get("results")
        != {
            "test_files": 14,
            "passed": 294,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
        }
        or metadata.get("claims") != expected_claims
    ):
        raise Phase6ExitCandidateV1AcceptanceError("acceptance metadata contract drift")
    anchors: dict[str, str] = {}
    for line in ANCHOR.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        anchors[relative] = digest
    if anchors != {
        f"docs/onyx/acceptance/{ID}.md": EXPECTED_RECORD,
        f"docs/onyx/acceptance/{ID}.manifest.json": EXPECTED_METADATA,
    }:
        raise Phase6ExitCandidateV1AcceptanceError("acceptance anchor drift")
    matrix = (PROJECT / "docs/onyx/CAPABILITY_MATRIX.md").read_text(encoding="utf-8")
    if (
        MATRIX_MARKER not in matrix
        or ID not in matrix.split(MATRIX_MARKER, 1)[1]
        or "Phase 7 default-off implementation may begin" not in matrix
    ):
        raise Phase6ExitCandidateV1AcceptanceError("accepted matrix delta absent")
    return metadata


def _run_candidate_verifier() -> dict[str, Any]:
    process = subprocess.run(
        [sys.executable, str(CANDIDATE_VERIFIER), "--run-tests"],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    prefix = "P6_EXIT_CANDIDATE_V1_OK "
    if process.returncode != 0 or not process.stdout.startswith(prefix):
        raise Phase6ExitCandidateV1AcceptanceError("candidate verifier failed")
    try:
        payload = json.loads(process.stdout[len(prefix) :])
    except json.JSONDecodeError as exc:
        raise Phase6ExitCandidateV1AcceptanceError(
            "candidate verifier output invalid"
        ) from exc
    if (
        payload.get("artifact_root_sha256") != EXPECTED_ARTIFACT_ROOT
        or payload.get("component_acceptance_root_sha256") != EXPECTED_COMPONENT_ROOT
        or payload.get("tests_executed") is not True
        or payload.get("selection")
        != {
            "errors": 0,
            "failed": 0,
            "passed": 294,
            "skipped": 0,
            "test_files": 14,
        }
        or payload.get("external_e6_accepted") is not False
        or payload.get("phase6_exit") is not False
        or payload.get("phase7_unlocked") is not False
        or payload.get("runtime_authority_added") is not False
    ):
        raise Phase6ExitCandidateV1AcceptanceError("candidate verifier contract drift")
    return payload


def verify() -> dict[str, Any]:
    _verify_candidate_bytes()
    metadata = _verify_acceptance_envelope()
    _run_candidate_verifier()
    return metadata


def main() -> int:
    result = verify()
    print(f"{MARKER} {json.dumps(result, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
