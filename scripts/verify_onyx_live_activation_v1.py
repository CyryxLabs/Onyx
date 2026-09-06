"""Verify the frozen, default-off Onyx Live Activation V1 transition."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "onyx" / "checkpoints" / "onyx-live-activation-v1" / "manifest.json"

REQUIRED_ACCEPTANCE = frozenset(
    {
        "docs/onyx/acceptance/VE-OWNER-PROFILE-V8-E6-001.md",
        "docs/onyx/acceptance/VE-P5-INTEGRATION-V3-E6-001.md",
        "docs/onyx/acceptance/VE-HUD-ORB-V5-LIVE-E6-001.md",
        "docs/onyx/acceptance/VE-P5-RUNTIME-V10-E6-001.md",
        "docs/onyx/acceptance/VE-P51-GRANTS-R11-E6-001.md",
        "docs/onyx/acceptance/VE-P52-APPROVAL-INBOX-V15-E6-001.md",
        "docs/onyx/acceptance/VE-P53-CAPABILITY-NEXUS-V32-E6-001.md",
    }
)
REQUIRED_TRANSITION = frozenset(
    {
        "core/onyx_live_activation_v1.py",
        "scripts/launch_onyx_live_v1.pyw",
        "scripts/verify_onyx_live_activation_v1.py",
        "tests/test_onyx_live_activation_v1.py",
        "docs/onyx/checkpoints/onyx-live-activation-v1/ONYX_LIVE_ACTIVATION_V1_CHECKPOINT.md",
    }
)
REQUIRED_HOST = frozenset(
    {
        "main.py",
        "ui.py",
        "core/permission_broker.py",
        "core/prompt.txt",
        "dashboard/server.py",
        "scripts/launch_onyx.pyw",
    }
)
REQUIRED_COMPONENT = frozenset(
    {
        "core/owner_profile_v8.py",
        "core/phase5_integration_v3.py",
        "core/phase5_runtime_v10.py",
        "core/phase5_component_adapters_v3.py",
        "core/session_grants_v11.py",
        "core/approval_inbox_v15.py",
        "core/capability_nexus_v32.py",
        "qml/OnyxLiveShellV5.qml",
        "qml/components/OnyxOrbCinematicV5.qml",
        "qml/assets/onyx-orb-cinematic-v3.png",
    }
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    raise SystemExit("ONYX_LIVE_ACTIVATION_V1_VERIFY_FAIL: " + message)


def main() -> None:
    try:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"manifest unreadable ({type(exc).__name__})")
    if type(payload) is not dict or payload.get("schema") != "onyx.live-activation.v1":
        fail("manifest schema")
    if payload.get("default_off") is not True:
        fail("transition is not default-off")
    for field in ("live_activated", "live_restart_performed", "provider_calls_performed"):
        if payload.get(field) is not False:
            fail(field)

    files = payload.get("files")
    if type(files) is not list:
        fail("files list")
    indexed = {}
    for entry in files:
        if type(entry) is not dict or set(entry) != {"path", "role", "sha256"}:
            fail("file entry")
        relative = entry["path"]
        if type(relative) is not str or relative in indexed:
            fail("duplicate or invalid file path")
        path = ROOT / relative
        if not path.is_file() or sha(path) != entry["sha256"]:
            fail("hash mismatch: " + relative)
        indexed[relative] = entry

    expected = REQUIRED_ACCEPTANCE | REQUIRED_TRANSITION | REQUIRED_HOST | REQUIRED_COMPONENT
    if frozenset(indexed) != expected:
        fail("manifest closure is incomplete or has extras")
    if any(indexed[path]["role"] != "accepted-e6-record" for path in REQUIRED_ACCEPTANCE):
        fail("acceptance record role")

    transition = (ROOT / "core" / "onyx_live_activation_v1.py").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts" / "launch_onyx_live_v1.pyw").read_text(encoding="utf-8")
    if "os.environ[" in transition or "os.environ.update" in transition:
        fail("transition mutates process environment")
    if any(token in transition for token in ("requests.", "httpx.", "socket.", "google.genai")):
        fail("provider/network dependency")
    rollback = launcher.find("if _true(ROLLBACK):")
    legacy = launcher.find("if not _true(MASTER):")
    activation = launcher.find("from core.onyx_live_activation_v1 import activate_main")
    if rollback < 0 or legacy < 0 or activation < 0 or not rollback < legacy < activation:
        fail("legacy/default-off import boundary")
    if "legacy_run()" not in launcher[legacy:activation]:
        fail("legacy delegation")
    rollback_branch = launcher[rollback:legacy]
    if "os.environ.pop(MASTER, None)" not in rollback_branch or "os.environ.pop(name, None)" not in rollback_branch:
        fail("one-switch rollback does not neutralize child flags")
    if "child flag set without master" not in launcher[legacy:activation]:
        fail("partial activation is not refused")
    if "OWNER_JOURNAL_RELATIVE = Path(\"identity\")" not in transition:
        fail("dedicated owner journal path")
    if "private_control_plane_runtime_dir" not in transition:
        fail("private runtime boundary")
    if "literal English" not in transition or "Efendim" not in transition:
        fail("literal non-translatable Sir contract")

    print("ONYX_LIVE_ACTIVATION_V1_OK")
    print("manifest_sha256=" + sha(MANIFEST))
    print("files=" + str(len(indexed)))


if __name__ == "__main__":
    main()
