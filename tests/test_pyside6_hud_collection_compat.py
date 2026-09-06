from __future__ import annotations

import importlib.util
import runpy
from pathlib import Path

import pytest

from scripts.verify_v19_pytest_collection import V19_TEST_FILES


PROJECT = Path(__file__).resolve().parents[1]
CONFTEST = PROJECT / "tests/conftest.py"
FROZEN = (
    "test_onyx_hud_orb_v7_candidate.py",
    "test_onyx_hud_orb_v8_candidate.py",
)
SUPERSEDED = (
    "test_hud_orb_v8_c001_acceptance.py",
    "test_onyx_hud_current_acceptance_v19.py",
    "test_onyx_hud_current_acceptance_v20.py",
    "test_onyx_hud_current_acceptance_v21.py",
    "test_onyx_hud_current_acceptance_v22.py",
    "test_onyx_hud_current_acceptance_v23.py",
    "test_onyx_hud_current_acceptance_v24.py",
    "test_onyx_hud_current_acceptance_v25.py",
)
SUPERSEDED_CAPABILITY = ("test_capability_nexus_v32_acceptance.py",)
CURRENT_HUD = "tests/test_onyx_hud_current_acceptance_v26.py"
REQUIRED_MODULES = (
    "PyQt6.QtQuick",
    "PyQt6.QtQuickWidgets",
    "PyQt6.QtTest",
    "PyQt6.QtWidgets",
)


@pytest.mark.parametrize("missing_module", REQUIRED_MODULES)
def test_each_missing_pyqt6_module_ignores_exactly_the_frozen_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    missing_module: str,
) -> None:
    def partial_binding(module_name: str) -> object | None:
        return None if module_name == missing_module else object()

    monkeypatch.setattr(importlib.util, "find_spec", partial_binding)
    namespace = runpy.run_path(str(CONFTEST))

    assert namespace["_FROZEN_PYQT6_HUD_TESTS"] == FROZEN
    assert namespace["_SUPERSEDED_HUD_ACCEPTANCE_TESTS"] == SUPERSEDED
    assert namespace["_SUPERSEDED_CAPABILITY_NEXUS_ACCEPTANCE_TESTS"] == (
        SUPERSEDED_CAPABILITY
    )
    assert namespace["collect_ignore"] == [
        *FROZEN,
        *SUPERSEDED,
        *SUPERSEDED_CAPABILITY,
    ]
    assert Path(CURRENT_HUD).name not in namespace["collect_ignore"]
    assert namespace["_complete_pyqt6_hud_binding_available"]() is False


@pytest.mark.parametrize(
    "error_type",
    (ImportError, ModuleNotFoundError, ValueError),
)
def test_binding_probe_errors_ignore_exactly_the_frozen_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    def failed_binding(_module_name: str) -> object:
        raise error_type("binding probe failed")

    monkeypatch.setattr(importlib.util, "find_spec", failed_binding)
    namespace = runpy.run_path(str(CONFTEST))

    assert namespace["collect_ignore"] == [
        *FROZEN,
        *SUPERSEDED,
        *SUPERSEDED_CAPABILITY,
    ]
    assert Path(CURRENT_HUD).name not in namespace["collect_ignore"]
    assert namespace["_complete_pyqt6_hud_binding_available"]() is False


def test_complete_pyqt6_binding_ignores_only_explicit_historical_tombstones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda _module_name: object())
    namespace = runpy.run_path(str(CONFTEST))

    assert namespace["collect_ignore"] == [*SUPERSEDED, *SUPERSEDED_CAPABILITY]
    assert Path(CURRENT_HUD).name not in namespace["collect_ignore"]
    assert namespace["_complete_pyqt6_hud_binding_available"]() is True


def test_supported_v7_and_current_v26_authorities_use_pyside6_binding() -> None:
    successors = (
        PROJECT / "tests/test_hud_orb_v7_c003_acceptance.py",
        PROJECT / "tests/test_onyx_hud_current_acceptance_v26.py",
    )
    for path in successors:
        source = path.read_text(encoding="utf-8")
        assert "from PySide6.QtQuick import QQuickItem" in source
        assert "from PySide6.QtQuickWidgets import QQuickWidget" in source
        assert "from PyQt6" not in source
    assert (PROJECT / "tests/test_hud_orb_v8_c001_acceptance.py").is_file()
    assert "tests/test_onyx_hud_current_acceptance_v19.py" in V19_TEST_FILES
