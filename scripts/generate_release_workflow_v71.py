"""Generate converged release-documentation Release V71 over V70."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / "tests/fixtures/release_workflow_transition_v70.json"
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v71.json"
PREDECESSOR_SHA256 = "52d90fdd99a2798307423493320b03cda2338edab6365990d4d212a42c0019d4"
CURRENT_CLOSURE_PATHS = (
    "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V30.json",
    "scripts/build_release.py",
    "scripts/generate_current_successor_retirement_v30.py",
    "scripts/generate_release_workflow_v71.py",
    "scripts/verify_current_successor_retirement_v30.py",
    "scripts/verify_release_workflow_v70.py",
    "tests/conftest.py",
    "tests/test_current_successor_retirement_v30.py",
    "tests/test_release_workflow_transition_v71.py",
)


def sha256(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def frame(d, v):
    e = v.encode()
    d.update(len(e).to_bytes(8, "big"))
    d.update(e)


def generate():
    if sha256(PREDECESSOR) != PREDECESSOR_SHA256:
        raise RuntimeError("Release V70 predecessor digest drifted")
    p = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    paths = sorted(
        {*(e["path"] for e in p["current_release_paths"]), *CURRENT_CLOSURE_PATHS}
    )
    entries = [{"path": x, "sha256": sha256(ROOT / x)} for x in paths]
    rec = {
        "schema": "onyx.release-workflow-transition.v71",
        "issued_at": "2026-08-25T08:45:00-04:00",
        "logical_sequence": 71,
        "predecessor": {
            "path": PREDECESSOR.relative_to(ROOT).as_posix(),
            "sha256": PREDECESSOR_SHA256,
        },
        "policy": p["policy"],
        "current_release_paths": entries,
        "current_root_sha256": "",
    }
    d = hashlib.sha256(b"ONYX-RELEASE-WORKFLOW-TRANSITION-V71\0")
    for v in (
        rec["issued_at"],
        str(rec["logical_sequence"]),
        rec["predecessor"]["path"],
        rec["predecessor"]["sha256"],
    ):
        frame(d, v)
    for e in entries:
        frame(d, e["path"])
        frame(d, e["sha256"])
    rec["current_root_sha256"] = d.hexdigest()
    TARGET.write_text(
        json.dumps(rec, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n"
    )
    return rec


if __name__ == "__main__":
    print(json.dumps(generate(), sort_keys=True))
