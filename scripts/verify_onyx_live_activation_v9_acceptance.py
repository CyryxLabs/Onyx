"""Verify the external E6 acceptance envelope for Activation V9."""

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "VE-ONYX-LIVE-ACTIVATION-V9-E6-001"
MANIFEST = ROOT / "docs/onyx/checkpoints/onyx-live-activation-v9/manifest.json"
META = ROOT / f"docs/onyx/acceptance/{ID}.manifest.json"
EXPECTED = "38de625b7725dab7aa9c7906f7f3164687f1f20a0cca6e683fe64145bb53142a"
ROOT_SHA = "88307dbbf5ac2f3d1656549db94cd1293103a12b38ba8d157271f71700c5123d"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    meta = json.loads(META.read_text(encoding="utf-8"))
    candidate = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert digest(MANIFEST) == EXPECTED == meta["candidate_manifest_sha256"]
    assert (
        meta["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        and meta["binding_count"] == 20
    )
    rows = sorted(candidate["files"], key=lambda x: x["path"])
    assert len(rows) == 20
    for row in rows:
        assert digest(ROOT / row["path"]) == row["sha256"]
    root = hashlib.sha256(
        "".join(f"{x['path']}\0{x['sha256']}\n" for x in rows).encode()
    ).hexdigest()
    assert root == ROOT_SHA == meta["evidence_root_sha256"]
    run = subprocess.run(
        [
            str(ROOT / ".venv/Scripts/python.exe"),
            "-I",
            "-S",
            "-B",
            "scripts/verify_onyx_live_activation_v9.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert run.returncode == 0 and "ONYX_LIVE_ACTIVATION_V9_CUMULATIVE_OK" in run.stdout
    return meta


if __name__ == "__main__":
    print("ONYX_LIVE_ACTIVATION_V9_ACCEPTANCE_OK", json.dumps(verify(), sort_keys=True))
