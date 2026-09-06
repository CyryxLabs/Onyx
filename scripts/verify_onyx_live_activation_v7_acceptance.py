"""Verify external E6 acceptance of frozen Onyx Live Activation V7."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[1]
ACCEPTANCE_ID = "VE-ONYX-LIVE-ACTIVATION-V7-E6-001"
ACCEPTANCE_RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
ACCEPTANCE_SHA = "docs/onyx/VE-ACCEPTANCE-ONYX-LIVE-ACTIVATION-V7-E6-001.sha256"
VERIFIER = "scripts/verify_onyx_live_activation_v7_acceptance.py"
ACCEPTANCE_TEST = "tests/test_onyx_live_activation_v7_acceptance.py"
CANDIDATE_MANIFEST = "docs/onyx/checkpoints/onyx-live-activation-v7/manifest.json"
CHECKPOINT = (
    "docs/onyx/checkpoints/onyx-live-activation-v7/"
    "ONYX_LIVE_ACTIVATION_V7_CHECKPOINT.md"
)
CORE = "core/onyx_live_activation_v7.py"
LAUNCHER = "scripts/launch_onyx_live_v7.pyw"
CANDIDATE_TEST = "tests/test_onyx_live_activation_v7.py"
HOST_GATE = "scripts/verify_onyx_live_activation_v7_host.py"
PROVIDER_GATE = "scripts/verify_onyx_live_activation_v7_provider.py"
CUMULATIVE_GATE = "scripts/verify_onyx_live_activation_v7.py"
MANIFEST_GATE = "scripts/verify_onyx_live_activation_v7_manifest.py"

MANIFEST_SHA256 = "312d6654f3423f16f4b36f435638920836994bd56c3e9a8766a086e2c6d647da"
INDEPENDENT_ROOT_SHA256 = (
    "c6c52ca0d9a7725b543989c7586fc9fe9ab535282223b7fa0e1b0d1b8f5807cc"
)
CHECKPOINT_SHA256 = "fc2cb24e0593500a39f3b9c69b29008803d1a6b6a7f695fd63c8b13f5988871b"
CORE_SHA256 = "906c7c0e31cb5efc28e5357bb158545e903d65ff1f160b3899bc3e2fb3c1dc77"
LAUNCHER_SHA256 = "a5dae76af4b09af90aa89b3638e2329fbed8c79a50fbcafa0a6179f38d82c531"
CANDIDATE_TEST_SHA256 = (
    "9ec4a10de3c08cf5e90ed6d58ca0292e9ff6f3edf1467be683d7ecd20bba8b6a"
)
HOST_GATE_SHA256 = "c7868cd2fa1fd42c457da96cc295be817dc1ffd5ec93ba3294162f279e6ff109"
PROVIDER_GATE_SHA256 = (
    "48e7a1e63046848c7b93274cf17ef2be82fc561f163eb88b52ab3a97251ffc66"
)
CUMULATIVE_GATE_SHA256 = (
    "6d32952922ebd5a9fbb8b09ae2e7a366f6fb7fc5678a9dc459b1c3825ce17b97"
)
MANIFEST_GATE_SHA256 = (
    "ac5f19a65ccbcaa03aaa33e677b8d1ba4c3dd3d10f09fce0a626e19df29bcb33"
)
ACCEPTANCE_TEST_SHA256 = (
    "bad81b091ae09ca41f289f9515f2d630ca1fffbd83f2913426899f4d38d746d9"
)
ACCEPTANCE_MARKER = "ONYX_LIVE_ACTIVATION_V7_ACCEPTANCE_OK"
_REPARSE_ATTRIBUTE = 0x400


class ActivationV7AcceptanceError(RuntimeError):
    """An acceptance artifact or immutable candidate anchor is invalid."""


def _canonical_relative(relative: str) -> tuple[str, ...]:
    if type(relative) is not str or not relative or "\\" in relative or "\x00" in relative:
        raise ActivationV7AcceptanceError("acceptance path is not canonical")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or str(parsed) != relative or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise ActivationV7AcceptanceError("acceptance path is not canonical")
    return parsed.parts


def _regular_path(project: Path, relative: str) -> Path:
    parts = _canonical_relative(relative)
    root = project.absolute()
    try:
        metadata = root.lstat()
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise ActivationV7AcceptanceError("acceptance root is unavailable") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or getattr(metadata, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        or resolved_root != root
    ):
        raise ActivationV7AcceptanceError("acceptance root is linked or aliased")
    current = root
    for index, part in enumerate(parts):
        try:
            entries = {entry.name: entry for entry in current.iterdir()}
        except OSError as exc:
            raise ActivationV7AcceptanceError(
                f"acceptance ancestor is unavailable: {relative}"
            ) from exc
        if part not in entries:
            raise ActivationV7AcceptanceError(
                f"acceptance path is missing or case-mismatched: {relative}"
            )
        current = entries[part]
        metadata = current.lstat()
        resolved = current.resolve(strict=True)
        if stat.S_ISLNK(metadata.st_mode) or getattr(
            metadata, "st_file_attributes", 0
        ) & _REPARSE_ATTRIBUTE:
            raise ActivationV7AcceptanceError(
                f"acceptance path uses a link/reparse point: {relative}"
            )
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ActivationV7AcceptanceError(
                f"acceptance path leaves project: {relative}"
            ) from exc
        if resolved.name != part:
            raise ActivationV7AcceptanceError(
                f"acceptance path uses a name alias: {relative}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise ActivationV7AcceptanceError(
                f"acceptance ancestor is not a directory: {relative}"
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        raise ActivationV7AcceptanceError(
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
    before = path.stat()
    value = path.read_bytes()
    after = path.stat()
    if _fingerprint(before) != _fingerprint(after):
        raise ActivationV7AcceptanceError(
            f"acceptance path changed while read: {relative}"
        )
    if _regular_path(project, relative) != path:
        raise ActivationV7AcceptanceError(
            f"acceptance path identity changed: {relative}"
        )
    return value


def _text(project: Path, relative: str) -> str:
    try:
        value = _bytes(project, relative).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ActivationV7AcceptanceError(
            f"acceptance text is not UTF-8: {relative}"
        ) from exc
    if "\r" in value or not value.endswith("\n"):
        raise ActivationV7AcceptanceError(
            f"acceptance text is not canonical LF: {relative}"
        )
    return value


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _require_digest(project: Path, relative: str, expected: str) -> None:
    observed = _digest(project, relative)
    if observed != expected:
        raise ActivationV7AcceptanceError(
            f"acceptance anchor drifted: {relative}: {observed}"
        )


def _sha_line(value: str) -> tuple[str, str]:
    lines = value.splitlines()
    if len(lines) != 1 or len(lines[0]) < 67 or lines[0][64:66] != "  ":
        raise ActivationV7AcceptanceError("acceptance SHA line is malformed")
    digest, relative = lines[0][:64], lines[0][66:]
    if any(character not in "0123456789abcdef" for character in digest):
        raise ActivationV7AcceptanceError("acceptance SHA digest is malformed")
    _canonical_relative(relative)
    return digest, relative


def _independent_root(entries: list[dict[str, str]]) -> str:
    material = "".join(
        f"{entry['path']}\0{entry['sha256']}\n"
        for entry in sorted(entries, key=lambda item: item["path"])
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _verify_candidate(project: Path) -> dict[str, object]:
    for relative, expected in (
        (CANDIDATE_MANIFEST, MANIFEST_SHA256),
        (CHECKPOINT, CHECKPOINT_SHA256),
        (CORE, CORE_SHA256),
        (LAUNCHER, LAUNCHER_SHA256),
        (CANDIDATE_TEST, CANDIDATE_TEST_SHA256),
        (HOST_GATE, HOST_GATE_SHA256),
        (PROVIDER_GATE, PROVIDER_GATE_SHA256),
        (CUMULATIVE_GATE, CUMULATIVE_GATE_SHA256),
        (MANIFEST_GATE, MANIFEST_GATE_SHA256),
        (ACCEPTANCE_TEST, ACCEPTANCE_TEST_SHA256),
    ):
        _require_digest(project, relative, expected)
    try:
        payload = json.loads(_text(project, CANDIDATE_MANIFEST))
    except (json.JSONDecodeError, TypeError) as exc:
        raise ActivationV7AcceptanceError("candidate manifest is invalid") from exc
    if (
        type(payload) is not dict
        or payload.get("schema") != "onyx.live-activation.v7"
        or payload.get("candidate") != "onyx-live-activation-v7"
        or payload.get("status") != "candidate-ready-for-independent-gate"
    ):
        raise ActivationV7AcceptanceError("candidate identity is invalid")
    for name, expected in {
        "default_off": True,
        "live_activated": False,
        "live_restart_performed": False,
        "provider_calls_performed": False,
        "credential_provisioned": False,
    }.items():
        if payload.get(name) is not expected:
            raise ActivationV7AcceptanceError(f"candidate boundary drifted: {name}")
    if payload.get("network_calls") != 0:
        raise ActivationV7AcceptanceError("candidate network boundary drifted")
    entries = payload.get("files")
    if type(entries) is not list or len(entries) != 19:
        raise ActivationV7AcceptanceError("candidate closure is not 19 files")
    paths: set[str] = set()
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "role", "sha256"}:
            raise ActivationV7AcceptanceError("candidate entry is malformed")
        relative, expected = entry["path"], entry["sha256"]
        _canonical_relative(relative)
        if relative in paths:
            raise ActivationV7AcceptanceError("candidate path is duplicated")
        if (
            type(expected) is not str
            or len(expected) != 64
            or any(character not in "0123456789abcdef" for character in expected)
        ):
            raise ActivationV7AcceptanceError("candidate digest is malformed")
        _require_digest(project, relative, expected)
        paths.add(relative)
    root = _independent_root(entries)
    if root != INDEPENDENT_ROOT_SHA256:
        raise ActivationV7AcceptanceError("independent 19-binding root drifted")

    expected_identity = {
        "principal_id": "onyx-owner",
        "workspace_id": "onyx-local-workspace",
        "account_id": "cyryx-local-account",
        "profile_id": "onyx-owner-profile",
    }
    host = payload.get("host_contract")
    catalog = payload.get("local_catalog")
    preserved = payload.get("preserved_v6")
    verification = payload.get("verification")
    if payload.get("phase5_identity") != expected_identity:
        raise ActivationV7AcceptanceError("Phase 5 identity drifted")
    if (
        type(host) is not dict
        or host.get("v6_transactional_writes") != 22
        or host.get("v7_transactional_writes") != 1
        or host.get("total_transactional_writes") != 23
        or host.get("exact_input_audio_mime") != "audio/pcm;rate=16000"
        or host.get("frozen_host_modified") is not False
        or host.get("frozen_v6_modified") is not False
    ):
        raise ActivationV7AcceptanceError("host contract drifted")
    if (
        type(catalog) is not dict
        or catalog.get("private_reference_grammar") != "catalog-p<PID>-n<N>"
        or catalog.get("public_arguments_coerced") is not False
        or catalog.get("full_main_broker") is not True
        or catalog.get("runtime_state") != "READY"
        or catalog.get("completed_reads") != 1
        or catalog.get("same_call_id_reexecution") != 0
        or catalog.get("egress") != "none"
        or catalog.get("cost_micro") != 0
    ):
        raise ActivationV7AcceptanceError("local catalog contract drifted")
    if (
        type(preserved) is not dict
        or preserved.get("provider_call_identity") != "exact_call_id"
        or preserved.get("replay_capacity") != 256
        or preserved.get("concurrent_duplicates") != "single_flight"
        or preserved.get("provider_circuit_authority")
        != "single_owning_asyncio_loop"
    ):
        raise ActivationV7AcceptanceError("preserved V6 contract drifted")
    if (
        type(verification) is not dict
        or verification.get("focused") != {"passed": 6, "failed": 0}
        or verification.get("combined_v4_v5_v6_v7")
        != {"passed": 57, "failed": 0}
        or verification.get("identity_variants_refused") != 32
        or verification.get("phase5_bridges_across_reconnect") != 2
        or verification.get("fake_provider_1011_recovery") != "pass"
        or verification.get("full_host_authorize_model_tool") != "pass"
        or verification.get("network_calls") != 0
        or verification.get("live_activation") != "not_performed"
    ):
        raise ActivationV7AcceptanceError("verification evidence drifted")

    candidate_text = _text(project, CANDIDATE_MANIFEST)
    for forbidden in (
        ACCEPTANCE_ID,
        ACCEPTANCE_RECORD,
        ACCEPTANCE_SHA,
        VERIFIER,
        ACCEPTANCE_TEST,
    ):
        if forbidden in candidate_text:
            raise ActivationV7AcceptanceError(
                "external acceptance entered frozen candidate root"
            )
    core_text = _text(project, CORE)
    checkpoint_text = _text(project, CHECKPOINT)
    if "accepted V6 runtime transition" not in core_text:
        raise ActivationV7AcceptanceError("known core docstring P3 drifted")
    if "V4–V7 cumulative pytest: `57 passed`." not in checkpoint_text:
        raise ActivationV7AcceptanceError("known checkpoint count P3 drifted")
    if '"combined_v4_v5_v6_v7": {"passed": 57, "failed": 0}' not in candidate_text:
        raise ActivationV7AcceptanceError("known manifest count label P3 drifted")
    for relative, labels in (
        (
            HOST_GATE,
            (
                "ONYX_LIVE_ACTIVATION_V7_HOST_OK",
                "canonical_identities=4",
                "refused_variants=",
                "network_calls=",
                "denial_diagnostic=content-free",
            ),
        ),
        (
            PROVIDER_GATE,
            (
                "ONYX_LIVE_ACTIVATION_V7_PHASE5_E2E_OK",
                "main.configure_owner_autonomy",
                "host._execute_tool",
                "local_catalog_reads=",
                "reconnect=continuous",
                "mime=audio/pcm;rate=16000",
            ),
        ),
    ):
        text = _text(project, relative)
        if any(label not in text for label in labels):
            raise ActivationV7AcceptanceError(
                f"gate evidence label drifted: {relative}"
            )
    return {
        "candidate_files": len(entries),
        "independent_root_sha256": root,
        "activation_master": payload["activation"]["master"],
        "launcher": payload["activation"]["launcher"],
        "rollback_switch": payload["rollback"]["single_switch"],
        "legacy_rollback": payload["rollback"]["delegates_to"],
    }


def _verify_record(project: Path) -> str:
    record_digest, relative = _sha_line(_text(project, ACCEPTANCE_SHA))
    if relative != ACCEPTANCE_RECORD:
        raise ActivationV7AcceptanceError("acceptance SHA points elsewhere")
    if _digest(project, ACCEPTANCE_RECORD) != record_digest:
        raise ActivationV7AcceptanceError("acceptance record digest mismatch")
    record = _text(project, ACCEPTANCE_RECORD)
    verifier_sha = _digest(project, VERIFIER)
    required = (
        ACCEPTANCE_ID,
        "ACCEPTED - Onyx Live Activation V7 frozen default-off handoff",
        MANIFEST_SHA256,
        INDEPENDENT_ROOT_SHA256,
        CHECKPOINT_SHA256,
        CORE_SHA256,
        LAUNCHER_SHA256,
        CANDIDATE_TEST_SHA256,
        ACCEPTANCE_TEST_SHA256,
        verifier_sha,
        "19/19",
        "P0=0, P1=0, P2=0, P3=2",
        "6 passed, 0 failed",
        "31 passed, 0 failed",
        "57 passed, 0 failed",
        "core docstring",
        "checkpoint/manifest count label",
        "full `main.authorize_model_tool`",
        "audio/pcm;rate=16000",
        "default-off",
        "No live activation",
    )
    missing = [item for item in required if item not in record]
    if missing:
        raise ActivationV7AcceptanceError(
            f"acceptance record is missing binding: {missing[0]}"
        )
    return record_digest


def verify(project: Path = PROJECT) -> dict[str, object]:
    project = Path(project)
    record_sha = _verify_record(project)
    candidate = _verify_candidate(project)
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "record_sha256": record_sha,
        "candidate_manifest_sha256": MANIFEST_SHA256,
        **candidate,
        "findings": {"P0": 0, "P1": 0, "P2": 0, "P3": 2},
        "focused": {"passed": 6, "failed": 0},
        "v4_v7": {"passed": 31, "failed": 0},
        "v2_v7": {"passed": 57, "failed": 0},
        "scope": "activation-v7-default-off-not-live-handoff",
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
