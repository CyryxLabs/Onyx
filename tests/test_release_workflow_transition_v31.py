from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from core.onyx_hud_current_acceptance_v26 import (
    CURRENT_RUNTIME_PATHS,
    MANIFEST_RELATIVE,
    PREDECESSOR_ACCEPTANCE_RELATIVE,
    PREDECESSOR_MANIFEST_RELATIVE,
    CurrentHudAcceptanceV26Error,
)
from scripts import verify_phase5_exit_retirement_v1 as retirement
from scripts.verify_release_workflow_v39 import verify_release_workflow_v39
from scripts.verify_release_runtime_closure_v1 import verify_runtime_inputs


ROOT = Path(__file__).resolve().parents[1]
V30 = ROOT / "tests/fixtures/release_workflow_transition_v30.json"
V31 = ROOT / "tests/fixtures/release_workflow_transition_v31.json"


def _copy_runtime_closure(destination: Path) -> None:
    for relative in {
        MANIFEST_RELATIVE,
        PREDECESSOR_ACCEPTANCE_RELATIVE,
        PREDECESSOR_MANIFEST_RELATIVE,
        *CURRENT_RUNTIME_PATHS,
    }:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)


def test_release_v31_authenticates_v30_and_transitive_runtime_closure() -> None:
    verify_release_workflow_v39(ROOT)
    release = json.loads(V31.read_text(encoding="utf-8"))
    assert hashlib.sha256(V31.read_bytes()).hexdigest() == retirement.RELEASE_TRANSITION_V31_SHA256
    assert hashlib.sha256(V30.read_bytes()).hexdigest() == retirement.RELEASE_TRANSITION_V30_SHA256
    assert release["schema"] == "onyx.release-workflow-transition.v31"
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert {
        "core/onyx_hud_current_acceptance_v26.py",
        "core/onyx_packaged_runtime_hud_contract_v1.py",
        "core/onyx_packaged_runtime_hud_contract_v1.manifest.json",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V26-E6-001.manifest.json",
        "scripts/verify_release_runtime_closure_v1.py",
        "tests/fixtures/phase5_current_successor_transition_v40.json",
        "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V7.json",
    } <= paths
    assert "scripts/verify_phase5_exit_retirement_v1.py" not in paths
    assert json.loads(V30.read_text(encoding="utf-8"))["schema"] == (
        "onyx.release-workflow-transition.v30"
    )


def test_direct_release_runtime_verifier_rejects_runtime_input_drift(
    tmp_path: Path,
) -> None:
    _copy_runtime_closure(tmp_path)
    target = tmp_path / "qml/OnyxLiveShellV10.qml"
    target.write_bytes(target.read_bytes() + b"\n// release runtime drift\n")

    with pytest.raises(CurrentHudAcceptanceV26Error, match="source input drift"):
        verify_runtime_inputs(tmp_path)
