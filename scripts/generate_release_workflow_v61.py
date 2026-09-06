"""Generate additive Release V61 for the living liquid-metal HUD closure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v60.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v61.json"
PREDECESSOR_SHA256 = "79521716c4c0cc7e835068d3441261123699096e20aaa66c448f21c8917ca49c"
CURRENT_CLOSURE_PATHS = (
    "core/onyx_hud_current_acceptance_v36.py",
    "core/onyx_hud_orb_v13.py",
    "core/onyx_packaged_runtime_hud_contract_v5.py",
    "core/onyx_packaged_runtime_hud_contract_v5.manifest.json",
    "docs/onyx/acceptance/VE-HUD-CURRENT-V36-E6-001.manifest.json",
    "packaging/onyx.spec",
    "qml/OnyxLiveShellGuardedV2.qml",
    "qml/OnyxLiveShellV12.qml",
    "qml/components/OnyxOrbEntityV9.qml",
    "scripts/build_release.py",
    "scripts/generate_release_workflow_v61.py",
    "scripts/package_hygiene.py",
    "tests/test_onyx_hud_current_acceptance_v36.py",
    "tests/test_onyx_hud_orb_v13.py",
    "tests/test_onyx_orb_liquid_metal_v9.py",
    "tests/test_packaged_runtime_hud_contract_v5.py",
    "tests/test_release_workflow_transition_v61.py",
    "ui.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V60 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *CURRENT_CLOSURE_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v61",
        "issued_at": "2026-08-24T01:00:00-04:00",
        "logical_sequence": 61,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V61\0")
    for value in (
        record["issued_at"],
        str(record["logical_sequence"]),
        record["predecessor"]["path"],
        record["predecessor"]["sha256"],
    ):
        frame(digest, value)
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
    print(json.dumps(generate(), sort_keys=True))
