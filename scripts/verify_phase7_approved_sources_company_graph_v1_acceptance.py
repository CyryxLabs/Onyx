"""Verify the Approved Sources + Company Graph V1 E6 acceptance envelope."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from scripts import (  # noqa: E402
    verify_phase7_approved_sources_company_graph_v1 as candidate,
)


ACCEPTANCE_ID = "VE-P7-APPROVED-SOURCES-COMPANY-GRAPH-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
ANCHOR = (
    PROJECT
    / "docs/onyx/"
    "VE-ACCEPTANCE-P7-APPROVED-SOURCES-COMPANY-GRAPH-V1-E6-001.sha256"
)
RECORD_SHA256 = (
    "b5336b1484c1225b58454dd39cfeb6fad51662fd46b7658bfbb3572389222650"
)
METADATA_SHA256 = (
    "27522c63449d625c97b500ac8ed9048aeddb4cf1d20f77a96bd5431cd21cd14d"
)
ANCHOR_SHA256 = (
    "d5d17c9fdceb76b43405afc8b54129f1e6c9af1e35e67f140cb25aeafb674f85"
)
CANDIDATE_MANIFEST_SHA256 = (
    "fa5fea91caf6914e559cbc22420841b602eeace0153653dc57591fb0070f23f3"
)
CANDIDATE_ARTIFACT_ROOT = (
    "d9efc2186412abbf95a1cd03b901c5f797bcb7c50e6b3a6d256211dd2eeac1c3"
)
MARKER = "P7_APPROVED_SOURCES_COMPANY_GRAPH_V1_ACCEPTANCE_OK"


class Phase7SourcesGraphV1AcceptanceError(RuntimeError):
    """The acceptance envelope or accepted candidate cannot reproduce."""


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise Phase7SourcesGraphV1AcceptanceError(
            f"acceptance artifact unavailable: {path.relative_to(PROJECT)}"
        )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase7SourcesGraphV1AcceptanceError(
                    f"duplicate JSON key: {key}"
                )
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise Phase7SourcesGraphV1AcceptanceError(
            "non-finite JSON number"
        )

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Phase7SourcesGraphV1AcceptanceError(
            "acceptance metadata is unreadable"
        ) from exc
    if type(value) is not dict:
        raise Phase7SourcesGraphV1AcceptanceError(
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
        raise Phase7SourcesGraphV1AcceptanceError(
            "acceptance envelope hash drift"
        )
    expected_anchor = (
        f"{RECORD_SHA256}  docs/onyx/acceptance/{ACCEPTANCE_ID}.md\n"
        f"{METADATA_SHA256}  "
        f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise Phase7SourcesGraphV1AcceptanceError(
            "acceptance anchor content drift"
        )
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
        "workspace_aliases_entry_roots",
        "results",
        "claims",
    }
    if (
        set(metadata) != expected_keys
        or metadata.get("schema") != "onyx.external-acceptance.v1"
        or metadata.get("acceptance_id") != ACCEPTANCE_ID
        or metadata.get("decision") != "accepted"
        or metadata.get("decision_date") != "2026-07-23"
        or metadata.get("findings")
        != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata.get("candidate_manifest_path")
        != (
            "docs/onyx/checkpoints/"
            "phase7-approved-sources-company-graph-v1/manifest.json"
        )
        or metadata.get("candidate_manifest_sha256")
        != CANDIDATE_MANIFEST_SHA256
        or metadata.get("artifact_root_sha256") != CANDIDATE_ARTIFACT_ROOT
        or metadata.get("artifacts") != 9
        or metadata.get("workspace_aliases_entry_roots") != 4
    ):
        raise Phase7SourcesGraphV1AcceptanceError(
            "acceptance identity drift"
        )
    expected_results = {
        "test_files": 7,
        "passed": 154,
        "failed": 0,
        "errors": 0,
        "skipped": 8,
        "explained_platform_skips": 8,
        "subtests_passed": 65,
    }
    expected_claims = {
        "approved_sources_v1_accepted": True,
        "company_graph_v1_accepted": True,
        "source_rights_scoring_freshness": True,
        "all_prd_knowledge_semantics": True,
        "declared_contradiction_supersession_closure": True,
        "artifact_only_completion_denied": True,
        "source_content_instruction_authority": False,
        "url_fetch": False,
        "artifact_content_read": False,
        "graph_persistent_writes": False,
        "automatic_contradiction_discovery": False,
        "founder_brief_implemented": False,
        "live_wiring": False,
        "runtime_authority_added": False,
        "phase7_exit": False,
        "full_onyx_prd_complete": False,
    }
    if (
        metadata.get("results") != expected_results
        or metadata.get("claims") != expected_claims
    ):
        raise Phase7SourcesGraphV1AcceptanceError(
            "acceptance result or claim drift"
        )
    record = RECORD.read_text(encoding="utf-8")
    required_record_text = (
        "P0=0",
        "P1=0",
        "P2=0",
        "P3=0",
        "154 passed tests",
        "65 passed subtests",
        "Approved Sources",
        "Company Graph",
        "artifact",
        "Founder Brief remains unimplemented",
        "Phase 7 is not exited",
        "full Onyx PRD is incomplete",
    )
    if any(value not in record for value in required_record_text):
        raise Phase7SourcesGraphV1AcceptanceError(
            "acceptance narrative drift"
        )
    return metadata


def verify(*, run_tests: bool = True) -> dict[str, object]:
    metadata = _verify_envelope()
    reproduced = candidate.verify(run_tests=run_tests)
    if (
        reproduced["artifact_root_sha256"] != CANDIDATE_ARTIFACT_ROOT
        or reproduced["results"]["passed"] != 154  # type: ignore[index]
        or reproduced["results"]["subtests_passed"] != 65  # type: ignore[index]
        or reproduced["results"]["skipped"] != 8  # type: ignore[index]
    ):
        raise Phase7SourcesGraphV1AcceptanceError(
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
