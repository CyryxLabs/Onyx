"""Verify the external E6 acceptance for frozen Phase 6 Agentic Core V6."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import stat

from scripts.verify_legacy_evidence_retirement_v1 import (
    LegacyEvidenceRetirementError,
    classify_historical_artifact,
)


PROJECT = Path(__file__).resolve().parents[1]
ACCEPTANCE_ID = "VE-P6-AGENTIC-CORE-V6-E6-001"
ACCEPTANCE_RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
ACCEPTANCE_MANIFEST = "docs/onyx/VE-ACCEPTANCE-P6-AGENTIC-CORE-V6-E6-001.sha256"
V6_MANIFEST = "docs/onyx/checkpoints/phase6-agentic-core-v6/manifest.json"
V6_MANIFEST_SHA256 = "cedea0a3ed3bf0c1ed069c589e2eb78035caa58886ced0c69658ac71d7bb4a15"
V6_ROOT_SHA256 = "ca7d7f3281d9926848696e25befe63373738596dbc7e9b5bdaf95325922b06b0"
MISSION_STORE = "core/missions.py"
MISSION_STORE_SHA256 = (
    "fe2074eb132c09beecb9f13c5151659e745cf888676c4244c037e0a7ed7f2fe5"
)
ACCEPTANCE_MARKER = "P6_AGENTIC_CORE_V6_ACCEPTANCE_OK"
_REPARSE_ATTRIBUTE = 0x400

V6_ANCHORS = {
    "core/phase6_agentic_core_v6.py": (
        "38f68d7dd8eb04fe7c9caa956db5a52d0a96426bab6a45f07b96e67e45d8001a"
    ),
    "tests/test_phase6_agentic_core_v6.py": (
        "83218e07beaa85e570998936278cb3cd53fcaee9f0b37d55cb675b35dedf8dc0"
    ),
    "docs/onyx/adrs/ADR-0015-phase6-agentic-core-v6-ascii-sql-lexing.md": (
        "b5f53cf7e79cb1dc65eedead54b83b97136903838b665216123c6bd56ecad77a"
    ),
    "docs/onyx/rejections/PHASE6_AGENTIC_CORE_V5_REJECTION.md": (
        "1b30f6e940a5c3666f252b0e805d57dfd08009067e6bb73600677365b0b7f4d9"
    ),
    (
        "docs/onyx/checkpoints/phase6-agentic-core-v6/"
        "PHASE6_AGENTIC_CORE_V6_CHECKPOINT.md"
    ): "96504a9007b919dc8ccb1ef4373d094580a382c785e772e49630726cf4acc124",
}

HISTORICAL_MANIFESTS = {
    1: (
        "82eea75a58beec613eba2823d928a76b6d520d9f76b4e4f6b8c811058c77cbd1",
        "192556429c262c63161bfcf1fe07d27e3e3470336fd6d97e6f8bacbf7816f0e1",
    ),
    2: (
        "c1608dbb7042b1f940422f9ca7c8791eb6935ec15505fe2859c0f756e129dcbc",
        "5d8dd8b9d65f8aae17224b2cbeed74546c3c563eba76a87a9f53ac3ba7104ec4",
    ),
    3: (
        "3d77e96c6561445adb8b2cdb61e400d4ba896d6556ed0c357bb270c501d98288",
        "9f0f710373441a86d6d77bf908cfc7cf81b7f06faab9b293dcba5d23dd33bf27",
    ),
    4: (
        "f831f52ff257b877f6dbb7b2eac279cee7c2ffd6c84b5761998ac37689e14315",
        "bdcdee76e4209c071705d4ad76a69515efd4dd6fe395005d3fa653da9c51b0cd",
    ),
    5: (
        "b879f2d3266601ec76fec2fa08c4dcb6364217d6b23d7d63811d700c769b8958",
        "9913b6731fd4ccdb103ce511ddb0b4133be456b4acd878dd45091f522d9d1fe4",
    ),
}

REJECTIONS = {
    1: "ba56145ef4404556ff70c47a88c7e8398e1c1f6959bda05dcc1cbaa96b9ba700",
    2: "74198315f36a100c1e2e1c5f31edfdb9df0c8cea0ef421f65d1910121242b513",
    3: "07958248641645d74fc7b87f9f6d8bf944179cc72694d10a80e7b21cd4aa370d",
    4: "9858ed2922b270a5a8d82ffb8cf4f29144ae359ded23e8322f2292416e8a41e5",
    5: "1b30f6e940a5c3666f252b0e805d57dfd08009067e6bb73600677365b0b7f4d9",
}


class AgenticCoreV6AcceptanceError(RuntimeError):
    """The external acceptance or one of its frozen anchors is invalid."""


def _canonical_relative(relative: str) -> tuple[str, ...]:
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or "\x00" in relative
    ):
        raise AgenticCoreV6AcceptanceError("acceptance path is not canonical")
    parsed = PurePosixPath(relative)
    if (
        parsed.is_absolute()
        or str(parsed) != relative
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise AgenticCoreV6AcceptanceError("acceptance path is not canonical")
    return parsed.parts


def _regular_path(project: Path, relative: str) -> Path:
    parts = _canonical_relative(relative)
    root = project.absolute()
    try:
        root_info = root.lstat()
        root_resolved = root.resolve(strict=True)
    except OSError as exc:
        raise AgenticCoreV6AcceptanceError("acceptance root is unavailable") from exc
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or getattr(root_info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        or root_resolved != root
    ):
        raise AgenticCoreV6AcceptanceError("acceptance root is linked or aliased")
    current = root
    for index, part in enumerate(parts):
        try:
            entries = {entry.name: entry for entry in current.iterdir()}
        except OSError as exc:
            raise AgenticCoreV6AcceptanceError(
                f"acceptance ancestor is unavailable: {relative}"
            ) from exc
        if part not in entries:
            raise AgenticCoreV6AcceptanceError(
                f"acceptance path is missing or case-mismatched: {relative}"
            )
        current = entries[part]
        try:
            metadata = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise AgenticCoreV6AcceptanceError(
                f"acceptance path is unavailable: {relative}"
            ) from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        ):
            raise AgenticCoreV6AcceptanceError(
                f"acceptance path uses a link/reparse point: {relative}"
            )
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise AgenticCoreV6AcceptanceError(
                f"acceptance path leaves the project: {relative}"
            ) from exc
        if resolved.name != part:
            raise AgenticCoreV6AcceptanceError(
                f"acceptance path uses a name alias: {relative}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise AgenticCoreV6AcceptanceError(
                f"acceptance ancestor is not a directory: {relative}"
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        raise AgenticCoreV6AcceptanceError(
            f"acceptance leaf is not a regular file: {relative}"
        )
    return current


def _bytes(project: Path, relative: str) -> bytes:
    try:
        return _regular_path(project, relative).read_bytes()
    except OSError as exc:
        raise AgenticCoreV6AcceptanceError(
            f"cannot read acceptance path: {relative}"
        ) from exc


def _text(project: Path, relative: str) -> str:
    raw = _bytes(project, relative)
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AgenticCoreV6AcceptanceError(
            f"acceptance text is not UTF-8: {relative}"
        ) from exc
    if "\r" in value or not value.endswith("\n"):
        raise AgenticCoreV6AcceptanceError(
            f"acceptance text is not canonical LF: {relative}"
        )
    return value


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _require_digest(project: Path, relative: str, expected: str) -> None:
    actual = _digest(project, relative)
    if actual != expected:
        raise AgenticCoreV6AcceptanceError(
            f"acceptance anchor drifted: {relative}: expected {expected}, got {actual}"
        )


def _artifact_root(artifacts: dict[str, str]) -> str:
    if type(artifacts) is not dict or not artifacts:
        raise AgenticCoreV6AcceptanceError("artifact mapping is invalid")
    records: list[str] = []
    for relative, digest in artifacts.items():
        _canonical_relative(relative)
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise AgenticCoreV6AcceptanceError("artifact digest is malformed")
        records.append(f"{relative}\0{digest}")
    return hashlib.sha256("\n".join(sorted(records)).encode("utf-8")).hexdigest()


def _manifest_line(value: str) -> tuple[str, str]:
    lines = value.splitlines()
    if len(lines) != 1:
        raise AgenticCoreV6AcceptanceError(
            "acceptance manifest must contain exactly one record"
        )
    line = lines[0]
    if len(line) < 67 or line[64:66] != "  ":
        raise AgenticCoreV6AcceptanceError("acceptance manifest record is malformed")
    digest, relative = line[:64], line[66:]
    if any(character not in "0123456789abcdef" for character in digest):
        raise AgenticCoreV6AcceptanceError("acceptance manifest digest is malformed")
    _canonical_relative(relative)
    return digest, relative


def _verify_record(project: Path) -> str:
    manifest_digest, manifest_path = _manifest_line(_text(project, ACCEPTANCE_MANIFEST))
    if manifest_path != ACCEPTANCE_RECORD:
        raise AgenticCoreV6AcceptanceError(
            "acceptance manifest points to an unexpected record"
        )
    record_digest = _digest(project, ACCEPTANCE_RECORD)
    if record_digest != manifest_digest:
        raise AgenticCoreV6AcceptanceError(
            "external acceptance record does not match its manifest"
        )
    record = _text(project, ACCEPTANCE_RECORD)
    required = (
        ACCEPTANCE_ID,
        "ACCEPTED — Agentic Core V6 only, isolated/default-off implementation handoff",
        V6_MANIFEST_SHA256,
        V6_ROOT_SHA256,
        MISSION_STORE_SHA256,
        "P0=0, P1=0, P2=0, P3=0",
        "V1-V5 remain **REJECTED**",
        "30 V6 tests",
        "134 cumulative V1-V6 tests",
        "246 tests plus 44 subtests",
        "36-node closure",
        "V6 remains isolated, default-off and unwired",
        "live provider adapters, `local_catalog` binding",
        "installed `ExternalAgent` execution",
    )
    missing = [item for item in required if item not in record]
    if missing:
        raise AgenticCoreV6AcceptanceError(
            f"acceptance record is missing required binding: {missing[0]}"
        )
    return record_digest


def _verify_bundle(
    project: Path,
    relative: str,
    expected_manifest: str,
    expected_root: str,
    *,
    version: int,
) -> int:
    _require_digest(project, relative, expected_manifest)
    try:
        manifest = json.loads(_text(project, relative))
    except (json.JSONDecodeError, TypeError) as exc:
        raise AgenticCoreV6AcceptanceError("candidate manifest is invalid") from exc
    if (
        type(manifest) is not dict
        or manifest.get("status") != "candidate_default_off_unaccepted"
        or type(manifest.get("activation")) is not dict
        or manifest["activation"].get("feature_flag")
        != f"ONYX_PHASE6_AGENTIC_CORE_V{version}"
        or manifest["activation"].get("default") != "off"
        or manifest["activation"].get("live_wiring") is not False
        or manifest.get("artifact_root_sha256") != expected_root
    ):
        raise AgenticCoreV6AcceptanceError(
            f"V{version} manifest lost its frozen default-off contract"
        )
    entries = manifest.get("artifacts")
    if type(entries) is not list or not entries:
        raise AgenticCoreV6AcceptanceError(f"V{version} artifact closure is invalid")
    artifacts: dict[str, str] = {}
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "bytes", "sha256"}:
            raise AgenticCoreV6AcceptanceError(
                f"V{version} artifact entry is malformed"
            )
        relative_path = entry["path"]
        digest = entry["sha256"]
        if type(entry["bytes"]) is not int or entry["bytes"] < 0:
            raise AgenticCoreV6AcceptanceError(
                f"V{version} artifact byte count is invalid"
            )
        try:
            classify_historical_artifact(
                project,
                relative_path,
                digest,
                historical_bytes=entry["bytes"],
            )
        except LegacyEvidenceRetirementError as exc:
            raise AgenticCoreV6AcceptanceError(str(exc)) from exc
        if relative_path in artifacts:
            raise AgenticCoreV6AcceptanceError(
                f"V{version} artifact path is duplicated"
            )
        artifacts[relative_path] = digest
    if _artifact_root(artifacts) != expected_root:
        raise AgenticCoreV6AcceptanceError(
            f"V{version} artifact root does not recompute"
        )
    return len(artifacts)


def _verify_candidate_anchors(project: Path) -> dict[str, object]:
    for relative, expected in V6_ANCHORS.items():
        try:
            classify_historical_artifact(project, relative, expected)
        except LegacyEvidenceRetirementError as exc:
            raise AgenticCoreV6AcceptanceError(str(exc)) from exc
    try:
        classify_historical_artifact(
            project,
            MISSION_STORE,
            MISSION_STORE_SHA256,
            historical_bytes=89747,
        )
    except LegacyEvidenceRetirementError as exc:
        raise AgenticCoreV6AcceptanceError(str(exc)) from exc
    v6_count = _verify_bundle(
        project,
        V6_MANIFEST,
        V6_MANIFEST_SHA256,
        V6_ROOT_SHA256,
        version=6,
    )
    historical: dict[str, int] = {}
    for version, (manifest_digest, root_digest) in HISTORICAL_MANIFESTS.items():
        relative = f"docs/onyx/checkpoints/phase6-agentic-core-v{version}/manifest.json"
        historical[f"v{version}"] = _verify_bundle(
            project,
            relative,
            manifest_digest,
            root_digest,
            version=version,
        )
        rejection = f"docs/onyx/rejections/PHASE6_AGENTIC_CORE_V{version}_REJECTION.md"
        _require_digest(project, rejection, REJECTIONS[version])
        rejection_text = _text(project, rejection)
        if (
            f"Phase 6 Agentic Core V{version} rejection record" not in rejection_text
            or "REJECTED" not in rejection_text
            or "must not be wired live" not in rejection_text
        ):
            raise AgenticCoreV6AcceptanceError(
                f"V{version} rejection disposition is missing"
            )
    return {"v6_artifacts": v6_count, "historical_artifacts": historical}


def _verify_unwired_and_provider_free(project: Path) -> int:
    live_paths = ["main.py", "ui.py"]
    allowed_suffixes = {".py", ".pyw", ".ps1", ".iss", ".js", ".html", ".qml"}
    for root_name in ("dashboard", "runtime", "packaging"):
        root = project / root_name
        if root.is_dir():
            live_paths.extend(
                path.relative_to(project).as_posix()
                for path in sorted(root.rglob("*"))
                if path.is_file() and path.suffix.lower() in allowed_suffixes
            )
    needles = ("phase6_agentic_core_v6", "ONYX_PHASE6_AGENTIC_CORE_V6")
    wired: list[str] = []
    for relative in live_paths:
        try:
            value = _bytes(project, relative).decode("utf-8")
        except UnicodeDecodeError:
            continue
        if any(needle in value for needle in needles):
            wired.append(relative)
    if wired:
        raise AgenticCoreV6AcceptanceError(
            f"Agentic Core V6 entered a live surface: {wired[0]}"
        )
    source = _text(project, "core/phase6_agentic_core_v6.py")
    forbidden_imports = (
        "import requests",
        "import httpx",
        "import aiohttp",
        "import socket",
        "import urllib",
        "from google",
        "from google.genai",
    )
    if any(item in source for item in forbidden_imports):
        raise AgenticCoreV6AcceptanceError(
            "Agentic Core V6 contains a network/provider import"
        )
    return len(live_paths)


def verify(project: Path = PROJECT) -> dict[str, object]:
    project = Path(project)
    record_sha256 = _verify_record(project)
    closure = _verify_candidate_anchors(project)
    live_files = _verify_unwired_and_provider_free(project)
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "record_sha256": record_sha256,
        "manifest_sha256": V6_MANIFEST_SHA256,
        "artifact_root_sha256": V6_ROOT_SHA256,
        "mission_store_sha256": MISSION_STORE_SHA256,
        "closure": closure,
        "live_files_checked": live_files,
        "severity": {"P0": 0, "P1": 0, "P2": 0, "P3": 0},
        "scope": "phase6-agentic-core-v6-isolated-default-off-unwired-handoff",
    }


def main() -> int:
    payload = verify()
    print(
        ACCEPTANCE_MARKER
        + " "
        + json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
