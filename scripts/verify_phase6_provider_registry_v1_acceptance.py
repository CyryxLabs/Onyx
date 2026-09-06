"""Verify external E6 acceptance of Provider Registry + Health V1."""

from __future__ import annotations

import ast
import hashlib
import json
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any


PROJECT = Path(__file__).resolve(strict=True).parents[1]
ACCEPTANCE_ID = "VE-P6-PROVIDER-REGISTRY-V1-E6-001"
MARKER = "P6_PROVIDER_REGISTRY_V1_ACCEPTANCE_OK"
CANDIDATE_MANIFEST = "docs/onyx/checkpoints/phase6-provider-registry-v1/manifest.json"
CANDIDATE_MANIFEST_SHA256 = (
    "7a3191607037f6210ae145b5477bbaeff5bfdaa7c756257d4775c1f30c0a10c6"
)
CANDIDATE_ROOT_SHA256 = (
    "98d381711cda0b9f72eadb9a1ae9f81f8bebff70a922b1f7aa42c139baa82baf"
)
ACCEPTANCE_RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
ACCEPTANCE_METADATA = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
SOURCE_MANIFEST = "docs/onyx/VE-SOURCE-P6-PROVIDER-REGISTRY-V1-E6-001.sha256"
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P6-PROVIDER-REGISTRY-V1-E6-001.sha256"
ACCEPTANCE_MANIFEST = "docs/onyx/VE-ACCEPTANCE-P6-PROVIDER-REGISTRY-V1-E6-001.sha256"

CANDIDATE_ARTIFACTS = {
    "core/phase6_provider_registry_v1.py": (
        28864,
        "7b3e6c682ff6ec8a7e3ceade8f245afdf4edbc562dd1872acf54fa241109b6ad",
    ),
    "tests/test_phase6_provider_registry_v1.py": (
        13339,
        "034443d484db5b524d42a99721066eff8847c4c4edda6c3c5ecf09edf0c0a9c6",
    ),
    "scripts/verify_phase6_provider_registry_v1.py": (
        5619,
        "393970577e86216825b9fe0d611ab0c10cffdf149acc7dce1f6d74e48e8c6557",
    ),
    "docs/onyx/adrs/ADR-0021-phase6-provider-registry-v1.md": (
        2046,
        "2e334685ce522b582729ed4cee105350e3b574fb238b77d3f4e1a3c525037aca",
    ),
    (
        "docs/onyx/checkpoints/phase6-provider-registry-v1/"
        "PHASE6_PROVIDER_REGISTRY_V1_CHECKPOINT.md"
    ): (
        2414,
        "a5dc60911634d211482d2eb4828c01fcbd33ec4dc9757fefd9781230df5b6a18",
    ),
}
FROZEN_ANCHORS = {
    "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
    "core/phase6_agentic_core_v1.py": (
        "ab7a6cfec738c31b7beb66ac7a66584f892231ce8a3a2c9e81f30945123cc965"
    ),
    "core/phase6_agentic_core_v6.py": (
        "38f68d7dd8eb04fe7c9caa956db5a52d0a96426bab6a45f07b96e67e45d8001a"
    ),
    "core/phase6_live_integration_v2.py": (
        "e3194a0d8e206d33218bc8291cbd518788e8dfb3931adfd2f067908655d409b5"
    ),
    "core/phase6_gemini_live_compat_v1.py": (
        "3fb18363c237c573c717472bb9b2d6b3891dccc6236be7f698ee0833b9a55df5"
    ),
    "core/phase6_live_wiring_v1.py": (
        "a658f430c10bb992724ad7bbd2ddae94b3c83f8893608fe724b241302b55d55f"
    ),
    "core/onyx_live_activation_v9.py": (
        "deb26314ef3871cb12fc8e3cee936f88e385122fad242c830580421ccb22a9d2"
    ),
}

_REPARSE_ATTRIBUTE = 0x400
_HEX = frozenset("0123456789abcdef")


class ProviderRegistryV1AcceptanceError(RuntimeError):
    """The frozen candidate or its acceptance envelope drifted."""


