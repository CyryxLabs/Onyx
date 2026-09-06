"""Generate lifecycle-identity Release V76 over immutable V75."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v75.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v76.json"
PREDECESSOR_SHA256 = "829cb6957786d699aa84f55caf76aed573912e5cde325d8969d5358447d397c6"
CURRENT_CLOSURE_PATHS = (
    "core/version.py",
    "docs/stories/ONYX-REL-1.1.11-PARITY-LIVE-SUCCESSOR-V1.story.md",
    "main.py",
    "packaging/legal-supplements/LGPL-2.1.txt",
    "packaging/onyx.spec",
    "scripts/build_release.py",
    "scripts/generate_release_workflow_v76.py",
    "scripts/missing_distribution_license_bundle.py",
    "tests/test_installer_lifecycle_release_identity_v1.py",
    "tests/test_missing_distribution_license_bundle_v1.py",
    "tests/test_release_workflow_transition_v76.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V75 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {
            *(entry["path"] for entry in predecessor["current_release_paths"]),
            *CURRENT_CLOSURE_PATHS,
        }
    )
    entries = [{"path": path, "sha256": sha256(ROOT / path)} for path in paths]
    record = {
        "schema": "onyx.release-workflow-transition.v76",
        "issued_at": "2026-09-02T00:35:00-04:00",
        "logical_sequence": 76,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V76\0")
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
        json.dumps(record, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return record


if __name__ == "__main__":
    print(json.dumps(generate(), sort_keys=True))
