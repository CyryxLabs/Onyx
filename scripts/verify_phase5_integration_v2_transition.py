"""Verify the immutable V10 history and the exact default-off V2 transition."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import tempfile
import types
import shutil


PROJECT = Path(__file__).resolve().parents[1]
MARKER = "P5_INTEGRATION_V2_TRANSITION_OK"
MANIFEST = "docs/onyx/checkpoints/phase5-integration-v2/manifest.json"
CHECKPOINT = (
    "docs/onyx/checkpoints/phase5-integration-v2/"
    "PHASE5_INTEGRATION_V2_CHECKPOINT.md"
)
ROOT_MANIFEST = (
    "docs/onyx/checkpoints/phase5-integration-v2/"
    "phase5-integration-v2.sha256"
)

V10_VERIFIER = "scripts/verify_phase5_runtime_v10_acceptance.py"
V10_ACCEPTANCE_ID = "VE-P5-RUNTIME-V10-E6-001"
V10_FROZEN = {
    "core/phase5_runtime_v10.py": "f80fd636e145e669cc1ea76cfc024fcc5d385451cc1ef8624f7c9d8e0ac3f439",
    "tests/test_phase5_runtime_v10.py": "b2a6d9524d2d5d1b85af3325462f7bd28793180cee0ea4295d6600750615cfff",
    "docs/onyx/checkpoints/phase5-runtime-v10/manifest.json": "1cc83a994194b3ecb87bf43a91db4219cf480d48da7821e7057eb4e068ca01cb",
    "docs/onyx/checkpoints/phase5-runtime-v10/PHASE5_RUNTIME_V10_CHECKPOINT.md": "7f31d7ddda750f35c7b56e0af2e3569e068229f8a236e783936c28c2fff55f0d",
    "docs/onyx/acceptance/VE-P5-RUNTIME-V10-E6-001.md": "135be5fc3e97e81466f398fcc9211da767c0e3fb251387588dfd836d02b28de0",
    "docs/onyx/VE-ACCEPTANCE-P5-RUNTIME-V10-E6-001.sha256": "44d4a70aa293524f494d503b7cc78a0e935520afc3b672653850ba4b8a1c8566",
    V10_VERIFIER: "71d7db0b01c1fb2c3b133302a1b3877bd04b549f136f7a06e8f2f26371fc3a2c",
    "tests/test_phase5_runtime_v10_acceptance.py": "3d8b2c2d8be5f19adb8be681ec6267d7d631acd22115bf0fa6c53ad95b8d2883",
}
V1_FROZEN = {
    "core/phase5_integration_v1.py": "234ba11fb9ce5336297c27951c97e0c9c63a34bf4841b6980b58cff026687cdc",
    "tests/test_phase5_integration_v1.py": "4d5a3432ee90009266cf57a33d098f57430aca1831f1ab07b354e0797e775fef",
    "docs/onyx/checkpoints/phase5-integration-v1/manifest.json": "f08832e05077223ddce4353fff1c3e99ced3efad56c7329963f836ca2cb3adb8",
    "docs/onyx/checkpoints/phase5-integration-v1/PHASE5_INTEGRATION_V1_CHECKPOINT.md": "5aa2ee76dadddbd9976d53d327b42ac2f06be9d7399ecc8ea485d4e939fe97a2",
    "docs/onyx/checkpoints/phase5-integration-v1/phase5-integration-v1.sha256": "ec0b1eadf1405fea202414a3ced08f0f41c1d38ee96bf63cb6ee09ebe6bdfd2f",
}
ACCEPTED_ANCHORS = {
    "core/session_grants_v11.py": "0f4ad25b72a9c64064dfc946afab6d2515edff1f91171d46d54e36e38c6cd159",
    "core/approval_inbox_v15.py": "f9627e6b9e840dbca8e098a047e56da4647d24ef80f201c5585a41d405d52061",
    "core/capability_nexus_v32.py": "576eed0bda063945d33f8bcb79b338e64976ca5252af793633fe3ab667ed1fc9",
    "core/phase5_component_adapters_v3.py": "9c570d40a410e57a18f82a4ee2c30eddfe515a0cc7798d13607d020e573e3239",
}
UNCHANGED_SURFACES = {
    "core/permission_broker.py": "e37fb092410ba0843036dbdc779342c4d24a811bbfcf0de8812f2f6144e7d250",
    "dashboard/server.py": "4d3142dc9c6a78cfe76f804de2b154334da2d7790484783a993babc92300bae1",
}
RESERVED_UI_PRE_PARALLEL_SHA256 = (
    "60bea0ac313efa7c77dfbc1e3bffec885a0dad010b6f3e9e332761d6cd0de043"
)

_REPARSE_ATTRIBUTE = 0x400
_SCAN_SUFFIXES = {".py", ".pyw", ".ps1", ".iss", ".js", ".html", ".qml"}
_SCAN_ROOTS = ("dashboard", "scripts", "packaging", "core")
_RUNTIME_NEEDLES = ("phase5_runtime_v10", "ONYX_PHASE5_RUNTIME_V10")
_RUNTIME_REFERENCE_ALLOWLIST = {
    "core/phase5_runtime_v10.py",
    "core/phase5_integration_v1.py",
    "core/phase5_integration_v2.py",
    "scripts/verify_phase5_runtime_v10_acceptance.py",
    "scripts/verify_phase5_integration_v2_transition.py",
}
_HISTORICAL_PROJECTION_EXCLUSIONS = {
    "core/phase5_integration_v1.py",
    "core/phase5_integration_v2.py",
    "scripts/verify_phase5_integration_v2_transition.py",
}


class Phase5IntegrationV2TransitionError(RuntimeError):
    """Transition evidence is incomplete, drifted, or over-authoritative."""


def _canonical_relative(relative: str) -> tuple[str, ...]:
    if type(relative) is not str or not relative or "\\" in relative or "\x00" in relative:
        raise Phase5IntegrationV2TransitionError("transition path is not canonical")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or str(parsed) != relative or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise Phase5IntegrationV2TransitionError("transition path is not canonical")
    return parsed.parts


def _regular_path(project: Path, relative: str) -> Path:
    parts = _canonical_relative(relative)
    root = project.absolute()
    try:
        root_info = root.lstat()
        root_resolved = root.resolve(strict=True)
    except OSError as exc:
        raise Phase5IntegrationV2TransitionError("transition root is unavailable") from exc
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or getattr(root_info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        or root_resolved != root
    ):
        raise Phase5IntegrationV2TransitionError("transition root is linked or aliased")
    current = root
    for index, part in enumerate(parts):
        try:
            entries = {entry.name: entry for entry in current.iterdir()}
        except OSError as exc:
            raise Phase5IntegrationV2TransitionError(
                f"transition ancestor is unavailable: {relative}"
            ) from exc
        if part not in entries:
            raise Phase5IntegrationV2TransitionError(
                f"transition path is missing or case-mismatched: {relative}"
            )
        current = entries[part]
        metadata = current.lstat()
        resolved = current.resolve(strict=True)
        if stat.S_ISLNK(metadata.st_mode) or getattr(
            metadata, "st_file_attributes", 0
        ) & _REPARSE_ATTRIBUTE:
            raise Phase5IntegrationV2TransitionError(
                f"transition path uses a link/reparse point: {relative}"
            )
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise Phase5IntegrationV2TransitionError(
                f"transition path leaves project: {relative}"
            ) from exc
        if resolved.name != part:
            raise Phase5IntegrationV2TransitionError(
                f"transition path uses a name alias: {relative}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise Phase5IntegrationV2TransitionError(
                f"transition ancestor is not a directory: {relative}"
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        raise Phase5IntegrationV2TransitionError(
            f"transition leaf is not a regular file: {relative}"
        )
    return current


def _bytes(project: Path, relative: str) -> bytes:
    try:
        return _regular_path(project, relative).read_bytes()
    except OSError as exc:
        raise Phase5IntegrationV2TransitionError(
            f"cannot read transition path: {relative}"
        ) from exc


def _text(project: Path, relative: str) -> str:
    try:
        value = _bytes(project, relative).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Phase5IntegrationV2TransitionError(
            f"transition text is not UTF-8: {relative}"
        ) from exc
    return value


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _require_digest(project: Path, relative: str, expected: str) -> None:
    actual = _digest(project, relative)
    if actual != expected:
        raise Phase5IntegrationV2TransitionError(
            f"transition anchor drifted: {relative}: expected {expected}, got {actual}"
        )


def _load_frozen_v10_verifier(project: Path) -> types.ModuleType:
    _require_digest(project, V10_VERIFIER, V10_FROZEN[V10_VERIFIER])
    name = "_onyx_frozen_phase5_runtime_v10_acceptance"
    spec = importlib.util.spec_from_file_location(name, _regular_path(project, V10_VERIFIER))
    if spec is None or spec.loader is None:
        raise Phase5IntegrationV2TransitionError("cannot load frozen V10 verifier")
    module = importlib.util.module_from_spec(spec)
    prior = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if prior is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = prior
    return module


def verify_historical_v10_e6(project: Path) -> dict[str, object]:
    """Prove frozen bytes and the signed historical unwired acceptance."""
    for relative, expected in V10_FROZEN.items():
        _require_digest(project, relative, expected)
    verifier = _load_frozen_v10_verifier(project)
    record_digest = verifier._verify_record(project)
    closure = verifier._verify_candidate_anchors(project)
    verifier._verify_projections(project)
    if record_digest != V10_FROZEN[
        "docs/onyx/acceptance/VE-P5-RUNTIME-V10-E6-001.md"
    ]:
        raise Phase5IntegrationV2TransitionError("historical E6 record digest drifted")
    record = _text(project, "docs/onyx/acceptance/VE-P5-RUNTIME-V10-E6-001.md")
    if "V10 remains isolated, default-off and unwired" not in record:
        raise Phase5IntegrationV2TransitionError("historical unwired statement is absent")
    return {
        "acceptance_id": V10_ACCEPTANCE_ID,
        "record_sha256": record_digest,
        "closure": closure,
        "historical_state": "isolated-default-off-unwired",
    }


def _eligible_scan_paths(project: Path) -> tuple[str, ...]:
    paths = ["main.py", "ui.py"]
    for root_name in _SCAN_ROOTS:
        root = project / root_name
        if root.is_dir():
            paths.extend(
                path.relative_to(project).as_posix()
                for path in sorted(root.rglob("*"))
                if path.is_file() and path.suffix.lower() in _SCAN_SUFFIXES
            )
    return tuple(dict.fromkeys(paths))


def _scan_transition_surfaces(project: Path) -> dict[str, object]:
    references: set[str] = set()
    paths = _eligible_scan_paths(project)
    for relative in paths:
        value = _bytes(project, relative)
        try:
            source = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Phase5IntegrationV2TransitionError(
                f"live surface is not UTF-8: {relative}"
            ) from exc
        if any(needle in source for needle in _RUNTIME_NEEDLES):
            references.add(relative)
    if references != _RUNTIME_REFERENCE_ALLOWLIST:
        extra = sorted(references - _RUNTIME_REFERENCE_ALLOWLIST)
        missing = sorted(_RUNTIME_REFERENCE_ALLOWLIST - references)
        raise Phase5IntegrationV2TransitionError(
            f"runtime reference allowlist mismatch: extra={extra}, missing={missing}"
        )
    return {"files_checked": len(paths), "runtime_references": sorted(references)}


def _historical_compatibility_projection(project: Path) -> dict[str, object]:
    """Run the exact frozen verifier on a closed post-transition exclusion view."""
    verifier = _load_frozen_v10_verifier(project)
    eligible = _eligible_scan_paths(project)
    included = tuple(
        relative
        for relative in eligible
        if relative not in _HISTORICAL_PROJECTION_EXCLUSIONS
    )
    closure = hashlib.sha256(
        "\n".join(f"{_digest(project, path)}  {path}" for path in included).encode()
    ).hexdigest()
    required_docs = set(V10_FROZEN) | {
        "docs/onyx/CAPABILITY_MATRIX.md",
        "docs/onyx/VERIFICATION_EVIDENCE.md",
    }
    candidate_manifest = json.loads(
        _text(project, "docs/onyx/checkpoints/phase5-runtime-v10/manifest.json")
    )
    for section in ("files", "historical_files"):
        entries = candidate_manifest.get(section)
        if type(entries) is not list:
            raise Phase5IntegrationV2TransitionError(
                "frozen candidate closure is malformed"
            )
        for entry in entries:
            if type(entry) is not dict or type(entry.get("path")) is not str:
                raise Phase5IntegrationV2TransitionError(
                    "frozen candidate closure entry is malformed"
                )
            required_docs.add(entry["path"])
    with tempfile.TemporaryDirectory(prefix="onyx-p5-v10-history-") as temporary:
        root = Path(temporary).resolve(strict=True)
        for relative in sorted(set(included) | required_docs):
            source = _regular_path(project, relative)
            target = root.joinpath(*PurePosixPath(relative).parts)
            if target.exists():
                raise Phase5IntegrationV2TransitionError(
                    "historical projection target unexpectedly exists"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        result = verifier.verify(root)
    if result.get("acceptance_id") != V10_ACCEPTANCE_ID:
        raise Phase5IntegrationV2TransitionError(
            "frozen verifier rejected the historical compatibility projection"
        )
    return {
        "included_count": len(included),
        "included_closure_sha256": closure,
        "excluded": sorted(_HISTORICAL_PROJECTION_EXCLUSIONS),
        "scope": "secondary-closed-historical-compatibility-projection",
    }


def _verify_ast_boundary(project: Path) -> dict[str, object]:
    main_source = _text(project, "main.py")
    imports: list[str] = []
    for node in ast.walk(ast.parse(main_source, filename="main.py")):
        if isinstance(node, ast.ImportFrom) and node.module and "phase5_integration" in node.module:
            imports.append(node.module)
    if imports != ["core.phase5_integration_v2"]:
        raise Phase5IntegrationV2TransitionError(
            f"main integration import boundary is invalid: {imports}"
        )
    for relative in ("main.py", "core/permission_broker.py", "dashboard/server.py"):
        source = _text(project, relative)
        if "phase5_integration_v1" in source:
            raise Phase5IntegrationV2TransitionError(
                f"rejected V1 remains reachable from host surface: {relative}"
            )
    v2_source = _text(project, "core/phase5_integration_v2.py")
    forbidden_ui_dependencies = ("from ui", "import ui", ".qml", "OnyxOrb", "dashboard.static")
    if any(value in v2_source for value in forbidden_ui_dependencies):
        raise Phase5IntegrationV2TransitionError(
            "V2 bridge entered the concurrent UI/HUD transition surface"
        )
    for flag in (
        "ONYX_PHASE5_INTEGRATION_V2",
        "ONYX_PHASE5_RUNTIME_V2",
        "ONYX_PHASE5_LOW_RISK_V2",
        "ONYX_PHASE5_LOCAL_CATALOG_READ_V2",
    ):
        if flag not in v2_source or flag not in main_source and flag in {
            "ONYX_PHASE5_INTEGRATION_V2", "ONYX_PHASE5_RUNTIME_V2"
        }:
            raise Phase5IntegrationV2TransitionError(f"V2 flag boundary missing: {flag}")
    if "setdefault(\"ONYX_PHASE5" in main_source or "setdefault(\"ONYX_PHASE5" in v2_source:
        raise Phase5IntegrationV2TransitionError("V2 feature flag is not default-off")
    return {
        "main_imports": imports,
        "default_off": True,
        "v1_reachable": False,
        "ui_dependency": False,
        "ui_scope": "out-of-scope-concurrent-transition",
    }


def _verify_root_manifest(project: Path) -> dict[str, str]:
    lines = _text(project, ROOT_MANIFEST).splitlines()
    records: dict[str, str] = {}
    for line in lines:
        if len(line) < 67 or line[64:66] != "  ":
            raise Phase5IntegrationV2TransitionError("root manifest line is malformed")
        digest, relative = line[:64], line[66:]
        if any(character not in "0123456789abcdef" for character in digest):
            raise Phase5IntegrationV2TransitionError("root manifest digest is malformed")
        _canonical_relative(relative)
        if relative in records:
            raise Phase5IntegrationV2TransitionError("root manifest path is duplicated")
        records[relative] = digest
        _require_digest(project, relative, digest)
    return records


def _verify_v2_manifest(project: Path) -> dict[str, object]:
    try:
        manifest = json.loads(_text(project, MANIFEST))
    except (json.JSONDecodeError, TypeError) as exc:
        raise Phase5IntegrationV2TransitionError("V2 transition manifest is invalid") from exc
    if (
        type(manifest) is not dict
        or manifest.get("schema") != "onyx.phase5.integration-transition-bundle.v2"
        or manifest.get("candidate") != "phase5-integration-v2"
        or manifest.get("default_off") is not True
        or manifest.get("live_activated") is not False
        or manifest.get("historical_runtime_acceptance")
        != "VE-P5-RUNTIME-V10-E6-001"
    ):
        raise Phase5IntegrationV2TransitionError("V2 transition manifest contract drifted")
    files = manifest.get("files")
    if type(files) is not list or not files:
        raise Phase5IntegrationV2TransitionError("V2 transition file closure is absent")
    seen: set[str] = set()
    for entry in files:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise Phase5IntegrationV2TransitionError("V2 file entry is malformed")
        relative, expected = entry["path"], entry["sha256"]
        if type(relative) is not str or type(expected) is not str or relative in seen:
            raise Phase5IntegrationV2TransitionError("V2 file entry is duplicated or invalid")
        seen.add(relative)
        _require_digest(project, relative, expected)
    roots = _verify_root_manifest(project)
    if set(roots) != seen | {MANIFEST, CHECKPOINT}:
        raise Phase5IntegrationV2TransitionError("root manifest closure is incomplete")
    return {"files": len(files), "root_records": len(roots)}


def verify(project: Path = PROJECT) -> dict[str, object]:
    project = Path(project)
    historical = verify_historical_v10_e6(project)
    for relative, expected in V1_FROZEN.items():
        _require_digest(project, relative, expected)
    for relative, expected in ACCEPTED_ANCHORS.items():
        _require_digest(project, relative, expected)
    for relative, expected in UNCHANGED_SURFACES.items():
        _require_digest(project, relative, expected)
    manifest = _verify_v2_manifest(project)
    boundary = _verify_ast_boundary(project)
    scan = _scan_transition_surfaces(project)
    compatibility = _historical_compatibility_projection(project)
    return {
        "candidate": "phase5-integration-v2",
        "historical": historical,
        "manifest": manifest,
        "boundary": boundary,
        "scan": scan,
        "compatibility": compatibility,
        "scope": "default-off-v2-transition-after-frozen-v10-e6",
    }


def main() -> int:
    print(MARKER + " " + json.dumps(verify(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
