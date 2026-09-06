"""Generate the additive Release V54 packaging-closure successor."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v53.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v54.json"
PREDECESSOR_SHA256 = "2d1531743bd7f1a30f680c447d819a1724771c70c98f4006cf940cc8433cac52"
ISSUED_AT = "2026-08-23T16:30:00-04:00"
LOGICAL_SEQUENCE = 54
ADDITIONAL_PATHS = (
    "core/capability_ports/__init__.py",
    "packaging/onyx.spec",
    "scripts/bootstrap_onyx.pyw",
    "scripts/build_release.py",
    "scripts/generate_release_workflow_v54.py",
    "scripts/onyx_capabilities_cli.py",
    "scripts/package_hygiene.py",
    "scripts/verify_release_runtime_closure_v2.py",
    "tests/test_release_runtime_closure_v2.py",
    "tests/test_release_workflow_transition_v54.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def generate() -> dict[str, object]:
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V53 predecessor digest drifted")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if predecessor.get("schema") != "onyx.release-workflow-transition.v53":
        raise RuntimeError("Release V53 predecessor contract drifted")
    current_paths = sorted(
        {*(entry["path"] for entry in predecessor["current_release_paths"]), *ADDITIONAL_PATHS}
    )
    entries = [{"path": relative, "sha256": sha256(ROOT / relative)} for relative in current_paths]
    record: dict[str, object] = {
        "schema": "onyx.release-workflow-transition.v54",
        "issued_at": ISSUED_AT,
        "logical_sequence": LOGICAL_SEQUENCE,
        "predecessor": {"path": PREDECESSOR.relative_to(ROOT).as_posix(), "sha256": PREDECESSOR_SHA256},
        "policy": predecessor["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    digest = hashlib.sha256()
    digest.update(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V54\0")
    frame(digest, record["issued_at"])
    frame(digest, str(record["logical_sequence"]))
    frame(digest, record["predecessor"]["path"])
    frame(digest, record["predecessor"]["sha256"])
    for entry in entries:
        frame(digest, entry["path"])
        frame(digest, entry["sha256"])
    record["current_root_sha256"] = digest.hexdigest()
    TARGET.write_text(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    return record


if __name__ == "__main__":
    result = generate()
    print(json.dumps({"fixture_sha256": sha256(TARGET), "root_sha256": result["current_root_sha256"], "paths": len(result["current_release_paths"])}, sort_keys=True))
