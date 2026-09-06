"""Verify the Founder Command V1 E6 acceptance envelope."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from scripts import verify_phase7_founder_command_v1 as candidate  # noqa: E402


ACCEPTANCE_ID = "VE-P7-FOUNDER-COMMAND-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
ANCHOR = (
    PROJECT
    / "docs/onyx/VE-ACCEPTANCE-P7-FOUNDER-COMMAND-V1-E6-001.sha256"
)
RECORD_SHA256 = (
    "0c239d45377b907e28f741b85202f35ee28eee73c8a3793fe88d63a78ff1f1d7"
)
METADATA_SHA256 = (
    "6fab5120163f523292dd1a164ca15e6ca4112875992a5e7db4553f5327e5fd53"
)
ANCHOR_SHA256 = (
    "3878c9028815ea22031189b627ba56be03eaf516e6d6417dab9e7aec1c635ebb"
)
CANDIDATE_MANIFEST_SHA256 = (
    "b094e18b99342465e06cdc703b3a7db118ffe9fe3e3182171be61be06f63457e"
)
CANDIDATE_ARTIFACT_ROOT = (
    "d636a5192224a48a0ef09038d0cfc4e805b16798c1857d7735b9f27748e0e633"
)
MARKER = "P7_FOUNDER_COMMAND_V1_ACCEPTANCE_OK"


class Phase7FounderCommandV1AcceptanceError(RuntimeError):
    """The acceptance envelope or accepted candidate cannot reproduce."""


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise Phase7FounderCommandV1AcceptanceError(
            f"acceptance artifact unavailable: {path.relative_to(PROJECT)}"
        )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase7FounderCommandV1AcceptanceError(
                    f"duplicate JSON key: {key}"
                )
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise Phase7FounderCommandV1AcceptanceError(
            "non-finite JSON number"
        )

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Phase7FounderCommandV1AcceptanceError(
            "acceptance metadata is unreadable"
        ) from exc
    if type(value) is not dict:
        raise Phase7FounderCommandV1AcceptanceError(
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
        raise Phase7FounderCommandV1AcceptanceError(
            "acceptance envelope hash drift"
        )
    expected_anchor = (
        f"{RECORD_SHA256}  docs/onyx/acceptance/{ACCEPTANCE_ID}.md\n"
        f"{METADATA_SHA256}  "
        f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise Phase7FounderCommandV1AcceptanceError(
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
        "company_graph_entry_roots",
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
        != "docs/onyx/checkpoints/phase7-founder-command-v1/manifest.json"
        or metadata.get("candidate_manifest_sha256")
        != CANDIDATE_MANIFEST_SHA256
        or metadata.get("artifact_root_sha256") != CANDIDATE_ARTIFACT_ROOT
        or metadata.get("artifacts") != 7
        or metadata.get("company_graph_entry_roots") != 4
    ):
        raise Phase7FounderCommandV1AcceptanceError(
            "acceptance identity drift"
        )
    expected_results = {
        "test_files": 8,
        "passed": 168,
        "failed": 0,
        "errors": 0,
        "skipped": 8,
        "explained_platform_skips": 8,
        "subtests_passed": 65,
    }
    expected_claims = {
        "founder_command_v1_accepted": True,
        "daily_founder_brief": True,
        "weekly_operating_review": True,
        "portfolio_view": True,
        "blocker_dependency_report": True,
        "decision_queue": True,
        "revenue_opportunity_queue": True,
        "risk_register": True,
        "what_changed_delta": True,
        "recommended_top_three_actions": True,
        "semantic_freshness_analysis": True,
        "declared_contradiction_preservation": True,
        "structured_status_conflict_detection": True,
        "general_nlp_contradiction_discovery": False,
        "invented_revenue_or_traction": False,
        "persistent_writes": False,
        "live_wiring": False,
        "runtime_authority_added": False,
        "phase7_exit": False,
        "full_onyx_prd_complete": False,
    }
    if (
        metadata.get("results") != expected_results
        or metadata.get("claims") != expected_claims
    ):
        raise Phase7FounderCommandV1AcceptanceError(
            "acceptance result or claim drift"
        )
    record = RECORD.read_text(encoding="utf-8")
    required_record_text = (
        "P0=0",
        "P1=0",
        "P2=0",
        "P3=0",
        "168 passed tests",
        "65 passed subtests",
        "daily Founder Brief",
        "weekly operating-review",
        "General open-text/NLP contradiction discovery is not implemented",
        "Phase 7 is not exited",
        "full Onyx PRD is incomplete",
    )
    if any(value not in record for value in required_record_text):
        raise Phase7FounderCommandV1AcceptanceError(
            "acceptance narrative drift"
        )
    return metadata


def verify(*, run_tests: bool = True) -> dict[str, object]:
    metadata = _verify_envelope()
    reproduced = candidate.verify(run_tests=run_tests)
    if (
        reproduced["artifact_root_sha256"] != CANDIDATE_ARTIFACT_ROOT
        or reproduced["results"]["passed"] != 168  # type: ignore[index]
        or reproduced["results"]["subtests_passed"] != 65  # type: ignore[index]
        or reproduced["results"]["skipped"] != 8  # type: ignore[index]
    ):
        raise Phase7FounderCommandV1AcceptanceError(
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
