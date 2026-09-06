"""Mechanical tests for the default-off Phase 4 E1-E5 candidate."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts import verify_phase4_exit_candidate as gate


def test_current_candidate_source_gate_passes_without_activation() -> None:
    result = gate.verify_all(require_process_flags_off=True)

    assert result["status"] == "P4_EXIT_CANDIDATE_SOURCE_OK"
    assert result["r10_files"] == 77
    assert result["activation"] is False
    assert result["owner_write_probe"] == "disabled-v1-zero-owner-writes"
    assert len(result["flags_default_off"]) == 8


@pytest.mark.parametrize("flag,reader,_accepted", gate.FLAG_SPECS)
def test_unknown_or_implicit_flag_values_never_enable(flag, reader, _accepted) -> None:
    for value in ("", "0", "false", "enabled", "2", " true-ish "):
        assert reader({flag: value}) is False


def test_source_gate_detects_startup_authority_widening(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    startup = tmp_path / "main.py"
    startup.write_text("from core.mission_evidence_v5 import LocalSystemStatusEvidenceService\n")
    monkeypatch.setattr(gate, "STARTUP_SOURCES", (startup,))

    with pytest.raises(RuntimeError, match="enhanced startup import"):
        gate.verify_startup_boundary()


def test_source_gate_detects_literal_dynamic_authority_widening(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    startup = tmp_path / "main.py"
    startup.write_text('__import__("core.control_plane_v5")\n', encoding="utf-8")
    monkeypatch.setattr(gate, "STARTUP_SOURCES", (startup,))

    with pytest.raises(RuntimeError, match="enhanced startup import"):
        gate.verify_startup_boundary()


def test_gate_module_has_no_owner_path_literal_or_mutating_runtime_call() -> None:
    source = Path(gate.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_literals = ("AppData", "runtime/control_plane.sqlite3", "owner_data")
    assert not any(value in source for value in forbidden_literals)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not ({"unlink", "rmdir", "replace", "rename"} & called)
