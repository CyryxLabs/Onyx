from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (
    ROOT / "docs/onyx/acceptance/VE-ADVANCED-OPS-V21-001.manifest.json"
)
PREDECESSOR = ROOT / "docs/onyx/acceptance/VE-ADVANCED-OPS-V20-001.manifest.json"
V19 = ROOT / "docs/onyx/acceptance/VE-ADVANCED-OPS-V19-001.manifest.json"


def test_advanced_operations_source_manifest_authenticates_exact_files() -> None:
    evidence = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert evidence["schema"] == "onyx.advanced-operations-source-acceptance.v3"
    assert evidence["status"] == "source_candidate"
    assert evidence["predecessor"] == {
        "path": "docs/onyx/acceptance/VE-ADVANCED-OPS-V20-001.manifest.json",
        "sha256": hashlib.sha256(PREDECESSOR.read_bytes()).hexdigest(),
    }
    entries = evidence["files"]
    assert [item["path"] for item in entries] == sorted(
        item["path"] for item in entries
    )
    assert len(entries) == len({item["path"] for item in entries}) == 18
    payload = bytearray(
        (
            evidence["domain"]
            + "\0"
            + evidence["predecessor"]["sha256"]
            + "\n"
        ).encode()
    )
    for item in entries:
        path = ROOT / item["path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == item["sha256"]
        payload.extend(f"{item['path']}\0{digest}\n".encode())
    assert hashlib.sha256(payload).hexdigest() == evidence["root_sha256"]


def test_v21_preserves_exact_v20_source_manifest() -> None:
    evidence = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    assert evidence["schema"] == "onyx.advanced-operations-source-acceptance.v3"
    assert evidence["predecessor"] == {
        "path": "docs/onyx/acceptance/VE-ADVANCED-OPS-V19-001.manifest.json",
        "sha256": hashlib.sha256(V19.read_bytes()).hexdigest(),
    }
    entries = evidence["files"]
    assert len(entries) == len({item["path"] for item in entries}) == 2
    payload = bytearray(
        (
            evidence["domain"]
            + "\0"
            + evidence["predecessor"]["sha256"]
            + "\n"
        ).encode()
    )
    for item in entries:
        assert len(item["sha256"]) == 64
        payload.extend(f"{item['path']}\0{item['sha256']}\n".encode())
    assert hashlib.sha256(payload).hexdigest() == evidence["root_sha256"]


def test_advanced_operations_source_policy_preserves_host_authority() -> None:
    policy = json.loads(MANIFEST.read_text(encoding="utf-8"))["policy"]
    assert policy == {
        "accepted_runtime_engine_replaced": False,
        "phase6_authority_replaced": False,
        "voice_provider_or_voice_changed": False,
        "mutable_state_inside_application_tree": False,
        "owner_private_runtime_required": True,
        "historical_v10_function_restored_after_activation": True,
        "diagnostic_credentials_are_ephemeral": True,
        "smoke_cleanup_runs_on_failure": True,
        "reference_source_or_branding_copied": False,
        "idle_screen_or_clipboard_polling_added": False,
    }
