"""Verify external E6 acceptance of corrected Onyx Live Activation V8."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "VE-ONYX-LIVE-ACTIVATION-V8-E6-001"
RECORD = ROOT / "docs" / "onyx" / "acceptance" / f"{ID}.md"
ACCEPTANCE = RECORD.with_suffix(".manifest.json")
SHA = ROOT / "docs" / "onyx" / "VE-ACCEPTANCE-ONYX-LIVE-ACTIVATION-V8-E6-001.sha256"
CANDIDATE = (
    ROOT / "docs" / "onyx" / "checkpoints" / "onyx-live-activation-v8" / "manifest.json"
)
EXPECTED_MANIFEST = "ab28f369248df1ed807aeeee15658193a533881bf68fb2268d49692b52c20392"
EXPECTED_ROOT = "8198e4265e45f6895ac07e95943a8868127ee7bb3037fd7512ccf31515d998dd"


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
        if artifact["path"] != "scripts/verify_onyx_live_activation_v8_acceptance.py":
            assert _digest(ROOT / artifact["path"]) == artifact["sha256"]
    assert _digest(CANDIDATE) == EXPECTED_MANIFEST == meta["candidate_manifest_sha256"]
    rows = sorted(candidate["files"], key=lambda item: item["path"])
    for item in rows:
        assert _digest(ROOT / item["path"]) == item["sha256"]
    material = "".join(f"{item['path']}\0{item['sha256']}\n" for item in rows).encode()
    root = hashlib.sha256(material).hexdigest()
    assert root == EXPECTED_ROOT == meta["evidence_root_sha256"]
    digest, relative = SHA.read_text(encoding="utf-8").strip().split("  ", 1)
    assert relative == f"docs/onyx/acceptance/{ID}.md" and digest == _digest(RECORD)
    result = subprocess.run(
        [
            str(ROOT / ".venv" / "Scripts" / "python.exe"),
            "-B",
            "scripts/verify_onyx_live_activation_v8_manifest.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=1200,
    )
    assert (
        result.returncode == 0
        and "ONYX_LIVE_ACTIVATION_V8_MANIFEST_OK" in result.stdout
    )
    return {
        "acceptance_id": ID,
        "manifest_sha256": EXPECTED_MANIFEST,
        "evidence_root_sha256": root,
        "findings": meta["findings"],
        "scope": meta["scope"],
    }


if __name__ == "__main__":
    print("ONYX_LIVE_ACTIVATION_V8_ACCEPTANCE_OK", json.dumps(verify(), sort_keys=True))
