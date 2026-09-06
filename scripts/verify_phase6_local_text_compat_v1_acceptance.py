"""Verify external E6 acceptance of Phase 6 Local/Text Compatibility V1."""

from __future__ import annotations

import ast
import hashlib
import json
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve(strict=True).parents[1]
ACCEPTANCE_ID = "VE-P6-LOCAL-TEXT-COMPAT-V1-E6-001"
MARKER = "P6_LOCAL_TEXT_COMPAT_V1_ACCEPTANCE_OK"
CANDIDATE_MANIFEST = "docs/onyx/checkpoints/phase6-local-text-compat-v1/manifest.json"
CANDIDATE_MANIFEST_SHA256 = (
    "a4c972e5ef74745884faf0c03e5bce3cad5424c524a7d03eee36a59f59ae49fc"
)
CANDIDATE_ROOT_SHA256 = (
    "9c14301f67b1f01604909265a50b9591645fa7d11451f981811e90e30da80611"
)
ACCEPTANCE_RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
ACCEPTANCE_METADATA = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
SOURCE_MANIFEST = "docs/onyx/VE-SOURCE-P6-LOCAL-TEXT-COMPAT-V1-E6-001.sha256"
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P6-LOCAL-TEXT-COMPAT-V1-E6-001.sha256"
ACCEPTANCE_MANIFEST = "docs/onyx/VE-ACCEPTANCE-P6-LOCAL-TEXT-COMPAT-V1-E6-001.sha256"
CANDIDATE_ARTIFACTS = {
    "core/phase6_local_text_compat_v1.py": (
        31_598,
        "6c17bdb0fc91dca58fb347c0d9b143d2dafe272d61552289c9d4b0e80e109fe8",
    ),
    "docs/onyx/adrs/ADR-0025-phase6-local-text-compat-v1.md": (
        3_611,
        "ab71aafe23bfc8bccf20a2f9840cb1d87bcf97080a042ca4d9eed777447fa993",
    ),
    (
        "docs/onyx/checkpoints/phase6-local-text-compat-v1/"
        "PHASE6_LOCAL_TEXT_COMPAT_V1_CHECKPOINT.md"
    ): (
        2_832,
        "fe3b073945eacb5e76b350fba64238645184baa2ad410c6a37f1e707d7f4694a",
    ),
    "scripts/verify_phase6_local_text_compat_v1.py": (
        8_636,
        "8b9927df1f41dcf860bea1f261f534cff9e3171a618f399e79c9e647cc476436",
    ),
    "tests/test_phase6_local_text_compat_v1.py": (
        18_372,
        "0b6a6140040d37e00504971d9e9bd1591e84b6ed51a3e617bede6f16fe994071",
    ),
}
FROZEN_ANCHORS = {
    "core/llm_client.py": (
        "e5c0f805e0d10a07e38054316fb9c6423409190cfa0f48bc39694e65c6a4e417"
    )
}
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_HEX = frozenset("0123456789abcdef")


class LocalTextAcceptanceError(RuntimeError):
    """Frozen candidate or external acceptance envelope drifted."""


