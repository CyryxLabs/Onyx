"""Verify external E6 acceptance of frozen Phase 6 Live Wiring V1."""

from __future__ import annotations

import hashlib
import json
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any


PROJECT = Path(__file__).resolve(strict=True).parents[1]
ACCEPTANCE_ID = "VE-P6-LIVE-WIRING-V1-E6-001"
MARKER = "P6_LIVE_WIRING_V1_ACCEPTANCE_OK"
CANDIDATE_MANIFEST = "docs/onyx/checkpoints/phase6-live-wiring-v1/manifest.json"
CANDIDATE_MANIFEST_SHA256 = (
    "d98cdd73ae056e3afe5eac2976565d8b301fb1410a8b0498f04c6f7e8c2db6ee"
)
CANDIDATE_ROOT_SHA256 = (
    "272143e6419ca5ef242916569aee8e1c18e01317ba638c10dc336e99283c0dc8"
)
ACCEPTANCE_RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
ACCEPTANCE_METADATA = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
SOURCE_MANIFEST = "docs/onyx/VE-SOURCE-P6-LIVE-WIRING-V1-E6-001.sha256"
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P6-LIVE-WIRING-V1-E6-001.sha256"
ACCEPTANCE_MANIFEST = "docs/onyx/VE-ACCEPTANCE-P6-LIVE-WIRING-V1-E6-001.sha256"

PHASE5_EXIT_RECORD = "docs/onyx/acceptance/VE-P5-EXIT-CANDIDATE-V2-E6-001.md"
PHASE5_EXIT_RECORD_SHA256 = (
    "052426cc0d62aad20af4ee8f1810d0729698fb0dd74e95cb76c1bbf0f50404d3"
)
PHASE5_EXIT_METADATA = (
    "docs/onyx/acceptance/VE-P5-EXIT-CANDIDATE-V2-E6-001.manifest.json"
)
PHASE5_EXIT_MANIFEST_SHA256 = (
    "b2cf8d781fc1f72a375be444c24ad74c4e59b910adab765a48c7c7b59ae15d2b"
)
PHASE5_EXIT_ROOT_SHA256 = (
    "2255b9a8a5315f99ab376f7f32d22ef8d39e6c2c4039a9ff77afa4ddf75e5fa6"
)

V9_MANIFEST = "docs/onyx/checkpoints/onyx-live-activation-v9/manifest.json"
V9_MANIFEST_SHA256 = "38de625b7725dab7aa9c7906f7f3164687f1f20a0cca6e683fe64145bb53142a"
V9_ROOT_SHA256 = "88307dbbf5ac2f3d1656549db94cd1293103a12b38ba8d157271f71700c5123d"
V8_MANIFEST = "docs/onyx/checkpoints/onyx-live-activation-v8/manifest.json"
V8_MANIFEST_SHA256 = "ab28f369248df1ed807aeeee15658193a533881bf68fb2268d49692b52c20392"
V8_CORE = "core/onyx_live_activation_v8.py"
V8_CORE_SHA256 = "a088d0c49851699c5486a59a4db6734b8ec81ed7c01ad821bf8a1ea1966486f4"
V7_CORE = "core/onyx_live_activation_v7.py"
V7_CORE_SHA256 = "906c7c0e31cb5efc28e5357bb158545e903d65ff1f160b3899bc3e2fb3c1dc77"

