"""Verify external E6 acceptance of Onyx Live Activation V11 C001."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ID = "VE-ONYX-LIVE-ACTIVATION-V11-C001-E6-001"
CANDIDATE = ROOT / "docs/onyx/checkpoints/onyx-live-activation-v11/manifest.json"
RECORD = ROOT / f"docs/onyx/acceptance/{ID}.md"
METADATA = RECORD.with_suffix(".manifest.json")
SOURCE = (
    ROOT / "docs/onyx/VE-SOURCE-ONYX-LIVE-ACTIVATION-V11-C001-E6-001.sha256"
)
ARTIFACTS = (
    ROOT / "docs/onyx/VE-ARTIFACTS-ONYX-LIVE-ACTIVATION-V11-C001-E6-001.sha256"
)
ACCEPTANCE = (
    ROOT / "docs/onyx/VE-ACCEPTANCE-ONYX-LIVE-ACTIVATION-V11-C001-E6-001.sha256"
)
EXPECTED_MANIFEST = "95aa2e7430db568abda4835ee88648a47a4848b2170649898be39f35ddd8fe8e"
EXPECTED_ROOT = "3c196ad5a9483675264ae3f04380cd037761c04c77c2fa523fc4867a09d9d935"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_sha(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        value, relative = line.split("  ", maxsplit=1)
        assert len(value) == 64 and relative not in result
        result[relative] = value
    return result


def run_gate(*arguments: str, timeout: int = 300) -> str:
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
    assert metadata["scope"] == "windows-c001-default-off-no-live-or-shortcut-write"
    assert metadata["results"] == {
        "candidate": 18,
        "external": 8,
        "v10_regression": 33,
        "hud_v8": 7,
        "files": 19,
        "seams": 37,
        "physical_smoke": 1,
        "network_calls": 0,
        "shortcut_writes": 0,
    }
    rows = sorted(candidate["files"], key=lambda record: record["path"])
    material = "".join(
        f"{record['path']}\0{record['sha256']}\n" for record in rows
    ).encode()
    assert hashlib.sha256(material).hexdigest() == EXPECTED_ROOT
    for record in rows:
        assert digest(ROOT / record["path"]) == record["sha256"]

    source = parse_sha(SOURCE)
    assert source == {record["path"]: record["sha256"] for record in rows}
    for relative, expected in source.items():
        assert digest(ROOT / relative) == expected
    assert parse_sha(ACCEPTANCE) == {
        f"docs/onyx/acceptance/{ID}.md": digest(RECORD)
    }
    for item in metadata["new_artifacts"]:
        assert digest(ROOT / item["path"]) == item["sha256"]

    artifacts = parse_sha(ARTIFACTS)
    expected_artifacts = {
        f"docs/onyx/acceptance/{ID}.md",
        f"docs/onyx/acceptance/{ID}.manifest.json",
        "docs/onyx/VE-SOURCE-ONYX-LIVE-ACTIVATION-V11-C001-E6-001.sha256",
        "docs/onyx/VE-ACCEPTANCE-ONYX-LIVE-ACTIVATION-V11-C001-E6-001.sha256",
        "scripts/verify_onyx_live_activation_v11_c001_acceptance.py",
        "tests/test_onyx_live_activation_v11_c001_acceptance.py",
    }
    assert set(artifacts) == expected_artifacts
    for relative, expected in artifacts.items():
        assert digest(ROOT / relative) == expected

    candidate_gate = run_gate(
        "-I", "-S", "scripts/verify_onyx_live_activation_v11.py"
    )
    smoke_gate = run_gate(
        "-I",
        "-S",
        "scripts/verify_onyx_live_activation_v11_c001_physical_smoke.py",
    )
    external_temp = Path(
        tempfile.mkdtemp(prefix=".pytest-onyx-live-v11-c001-e6-", dir=ROOT)
    )
    try:
        external_gate = run_gate(
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(external_temp),
            "tests/test_onyx_live_activation_v11_c001_acceptance.py",
        )
    finally:
        shutil.rmtree(external_temp, ignore_errors=True)
    assert "ONYX_LIVE_ACTIVATION_V11_C001_CANDIDATE_OK" in candidate_gate
    assert "ONYX_LIVE_ACTIVATION_V11_C001_PHYSICAL_SMOKE_OK" in smoke_gate
    assert "8 passed" in external_gate
    return {
        "acceptance_id": ID,
        "candidate_manifest_sha256": EXPECTED_MANIFEST,
        "evidence_root_sha256": EXPECTED_ROOT,
        "findings": metadata["findings"],
        "gates": [18, 8, 33, 7, 1],
        "live": False,
        "shortcut_writes": 0,
    }


if __name__ == "__main__":
    print(
        "ONYX_LIVE_ACTIVATION_V11_C001_ACCEPTANCE_OK",
        json.dumps(verify(), sort_keys=True),
    )
