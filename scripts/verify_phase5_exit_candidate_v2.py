"""Verify the evidence-only Phase 5 Exit Candidate V2 composition."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

from scripts import verify_phase5_exit_retirement_v1 as exit_retirement


PROJECT = Path(__file__).resolve(strict=True).parents[1]
MANIFEST = "docs/onyx/checkpoints/phase5-exit-candidate-v2/manifest.json"
CHECKPOINT = (
    "docs/onyx/checkpoints/phase5-exit-candidate-v2/"
    "PHASE5_EXIT_CANDIDATE_V2_CHECKPOINT.md"
)
CUMULATIVE_SELECTION = (
    "docs/onyx/checkpoints/phase5-exit-candidate-v2/cumulative-selection.json"
)
MARKER = "P5_EXIT_CANDIDATE_V2_OK"
SCHEMA = "onyx.phase5.exit-candidate.v2"

C1_MANIFEST = "docs/onyx/checkpoints/phase5-exit-candidate-v1/manifest.json"
C1_CHECKPOINT = (
    "docs/onyx/checkpoints/phase5-exit-candidate-v1/"
    "PHASE5_EXIT_CANDIDATE_V1_CHECKPOINT.md"
)
C1_VERIFIER = "scripts/verify_phase5_exit_candidate_v1.py"
C1_TESTS = "tests/test_phase5_exit_candidate_v1.py"
C1_BINDINGS = {
    C1_MANIFEST: "3188e006fa11040eb8d743086c74f0ceae70a1d62b70e9919ca73cb41187ec80",
    C1_CHECKPOINT: "8788ce0185800725a7af8e7754dc72a12890b89e62c0cb4f1ef4a5c553d1688d",
    C1_VERIFIER: "a49f23a28c304c6ee62125636c3b30d1af35619716d00e8d33147b002a29f01c",
    C1_TESTS: "e7700a8450f82fc77ef32719b3cbe0e0299e865435e83db746c3a77a88ce7c73",
}

V9_ACCEPTANCE_ID = "VE-ONYX-LIVE-ACTIVATION-V9-E6-001"
V9_MANIFEST = "docs/onyx/checkpoints/onyx-live-activation-v9/manifest.json"
V9_MANIFEST_SHA256 = "38de625b7725dab7aa9c7906f7f3164687f1f20a0cca6e683fe64145bb53142a"
V9_ACCEPTANCE_RECORD = "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V9-E6-001.md"
V9_ACCEPTANCE_RECORD_SHA256 = (
    "91a3613df269d1fe222c437b92b0d3022f3f2a603ae9689a951e63e0c4e4f0ec"
)
V9_ACCEPTANCE_METADATA = (
    "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V9-E6-001.manifest.json"
)
V9_ACCEPTANCE_METADATA_SHA256 = (
    "bb8a3e88b6db05b548a306aba3e2c09bdd3b0f760777d34a64326e8820743cbd"
)
V9_ACCEPTANCE_VERIFIER = "scripts/verify_onyx_live_activation_v9_acceptance.py"
V9_ACCEPTANCE_VERIFIER_SHA256 = (
    "660f07a81dbd9bfd141f9ca2e11ed45124e0d873db5a0ff1aad84cb7c4667d1c"
)
V9_ACCEPTANCE_TEST = "tests/test_onyx_live_activation_v9_acceptance.py"
V9_ACCEPTANCE_TEST_SHA256 = (
    "ea1377949933297b4b159f29165723e51fbc60fb15fc88c3fb1f33db149b00ae"
)
V9_ACCEPTANCE_SHA = "docs/onyx/VE-ACCEPTANCE-ONYX-LIVE-ACTIVATION-V9-E6-001.sha256"
V9_ACCEPTANCE_SHA256 = (
    "a69c912b947b4605305da86b070fbddab8812a84cc8c2cf6b138a641e5cb339b"
)
V9_SOURCE_MANIFEST = "docs/onyx/VE-SOURCE-ONYX-LIVE-ACTIVATION-V9-E6-001.sha256"
V9_SOURCE_MANIFEST_SHA256 = (
    "0082d6b553a1f6af2b35aa1661f46905ac737baf7c7b362fb6642304d2f27871"
)
V9_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-ONYX-LIVE-ACTIVATION-V9-E6-001.sha256"
V9_ARTIFACT_MANIFEST_SHA256 = (
    "034c4569ee69cb60b4e821ee1e64a383fb29887b4f2cd196689681ff45889d5e"
)
V9_EVIDENCE_ROOT_SHA256 = (
    "88307dbbf5ac2f3d1656549db94cd1293103a12b38ba8d157271f71700c5123d"
)

HISTORICAL_PROJECTIONS = {
    "docs/onyx/CAPABILITY_MATRIX.md": (
        "2ba2507ccbf4ff5cae4a38609366f2c547bf47446527cf14ded3636806c10a87"
    ),
    "docs/onyx/VERIFICATION_EVIDENCE.md": (
        "7f1d216fc8fb5e9b02f40b1bab21c80c79746c2dcc1171df4829708494e4a2ad"
    ),
}

EXPECTED_COMPONENT_ACCEPTANCES = (
    "VE-P5-RUNTIME-V10-E6-001",
    "VE-P51-GRANTS-R11-E6-001",
    "VE-P52-APPROVAL-INBOX-V15-E6-001",
    "VE-P53-CAPABILITY-NEXUS-V32-E6-001",
    "VE-P5-INTEGRATION-V3-E6-001",
)

EXPECTED_CUMULATIVE_TESTS = (
    "tests/test_session_grants_v11.py",
    "tests/test_approval_inbox_v15_acceptance.py",
    "tests/test_capability_nexus_v32_acceptance.py",
    "tests/test_phase5_component_adapters_v3.py",
    "tests/test_phase5_runtime_v10.py",
    "tests/test_phase5_integration_v3.py",
    "tests/test_phase5_integration_v3_transition.py",
    "tests/test_onyx_live_activation_v9.py",
    "tests/test_onyx_live_activation_v9_acceptance.py",
    "tests/test_phase5_exit_candidate_v2.py",
)
EXPECTED_CUMULATIVE_ARGUMENTS = (
    "-q",
    "--disable-warnings",
    "--basetemp",
    ".pytest-p5-exit-v2-compatible",
)

EXPECTED_STARTUP_CLOSURE = tuple(
    sorted(
        {
            ".github/workflows/release-packages.yml",
            "packaging/linux/onyx.desktop",
            "packaging/macos/entitlements.plist",
            "packaging/onyx.spec",
            "packaging/windows/onyx.iss",
            "scripts/bootstrap_onyx_live_v8.pyw",
            "scripts/bootstrap_onyx_live_v9.pyw",
            "scripts/build_release.py",
            "scripts/check_release_eligibility.py",
            "scripts/launch_onyx.pyw",
            "setup.py",
            *{f"scripts/launch_onyx_live_v{version}.pyw" for version in range(1, 10)},
            *{
                f"scripts/launch_onyx_live_v{version}_{mode}.cmd"
                for version in range(4, 10)
                for mode in ("active", "rollback")
            },
        }
    )
)

ROOT_ALGORITHM = "sha256-domain-count-u32be-path-u32be-role-digest32-v1"
ROOT_DOMAIN = b"onyx.phase5.exit-candidate.v2.bindings.v1\0"
FORBIDDEN_PREVIOUS_ROOT_PREFIX = "176ca"
FORBIDDEN_EXIT_SYMBOLS = (
    "phase5_exit_candidate",
    "phase5-exit-candidate",
    "onyx_phase5_exit",
    "p5_exit_candidate",
)
APPLICATION_SURFACES = ("main.py", "ui.py", "dashboard/server.py")

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_PATH = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\Z")


class Phase5ExitCandidateV2Error(RuntimeError):
    """The Candidate V2 composition is incomplete, drifted or overclaimed."""


def _regular_path(project: Path, relative: str) -> Path:
    if type(relative) is not str or not _SAFE_PATH.fullmatch(relative):
        raise Phase5ExitCandidateV2Error(f"unsafe binding path: {relative!r}")
    root = project.resolve(strict=True)
    lexical = root.joinpath(*relative.split("/"))
    try:
        before = os.lstat(lexical)
        resolved = lexical.resolve(strict=True)
        after = os.stat(resolved, follow_symlinks=False)
    except (OSError, RuntimeError) as exc:
        raise Phase5ExitCandidateV2Error(f"missing binding path: {relative}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise Phase5ExitCandidateV2Error(
            f"binding path escapes project: {relative}"
        ) from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or not stat.S_ISREG(after.st_mode)
        or lexical.absolute() != resolved
    ):
        raise Phase5ExitCandidateV2Error(
            f"binding path is not a canonical regular file: {relative}"
        )
    return resolved


def _bytes(project: Path, relative: str) -> bytes:
    path = _regular_path(project, relative)
    try:
        before = os.stat(path, follow_symlinks=False)
        payload = path.read_bytes()
        after = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise Phase5ExitCandidateV2Error(f"cannot read binding: {relative}") from exc
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if before_identity != after_identity or len(payload) != after.st_size:
        raise Phase5ExitCandidateV2Error(f"binding changed during read: {relative}")
    return payload


def _sha256(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _binding_state(project: Path, relative: str, expected: str) -> str:
    try:
        return exit_retirement.classify(project, relative, expected)
    except exit_retirement.Phase5ExitRetirementError as error:
        raise Phase5ExitCandidateV2Error(str(error)) from error


def _text(project: Path, relative: str) -> str:
    try:
        return _bytes(project, relative).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Phase5ExitCandidateV2Error(f"binding is not UTF-8: {relative}") from exc


def _json(project: Path, relative: str) -> dict[str, Any]:
    try:
        value = json.loads(_text(project, relative))
    except json.JSONDecodeError as exc:
        raise Phase5ExitCandidateV2Error(f"invalid JSON: {relative}") from exc
    if type(value) is not dict:
        raise Phase5ExitCandidateV2Error(f"JSON object required: {relative}")
    return value


def _load_manifest(project: Path) -> dict[str, Any]:
    value = _json(project, MANIFEST)
    expected_keys = {
        "schema",
        "candidate",
        "created_at",
        "status",
        "claims",
        "rollback",
        "predecessor",
        "component_acceptances",
        "startup_closure",
        "cumulative_selection",
        "v9_acceptance",
        "independent_root",
        "files",
    }
    if set(value) != expected_keys:
        raise Phase5ExitCandidateV2Error("Candidate V2 manifest schema drift")
    if (
        value["schema"] != SCHEMA
        or value["candidate"] != "phase5-exit-candidate-v2"
        or value["created_at"] != "2026-07-23"
        or value["status"] != "candidate-e1-e5-e6-pending"
    ):
        raise Phase5ExitCandidateV2Error("Candidate V2 manifest identity drift")
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
        "v9_e6_composed": True,
    }
    if manifest.get("claims") != expected:
        raise Phase5ExitCandidateV2Error("Candidate V2 claims exceed its scope")
    if manifest.get("rollback") != {
        "kind": "evidence-only",
        "application_restart_required": False,
        "runtime_state_created": False,
        "candidate_v1_retained": True,
        "activation_v9_retained": True,
    }:
        raise Phase5ExitCandidateV2Error("Candidate V2 rollback contract drift")
    return expected


def _verify_files(
    project: Path, manifest: dict[str, Any]
) -> tuple[list[dict[str, str]], dict[str, str]]:
    raw = manifest.get("files")
    if type(raw) is not list or not raw:
        raise Phase5ExitCandidateV2Error("Candidate V2 file bindings are absent")
    entries: list[dict[str, str]] = []
    digests: dict[str, str] = {}
    for entry in raw:
        if type(entry) is not dict or set(entry) != {"path", "role", "sha256"}:
            raise Phase5ExitCandidateV2Error("Candidate V2 binding schema drift")
        relative, role, digest = entry["path"], entry["role"], entry["sha256"]
        if (
            type(relative) is not str
            or not _SAFE_PATH.fullmatch(relative)
            or type(role) is not str
            or not role
            or type(digest) is not str
            or not _HEX64.fullmatch(digest)
            or relative in digests
            or relative == MANIFEST
        ):
            raise Phase5ExitCandidateV2Error("Candidate V2 binding is invalid")
        actual = _sha256(project, relative)
        if actual != digest:
            _binding_state(project, relative, digest)
        normalized = {"path": relative, "role": role, "sha256": digest}
        entries.append(normalized)
        digests[relative] = digest
    required = {
        CHECKPOINT,
        CUMULATIVE_SELECTION,
        "scripts/verify_phase5_exit_candidate_v2.py",
        "tests/test_phase5_exit_candidate_v2.py",
        *EXPECTED_CUMULATIVE_TESTS,
        *C1_BINDINGS,
        *HISTORICAL_PROJECTIONS,
        *EXPECTED_STARTUP_CLOSURE,
        V9_MANIFEST,
        V9_ACCEPTANCE_RECORD,
        V9_ACCEPTANCE_METADATA,
        V9_ACCEPTANCE_VERIFIER,
        V9_ACCEPTANCE_TEST,
        V9_ACCEPTANCE_SHA,
        V9_SOURCE_MANIFEST,
        V9_ARTIFACT_MANIFEST,
    }
    if not required <= set(digests):
        missing = sorted(required - set(digests))
        raise Phase5ExitCandidateV2Error(
            f"Candidate V2 required binding is absent: {missing[0]}"
        )
    for relative, expected in {**C1_BINDINGS, **HISTORICAL_PROJECTIONS}.items():
        if digests.get(relative) != expected:
            raise Phase5ExitCandidateV2Error(
                f"Candidate V2 frozen root drift: {relative}"
            )
    return entries, digests


def _u32(value: int) -> bytes:
    if type(value) is not int or value < 0 or value > 0xFFFFFFFF:
        raise Phase5ExitCandidateV2Error("binding frame length is outside uint32")
    return value.to_bytes(4, "big")


def _binding_frame(entries: list[dict[str, str]]) -> bytes:
    if not entries:
        raise Phase5ExitCandidateV2Error("independent root cannot bind an empty set")
    ordered = sorted(entries, key=lambda entry: entry["path"].encode("utf-8"))
    frame = bytearray(ROOT_DOMAIN)
    frame.extend(_u32(len(ordered)))
    for entry in ordered:
        path_bytes = entry["path"].encode("utf-8")
        role_bytes = entry["role"].encode("utf-8")
        frame.extend(b"\x01")
        frame.extend(_u32(len(path_bytes)))
        frame.extend(path_bytes)
        frame.extend(_u32(len(role_bytes)))
        frame.extend(role_bytes)
        frame.extend(bytes.fromhex(entry["sha256"]))
    return bytes(frame)


def _independent_root(entries: list[dict[str, str]]) -> str:
    return hashlib.sha256(_binding_frame(entries)).hexdigest()


def _verify_independent_root(
    manifest: dict[str, Any], entries: list[dict[str, str]]
) -> str:
    expected = manifest.get("independent_root")
    if type(expected) is not dict or set(expected) != {
        "algorithm",
        "binding_count",
        "sha256",
    }:
        raise Phase5ExitCandidateV2Error("independent root declaration drift")
    actual = _independent_root(entries)
    if (
        expected["algorithm"] != ROOT_ALGORITHM
        or expected["binding_count"] != len(entries)
        or expected["sha256"] != actual
        or actual.startswith(FORBIDDEN_PREVIOUS_ROOT_PREFIX)
    ):
        raise Phase5ExitCandidateV2Error("independent root verification failed")
    return actual


def _discover_startup_closure(project: Path) -> tuple[str, ...]:
    discovered: set[str] = set()
    scripts = project / "scripts"
    if not scripts.is_dir():
        raise Phase5ExitCandidateV2Error("startup scripts directory is missing")
    script_name = re.compile(
        r"(?:"
        r"launch_onyx(?:_live_v[0-9]+(?:_(?:active|rollback))?)?\.(?:pyw|cmd)"
        r"|bootstrap_onyx_live_v[0-9]+\.pyw"
        r"|build_release[^/]*\.py"
        r"|check_release_eligibility[^/]*\.py"
        r")\Z"
    )
    for path in scripts.iterdir():
        if script_name.fullmatch(path.name):
            discovered.add(f"scripts/{path.name}")

    packaging = project / "packaging"
    if not packaging.is_dir():
        raise Phase5ExitCandidateV2Error("packaging directory is missing")
    for path in packaging.rglob("*"):
        if path.is_file() or path.is_symlink():
            discovered.add(path.relative_to(project).as_posix())

    workflows = project / ".github" / "workflows"
    if not workflows.is_dir():
        raise Phase5ExitCandidateV2Error("release workflow directory is missing")
    for path in workflows.iterdir():
        if re.fullmatch(r"release[^/]*\.ya?ml", path.name):
            discovered.add(f".github/workflows/{path.name}")
    if (project / "setup.py").exists():
        discovered.add("setup.py")
    return tuple(sorted(discovered))


def _verify_startup_closure(
    project: Path, manifest: dict[str, Any], digests: dict[str, str]
) -> dict[str, int]:
    declared = manifest.get("startup_closure")
    if type(declared) is not list or tuple(declared) != EXPECTED_STARTUP_CLOSURE:
        raise Phase5ExitCandidateV2Error("startup closure manifest drift")
    discovered = _discover_startup_closure(project)
    if discovered != EXPECTED_STARTUP_CLOSURE:
        missing = sorted(set(EXPECTED_STARTUP_CLOSURE) - set(discovered))
        extra = sorted(set(discovered) - set(EXPECTED_STARTUP_CLOSURE))
        if missing or project.resolve() != PROJECT.resolve():
            detail = missing[0] if missing else extra[0]
            raise Phase5ExitCandidateV2Error(f"startup closure path drift: {detail}")
        try:
            exit_retirement.authenticate_successor("scripts/package_hygiene.py")
        except exit_retirement.Phase5ExitRetirementError as error:
            raise Phase5ExitCandidateV2Error(str(error)) from error
    if not set(EXPECTED_STARTUP_CLOSURE) <= set(digests):
        raise Phase5ExitCandidateV2Error("startup closure is not fully hash-bound")
    for relative in (*EXPECTED_STARTUP_CLOSURE, *APPLICATION_SURFACES):
        lowered = _text(project, relative).casefold()
        if any(symbol in lowered for symbol in FORBIDDEN_EXIT_SYMBOLS):
            raise Phase5ExitCandidateV2Error(
                f"Phase 5 Exit symbol entered live/startup surface: {relative}"
            )
    packaging = {
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
        "bootstraps": sum(
            path.startswith("scripts/bootstrap_onyx")
            for path in EXPECTED_STARTUP_CLOSURE
        ),
        "packaging_entrypoints": len(packaging),
    }


def _load_exact_module(
    project: Path, relative: str, expected_digest: str, name: str
) -> types.ModuleType:
    try:
        payload = exit_retirement.historical_bytes(project, relative, expected_digest)
    except exit_retirement.Phase5ExitRetirementError as error:
        raise Phase5ExitCandidateV2Error(str(error)) from error
    path = _regular_path(project, relative)
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    try:
        exec(compile(payload, str(path), "exec"), module.__dict__)
    except BaseException as exc:
        raise Phase5ExitCandidateV2Error(
            f"exact module could not load: {relative}"
        ) from exc
    return module


def _verify_predecessor(
    project: Path, manifest: dict[str, Any]
) -> tuple[types.ModuleType, dict[str, Any], dict[str, object]]:
    predecessor = manifest.get("predecessor")
    expected_predecessor = {
        "candidate": "phase5-exit-candidate-v1",
        "manifest_path": C1_MANIFEST,
        "manifest_sha256": C1_BINDINGS[C1_MANIFEST],
        "verifier_path": C1_VERIFIER,
        "verifier_sha256": C1_BINDINGS[C1_VERIFIER],
    }
    if predecessor != expected_predecessor:
        raise Phase5ExitCandidateV2Error("Candidate V1 predecessor binding drift")
    c1 = _load_exact_module(
        project,
        C1_VERIFIER,
        C1_BINDINGS[C1_VERIFIER],
        "_onyx_phase5_exit_candidate_v1_frozen",
    )
    try:
        c1_manifest = c1._load_manifest(project)
        c1._verify_claims(c1_manifest)
        c1_files: dict[str, str] = {}
        for entry in c1_manifest["files"]:
            relative = entry["path"]
            digest = entry["sha256"]
            if _sha256(project, relative) != digest:
                _binding_state(project, relative, digest)
            c1_files[relative] = digest
        acceptances = c1._verify_acceptances(project, c1_manifest)
        default_off = c1._verify_default_off(project)
        c1._verify_projection_words(project)
        c1._external_specs(c1_manifest)
    except BaseException as exc:
        raise Phase5ExitCandidateV2Error(
            "Candidate V1 frozen composition did not reproduce"
        ) from exc
    if (
        tuple(acceptances) != EXPECTED_COMPONENT_ACCEPTANCES
        or default_off.get("flags") != 8
    ):
        raise Phase5ExitCandidateV2Error("Candidate V1 component boundary drift")
    return (
        c1,
        c1_manifest,
        {
            "files": len(c1_files),
            "component_acceptances": len(acceptances),
            "flags_default_false": default_off["flags"],
        },
    )


def _v9_evidence_root(rows: list[dict[str, str]]) -> str:
    ordered = sorted(rows, key=lambda row: row["path"])
    material = "".join(f"{row['path']}\0{row['sha256']}\n" for row in ordered).encode(
        "utf-8"
    )
    return hashlib.sha256(material).hexdigest()


def _verify_v9(
    project: Path, manifest: dict[str, Any], digests: dict[str, str]
) -> dict[str, object]:
    expected_v9 = {
        "acceptance_id": V9_ACCEPTANCE_ID,
        "candidate_manifest_path": V9_MANIFEST,
        "candidate_manifest_sha256": V9_MANIFEST_SHA256,
        "acceptance_record_path": V9_ACCEPTANCE_RECORD,
        "acceptance_record_sha256": V9_ACCEPTANCE_RECORD_SHA256,
        "acceptance_metadata_path": V9_ACCEPTANCE_METADATA,
        "acceptance_metadata_sha256": V9_ACCEPTANCE_METADATA_SHA256,
        "acceptance_verifier_path": V9_ACCEPTANCE_VERIFIER,
        "acceptance_verifier_sha256": V9_ACCEPTANCE_VERIFIER_SHA256,
        "acceptance_test_path": V9_ACCEPTANCE_TEST,
        "acceptance_test_sha256": V9_ACCEPTANCE_TEST_SHA256,
        "acceptance_sha_path": V9_ACCEPTANCE_SHA,
        "acceptance_sha256": V9_ACCEPTANCE_SHA256,
        "source_manifest_path": V9_SOURCE_MANIFEST,
        "source_manifest_sha256": V9_SOURCE_MANIFEST_SHA256,
        "artifact_manifest_path": V9_ARTIFACT_MANIFEST,
        "artifact_manifest_sha256": V9_ARTIFACT_MANIFEST_SHA256,
    }
    if manifest.get("v9_acceptance") != expected_v9:
        raise Phase5ExitCandidateV2Error("Activation V9 acceptance binding drift")
    for key, expected in (
        (V9_MANIFEST, V9_MANIFEST_SHA256),
        (V9_ACCEPTANCE_RECORD, V9_ACCEPTANCE_RECORD_SHA256),
        (V9_ACCEPTANCE_METADATA, V9_ACCEPTANCE_METADATA_SHA256),
        (V9_ACCEPTANCE_VERIFIER, V9_ACCEPTANCE_VERIFIER_SHA256),
        (V9_ACCEPTANCE_TEST, V9_ACCEPTANCE_TEST_SHA256),
        (V9_ACCEPTANCE_SHA, V9_ACCEPTANCE_SHA256),
        (V9_SOURCE_MANIFEST, V9_SOURCE_MANIFEST_SHA256),
        (V9_ARTIFACT_MANIFEST, V9_ARTIFACT_MANIFEST_SHA256),
    ):
        if digests.get(key) != expected:
            raise Phase5ExitCandidateV2Error(f"Activation V9 E6 byte drift: {key}")

    candidate = _json(project, V9_MANIFEST)
    rows = candidate.get("files")
    if (
        candidate.get("schema") != "onyx.live-activation.v9"
        or candidate.get("default_off") is not True
        or candidate.get("live_activated") is not False
        or type(rows) is not list
        or len(rows) != 20
    ):
        raise Phase5ExitCandidateV2Error("Activation V9 candidate contract drift")
    seen: set[str] = set()
    normalized: list[dict[str, str]] = []
    for row in rows:
        if type(row) is not dict or set(row) != {"path", "role", "sha256"}:
            raise Phase5ExitCandidateV2Error("Activation V9 binding schema drift")
        relative, digest = row["path"], row["sha256"]
        if (
            type(relative) is not str
            or type(digest) is not str
            or not _HEX64.fullmatch(digest)
            or relative in seen
            or digests.get(relative) != digest
        ):
            raise Phase5ExitCandidateV2Error(
                "Activation V9 binding is absent or drifted"
            )
        if _sha256(project, relative) != digest:
            _binding_state(project, relative, digest)
        seen.add(relative)
        normalized.append({"path": relative, "sha256": digest})

    metadata = _json(project, V9_ACCEPTANCE_METADATA)
    v9_root = _v9_evidence_root(normalized)
    if (
        metadata.get("schema") != "onyx.external-acceptance.v1"
        or metadata.get("acceptance_id") != V9_ACCEPTANCE_ID
        or metadata.get("decision") != "accepted"
        or metadata.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        or metadata.get("candidate_manifest_sha256") != V9_MANIFEST_SHA256
        or metadata.get("binding_count") != 20
        or metadata.get("evidence_root_sha256") != V9_EVIDENCE_ROOT_SHA256
        or v9_root != V9_EVIDENCE_ROOT_SHA256
    ):
        raise Phase5ExitCandidateV2Error("Activation V9 E6 envelope drift")
    record = _text(project, V9_ACCEPTANCE_RECORD)
    if V9_ACCEPTANCE_ID not in record or "ACCEPTED" not in record:
        raise Phase5ExitCandidateV2Error("Activation V9 E6 record drift")
    if _text(project, V9_ACCEPTANCE_SHA).splitlines() != [
        f"{V9_ACCEPTANCE_RECORD_SHA256}  {V9_ACCEPTANCE_RECORD}"
    ]:
        raise Phase5ExitCandidateV2Error("Activation V9 acceptance anchor drift")
    if _text(project, V9_SOURCE_MANIFEST).splitlines() != [
        f"{V9_ACCEPTANCE_VERIFIER_SHA256}  {V9_ACCEPTANCE_VERIFIER}",
        f"{V9_ACCEPTANCE_TEST_SHA256}  {V9_ACCEPTANCE_TEST}",
    ]:
        raise Phase5ExitCandidateV2Error("Activation V9 source anchor drift")
    if _text(project, V9_ARTIFACT_MANIFEST).splitlines() != [
        f"{V9_ACCEPTANCE_RECORD_SHA256}  {V9_ACCEPTANCE_RECORD}",
        f"{V9_ACCEPTANCE_METADATA_SHA256}  {V9_ACCEPTANCE_METADATA}",
    ]:
        raise Phase5ExitCandidateV2Error("Activation V9 artifact anchor drift")
    return {
        "acceptance_id": V9_ACCEPTANCE_ID,
        "bindings": len(normalized),
        "evidence_root_sha256": v9_root,
        "default_off": True,
        "live_activated": False,
    }


def _run_v9_acceptance(project: Path) -> dict[str, object]:
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(_regular_path(project, V9_ACCEPTANCE_VERIFIER)),
            ],
            cwd=project,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=900,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Phase5ExitCandidateV2Error(
            "Activation V9 E6 verifier did not complete"
        ) from exc
    prefix = "ONYX_LIVE_ACTIVATION_V9_ACCEPTANCE_OK "
    lines = completed.stdout.splitlines()
    if (
        completed.returncode != 0
        or completed.stderr
        or len(lines) != 1
        or not lines[0].startswith(prefix)
    ):
        raise Phase5ExitCandidateV2Error(
            "Activation V9 E6 verifier failed or marker drifted"
        )
    try:
        payload = json.loads(lines[0][len(prefix) :])
    except json.JSONDecodeError as exc:
        raise Phase5ExitCandidateV2Error(
            "Activation V9 E6 marker payload is invalid"
        ) from exc
    if (
        type(payload) is not dict
        or payload.get("acceptance_id") != V9_ACCEPTANCE_ID
        or payload.get("decision") != "accepted"
        or payload.get("evidence_root_sha256") != V9_EVIDENCE_ROOT_SHA256
    ):
        raise Phase5ExitCandidateV2Error("Activation V9 E6 marker overclaim/drift")
    return payload


def _verify_checkpoint(project: Path) -> None:
    text = _text(project, CHECKPOINT)
    required = (
        "E1-E5",
        "E6 external acceptance pending",
        "Phase 5 remains incomplete",
        "does **not** declare the Phase 5 exit complete",
        ROOT_ALGORITHM,
        ROOT_DOMAIN[:-1].decode("ascii"),
        "176ca",
        "full historical",
        "default-off",
        "rollback",
    )
    if any(value not in text for value in required):
        raise Phase5ExitCandidateV2Error("Candidate V2 checkpoint boundary drift")


def _verify_cumulative_selection(
    project: Path, manifest: dict[str, Any], digests: dict[str, str]
) -> dict[str, object]:
    declaration = manifest.get("cumulative_selection")
    expected_declaration = {
        "path": CUMULATIVE_SELECTION,
        "expected_passed": 257,
        "expected_failed": 0,
        "historical_direct_passed": 275,
        "historical_direct_failed": 2,
    }
    if declaration != expected_declaration:
        raise Phase5ExitCandidateV2Error("cumulative selection declaration drift")
    selection = _json(project, CUMULATIVE_SELECTION)
    if set(selection) != {
        "schema",
        "created_at",
        "test_paths",
        "pytest_arguments",
        "expected_result",
        "historical_direct_replay",
    }:
        raise Phase5ExitCandidateV2Error("cumulative selection schema drift")
    if (
        selection["schema"] != "onyx.phase5.exit-candidate.v2.cumulative-selection"
        or selection["created_at"] != "2026-07-23"
        or tuple(selection["test_paths"]) != EXPECTED_CUMULATIVE_TESTS
        or tuple(selection["pytest_arguments"]) != EXPECTED_CUMULATIVE_ARGUMENTS
        or selection["expected_result"] != {"passed": 257, "failed": 0}
        or selection["historical_direct_replay"]
        != {
            "passed": 275,
            "failed": 2,
            "failed_test_path": C1_TESTS,
            "reason": "V1-V8 startup discovery rejects the later V9 bootstrap",
        }
    ):
        raise Phase5ExitCandidateV2Error("cumulative selection membership drift")
    for relative in (CUMULATIVE_SELECTION, *EXPECTED_CUMULATIVE_TESTS):
        if relative not in digests:
            raise Phase5ExitCandidateV2Error(
                f"cumulative selection binding is absent: {relative}"
            )
    if C1_TESTS in EXPECTED_CUMULATIVE_TESTS:
        raise Phase5ExitCandidateV2Error("obsolete Candidate V1 suite entered gate")
    command = [
        r".\.venv\Scripts\python.exe",
        "-m",
        "pytest",
        "-q",
        *EXPECTED_CUMULATIVE_TESTS,
        "--disable-warnings",
        "--basetemp",
        ".pytest-p5-exit-v2-compatible",
    ]
    return {
        "test_files": len(EXPECTED_CUMULATIVE_TESTS),
        "expected_passed": 257,
        "expected_failed": 0,
        "command": command,
    }


def verify(project: Path = PROJECT, *, run_external: bool = True) -> dict[str, object]:
    project = Path(project)
    manifest = _load_manifest(project)
    claims = _verify_claims(manifest)
    if (
        tuple(manifest.get("component_acceptances", ()))
        != EXPECTED_COMPONENT_ACCEPTANCES
    ):
        raise Phase5ExitCandidateV2Error("component acceptance set/order drift")
    entries, digests = _verify_files(project, manifest)
    independent_root = _verify_independent_root(manifest, entries)
    startup = _verify_startup_closure(project, manifest, digests)
    cumulative = _verify_cumulative_selection(project, manifest, digests)
    c1, c1_manifest, predecessor = _verify_predecessor(project, manifest)
    v9 = _verify_v9(project, manifest, digests)
    _verify_checkpoint(project)

    component_results: dict[str, str] = {}
    v9_external: dict[str, object] = {}
    if run_external:
        try:
            component_results = c1._run_external(project, c1_manifest)
        except BaseException as exc:
            raise Phase5ExitCandidateV2Error(
                "five preserved component closures failed"
            ) from exc
        if set(component_results) != {
            "runtime-v10",
            "grants-r11",
            "approval-inbox-v15",
            "capability-nexus-v32",
            "integration-v3",
        }:
            raise Phase5ExitCandidateV2Error(
                "five preserved component closures are incomplete"
            )
        v9_external = _run_v9_acceptance(project)

    return {
        "candidate": "phase5-exit-candidate-v2",
        "status": (
            "e1-e5-verified-e6-pending"
            if run_external
            else "focused-only-not-release-pass"
        ),
        "manifest_sha256": _sha256(project, MANIFEST),
        "independent_root_sha256": independent_root,
        "root_algorithm": ROOT_ALGORITHM,
        "binding_count": len(entries),
        "predecessor": predecessor,
        "startup_closure": startup,
        "cumulative_selection": cumulative,
        "v9_acceptance": v9,
        "component_verifiers_executed": len(component_results),
        "v9_acceptance_executed": bool(v9_external),
        "external_e6_accepted": False,
        "phase6_unlocked": False,
        "onyx_complete": False,
        "claims": claims,
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
