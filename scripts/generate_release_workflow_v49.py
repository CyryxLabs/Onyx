"""Generate the acyclic Release V49 transition over immutable V48."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v48.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v49.json"
PREDECESSOR_SHA256 = (
    "32ff477f4cfe144c024309b119b3f4e630a703bcee9473071e847d2d257b60db"
)
ISSUED_AT = "2026-08-11T09:45:00-04:00"
LOGICAL_SEQUENCE = 49
ADDITIONAL_PATHS = (
    "core/onyx_hud_current_acceptance_v31.py",
    "core/onyx_hud_orb_v12.py",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V31-E6-001.manifest.json",
    "scripts/generate_hud_v31_manifests.py",
    "scripts/generate_phase5_current_successor_transition_v49.py",
    "scripts/generate_release_workflow_v49.py",
    "tests/fixtures/phase5_current_successor_transition_v49.json",
    "tests/test_onyx_hud_current_acceptance_v31.py",
    "tests/test_onyx_hud_orb_v12.py",
    "tests/test_phase5_current_successor_transition_v49.py",
    "tests/test_release_workflow_transition_v49.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V48 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if predecessor.get("schema") != "onyx.release-workflow-transition.v48":
        raise RuntimeError("Release V48 predecessor contract drifted")
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
        "schema": "onyx.release-workflow-transition.v49",
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
    digest.update(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V49\0")
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
