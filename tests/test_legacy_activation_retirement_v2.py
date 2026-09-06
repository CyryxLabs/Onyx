from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import generate_legacy_activation_retirement_v2 as generator
from scripts import verify_legacy_activation_retirement_v2 as retirement


ROOT = Path(__file__).resolve().parents[1]


def test_v2_is_reproducible_and_preserves_v1() -> None:
    record = retirement.load_record(ROOT)
    assert record == generator.build()
    assert record["predecessor"] == {
        "path": "docs/onyx/checkpoints/LEGACY_ACTIVATION_RETIREMENT_V1.json",
        "sha256": hashlib.sha256(generator.PREDECESSOR.read_bytes()).hexdigest(),
    }
    assert len(retirement.registered_test_ids(ROOT)) == 44


def test_v19_cannot_regress_to_active_successor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    record = generator.build()
    claim = next(
        item for item in record["claims"]
        if item["id"] == generator.RETIRED_CLAIM
    )
    claim["successor_tests"] = [
        {
            "path": retirement.RETIRED_GENERATION,
            "sha256": hashlib.sha256(
                (ROOT / retirement.RETIRED_GENERATION).read_bytes()
            ).hexdigest(),
        }
    ]
    for relative in (
        "docs/onyx/checkpoints/LEGACY_ACTIVATION_RETIREMENT_V1.json",
        "docs/onyx/checkpoints/LEGACY_ACTIVATION_RETIREMENT_V2.json",
    ):
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if relative.endswith("V2.json"):
            target.write_text(
                json.dumps(record, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        else:
            target.write_bytes((ROOT / relative).read_bytes())
    monkeypatch.setattr(
        retirement,
        "_binding",
        lambda _root, value, _label: value["path"],
    )
    with pytest.raises(
        retirement.LegacyActivationRetirementV2Error,
        match="active successor is not Phase 6 current",
    ):
        retirement.load_record(project)
