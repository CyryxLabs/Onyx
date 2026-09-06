"""Generate the additive Release V52 legal-evidence transition."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v51.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v52.json"
PREDECESSOR_SHA256 = (
    "524594408b9b26297babad1e94f301435234989285137ceaa2b5d6c4241b7984"
)
ISSUED_AT = "2026-08-11T15:08:00-04:00"
LOGICAL_SEQUENCE = 52
ADDITIONAL_PATHS = (
    "THIRD_PARTY_NOTICES.md",
    "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V13.json",
    "scripts/freeze_release_source.py",
    "scripts/generate_release_workflow_v52.py",
    "scripts/missing_distribution_license_bundle.py",
    "scripts/verify_current_successor_retirement_v1.py",
    "tests/test_current_successor_retirement_v13.py",
    "tests/test_freeze_release_source_v52.py",
    "tests/test_missing_distribution_license_bundle_v1.py",
    "tests/test_release_workflow_transition_v52.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V51 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v51"
        or predecessor.get("logical_sequence") != 51
    ):
        raise RuntimeError("Release V51 predecessor contract drifted")
    current_paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *ADDITIONAL_PATHS,
        }
    )
    entries = [
        {"path": relative, "sha256": sha256(ROOT / relative)}
        for relative in current_paths
    ]
    record: dict[str, object] = {
        "schema": "onyx.release-workflow-transition.v52",
        "issued_at": ISSUED_AT,
        "logical_sequence": LOGICAL_SEQUENCE,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256()
    digest.update(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V52\0")
    frame(digest, record["issued_at"])
    frame(digest, str(record["logical_sequence"]))
    frame(digest, record["predecessor"]["path"])
    frame(digest, record["predecessor"]["sha256"])
    for entry in entries:
        frame(digest, entry["path"])
        frame(digest, entry["sha256"])
    record["current_root_sha256"] = digest.hexdigest()
    TARGET.write_text(
        json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return record


if __name__ == "__main__":
    result = generate()
    print(
        json.dumps(
            {
                "fixture_sha256": sha256(TARGET),
                "root_sha256": result["current_root_sha256"],
                "paths": len(result["current_release_paths"]),
            },
            sort_keys=True,
        )
    )
