"""Reproduce the frozen Phase 6 Live Wiring V2 candidate closure."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from core import phase6_live_wiring_v2 as wiring  # noqa: E402


MANIFEST = PROJECT / "docs/onyx/checkpoints/phase6-live-wiring-v2/manifest.json"
ARTIFACT_PATHS = (
    "core/phase6_live_wiring_v2.py",
    "tests/test_phase6_live_wiring_v2.py",
    "docs/onyx/adrs/ADR-0027-phase6-live-wiring-v2.md",
    ("docs/onyx/checkpoints/phase6-live-wiring-v2/PHASE6_LIVE_WIRING_V2_CHECKPOINT.md"),
    "scripts/verify_phase6_live_wiring_v2.py",
)


class Phase6LiveWiringV2VerificationError(RuntimeError):
    """The frozen V2 candidate does not reproduce."""


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _root(records: dict[str, str]) -> str:
    rows = [f"{path}\0{digest}" for path, digest in records.items()]
    return hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()


def _strict_json(path: Path) -> dict[str, object]:
    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase6LiveWiringV2VerificationError(
                    f"duplicate manifest key: {key}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=no_duplicates,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Phase6LiveWiringV2VerificationError(
            "candidate manifest is unreadable"
        ) from exc
    if type(value) is not dict:
        raise Phase6LiveWiringV2VerificationError(
            "candidate manifest must be an object"
        )
    return value


def verify() -> dict[str, object]:
    manifest = _strict_json(MANIFEST)
    if (
        manifest.get("schema") != "OnyxPhase6LiveWiringCheckpoint.v2"
        or manifest.get("candidate") != wiring.CANDIDATE
        or manifest.get("status") != "candidate_default_off_not_live"
        or manifest.get("feature_flag") != wiring.FEATURE_FLAG
        or manifest.get("enabled_value") != "true"
        or manifest.get("default_off") is not True
        or manifest.get("live_wiring") is not False
    ):
        raise Phase6LiveWiringV2VerificationError("candidate manifest contract drift")
    artifacts = manifest.get("artifacts")
    if type(artifacts) is not list or len(artifacts) != len(ARTIFACT_PATHS):
        raise Phase6LiveWiringV2VerificationError(
            "candidate artifact closure is incomplete"
        )
    observed: dict[str, str] = {}
    for index, record in enumerate(artifacts):
        if (
            type(record) is not dict
            or set(record) != {"path", "bytes", "sha256"}
            or record.get("path") != ARTIFACT_PATHS[index]
            or type(record.get("bytes")) is not int
            or type(record.get("sha256")) is not str
        ):
            raise Phase6LiveWiringV2VerificationError("candidate artifact record drift")
        path = PROJECT / record["path"]
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != record["bytes"]
        ):
            raise Phase6LiveWiringV2VerificationError(
                f"candidate artifact unavailable: {record['path']}"
            )
        actual = _digest(path)
        if actual != record["sha256"]:
            raise Phase6LiveWiringV2VerificationError(
                f"candidate artifact drift: {record['path']}"
            )
        observed[record["path"]] = actual
    artifact_root = _root(observed)
    if artifact_root != manifest.get("artifact_root_sha256"):
        raise Phase6LiveWiringV2VerificationError("candidate artifact root drift")
    component_root = wiring._verify_component_roots(PROJECT)
    if len(wiring.COMPONENT_ACCEPTANCE_ROOTS) != 15 or component_root != manifest.get(
        "component_acceptance_root_sha256"
    ):
        raise Phase6LiveWiringV2VerificationError("accepted component closure drift")
    if (
        wiring.create_phase6_live_wiring_v2(gate=wiring.LiveWiringV2FeatureGate(False))
        is not None
    ):
        raise Phase6LiveWiringV2VerificationError(
            "default-off factory constructed a controller"
        )
    source = (PROJECT / "core/phase6_live_wiring_v2.py").read_text(encoding="utf-8")
    required = (
        'FEATURE_FLAG: Final = "ONYX_PHASE6_LIVE_WIRING_V2"',
        'PATCHED_CONTROLLER_SEAMS = ("_create_session", "_detach_session")',
        "AdapterStatusV1.BLOCKED_BY_POLICY",
        "return self.router.plan(command, now_ms=now_ms)",
        "create_unified_command_router_v1",
    )
    if any(value not in source for value in required):
        raise Phase6LiveWiringV2VerificationError("candidate source invariant drift")
    for relative in (
        "main.py",
        "ui.py",
        "dashboard/server.py",
        "scripts/launch_onyx_live_v12.pyw",
    ):
        if wiring.FEATURE_FLAG in (PROJECT / relative).read_text(encoding="utf-8"):
            raise Phase6LiveWiringV2VerificationError(
                f"candidate leaked into live surface: {relative}"
            )
    return {
        "candidate": wiring.CANDIDATE,
        "artifacts": len(observed),
        "artifact_root_sha256": artifact_root,
        "component_roots": len(wiring.COMPONENT_ACCEPTANCE_ROOTS),
        "component_acceptance_root_sha256": component_root,
        "default_off": True,
        "live_wiring": False,
        "provider_calls": 0,
        "process_calls": 0,
        "network_calls": 0,
        "live_calls": 0,
        "phase6_exit": False,
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, sort_keys=True))
    print("P6_LIVE_WIRING_V2_CANDIDATE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
