"""Verify external E6 acceptance of Gemini Live Compatibility C003."""

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "VE-P6-GEMINI-LIVE-COMPAT-C003-E6-001"
MANIFEST = ROOT / "docs/onyx/checkpoints/phase6-gemini-live-compat-v1/manifest.json"
META = ROOT / f"docs/onyx/acceptance/{ID}.manifest.json"
RECORD = ROOT / f"docs/onyx/acceptance/{ID}.md"
ACCEPTANCE = ROOT / "docs/onyx/VE-ACCEPTANCE-P6-GEMINI-LIVE-COMPAT-C003-E6-001.sha256"
EXPECTED_MANIFEST = "588d1c7d897ae0533031d2a20ea94f0fb711b8e8fc299da7f37b3604e3ef9854"
EXPECTED_ROOT = "1ec67d869234ff8b389b5dd228d82516958cf68fe5e4b8f140610601b6233ed6"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> dict[str, object]:
    meta = json.loads(META.read_text(encoding="utf-8"))
    candidate = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert digest(MANIFEST) == EXPECTED_MANIFEST == meta["candidate_manifest_sha256"]
    assert meta["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert len(candidate["artifacts"]) == meta["artifact_count"] == 7
    assert len(candidate["frozen_anchors"]) == meta["anchor_count"] == 6
    for item in candidate["artifacts"]:
        assert digest(ROOT / item["path"]) == item["sha256"]
    for path, expected in candidate["frozen_anchors"].items():
        assert digest(ROOT / path) == expected
    assert candidate["artifact_root_sha256"] == EXPECTED_ROOT
    assert [item["candidate"] for item in candidate["rejection_history"]] == [
        "phase6-gemini-live-compat-candidate-001",
        "phase6-gemini-live-compat-candidate-002",
    ]
    bound, relative = ACCEPTANCE.read_text(encoding="utf-8").strip().split("  ", 1)
    assert relative == f"docs/onyx/acceptance/{ID}.md" and bound == digest(RECORD)
    run = subprocess.run(
        [
            str(ROOT / ".venv/Scripts/python.exe"),
            "-I",
            "-S",
            "-B",
            "scripts/verify_phase6_gemini_live_compat_v1.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert run.returncode == 0 and "P6_GEMINI_LIVE_COMPAT_V1_OK" in run.stdout
    return meta


if __name__ == "__main__":
    print(
        "P6_GEMINI_LIVE_COMPAT_C003_ACCEPTANCE_OK", json.dumps(verify(), sort_keys=True)
    )
