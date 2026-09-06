"""Frozen bundle verifier for Onyx Live Activation V2."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "onyx" / "checkpoints" / "onyx-live-activation-v2" / "manifest.json"

V1 = frozenset(
    {
        "core/onyx_live_activation_v1.py",
        "scripts/launch_onyx_live_v1.pyw",
        "scripts/verify_onyx_live_activation_v1.py",
        "tests/test_onyx_live_activation_v1.py",
        "docs/onyx/checkpoints/onyx-live-activation-v1/manifest.json",
        "docs/onyx/checkpoints/onyx-live-activation-v1/ONYX_LIVE_ACTIVATION_V1_CHECKPOINT.md",
        "docs/onyx/rejections/ONYX_LIVE_ACTIVATION_V1_REJECTED.md",
    }
)
V2 = frozenset(
    {
        "core/onyx_live_activation_v2.py",
        "scripts/launch_onyx_live_v2.pyw",
        "scripts/verify_onyx_live_activation_v2.py",
        "scripts/verify_onyx_live_activation_v2_host.py",
        "tests/test_onyx_live_activation_v2.py",
        "docs/onyx/checkpoints/onyx-live-activation-v2/ONYX_LIVE_ACTIVATION_V2_CHECKPOINT.md",
    }
)
HOST = frozenset(
    {
        "main.py",
        "ui.py",
        "core/permission_broker.py",
        "dashboard/server.py",
        "scripts/launch_onyx.pyw",
    }
)
COMPONENTS = frozenset(
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
E6 = frozenset(
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


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    raise SystemExit("ONYX_LIVE_ACTIVATION_V2_VERIFY_FAIL: " + message)


def main() -> None:
    try:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"manifest unreadable ({type(exc).__name__})")
    if type(payload) is not dict or payload.get("schema") != "onyx.live-activation.v2":
        fail("manifest schema")
    for name, expected in {
        "default_off": True,
        "live_activated": False,
        "live_restart_performed": False,
        "provider_calls_performed": False,
        "credential_provisioned": False,
    }.items():
        if payload.get(name) is not expected:
            fail(name)
    entries = payload.get("files")
    if type(entries) is not list:
        fail("files")
    indexed = {}
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "role", "sha256"}:
            fail("file entry")
        relative = entry["path"]
        if relative in indexed or not isinstance(relative, str):
            fail("duplicate file")
        path = ROOT / relative
        if not path.is_file() or sha(path) != entry["sha256"]:
            fail("hash mismatch: " + relative)
        indexed[relative] = entry
    if frozenset(indexed) != V1 | V2 | HOST | COMPONENTS | E6:
        fail("closure mismatch")
    if any(indexed[path]["role"] != "rejected-v1" for path in V1):
        fail("V1 rejection role")
    if any(indexed[path]["role"] != "accepted-e6-record" for path in E6):
        fail("E6 role")

    core = (ROOT / "core" / "onyx_live_activation_v2.py").read_text(encoding="utf-8")
    launcher = (ROOT / "scripts" / "launch_onyx_live_v2.pyw").read_text(encoding="utf-8")
    worker = (ROOT / "scripts" / "verify_onyx_live_activation_v2_host.py").read_text(encoding="utf-8")
    if "onyx_live_activation_v1" in core:
        fail("V2 reaches rejected V1")
    if "os.urandom" in core:
        fail("session binding still uses entropy")
    if 'f"session-{suffix}"' not in core or 'f"trace-{suffix}"' not in core:
        fail("short monotonic binding")
    if "main.OnyxLive" not in core or "ui.MainWindow" not in core:
        fail("real host contract")
    if "value != \"1\"" not in launcher:
        fail("canonical truth comparison")
    refusal = launcher.find("ONYX_LIVE_V2_PREIMPORT_REFUSAL")
    main_import = launcher.find("import main as onyx_main")
    if refusal < 0 or main_import < 0 or refusal >= main_import:
        fail("preimport refusal boundary")
    if "Assistant" in core or "Assistant" in worker:
        fail("obsolete host stub")
    if "range(1, 65)" not in worker or "catalog_read" not in worker:
        fail("64-reconnect host evidence")
    if "bridge.kill()" not in worker or "bridge.revoke()" not in worker or '"shutdown"' not in worker:
        fail("termination evidence")
    if any(token in core for token in ("requests.", "httpx.", "socket.", "google.genai")):
        fail("network/provider dependency")

    tree = ast.parse(core, filename="core/onyx_live_activation_v2.py")
    activate = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "activate_main"
    )
    calls = [
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for statement in activate.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    ]
    try:
        preflight_index = calls.index("preflight_host")
        install_index = calls.index("install")
        start_index = calls.index("start")
    except ValueError:
        fail("activation order calls")
    if not preflight_index < install_index < start_index:
        fail("preflight/install/provision order")

    print("ONYX_LIVE_ACTIVATION_V2_OK")
    print("manifest_sha256=" + sha(MANIFEST))
    print("files=" + str(len(indexed)))


if __name__ == "__main__":
    main()
