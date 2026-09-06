"""Verify external E6 acceptance of frozen Onyx Live Activation V6."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import stat


PROJECT = Path(__file__).resolve().parents[1]
ACCEPTANCE_ID = "VE-ONYX-LIVE-ACTIVATION-V6-E6-001"
ACCEPTANCE_RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
ACCEPTANCE_SHA = "docs/onyx/VE-ACCEPTANCE-ONYX-LIVE-ACTIVATION-V6-E6-001.sha256"
VERIFIER = "scripts/verify_onyx_live_activation_v6_acceptance.py"
ACCEPTANCE_TEST = "tests/test_onyx_live_activation_v6_acceptance.py"
CANDIDATE_MANIFEST = "docs/onyx/checkpoints/onyx-live-activation-v6/manifest.json"
CHECKPOINT = (
    "docs/onyx/checkpoints/onyx-live-activation-v6/"
    "ONYX_LIVE_ACTIVATION_V6_CHECKPOINT.md"
)
CORE = "core/onyx_live_activation_v6.py"
LAUNCHER = "scripts/launch_onyx_live_v6.pyw"
CANDIDATE_TEST = "tests/test_onyx_live_activation_v6.py"
HOST_GATE = "scripts/verify_onyx_live_activation_v6_host.py"
PROVIDER_GATE = "scripts/verify_onyx_live_activation_v6_provider.py"
QT_GATE = "scripts/verify_onyx_live_activation_v6_qt.py"
CUMULATIVE_GATE = "scripts/verify_onyx_live_activation_v6.py"
MANIFEST_GATE = "scripts/verify_onyx_live_activation_v6_manifest.py"

MANIFEST_SHA256 = "4b7b3bcdb7c87043e97baa952b883dcfc9f498026c272099f5222de7decb4453"
INDEPENDENT_ROOT_SHA256 = (
    "e935133d2f08273088450c14e801b7b07d0e25503e2855cd9b324c7dc9f4839b"
)
CHECKPOINT_SHA256 = "51cb9fd819b89f5e70eed4f7275c05a8a4b6a9557ae7985ea12982a5a7780495"
CORE_SHA256 = "68d75e89728355b6b26b153f19ec5d732f26369b79d7e03e700bc8b00ee95f54"
LAUNCHER_SHA256 = "de6aff494b5c9c22dc93e209c50cfa5710a6d7012b217d263c22bca3076eeb0f"
CANDIDATE_TEST_SHA256 = (
    "0eed5cad48d30d38523e50b0ce6081762175d84b29e0e062ad2400b26a1bd565"
)
HOST_GATE_SHA256 = "9601395112ef21cacd09bfb9b52dbcce378757dbcb3fd5b9d87ea86ff41889b9"
PROVIDER_GATE_SHA256 = (
    "beabad244a69372fcb19de2d1229d4d9882aa49d83948b3c5d336d86e2f7a510"
)
QT_GATE_SHA256 = "881c8ee51537f18c2b83f7bf8f77a8783482a735a05bf1f926a0f4649407b9e9"
CUMULATIVE_GATE_SHA256 = (
    "58d94c7f2ef3e37b64494da07102a765575bb512a0c250c7c9b4d806dd463c02"
)
MANIFEST_GATE_SHA256 = (
    "685bcf55f7baa688c32dfd348f9085e3edd6deef25b2109b83d16a9a9923e88a"
)
ACCEPTANCE_TEST_SHA256 = (
    "eecadb3265966780a7822d15db688019fd7086b16472b87d68dc1a87d9b196fb"
)
ACCEPTANCE_MARKER = "ONYX_LIVE_ACTIVATION_V6_ACCEPTANCE_OK"
_REPARSE_ATTRIBUTE = 0x400


class ActivationV6AcceptanceError(RuntimeError):
    """An acceptance artifact or immutable candidate anchor is invalid."""


def _canonical_relative(relative: str) -> tuple[str, ...]:
    if type(relative) is not str or not relative or "\\" in relative or "\x00" in relative:
        raise ActivationV6AcceptanceError("acceptance path is not canonical")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or str(parsed) != relative or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise ActivationV6AcceptanceError("acceptance path is not canonical")
    return parsed.parts


def _regular_path(project: Path, relative: str) -> Path:
    parts = _canonical_relative(relative)
    root = project.absolute()
    try:
        metadata = root.lstat()
        resolved_root = root.resolve(strict=True)
    except OSError as exc:
        raise ActivationV6AcceptanceError("acceptance root is unavailable") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or getattr(metadata, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        or resolved_root != root
    ):
        raise ActivationV6AcceptanceError("acceptance root is linked or aliased")
    current = root
    for index, part in enumerate(parts):
        try:
            entries = {entry.name: entry for entry in current.iterdir()}
        except OSError as exc:
            raise ActivationV6AcceptanceError(
                f"acceptance ancestor is unavailable: {relative}"
            ) from exc
        if part not in entries:
            raise ActivationV6AcceptanceError(
                f"acceptance path is missing or case-mismatched: {relative}"
            )
        current = entries[part]
        metadata = current.lstat()
        resolved = current.resolve(strict=True)
        if stat.S_ISLNK(metadata.st_mode) or getattr(
            metadata, "st_file_attributes", 0
        ) & _REPARSE_ATTRIBUTE:
            raise ActivationV6AcceptanceError(
                f"acceptance path uses a link/reparse point: {relative}"
            )
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ActivationV6AcceptanceError(
                f"acceptance path leaves project: {relative}"
            ) from exc
        if resolved.name != part:
            raise ActivationV6AcceptanceError(
                f"acceptance path uses a name alias: {relative}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise ActivationV6AcceptanceError(
                f"acceptance ancestor is not a directory: {relative}"
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        raise ActivationV6AcceptanceError(
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
        raise ActivationV6AcceptanceError(
            f"acceptance path changed while read: {relative}"
        )
    if _regular_path(project, relative) != path:
        raise ActivationV6AcceptanceError(
            f"acceptance path identity changed: {relative}"
        )
    return value


def _text(project: Path, relative: str) -> str:
    try:
        value = _bytes(project, relative).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ActivationV6AcceptanceError(
            f"acceptance text is not UTF-8: {relative}"
        ) from exc
    if "\r" in value or not value.endswith("\n"):
        raise ActivationV6AcceptanceError(
            f"acceptance text is not canonical LF: {relative}"
        )
    return value


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _require_digest(project: Path, relative: str, expected: str) -> None:
    observed = _digest(project, relative)
    if observed != expected:
        raise ActivationV6AcceptanceError(
            f"acceptance anchor drifted: {relative}: {observed}"
        )


def _sha_line(value: str) -> tuple[str, str]:
    lines = value.splitlines()
    if len(lines) != 1 or len(lines[0]) < 67 or lines[0][64:66] != "  ":
        raise ActivationV6AcceptanceError("acceptance SHA line is malformed")
    digest, relative = lines[0][:64], lines[0][66:]
    if any(character not in "0123456789abcdef" for character in digest):
        raise ActivationV6AcceptanceError("acceptance SHA digest is malformed")
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
        (QT_GATE, QT_GATE_SHA256),
        (CUMULATIVE_GATE, CUMULATIVE_GATE_SHA256),
        (MANIFEST_GATE, MANIFEST_GATE_SHA256),
        (ACCEPTANCE_TEST, ACCEPTANCE_TEST_SHA256),
    ):
        _require_digest(project, relative, expected)
    try:
        payload = json.loads(_text(project, CANDIDATE_MANIFEST))
    except (json.JSONDecodeError, TypeError) as exc:
        raise ActivationV6AcceptanceError("candidate manifest is invalid") from exc
    if (
        type(payload) is not dict
        or payload.get("schema") != "onyx.live-activation.v6"
        or payload.get("candidate") != "onyx-live-activation-v6"
        or payload.get("status") != "candidate-ready-for-independent-gate"
    ):
        raise ActivationV6AcceptanceError("candidate identity is invalid")
    for name, expected in {
        "default_off": True,
        "live_activated": False,
        "live_restart_performed": False,
        "provider_calls_performed": False,
        "credential_provisioned": False,
    }.items():
        if payload.get(name) is not expected:
            raise ActivationV6AcceptanceError(f"candidate boundary drifted: {name}")
    entries = payload.get("files")
    if type(entries) is not list or len(entries) != 34:
        raise ActivationV6AcceptanceError("candidate closure is not 34 files")
    paths = set()
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "role", "sha256"}:
            raise ActivationV6AcceptanceError("candidate entry is malformed")
        relative, expected = entry["path"], entry["sha256"]
        _canonical_relative(relative)
        if relative in paths:
            raise ActivationV6AcceptanceError("candidate path is duplicated")
        if (
            type(expected) is not str
            or len(expected) != 64
            or any(character not in "0123456789abcdef" for character in expected)
        ):
            raise ActivationV6AcceptanceError("candidate digest is malformed")
        _require_digest(project, relative, expected)
        paths.add(relative)
    root = _independent_root(entries)
    if root != INDEPENDENT_ROOT_SHA256:
        raise ActivationV6AcceptanceError("independent 34-binding root drifted")
    host = payload.get("host_contract")
    replay = payload.get("tool_replay")
    circuit = payload.get("provider_circuit")
    verification = payload.get("verification")
    if (
        type(host) is not dict
        or host.get("total_transactional_writes") != 22
        or host.get("exact_input_audio_mime") != "audio/pcm;rate=16000"
        or host.get("visible_setup_surfaces") != 1
    ):
        raise ActivationV6AcceptanceError("host contract drifted")
    if (
        type(replay) is not dict
        or replay.get("identity") != "exact_call_id"
        or replay.get("capacity") != 256
        or replay.get("inflight_eviction") is not False
        or replay.get("capacity_overflow") != "fail_closed"
    ):
        raise ActivationV6AcceptanceError("tool replay contract drifted")
    if (
        type(circuit) is not dict
        or circuit.get("transition_authority") != "single_owning_asyncio_loop"
        or circuit.get("manual_recovery") != "cross_thread_command_with_ack"
        or circuit.get("rejects_bool_nonfinite_nonpositive_extreme") is not True
    ):
        raise ActivationV6AcceptanceError("provider circuit contract drifted")
    if (
        type(verification) is not dict
        or verification.get("focused") != {"passed": 6, "failed": 0}
        or verification.get("combined_v4_v5_v6") != {"passed": 35, "failed": 0}
        or verification.get("seam_failpoints") != 22
        or verification.get("sequential_ids") != 1000
        or verification.get("retained_ids") != 256
        or verification.get("all_inflight_257") != "refused"
        or verification.get("fake_provider_1007_1011_recovery") != "pass"
        or verification.get("accelerated_stability_seconds") != 601
        or verification.get("real_qt_offscreen") != "pass"
        or verification.get("network_calls") != 0
        or verification.get("live_activation") != "not_performed"
    ):
        raise ActivationV6AcceptanceError("verification evidence drifted")
    candidate_text = _text(project, CANDIDATE_MANIFEST)
    for forbidden in (
        ACCEPTANCE_ID,
        ACCEPTANCE_RECORD,
        ACCEPTANCE_SHA,
        VERIFIER,
        ACCEPTANCE_TEST,
    ):
        if forbidden in candidate_text:
            raise ActivationV6AcceptanceError(
                "external acceptance entered frozen candidate root"
            )
    for relative, labels in (
        (
            HOST_GATE,
            (
                "ONYX_LIVE_ACTIVATION_V6_REAL_HOST_OK",
                "seam_failpoints=22",
                "ids_tested=1000",
                "inflight_257=refused",
                "manual_recovery=cross-thread-ack",
            ),
        ),
        (
            PROVIDER_GATE,
            (
                "ONYX_LIVE_ACTIVATION_V6_FAKE_PROVIDER_OK",
                "failures=1007,1011",
                "simulated_seconds=",
                "setup_prompts=0",
            ),
        ),
        (
            QT_GATE,
            (
                "ONYX_LIVE_ACTIVATION_V6_QT_OK",
                "setup_surfaces=1",
                "renderer=suspended/resumed",
            ),
        ),
    ):
        text = _text(project, relative)
        if any(label not in text for label in labels):
            raise ActivationV6AcceptanceError(
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
        raise ActivationV6AcceptanceError("acceptance SHA points elsewhere")
    if _digest(project, ACCEPTANCE_RECORD) != record_digest:
        raise ActivationV6AcceptanceError("acceptance record digest mismatch")
    record = _text(project, ACCEPTANCE_RECORD)
    verifier_sha = _digest(project, VERIFIER)
    required = (
        ACCEPTANCE_ID,
        "ACCEPTED - Onyx Live Activation V6 frozen default-off handoff only",
        MANIFEST_SHA256,
        INDEPENDENT_ROOT_SHA256,
        CHECKPOINT_SHA256,
        CORE_SHA256,
        LAUNCHER_SHA256,
        CANDIDATE_TEST_SHA256,
        ACCEPTANCE_TEST_SHA256,
        verifier_sha,
        "224 passed, 0 failed",
        "P0=0, P1=0, P2=0, P3=0",
        "6 passed, 0 failed",
        "35 passed, 0 failed",
        "fake provider",
        "offscreen",
        "default-off",
        "real live activation is the next gate",
    )
    missing = [item for item in required if item not in record]
    if missing:
        raise ActivationV6AcceptanceError(
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
        "historical": {"passed": 224, "failed": 0},
        "findings": {"P0": 0, "P1": 0, "P2": 0, "P3": 0},
        "focused": {"passed": 6, "failed": 0},
        "combined": {"passed": 35, "failed": 0},
        "scope": "activation-v6-default-off-not-live-handoff",
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
