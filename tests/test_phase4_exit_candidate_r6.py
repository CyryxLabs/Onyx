"""Self-tests for the fresh R12-bound Phase 4 R6 evidence candidate."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import verify_phase4_exit_candidate_r6 as gate


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _manifest(root: Path, path: Path, inputs: frozenset[str]) -> None:
    path.write_text(
        "".join(
            f"{hashlib.sha256((root / relative).read_bytes()).hexdigest()} *{relative}\n"
            for relative in sorted(inputs)
        ),
        encoding="utf-8",
        newline="\n",
    )


def test_r12_manifest_is_current_and_comprehensive() -> None:
    count, _digest = gate.r12.verify(gate.R12_MANIFEST)
    assert count == 80
    assert {"ui.py", "tests/test_desktop_shortcut.py"} <= gate.r12.expected_scope()


def test_r6_selection_is_current_and_all_sources_are_bound() -> None:
    assert gate.verify_selection_scope() == {
        "nodes": 34,
        "sources": 10,
        "obsolete_bindings": 0,
    }


def test_r6_source_gate_is_nonactivating_and_owner_safe() -> None:
    result = gate.verify_source_only()
    assert result["status"] == "P4_EXIT_CANDIDATE_R6_SOURCE_OK"
    assert result["activation"] is False and result["e6_accepted"] is False
    assert result["owner_write_probe"] == "disabled-v1-zero-write"


def test_top_source_anchor_covers_both_manifest_levels(tmp_path: Path) -> None:
    sources = frozenset({"r12.sha256", "checkpoint.md", "artifacts.sha256"})
    artifacts = frozenset({"bundle.json", "pytest.log"})
    for relative in sources - {"artifacts.sha256"}:
        _write(tmp_path / relative, relative + "\n")
    for relative in artifacts:
        _write(tmp_path / relative, relative + "\n")
    artifact_manifest = tmp_path / "artifacts.sha256"
    source_manifest = tmp_path / "source.sha256"
    _manifest(tmp_path, artifact_manifest, artifacts)
    _manifest(tmp_path, source_manifest, sources)
    anchor = hashlib.sha256(source_manifest.read_bytes()).hexdigest()
    result = gate.verify_two_level_dag(
        root=tmp_path,
        source_manifest=source_manifest,
        source_paths=sources,
        artifact_manifest=artifact_manifest,
        artifact_paths=artifacts,
        external_source_sha256=anchor,
    )
    assert result["external_source_anchor_verified"] is True
    _write(tmp_path / "bundle.json", "tampered\n")
    with pytest.raises(RuntimeError, match="bundle.json"):
        gate.verify_two_level_dag(
            root=tmp_path,
            source_manifest=source_manifest,
            source_paths=sources,
            artifact_manifest=artifact_manifest,
            artifact_paths=artifacts,
            external_source_sha256=anchor,
        )


def test_historical_r11_r4_r5_manifests_remain_unchanged() -> None:
    expected = {
        "docs/onyx/VE-SCOPE-P44-R11-001.sha256":
            "6b94727640bdc60a5001d6b6ebf0cc484ec7cf37bd52c18634487fa430e72edc",
        "docs/onyx/VE-SCOPE-P4-E1E5-R4-001.sha256":
            "b39d0fdc8dde20a5bcb6f7c067edcc0a5bd4d289f27c5de6b3841c65d7ec54a0",
        "docs/onyx/VE-SCOPE-P4-E1E5-R5-001.sha256":
            "ebd16e9a426c57ca823775ab760a0f795027751039304a7a2cb93453960b4330",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((gate.PROJECT / relative).read_bytes()).hexdigest() == digest
