"""Verify the Layered Memory V1 E6 acceptance envelope."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from scripts import verify_phase7_layered_memory_v1 as candidate  # noqa: E402

ACCEPTANCE_ID = "VE-P7-LAYERED-MEMORY-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P7-LAYERED-MEMORY-V1-E6-001.sha256"
RECORD_SHA256 = "594af1ea18644aa3f2ab951ecf2204bde01649399cb8a2c8ca793308b87def5a"
METADATA_SHA256 = "5fb4ea8b702967a4d9861215783f54b79ab156637870c195d32ee7bb4ccae0d6"
ANCHOR_SHA256 = "b4c14e068728d685f22b9049d0f2776188072451eb1dde850081238f41dd3fd7"
CANDIDATE_MANIFEST_SHA256 = (
    "2818c6ffe66681436286d89f557c57cd23c35c29ee7f29d53d7eb2bf9d8ec95d"
)
CANDIDATE_ARTIFACT_ROOT = (
    "96218afa17936918aaed3bc4f225db3fee0eb117fa4e94f9439d93d1f6ed1020"
)
MARKER = "P7_LAYERED_MEMORY_V1_ACCEPTANCE_OK"


class Phase7LayeredMemoryV1AcceptanceError(RuntimeError):
    """The acceptance envelope or accepted candidate cannot reproduce."""


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise Phase7LayeredMemoryV1AcceptanceError(
            f"acceptance artifact unavailable: {path.relative_to(PROJECT)}"
        )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase7LayeredMemoryV1AcceptanceError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise Phase7LayeredMemoryV1AcceptanceError("non-finite JSON number")

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Phase7LayeredMemoryV1AcceptanceError(
            "acceptance metadata is unreadable"
        ) from exc
    if type(value) is not dict:
        raise Phase7LayeredMemoryV1AcceptanceError(
            "acceptance metadata must be an object"
        )
    return value


def _verify_envelope() -> dict[str, Any]:
    if (
        _digest(RECORD) != RECORD_SHA256
        or _digest(METADATA) != METADATA_SHA256
        or _digest(ANCHOR) != ANCHOR_SHA256
        or _digest(candidate.MANIFEST) != CANDIDATE_MANIFEST_SHA256
    ):
        raise Phase7LayeredMemoryV1AcceptanceError("acceptance envelope hash drift")
    expected_anchor = (
        f"{RECORD_SHA256}  docs/onyx/acceptance/{ACCEPTANCE_ID}.md\n"
        f"{METADATA_SHA256}  "
        f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise Phase7LayeredMemoryV1AcceptanceError("acceptance anchor content drift")
    metadata = _strict_json(METADATA)
    expected_keys = {
        "schema",
        "acceptance_id",
        "decision",
        "decision_date",
        "findings",
        "candidate_manifest_path",
        "candidate_manifest_sha256",
        "artifact_root_sha256",
        "artifacts",
        "workspace_memory_entry_roots",
        "results",
        "claims",
    }
    if (
        set(metadata) != expected_keys
        or metadata.get("schema") != "onyx.external-acceptance.v1"
        or metadata.get("acceptance_id") != ACCEPTANCE_ID
        or metadata.get("decision") != "accepted"
        or metadata.get("decision_date") != "2026-07-23"
        or metadata.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata.get("candidate_manifest_path")
        != "docs/onyx/checkpoints/phase7-layered-memory-v1/manifest.json"
        or metadata.get("candidate_manifest_sha256") != CANDIDATE_MANIFEST_SHA256
        or metadata.get("artifact_root_sha256") != CANDIDATE_ARTIFACT_ROOT
        or metadata.get("artifacts") != 7
        or metadata.get("workspace_memory_entry_roots") != 4
    ):
        raise Phase7LayeredMemoryV1AcceptanceError("acceptance identity drift")
    expected_results = {
        "test_files": 9,
        "passed": 161,
        "failed": 0,
        "errors": 0,
        "skipped": 1,
        "explained_platform_skips": 1,
        "subtests_passed": 77,
    }
    expected_claims = {
        "layered_memory_v1_accepted": True,
        "seven_typed_layers": True,
        "workspace_principal_isolation": True,
        "pre_ranking_hard_filters": True,
        "hmac_integrity": True,
        "normalized_deduplication": True,
        "explicit_entity_resolution": True,
        "correction_supersession_contradiction": True,
        "freshness_validity": True,
        "retention_export_delete": True,
        "source_deletion": True,
        "poisoning_defenses": True,
        "instruction_authority": False,
        "global_vector_index": False,
        "general_nlp_entity_extraction": False,
        "accepted_workspace_memory_modified": False,
        "live_wiring": False,
        "runtime_authority_added": False,
        "phase7_exit": False,
        "full_onyx_prd_complete": False,
    }
    if (
        metadata.get("results") != expected_results
        or metadata.get("claims") != expected_claims
    ):
        raise Phase7LayeredMemoryV1AcceptanceError("acceptance result or claim drift")
    record = RECORD.read_text(encoding="utf-8")
    required_record_text = (
        "P0=0",
        "P1=0",
        "P2=0",
        "P3=0",
        "161 passed tests",
        "77 passed subtests",
        "session-working",
        "temporal-status",
        "General NLP entity extraction is not implemented",
        "Phase 7 is not exited",
        "full Onyx PRD is incomplete",
    )
    if any(value not in record for value in required_record_text):
        raise Phase7LayeredMemoryV1AcceptanceError("acceptance narrative drift")
    return metadata


def verify(*, run_tests: bool = True) -> dict[str, object]:
    metadata = _verify_envelope()
    reproduced = candidate.verify(run_tests=run_tests)
    if (
        reproduced["artifact_root_sha256"] != CANDIDATE_ARTIFACT_ROOT
        or reproduced["results"]["passed"] != 161  # type: ignore[index]
        or reproduced["results"]["subtests_passed"] != 77  # type: ignore[index]
        or reproduced["results"]["skipped"] != 1  # type: ignore[index]
    ):
        raise Phase7LayeredMemoryV1AcceptanceError(
            "accepted candidate reproduction drift"
        )
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "decision": metadata["decision"],
        "findings": metadata["findings"],
        "claims": metadata["claims"],
        "candidate_artifact_root_sha256": CANDIDATE_ARTIFACT_ROOT,
        "record_sha256": RECORD_SHA256,
        "metadata_sha256": METADATA_SHA256,
        "anchor_sha256": ANCHOR_SHA256,
        "marker": MARKER,
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, sort_keys=True))
    print(MARKER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
