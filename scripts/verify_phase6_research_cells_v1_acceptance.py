"""Verify external E6 acceptance of Research + Verifier Cells V1."""

from __future__ import annotations

import ast
import hashlib
import json
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any


PROJECT = Path(__file__).resolve(strict=True).parents[1]
ACCEPTANCE_ID = "VE-P6-RESEARCH-CELLS-V1-E6-001"
MARKER = "P6_RESEARCH_CELLS_V1_ACCEPTANCE_OK"
CANDIDATE_MANIFEST = "docs/onyx/checkpoints/phase6-research-cells-v1/manifest.json"
CANDIDATE_MANIFEST_SHA256 = (
    "216e008c7b77df4b464d187ff39547f77ffc7d2d4c59466db16480081a48c3ab"
)
CANDIDATE_ROOT_SHA256 = (
    "8cbf4837eec80a560885cf000b8ba3856f595057c2dbddfa58592c2dda593e4d"
)
ACCEPTANCE_RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
ACCEPTANCE_METADATA = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
SOURCE_MANIFEST = "docs/onyx/VE-SOURCE-P6-RESEARCH-CELLS-V1-E6-001.sha256"
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P6-RESEARCH-CELLS-V1-E6-001.sha256"
ACCEPTANCE_MANIFEST = "docs/onyx/VE-ACCEPTANCE-P6-RESEARCH-CELLS-V1-E6-001.sha256"

CANDIDATE_ARTIFACTS = {
    "core/phase6_research_cells_v1.py": (
        54496,
        "e5eb0c05998aa07c8b63824f93842a602e5fe93f82d566b668bd7afd11ee7013",
    ),
    "tests/test_phase6_research_cells_v1.py": (
        23512,
        "f75d7410150c89f3478d81a3ed2fae193100180c93e98f7e699a9081de9e5dc7",
    ),
    "scripts/verify_phase6_research_cells_v1.py": (
        8563,
        "21fd7fcb928bf56a53df166a2a3c7e8e3a3da93e26f172e67454d18aedf1d479",
    ),
    "docs/onyx/adrs/ADR-0023-phase6-research-cells-v1.md": (
        3471,
        "edae93cce8ed2649c858c972e69b4e548bb28937068d8708feabe6d3012b59ae",
    ),
    (
        "docs/onyx/checkpoints/phase6-research-cells-v1/"
        "PHASE6_RESEARCH_CELLS_V1_CHECKPOINT.md"
    ): (
        3848,
        "c631a83f2fb6496ccf7986fb02e7693d3e5c6c54b7e4eebf832fff0fca050c0b",
    ),
}
FROZEN_ANCHORS = {
    "core/phase6_agentic_core_v1.py": (
        "ab7a6cfec738c31b7beb66ac7a66584f892231ce8a3a2c9e81f30945123cc965"
    ),
    "core/phase6_agentic_core_v6.py": (
        "38f68d7dd8eb04fe7c9caa956db5a52d0a96426bab6a45f07b96e67e45d8001a"
    ),
    "docs/onyx/checkpoints/phase6-agentic-core-v6/manifest.json": (
        "cedea0a3ed3bf0c1ed069c589e2eb78035caa58886ced0c69658ac71d7bb4a15"
    ),
    "docs/onyx/acceptance/VE-P6-AGENTIC-CORE-V6-E6-001.md": (
        "5a42068983942c1bf163fc7b8fddaf8ce336cb5a253a228e319943cc04d8d23d"
    ),
    "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
    "ui.py": "e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b",
    "dashboard/server.py": (
        "4d3142dc9c6a78cfe76f804de2b154334da2d7790484783a993babc92300bae1"
    ),
    "core/phase6_live_wiring_v1.py": (
        "a658f430c10bb992724ad7bbd2ddae94b3c83f8893608fe724b241302b55d55f"
    ),
    "core/onyx_live_activation_v9.py": (
        "deb26314ef3871cb12fc8e3cee936f88e385122fad242c830580421ccb22a9d2"
    ),
}
IDENTITIES = {
    "research": "b56857acde92d5caded13274363758c8e23f3a38817cfb7acabfd8dfb6e7dc18",
    "verifier": "50288fcb69c23315b5f831562c107c44784d9589dcdd2e81651d1e8f71545115",
}
INSTRUCTIONS = {
    "research": "78386ecb9216e6ab7e36a6e59372e21ed97f7297dcb932afe479e60f5a803a5d",
    "verifier": "50c72840e0f4c5417a1fc6966168571b191e961d9d63d5f56de919d78853270f",
}
_REPARSE_ATTRIBUTE = 0x400
_HEX = frozenset("0123456789abcdef")