def _parts(relative: str) -> tuple[str, ...]:
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or "\x00" in relative
    ):
        raise LocalTextAcceptanceError("non-canonical path")
    parsed = PurePosixPath(relative)
    if (
        parsed.is_absolute()
        or parsed.as_posix() != relative
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise LocalTextAcceptanceError("non-canonical path")
    return parsed.parts


def _path(project: Path, relative: str) -> Path:
    root_info = project.lstat()
    root = project.resolve(strict=True)
    if stat.S_ISLNK(root_info.st_mode) or (
        getattr(root_info, "st_file_attributes", 0) & _REPARSE
    ):
        raise LocalTextAcceptanceError("project root is linked")
    current = project
    parts = _parts(relative)
    for index, part in enumerate(parts):
        current /= part
        try:
            info = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise LocalTextAcceptanceError(f"path unavailable: {relative}") from exc
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0) & _REPARSE
        ):
            raise LocalTextAcceptanceError(f"path is linked: {relative}")
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise LocalTextAcceptanceError(f"path escaped: {relative}") from exc
        if resolved.name != part:
            raise LocalTextAcceptanceError(f"path alias: {relative}")
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise LocalTextAcceptanceError(f"ancestor is not directory: {relative}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise LocalTextAcceptanceError(f"path is not regular: {relative}")
    return current


def _bytes(project: Path, relative: str) -> bytes:
    return _path(project, relative).read_bytes()


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _json(project: Path, relative: str) -> dict[str, object]:
    try:
        value = json.loads(_bytes(project, relative).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalTextAcceptanceError(f"invalid JSON: {relative}") from exc
    if type(value) is not dict:
        raise LocalTextAcceptanceError(f"JSON object required: {relative}")
    return value


def _artifact_root(artifacts: dict[str, str]) -> str:
    payload = "".join(f"{path}\0{artifacts[path]}\n" for path in sorted(artifacts))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _manifest_rows(project: Path, relative: str) -> dict[str, str]:
    try:
        lines = _bytes(project, relative).decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise LocalTextAcceptanceError("manifest must be ASCII") from exc
    if not 1 <= len(lines) <= 64:
        raise LocalTextAcceptanceError("manifest row limit violated")
    rows: dict[str, str] = {}
    for line in lines:
        if len(line) < 67 or line[64:66] != "  ":
            raise LocalTextAcceptanceError("invalid manifest row")
        digest, target = line[:64], line[66:]
        if (
            any(character not in _HEX for character in digest)
            or target in rows
            or target != PurePosixPath(target).as_posix()
        ):
            raise LocalTextAcceptanceError("invalid manifest row")
        _parts(target)
        rows[target] = digest
    return rows


def _verify_rows(
    project: Path, relative: str, expected_members: set[str]
) -> dict[str, str]:
    rows = _manifest_rows(project, relative)
    if set(rows) != expected_members:
        raise LocalTextAcceptanceError(f"manifest membership drifted: {relative}")
    for target, expected in rows.items():
        if _digest(project, target) != expected:
            raise LocalTextAcceptanceError(f"manifest leaf drifted: {target}")
    return rows


def _verify_candidate(project: Path) -> dict[str, object]:
    if _digest(project, CANDIDATE_MANIFEST) != CANDIDATE_MANIFEST_SHA256:
        raise LocalTextAcceptanceError("candidate manifest drifted")
    manifest = _json(project, CANDIDATE_MANIFEST)
    if (
        manifest.get("schema") != "OnyxPhase6LocalTextCompatibility.v1"
        or manifest.get("candidate") != "phase6-local-text-compat-candidate-001"
        or manifest.get("status") != "candidate_default_off_not_live"
        or manifest.get("artifact_root_sha256") != CANDIDATE_ROOT_SHA256
    ):
        raise LocalTextAcceptanceError("candidate identity drifted")
    if manifest.get("activation") != {
        "flag": "ONYX_PHASE6_LOCAL_TEXT_COMPAT_V1",
        "enabled_value": "true",
        "exact": "ONYX_PHASE6_LOCAL_TEXT_COMPAT_V1=true",
        "default": "off",
        "factory_only": True,
        "explicit_install_required": True,
        "live_wiring": False,
    }:
        raise LocalTextAcceptanceError("candidate activation drifted")
    entries = manifest.get("artifacts")
    if type(entries) is not list or len(entries) != len(CANDIDATE_ARTIFACTS):
        raise LocalTextAcceptanceError("candidate closure cardinality drifted")
    observed: dict[str, str] = {}
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "bytes", "sha256"}:
            raise LocalTextAcceptanceError("candidate artifact row drifted")
        relative = entry["path"]
        if type(relative) is not str or relative not in CANDIDATE_ARTIFACTS:
            raise LocalTextAcceptanceError("candidate artifact member drifted")
        if relative in observed:
            raise LocalTextAcceptanceError("candidate artifact duplicated")
        expected_size, expected_digest = CANDIDATE_ARTIFACTS[relative]
        target = _path(project, relative)
        if (
            entry["bytes"] != expected_size
            or entry["sha256"] != expected_digest
            or target.stat().st_size != expected_size
            or _digest(project, relative) != expected_digest
        ):
            raise LocalTextAcceptanceError(f"candidate artifact drifted: {relative}")
        observed[relative] = expected_digest
    if set(observed) != set(CANDIDATE_ARTIFACTS):
        raise LocalTextAcceptanceError("candidate closure incomplete")
    if _artifact_root(observed) != CANDIDATE_ROOT_SHA256:
        raise LocalTextAcceptanceError("candidate artifact root drifted")
    if manifest.get("frozen_anchors") != FROZEN_ANCHORS:
        raise LocalTextAcceptanceError("frozen anchors drifted")
    for relative, expected in FROZEN_ANCHORS.items():
        if _digest(project, relative) != expected:
            raise LocalTextAcceptanceError(f"frozen anchor drifted: {relative}")
    contracts = manifest.get("contracts")
    if type(contracts) is not dict:
        raise LocalTextAcceptanceError("candidate contracts missing")
    required = {
        "providers": ["ollama", "openai_compatible"],
        "transport": "factory_injected_only",
        "privacy": "http_loopback_only",
        "network_calls": 0,
        "real_provider_calls": 0,
        "silent_cross_routing": False,
        "streaming_nonstreaming": True,
        "tool_call_parity": True,
        "timeout_enforcement": "injected_transport",
        "blocking_cancellation": "cooperative",
        "lazy_stream_failure_mapping": True,
        "owner_drift_restoration": True,
        "exact_rollback": True,
        "llm_client_bytes_changed": False,
    }
    for name, expected in required.items():
        if contracts.get(name) != expected:
            raise LocalTextAcceptanceError(f"candidate contract drifted: {name}")
    source = _bytes(project, "core/phase6_local_text_compat_v1.py").decode("utf-8")
    tree = ast.parse(source)
    forbidden = {"aiohttp", "httpx", "openai", "requests", "socket"}
    imports = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    if imports & forbidden:
        raise LocalTextAcceptanceError("candidate gained network/provider import")
    return manifest


def _verify_acceptance_envelope(project: Path) -> dict[str, object]:
    _verify_rows(
        project,
        SOURCE_MANIFEST,
        {
            "scripts/verify_phase6_local_text_compat_v1_acceptance.py",
            "tests/test_phase6_local_text_compat_v1_acceptance.py",
        },
    )
    _verify_rows(
        project,
        ARTIFACT_MANIFEST,
        {ACCEPTANCE_RECORD, ACCEPTANCE_METADATA},
    )
    _verify_rows(project, ACCEPTANCE_MANIFEST, {ACCEPTANCE_RECORD})
    metadata = _json(project, ACCEPTANCE_METADATA)
    if (
        metadata.get("schema") != "onyx.external-acceptance.v1"
        or metadata.get("acceptance_id") != ACCEPTANCE_ID
        or metadata.get("decision") != "accepted"
        or metadata.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata.get("candidate_manifest_sha256") != CANDIDATE_MANIFEST_SHA256
        or metadata.get("artifact_root_sha256") != CANDIDATE_ROOT_SHA256
        or metadata.get("default_off") is not True
        or metadata.get("factory_only") is not True
        or metadata.get("live_activation") is not False
        or metadata.get("phase6_exit") is not False
    ):
        raise LocalTextAcceptanceError("acceptance metadata drifted")
    record = _bytes(project, ACCEPTANCE_RECORD).decode("utf-8")
    for required in (
        "ACCEPTED",
        "P0: 0",
        "P1: 0",
        "P2: 0",
        "P3: 0",
        CANDIDATE_MANIFEST_SHA256,
        CANDIDATE_ROOT_SHA256,
        "default-off",
        "factory-only",
    ):
        if required not in record:
            raise LocalTextAcceptanceError("acceptance record drifted")
    return metadata


def _live_scan(project: Path) -> int:
    values = [project / "main.py", project / "ui.py"]
    for root_name in ("dashboard", "runtime", "packaging", "qml"):
        root = project / root_name
        if root.is_dir():
            values.extend(path for path in root.rglob("*") if path.is_file())
    values.extend(
        path for path in (project / "scripts").glob("launch_*") if path.is_file()
    )
    checked = 0
    for path in sorted(set(values)):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        checked += 1
        if (
            "phase6_local_text_compat_v1" in text
            or "ONYX_PHASE6_LOCAL_TEXT_COMPAT_V1" in text
        ):
            raise LocalTextAcceptanceError(f"candidate entered live surface: {path}")
    return checked


def verify(project: Path = PROJECT, *, run_tests: bool = True) -> dict[str, object]:
    _verify_candidate(project)
    metadata = _verify_acceptance_envelope(project)
    live_checked = _live_scan(project)
    if run_tests:
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "tests/test_phase6_local_text_compat_v1.py",
            ],
            cwd=project,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if result.returncode or "31 passed" not in result.stdout:
            raise LocalTextAcceptanceError(result.stdout + result.stderr)
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "decision": metadata["decision"],
        "candidate_manifest_sha256": CANDIDATE_MANIFEST_SHA256,
        "artifact_root_sha256": CANDIDATE_ROOT_SHA256,
        "focused_passed": 31,
        "live_files_checked": live_checked,
        "network_calls": 0,
        "provider_calls": 0,
        "marker": MARKER,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
