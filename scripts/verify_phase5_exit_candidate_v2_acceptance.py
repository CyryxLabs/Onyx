"""Verify external E6 acceptance of Phase 5 Exit Candidate V2."""

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = "VE-P5-EXIT-CANDIDATE-V2-E6-001"
MANIFEST = ROOT / "docs/onyx/checkpoints/phase5-exit-candidate-v2/manifest.json"
META = ROOT / f"docs/onyx/acceptance/{ID}.manifest.json"
RECORD = ROOT / f"docs/onyx/acceptance/{ID}.md"
ACCEPTANCE = ROOT / "docs/onyx/VE-ACCEPTANCE-P5-EXIT-CANDIDATE-V2-E6-001.sha256"
EXPECTED_MANIFEST = "b2cf8d781fc1f72a375be444c24ad74c4e59b910adab765a48c7c7b59ae15d2b"
EXPECTED_ROOT = "2255b9a8a5315f99ab376f7f32d22ef8d39e6c2c4039a9ff77afa4ddf75e5fa6"
EXPECTED_SELECTION = "39735644fa8b88bd856eb994a526a56da4f79544ad4a6f9bd96fe9651fcafc8f"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> dict[str, object]:
    meta = json.loads(META.read_text(encoding="utf-8"))
    candidate = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert digest(MANIFEST) == EXPECTED_MANIFEST == meta["candidate_manifest_sha256"]
    assert meta["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    assert len(candidate["files"]) == meta["binding_count"] == 73
    digests = {item["path"]: item["sha256"] for item in candidate["files"]}
    for path, expected in digests.items():
        assert digest(ROOT / path) == expected
    selection = (
        "docs/onyx/checkpoints/phase5-exit-candidate-v2/cumulative-selection.json"
    )
    assert digests[selection] == EXPECTED_SELECTION
    assert candidate["independent_root"]["sha256"] == EXPECTED_ROOT
    bound, relative = ACCEPTANCE.read_text(encoding="utf-8").strip().split("  ", 1)
    assert relative == f"docs/onyx/acceptance/{ID}.md" and bound == digest(RECORD)
    run = subprocess.run(
        [
            str(ROOT / ".venv/Scripts/python.exe"),
            "-I",
            "-S",
            "-B",
            "scripts/verify_phase5_exit_candidate_v2.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    assert run.returncode == 0 and "P5_EXIT_CANDIDATE_V2_OK" in run.stdout
    payload = json.loads(run.stdout.split(" ", 1)[1])
    assert payload["independent_root_sha256"] == EXPECTED_ROOT
    assert payload["binding_count"] == 73
    assert payload["startup_closure"]["files"] == 32
    assert payload["predecessor"] == {
        "component_acceptances": 5,
        "files": 66,
        "flags_default_false": 8,
    }
    assert payload["cumulative_selection"]["expected_passed"] == 257
    assert payload["cumulative_selection"]["expected_failed"] == 0
    assert payload["cumulative_selection"]["test_files"] == 10
    assert payload["v9_acceptance_executed"] is True
    assert payload["phase6_unlocked"] is False
    return meta


if __name__ == "__main__":
    print("P5_EXIT_CANDIDATE_V2_ACCEPTANCE_OK", json.dumps(verify(), sort_keys=True))
