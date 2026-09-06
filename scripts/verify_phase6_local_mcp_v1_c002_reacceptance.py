"""Reaccept the immutable Local MCP V1 candidate against Activation V10 C003."""

from __future__ import annotations

import hashlib
import json
import stat
import subprocess
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
MARKER = "P6_LOCAL_MCP_V1_C002_REACCEPTANCE_OK"
ORIGINAL_MANIFEST = "docs/onyx/checkpoints/phase6-local-mcp-v1/manifest.json"
ORIGINAL_MANIFEST_SHA256 = (
    "9529946b80d4ee8c4434acd2db064afab03bbb049482e82126a57151fc395921"
)
ORIGINAL_ARTIFACT_ROOT = (
    "c0efe67f8e28fb6444456d535f482c5af783d20508fcb48a618dd3b3ce693f6f"
)
OLD_V10_ANCHOR = "608d38456cdd4ac1f4b2c7e1128fce9feec1725422f204370fed58b27db79cc8"
CURRENT_V10_SOURCE = "core/onyx_live_activation_v10.py"
CURRENT_V10_SOURCE_SHA256 = (
    "546842aeceb8fc5839d0782658ea4272d4bea999b786b96d38d7968c419a2ee7"
)
V10_C003_EVIDENCE = {
    "docs/onyx/checkpoints/onyx-live-activation-v10/manifest.json": (
        "b22459a5315370f179089cf67d501a687305c2147d2c68ef132575326d47e236"
    ),
    "scripts/verify_onyx_live_activation_v10_c003_acceptance.py": (
        "f52d0befe3aed08ba400523eeb14c5ba85087b0fabee4aae21da680b909d78d8"
    ),
    "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V10-C003-E6-001.md": (
        "4134d37498ccefe9044782c5c4edace53f14c29396117eac7a1181006cc38154"
    ),
    (
        "docs/onyx/acceptance/"
        "VE-ONYX-LIVE-ACTIVATION-V10-C003-E6-001.manifest.json"
    ): "31f4d19c25d137edff5f9c1a148e141e66174709021cbda73b56788fd9537ce0",
}
UNCHANGED_ANCHORS = {
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
}
_REPARSE_ATTRIBUTE = 0x400


class ReacceptanceError(RuntimeError):
    """The dependency-only reacceptance envelope drifted."""


def _path(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or pure.is_absolute()
        or str(pure) != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ReacceptanceError(f"noncanonical path: {relative!r}")
    root = ROOT.resolve(strict=True)
    current = ROOT
    for index, part in enumerate(pure.parts):
        current /= part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        ):
            raise ReacceptanceError(f"linked path denied: {relative}")
        current.resolve(strict=True).relative_to(root)
        if index < len(pure.parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ReacceptanceError(f"non-directory ancestor: {relative}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise ReacceptanceError(f"non-regular leaf: {relative}")
    return current


def _digest(relative: str) -> str:
    return hashlib.sha256(_path(relative).read_bytes()).hexdigest()


def _root(records: dict[str, str]) -> str:
    payload = "".join(
        f"{relative}\0{records[relative]}\n" for relative in sorted(records)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _run_local_mcp_tests() -> None:
    command = [
        str(ROOT / ".venv/Scripts/python.exe"),
        "-B",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        ".pytest-p6-local-mcp-v1-c002-reacceptance",
        "tests/test_phase6_local_mcp_v1.py",
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if completed.returncode or "27 passed" not in completed.stdout:
        raise ReacceptanceError(completed.stdout + completed.stderr)


def verify(*, run_tests: bool = True) -> dict[str, object]:
    if _digest(ORIGINAL_MANIFEST) != ORIGINAL_MANIFEST_SHA256:
        raise ReacceptanceError("original candidate manifest drift")
    candidate = json.loads(_path(ORIGINAL_MANIFEST).read_text(encoding="utf-8"))
    if (
        candidate.get("candidate") != "phase6-local-mcp-candidate-001"
        or candidate.get("artifact_root_sha256") != ORIGINAL_ARTIFACT_ROOT
    ):
        raise ReacceptanceError("original candidate identity drift")

    records: dict[str, str] = {}
    for item in candidate.get("artifacts", ()):
        if type(item) is not dict or type(item.get("path")) is not str:
            raise ReacceptanceError("malformed original artifact")
        relative = item["path"]
        observed = _digest(relative)
        if (
            observed != item.get("sha256")
            or _path(relative).stat().st_size != item.get("bytes")
        ):
            raise ReacceptanceError(f"original artifact drift: {relative}")
        records[relative] = observed
    if len(records) != 6 or _root(records) != ORIGINAL_ARTIFACT_ROOT:
        raise ReacceptanceError("original artifact closure drift")

    anchors = candidate.get("frozen_anchors")
    if type(anchors) is not dict or anchors.get(CURRENT_V10_SOURCE) != OLD_V10_ANCHOR:
        raise ReacceptanceError("historical V10 anchor is not exact")
    for relative, expected in UNCHANGED_ANCHORS.items():
        if anchors.get(relative) != expected or _digest(relative) != expected:
            raise ReacceptanceError(f"unchanged anchor drift: {relative}")

    if _digest(CURRENT_V10_SOURCE) != CURRENT_V10_SOURCE_SHA256:
        raise ReacceptanceError("current Activation V10 source drift")
    for relative, expected in V10_C003_EVIDENCE.items():
        if _digest(relative) != expected:
            raise ReacceptanceError(f"Activation V10 C003 evidence drift: {relative}")
    activation_manifest = json.loads(
        _path(
            "docs/onyx/checkpoints/onyx-live-activation-v10/manifest.json"
        ).read_text(encoding="utf-8")
    )
    if (
        activation_manifest.get("candidate") != "onyx-live-activation-v10-c003"
        or activation_manifest.get("artifact_root_sha256")
        != "5f1b32f01fe7a481f27062b90e5cbbf9816a7b6306547b7a0fe7ddf2a26a56c4"
    ):
        raise ReacceptanceError("Activation V10 C003 identity drift")
    metadata = json.loads(
        _path(
            "docs/onyx/acceptance/"
            "VE-ONYX-LIVE-ACTIVATION-V10-C003-E6-001.manifest.json"
        ).read_text(encoding="utf-8")
    )
    if (
        metadata.get("decision") != "accepted"
        or metadata.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata.get("candidate_manifest_sha256")
        != V10_C003_EVIDENCE[
            "docs/onyx/checkpoints/onyx-live-activation-v10/manifest.json"
        ]
    ):
        raise ReacceptanceError("Activation V10 C003 acceptance drift")

    if run_tests:
        _run_local_mcp_tests()
    return {
        "candidate": "phase6-local-mcp-candidate-001",
        "reacceptance": "c002-activation-v10-c003",
        "original_artifacts": 6,
        "unchanged_anchors": 4,
        "superseded_anchor": "core/onyx_live_activation_v10.py",
        "activation_v10": "candidate-003-e6-accepted",
        "focused": 27 if run_tests else 0,
        "network_calls": 0,
        "provider_calls": 0,
        "live_activation": False,
        "phase6_exit": False,
    }


if __name__ == "__main__":
    print(MARKER, json.dumps(verify(), sort_keys=True))
