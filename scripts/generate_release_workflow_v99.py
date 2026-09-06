"""Prepare V99 SOURCE authority; generation awaits the parent's 'seal now'.

Finalize ADDITIONS and ISSUED_AT from the parent's final file list before
enabling FINAL_FILE_LIST_CONFIRMED. Never rewrite V98 or an existing V99.
The V99 verifier is excluded from its own digest closure, as in V98.
"""

import json
from datetime import datetime
from importlib import import_module
from pathlib import Path

from scripts.hud_test_succession_v1 import load_record as load_hud_record
from scripts.source_test_succession_v1 import load_record
from scripts.verify_release_workflow_v70 import POLICY, _entries, _file, _json, _root, _sha256
from scripts.verify_release_workflow_v98 import V98, V98_ROOT_SHA256, V98_SHA256

ROOT = Path(__file__).resolve().parents[1]
PREDECESSOR = ROOT / V98
TARGET = ROOT / "tests/fixtures/release_workflow_transition_v99.json"
FINAL_FILE_LIST_CONFIRMED = True
ISSUED_AT = "2026-09-05T22:40:45+00:00"
HISTORICAL_FIXTURES = tuple(
    f"tests/fixtures/release_workflow_transition_v{sequence}.json"
    for sequence in range(71, 99)
)
R11_SNAPSHOTS = (
    "tests/fixtures/r11-memory-store-0516fafd.snapshot",
    "tests/fixtures/r11-a233194960de277fe697172d663ea12d8d6ac9de5feb4e1c41fc24ce7185a04c.snapshot",
    "tests/fixtures/r11-6cd546e975b05efd74c5cd790f3a6129d151ff86fb8557e8ec56cd465a661601.snapshot",
    "tests/fixtures/r11-6f4418afba826a60a682ec2c926fb9d214f14081a20c958f7f55688b66b0777c.snapshot",
)
ADDITIONS = (
    "core/telegram_official_connector_v1.py",
    "core/business_document_delivery_v1.py",
    "tests/test_telegram_document_delivery_v1.py",
    "tests/test_telegram_official_connector_v1.py",
    "tests/test_business_document_delivery_v1.py",
    "scripts/retirement_validation_session_v1.py",
    "scripts/successor_test_runner_v1.py",
    "scripts/r11_memory_evidence_supplement_v3.py",
    "scripts/advanced_operations_v23_test_succession.py",
    "tests/conftest.py",
    "tests/test_retirement_validation_session_v1.py",
    "tests/test_successor_test_runner_v1.py",
    "tests/test_r11_memory_evidence_supplement_v3.py",
    "tests/test_advanced_operations_v23_test_succession.py",
    "readme.md",
    "docs/INSTALLATION.md",
    "docs/onyx/CURRENT_CAPABILITY_STATUS_V2.md",
    "docs/onyx/BLOCKER_RESOLUTION_20260905.md",
    "docs/stories/ONYX-SECOND-BRAIN-PHONE-TWO-SPRINTS-V1.story.md",
    "tests/test_current_capability_status_v2.py",
    "tests/test_capability_expansion_layout_freeze_v1.py",
    "tests/test_hud_source_frozen_selection_v1.py",
    "tests/test_macos_release_pipeline_v1.py",
    "tests/test_onyx_hud_accessibility_stability_v1.py",
    "scripts/source_test_succession_v1.py",
    "tests/fixtures/source_test_succession_v1.json",
    "tests/test_source_test_succession_v1.py",
    "scripts/hud_test_succession_v1.py",
    "tests/fixtures/hud_test_succession_v1.json",
    "tests/test_hud_test_succession_v1.py",
    *R11_SNAPSHOTS,
    *HISTORICAL_FIXTURES,
    "scripts/verify_release_workflow_v98.py",
    "scripts/generate_release_workflow_v99.py",
    "tests/test_release_workflow_transition_v99.py",
    # Immutable registry bindings are added by planned_paths after authentication.
    # Parent confirmed final conftest/story/report and worker bytes before seal.
)


def planned_paths(old, succession, hud_succession):
    """Include every authenticated registry binding without executing its routes."""
    return sorted({
        *(row["path"] for row in _entries(old)),
        *ADDITIONS,
        *succession["bindings"],
        *hud_succession["bindings"],
    })


def generate():
    if not FINAL_FILE_LIST_CONFIRMED:
        raise RuntimeError("V99 unsealed: awaiting parent 'seal now' and final file list")
    # load_record authenticates the registry and all immutable bindings only.
    # verify_and_run would call V99 before its fixture exists and run pytest;
    # neither belongs in source generation.
    succession = load_record(ROOT)
    hud_succession = load_hud_record(ROOT)
    if _sha256(_file(ROOT, V98)) != V98_SHA256:
        raise RuntimeError("V98 predecessor changed")
    old = _json(PREDECESSOR)
    if (
        old.get("current_root_sha256") != V98_ROOT_SHA256
        or _root(old, 98) != V98_ROOT_SHA256
        or old.get("policy") != POLICY
        or len(_entries(old)) != 609
    ):
        raise RuntimeError("V98 predecessor contract changed")
    if datetime.fromisoformat(ISSUED_AT) <= datetime.fromisoformat(old["issued_at"]):
        raise RuntimeError("V99 chronology must follow V98")
    # Authenticate retained evidence against its original pins, never rebind it
    # to whatever bytes happen to be present when the successor is generated.
    for sequence, relative in zip(range(71, 99), HISTORICAL_FIXTURES, strict=True):
        authority = import_module(f"scripts.verify_release_workflow_v{sequence}")
        if _sha256(_file(ROOT, relative)) != getattr(authority, f"V{sequence}_SHA256"):
            raise RuntimeError(f"V{sequence} historical fixture changed")
    paths = planned_paths(old, succession, hud_succession)
    if {
        "scripts/verify_release_workflow_v99.py",
        TARGET.relative_to(ROOT).as_posix(),
    }.intersection(paths):
        raise RuntimeError("V99 cannot include its own verifier or fixture digest")
    record = {
        "schema": "onyx.release-workflow-transition.v99",
        "issued_at": ISSUED_AT,
        "logical_sequence": 99,
        "predecessor": {"path": V98.as_posix(), "sha256": V98_SHA256},
        "policy": old["policy"],
        "current_release_paths": [
            {"path": path, "sha256": _sha256(_file(ROOT, path))} for path in paths
        ],
        "current_root_sha256": "",
    }
    for row in record["current_release_paths"]:
        for registry in (succession, hud_succession):
            expected = registry["bindings"].get(row["path"])
            if expected is not None and row["sha256"] != expected:
                raise RuntimeError(f"succession binding changed during generation: {row['path']}")
    record["current_root_sha256"] = _root(record, 99)
    encoded = (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8")
    if TARGET.exists():
        if TARGET.is_symlink() or TARGET.read_bytes() != encoded:
            raise RuntimeError("V99 already exists with different bytes; create a successor")
    else:
        with TARGET.open("xb") as stream:
            stream.write(encoded)
    return {
        "sha256": _sha256(TARGET),
        "root_sha256": record["current_root_sha256"],
        "paths": len(paths),
    }


if __name__ == "__main__":
    print(json.dumps(generate()))
