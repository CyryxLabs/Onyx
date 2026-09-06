"""Verify frozen Phase 5 history and the independent default-off V3 bridge."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import types

from scripts.verify_legacy_evidence_retirement_v1 import (
    LegacyEvidenceRetirementError,
    artifact_retirement,
    classify_historical_artifact,
)
from scripts import verify_phase5_exit_retirement_v1 as exit_retirement


PROJECT = Path(__file__).resolve().parents[1]
MARKER = "P5_INTEGRATION_V3_TRANSITION_OK"
MANIFEST = "docs/onyx/checkpoints/phase5-integration-v3/manifest.json"
CHECKPOINT = (
    "docs/onyx/checkpoints/phase5-integration-v3/"
    "PHASE5_INTEGRATION_V3_CHECKPOINT.md"
)
ROOT_MANIFEST = (
    "docs/onyx/checkpoints/phase5-integration-v3/"
    "phase5-integration-v3.sha256"
)

PROJECTION_MANIFESTS = {
    "runtime-v10-e6": (
        "docs/onyx/checkpoints/phase5-integration-v3/"
        "projections/runtime-v10.json"
    ),
    "approval-inbox-v15-e6": (
        "docs/onyx/checkpoints/phase5-integration-v3/"
        "projections/approval-inbox-v15.json"
    ),
    "capability-nexus-v32-e6": (
        "docs/onyx/checkpoints/phase5-integration-v3/"
        "projections/capability-nexus-v32.json"
    ),
}

V1_FROZEN = {
    "core/phase5_integration_v1.py": "234ba11fb9ce5336297c27951c97e0c9c63a34bf4841b6980b58cff026687cdc",
    "tests/test_phase5_integration_v1.py": "4d5a3432ee90009266cf57a33d098f57430aca1831f1ab07b354e0797e775fef",
    "docs/onyx/checkpoints/phase5-integration-v1/manifest.json": "f08832e05077223ddce4353fff1c3e99ced3efad56c7329963f836ca2cb3adb8",
    "docs/onyx/checkpoints/phase5-integration-v1/PHASE5_INTEGRATION_V1_CHECKPOINT.md": "5aa2ee76dadddbd9976d53d327b42ac2f06be9d7399ecc8ea485d4e939fe97a2",
    "docs/onyx/checkpoints/phase5-integration-v1/phase5-integration-v1.sha256": "ec0b1eadf1405fea202414a3ced08f0f41c1d38ee96bf63cb6ee09ebe6bdfd2f",
}
V2_FROZEN = {
    "core/phase5_integration_v2.py": "ae035c4be1364d87f23c308ca42d33c938a29d6181680de62b5d9de5fe5f285d",
    "tests/test_phase5_integration_v2.py": "cb9ec992e08c5b47c51a7aac4a57b813fd6648526c22a488dfff4b51fe3a1217",
    "scripts/verify_phase5_integration_v2_transition.py": "9eacbe19c29d58ff1890b0a50b48bfa37c7ba681c28c640115264a5627dca1b0",
    "tests/test_phase5_integration_v2_transition.py": "2efe373bf0740d32384929ab3ade7aabbcce16388d7d0063b33ef9ce3b3a1f9e",
    "docs/onyx/checkpoints/phase5-integration-v2/manifest.json": "8f8a7aafb1f42d0de482adf69827c43ca8c04312fe90931683a4368148ef8498",
    "docs/onyx/checkpoints/phase5-integration-v2/PHASE5_INTEGRATION_V2_CHECKPOINT.md": "3c61b694f188494e9754867adb8e85fe13968dd5d1981d3576d1f8552eb68b29",
    "docs/onyx/checkpoints/phase5-integration-v2/phase5-integration-v2.sha256": "29324c092273f046e6b68989fbe5b516a139a1ece41fb09a5d061efcc0661fb5",
}
ACCEPTED_ANCHORS = {
    "core/session_grants_v11.py": "0f4ad25b72a9c64064dfc946afab6d2515edff1f91171d46d54e36e38c6cd159",
    "core/approval_inbox_v15.py": "f9627e6b9e840dbca8e098a047e56da4647d24ef80f201c5585a41d405d52061",
    "core/capability_nexus_v32.py": "576eed0bda063945d33f8bcb79b338e64976ca5252af793633fe3ab667ed1fc9",
    "core/phase5_component_adapters_v3.py": "9c570d40a410e57a18f82a4ee2c30eddfe515a0cc7798d13607d020e573e3239",
    "core/phase5_runtime_v10.py": "f80fd636e145e669cc1ea76cfc024fcc5d385451cc1ef8624f7c9d8e0ac3f439",
}
UNCHANGED_HOOKS = {
    "dashboard/server.py": "4d3142dc9c6a78cfe76f804de2b154334da2d7790484783a993babc92300bae1",
}
RETIRED_HOOKS = {
    "core/permission_broker.py": "e37fb092410ba0843036dbdc779342c4d24a811bbfcf0de8812f2f6144e7d250",
}
HISTORICAL_PERMISSION_BROKER_SHA256 = (
    "8358ba39d7ff2d965eae7af7c24007f64f4670bef349447737c72e88776cbffc"
)

REPRODUCIBLE_CUMULATIVE_COMMAND = [
    "python",
    "-m",
    "pytest",
    "-q",
    "tests/test_session_grants_v11.py",
    "tests/test_approval_inbox_v15_acceptance.py",
    "tests/test_capability_nexus_v32_acceptance.py",
    "tests/test_phase5_component_adapters_v3.py",
    "tests/test_phase5_runtime_v10.py",
    "tests/test_phase5_integration_v3.py",
    "tests/test_phase5_integration_v3_transition.py",
    "--basetemp",
    ".pytest-p5-v3-cumulative",
]

_REPARSE_ATTRIBUTE = 0x400


class Phase5IntegrationV3TransitionError(RuntimeError):
    """V3 transition evidence is incomplete, drifted, or non-reproducible."""


def _canonical_relative(relative: str) -> tuple[str, ...]:
    if type(relative) is not str or not relative or "\\" in relative or "\x00" in relative:
        raise Phase5IntegrationV3TransitionError("transition path is not canonical")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or str(parsed) != relative or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise Phase5IntegrationV3TransitionError("transition path is not canonical")
    return parsed.parts


def _regular_path(project: Path, relative: str) -> Path:
    parts = _canonical_relative(relative)
    root = project.absolute()
    try:
        root_info = root.lstat()
        root_resolved = root.resolve(strict=True)
    except OSError as exc:
        raise Phase5IntegrationV3TransitionError("transition root is unavailable") from exc
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or getattr(root_info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        or root_resolved != root
    ):
        raise Phase5IntegrationV3TransitionError("transition root is linked or aliased")
    current = root
    for index, part in enumerate(parts):
        try:
            entries = {entry.name: entry for entry in current.iterdir()}
        except OSError as exc:
            raise Phase5IntegrationV3TransitionError(
                f"transition ancestor is unavailable: {relative}"
            ) from exc
        if part not in entries:
            raise Phase5IntegrationV3TransitionError(
                f"transition path is missing or case-mismatched: {relative}"
            )
        current = entries[part]
        metadata = current.lstat()
        resolved = current.resolve(strict=True)
        if stat.S_ISLNK(metadata.st_mode) or getattr(
            metadata, "st_file_attributes", 0
        ) & _REPARSE_ATTRIBUTE:
            raise Phase5IntegrationV3TransitionError(
                f"transition path uses a link/reparse point: {relative}"
            )
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise Phase5IntegrationV3TransitionError(
                f"transition path leaves project: {relative}"
            ) from exc
        if resolved.name != part:
            raise Phase5IntegrationV3TransitionError(
                f"transition path uses a name alias: {relative}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise Phase5IntegrationV3TransitionError(
                f"transition ancestor is not a directory: {relative}"
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        raise Phase5IntegrationV3TransitionError(
            f"transition leaf is not a regular file: {relative}"
        )
    return current


def _read_handle_bytes(project: Path, relative: str) -> bytes:
    path = _regular_path(project, relative)
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise Phase5IntegrationV3TransitionError(
                    f"transition handle is not regular: {relative}"
                )
            data = handle.read()
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise Phase5IntegrationV3TransitionError(
            f"cannot read transition handle: {relative}"
        ) from exc
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or len(data) != after.st_size
    ):
        raise Phase5IntegrationV3TransitionError(
            f"transition source changed during handle read: {relative}"
        )
    return data


def _bytes(project: Path, relative: str) -> bytes:
    return _read_handle_bytes(project, relative)


def _text(project: Path, relative: str) -> str:
    try:
        return _bytes(project, relative).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Phase5IntegrationV3TransitionError(
            f"transition text is not UTF-8: {relative}"
        ) from exc


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _require_digest(project: Path, relative: str, expected: str) -> None:
    actual = _digest(project, relative)
    if actual != expected:
        try:
            classify_historical_artifact(project, relative, expected)
            return
        except LegacyEvidenceRetirementError:
            pass
        try:
            exit_retirement.classify(project, relative, expected)
            return
        except exit_retirement.Phase5ExitRetirementError as error:
            raise Phase5IntegrationV3TransitionError(
                f"transition anchor drifted: {relative}: expected {expected}, got {actual}"
            ) from error


def _closure_root(files: list[dict[str, str]]) -> str:
    lines = "".join(
        f"{entry['sha256']}  {entry['path']}\n"
        for entry in sorted(files, key=lambda item: item["path"])
    )
    return hashlib.sha256(lines.encode()).hexdigest()


def _load_projection_manifest(
    project: Path, relative: str, expected_digest: str, expected_root: str
) -> dict[str, object]:
    _require_digest(project, relative, expected_digest)
    try:
        value = json.loads(_text(project, relative))
    except (json.JSONDecodeError, TypeError) as exc:
        raise Phase5IntegrationV3TransitionError(
            f"historical projection manifest is invalid: {relative}"
        ) from exc
    if (
        type(value) is not dict
        or value.get("schema") != "onyx.phase5.historical-execution-closure.v1"
        or value.get("closure_root_sha256") != expected_root
    ):
        raise Phase5IntegrationV3TransitionError(
            f"historical projection contract drifted: {relative}"
        )
    files = value.get("files")
    if type(files) is not list or not files:
        raise Phase5IntegrationV3TransitionError("historical projection is empty")
    seen: set[str] = set()
    for entry in files:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise Phase5IntegrationV3TransitionError(
                "historical projection entry is malformed"
            )
        path, digest = entry["path"], entry["sha256"]
        if type(path) is not str or type(digest) is not str or path in seen:
            raise Phase5IntegrationV3TransitionError(
                "historical projection entry is duplicated or invalid"
            )
        _canonical_relative(path)
        seen.add(path)
    if files != sorted(files, key=lambda item: item["path"]):
        raise Phase5IntegrationV3TransitionError(
            "historical projection entries are not deterministic"
        )
    if _closure_root(files) != expected_root:
        raise Phase5IntegrationV3TransitionError(
            "historical projection closure root is invalid"
        )
    entrypoint = value.get("entrypoint")
    if type(entrypoint) is not str or entrypoint not in seen:
        raise Phase5IntegrationV3TransitionError(
            "historical projection entrypoint is outside closure"
        )
    return value


def _copy_projection(
    project: Path, destination: Path, projection: dict[str, object]
) -> None:
    root = Path(destination).resolve(strict=True)
    if any(root.iterdir()):
        raise Phase5IntegrationV3TransitionError(
            "historical projection destination is not empty"
        )
    files = projection["files"]
    assert type(files) is list
    for entry in files:
        assert type(entry) is dict
        relative = entry["path"]
        expected = entry["sha256"]
        assert type(relative) is str and type(expected) is str
        data = _read_handle_bytes(project, relative)
        if hashlib.sha256(data).hexdigest() != expected:
            try:
                state = exit_retirement.classify(project, relative, expected)
            except exit_retirement.Phase5ExitRetirementError as error:
                raise Phase5IntegrationV3TransitionError(
                    f"projection source handle digest drifted: {relative}"
                ) from error
            if state != "archived-exact":
                raise Phase5IntegrationV3TransitionError(
                    f"historical projection retired and delegated: {relative}"
                )
            try:
                data = exit_retirement.historical_bytes(project, relative, expected)
            except exit_retirement.Phase5ExitRetirementError as error:
                raise Phase5IntegrationV3TransitionError(str(error)) from error
        target = root.joinpath(*PurePosixPath(relative).parts)
        if target.exists():
            raise Phase5IntegrationV3TransitionError(
                f"projection target already exists: {relative}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise Phase5IntegrationV3TransitionError(
                f"projection target write failed: {relative}"
            ) from exc
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise Phase5IntegrationV3TransitionError(
                f"projection destination rehash failed: {relative}"
            )


def _verify_projection_tree(root: Path, projection: dict[str, object]) -> int:
    files = projection["files"]
    assert type(files) is list
    expected = {entry["path"]: entry["sha256"] for entry in files}
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if actual_paths != set(expected):
        raise Phase5IntegrationV3TransitionError(
            "projection contains extra or missing files"
        )
    for relative, digest in expected.items():
        if hashlib.sha256(root.joinpath(*PurePosixPath(relative).parts).read_bytes()).hexdigest() != digest:
            raise Phase5IntegrationV3TransitionError(
                f"projection byte drifted before execution: {relative}"
            )
    return len(expected)


def _execute_projection_module(
    root: Path, projection: dict[str, object]
) -> types.ModuleType:
    entrypoint = projection["entrypoint"]
    assert type(entrypoint) is str
    path = root.joinpath(*PurePosixPath(entrypoint).parts)
    source = path.read_bytes()
    module = types.ModuleType(
        "_onyx_phase5_v3_projection_" + str(projection["closure"]).replace("-", "_")
    )
    module.__file__ = str(path)
    module.__package__ = ""
    exec(compile(source, str(path), "exec"), module.__dict__)
    return module


def _run_projection(
    project: Path, projection: dict[str, object]
) -> dict[str, object]:
    closure = projection.get("closure")
    files = projection["files"]
    assert type(files) is list
    delegated: dict[str, str] = {}
    for entry in files:
        assert type(entry) is dict
        relative, expected = entry["path"], entry["sha256"]
        assert type(relative) is str and type(expected) is str
        if _digest(project, relative) == expected:
            continue
        try:
            state = exit_retirement.classify(project, relative, expected)
        except exit_retirement.Phase5ExitRetirementError as error:
            raise Phase5IntegrationV3TransitionError(str(error)) from error
        if state.startswith("retired-delegated:"):
            delegated[relative] = state.removeprefix("retired-delegated:")
    if delegated:
        acceptance_ids = {
            "runtime-v10-e6": "VE-P5-RUNTIME-V10-E6-001",
            "approval-inbox-v15-e6": "VE-P52-APPROVAL-INBOX-V15-E6-001",
            "capability-nexus-v32-e6": "VE-P53-CAPABILITY-NEXUS-V32-E6-001",
        }
        if closure not in acceptance_ids:
            raise Phase5IntegrationV3TransitionError(
                f"unknown historical projection: {closure}"
            )
        result: dict[str, object] = {
            "acceptance_id": acceptance_ids[closure],
            "historical_state": "retired-delegated-current-successor",
            "delegated_bindings": delegated,
        }
        if closure == "runtime-v10-e6":
            result["historical_state"] = "isolated-default-off-unwired"
        return {
            "closure": closure,
            "closure_root_sha256": projection["closure_root_sha256"],
            "files": len(files),
            "result": result,
        }
    with tempfile.TemporaryDirectory(prefix=f"onyx-{closure}-") as temporary:
        root = Path(temporary).resolve(strict=True)
        _copy_projection(project, root, projection)
        file_count = _verify_projection_tree(root, projection)
        module = _execute_projection_module(root, projection)
        if closure == "runtime-v10-e6":
            record = module._verify_record(root)
            candidate = module._verify_candidate_anchors(root)
            module._verify_projections(root)
            result = {
                "acceptance_id": module.ACCEPTANCE_ID,
                "record_sha256": record,
                "candidate": candidate,
                "historical_state": "isolated-default-off-unwired",
            }
        elif closure in {"approval-inbox-v15-e6", "capability-nexus-v32-e6"}:
            result = module.verify(root, run_parent=False)
        else:
            raise Phase5IntegrationV3TransitionError(
                f"unknown historical projection: {closure}"
            )
        _verify_projection_tree(root, projection)
    return {
        "closure": closure,
        "closure_root_sha256": projection["closure_root_sha256"],
        "files": file_count,
        "result": result,
    }


def _verify_permission_broker_transition(project: Path) -> dict[str, object]:
    accepted_sha256 = RETIRED_HOOKS["core/permission_broker.py"]
    try:
        artifact_retirement(
            project,
            "core/permission_broker.py",
            accepted_sha256,
            historical_bytes=21754,
        )
    except LegacyEvidenceRetirementError as exc:
        raise Phase5IntegrationV3TransitionError(str(exc)) from exc
    v15_bundle = _text(
        project,
        "docs/onyx/checkpoints/phase5-approval-inbox-v15/"
        "phase5-approval-inbox-v15.bundle.json",
    )
    v32_artifacts = _text(
        project, "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V32-001.sha256"
    )
    historical_binding = (
        HISTORICAL_PERMISSION_BROKER_SHA256 in v15_bundle
        and (
            HISTORICAL_PERMISSION_BROKER_SHA256
            + "  core/permission_broker.py"
        )
        in v32_artifacts
    )
    if not historical_binding:
        raise Phase5IntegrationV3TransitionError(
            "historical permission broker transition is not explicitly bound"
        )
    return {
        "historical_sha256": HISTORICAL_PERMISSION_BROKER_SHA256,
        # This field name is retained for compatibility with the accepted V3
        # evidence schema.  Its value is the V3-era generic-hook digest; the
        # retirement verifier above proves the live successor is different.
        "current_generic_hook_sha256": accepted_sha256,
        "governed_as_post_acceptance_transition": True,
    }


def _verify_ast_boundary(project: Path) -> dict[str, object]:
    main_source = _text(project, "main.py")
    imports = [
        node.module
        for node in ast.walk(ast.parse(main_source, filename="main.py"))
        if isinstance(node, ast.ImportFrom)
        and node.module
        and "phase5_integration" in node.module
    ]
    if imports != ["core.phase5_integration_v3"]:
        raise Phase5IntegrationV3TransitionError(
            f"main integration import boundary is invalid: {imports}"
        )
    v3_source = _text(project, "core/phase5_integration_v3.py")
    forbidden = (
        "phase5_integration_v1",
        "phase5_integration_v2",
        "Phase5IntegrationV1",
        "Phase5IntegrationV2",
        "from ui",
        "import ui",
        ".qml",
        "OnyxOrb",
        "dashboard.static",
    )
    if any(value in v3_source for value in forbidden):
        raise Phase5IntegrationV3TransitionError(
            "V3 imports a rejected predecessor or concurrent UI surface"
        )
    for flag in (
        "ONYX_PHASE5_INTEGRATION_V3",
        "ONYX_PHASE5_RUNTIME_V3",
        "ONYX_PHASE5_LOW_RISK_V3",
        "ONYX_PHASE5_LOCAL_CATALOG_READ_V3",
    ):
        if flag not in v3_source:
            raise Phase5IntegrationV3TransitionError(f"V3 flag is absent: {flag}")
    if "setdefault(\"ONYX_PHASE5" in main_source or "setdefault(\"ONYX_PHASE5" in v3_source:
        raise Phase5IntegrationV3TransitionError("V3 is not strictly default-off")
    return {
        "main_imports": imports,
        "v1_reachable": False,
        "v2_reachable": False,
        "ui_dependency": False,
        "default_off": True,
    }


def _verify_root_manifest(project: Path, expected_paths: set[str]) -> int:
    records: dict[str, str] = {}
    for line in _text(project, ROOT_MANIFEST).splitlines():
        if len(line) < 67 or line[64:66] != "  ":
            raise Phase5IntegrationV3TransitionError("root manifest line is malformed")
        digest, relative = line[:64], line[66:]
        _canonical_relative(relative)
        if relative in records:
            raise Phase5IntegrationV3TransitionError("root manifest path is duplicated")
        records[relative] = digest
        _require_digest(project, relative, digest)
    if set(records) != expected_paths:
        raise Phase5IntegrationV3TransitionError("root manifest closure is incomplete")
    return len(records)


def _verify_v3_manifest(project: Path) -> dict[str, object]:
    try:
        manifest = json.loads(_text(project, MANIFEST))
    except (json.JSONDecodeError, TypeError) as exc:
        raise Phase5IntegrationV3TransitionError("V3 manifest is invalid") from exc
    if (
        type(manifest) is not dict
        or manifest.get("schema") != "onyx.phase5.integration-transition-bundle.v3"
        or manifest.get("candidate") != "phase5-integration-v3"
        or manifest.get("default_off") is not True
        or manifest.get("live_activated") is not False
        or manifest.get("live_restart_performed") is not False
        or manifest.get("reproducible_cumulative_command")
        != REPRODUCIBLE_CUMULATIVE_COMMAND
    ):
        raise Phase5IntegrationV3TransitionError("V3 manifest contract drifted")
    files = manifest.get("files")
    projections = manifest.get("historical_execution_closures")
    if type(files) is not list or type(projections) is not list:
        raise Phase5IntegrationV3TransitionError("V3 manifest closure is absent")
    file_paths: set[str] = set()
    for entry in files:
        if type(entry) is not dict or set(entry) != {"path", "sha256"}:
            raise Phase5IntegrationV3TransitionError("V3 file entry is malformed")
        relative, digest = entry["path"], entry["sha256"]
        if type(relative) is not str or type(digest) is not str or relative in file_paths:
            raise Phase5IntegrationV3TransitionError("V3 file entry is invalid")
        file_paths.add(relative)
        _require_digest(project, relative, digest)
    projection_values: dict[str, dict[str, object]] = {}
    projection_paths: set[str] = set()
    for entry in projections:
        if type(entry) is not dict or set(entry) != {
            "closure", "manifest_path", "manifest_sha256", "closure_root_sha256"
        }:
            raise Phase5IntegrationV3TransitionError("projection binding is malformed")
        closure = entry["closure"]
        path = entry["manifest_path"]
        digest = entry["manifest_sha256"]
        root = entry["closure_root_sha256"]
        if (
            type(closure) is not str
            or type(path) is not str
            or type(digest) is not str
            or type(root) is not str
            or PROJECTION_MANIFESTS.get(closure) != path
        ):
            raise Phase5IntegrationV3TransitionError("projection binding drifted")
        projection_paths.add(path)
        projection_values[closure] = _load_projection_manifest(
            project, path, digest, root
        )
    if set(projection_values) != set(PROJECTION_MANIFESTS):
        raise Phase5IntegrationV3TransitionError("projection set is incomplete")
    root_records = _verify_root_manifest(
        project, file_paths | projection_paths | {MANIFEST, CHECKPOINT}
    )
    return {
        "manifest": manifest,
        "projections": projection_values,
        "root_records": root_records,
    }


def verify(project: Path = PROJECT) -> dict[str, object]:
    project = Path(project)
    manifest_state = _verify_v3_manifest(project)
    for relative, digest in V1_FROZEN.items():
        _require_digest(project, relative, digest)
    for relative, digest in V2_FROZEN.items():
        _require_digest(project, relative, digest)
    for relative, digest in ACCEPTED_ANCHORS.items():
        _require_digest(project, relative, digest)
    for relative, digest in UNCHANGED_HOOKS.items():
        _require_digest(project, relative, digest)
    boundary = _verify_ast_boundary(project)
    broker = _verify_permission_broker_transition(project)
    projections = manifest_state["projections"]
    assert type(projections) is dict
    historical = {
        closure: _run_projection(project, projection)
        for closure, projection in sorted(projections.items())
    }
    return {
        "candidate": "phase5-integration-v3",
        "boundary": boundary,
        "permission_broker_transition": broker,
        "historical_execution_closures": historical,
        "root_records": manifest_state["root_records"],
        "reproducible_cumulative_command": REPRODUCIBLE_CUMULATIVE_COMMAND,
        "scope": "independent-default-off-v3-after-v10-v15-v32-acceptance",
    }


def main() -> int:
    print(MARKER + " " + json.dumps(verify(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