def _parts(relative: str) -> tuple[str, ...]:
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or "\x00" in relative
    ):
        raise ProviderRegistryV1AcceptanceError("non-canonical path")
    parsed = PurePosixPath(relative)
    if (
        parsed.is_absolute()
        or str(parsed) != relative
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ProviderRegistryV1AcceptanceError("non-canonical path")
    return parsed.parts


def _path(project: Path, relative: str) -> Path:
    root = project.resolve(strict=True)
    current = project
    for index, part in enumerate(_parts(relative)):
        current = current / part
        try:
            info = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise ProviderRegistryV1AcceptanceError(
                f"path unavailable: {relative}"
            ) from exc
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        ):
            raise ProviderRegistryV1AcceptanceError(f"path is linked: {relative}")
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ProviderRegistryV1AcceptanceError(
                f"path escaped project: {relative}"
            ) from exc
        if index < len(_parts(relative)) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ProviderRegistryV1AcceptanceError(
                f"path ancestor is not a directory: {relative}"
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        raise ProviderRegistryV1AcceptanceError(f"path is not regular: {relative}")
    return current


def _bytes(project: Path, relative: str) -> bytes:
    return _path(project, relative).read_bytes()


def _text(project: Path, relative: str) -> str:
    try:
        return _bytes(project, relative).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProviderRegistryV1AcceptanceError(
            f"text is not UTF-8: {relative}"
        ) from exc


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _require_digest(project: Path, relative: str, expected: str) -> None:
    if _digest(project, relative) != expected:
        raise ProviderRegistryV1AcceptanceError(f"anchor drifted: {relative}")


def _json(project: Path, relative: str) -> dict[str, Any]:
    try:
        value = json.loads(_text(project, relative))
    except json.JSONDecodeError as exc:
        raise ProviderRegistryV1AcceptanceError(f"invalid JSON: {relative}") from exc
    if type(value) is not dict:
        raise ProviderRegistryV1AcceptanceError(f"JSON object required: {relative}")
    return value


def _artifact_root(artifacts: dict[str, str]) -> str:
    payload = "".join(f"{path}\0{artifacts[path]}\n" for path in sorted(artifacts))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _manifest_rows(project: Path, relative: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in _text(project, relative).splitlines():
        if len(line) < 67 or line[64:66] != "  ":
            raise ProviderRegistryV1AcceptanceError(f"bad sha256 row: {relative}")
        digest, target = line[:64], line[66:]
        if any(character not in _HEX for character in digest) or target in rows:
            raise ProviderRegistryV1AcceptanceError(f"bad sha256 row: {relative}")
        _parts(target)
        rows[target] = digest
    if not rows:
        raise ProviderRegistryV1AcceptanceError(f"empty sha256 manifest: {relative}")
    return rows


def _verify_candidate(project: Path) -> dict[str, Any]:
    _require_digest(project, CANDIDATE_MANIFEST, CANDIDATE_MANIFEST_SHA256)
    manifest = _json(project, CANDIDATE_MANIFEST)
    if (
        manifest.get("schema") != "OnyxPhase6ProviderRegistry.v1"
        or manifest.get("candidate") != "phase6-provider-registry-candidate-001"
        or manifest.get("status") != "candidate_default_off_not_live"
        or manifest.get("artifact_root_sha256") != CANDIDATE_ROOT_SHA256
        or manifest.get("activation")
        != {
            "flag": "ONYX_PHASE6_PROVIDER_REGISTRY_V1",
            "enabled_value": "true",
            "exact": "ONYX_PHASE6_PROVIDER_REGISTRY_V1=true",
            "default": "off",
            "live_wiring": False,
        }
    ):
        raise ProviderRegistryV1AcceptanceError("candidate identity drifted")
    entries = manifest.get("artifacts")
    if type(entries) is not list or len(entries) != 5:
        raise ProviderRegistryV1AcceptanceError("candidate closure is not 5/5")
    observed: dict[str, str] = {}
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "bytes", "sha256"}:
            raise ProviderRegistryV1AcceptanceError("artifact row drifted")
        relative = entry["path"]
        if relative in observed or relative not in CANDIDATE_ARTIFACTS:
            raise ProviderRegistryV1AcceptanceError("artifact set drifted")
        expected_size, expected_digest = CANDIDATE_ARTIFACTS[relative]
        target = _path(project, relative)
        if (
            target.stat().st_size != expected_size
            or entry["bytes"] != expected_size
            or entry["sha256"] != expected_digest
        ):
            raise ProviderRegistryV1AcceptanceError(
                f"artifact metadata drifted: {relative}"
            )
        _require_digest(project, relative, expected_digest)
        observed[relative] = expected_digest
    if set(observed) != set(CANDIDATE_ARTIFACTS):
        raise ProviderRegistryV1AcceptanceError("artifact closure incomplete")
    if _artifact_root(observed) != CANDIDATE_ROOT_SHA256:
        raise ProviderRegistryV1AcceptanceError("artifact root mismatch")
    if manifest.get("frozen_anchors") != FROZEN_ANCHORS:
        raise ProviderRegistryV1AcceptanceError("frozen anchor declaration drifted")
    for relative, expected in FROZEN_ANCHORS.items():
        _require_digest(project, relative, expected)
    contracts = manifest.get("contracts", {})
    required_contracts = {
        "factory_only": True,
        "health_authentication": "HMAC-SHA-256",
        "health_key_bytes": 32,
        "health_key_fingerprint_attested": True,
        "health_monotonic_sequence": True,
        "health_previous_digest_chain": True,
        "health_snapshot_membership_exact": True,
        "health_strictly_increasing_observed_time": True,
        "health_freshness_max_ms": 300000,
        "sensitive_remote_fallback": False,
        "ordered_plan_only": True,
        "provider_invocation": False,
        "prompt_or_payload_accepted": False,
    }
    for name, expected in required_contracts.items():
        if contracts.get(name) != expected:
            raise ProviderRegistryV1AcceptanceError(f"contract drifted: {name}")
    if contracts.get("exact_agentic_core_types") != [
        "ModelDescriptorV1",
        "RouteRequestV1",
        "ModelRouterV1",
    ]:
        raise ProviderRegistryV1AcceptanceError("exact core types drifted")
    if contracts.get("hard_filter_order") != [
        "privacy_and_data_class",
        "workspace",
        "modality",
        "local_private",
        "structured_output",
        "budget",
        "health_freshness_and_availability",
        "ModelRouterV1_ranking",
    ]:
        raise ProviderRegistryV1AcceptanceError("hard filter order drifted")
    verification = manifest.get("verification", {})
    if (
        verification.get("focused") != "22 passed"
        or verification.get("cumulative") != "156 passed"
        or verification.get("network_calls") != 0
        or verification.get("live_activation") is not False
        or verification.get("e6") != "not_performed"
    ):
        raise ProviderRegistryV1AcceptanceError("candidate evidence drifted")
    return manifest


def _verify_adversarial_source(project: Path) -> None:
    source = _text(project, "core/phase6_provider_registry_v1.py")
    tree = ast.parse(source)
    imported_types = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "core.phase6_agentic_core_v1"
        for alias in node.names
    }
    if (
        not {
            "ModelDescriptorV1",
            "RouteRequestV1",
            "ModelRouterV1",
        }
        <= imported_types
    ):
        raise ProviderRegistryV1AcceptanceError("exact type reuse disappeared")
    forbidden_imports = {"requests", "httpx", "aiohttp", "openai", "socket"}
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    if forbidden_imports & imported:
        raise ProviderRegistryV1AcceptanceError("network/provider import appeared")
    required = (
        "_authentication_key_digest",
        "set(self._health) != set(self._health_snapshots)",
        '"privacy_hard_filter"',
        '"budget_hard_filter"',
        'excluded["health_unavailable"]',
        "_MODEL_ROUTER_TYPE(",
    )
    if any(value not in source for value in required):
        raise ProviderRegistryV1AcceptanceError("adversarial closure disappeared")
    privacy = source.index('"privacy_hard_filter"')
    budget = source.index('"budget_hard_filter"')
    health = source.index('excluded["health_unavailable"]')
    router = source.index("_MODEL_ROUTER_TYPE(")
    if not privacy < budget < health < router:
        raise ProviderRegistryV1AcceptanceError("privacy-hard order drifted")