class ResearchCellsV1AcceptanceError(RuntimeError):
    """The frozen candidate or acceptance envelope drifted."""


def _parts(relative: str) -> tuple[str, ...]:
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or "\x00" in relative
    ):
        raise ResearchCellsV1AcceptanceError("non-canonical path")
    parsed = PurePosixPath(relative)
    if (
        parsed.is_absolute()
        or str(parsed) != relative
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ResearchCellsV1AcceptanceError("non-canonical path")
    return parsed.parts


def _path(project: Path, relative: str) -> Path:
    root = project.resolve(strict=True)
    current = project
    parts = _parts(relative)
    for index, part in enumerate(parts):
        current = current / part
        try:
            info = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise ResearchCellsV1AcceptanceError(
                f"path unavailable: {relative}"
            ) from exc
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        ):
            raise ResearchCellsV1AcceptanceError(f"path is linked: {relative}")
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ResearchCellsV1AcceptanceError(
                f"path escaped project: {relative}"
            ) from exc
        if index < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ResearchCellsV1AcceptanceError(
                f"path ancestor is not a directory: {relative}"
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        raise ResearchCellsV1AcceptanceError(f"path is not regular: {relative}")
    return current


def _bytes(project: Path, relative: str) -> bytes:
    return _path(project, relative).read_bytes()


def _text(project: Path, relative: str) -> str:
    try:
        return _bytes(project, relative).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResearchCellsV1AcceptanceError(f"text is not UTF-8: {relative}") from exc


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _require_digest(project: Path, relative: str, expected: str) -> None:
    if _digest(project, relative) != expected:
        raise ResearchCellsV1AcceptanceError(f"anchor drifted: {relative}")


def _json(project: Path, relative: str) -> dict[str, Any]:
    try:
        value = json.loads(_text(project, relative))
    except json.JSONDecodeError as exc:
        raise ResearchCellsV1AcceptanceError(f"invalid JSON: {relative}") from exc
    if type(value) is not dict:
        raise ResearchCellsV1AcceptanceError(f"JSON object required: {relative}")
    return value


def _artifact_root(artifacts: dict[str, str]) -> str:
    material = "".join(f"{path}\0{artifacts[path]}\n" for path in sorted(artifacts))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _manifest_rows(project: Path, relative: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in _text(project, relative).splitlines():
        if len(line) < 67 or line[64:66] != "  ":
            raise ResearchCellsV1AcceptanceError(f"bad sha256 row: {relative}")
        digest, target = line[:64], line[66:]
        if any(character not in _HEX for character in digest) or target in rows:
            raise ResearchCellsV1AcceptanceError(f"bad sha256 row: {relative}")
        _parts(target)
        rows[target] = digest
    if not rows:
        raise ResearchCellsV1AcceptanceError(f"empty sha256 manifest: {relative}")
    return rows


def _verify_candidate(project: Path) -> dict[str, Any]:
    _require_digest(project, CANDIDATE_MANIFEST, CANDIDATE_MANIFEST_SHA256)
    manifest = _json(project, CANDIDATE_MANIFEST)
    if (
        manifest.get("schema") != "OnyxPhase6ResearchCells.v1"
        or manifest.get("candidate") != "phase6-research-cells-candidate-001"
        or manifest.get("status") != "candidate_default_off_not_live"
        or manifest.get("artifact_root_sha256") != CANDIDATE_ROOT_SHA256
        or manifest.get("activation")
        != {
            "flag": "ONYX_PHASE6_RESEARCH_CELLS_V1",
            "enabled_value": "true",
            "exact": "ONYX_PHASE6_RESEARCH_CELLS_V1=true",
            "default": "off",
            "factory_only": True,
            "live_wiring": False,
        }
    ):
        raise ResearchCellsV1AcceptanceError("candidate identity drifted")
    entries = manifest.get("artifacts")
    if type(entries) is not list or len(entries) != 5:
        raise ResearchCellsV1AcceptanceError("candidate closure is not 5/5")
    observed: dict[str, str] = {}
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "bytes", "sha256"}:
            raise ResearchCellsV1AcceptanceError("artifact row drifted")
        relative = entry["path"]
        if relative in observed or relative not in CANDIDATE_ARTIFACTS:
            raise ResearchCellsV1AcceptanceError("artifact set drifted")
        expected_size, expected_digest = CANDIDATE_ARTIFACTS[relative]
        target = _path(project, relative)
        if (
            target.stat().st_size != expected_size
            or entry["bytes"] != expected_size
            or entry["sha256"] != expected_digest
        ):
            raise ResearchCellsV1AcceptanceError(
                f"artifact metadata drifted: {relative}"
            )
        _require_digest(project, relative, expected_digest)
        observed[relative] = expected_digest
    if set(observed) != set(CANDIDATE_ARTIFACTS):
        raise ResearchCellsV1AcceptanceError("candidate closure incomplete")
    if _artifact_root(observed) != CANDIDATE_ROOT_SHA256:
        raise ResearchCellsV1AcceptanceError("candidate root mismatch")
    if manifest.get("frozen_anchors") != FROZEN_ANCHORS:
        raise ResearchCellsV1AcceptanceError("frozen anchors drifted")
    for relative, expected in FROZEN_ANCHORS.items():
        _require_digest(project, relative, expected)
    contracts = manifest.get("contracts", {})
    required = {
        "distinct_cell_identities": True,
        "distinct_instruction_profile_digests": True,
        "source_and_bundle_hmac": True,
        "research_self_certifies": False,
        "verifier_content_instructions": False,
        "verifier_validates_every_citation": True,
        "exact_claim_citation_projection": True,
        "verifier_generates_facts": False,
        "finalize_requires_independent_accept": True,
        "receipt_authentication": "HMAC-SHA-256",
        "receipt_map_key_binding": True,
        "atomic_replay_conflict": True,
        "candidate_item_byte_bounds": True,
        "provider_invocation": False,
        "network_calls": 0,
    }
    for name, expected in required.items():
        if contracts.get(name) != expected:
            raise ResearchCellsV1AcceptanceError(f"contract drifted: {name}")
    if contracts.get("verifier_decisions") != ["accept", "revise", "reject"]:
        raise ResearchCellsV1AcceptanceError("decision set drifted")
    verification = manifest.get("verification", {})
    if (
        verification.get("focused") != "22 passed"
        or verification.get("cumulative") != "178 passed"
        or verification.get("network_calls") != 0
        or verification.get("live_activation") is not False
        or verification.get("e6") != "not_performed"
    ):
        raise ResearchCellsV1AcceptanceError("candidate evidence drifted")
    return manifest


def _verify_source_contract(project: Path) -> None:
    source = _text(project, "core/phase6_research_cells_v1.py")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    if {"requests", "httpx", "aiohttp", "socket", "openai"} & imports:
        raise ResearchCellsV1AcceptanceError("network/provider import appeared")
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    if {"connect", "send", "invoke", "generate_content"} & calls:
        raise ResearchCellsV1AcceptanceError("provider invocation appeared")
    required = (
        "create_evidence_bundle_v1",
        "forged evidence bundle denied",
        "receipt replay map drift denied",
        "research candidate item or byte budget exhausted",
        "claim_projection_drift",
        "candidate_not_certified",
        "pipeline finalization requires independent acceptance",
        "with self._lock",
    )
    if any(value not in source for value in required):
        raise ResearchCellsV1AcceptanceError("adversarial closure disappeared")
    public = {
        node.name: tuple(
            argument.arg for argument in (*node.args.args, *node.args.kwonlyargs)
        )
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name in {"research", "verify", "finalize"}
    }
    if set(public) != {"research", "verify", "finalize"} or any(
        "instruction" in arguments for arguments in public.values()
    ):
        raise ResearchCellsV1AcceptanceError("instruction surface appeared")
    claims = source.index("expected_claims = self._claims(bundle)")
    projection = source.index('findings.add("claim_projection_drift")')
    contradictions = source.index(
        "expected_contradictions = self._contradictions(expected_claims)"
    )
    if not claims < projection < contradictions:
        raise ResearchCellsV1AcceptanceError("claim verification order drifted")


def _verify_no_live_wiring(project: Path) -> int:
    candidates = [project / "main.py", project / "ui.py"]
    for root_name in ("dashboard", "runtime", "packaging", "qml"):
        root = project / root_name
        if root.is_dir():
            candidates.extend(path for path in root.rglob("*") if path.is_file())
    candidates.extend(
        path for path in (project / "scripts").glob("launch_*") if path.is_file()
    )
    checked = 0
    for path in candidates:
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        checked += 1
        if (
            "phase6_research_cells_v1" in source
            or "ONYX_PHASE6_RESEARCH_CELLS_V1" in source
        ):
            raise ResearchCellsV1AcceptanceError(
                f"candidate entered live surface: {path.relative_to(project)}"
            )
    return checked


def _verify_envelope(project: Path) -> tuple[str, str]:
    record_digest = _digest(project, ACCEPTANCE_RECORD)
    metadata_digest = _digest(project, ACCEPTANCE_METADATA)
    source_rows = _manifest_rows(project, SOURCE_MANIFEST)
    artifact_rows = _manifest_rows(project, ARTIFACT_MANIFEST)
    final_rows = _manifest_rows(project, ACCEPTANCE_MANIFEST)
    expected_source = {
        "scripts/verify_phase6_research_cells_v1_acceptance.py": _digest(
            project, "scripts/verify_phase6_research_cells_v1_acceptance.py"
        ),
        "tests/test_phase6_research_cells_v1_acceptance.py": _digest(
            project, "tests/test_phase6_research_cells_v1_acceptance.py"
        ),
    }
    if source_rows != expected_source:
        raise ResearchCellsV1AcceptanceError("source manifest drifted")
    if artifact_rows != {
        ACCEPTANCE_RECORD: record_digest,
        ACCEPTANCE_METADATA: metadata_digest,
    }:
        raise ResearchCellsV1AcceptanceError("artifact manifest drifted")
    if final_rows != {ACCEPTANCE_RECORD: record_digest}:
        raise ResearchCellsV1AcceptanceError("acceptance manifest drifted")
    metadata = _json(project, ACCEPTANCE_METADATA)
    if (
        metadata.get("acceptance_id") != ACCEPTANCE_ID
        or metadata.get("decision") != "accepted"
        or metadata.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata.get("pre_acceptance_resolved") != {"P1": 5}
        or metadata.get("candidate_manifest_sha256") != CANDIDATE_MANIFEST_SHA256
        or metadata.get("artifact_root_sha256") != CANDIDATE_ROOT_SHA256
        or metadata.get("artifact_count") != 5
        or metadata.get("frozen_anchors") != 9
        or metadata.get("cell_identity_digests") != IDENTITIES
        or metadata.get("instruction_profile_digests") != INSTRUCTIONS
        or metadata.get("results")
        != {
            "focused": {"passed": 22, "failed": 0},
            "cumulative": {"passed": 178, "failed": 0},
            "live_files_checked": 204,
        }
        or metadata.get("default_off") is not True
        or metadata.get("live_wiring") is not False
        or metadata.get("phase6_exit") is not False
    ):
        raise ResearchCellsV1AcceptanceError("acceptance metadata drifted")
    record = _text(project, ACCEPTANCE_RECORD)
    required = (
        ACCEPTANCE_ID,
        CANDIDATE_MANIFEST_SHA256,
        CANDIDATE_ROOT_SHA256,
        "P0=0, P1=0, P2=0, P3=0",
        "22/22 focused tests",
        "178/178 cumulative",
        "isolated, default-off, provider-free, unwired and not",
    )
    if any(value not in record for value in required):
        raise ResearchCellsV1AcceptanceError("acceptance record binding missing")
    return record_digest, metadata_digest


def _run_candidate_verifier(project: Path) -> None:
    result = subprocess.run(
        [
            str(project / ".venv" / "Scripts" / "python.exe"),
            "-I",
            "-S",
            "-B",
            "scripts/verify_phase6_research_cells_v1.py",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0 or "P6_RESEARCH_CELLS_V1_OK" not in result.stdout:
        raise ResearchCellsV1AcceptanceError("candidate verifier failed")


def verify(project: Path = PROJECT) -> dict[str, object]:
    project = Path(project)
    _verify_candidate(project)
    _verify_source_contract(project)
    live_files = _verify_no_live_wiring(project)
    record_digest, metadata_digest = _verify_envelope(project)
    _run_candidate_verifier(project)
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "decision": "accepted",
        "candidate_manifest_sha256": CANDIDATE_MANIFEST_SHA256,
        "artifact_root_sha256": CANDIDATE_ROOT_SHA256,
        "artifacts": 5,
        "frozen_anchors": 9,
        "focused_passed": 22,
        "cumulative_passed": 178,
        "live_files_checked": live_files,
        "record_sha256": record_digest,
        "metadata_sha256": metadata_digest,
        "severity": {"P0": 0, "P1": 0, "P2": 0, "P3": 0},
        "pre_acceptance_resolved": {"P1": 5},
        "scope": (
            "phase6-research-cells-v1-isolated-default-off-provider-free-unwired"
        ),
        "default_off": True,
        "live_wiring": False,
        "network_calls": 0,
        "phase6_exit": False,
    }


if __name__ == "__main__":
    print(MARKER, json.dumps(verify(), sort_keys=True, separators=(",", ":")))
