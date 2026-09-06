"""Verify the frozen default-off Phase 6 Live Integration V1 candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[1]
MANIFEST = "docs/onyx/checkpoints/phase6-live-integration-v1/manifest.json"
MARKER = "P6_LIVE_INTEGRATION_V1_OK"

EXPECTED_ARTIFACTS = {
    "core/phase6_live_integration_v1.py",
    "tests/test_phase6_live_integration_v1.py",
    "docs/onyx/adrs/ADR-0016-phase6-live-integration-v1.md",
    (
        "docs/onyx/checkpoints/phase6-live-integration-v1/"
        "PHASE6_LIVE_INTEGRATION_V1_CHECKPOINT.md"
    ),
    "scripts/verify_phase6_live_integration_v1.py",
}
FROZEN_ANCHORS = {
    "core/phase6_agentic_core_v6.py": (
        "38f68d7dd8eb04fe7c9caa956db5a52d0a96426bab6a45f07b96e67e45d8001a"
    ),
    "core/phase5_integration_v3.py": (
        "52d48c121da485c024811e6cd3fafbabaed971175d7cb41ad23358c5c2879b0d"
    ),
    "core/llm_client.py": (
        "e5c0f805e0d10a07e38054316fb9c6423409190cfa0f48bc39694e65c6a4e417"
    ),
    "core/missions.py": (
        "fe2074eb132c09beecb9f13c5151659e745cf888676c4244c037e0a7ed7f2fe5"
    ),
    "main.py": ("6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712"),
    "ui.py": ("e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b"),
    "dashboard/server.py": (
        "4d3142dc9c6a78cfe76f804de2b154334da2d7790484783a993babc92300bae1"
    ),
    "docs/onyx/checkpoints/phase6-agentic-core-v6/manifest.json": (
        "cedea0a3ed3bf0c1ed069c589e2eb78035caa58886ced0c69658ac71d7bb4a15"
    ),
    "docs/onyx/checkpoints/phase5-integration-v3/manifest.json": (
        "9ee4b34fc87a6be5e123c83c7dd244804498891eb175b5201cf074475ff0d167"
    ),
}


class VerificationError(RuntimeError):
    """Candidate evidence or a frozen dependency is inconsistent."""


def _canonical_path(relative: str) -> Path:
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or "\x00" in relative
    ):
        raise VerificationError("artifact path is not canonical")
    parsed = PurePosixPath(relative)
    if (
        parsed.is_absolute()
        or str(parsed) != relative
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise VerificationError("artifact path is not canonical")
    path = PROJECT.joinpath(*parsed.parts)
    if not path.is_file() or path.is_symlink():
        raise VerificationError(f"artifact is missing or linked: {relative}")
    try:
        path.resolve(strict=True).relative_to(PROJECT.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise VerificationError(f"artifact escapes project: {relative}") from exc
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
            raise VerificationError("artifact digest is malformed")
        records.append(f"{relative}\0{digest}")
    return hashlib.sha256("\n".join(sorted(records)).encode("utf-8")).hexdigest()


def verify() -> dict[str, object]:
    try:
        manifest = json.loads(_canonical_path(MANIFEST).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError("manifest is unreadable") from exc
    if (
        type(manifest) is not dict
        or manifest.get("schema") != "OnyxPhase6LiveIntegrationCheckpoint.v1"
        or manifest.get("status") != "candidate_default_off_not_live"
    ):
        raise VerificationError("manifest identity or status is invalid")
    activation = manifest.get("activation")
    if activation != {
        "feature_flag": "ONYX_PHASE6_LIVE_INTEGRATION_V1",
        "enabled_value": "true",
        "default": "off",
        "live_wiring": False,
    }:
        raise VerificationError("activation contract is invalid")
    raw_artifacts = manifest.get("artifacts")
    if type(raw_artifacts) is not list:
        raise VerificationError("manifest artifacts are invalid")
    artifacts: dict[str, str] = {}
    for item in raw_artifacts:
        if type(item) is not dict or set(item) != {"path", "bytes", "sha256"}:
            raise VerificationError("artifact record is invalid")
        relative = item["path"]
        if relative in artifacts:
            raise VerificationError("artifact path is duplicated")
        path = _canonical_path(relative)
        if item["bytes"] != path.stat().st_size:
            raise VerificationError(f"artifact size drifted: {relative}")
        digest = _digest(relative)
        if item["sha256"] != digest:
            raise VerificationError(f"artifact digest drifted: {relative}")
        artifacts[relative] = digest
    if set(artifacts) != EXPECTED_ARTIFACTS:
        raise VerificationError("artifact closure is incomplete")
    root = _artifact_root(artifacts)
    if manifest.get("artifact_root_sha256") != root:
        raise VerificationError("artifact root mismatch")
    for relative, expected in FROZEN_ANCHORS.items():
        if _digest(relative) != expected:
            raise VerificationError(f"frozen dependency drifted: {relative}")
    for relative in ("main.py", "ui.py", "dashboard/server.py"):
        source = _canonical_path(relative).read_text(encoding="utf-8")
        if "phase6_live_integration_v1" in source:
            raise VerificationError(f"live wiring exists in {relative}")
    source = _canonical_path("core/phase6_live_integration_v1.py").read_text(
        encoding="utf-8"
    )
    required = (
        'FEATURE_FLAG = "ONYX_PHASE6_LIVE_INTEGRATION_V1"',
        "if not gate.enabled:",
        "return None",
        "from core.llm_client import call_llm_text",
        "Phase5IntegrationV3",
        "permission_hook",
        "catalog_read",
        "DisabledExternalAgentAdapterV1",
        "BLOCKED_BY_POLICY",
        "WAITING_FOR_PHASE5",
    )
    missing = [item for item in required if item not in source]
    if missing:
        raise VerificationError(f"integration contract is missing: {missing[0]}")
    forbidden = (
        "requests.",
        "subprocess.",
        "selenium",
        "playwright",
        "browser_control",
    )
    present = [item for item in forbidden if item in source]
    if present:
        raise VerificationError(f"unexpected direct capability: {present[0]}")
    external = manifest.get("external_agent")
    if external != {
        "adapter_id": "external_agent_disabled",
        "status": "blocked_by_access",
        "live": False,
    }:
        raise VerificationError("external-agent boundary is invalid")
    return {
        "marker": MARKER,
        "artifact_root_sha256": root,
        "artifacts": len(artifacts),
        "frozen_anchors": len(FROZEN_ANCHORS),
        "live_wiring": False,
        "external_agent": "blocked_by_access",
    }


if __name__ == "__main__":
    result = verify()
    print(MARKER)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
