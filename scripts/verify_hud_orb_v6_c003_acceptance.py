"""Verify external E6 acceptance of HUD Orb V6 Candidate 003."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "VE-HUD-ORB-V6-C003-E6-001"
RECORD = ROOT / "docs" / "onyx" / "acceptance" / f"{ID}.md"
ACCEPTANCE = RECORD.with_suffix(".manifest.json")
SHA = ROOT / "docs" / "onyx" / "VE-ACCEPTANCE-HUD-ORB-V6-C003-E6-001.sha256"
CANDIDATE = (
    ROOT / "docs" / "onyx" / "checkpoints" / "hud-orb-v6-candidate" / "manifest.json"
)
EXPECTED_MANIFEST = "ba034588791b1003a6743bf037ae32a11285adcac7c4084cba1bc5bb3923ae1c"
EXPECTED_ROOT = "0e100c6d7ace7c058d57ec53b72338b566345c4e36874c120bc8bc1c219f76ee"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> dict[str, object]:
    meta = json.loads(ACCEPTANCE.read_text(encoding="utf-8"))
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    assert meta["acceptance_id"] == ID and meta["findings"] == {
        "P0": 0,
        "P1": 0,
        "P2": 0,
        "P3": 0,
    }
    for artifact in meta["new_artifacts"]:
        if artifact["path"] != "scripts/verify_hud_orb_v6_c003_acceptance.py":
            assert _digest(ROOT / artifact["path"]) == artifact["sha256"]
    assert _digest(CANDIDATE) == EXPECTED_MANIFEST == meta["candidate_manifest_sha256"]
    rows = sorted(
        candidate["files"] + candidate["preserved_anchors"],
        key=lambda item: item["path"],
    )
    for item in rows:
        path = ROOT / item["path"]
        assert path.stat().st_size == item["size"] and _digest(path) == item["sha256"]
    material = "".join(
        f"{item['path']}\0{item['size']}\0{item['sha256']}\n" for item in rows
    ).encode()
    root = hashlib.sha256(material).hexdigest()
    assert root == EXPECTED_ROOT == meta["evidence_root_sha256"]
    assert meta["physical_evidence_reuse"] == "candidate-002-byte-exact"
    digest, relative = SHA.read_text(encoding="utf-8").strip().split("  ", 1)
    assert relative == f"docs/onyx/acceptance/{ID}.md" and digest == _digest(RECORD)
    result = subprocess.run(
        [
            str(ROOT / ".venv" / "Scripts" / "python.exe"),
            "-B",
            "scripts/verify_hud_orb_v6_candidate.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0 and "HUD_ORB_V6_CANDIDATE_OK" in result.stdout
    return {
        "acceptance_id": ID,
        "manifest_sha256": EXPECTED_MANIFEST,
        "evidence_root_sha256": root,
        "findings": meta["findings"],
        "scope": meta["scope"],
    }


if __name__ == "__main__":
    print("HUD_ORB_V6_C003_ACCEPTANCE_OK", json.dumps(verify(), sort_keys=True))
