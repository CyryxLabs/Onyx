from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import ui


def test_source_hud_path_uses_full_v47_acceptance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[tuple[str, Path]] = []
    acceptance = SimpleNamespace(
        verify_current_hud_acceptance=lambda root: calls.append(("source", root)) or {}
    )
    monkeypatch.setattr(ui, "is_frozen", lambda: False)
    monkeypatch.setattr(
        ui.importlib,
        "import_module",
        lambda name: (
            acceptance
            if name == "core.onyx_hud_current_acceptance_v48"
            else (_ for _ in ()).throw(AssertionError(name))
        ),
    )

    ui._verify_current_hud_contract(tmp_path)

    assert calls == [("source", tmp_path)]


def test_frozen_hud_path_uses_only_packaged_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[tuple[str, Path]] = []
    packaged = SimpleNamespace(
        verify_packaged_runtime_hud_contract=lambda root: (
            calls.append(("packaged", root)) or {}
        )
    )
    monkeypatch.setattr(ui, "is_frozen", lambda: True)
    monkeypatch.setattr(
        ui.importlib,
        "import_module",
        lambda name: (
            packaged
            if name == "core.onyx_packaged_runtime_hud_contract_v17"
            else (_ for _ in ()).throw(AssertionError(name))
        ),
    )

    ui._verify_current_hud_contract(tmp_path)

    assert calls == [("packaged", tmp_path)]
