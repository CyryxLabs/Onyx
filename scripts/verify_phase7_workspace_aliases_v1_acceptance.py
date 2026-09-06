"""Independently verify the Workspace Aliases V1 E6 acceptance envelope."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from scripts import verify_phase7_workspace_aliases_v1 as candidate  # noqa: E402


ACCEPTANCE_ID = "VE-P7-WORKSPACE-ALIASES-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P7-WORKSPACE-ALIASES-V1-E6-001.sha256"
RECORD_SHA256 = "27b61a9ef3351728f0811af6d86a83d4a8dfa80e00640b0ac847bce9917e22cf"
METADATA_SHA256 = "98ca596125e43dec17424d06d6716528e319cd129cc5a7737372626c89a5343c"
ANCHOR_SHA256 = "5f80d972ac6d8c4eef521a7015a027cbe81d61833d4c27b4868bf7c659b01d41"
CANDIDATE_MANIFEST_SHA256 = (
    "ec1938f4b1671187ed8384f104bb6082b0bd75d157cf4c8f12e259beb5612ca4"
)
CANDIDATE_ARTIFACT_ROOT = (
    "1ae29f0e8300b19737f61e795ea867f474d5dc7efd803a5a6bbaef4e74f2362e"
)
MARKER = "P7_WORKSPACE_ALIASES_V1_ACCEPTANCE_OK"


class Phase7WorkspaceAliasesV1AcceptanceError(RuntimeError):
    """The acceptance envelope or accepted candidate cannot reproduce."""


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise Phase7WorkspaceAliasesV1AcceptanceError(
            f"acceptance artifact unavailable: {path.relative_to(PROJECT)}"
        )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase7WorkspaceAliasesV1AcceptanceError(
                    f"duplicate JSON key: {key}"
                )
            result[key] = value
        return result

    def reject_constant(_value: str) -> object:
        raise Phase7WorkspaceAliasesV1AcceptanceError(
            "non-finite JSON number"
        )

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Phase7WorkspaceAliasesV1AcceptanceError(
            "acceptance metadata is unreadable"
        ) from exc
    if type(value) is not dict:
        raise Phase7WorkspaceAliasesV1AcceptanceError(
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
        raise Phase7WorkspaceAliasesV1AcceptanceError(
            "acceptance envelope hash drift"
        )
    expected_anchor = (
        f"{RECORD_SHA256}  docs/onyx/acceptance/{ACCEPTANCE_ID}.md\n"
        f"{METADATA_SHA256}  "
        f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json\n"
    )
    if ANCHOR.read_text(encoding="utf-8") != expected_anchor:
        raise Phase7WorkspaceAliasesV1AcceptanceError(
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
        or metadata.get("findings")
        != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata.get("candidate_manifest_path")
        != "docs/onyx/checkpoints/phase7-workspace-aliases-v1/manifest.json"
        or metadata.get("candidate_manifest_sha256")
        != CANDIDATE_MANIFEST_SHA256
        or metadata.get("artifact_root_sha256") != CANDIDATE_ARTIFACT_ROOT
        or metadata.get("artifacts") != 7
        or metadata.get("workspace_memory_entry_roots") != 4
    ):
        raise Phase7WorkspaceAliasesV1AcceptanceError(
            "acceptance identity drift"
        )
    expected_results = {
        "test_files": 7,
        "passed": 160,
        "failed": 0,
        "errors": 0,
        "skipped": 9,
        "explained_platform_skips": 9,
        "subtests_passed": 113,
    }
    expected_claims = {
        "workspace_aliases_v1_accepted": True,
        "credential_aliases": True,
        "profile_aliases": True,
        "artifact_aliases": True,
        "secret_storage": False,
        "secret_resolution": False,
        "browser_launch": False,
        "artifact_content_read": False,
        "live_wiring": False,
        "runtime_authority_added": False,
        "approved_source_registry_implemented": False,
        "company_graph_implemented": False,
        "founder_brief_implemented": False,
        "phase7_exit": False,
        "full_onyx_prd_complete": False,
    }
    if (
        metadata.get("results") != expected_results
        or metadata.get("claims") != expected_claims
    ):
        raise Phase7WorkspaceAliasesV1AcceptanceError(
            "acceptance result or claim drift"
        )
    record = RECORD.read_text(encoding="utf-8")
    required_record_text = (
        "P0=0",
        "P1=0",
        "P2=0",
        "P3=0",
        "160 passed tests",
        "113 passed subtests",
        "Approved-source registry",
        "Phase 7 is not exited",
        "full Onyx PRD is incomplete",
    )
    if any(value not in record for value in required_record_text):
        raise Phase7WorkspaceAliasesV1AcceptanceError(
            "acceptance narrative drift"
        )
    return metadata


def verify(*, run_tests: bool = True) -> dict[str, object]:
    metadata = _verify_envelope()
    reproduced = candidate.verify(run_tests=run_tests)
    if (
        reproduced["artifact_root_sha256"] != CANDIDATE_ARTIFACT_ROOT
        or reproduced["results"]["passed"] != 160  # type: ignore[index]
        or reproduced["results"]["subtests_passed"] != 113  # type: ignore[index]
    ):
        raise Phase7WorkspaceAliasesV1AcceptanceError(
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
