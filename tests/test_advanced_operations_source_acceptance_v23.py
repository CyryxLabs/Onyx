from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import generate_advanced_operations_source_acceptance_v23 as generator
from scripts import verify_advanced_operations_source_acceptance_v23 as verifier


ROOT = Path(__file__).resolve().parents[1]


def test_v23_is_reproducible_exact_and_append_only() -> None:
    manifest = verifier.verify(ROOT)
    assert manifest == generator.build(ROOT)
    assert manifest["predecessor"]["path"].endswith("V22-001.manifest.json")
    assert manifest["selection"]["count"] == len(generator.SELECTED_PATHS) == 18
    assert [item["path"] for item in manifest["files"]] == sorted(
        generator.SELECTED_PATHS
    )


def test_v23_rejects_selection_scope_reduction(tmp_path: Path) -> None:
    manifest = generator.build(ROOT)
    manifest["files"].pop()
    target = tmp_path / verifier.MANIFEST_RELATIVE
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    predecessor = tmp_path / generator.PREDECESSOR_RELATIVE
    predecessor.parent.mkdir(parents=True, exist_ok=True)
    predecessor.write_bytes((ROOT / generator.PREDECESSOR_RELATIVE).read_bytes())
    with pytest.raises(
        verifier.AdvancedOperationsSourceAcceptanceV23Error,
        match="selected paths drifted",
    ):
        verifier.verify(tmp_path)
