"""Verify the blocked, default-off Activation V10 composition candidate."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv/Scripts/python.exe"
FROZEN = {
    "core/onyx_live_activation_v9.py": (
        "deb26314ef3871cb12fc8e3cee936f88e385122fad242c830580421ccb22a9d2"
    ),
    "docs/onyx/checkpoints/onyx-live-activation-v9/manifest.json": (
        "38de625b7725dab7aa9c7906f7f3164687f1f20a0cca6e683fe64145bb53142a"
    ),
    "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V9-E6-001.md": (
        "91a3613df269d1fe222c437b92b0d3022f3f2a603ae9689a951e63e0c4e4f0ec"
    ),
    "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V9-E6-001.manifest.json": (
        "bb8a3e88b6db05b548a306aba3e2c09bdd3b0f760777d34a64326e8820743cbd"
    ),
    "core/phase6_live_wiring_v1.py": (
        "a658f430c10bb992724ad7bbd2ddae94b3c83f8893608fe724b241302b55d55f"
    ),
    "docs/onyx/checkpoints/phase6-live-wiring-v1/manifest.json": (
        "d98cdd73ae056e3afe5eac2976565d8b301fb1410a8b0498f04c6f7e8c2db6ee"
    ),
    "docs/onyx/acceptance/VE-P6-LIVE-WIRING-V1-E6-001.md": (
        "51c542420b55f58409fba1b9a5efe753fb9aabdfebd1bc5e3ab2b9abf1f15dd7"
    ),
    "docs/onyx/acceptance/VE-P6-LIVE-WIRING-V1-E6-001.manifest.json": (
        "8e4f139033bd8450a7f4c3c325363e57166bb7d0de3d5f5e6baf4f6817e8088c"
    ),
    "docs/onyx/checkpoints/phase5-exit-candidate-v2/manifest.json": (
        "b2cf8d781fc1f72a375be444c24ad74c4e59b910adab765a48c7c7b59ae15d2b"
    ),
    "docs/onyx/acceptance/VE-P5-EXIT-CANDIDATE-V2-E6-001.md": (
        "052426cc0d62aad20af4ee8f1810d0729698fb0dd74e95cb76c1bbf0f50404d3"
    ),
    "docs/onyx/acceptance/VE-P5-EXIT-CANDIDATE-V2-E6-001.manifest.json": (
        "db41fff1130f4991f6e6f3da9811f6a8877a408a17ffef809f41eb128704392c"
    ),
    "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
    "ui.py": "e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b",
}
HUD_V7_ACCEPTED = {
    "core/onyx_hud_orb_v7.py": (
        "31fd7d0df7413ac9dbba3db463de28390bdfaa75e2173dae54c04dfd82a6c150"
    ),
    "docs/onyx/checkpoints/hud-orb-v7-candidate/manifest.json": (
        "3be0988e98b4f8222751686386041094606da4366c8111453b381d4cf47c84f2"
    ),
    "docs/onyx/acceptance/VE-HUD-ORB-V7-C003-E6-001.md": (
        "d275d7166de989dcbf57a8ad9d2c217dd0f52ff433e3ce2ba9301333cb73bfed"
    ),
    "docs/onyx/acceptance/VE-HUD-ORB-V7-C003-E6-001.manifest.json": (
        "8e25a01d1701a5effc9d49c8ceee6958e2d00e5926c582612894332e9fc2fb73"
    ),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> None:
    for relative, expected in FROZEN.items():
        if digest(ROOT / relative) != expected:
            raise RuntimeError(f"accepted predecessor drift: {relative}")

    v9 = json.loads(
        (
            ROOT
            / "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V9-E6-001.manifest.json"
        ).read_text(encoding="utf-8")
    )
    wiring = json.loads(
        (
            ROOT / "docs/onyx/acceptance/VE-P6-LIVE-WIRING-V1-E6-001.manifest.json"
        ).read_text(encoding="utf-8")
    )
    phase5 = json.loads(
        (
            ROOT / "docs/onyx/acceptance/VE-P5-EXIT-CANDIDATE-V2-E6-001.manifest.json"
        ).read_text(encoding="utf-8")
    )
    for envelope in (v9, wiring, phase5):
        if envelope.get("decision") != "accepted" or envelope.get("findings") != {
            "P0": 0,
            "P1": 0,
            "P2": 0,
            "P3": 0,
        }:
            raise RuntimeError("accepted predecessor envelope is invalid")
    if phase5.get("raw_historical") != {
        "passed": 275,
        "failed": 2,
        "scope": "obsolete-v1-startup-discovery-only",
    }:
        raise RuntimeError("Phase5 C2 historical envelope drift")
    if phase5.get("phase6_unlocked") is not False:
        raise RuntimeError("Phase5 C2 must not imply Phase6 unlock")
    for relative, expected in HUD_V7_ACCEPTED.items():
        path = ROOT / relative
        if not path.is_file() or digest(path) != expected:
            raise RuntimeError(f"accepted HUD V7 C003 drift: {relative}")
    hud_e6 = json.loads(
        (
            ROOT / "docs/onyx/acceptance/VE-HUD-ORB-V7-C003-E6-001.manifest.json"
        ).read_text(encoding="utf-8")
    )
    if (
        hud_e6.get("decision") != "accepted"
        or hud_e6.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or hud_e6.get("candidate_manifest_sha256")
        != HUD_V7_ACCEPTED["docs/onyx/checkpoints/hud-orb-v7-candidate/manifest.json"]
        or hud_e6.get("activation", {}).get("live_activated") is not False
    ):
        raise RuntimeError("accepted HUD V7 C003 envelope is invalid")

    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    base_temp = Path(
        tempfile.mkdtemp(prefix=".pytest-onyx-live-v10-verifier-", dir=ROOT)
    )
    try:
        result = subprocess.run(
            [
                str(PYTHON),
                "-B",
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "--basetemp",
                str(base_temp),
                "tests/test_onyx_live_activation_v10.py",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
        )
    finally:
        shutil.rmtree(base_temp, ignore_errors=True)
    if result.returncode or "33 passed" not in result.stdout:
        raise RuntimeError(result.stdout + result.stderr)
    smoke = subprocess.run(
        [
            str(PYTHON),
            "-I",
            "-S",
            "-B",
            "scripts/verify_onyx_live_activation_v10_c003_physical_smoke.py",
        ],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=240,
        check=False,
    )
    if (
        smoke.returncode
        or "ONYX_LIVE_ACTIVATION_V10_C003_PHYSICAL_SMOKE_OK" not in smoke.stdout
    ):
        raise RuntimeError(smoke.stdout + smoke.stderr)
    print("ONYX_LIVE_ACTIVATION_V10_C003_CANDIDATE_OK")
    print(
        "focused=33/33 predecessors=v9-e6,wiring-v1-e6,phase5-c2-e6 "
        "hud_v7_contract=real-c003 hud_v7_e6=accepted "
        "preflight=accepted-before-live-host hud_memory_spoof=deny "
        "cmd_arbitrary_cwd=pass onboarding=secure-unknown-owner-ready "
        "physical_smoke=pass configured_shortcut=refresh "
        "network_calls=0 shortcut_writes=0 live_activation=not_performed"
    )


if __name__ == "__main__":
    run()
