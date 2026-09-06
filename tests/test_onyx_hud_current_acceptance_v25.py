from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PySide6.QtQuick import QQuickItem  # noqa: F401
from PySide6.QtQuickWidgets import QQuickWidget  # noqa: F401

from core.onyx_hud_current_acceptance_v25 import (
    CURRENT_RUNTIME_PATHS,
    CurrentHudAcceptanceV25Error,
    MANIFEST_RELATIVE,
    PREDECESSOR_ACCEPTANCE_RELATIVE,
    PREDECESSOR_MANIFEST_RELATIVE,
    PREDECESSOR_MANIFEST_SHA256,
    verify_current_hud_acceptance,
)


ROOT = Path(__file__).resolve().parents[1]


def _copy_acceptance(destination: Path) -> None:
    for relative in {
        MANIFEST_RELATIVE,
        PREDECESSOR_MANIFEST_RELATIVE,
        PREDECESSOR_ACCEPTANCE_RELATIVE,
        *CURRENT_RUNTIME_PATHS,
    }:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)


def test_current_v25_full_source_closure_is_exact() -> None:
    result = verify_current_hud_acceptance(ROOT)
    assert {key: result[key] for key in (
        "candidate", "current_root", "qml_files", "runtime_inputs",
        "artifact_root_sha256", "predecessor_manifest_sha256",
        "stable_activation", "packaged_subset_contract",
    )} == {
        "candidate": "onyx-hud-v10-v37-packaged-runtime-contract-007",
        "current_root": "qml/OnyxLiveShellV10.qml",
        "qml_files": 6,
        "runtime_inputs": len(CURRENT_RUNTIME_PATHS),
        "artifact_root_sha256": result["artifact_root_sha256"],
        "predecessor_manifest_sha256": PREDECESSOR_MANIFEST_SHA256,
        "stable_activation": "V24",
        "packaged_subset_contract": "v1",
    }
    assert set(result["runtime_input_sha256"]) == {
        path.as_posix() for path in CURRENT_RUNTIME_PATHS
    }
    assert len(result["manifest_sha256"]) == 64


def test_every_v25_source_input_tamper_fails_closed(tmp_path: Path) -> None:
    _copy_acceptance(tmp_path)
    target = tmp_path / "scripts/package_hygiene.py"
    with target.open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(CurrentHudAcceptanceV25Error, match="input drift"):
        verify_current_hud_acceptance(tmp_path)


def test_v24_predecessor_remains_immutable(tmp_path: Path) -> None:
    _copy_acceptance(tmp_path)
    with (tmp_path / PREDECESSOR_MANIFEST_RELATIVE).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(CurrentHudAcceptanceV25Error, match="predecessor drift"):
        verify_current_hud_acceptance(tmp_path)
