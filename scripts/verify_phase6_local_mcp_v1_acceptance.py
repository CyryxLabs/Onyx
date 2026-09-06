"""Verify the external E6 acceptance envelope for Phase 6 Local MCP V1."""

from __future__ import annotations

import hashlib
import json
import stat
import subprocess
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[1]
ACCEPTANCE_ID = "VE-P6-LOCAL-MCP-V1-E6-001"
MARKER = "P6_LOCAL_MCP_V1_ACCEPTANCE_OK"
CANDIDATE_MANIFEST = "docs/onyx/checkpoints/phase6-local-mcp-v1/manifest.json"
CANDIDATE_MANIFEST_SHA256 = (
    "9529946b80d4ee8c4434acd2db064afab03bbb049482e82126a57151fc395921"
)
CANDIDATE_ROOT_SHA256 = (
    "c0efe67f8e28fb6444456d535f482c5af783d20508fcb48a618dd3b3ce693f6f"
)
ACCEPTANCE_RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
ACCEPTANCE_METADATA = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
SOURCE_MANIFEST = "docs/onyx/VE-SOURCE-P6-LOCAL-MCP-V1-E6-001.sha256"
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P6-LOCAL-MCP-V1-E6-001.sha256"
ACCEPTANCE_MANIFEST = "docs/onyx/VE-ACCEPTANCE-P6-LOCAL-MCP-V1-E6-001.sha256"

CANDIDATE_ARTIFACTS = {
    "core/phase6_local_mcp_v1.py": (
        39057,
        "4c083516438c6ef620db11f91996a56d0fec4cd2538cb603d8c5c0e5872f6975",
    ),
    "tests/test_phase6_local_mcp_v1.py": (
        12809,
        "50e287a44a9d54b7156a8eb844353b917c413150378c9d110983c1b740e83e23",
    ),
    "tests/fixtures/phase6_local_mcp_server.py": (
        9382,
        "1f92545f11d91840c588fdb9f7384aded6f8906a2ea5bb30f1e1d36af762910a",
    ),
    "scripts/verify_phase6_local_mcp_v1.py": (
        5490,
        "037c3acd9e6f9aa9bd0294aa22a5bf7984924ddf696c8a3da72b6dccfbccd0cc",
    ),
    "docs/onyx/adrs/ADR-0022-phase6-local-read-only-mcp-v1.md": (
        2359,
        "607c6fe6ae95ed26685bf37fc1d0c82547811153c029317f3465b1af91ecfd70",
    ),
    ("docs/onyx/checkpoints/phase6-local-mcp-v1/PHASE6_LOCAL_MCP_V1_CHECKPOINT.md"): (
        3642,
        "036477b4783530c4a488e45292658827278cd9b4f90f83fb28837b2d9a569d45",
    ),
}
FROZEN_ANCHORS = {
    "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
    "core/phase5_integration_v3.py": (
        "52d48c121da485c024811e6cd3fafbabaed971175d7cb41ad23358c5c2879b0d"
    ),
    "core/phase6_agentic_core_v6.py": (
        "38f68d7dd8eb04fe7c9caa956db5a52d0a96426bab6a45f07b96e67e45d8001a"
    ),
    "core/phase6_live_integration_v2.py": (
        "e3194a0d8e206d33218bc8291cbd518788e8dfb3931adfd2f067908655d409b5"
    ),
    "core/onyx_live_activation_v10.py": (
        "608d38456cdd4ac1f4b2c7e1128fce9feec1725422f204370fed58b27db79cc8"
    ),
}
_REPARSE_ATTRIBUTE = 0x400


class LocalMCPV1AcceptanceError(RuntimeError):
    """The external acceptance envelope is incomplete or drifted."""


