"""Verify external E6 acceptance of frozen Onyx Live Activation V4."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat


PROJECT = Path(__file__).resolve().parents[1]
ACCEPTANCE_ID = "VE-ONYX-LIVE-ACTIVATION-V4-E6-001"
ACCEPTANCE_RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
ACCEPTANCE_MANIFEST = (
    "docs/onyx/VE-ACCEPTANCE-ONYX-LIVE-ACTIVATION-V4-E6-001.sha256"
)
VERIFIER = "scripts/verify_onyx_live_activation_v4_acceptance.py"
ACCEPTANCE_TEST = "tests/test_onyx_live_activation_v4_acceptance.py"
CANDIDATE_MANIFEST = "docs/onyx/checkpoints/onyx-live-activation-v4/manifest.json"
CHECKPOINT = (
    "docs/onyx/checkpoints/onyx-live-activation-v4/"
    "ONYX_LIVE_ACTIVATION_V4_CHECKPOINT.md"
)
MANIFEST_SHA256 = "ebe3b24e641d1148e3ddb3767705b593a0d9df0898ba2654b53cd7820e0d6c09"
CHECKPOINT_SHA256 = "3ea17bf227025f7dbe2ce4f91e15801151c6262efc01173657e7c3ce481d638f"
ACCEPTANCE_TEST_SHA256 = (
    "86b22756c450db1c12e0891eef866c75791854b3c18d8580dfe56332ac6c7b14"
)
ACCEPTANCE_MARKER = "ONYX_LIVE_ACTIVATION_V4_ACCEPTANCE_OK"
_REPARSE_ATTRIBUTE = 0x400

REJECTED = {
    "v1": frozenset(
        {
            "core/onyx_live_activation_v1.py",
            "scripts/launch_onyx_live_v1.pyw",
            "scripts/verify_onyx_live_activation_v1.py",
            "tests/test_onyx_live_activation_v1.py",
            "docs/onyx/checkpoints/onyx-live-activation-v1/manifest.json",
            "docs/onyx/checkpoints/onyx-live-activation-v1/ONYX_LIVE_ACTIVATION_V1_CHECKPOINT.md",
            "docs/onyx/rejections/ONYX_LIVE_ACTIVATION_V1_REJECTED.md",
        }
    ),
    "v2": frozenset(
        {
            "core/onyx_live_activation_v2.py",
            "scripts/launch_onyx_live_v2.pyw",
            "scripts/verify_onyx_live_activation_v2.py",
            "scripts/verify_onyx_live_activation_v2_host.py",
            "tests/test_onyx_live_activation_v2.py",
            "docs/onyx/checkpoints/onyx-live-activation-v2/manifest.json",
            "docs/onyx/checkpoints/onyx-live-activation-v2/ONYX_LIVE_ACTIVATION_V2_CHECKPOINT.md",
            "docs/onyx/rejections/ONYX_LIVE_ACTIVATION_V2_REJECTED.md",
        }
    ),
    "v3": frozenset(
        {
            "core/onyx_live_activation_v3.py",
            "scripts/launch_onyx_live_v3.pyw",
            "scripts/verify_onyx_live_activation_v3.py",
            "scripts/verify_onyx_live_activation_v3_host.py",
            "scripts/verify_onyx_live_activation_v3_qt.py",
            "tests/test_onyx_live_activation_v3.py",
            "docs/onyx/checkpoints/onyx-live-activation-v3/manifest.json",
            "docs/onyx/checkpoints/onyx-live-activation-v3/ONYX_LIVE_ACTIVATION_V3_CHECKPOINT.md",
            "docs/onyx/rejections/ONYX_LIVE_ACTIVATION_V3_REJECTED.md",
        }
    ),
}
V4 = frozenset(
    {
        "core/onyx_live_activation_v4.py",
        "scripts/launch_onyx_live_v4.pyw",
        "scripts/verify_onyx_live_activation_v4.py",
        "scripts/verify_onyx_live_activation_v4_host.py",
        "scripts/verify_onyx_live_activation_v4_qt.py",
        "tests/test_onyx_live_activation_v4.py",
        CHECKPOINT,
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


class ActivationV4AcceptanceError(RuntimeError):
    """An acceptance artifact or immutable candidate anchor is invalid."""


def _canonical_relative(relative: str) -> tuple[str, ...]:
    if type(relative) is not str or not relative or "\\" in relative or "\x00" in relative:
        raise ActivationV4AcceptanceError("acceptance path is not canonical")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or str(parsed) != relative or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise ActivationV4AcceptanceError("acceptance path is not canonical")
    return parsed.parts


def _regular_path(project: Path, relative: str) -> Path:
    parts = _canonical_relative(relative)
    root = project.absolute()
    try:
        metadata = root.lstat()
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise ActivationV4AcceptanceError("acceptance root is unavailable") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or getattr(metadata, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        or resolved_root != root
    ):
        raise ActivationV4AcceptanceError("acceptance root is linked or aliased")
    current = root
    for index, part in enumerate(parts):
        try:
            entries = {entry.name: entry for entry in current.iterdir()}
        except OSError as exc:
            raise ActivationV4AcceptanceError(
                f"acceptance ancestor is unavailable: {relative}"
            ) from exc
        if part not in entries:
            raise ActivationV4AcceptanceError(
                f"acceptance path is missing or case-mismatched: {relative}"
            )
        current = entries[part]
        try:
            metadata = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise ActivationV4AcceptanceError(
                f"acceptance path is unavailable: {relative}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode) or getattr(
            metadata, "st_file_attributes", 0
        ) & _REPARSE_ATTRIBUTE:
            raise ActivationV4AcceptanceError(
                f"acceptance path uses a link/reparse point: {relative}"
            )
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ActivationV4AcceptanceError(
                f"acceptance path leaves project: {relative}"
            ) from exc
        if resolved.name != part:
            raise ActivationV4AcceptanceError(
                f"acceptance path uses a name alias: {relative}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise ActivationV4AcceptanceError(
                f"acceptance ancestor is not a directory: {relative}"
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        raise ActivationV4AcceptanceError(
            f"acceptance leaf is not a regular file: {relative}"
        )
    return current


def _fingerprint(metadata: object) -> tuple[object, ...]:
    return (
        getattr(metadata, "st_dev", None),
        getattr(metadata, "st_ino", None),
        getattr(metadata, "st_size", None),
        getattr(metadata, "st_mtime_ns", None),
        getattr(metadata, "st_file_attributes", None),
    )


def _bytes(project: Path, relative: str) -> bytes:
    path = _regular_path(project, relative)
    try:
        before = path.stat()
        value = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise ActivationV4AcceptanceError(
            f"cannot read acceptance path: {relative}"
        ) from exc
    if _fingerprint(before) != _fingerprint(after):
        raise ActivationV4AcceptanceError(
            f"acceptance path changed while read: {relative}"
        )
    if _regular_path(project, relative) != path:
        raise ActivationV4AcceptanceError(
            f"acceptance path identity changed: {relative}"
        )
    return value


def _text(project: Path, relative: str) -> str:
    try:
        value = _bytes(project, relative).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ActivationV4AcceptanceError(
            f"acceptance text is not UTF-8: {relative}"
        ) from exc
    if "\r" in value or not value.endswith("\n"):
        raise ActivationV4AcceptanceError(
            f"acceptance text is not canonical LF: {relative}"
        )
    return value


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _require_digest(project: Path, relative: str, expected: str) -> None:
    actual = _digest(project, relative)
    if actual != expected:
        raise ActivationV4AcceptanceError(
            f"acceptance anchor drifted: {relative}: expected {expected}, got {actual}"
        )


def _manifest_line(value: str) -> tuple[str, str]:
    lines = value.splitlines()
    if len(lines) != 1 or len(lines[0]) < 67 or lines[0][64:66] != "  ":
        raise ActivationV4AcceptanceError("acceptance manifest is malformed")
    digest, relative = lines[0][:64], lines[0][66:]
    if any(character not in "0123456789abcdef" for character in digest):
        raise ActivationV4AcceptanceError("acceptance digest is malformed")
    _canonical_relative(relative)
    return digest, relative


def _verify_record(project: Path) -> str:
    manifest_digest, manifest_path = _manifest_line(
        _text(project, ACCEPTANCE_MANIFEST)
    )
    if manifest_path != ACCEPTANCE_RECORD:
        raise ActivationV4AcceptanceError("acceptance manifest points elsewhere")
    record_digest = _digest(project, ACCEPTANCE_RECORD)
    if record_digest != manifest_digest:
        raise ActivationV4AcceptanceError("acceptance record digest mismatch")
    record = _text(project, ACCEPTANCE_RECORD)
    verifier_sha256 = _digest(project, VERIFIER)
    required = (
        ACCEPTANCE_ID,
        "ACCEPTED - Onyx Live Activation V4 frozen default-off handoff only",
        MANIFEST_SHA256,
        CHECKPOINT_SHA256,
        ACCEPTANCE_TEST_SHA256,
        verifier_sha256,
        "53/53",
        "P0=0, P1=0, P2=0",
        "P3=1",
        "bundled timeout label gap",
        "No activation, restart, credential provisioning, provider call",
        "Activation V4 remains default-off and not activated",
    )
    missing = [item for item in required if item not in record]
    if missing:
        raise ActivationV4AcceptanceError(
            f"acceptance record is missing binding: {missing[0]}"
        )
    return record_digest


def _verify_candidate(project: Path) -> dict[str, object]:
    _require_digest(project, CANDIDATE_MANIFEST, MANIFEST_SHA256)
    _require_digest(project, CHECKPOINT, CHECKPOINT_SHA256)
    _require_digest(project, ACCEPTANCE_TEST, ACCEPTANCE_TEST_SHA256)
    try:
        payload = json.loads(_text(project, CANDIDATE_MANIFEST))
    except (json.JSONDecodeError, TypeError) as exc:
        raise ActivationV4AcceptanceError("candidate manifest is invalid") from exc
    if (
        type(payload) is not dict
        or payload.get("schema") != "onyx.live-activation.v4"
        or payload.get("candidate") != "onyx-live-activation-v4"
    ):
        raise ActivationV4AcceptanceError("candidate identity is invalid")
    for name, expected in {
        "default_off": True,
        "live_activated": False,
        "live_restart_performed": False,
        "provider_calls_performed": False,
        "credential_provisioned": False,
    }.items():
        if payload.get(name) is not expected:
            raise ActivationV4AcceptanceError(f"candidate boundary drifted: {name}")

    entries = payload.get("files")
    if type(entries) is not list or len(entries) != 53:
        raise ActivationV4AcceptanceError("candidate closure is not 53 files")
    indexed: dict[str, dict[str, str]] = {}
    roles: Counter[str] = Counter()
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "role", "sha256"}:
            raise ActivationV4AcceptanceError("candidate file entry is malformed")
        relative, role, expected = entry["path"], entry["role"], entry["sha256"]
        if (
            type(relative) is not str
            or type(role) is not str
            or type(expected) is not str
            or len(expected) != 64
            or any(character not in "0123456789abcdef" for character in expected)
        ):
            raise ActivationV4AcceptanceError("candidate entry types are invalid")
        _canonical_relative(relative)
        if relative in indexed:
            raise ActivationV4AcceptanceError("candidate path is duplicated")
        _require_digest(project, relative, expected)
        indexed[relative] = entry
        roles[role] += 1

    expected_paths = (
        REJECTED["v1"]
        | REJECTED["v2"]
        | REJECTED["v3"]
        | V4
        | HOST
        | COMPONENTS
        | E6
    )
    if frozenset(indexed) != expected_paths:
        raise ActivationV4AcceptanceError("candidate closure path set drifted")
    for version, paths in REJECTED.items():
        if any(indexed[path]["role"] != f"rejected-{version}" for path in paths):
            raise ActivationV4AcceptanceError(
                f"rejected {version.upper()} history lost its role"
            )
    if any(indexed[path]["role"] != "accepted-e6-record" for path in E6):
        raise ActivationV4AcceptanceError("accepted E6 anchor role drifted")

    host = payload.get("host_contract")
    continuity = payload.get("continuity")
    activation = payload.get("activation")
    rollback = payload.get("rollback")
    verification = payload.get("verification")
    if type(host) is not dict or host.get("transactional_seams") != 11:
        raise ActivationV4AcceptanceError("host seam contract drifted")
    if type(continuity) is not dict or continuity != {
        "reconnects": 64,
        "catalog_reads": 64,
        "unique_session_trace_ids": 128,
        "id_form": "(session|trace)-p<PID>-n<N>",
    }:
        raise ActivationV4AcceptanceError("continuity evidence drifted")
    if activation != {
        "master": "ONYX_LIVE_ACTIVATION_V4=1",
        "launcher": "scripts/launch_onyx_live_v4.pyw",
        "controlled_restart_required": True,
    }:
        raise ActivationV4AcceptanceError("activation recipe drifted")
    if rollback != {
        "single_switch": "ONYX_LIVE_ROLLBACK_V4=1",
        "delegates_to": "scripts/launch_onyx.pyw",
    }:
        raise ActivationV4AcceptanceError("rollback recipe drifted")
    if (
        type(verification) is not dict
        or verification.get("focused") != {"passed": 13, "failed": 0}
        or verification.get("combined") != {"passed": 67, "failed": 0}
        or verification.get("real_host") != "pass"
        or verification.get("real_qt_offscreen") != "pass"
        or verification.get("bundle_verifier") != "pass"
    ):
        raise ActivationV4AcceptanceError("verification evidence drifted")

    checkpoint = _text(project, CHECKPOINT)
    for required in (
        "candidate verified, default-off, not activated",
        "Timeout cancellation still removes the request before late queued delivery",
        "13 passed",
        "67 passed",
        "11/11",
        "64/64",
        "128",
        "No live activation, credential provisioning, provider call, shortcut change",
    ):
        if required not in checkpoint:
            raise ActivationV4AcceptanceError(
                f"candidate checkpoint lost evidence: {required}"
            )

    candidate_text = _text(project, CANDIDATE_MANIFEST)
    if any(
        item in candidate_text
        for item in (
            ACCEPTANCE_ID,
            ACCEPTANCE_RECORD,
            ACCEPTANCE_MANIFEST,
            ACCEPTANCE_TEST,
            VERIFIER,
        )
    ):
        raise ActivationV4AcceptanceError(
            "external acceptance entered frozen candidate root"
        )
    core = _text(project, "core/onyx_live_activation_v4.py")
    launcher = _text(project, "scripts/launch_onyx_live_v4.pyw")
    host_gate = _text(project, "scripts/verify_onyx_live_activation_v4_host.py")
    qt_gate = _text(project, "scripts/verify_onyx_live_activation_v4_qt.py")
    if any(token in core for token in ("requests.", "httpx.", "socket.", "google.genai")):
        raise ActivationV4AcceptanceError("candidate gained a provider/network path")
    for required in (
        'MASTER = "ONYX_LIVE_ACTIVATION_V4"',
        'ROLLBACK = "ONYX_LIVE_ROLLBACK_V4"',
        'return "rollback" if (master and complete) or (not master and empty)',
        "for name in CONTROL:",
        "os.environ.pop(name, None)",
        "_legacy()",
    ):
        if required not in launcher:
            raise ActivationV4AcceptanceError("launcher recipe is incomplete")
    if "seam_failpoints=11 reconnects=64 catalog_reads=64 session_trace_ids=128" not in host_gate:
        raise ActivationV4AcceptanceError("real-host evidence label drifted")
    for label in (
        "ONYX_LIVE_ACTIVATION_V4_QT_OK",
        "readback=set/correct/forget",
        "direct64_ms=",
    ):
        if label not in qt_gate:
            raise ActivationV4AcceptanceError("real-Qt evidence label drifted")
    return {
        "candidate_files": len(indexed),
        "rejected_history": {key: len(value) for key, value in REJECTED.items()},
        "accepted_e6_anchors": len(E6),
        "roles": dict(sorted(roles.items())),
        "activation_master": activation["master"],
        "launcher": activation["launcher"],
        "rollback_switch": rollback["single_switch"],
        "legacy_rollback": rollback["delegates_to"],
    }


def verify(project: Path = PROJECT) -> dict[str, object]:
    project = Path(project)
    record_sha256 = _verify_record(project)
    candidate = _verify_candidate(project)
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "record_sha256": record_sha256,
        "candidate_manifest_sha256": MANIFEST_SHA256,
        **candidate,
        "findings": {"P0": 0, "P1": 0, "P2": 0, "P3": 1},
        "scope": "activation-v4-default-off-not-activated-handoff",
    }


def main() -> int:
    print(
        ACCEPTANCE_MARKER
        + " "
        + json.dumps(verify(), sort_keys=True, separators=(",", ":"))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