CANDIDATE_ARTIFACTS = {
    "core/phase6_live_wiring_v1.py": (
        24529,
        "a658f430c10bb992724ad7bbd2ddae94b3c83f8893608fe724b241302b55d55f",
    ),
    "tests/test_phase6_live_wiring_v1.py": (
        16916,
        "a252d4b6c1f2b0717572171bf4f2b518d105a9cf966c58d3b63c88b99730e510",
    ),
    "docs/onyx/adrs/ADR-0019-phase6-live-wiring-v1.md": (
        5683,
        "e75e2f76bbaafcb4a00841d6f487116df25a594c4ead49e175e90b720f3b70d8",
    ),
    (
        "docs/onyx/checkpoints/phase6-live-wiring-v1/"
        "PHASE6_LIVE_WIRING_V1_CHECKPOINT.md"
    ): (
        7889,
        "ace81a864b00be6ec3e51c7a7f238fc3b268b2edefd41e521cea2e8b8e2efbda",
    ),
    "scripts/verify_phase6_live_wiring_v1.py": (
        12413,
        "69f1bbf465c76b6398c7cdc44f236b01b1cddb91b69103be8b4bd2d8a7985489",
    ),
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
    V7_CORE: V7_CORE_SHA256,
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

BOUND_VERIFIERS = {
    "scripts/verify_phase6_live_wiring_v1.py": "P6_LIVE_WIRING_V1_OK",
    "scripts/verify_phase6_agentic_core_v6_acceptance.py": (
        "P6_AGENTIC_CORE_V6_ACCEPTANCE_OK"
    ),
    "scripts/verify_phase6_live_integration_v2_acceptance.py": (
        "P6_LIVE_INTEGRATION_V2_ACCEPTANCE_OK"
    ),
    "scripts/verify_phase5_exit_candidate_v2_acceptance.py": (
        "P5_EXIT_CANDIDATE_V2_ACCEPTANCE_OK"
    ),
    "scripts/verify_onyx_live_activation_v9_acceptance.py": (
        "ONYX_LIVE_ACTIVATION_V9_ACCEPTANCE_OK"
    ),
}

_REPARSE_ATTRIBUTE = 0x400
_HEX = frozenset("0123456789abcdef")


class LiveWiringV1AcceptanceError(RuntimeError):
    """The external acceptance envelope is incomplete or drifted."""


def _parts(relative: str) -> tuple[str, ...]:
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or "\x00" in relative
    ):
        raise LiveWiringV1AcceptanceError("non-canonical acceptance path")
    parsed = PurePosixPath(relative)
    if (
        parsed.is_absolute()
        or str(parsed) != relative
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise LiveWiringV1AcceptanceError("non-canonical acceptance path")
    return parsed.parts


def _path(project: Path, relative: str) -> Path:
    parts = _parts(relative)
    root = project.resolve(strict=True)
    current = project
    for index, part in enumerate(parts):
        current = current / part
        try:
            info = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise LiveWiringV1AcceptanceError(
                f"acceptance path unavailable: {relative}"
            ) from exc
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        ):
            raise LiveWiringV1AcceptanceError(f"acceptance path is linked: {relative}")
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise LiveWiringV1AcceptanceError(
                f"acceptance path escaped project: {relative}"
            ) from exc
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise LiveWiringV1AcceptanceError(
                f"acceptance ancestor is not a directory: {relative}"
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        raise LiveWiringV1AcceptanceError(f"acceptance leaf is not regular: {relative}")
    return current


def _bytes(project: Path, relative: str) -> bytes:
    return _path(project, relative).read_bytes()


def _text(project: Path, relative: str) -> str:
    try:
        return _bytes(project, relative).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LiveWiringV1AcceptanceError(
            f"acceptance text is not UTF-8: {relative}"
        ) from exc


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _require_digest(project: Path, relative: str, expected: str) -> None:
    if _digest(project, relative) != expected:
        raise LiveWiringV1AcceptanceError(f"acceptance anchor drifted: {relative}")


def _json(project: Path, relative: str) -> dict[str, Any]:
    try:
        value = json.loads(_text(project, relative))
    except json.JSONDecodeError as exc:
        raise LiveWiringV1AcceptanceError(f"invalid JSON: {relative}") from exc
    if type(value) is not dict:
        raise LiveWiringV1AcceptanceError(f"JSON object required: {relative}")
    return value


def _root(artifacts: dict[str, str]) -> str:
    records = [f"{path}\0{digest}" for path, digest in artifacts.items()]
    return hashlib.sha256("\n".join(sorted(records)).encode("utf-8")).hexdigest()


def _manifest_rows(project: Path, relative: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in _text(project, relative).splitlines():
        if len(line) < 67 or line[64:66] != "  ":
            raise LiveWiringV1AcceptanceError(f"invalid sha256 row: {relative}")
        digest, target = line[:64], line[66:]
        if any(character not in _HEX for character in digest) or target in rows:
            raise LiveWiringV1AcceptanceError(f"invalid sha256 row: {relative}")
        _parts(target)
        rows[target] = digest
    if not rows:
        raise LiveWiringV1AcceptanceError(f"empty sha256 manifest: {relative}")
    return rows


def _verify_candidate(project: Path) -> dict[str, Any]:
    _require_digest(project, CANDIDATE_MANIFEST, CANDIDATE_MANIFEST_SHA256)
    manifest = _json(project, CANDIDATE_MANIFEST)
    if (
        manifest.get("schema") != "OnyxPhase6LiveWiringCheckpoint.v1"
        or manifest.get("status") != "candidate_default_off_not_live"
        or manifest.get("artifact_root_sha256") != CANDIDATE_ROOT_SHA256
        or manifest.get("activation")
        != {
            "feature_flag": "ONYX_PHASE6_LIVE_WIRING_V1",
            "enabled_value": "true",
            "default": "off",
            "live_wiring": False,
            "auto_install": False,
        }
        or manifest.get("lifecycle", {}).get("patched_seams")
        != ["__init__", "_start_phase5_session", "_stop_phase5_session"]
        or manifest.get("lifecycle", {}).get("protected_seams")
        != ["_execute_tool", "_run_live_loop", "_send_realtime"]
    ):
        raise LiveWiringV1AcceptanceError("candidate contract drifted")
    entries = manifest.get("artifacts")
    if type(entries) is not list or len(entries) != 5:
        raise LiveWiringV1AcceptanceError("candidate closure is not 5/5")
    observed: dict[str, str] = {}
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "bytes", "sha256"}:
            raise LiveWiringV1AcceptanceError("candidate artifact row drifted")
        relative = entry["path"]
        if relative in observed or relative not in CANDIDATE_ARTIFACTS:
            raise LiveWiringV1AcceptanceError("candidate artifact set drifted")
        expected_bytes, expected_digest = CANDIDATE_ARTIFACTS[relative]
        target = _path(project, relative)
        if (
            target.stat().st_size != expected_bytes
            or entry["bytes"] != expected_bytes
            or entry["sha256"] != expected_digest
        ):
            raise LiveWiringV1AcceptanceError(
                f"candidate artifact metadata drifted: {relative}"
            )
        _require_digest(project, relative, expected_digest)
        observed[relative] = expected_digest
    if (
        set(observed) != set(CANDIDATE_ARTIFACTS)
        or _root(observed) != CANDIDATE_ROOT_SHA256
    ):
        raise LiveWiringV1AcceptanceError("candidate root did not recompute")
    for relative, expected in FROZEN_ANCHORS.items():
        _require_digest(project, relative, expected)
    return manifest


def _verify_entry_and_v9(project: Path) -> None:
    _require_digest(project, PHASE5_EXIT_RECORD, PHASE5_EXIT_RECORD_SHA256)
    phase5 = _json(project, PHASE5_EXIT_METADATA)
    if (
        phase5.get("acceptance_id") != "VE-P5-EXIT-CANDIDATE-V2-E6-001"
        or phase5.get("decision") != "accepted"
        or phase5.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or phase5.get("candidate_manifest_sha256") != PHASE5_EXIT_MANIFEST_SHA256
        or phase5.get("evidence_root_sha256") != PHASE5_EXIT_ROOT_SHA256
        or phase5.get("phase6_unlocked") is not False
    ):
        raise LiveWiringV1AcceptanceError("Phase 5 Exit entry evidence drifted")

    _require_digest(project, V9_MANIFEST, V9_MANIFEST_SHA256)
    _require_digest(project, V8_MANIFEST, V8_MANIFEST_SHA256)
    v9 = _json(project, V9_MANIFEST)
    v8 = _json(project, V8_MANIFEST)
    v9_rows = {entry["path"]: entry["sha256"] for entry in v9.get("files", [])}
    v8_rows = {entry["path"]: entry["sha256"] for entry in v8.get("files", [])}
    if v9_rows.get(V8_CORE) != V8_CORE_SHA256 or v8_rows.get(V7_CORE) != V7_CORE_SHA256:
        raise LiveWiringV1AcceptanceError("V9 to V8 to V7 chain drifted")
    _require_digest(project, V8_CORE, V8_CORE_SHA256)
    _require_digest(project, V7_CORE, V7_CORE_SHA256)
    for relative in (
        V8_CORE,
        "core/onyx_live_activation_v9.py",
        "scripts/launch_onyx_live_v8.pyw",
        "scripts/launch_onyx_live_v9.pyw",
    ):
        source = _text(project, relative)
        if "phase6_live_wiring_v1" in source or "ONYX_PHASE6_LIVE_WIRING_V1" in source:
            raise LiveWiringV1AcceptanceError(
                f"Wiring V1 entered V8/V9 chain: {relative}"
            )


def _verify_external_envelope(project: Path) -> tuple[str, str]:
    record_digest = _digest(project, ACCEPTANCE_RECORD)
    metadata_digest = _digest(project, ACCEPTANCE_METADATA)
    source = _manifest_rows(project, SOURCE_MANIFEST)
    artifacts = _manifest_rows(project, ARTIFACT_MANIFEST)
    acceptance = _manifest_rows(project, ACCEPTANCE_MANIFEST)
    expected_source = {
        "scripts/verify_phase6_live_wiring_v1_acceptance.py": _digest(
            project, "scripts/verify_phase6_live_wiring_v1_acceptance.py"
        ),
        "tests/test_phase6_live_wiring_v1_acceptance.py": _digest(
            project, "tests/test_phase6_live_wiring_v1_acceptance.py"
        ),
    }
    if source != expected_source:
        raise LiveWiringV1AcceptanceError("source manifest drifted")
    if artifacts != {
        ACCEPTANCE_RECORD: record_digest,
        ACCEPTANCE_METADATA: metadata_digest,
    }:
        raise LiveWiringV1AcceptanceError("artifact manifest drifted")
    if acceptance != {ACCEPTANCE_RECORD: record_digest}:
        raise LiveWiringV1AcceptanceError("acceptance manifest drifted")
    metadata = _json(project, ACCEPTANCE_METADATA)
    if (
        metadata.get("acceptance_id") != ACCEPTANCE_ID
        or metadata.get("decision") != "accepted"
        or metadata.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata.get("candidate_manifest_sha256") != CANDIDATE_MANIFEST_SHA256
        or metadata.get("artifact_root_sha256") != CANDIDATE_ROOT_SHA256
        or metadata.get("artifact_count") != 5
        or metadata.get("frozen_anchors") != 18
        or metadata.get("results")
        != {
            "focused": {"passed": 17, "failed": 0},
            "cumulative": {"passed": 264, "failed": 0},
        }
        or metadata.get("default_off") is not True
        or metadata.get("live_wiring") is not False
        or metadata.get("network_calls") != 0
        or metadata.get("phase6_exit") is not False
    ):
        raise LiveWiringV1AcceptanceError("acceptance metadata drifted")
    record = _text(project, ACCEPTANCE_RECORD)
    required = (
        ACCEPTANCE_ID,
        "ACCEPTED — exact default-off, unwired candidate only",
        CANDIDATE_MANIFEST_SHA256,
        CANDIDATE_ROOT_SHA256,
        "5/5 artifact root",
        "18 frozen anchors",
        "17/17 focused tests",
        "264/264 cumulative tests",
        "P0=0, P1=0, P2=0, P3=0",
        PHASE5_EXIT_RECORD_SHA256,
        PHASE5_EXIT_MANIFEST_SHA256,
        PHASE5_EXIT_ROOT_SHA256,
        "phase6_unlocked=false",
        "strict default-off, unwired and not live",
    )
    missing = [value for value in required if value not in record]
    if missing:
        raise LiveWiringV1AcceptanceError(
            f"acceptance record missing binding: {missing[0]}"
        )
    return record_digest, metadata_digest


def _run_bound_verifiers(project: Path) -> dict[str, str]:
    executable = project / ".venv" / "Scripts" / "python.exe"
    markers: dict[str, str] = {}
    for relative, marker in BOUND_VERIFIERS.items():
        result = subprocess.run(
            [str(executable), "-I", "-S", "-B", relative],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        if result.returncode != 0 or marker not in result.stdout.splitlines()[0]:
            raise LiveWiringV1AcceptanceError(
                f"bound verifier failed: {relative}: {result.stderr.strip()}"
            )
        markers[relative] = marker
    return markers


def verify(project: Path = PROJECT) -> dict[str, object]:
    project = Path(project)
    manifest = _verify_candidate(project)
    _verify_entry_and_v9(project)
    record_digest, metadata_digest = _verify_external_envelope(project)
    markers = _run_bound_verifiers(project)
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "decision": "accepted",
        "candidate_manifest_sha256": CANDIDATE_MANIFEST_SHA256,
        "artifact_root_sha256": CANDIDATE_ROOT_SHA256,
        "artifacts": 5,
        "frozen_anchors": len(FROZEN_ANCHORS),
        "focused_passed": 17,
        "cumulative_passed": 264,
        "patched_seams": len(manifest["lifecycle"]["patched_seams"]),
        "protected_seams": len(manifest["lifecycle"]["protected_seams"]),
        "phase5_exit_record_sha256": PHASE5_EXIT_RECORD_SHA256,
        "v9_chain_compatible_unwired": True,
        "record_sha256": record_digest,
        "metadata_sha256": metadata_digest,
        "severity": {"P0": 0, "P1": 0, "P2": 0, "P3": 0},
        "verifiers": markers,
        "scope": "phase6-live-wiring-v1-default-off-unwired-no-live-activation",
        "default_off": True,
        "live_wiring": False,
        "network_calls": 0,
        "phase6_exit": False,
    }


if __name__ == "__main__":
    print(MARKER, json.dumps(verify(), sort_keys=True, separators=(",", ":")))