def _path(project: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or pure.is_absolute()
        or str(pure) != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise LocalMCPV1AcceptanceError("noncanonical acceptance path")
    root = project.resolve(strict=True)
    current = project
    for index, part in enumerate(pure.parts):
        current /= part
        try:
            info = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise LocalMCPV1AcceptanceError(
                f"acceptance path unavailable: {relative}"
            ) from exc
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        ):
            raise LocalMCPV1AcceptanceError(f"acceptance path is linked: {relative}")
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise LocalMCPV1AcceptanceError(
                f"acceptance path escapes project: {relative}"
            ) from exc
        if index < len(pure.parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise LocalMCPV1AcceptanceError(
                f"acceptance ancestor is not a directory: {relative}"
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        raise LocalMCPV1AcceptanceError(f"acceptance leaf is not regular: {relative}")
    return current


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_path(project, relative).read_bytes()).hexdigest()


def _json(project: Path, relative: str) -> dict[str, object]:
    try:
        value = json.loads(_path(project, relative).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LocalMCPV1AcceptanceError(
            f"acceptance JSON is invalid: {relative}"
        ) from exc
    if type(value) is not dict:
        raise LocalMCPV1AcceptanceError("acceptance JSON must be an object")
    return value


def _root(records: dict[str, str]) -> str:
    payload = "".join(
        f"{relative}\0{records[relative]}\n" for relative in sorted(records)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _manifest_rows(project: Path, relative: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    text = _path(project, relative).read_text(encoding="utf-8")
    for line in text.splitlines():
        parts = line.split("  ", 1)
        if (
            len(parts) != 2
            or len(parts[0]) != 64
            or any(char not in "0123456789abcdef" for char in parts[0])
            or parts[1] in rows
        ):
            raise LocalMCPV1AcceptanceError(f"invalid SHA-256 manifest row: {relative}")
        _path(project, parts[1])
        rows[parts[1]] = parts[0]
    if not rows:
        raise LocalMCPV1AcceptanceError(f"empty SHA-256 manifest: {relative}")
    return rows


def _run(command: list[str], marker: str, timeout: int = 900) -> None:
    completed = subprocess.run(
        command,
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode or marker not in completed.stdout:
        raise LocalMCPV1AcceptanceError(completed.stdout + completed.stderr)


def verify() -> dict[str, object]:
    if _digest(PROJECT, CANDIDATE_MANIFEST) != CANDIDATE_MANIFEST_SHA256:
        raise LocalMCPV1AcceptanceError("candidate manifest drift")
    candidate = _json(PROJECT, CANDIDATE_MANIFEST)
    records: dict[str, str] = {}
    for entry in candidate.get("artifacts", ()):
        if type(entry) is not dict:
            raise LocalMCPV1AcceptanceError("candidate artifact is malformed")
        relative = entry.get("path")
        if type(relative) is not str or relative not in CANDIDATE_ARTIFACTS:
            raise LocalMCPV1AcceptanceError("candidate artifact closure drift")
        expected_size, expected_digest = CANDIDATE_ARTIFACTS[relative]
        path = _path(PROJECT, relative)
        observed = _digest(PROJECT, relative)
        if (
            path.stat().st_size != expected_size
            or entry.get("bytes") != expected_size
            or observed != expected_digest
            or entry.get("sha256") != expected_digest
        ):
            raise LocalMCPV1AcceptanceError(f"candidate artifact drift: {relative}")
        records[relative] = observed
    if (
        len(records) != len(CANDIDATE_ARTIFACTS)
        or _root(records) != CANDIDATE_ROOT_SHA256
        or candidate.get("artifact_root_sha256") != CANDIDATE_ROOT_SHA256
    ):
        raise LocalMCPV1AcceptanceError("candidate artifact root drift")
    for relative, expected in FROZEN_ANCHORS.items():
        if _digest(PROJECT, relative) != expected:
            raise LocalMCPV1AcceptanceError(f"frozen anchor drift: {relative}")

    source = _manifest_rows(PROJECT, SOURCE_MANIFEST)
    expected_source_paths = {
        "scripts/verify_phase6_local_mcp_v1_acceptance.py",
        "tests/test_phase6_local_mcp_v1_acceptance.py",
    }
    if set(source) != expected_source_paths or any(
        _digest(PROJECT, relative) != digest for relative, digest in source.items()
    ):
        raise LocalMCPV1AcceptanceError("acceptance source manifest drift")
    artifacts = _manifest_rows(PROJECT, ARTIFACT_MANIFEST)
    if set(artifacts) != {ACCEPTANCE_RECORD, ACCEPTANCE_METADATA} or any(
        _digest(PROJECT, relative) != digest for relative, digest in artifacts.items()
    ):
        raise LocalMCPV1AcceptanceError("acceptance artifact manifest drift")
    final = _manifest_rows(PROJECT, ACCEPTANCE_MANIFEST)
    if final != {ACCEPTANCE_RECORD: artifacts[ACCEPTANCE_RECORD]}:
        raise LocalMCPV1AcceptanceError("final acceptance manifest drift")

    metadata = _json(PROJECT, ACCEPTANCE_METADATA)
    expected_findings = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    if (
        metadata.get("acceptance_id") != ACCEPTANCE_ID
        or metadata.get("decision") != "accepted"
        or metadata.get("findings") != expected_findings
        or metadata.get("candidate_manifest_sha256") != CANDIDATE_MANIFEST_SHA256
        or metadata.get("artifact_root_sha256") != CANDIDATE_ROOT_SHA256
        or metadata.get("artifact_count") != 6
        or metadata.get("focused") != {"passed": 27, "failed": 0}
        or metadata.get("cumulative") != {"passed": 59, "failed": 0}
        or metadata.get("network_calls") != 0
        or metadata.get("provider_calls") != 0
        or metadata.get("live_activation") is not False
    ):
        raise LocalMCPV1AcceptanceError("acceptance metadata drift")

    python = str(PROJECT / ".venv/Scripts/python.exe")
    _run(
        [python, "-I", "-S", "-B", "scripts/verify_phase6_local_mcp_v1.py"],
        "P6_LOCAL_MCP_V1_OK",
    )
    _run(
        [
            python,
            "-B",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            ".pytest-p6-local-mcp-e6-focused",
            "tests/test_phase6_local_mcp_v1.py",
        ],
        "27 passed",
    )
    _run(
        [
            python,
            "-B",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            ".pytest-p6-local-mcp-e6-cumulative",
            "tests/test_phase6_agentic_core_v6_acceptance.py",
            "tests/test_phase6_live_integration_v2_acceptance.py",
            "tests/test_phase6_gemini_live_compat_c003_acceptance.py",
            "tests/test_phase6_local_mcp_v1.py",
        ],
        "59 passed",
    )
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "decision": "accepted",
        "candidate_manifest_sha256": CANDIDATE_MANIFEST_SHA256,
        "artifact_root_sha256": CANDIDATE_ROOT_SHA256,
        "artifacts": 6,
        "frozen_anchors": 5,
        "focused_passed": 27,
        "cumulative_passed": 59,
        "findings": expected_findings,
        "network_calls": 0,
        "provider_calls": 0,
        "default_off": True,
        "live_activation": False,
        "phase6_exit": False,
    }


if __name__ == "__main__":
    print(MARKER, json.dumps(verify(), sort_keys=True))
