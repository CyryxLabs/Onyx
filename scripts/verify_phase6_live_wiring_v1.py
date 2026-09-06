"""Verify the frozen default-off Phase 6 Live Wiring V1 candidate."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[1]
MANIFEST = "docs/onyx/checkpoints/phase6-live-wiring-v1/manifest.json"
MARKER = "P6_LIVE_WIRING_V1_OK"

EXPECTED_ARTIFACTS = {
    "core/phase6_live_wiring_v1.py",
    "tests/test_phase6_live_wiring_v1.py",
    "docs/onyx/adrs/ADR-0019-phase6-live-wiring-v1.md",
    ("docs/onyx/checkpoints/phase6-live-wiring-v1/PHASE6_LIVE_WIRING_V1_CHECKPOINT.md"),
    "scripts/verify_phase6_live_wiring_v1.py",
}
FROZEN_ANCHORS = {
    "core/phase6_live_integration_v2.py": (
        "e3194a0d8e206d33218bc8291cbd518788e8dfb3931adfd2f067908655d409b5"
    ),
    "docs/onyx/checkpoints/phase6-live-integration-v2/manifest.json": (
        "d02b265e5d67c98fb9dd2e868440ead39360187bdd95592fcf89a44f4448833a"
    ),
    "docs/onyx/acceptance/VE-P6-LIVE-INTEGRATION-V2-E6-001.md": (
        "cfe947b7c81bbf7ad0fb6e75469c473c0d69c8b1b813d89c08ca1c729dd9f687"
    ),
    "docs/onyx/VE-ACCEPTANCE-P6-LIVE-INTEGRATION-V2-E6-001.sha256": (
        "4c85d302559f8b469ad7441951996496dd8bdd9b08743eb0b9f02e8f317de9c7"
    ),
    "core/phase6_agentic_core_v6.py": (
        "38f68d7dd8eb04fe7c9caa956db5a52d0a96426bab6a45f07b96e67e45d8001a"
    ),
    "docs/onyx/checkpoints/phase6-agentic-core-v6/manifest.json": (
        "cedea0a3ed3bf0c1ed069c589e2eb78035caa58886ced0c69658ac71d7bb4a15"
    ),
    "core/phase5_integration_v3.py": (
        "52d48c121da485c024811e6cd3fafbabaed971175d7cb41ad23358c5c2879b0d"
    ),
    "docs/onyx/checkpoints/phase5-integration-v3/manifest.json": (
        "9ee4b34fc87a6be5e123c83c7dd244804498891eb175b5201cf074475ff0d167"
    ),
    "core/onyx_live_activation_v7.py": (
        "906c7c0e31cb5efc28e5357bb158545e903d65ff1f160b3899bc3e2fb3c1dc77"
    ),
    "docs/onyx/checkpoints/onyx-live-activation-v7/manifest.json": (
        "312d6654f3423f16f4b36f435638920836994bd56c3e9a8766a086e2c6d647da"
    ),
    "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V7-E6-001.md": (
        "8438769b1b597b0d66174db0c73d50a9577702c5957ba6ff24b55315d11aedb5"
    ),
    "docs/onyx/VE-ACCEPTANCE-ONYX-LIVE-ACTIVATION-V7-E6-001.sha256": (
        "40f0ed22791f66264860690c1bf3329b4f2f783a9cd51bf07c0e91f619025e61"
    ),
    "scripts/launch_onyx_live_v7.pyw": (
        "a5dae76af4b09af90aa89b3638e2329fbed8c79a50fbcafa0a6179f38d82c531"
    ),
    "scripts/launch_onyx_live_v7_active.cmd": (
        "c3a144c6913c6c77aed0752d44913966b4b3eabf1c014e20761c8dec1adea1ae"
    ),
    "scripts/launch_onyx_live_v7_rollback.cmd": (
        "b6312849e2687fe152c5ae2667ce130fac1475ae2ca2cb2e53e53270c7777e29"
    ),
    "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
    "ui.py": "e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b",
    "dashboard/server.py": (
        "4d3142dc9c6a78cfe76f804de2b154334da2d7790484783a993babc92300bae1"
    ),
}


class LiveWiringV1VerificationError(RuntimeError):
    """Candidate evidence or a frozen dependency is inconsistent."""


def _canonical_path(relative: str) -> Path:
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or "\x00" in relative
    ):
        raise LiveWiringV1VerificationError("artifact path is not canonical")
    parsed = PurePosixPath(relative)
    if (
        parsed.is_absolute()
        or str(parsed) != relative
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise LiveWiringV1VerificationError("artifact path is not canonical")
    path = PROJECT.joinpath(*parsed.parts)
    if not path.is_file() or path.is_symlink():
        raise LiveWiringV1VerificationError(
            f"artifact is missing or linked: {relative}"
        )
    try:
        path.resolve(strict=True).relative_to(PROJECT.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise LiveWiringV1VerificationError(
            f"artifact escapes project: {relative}"
        ) from exc
    return path


def _digest(relative: str) -> str:
    return hashlib.sha256(_canonical_path(relative).read_bytes()).hexdigest()


def _artifact_root(artifacts: dict[str, str]) -> str:
    records = []
    for relative, digest in artifacts.items():
        _canonical_path(relative)
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise LiveWiringV1VerificationError("artifact digest is malformed")
        records.append(f"{relative}\0{digest}")
    return hashlib.sha256("\n".join(sorted(records)).encode("utf-8")).hexdigest()


def _function_args(
    tree: ast.Module, *, class_name: str | None, function_name: str
) -> tuple[list[str], list[str]]:
    body: list[ast.stmt] = tree.body
    if class_name is not None:
        classes = [
            node
            for node in body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        ]
        if len(classes) != 1:
            raise LiveWiringV1VerificationError(
                f"class is missing or duplicated: {class_name}"
            )
        body = classes[0].body
    functions = [
        node
        for node in body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]
    if len(functions) != 1:
        raise LiveWiringV1VerificationError(
            f"function is missing or duplicated: {function_name}"
        )
    function = functions[0]
    if function.args.vararg is not None or function.args.kwarg is not None:
        raise LiveWiringV1VerificationError(
            f"variadic operational seam: {function_name}"
        )
    return (
        [argument.arg for argument in function.args.args],
        [argument.arg for argument in function.args.kwonlyargs],
    )


def _live_paths() -> list[str]:
    paths = ["main.py", "ui.py"]
    suffixes = {".py", ".pyw", ".cmd", ".ps1", ".iss", ".js", ".html", ".qml"}
    for root_name in ("dashboard", "runtime", "packaging", "qml"):
        root = PROJECT / root_name
        if root.is_dir():
            paths.extend(
                path.relative_to(PROJECT).as_posix()
                for path in sorted(root.rglob("*"))
                if path.is_file() and path.suffix.lower() in suffixes
            )
    scripts = PROJECT / "scripts"
    paths.extend(
        path.relative_to(PROJECT).as_posix()
        for path in sorted(scripts.glob("launch_*"))
        if path.is_file() and path.suffix.lower() in suffixes
    )
    return sorted(set(paths))


def verify() -> dict[str, object]:
    try:
        manifest = json.loads(_canonical_path(MANIFEST).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveWiringV1VerificationError("manifest is unreadable") from exc
    if (
        type(manifest) is not dict
        or manifest.get("schema") != "OnyxPhase6LiveWiringCheckpoint.v1"
        or manifest.get("status") != "candidate_default_off_not_live"
        or manifest.get("activation")
        != {
            "feature_flag": "ONYX_PHASE6_LIVE_WIRING_V1",
            "enabled_value": "true",
            "default": "off",
            "live_wiring": False,
            "auto_install": False,
        }
    ):
        raise LiveWiringV1VerificationError(
            "manifest identity or activation is invalid"
        )
    entries = manifest.get("artifacts")
    if type(entries) is not list:
        raise LiveWiringV1VerificationError("manifest artifacts are invalid")
    artifacts: dict[str, str] = {}
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "bytes", "sha256"}:
            raise LiveWiringV1VerificationError("artifact record is invalid")
        relative = entry["path"]
        if relative in artifacts:
            raise LiveWiringV1VerificationError("artifact path is duplicated")
        path = _canonical_path(relative)
        if path.stat().st_size != entry["bytes"]:
            raise LiveWiringV1VerificationError(
                f"artifact byte count drifted: {relative}"
            )
        digest = _digest(relative)
        if entry["sha256"] != digest:
            raise LiveWiringV1VerificationError(f"artifact digest drifted: {relative}")
        artifacts[relative] = digest
    if set(artifacts) != EXPECTED_ARTIFACTS:
        raise LiveWiringV1VerificationError("artifact closure is incomplete")
    root = _artifact_root(artifacts)
    if manifest.get("artifact_root_sha256") != root:
        raise LiveWiringV1VerificationError("artifact root mismatch")

    for relative, expected in FROZEN_ANCHORS.items():
        if _digest(relative) != expected:
            raise LiveWiringV1VerificationError(
                f"frozen dependency drifted: {relative}"
            )

    live_paths = _live_paths()
    for relative in live_paths:
        try:
            source = _canonical_path(relative).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "phase6_live_wiring_v1" in source or "ONYX_PHASE6_LIVE_WIRING_V1" in source:
            raise LiveWiringV1VerificationError(
                f"candidate entered a live surface: {relative}"
            )

    source = _canonical_path("core/phase6_live_wiring_v1.py").read_text(
        encoding="utf-8"
    )
    required = (
        'FEATURE_FLAG = "ONYX_PHASE6_LIVE_WIRING_V1"',
        'PATCHED_SEAMS = ("__init__", "_start_phase5_session", "_stop_phase5_session")',
        'PROTECTED_SEAMS = ("_execute_tool", "_run_live_loop", "_send_realtime")',
        "_CORE_FACTORY = agentic_v6.create_phase6_agentic_core_v6",
        "_INTEGRATION_FACTORY = integration_v2.create_phase6_live_integration_v2",
        "identity = LiveWiringIdentityV1.from_activation(activation)",
        "session.close()",
        'originals["_stop_phase5_session"](instance, reason)',
        '"identity_digest": identity.digest',
        "if not gate.enabled:",
        "return None",
    )
    missing = [value for value in required if value not in source]
    if missing:
        raise LiveWiringV1VerificationError(f"wiring contract is missing: {missing[0]}")
    if source.index("session.close()") > source.index(
        'originals["_stop_phase5_session"](instance, reason)'
    ):
        raise LiveWiringV1VerificationError("teardown ordering is not fail-closed")
    forbidden = (
        "import requests",
        "import httpx",
        "import socket",
        "import subprocess",
        "playwright",
        "selenium",
        "browser_control",
    )
    present = [value for value in forbidden if value in source]
    if present:
        raise LiveWiringV1VerificationError(
            f"unexpected direct capability: {present[0]}"
        )

    tree = ast.parse(source, filename="core/phase6_live_wiring_v1.py")
    positional, keywords = _function_args(
        tree, class_name=None, function_name="create_phase6_live_wiring_v1"
    )
    if positional or keywords != ["gate", "activation", "state_root"]:
        raise LiveWiringV1VerificationError("operational factory is not sealed")
    identities = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "LiveWiringIdentityV1"
    ]
    if len(identities) != 1:
        raise LiveWiringV1VerificationError("wiring identity class is invalid")
    fields = [
        node.target.id
        for node in identities[0].body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    ]
    if fields != ["workspace_id", "account_id", "profile_id", "principal_id"]:
        raise LiveWiringV1VerificationError("wiring identity fields diverged")

    return {
        "marker": MARKER,
        "artifact_root_sha256": root,
        "artifacts": len(artifacts),
        "frozen_anchors": len(FROZEN_ANCHORS),
        "identity_fields": len(fields),
        "patched_seams": 3,
        "protected_seams": 3,
        "live_files_checked": len(live_paths),
        "default_off": True,
        "live_wiring": False,
        "phase6_exit": False,
    }


if __name__ == "__main__":
    result = verify()
    print(MARKER)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
