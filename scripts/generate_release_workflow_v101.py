"""V101 SOURCE successor; generation requires the parent's final seal authority.

All V100 paths are inherited. Historical receipt tests are hash-bound file data,
not imported pytest suites. Neither current verification nor staged validation
belongs in registry authentication during generation.
"""

from datetime import datetime
from importlib import import_module
import json
from pathlib import Path

from scripts.verify_release_workflow_v70 import POLICY, _entries, _file, _json, _root, _sha256
from scripts.verify_release_workflow_v100 import V100, V100_ROOT_SHA256, V100_SHA256

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v101.json"
FINAL_FILE_LIST_CONFIRMED = True
ISSUED_AT = "2026-09-05T23:56:30+00:00"
REGISTRY_SOURCES = (
    "scripts/source_test_succession_v3.py",
    "tests/fixtures/source_test_succession_v3.json",
    "tests/test_source_test_succession_v3.py",
)
HISTORICAL_FIXTURES = tuple(
    f"tests/fixtures/release_workflow_transition_v{sequence}.json"
    for sequence in range(71, 101)
)
HISTORICAL_RECEIPTS = (
    "tests/test_onyx_hud_orb_v7_candidate.py",
    "tests/test_onyx_hud_orb_v8_candidate.py",
    "tests/test_phase6_live_wiring_v2.py",
)
REPORT = "docs/onyx/V101_WINDOWS_LINK_QUALIFICATION_20260905.md"
ADDITIONS = (
    "tests/fixtures/release_workflow_transition_v100.json",
    "scripts/verify_release_workflow_v100.py",
    "scripts/generate_release_workflow_v101.py",
    "tests/test_release_workflow_transition_v101.py",
    "scripts/verify_staged_capabilities_v1.py",
    "tests/test_staged_capability_source_v1.py",
    "tests/test_hud_linked_input_v1.py",
    "tests/test_packaged_humanoid_smoke_targets_v1.py",
    "tests/test_onyx_humanoid_entity_v10.py",
    "tests/test_release_preparation_v110.py",
    "tests/test_ruff_historical_immutable_ignores.py",
    REPORT,
    *HISTORICAL_RECEIPTS,
    *REGISTRY_SOURCES,
    *HISTORICAL_FIXTURES,
)


def load_record(root):
    # Lazy import keeps pre-seal preparation independent of unfinished parent
    # files. Only the finalized helper may authenticate registry V3 at seal.
    from scripts.source_test_succession_v3 import load_record as authenticate

    return authenticate(root)


def planned_paths(old, succession):
    """Pure plan over an already authenticated predecessor and future registry."""
    return sorted({
        *(row["path"] for row in _entries(old)),
        *ADDITIONS,
        *succession["bindings"],
    })


def generate():
    if not FINAL_FILE_LIST_CONFIRMED:
        raise RuntimeError("V101 unsealed: awaiting parent 'seal now' and final file list")
    succession = load_record(ROOT)
    # Never run verify_and_run, staged validation, or current V101 verification
    # from generation: those depend on the fixture we have not sealed yet.
    if _sha256(_file(ROOT, V100)) != V100_SHA256:
        raise RuntimeError("V100 predecessor changed")
    old = _json(ROOT / V100)
    if (
        old.get("current_root_sha256") != V100_ROOT_SHA256
        or _root(old, 100) != V100_ROOT_SHA256
        or old.get("policy") != POLICY
        or len(_entries(old)) != 687
    ):
        raise RuntimeError("V100 predecessor contract changed")
    if not isinstance(ISSUED_AT, str):
        raise RuntimeError("V101 unsealed: final issue time is required")
    if datetime.fromisoformat(ISSUED_AT) <= datetime.fromisoformat(old["issued_at"]):
        raise RuntimeError("V101 chronology must follow V100")
    for sequence, relative in zip(range(71, 101), HISTORICAL_FIXTURES, strict=True):
        authority = import_module(f"scripts.verify_release_workflow_v{sequence}")
        if _sha256(_file(ROOT, relative)) != getattr(authority, f"V{sequence}_SHA256"):
            raise RuntimeError(f"V{sequence} historical fixture changed")
    paths = planned_paths(old, succession)
    if {"scripts/verify_release_workflow_v101.py", TARGET.relative_to(ROOT).as_posix()}.intersection(paths):
        raise RuntimeError("V101 cannot include its own verifier or fixture digest")
    record = {
        "schema": "onyx.release-workflow-transition.v101",
        "issued_at": ISSUED_AT,
        "logical_sequence": 101,
        "predecessor": {"path": V100.as_posix(), "sha256": V100_SHA256},
        "policy": old["policy"],
        "current_release_paths": [
            {"path": path, "sha256": _sha256(_file(ROOT, path))} for path in paths
        ],
        "current_root_sha256": "",
    }
    for row in record["current_release_paths"]:
        expected = succession["bindings"].get(row["path"])
        if expected is not None and row["sha256"] != expected:
            raise RuntimeError(f"succession binding changed during generation: {row['path']}")
    record["current_root_sha256"] = _root(record, 101)
    encoded = (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8")
    if TARGET.exists():
        if TARGET.is_symlink() or TARGET.read_bytes() != encoded:
            raise RuntimeError("V101 already exists with different bytes; create a successor")
    else:
        with TARGET.open("xb") as stream:
            stream.write(encoded)
    return {"sha256": _sha256(TARGET), "root_sha256": record["current_root_sha256"], "paths": len(paths)}


if __name__ == "__main__":
    print(json.dumps(generate()))