def _verify_no_live_wiring(project: Path) -> int:
    candidates = [project / "main.py", project / "ui.py"]
    for root_name in ("dashboard", "runtime", "packaging", "qml"):
        root = project / root_name
        if root.is_dir():
            candidates.extend(path for path in root.rglob("*") if path.is_file())
    scripts = project / "scripts"
    candidates.extend(path for path in scripts.glob("launch_*") if path.is_file())
    checked = 0
    for path in candidates:
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        checked += 1
        if (
            "phase6_provider_registry_v1" in source
            or "ONYX_PHASE6_PROVIDER_REGISTRY_V1" in source
        ):
            raise ProviderRegistryV1AcceptanceError(
                f"candidate entered live surface: {path.relative_to(project)}"
            )
    return checked


def _verify_envelope(project: Path) -> tuple[str, str]:
    record_digest = _digest(project, ACCEPTANCE_RECORD)
    metadata_digest = _digest(project, ACCEPTANCE_METADATA)
    source = _manifest_rows(project, SOURCE_MANIFEST)
    artifacts = _manifest_rows(project, ARTIFACT_MANIFEST)
    final = _manifest_rows(project, ACCEPTANCE_MANIFEST)
    expected_source = {
        "scripts/verify_phase6_provider_registry_v1_acceptance.py": _digest(
            project, "scripts/verify_phase6_provider_registry_v1_acceptance.py"
        ),
        "tests/test_phase6_provider_registry_v1_acceptance.py": _digest(
            project, "tests/test_phase6_provider_registry_v1_acceptance.py"
        ),
    }
    if source != expected_source:
        raise ProviderRegistryV1AcceptanceError("source manifest drifted")
    if artifacts != {
        ACCEPTANCE_RECORD: record_digest,
        ACCEPTANCE_METADATA: metadata_digest,
    }:
        raise ProviderRegistryV1AcceptanceError("artifact manifest drifted")
    if final != {ACCEPTANCE_RECORD: record_digest}:
        raise ProviderRegistryV1AcceptanceError("acceptance manifest drifted")
    metadata = _json(project, ACCEPTANCE_METADATA)
    if (
        metadata.get("acceptance_id") != ACCEPTANCE_ID
        or metadata.get("decision") != "accepted"
        or metadata.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata.get("pre_acceptance_resolved") != {"P1": 2, "P2": 1}
        or metadata.get("candidate_manifest_sha256") != CANDIDATE_MANIFEST_SHA256
        or metadata.get("artifact_root_sha256") != CANDIDATE_ROOT_SHA256
        or metadata.get("artifact_count") != 5
        or metadata.get("frozen_anchors") != 7
        or metadata.get("results")
        != {
            "focused": {"passed": 22, "failed": 0},
            "cumulative": {"passed": 156, "failed": 0},
        }
        or metadata.get("default_off") is not True
        or metadata.get("live_wiring") is not False
        or metadata.get("phase6_exit") is not False
    ):
        raise ProviderRegistryV1AcceptanceError("acceptance metadata drifted")
    record = _text(project, ACCEPTANCE_RECORD)
    required = (
        ACCEPTANCE_ID,
        CANDIDATE_MANIFEST_SHA256,
        CANDIDATE_ROOT_SHA256,
        "P0=0, P1=0, P2=0, P3=0",
        "22/22 focused tests",
        "156/156 cumulative",
        "isolated, default-off, metadata-only, unwired and not",
    )
    missing = [value for value in required if value not in record]
    if missing:
        raise ProviderRegistryV1AcceptanceError(
            f"acceptance record missing binding: {missing[0]}"
        )
    return record_digest, metadata_digest


