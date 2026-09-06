"""Verify external E6 acceptance of HUD/Orb V8 Candidate 001."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ID = "VE-HUD-ORB-V8-C001-E6-001"
CANDIDATE = ROOT / "docs/onyx/checkpoints/hud-orb-v8-candidate/manifest.json"
RECORD = ROOT / f"docs/onyx/acceptance/{ID}.md"
METADATA = RECORD.with_suffix(".manifest.json")
SOURCE = ROOT / "docs/onyx/VE-SOURCE-HUD-ORB-V8-C001-E6-001.sha256"
ARTIFACTS = ROOT / "docs/onyx/VE-ARTIFACTS-HUD-ORB-V8-C001-E6-001.sha256"
ACCEPTANCE = ROOT / "docs/onyx/VE-ACCEPTANCE-HUD-ORB-V8-C001-E6-001.sha256"
EXPECTED_MANIFEST = "b3ea35bea9a160803ae01c3ddfc8e4e5811d5547095f7dc21b0ca8f2adbf4152"
EXPECTED_ROOT = "7d32ac55daeb3bb01dcdb18ea112c4d6d71453ff28cf1aed7fb07d9ae803a967"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_sha(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        value, relative = line.split("  ", maxsplit=1)
        assert len(value) == 64 and relative not in result
        result[relative] = value
    return result


def run_gate(*arguments: str, timeout: int = 180) -> str:
    result = subprocess.run(
        [str(ROOT / ".venv/Scripts/python.exe"), "-B", *arguments],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout


def verify() -> dict[str, object]:
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    assert digest(CANDIDATE) == EXPECTED_MANIFEST
    assert candidate["artifact_root_sha256"] == EXPECTED_ROOT
    assert metadata["acceptance_id"] == ID
    assert metadata["decision"] == "accepted"
    assert metadata["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert metadata["candidate_manifest_sha256"] == EXPECTED_MANIFEST
    assert metadata["evidence_root_sha256"] == EXPECTED_ROOT
    assert metadata["scope"] == "windows-d3d11-default-off-no-live-activation"
    assert metadata["results"] == {
        "candidate": 7,
        "external": 8,
        "v7_regression": 19,
        "quick_widgets": 1,
        "voice_layer_fps": [12, 0, 0],
    }

    rows = sorted(candidate["artifacts"], key=lambda item: item["path"])
    material = "".join(
        f"{item['path']}\0{item['sha256']}\n" for item in rows
    ).encode()
    assert hashlib.sha256(material).hexdigest() == EXPECTED_ROOT
    for item in rows:
        assert digest(ROOT / item["path"]) == item["sha256"]
    for relative, expected in candidate["frozen_anchors"].items():
        assert digest(ROOT / relative) == expected

    source = parse_sha(SOURCE)
    expected_source = {
        item["path"]: item["sha256"] for item in candidate["artifacts"]
    } | candidate["frozen_anchors"]
    assert source == expected_source
    for relative, expected in source.items():
        assert digest(ROOT / relative) == expected

    acceptance = parse_sha(ACCEPTANCE)
    assert acceptance == {f"docs/onyx/acceptance/{ID}.md": digest(RECORD)}
    for item in metadata["new_artifacts"]:
        assert digest(ROOT / item["path"]) == item["sha256"]

    artifacts = parse_sha(ARTIFACTS)
    expected_artifacts = {
        f"docs/onyx/acceptance/{ID}.md",
        f"docs/onyx/acceptance/{ID}.manifest.json",
        "docs/onyx/VE-SOURCE-HUD-ORB-V8-C001-E6-001.sha256",
        "docs/onyx/VE-ACCEPTANCE-HUD-ORB-V8-C001-E6-001.sha256",
        "scripts/verify_hud_orb_v8_c001_acceptance.py",
        "tests/test_hud_orb_v8_c001_acceptance.py",
    }
    assert set(artifacts) == expected_artifacts
    for relative, expected in artifacts.items():
        assert digest(ROOT / relative) == expected

    candidate_gate = run_gate("-I", "-S", "scripts/verify_hud_orb_v8_candidate.py")
    external_gate = run_gate(
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        ".pytest-hud-v8-c001-e6-external",
        "tests/test_hud_orb_v8_c001_acceptance.py",
    )
    v7_gate = run_gate(
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        ".pytest-hud-v8-c001-e6-v7",
        "tests/test_onyx_hud_orb_v7_candidate.py",
    )
    assert "HUD_ORB_V8_CANDIDATE_OK" in candidate_gate
    assert "8 passed" in external_gate
    assert "19 passed" in v7_gate
    return {
        "acceptance_id": ID,
        "candidate_manifest_sha256": EXPECTED_MANIFEST,
        "evidence_root_sha256": EXPECTED_ROOT,
        "findings": metadata["findings"],
        "gates": [7, 8, 19],
        "live": False,
    }


if __name__ == "__main__":
    print(
        "HUD_ORB_V8_C001_ACCEPTANCE_OK",
        json.dumps(verify(), sort_keys=True),
    )
