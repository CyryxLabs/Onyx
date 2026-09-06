from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

import pytest

from scripts import verify_r11_projection_retirement_v2 as retirement


def test_v2_materializes_authenticated_historical_desktop(tmp_path: Path) -> None:
    module = importlib.import_module("scripts.verify_phase5_approval_inbox_v7")
    root = tmp_path / "projection"
    copied = retirement.materialize_r11(module, root)
    desktop_path = "actions/desktop.py"
    desktop = root / desktop_path
    assert desktop_path in copied
    assert hashlib.sha256(desktop.read_bytes()).hexdigest() == retirement.SUPPLEMENTAL_HEAD_FILES[desktop_path][1]
    retirement.verify_r11(module, root, (module.R11_ROOT, module.R11_ACCEPTANCE_MANIFEST))


def test_v2_supplement_fails_closed_on_wrong_manifest_edge() -> None:
    with pytest.raises(
        retirement.R11ProjectionRetirementError,
        match="supplemental manifest edge drifted",
    ):
        retirement._historical_head_file("actions/desktop.py", "0" * 64)
