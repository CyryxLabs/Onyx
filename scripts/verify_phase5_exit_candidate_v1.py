"""Verify the evidence-only Phase 5 Exit Candidate V1 composition.

The default command executes the accepted Integration V3 historical closure
and the proportional Grants R11 evidence gate. ``--no-external`` is a
focused-test mode and can never yield a release pass.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import sysconfig
import tempfile
import types
from pathlib import Path
from typing import Any

from scripts import verify_phase5_exit_retirement_v1 as exit_retirement


PROJECT = Path(__file__).resolve(strict=True).parents[1]
MANIFEST = "docs/onyx/checkpoints/phase5-exit-candidate-v1/manifest.json"
MARKER = "P5_EXIT_CANDIDATE_V1_OK"
SCHEMA = "onyx.phase5.exit-candidate.v1"
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_PATH = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\Z")

EXPECTED_ACCEPTANCE_IDS = (
    "VE-P5-RUNTIME-V10-E6-001",
    "VE-P51-GRANTS-R11-E6-001",
    "VE-P52-APPROVAL-INBOX-V15-E6-001",
    "VE-P53-CAPABILITY-NEXUS-V32-E6-001",
    "VE-P5-INTEGRATION-V3-E6-001",
)

EXPECTED_EXTERNAL = (
    (
        "runtime-v10",
        "scripts/verify_phase5_" + "runtime_v10_acceptance.py",
        "integration-v3-historical-projection",
        (),
        "P5_RUNTIME_V10_ACCEPTANCE_OK ",
        300,
    ),
    (
        "grants-r11",
        "scripts/verify_phase5_grants_r11.py",
        "proportional-r11-frozen-evidence",
        (),
        "P51_GRANTS_R11_EVIDENCE_OK ",
        180,
    ),
    (
        "approval-inbox-v15",
        "scripts/verify_phase5_approval_inbox_v15_acceptance.py",
        "integration-v3-historical-projection",
        (),
        "P52_APPROVAL_INBOX_V15_ACCEPTANCE_OK ",
        300,
    ),
    (
        "capability-nexus-v32",
        "scripts/verify_phase5_capability_nexus_v32_acceptance.py",
        "integration-v3-historical-projection",
        (),
        "P53_CAPABILITY_NEXUS_V32_ACCEPTANCE_OK ",
        300,
    ),
    (
        "integration-v3",
        "scripts/verify_phase5_integration_v3_acceptance.py",
        "projected-current-transition",
        (),
        "P5_INTEGRATION_V3_ACCEPTANCE_OK ",
        300,
    ),
)

HISTORICAL_PROJECTIONS = {
    "docs/onyx/CAPABILITY_MATRIX.md": (
        "2ba2507ccbf4ff5cae4a38609366f2c547bf47446527cf14ded3636806c10a87"
    ),
    "docs/onyx/VERIFICATION_EVIDENCE.md": (
        "7f1d216fc8fb5e9b02f40b1bab21c80c79746c2dcc1171df4829708494e4a2ad"
    ),
}

EXPECTED_STARTUP_CLOSURE = tuple(
    sorted(
        {
            ".github/workflows/release-packages.yml",
            "packaging/linux/onyx.desktop",
            "packaging/macos/entitlements.plist",
            "packaging/onyx.spec",
            "packaging/windows/onyx.iss",
            "scripts/bootstrap_onyx_live_v8.pyw",
            "scripts/build_release.py",
            "scripts/check_release_eligibility.py",
            "scripts/launch_onyx.pyw",
            "setup.py",
            *{f"scripts/launch_onyx_live_v{version}.pyw" for version in range(1, 9)},
            *{
                f"scripts/launch_onyx_live_v{version}_{mode}.cmd"
                for version in range(4, 9)
                for mode in ("active", "rollback")
            },
        }
    )
)

FORBIDDEN_EXIT_SYMBOLS = (
    "phase5_exit_candidate",
    "phase5-exit-candidate",
    "onyx_phase5_exit",
    "p5_exit_candidate",
)

LIVE_SURFACES = (
    "main.py",
    "ui.py",
    "dashboard/server.py",
    "scripts/launch_onyx.pyw",
    "scripts/start_onyx.ps1",
)


class Phase5ExitCandidateV1Error(RuntimeError):
    """The candidate composition could not be verified exactly."""


def _regular_path(project: Path, relative: str) -> Path:
    if type(relative) is not str or not _SAFE_PATH.fullmatch(relative):
        raise Phase5ExitCandidateV1Error(f"unsafe manifest path: {relative!r}")
    root = project.resolve(strict=True)
    lexical = root / Path(*relative.split("/"))
    try:
        before = os.lstat(lexical)
        resolved = lexical.resolve(strict=True)
        after = os.stat(resolved, follow_symlinks=False)
    except (OSError, RuntimeError) as exc:
        raise Phase5ExitCandidateV1Error(f"missing candidate path: {relative}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise Phase5ExitCandidateV1Error(
            f"candidate path escapes project: {relative}"
        ) from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or not stat.S_ISREG(after.st_mode)
        or lexical.absolute() != resolved
    ):
        raise Phase5ExitCandidateV1Error(
            f"candidate path is not a canonical regular file: {relative}"
        )
    return resolved


def _bytes(project: Path, relative: str) -> bytes:
    path = _regular_path(project, relative)
    try:
        before = os.stat(path, follow_symlinks=False)
        payload = path.read_bytes()
        after = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise Phase5ExitCandidateV1Error(f"cannot read {relative}") from exc
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if identity_before != identity_after or len(payload) != after.st_size:
        raise Phase5ExitCandidateV1Error(f"path changed during read: {relative}")
    return payload


def _sha256(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _binding_state(project: Path, relative: str, expected: str) -> str:
    try:
        return exit_retirement.classify(project, relative, expected)
    except exit_retirement.Phase5ExitRetirementError as error:
        raise Phase5ExitCandidateV1Error(str(error)) from error


def _text(project: Path, relative: str) -> str:
    try:
        return _bytes(project, relative).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Phase5ExitCandidateV1Error(f"{relative} is not UTF-8") from exc


def _load_manifest(project: Path) -> dict[str, Any]:
    try:
        value = json.loads(_text(project, MANIFEST))
    except json.JSONDecodeError as exc:
        raise Phase5ExitCandidateV1Error("candidate manifest is not JSON") from exc
    if type(value) is not dict:
        raise Phase5ExitCandidateV1Error("candidate manifest must be an object")
    expected_keys = {
        "schema",
        "candidate",
        "created_at",
        "status",
        "claims",
        "rollback",
        "acceptances",
        "files",
        "external_verifiers",
        "startup_closure",
    }
    if set(value) != expected_keys:
        raise Phase5ExitCandidateV1Error("candidate manifest schema drift")
    if (
        value["schema"] != SCHEMA
        or value["candidate"] != "phase5-exit-candidate-v1"
        or value["created_at"] != "2026-07-23"
        or value["status"] != "candidate-e1-e5-e6-pending"
    ):
        raise Phase5ExitCandidateV1Error("candidate manifest identity drift")
    return value


def _verify_claims(manifest: dict[str, Any]) -> dict[str, bool]:
    expected = {
        "e1_e5_candidate": True,
        "external_e6_accepted": False,
        "phase5_exit_complete": False,
        "phase6_unlocked": False,
        "live_activated": False,
        "runtime_authority_added": False,
        "onyx_complete": False,
    }
    if manifest.get("claims") != expected:
        raise Phase5ExitCandidateV1Error("candidate claims exceed E1-E5 scope")
    rollback = manifest.get("rollback")
    if rollback != {
        "kind": "evidence-only",
        "application_restart_required": False,
        "runtime_state_created": False,
        "integration_v3_transition_retained": True,
    }:
        raise Phase5ExitCandidateV1Error("candidate rollback contract drift")
    return expected


def _verify_files(project: Path, manifest: dict[str, Any]) -> dict[str, str]:
    entries = manifest.get("files")
    if type(entries) is not list or not entries:
        raise Phase5ExitCandidateV1Error("candidate file inventory missing")
    actual: dict[str, str] = {}
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "role", "sha256"}:
            raise Phase5ExitCandidateV1Error("candidate file entry schema drift")
        relative = entry["path"]
        digest = entry["sha256"]
        role = entry["role"]
        if (
            type(relative) is not str
            or type(role) is not str
            or not role
            or type(digest) is not str
            or not _HEX64.fullmatch(digest)
            or relative in actual
        ):
            raise Phase5ExitCandidateV1Error("candidate file entry invalid")
        computed = _sha256(project, relative)
        if computed != digest:
            _binding_state(project, relative, digest)
        actual[relative] = digest
    required = {
        "docs/onyx/adrs/ADR-0018-phase5-exit-candidate-v1.md",
        "docs/onyx/checkpoints/phase5-exit-candidate-v1/PHASE5_EXIT_CANDIDATE_V1_CHECKPOINT.md",
        "scripts/verify_phase5_exit_candidate_v1.py",
        "tests/test_phase5_exit_candidate_v1.py",
        "core/phase5_" + "runtime_v10.py",
        "core/session_grants_v11.py",
        "core/approval_inbox_v15.py",
        "core/capability_nexus_v32.py",
        "core/phase5_integration_v3.py",
        "core/phase5_component_adapters_v3.py",
        "main.py",
        "ui.py",
        "dashboard/server.py",
        *HISTORICAL_PROJECTIONS,
        *EXPECTED_STARTUP_CLOSURE,
    }
    if not required <= set(actual):
        missing = sorted(required - set(actual))
        raise Phase5ExitCandidateV1Error(
            f"candidate inventory lacks required anchor: {missing[0]}"
        )
    for relative, expected in HISTORICAL_PROJECTIONS.items():
        if actual.get(relative) != expected:
            raise Phase5ExitCandidateV1Error(
                f"historical projection full-file hash drift: {relative}"
            )
    return actual


def _discover_startup_closure(project: Path) -> tuple[str, ...]:
    discovered: set[str] = set()
    scripts = project / "scripts"
    if not scripts.is_dir():
        raise Phase5ExitCandidateV1Error("startup scripts directory is missing")
    script_name = re.compile(
        r"(?:"
        r"launch_onyx(?:_live_v[0-9]+(?:_(?:active|rollback))?)?\.(?:pyw|cmd)"
        r"|bootstrap_onyx_live_v[0-9]+\.pyw"
        r"|start_onyx\.ps1"
        r"|build_release[^/]*\.py"
        r"|check_release_eligibility[^/]*\.py"
        r")\Z"
    )
    for path in scripts.iterdir():
        if script_name.fullmatch(path.name):
            discovered.add(f"scripts/{path.name}")

    packaging = project / "packaging"
    if not packaging.is_dir():
        raise Phase5ExitCandidateV1Error("packaging directory is missing")
    for path in packaging.rglob("*"):
        if path.is_file() or path.is_symlink():
            discovered.add(path.relative_to(project).as_posix())

    workflows = project / ".github" / "workflows"
    if not workflows.is_dir():
        raise Phase5ExitCandidateV1Error("release workflow directory is missing")
    for path in workflows.iterdir():
        if re.fullmatch(r"release[^/]*\.ya?ml", path.name):
            discovered.add(f".github/workflows/{path.name}")

    if (project / "setup.py").exists():
        discovered.add("setup.py")
    return tuple(sorted(discovered))


def _verify_startup_closure(
    project: Path, manifest: dict[str, Any], files: dict[str, str]
) -> dict[str, object]:
    entries = manifest.get("startup_closure")
    if type(entries) is not list or tuple(entries) != EXPECTED_STARTUP_CLOSURE:
        raise Phase5ExitCandidateV1Error("startup closure manifest drift")
    discovered = _discover_startup_closure(project)
    if discovered != EXPECTED_STARTUP_CLOSURE:
        missing = sorted(set(EXPECTED_STARTUP_CLOSURE) - set(discovered))
        extra = sorted(set(discovered) - set(EXPECTED_STARTUP_CLOSURE))
        if missing or project.resolve() != PROJECT.resolve():
            detail = missing[0] if missing else extra[0]
            raise Phase5ExitCandidateV1Error(f"startup closure path drift: {detail}")
        try:
            exit_retirement.authenticate_successor("scripts/package_hygiene.py")
        except exit_retirement.Phase5ExitRetirementError as error:
            raise Phase5ExitCandidateV1Error(str(error)) from error
    if not set(EXPECTED_STARTUP_CLOSURE) <= set(files):
        raise Phase5ExitCandidateV1Error(
            "startup closure is not fully hash-bound by the candidate"
        )
    for relative in EXPECTED_STARTUP_CLOSURE:
        lowered = _text(project, relative).casefold()
        if any(symbol in lowered for symbol in FORBIDDEN_EXIT_SYMBOLS):
            raise Phase5ExitCandidateV1Error(
                f"Phase 5 Exit symbol entered startup surface: {relative}"
            )
    packaging_entrypoints = {
        ".github/workflows/release-packages.yml",
        "scripts/build_release.py",
        "scripts/check_release_eligibility.py",
        "setup.py",
        *{path for path in EXPECTED_STARTUP_CLOSURE if path.startswith("packaging/")},
    }
    return {
        "files": len(EXPECTED_STARTUP_CLOSURE),
        "launchers": sum(
            path.startswith("scripts/launch_onyx") for path in EXPECTED_STARTUP_CLOSURE
        ),
        "packaging_entrypoints": len(packaging_entrypoints),
    }


def _parse_acceptance_manifest(
    project: Path, relative: str, expected_record: str, expected_digest: str
) -> None:
    lines = _text(project, relative).splitlines()
    expected_line = f"{expected_digest}  {expected_record}"
    if lines != [expected_line]:
        raise Phase5ExitCandidateV1Error(
            f"acceptance manifest relation drift: {relative}"
        )


def _verify_acceptances(project: Path, manifest: dict[str, Any]) -> tuple[str, ...]:
    entries = manifest.get("acceptances")
    if type(entries) is not list or len(entries) != len(EXPECTED_ACCEPTANCE_IDS):
        raise Phase5ExitCandidateV1Error("acceptance composition cardinality drift")
    observed: list[str] = []
    for entry in entries:
        required = {
            "id",
            "record_path",
            "record_sha256",
            "acceptance_manifest_path",
            "acceptance_manifest_sha256",
            "scope",
        }
        if type(entry) is not dict or set(entry) != required:
            raise Phase5ExitCandidateV1Error("acceptance entry schema drift")
        acceptance_id = entry["id"]
        if (
            acceptance_id not in EXPECTED_ACCEPTANCE_IDS
            or acceptance_id in observed
            or type(entry["scope"]) is not str
            or not entry["scope"]
        ):
            raise Phase5ExitCandidateV1Error("acceptance entry identity drift")
        record_digest = entry["record_sha256"]
        manifest_digest = entry["acceptance_manifest_sha256"]
        if (
            type(record_digest) is not str
            or not _HEX64.fullmatch(record_digest)
            or type(manifest_digest) is not str
            or not _HEX64.fullmatch(manifest_digest)
        ):
            raise Phase5ExitCandidateV1Error("acceptance digest invalid")
        if _sha256(project, entry["record_path"]) != record_digest:
            raise Phase5ExitCandidateV1Error(
                f"acceptance record drift: {acceptance_id}"
            )
        if _sha256(project, entry["acceptance_manifest_path"]) != manifest_digest:
            raise Phase5ExitCandidateV1Error(
                f"acceptance manifest drift: {acceptance_id}"
            )
        _parse_acceptance_manifest(
            project,
            entry["acceptance_manifest_path"],
            entry["record_path"],
            record_digest,
        )
        record = _text(project, entry["record_path"])
        if acceptance_id not in record or "ACCEPTED" not in record:
            raise Phase5ExitCandidateV1Error(
                f"acceptance record content drift: {acceptance_id}"
            )
        observed.append(acceptance_id)
    if tuple(observed) != EXPECTED_ACCEPTANCE_IDS:
        raise Phase5ExitCandidateV1Error("acceptance composition order drift")
    return tuple(observed)


def _verify_default_off(project: Path) -> dict[str, object]:
    relative = "core/phase5_integration_v3.py"
    try:
        tree = ast.parse(_text(project, relative), filename=relative)
    except SyntaxError as exc:
        raise Phase5ExitCandidateV1Error("Integration V3 is not valid Python") from exc
    target: ast.ClassDef | None = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "IntegrationFlagsV3":
            target = node
            break
    if target is None:
        raise Phase5ExitCandidateV1Error("IntegrationFlagsV3 is unavailable")
    defaults: dict[str, object] = {}
    for node in target.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            try:
                defaults[node.target.id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                raise Phase5ExitCandidateV1Error(
                    f"nonliteral integration flag: {node.target.id}"
                ) from None
    expected_names = {
        "runtime",
        "grant_shadow",
        "nexus_projection",
        "approval_inbox",
        "low_risk",
        "local_catalog_read",
        "dashboard_projection",
        "integration",
    }
    if set(defaults) != expected_names or any(
        type(value) is not bool or value is not False for value in defaults.values()
    ):
        raise Phase5ExitCandidateV1Error("Integration V3 flags are not exact false")

    checked: list[str] = []
    for relative in LIVE_SURFACES:
        path = project / Path(*relative.split("/"))
        if not path.is_file():
            continue
        lowered = _text(project, relative).casefold()
        if any(symbol in lowered for symbol in FORBIDDEN_EXIT_SYMBOLS):
            raise Phase5ExitCandidateV1Error(
                f"exit candidate entered live surface: {relative}"
            )
        checked.append(relative)
    return {"flags": len(expected_names), "live_surfaces": tuple(checked)}


def _verify_projection_words(project: Path) -> None:
    checkpoint = _text(
        project,
        "docs/onyx/checkpoints/phase5-exit-candidate-v1/"
        "PHASE5_EXIT_CANDIDATE_V1_CHECKPOINT.md",
    )
    adr = _text(project, "docs/onyx/adrs/ADR-0018-phase5-exit-candidate-v1.md")
    matrix_delta = _text(
        project,
        "docs/onyx/checkpoints/phase5-exit-candidate-v1/CAPABILITY_MATRIX_DELTA.md",
    )
    evidence_delta = _text(
        project,
        "docs/onyx/checkpoints/phase5-exit-candidate-v1/VERIFICATION_EVIDENCE_DELTA.md",
    )
    for label, value in (
        ("checkpoint", checkpoint),
        ("ADR", adr),
        ("capability matrix delta", matrix_delta),
        ("verification evidence delta", evidence_delta),
    ):
        required = (
            "E1-E5",
            "E6",
            "Phase 5 remains incomplete",
            "Phase 6",
            "rollback",
            "default-off",
        )
        if any(token not in value for token in required):
            raise Phase5ExitCandidateV1Error(
                f"{label} omits an explicit candidate boundary"
            )


def _external_specs(manifest: dict[str, Any]) -> tuple[tuple[object, ...], ...]:
    entries = manifest.get("external_verifiers")
    if type(entries) is not list or len(entries) != len(EXPECTED_EXTERNAL):
        raise Phase5ExitCandidateV1Error("external verifier inventory drift")
    normalized: list[tuple[object, ...]] = []
    for entry, expected in zip(entries, EXPECTED_EXTERNAL, strict=True):
        if type(entry) is not dict or set(entry) != {
            "name",
            "path",
            "execution",
            "args",
            "marker_prefix",
            "timeout_seconds",
        }:
            raise Phase5ExitCandidateV1Error("external verifier entry schema drift")
        actual = (
            entry["name"],
            entry["path"],
            entry["execution"],
            tuple(entry["args"]) if type(entry["args"]) is list else None,
            entry["marker_prefix"],
            entry["timeout_seconds"],
        )
        if actual != expected:
            raise Phase5ExitCandidateV1Error(
                f"external verifier contract drift: {expected[0]}"
            )
        normalized.append(expected)
    return tuple(normalized)


def _execute_exact_module(project: Path, relative: str, name: str) -> types.ModuleType:
    path = _regular_path(project, relative)
    source = _bytes(project, relative)
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    original_path = list(sys.path)
    environment_root = Path(sys.executable).resolve().parent.parent
    library_candidates = (
        environment_root / "Lib/site-packages",
        environment_root
        / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages",
        Path(sysconfig.get_path("purelib")),
    )
    for library in library_candidates:
        value = str(library)
        if library.is_dir() and value not in sys.path:
            sys.path.insert(0, value)
    try:
        exec(compile(source, str(path), "exec"), module.__dict__)
    except BaseException as exc:
        raise Phase5ExitCandidateV1Error(
            f"existing verifier could not load: {relative}"
        ) from exc
    finally:
        sys.path[:] = original_path
    return module


def _run_grants_proportional(project: Path) -> str:
    """Execute exact R11 verifier code against its immutable stored evidence.

    Its original live-surface scan is intentionally historical and cannot be
    replayed against the later accepted Integration V3/live-activation tree.
    """

    relative = "scripts/verify_phase5_grants_r11.py"
    module = _execute_exact_module(
        project, relative, "_onyx_phase5_exit_r11_proportional"
    )
    try:
        root_sha = module._sha(module._path(project, module.TOP_MANIFEST))
        artifact_sha = module._sha(module._path(project, module.ARTIFACT_MANIFEST))
        top = module._parse_manifest(
            module._path(project, module.TOP_MANIFEST),
            (module.ARTIFACT_MANIFEST,),
        )
        artifacts = module._parse_manifest(
            module._path(project, module.ARTIFACT_MANIFEST)
        )
        artifact_map = {path: digest for digest, path in artifacts}
        immutable_paths = (
            "core/session_grants_v11.py",
            relative,
            module.CHECKPOINT,
            module.BUNDLE,
            module.JUNIT,
            module.LIVE_SCAN_MANIFEST,
            module.RAW_LOG,
            module.STATIC_LOG,
        )
        immutable_entries = tuple(
            (artifact_map[path], path) for path in immutable_paths
        )
        module._verify_entries(project, top)
        module._verify_entries(project, immutable_entries)
        bundle = module._read_bundle(project)
        counts, _timestamp, names = module._junit(project)
        history = bundle.get("history")
        limits = module._constants(project)
        raw = module._kv_log(project, module.RAW_LOG)
        static = module._kv_log(project, module.STATIC_LOG)
        module._validate_code_claims(project)
    except BaseException as exc:
        raise Phase5ExitCandidateV1Error(
            "R11 proportional frozen-evidence execution failed"
        ) from exc
    if (
        root_sha != "b4759d8840611e2affbd322831ae8dc88ff84ac09701a24b4a6f56df66463071"
        or artifact_sha
        != "0253aba6b0fed67bbac6b1eda55ea32a9928f44b036b2fbc0c5daec78e0b33d7"
        or counts != {"passed": 51, "failed": 0, "errors": 0, "skipped": 0}
        or len(names) != 51
        or type(history) is not dict
        or len(history) != 10
        or type(limits) is not dict
        or not limits
        or bundle.get("counts") != counts
        or bundle.get("limits") != limits
        or bundle.get("status") != "candidate-default-off-not-accepted"
        or bundle.get("feature_flag")
        != {"default": False, "name": "ONYX_GRANT_EVALUATOR"}
        or bundle.get("external_e6")
        != {
            "accepted": False,
            "required_before_acceptance": True,
            "status": "pending-external-review",
        }
        or len(artifacts) != 42
        or len(immutable_entries) != 8
        or raw.get("exit_code") != "0"
        or static.get("ruff_exit_code") != "0"
        or not callable(getattr(module, "verify_evidence", None))
    ):
        raise Phase5ExitCandidateV1Error(
            "R11 proportional frozen-evidence result drifted"
        )
    return "P51_GRANTS_R11_EVIDENCE_OK " + json.dumps(
        {
            "execution": "proportional-r11-frozen-evidence",
            "root_sha256": root_sha,
            "artifact_sha256": artifact_sha,
            "artifact_records": len(artifacts),
            "immutable_records_rehashed": len(immutable_entries),
            "stored_tests": counts["passed"],
            "historical_candidates": len(history),
            "full_historical_live_scan_replayed": False,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _exact_projection_bytes(
    project: Path, relative: str, expected_digest: str
) -> bytes:
    current = _bytes(project, relative)
    if hashlib.sha256(current).hexdigest() != expected_digest:
        raise Phase5ExitCandidateV1Error(
            f"Integration V3 exact projection source drifted: {relative}"
        )
    return current


def _run_integration_projected(
    project: Path, *, timeout: int
) -> tuple[str, dict[str, object]]:
    relative = "scripts/verify_phase5_integration_v3_acceptance.py"
    module = _execute_exact_module(
        project, relative, "_onyx_phase5_exit_integration_v3_inventory"
    )
    expected: dict[str, str] = {
        relative: _sha256(project, relative),
        module.ACCEPTANCE_RECORD: _sha256(project, module.ACCEPTANCE_RECORD),
        module.ACCEPTANCE_MANIFEST: _sha256(project, module.ACCEPTANCE_MANIFEST),
        module.MANIFEST: module.MANIFEST_SHA256,
        module.CHECKPOINT: module.CHECKPOINT_SHA256,
        module.ROOT_MANIFEST: module.ROOT_MANIFEST_SHA256,
        **module.CANDIDATE_FILES,
        **module.V1_FROZEN,
        **module.V2_FROZEN,
        **module.ACCEPTED_ANCHORS,
    }
    for projection in module.PROJECTIONS.values():
        projection_path = projection["path"]
        expected[projection_path] = projection["sha256"]
        try:
            projection_value = json.loads(_text(project, projection_path))
        except json.JSONDecodeError as exc:
            raise Phase5ExitCandidateV1Error(
                "Integration V3 projection manifest is invalid"
            ) from exc
        files = projection_value.get("files")
        if type(files) is not list:
            raise Phase5ExitCandidateV1Error(
                "Integration V3 projection file inventory is invalid"
            )
        for entry in files:
            if type(entry) is not dict or set(entry) != {"path", "sha256"}:
                raise Phase5ExitCandidateV1Error(
                    "Integration V3 projection file entry drifted"
                )
            prior = expected.get(entry["path"])
            if prior is not None and prior != entry["sha256"]:
                raise Phase5ExitCandidateV1Error(
                    "Integration V3 projections disagree on a shared path"
                )
            expected[entry["path"]] = entry["sha256"]

    with tempfile.TemporaryDirectory(prefix="onyx-p5-exit-v1-integration-") as raw:
        root = Path(raw).resolve(strict=True)
        for path, digest in sorted(expected.items()):
            payload = _exact_projection_bytes(project, path, digest)
            destination = root.joinpath(*path.split("/"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise Phase5ExitCandidateV1Error(
                    f"Integration V3 projected write drifted: {path}"
                )
        entrypoint = root.joinpath(*relative.split("/"))
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-S", "-B", str(entrypoint)],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Phase5ExitCandidateV1Error(
                "Integration V3 projected verifier did not complete"
            ) from exc
    marker = "P5_INTEGRATION_V3_ACCEPTANCE_OK "
    lines = completed.stdout.splitlines()
    if (
        completed.returncode != 0
        or completed.stderr
        or len(lines) != 1
        or not lines[0].startswith(marker)
    ):
        raise Phase5ExitCandidateV1Error(
            "Integration V3 projected verifier failed or marker drifted"
        )
    try:
        payload = json.loads(lines[0][len(marker) :])
    except json.JSONDecodeError as exc:
        raise Phase5ExitCandidateV1Error(
            "Integration V3 external marker payload is invalid"
        ) from exc
    if type(payload) is not dict:
        raise Phase5ExitCandidateV1Error(
            "Integration V3 external marker payload is not an object"
        )
    return lines[0], payload


def _run_external(project: Path, manifest: dict[str, Any]) -> dict[str, str]:
    specs = _external_specs(manifest)
    results = {"grants-r11": _run_grants_proportional(project)}
    integration_spec = next(value for value in specs if value[0] == "integration-v3")
    integration_line, integration_payload = _run_integration_projected(
        project, timeout=int(integration_spec[5])
    )
    results["integration-v3"] = integration_line
    expected_closures = {
        "runtime-v10-e6",
        "approval-inbox-v15-e6",
        "capability-nexus-v32-e6",
    }
    closure_roots = integration_payload.get("closure_roots")
    if (
        type(closure_roots) is not dict
        or set(closure_roots) != expected_closures
        or integration_payload.get("transition_marker")
        != "P5_INTEGRATION_V3_TRANSITION_OK"
    ):
        raise Phase5ExitCandidateV1Error(
            "Integration V3 did not execute the three historical verifiers"
        )
    for name, _relative, execution, _args, marker, _timeout in specs:
        if execution == "integration-v3-historical-projection":
            results[str(name)] = str(marker) + json.dumps(
                {
                    "execution": execution,
                    "closure_root_sha256": closure_roots[f"{name}-e6"],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
    return results


def verify(project: Path = PROJECT, *, run_external: bool = True) -> dict[str, object]:
    project = Path(project)
    manifest = _load_manifest(project)
    claims = _verify_claims(manifest)
    files = _verify_files(project, manifest)
    acceptances = _verify_acceptances(project, manifest)
    default_off = _verify_default_off(project)
    startup_closure = _verify_startup_closure(project, manifest, files)
    _verify_projection_words(project)
    specs = _external_specs(manifest)
    external = _run_external(project, manifest) if run_external else {}
    if run_external and len(external) != len(specs):
        raise Phase5ExitCandidateV1Error("external verifier set incomplete")
    return {
        "candidate": "phase5-exit-candidate-v1",
        "status": (
            "e1-e5-verified-e6-pending"
            if run_external
            else "focused-only-not-release-pass"
        ),
        "manifest_sha256": _sha256(project, MANIFEST),
        "files_verified": len(files),
        "acceptances": acceptances,
        "external_verifiers_executed": run_external,
        "external_verifier_count": len(external),
        "default_off": default_off,
        "startup_closure": startup_closure,
        "rollback": manifest["rollback"],
        "claims": claims,
        "external_e6_accepted": False,
        "phase6_unlocked": False,
        "onyx_complete": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-external",
        action="store_true",
        help="focused composition test only; never a release pass",
    )
    arguments = parser.parse_args()
    payload = verify(run_external=not arguments.no_external)
    print(MARKER + " " + json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