def _run_candidate_verifier(project: Path) -> None:
    result = subprocess.run(
        [
            str(project / ".venv" / "Scripts" / "python.exe"),
            "-I",
            "-S",
            "-B",
            "scripts/verify_phase6_provider_registry_v1.py",
        ],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0 or "P6_PROVIDER_REGISTRY_V1_OK" not in result.stdout:
        raise ProviderRegistryV1AcceptanceError("candidate verifier failed")


def verify(project: Path = PROJECT) -> dict[str, object]:
    project = Path(project)
    _verify_candidate(project)
    _verify_adversarial_source(project)
    live_files = _verify_no_live_wiring(project)
    record_digest, metadata_digest = _verify_envelope(project)
    _run_candidate_verifier(project)
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "decision": "accepted",
        "candidate_manifest_sha256": CANDIDATE_MANIFEST_SHA256,
        "artifact_root_sha256": CANDIDATE_ROOT_SHA256,
        "artifacts": 5,
        "frozen_anchors": 7,
        "focused_passed": 22,
        "cumulative_passed": 156,
        "live_files_checked": live_files,
        "record_sha256": record_digest,
        "metadata_sha256": metadata_digest,
        "severity": {"P0": 0, "P1": 0, "P2": 0, "P3": 0},
        "pre_acceptance_resolved": {"P1": 2, "P2": 1},
        "scope": "phase6-provider-registry-v1-isolated-default-off-unwired",
        "default_off": True,
        "live_wiring": False,
        "network_calls": 0,
        "phase6_exit": False,
    }


if __name__ == "__main__":
    print(MARKER, json.dumps(verify(), sort_keys=True, separators=(",", ":")))
