"""Evidence-DAG self-tests for the Phase 4 E1-E5 R5 successor."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import verify_phase4_exit_candidate_r5 as gate


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def _manifest(root: Path, path: Path, inputs: set[str]) -> None:
    lines = [
        f"{hashlib.sha256((root / relative).read_bytes()).hexdigest()} *{relative}"
        for relative in sorted(inputs)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _synthetic_dag(tmp_path: Path):
    source_inputs = {"source.py", "test.py", "r11.sha256", "checkpoint.md", "artifacts.sha256"}
    artifact_inputs = {"bundle.json", "output.log"}
    for relative in source_inputs - {"artifacts.sha256"}:
        _write(tmp_path / relative, relative + "\n")
    for relative in artifact_inputs:
        _write(tmp_path / relative, relative + "\n")
    artifact_manifest = tmp_path / "artifacts.sha256"
    source_manifest = tmp_path / "source.sha256"
    _manifest(tmp_path, artifact_manifest, artifact_inputs)
    _manifest(tmp_path, source_manifest, source_inputs)
    anchor = hashlib.sha256(source_manifest.read_bytes()).hexdigest()
    return source_inputs, artifact_inputs, source_manifest, artifact_manifest, anchor


@pytest.mark.parametrize("relative", ["source.py", "test.py", "r11.sha256", "checkpoint.md"])
def test_external_source_anchor_rejects_every_source_layer_tamper(tmp_path: Path, relative: str) -> None:
    source, artifacts, source_manifest, artifact_manifest, anchor = _synthetic_dag(tmp_path)
    gate.verify_two_level_dag(
        root=tmp_path,
        source_manifest=source_manifest,
        source_paths=frozenset(source),
        artifact_manifest=artifact_manifest,
        artifact_paths=frozenset(artifacts),
        external_source_sha256=anchor,
    )
    _write(tmp_path / relative, "tampered\n")
    with pytest.raises(RuntimeError, match="source.py|test.py|r11.sha256|checkpoint.md"):
        gate.verify_two_level_dag(
            root=tmp_path,
            source_manifest=source_manifest,
            source_paths=frozenset(source),
            artifact_manifest=artifact_manifest,
            artifact_paths=frozenset(artifacts),
            external_source_sha256=anchor,
        )


def test_external_source_anchor_rejects_artifact_manifest_change(tmp_path: Path) -> None:
    source, artifacts, source_manifest, artifact_manifest, anchor = _synthetic_dag(tmp_path)
    artifact_manifest.write_bytes(artifact_manifest.read_bytes() + b"\n")
    with pytest.raises(RuntimeError, match="artifacts.sha256"):
        gate.verify_two_level_dag(
            root=tmp_path,
            source_manifest=source_manifest,
            source_paths=frozenset(source),
            artifact_manifest=artifact_manifest,
            artifact_paths=frozenset(artifacts),
            external_source_sha256=anchor,
        )


@pytest.mark.parametrize("relative", ["bundle.json", "output.log"])
def test_second_level_manifest_rejects_artifact_tamper(tmp_path: Path, relative: str) -> None:
    source, artifacts, source_manifest, artifact_manifest, anchor = _synthetic_dag(tmp_path)
    _write(tmp_path / relative, "tampered\n")
    with pytest.raises(RuntimeError, match=relative.replace(".", r"\.")):
        gate.verify_two_level_dag(
            root=tmp_path,
            source_manifest=source_manifest,
            source_paths=frozenset(source),
            artifact_manifest=artifact_manifest,
            artifact_paths=frozenset(artifacts),
            external_source_sha256=anchor,
        )


def test_current_r5_is_frozen_but_not_externally_anchored() -> None:
    result = gate.verify_frozen()
    assert result["status"] == "P4_EXIT_CANDIDATE_R5_FROZEN_OK"
    assert result["e6_accepted"] is False
    assert result["external_source_anchor_present"] is False
    assert result["dag"]["external_source_anchor_verified"] is False
    assert result["reused_r4_junit_tests"] == 73


def test_bundle_has_no_manifest_or_self_hash_claims() -> None:
    path = gate.PROJECT / "docs/onyx/checkpoints/phase4-e1-e5/phase4-e1-e5-r5.bundle.json"
    dag = json.loads(path.read_text(encoding="utf-8"))["manifest_dag"]
    assert dag["external_registration_must_store"] == "source_manifest_sha256"
    assert dag["external_source_anchor_present"] is False
    assert not {
        "bundle_sha256",
        "source_manifest_sha256",
        "artifact_manifest_sha256",
        "evidence_manifest_sha256",
    } & set(dag)


def test_r4_historical_bytes_are_unchanged() -> None:
    expected = {
        "docs/onyx/VE-SCOPE-P4-E1E5-R4-001.sha256":
            "b39d0fdc8dde20a5bcb6f7c067edcc0a5bd4d289f27c5de6b3841c65d7ec54a0",
        "docs/onyx/VE-ARTIFACTS-P4-E1E5-R4-001.sha256":
            "9f3ec104b8f07835a302c9b875d40f3ad36d3505c91480c386be828001dbff6e",
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-e1-e5-r4.bundle.json":
            "61d7b2e099a93a8e78b2ba3222169f24449862d1c2c9851b9fd6e40ba3640424",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((gate.PROJECT / relative).read_bytes()).hexdigest() == digest
