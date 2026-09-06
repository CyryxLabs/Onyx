"""Successor-binding tests for the Phase 4 E1-E5 R4 candidate."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import verify_p44_scope_r11 as r11
from scripts import verify_phase4_exit_candidate_r3 as r3
from scripts import verify_phase4_exit_candidate_r4 as gate


def test_r11_scope_is_r10_superset_with_shortcut_regression() -> None:
    prior = r11.r10.expected_scope()
    current = r11.expected_scope()
    assert prior < current
    assert current - prior == {
        "scripts/verify_p44_scope_r11.py",
        "tests/test_desktop_shortcut.py",
    }
    assert "ui.py" in current


def test_r11_manifest_is_current_and_exact() -> None:
    count, _digest = r11.verify(gate.R11_MANIFEST)
    assert count == len(r11.expected_scope())


def test_r4_selection_retires_only_obsolete_r10_binding_and_is_fully_scoped() -> None:
    prior_nodes, _ = r3.parse_selection()
    nodes, sources = gate.parse_selection()
    assert set(prior_nodes) - {gate.RETIRED_R3_NODE} <= set(nodes)
    assert gate.RETIRED_R3_NODE not in nodes
    assert gate.R3_SUCCESSOR_NODES <= set(nodes)
    assert set(nodes) - (set(prior_nodes) | gate.R3_SUCCESSOR_NODES) == {
        "tests/test_desktop_shortcut.py",
        "tests/test_phase4_exit_candidate_r4.py",
    }
    assert "tests/test_desktop_shortcut.py" in sources
    assert gate.verify_selection_scope() == {"nodes": 30, "sources": 10}


def test_r4_selection_missing_predecessor_node_fails_closed(tmp_path: Path) -> None:
    nodes, _ = gate.parse_selection()
    retained = sorted(set(r3.parse_selection()[0]) - {gate.RETIRED_R3_NODE})
    removed = retained[0]
    selection = tmp_path / "selection.txt"
    selection.write_text(
        "\n".join(node for node in nodes if node != removed) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="omitted R3 node"):
        gate.verify_selection_scope(selection=selection)


def test_r4_source_only_is_current_nonactivating_and_owner_safe() -> None:
    result = gate.verify_source_only()
    assert result["status"] == "P4_EXIT_CANDIDATE_R4_SOURCE_OK"
    assert result["activation"] is False
    assert result["e6_accepted"] is False
    assert result["owner_write_probe"] == "disabled-v1-zero-write"
    assert result["r11_files"] == len(r11.expected_scope())


def test_successor_manifests_never_hash_themselves() -> None:
    assert "docs/onyx/VE-SCOPE-P4-E1E5-R4-001.sha256" not in gate.R4_SOURCE_PATHS
    assert "docs/onyx/VE-ARTIFACTS-P4-E1E5-R4-001.sha256" not in gate.R4_EVIDENCE_PATHS


def test_historical_r10_and_r3_artifacts_remain_byte_bound() -> None:
    expected = {
        "docs/onyx/VE-SCOPE-P44-R10-001.sha256":
            "7745fd80ef2f8dda06fffee3a497097cc6c89cae7a1cbc89f514dc07cf88ef4d",
        "docs/onyx/VE-SCOPE-P4-E1E5-R3-001.sha256":
            "8a5372d207211dec706784aa0a5840af1aacb91a69fc20aa674dea8784c3e6bb",
        "docs/onyx/VE-ARTIFACTS-P4-E1E5-R3-001.sha256":
            "c5aac221fee66e3dcc0463f385f8c954617ec038e99eac35b948acea0345027f",
    }
    for relative, digest in expected.items():
        actual = hashlib.sha256((gate.PROJECT / relative).read_bytes()).hexdigest()
        assert actual == digest
