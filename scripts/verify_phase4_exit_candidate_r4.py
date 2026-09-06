"""Successor verifier for the default-off Phase 4 E1-E5 R4 candidate.

R4 retains the reviewed R3 authority/default-off mechanics, binds them to the
current comprehensive R11 product scope, and adds the desktop-shortcut
durability regression.  It does not activate any Phase 4 capability or accept
E6.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts import verify_phase4_exit_candidate_r3 as r3  # noqa: E402
from scripts.verify_p44_scope_r11 import verify as verify_r11  # noqa: E402


AUTHORITY_BEARING = r3.AUTHORITY_BEARING
AUTHORITY_LEAVES = r3.AUTHORITY_LEAVES
STARTUP_SOURCES = r3.STARTUP_SOURCES
STARTUP_MODULES = r3.STARTUP_MODULES
FLAG_SPECS = r3.FLAG_SPECS
CONTROL_PLANE_FLAG = r3.CONTROL_PLANE_FLAG
ControlPlaneDisabled = r3.ControlPlaneDisabled
ControlPlaneStore = r3.ControlPlaneStore

display_path = r3.display_path
static_import_closure = r3.static_import_closure
verify_root_token_policy = r3.verify_root_token_policy
verify_static_authority_closure = r3.verify_static_authority_closure
verify_fresh_import_probe = r3.verify_fresh_import_probe
verify_manifest = r3.verify_manifest
verify_default_off = r3.verify_default_off
verify_disabled_v1_zero_write = r3.verify_disabled_v1_zero_write
_manifest_paths = r3._manifest_paths

R11_MANIFEST = PROJECT / "docs/onyx/VE-SCOPE-P44-R11-001.sha256"
R4_SOURCE_MANIFEST = PROJECT / "docs/onyx/VE-SCOPE-P4-E1E5-R4-001.sha256"
R4_EVIDENCE_MANIFEST = PROJECT / "docs/onyx/VE-ARTIFACTS-P4-E1E5-R4-001.sha256"
SELECTION_FILE = PROJECT / "tests/phase4_e1e5_r4_selection.txt"
R4_SOURCE_PATHS = frozenset(
    {
        "docs/onyx/CAPABILITY_MATRIX.md",
        "docs/onyx/VE-ARTIFACTS-P4-E1E5-R4-001.sha256",
        "docs/onyx/VE-SCOPE-P44-R11-001.sha256",
        "docs/onyx/checkpoints/phase4-e1-e5/PHASE4_E1_E5_CHECKPOINT_R4.md",
        "scripts/verify_phase4_exit_candidate_r3.py",
        "scripts/verify_phase4_exit_candidate_r4.py",
        "tests/phase4_e1e5_r4_selection.txt",
        "tests/test_control_plane.py",
        "tests/test_phase4_exit_candidate_r3.py",
        "tests/test_phase4_exit_candidate_r4.py",
        "tests/test_workspace_registry.py",
    }
)
R4_EVIDENCE_PATHS = frozenset(
    {
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-e1-e5-r4.bundle.json",
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-r4-pytest.log",
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-r4-safety.junit.xml",
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-r4-source.json",
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-r4-static.log",
    }
)
RETIRED_R3_NODE = "tests/test_phase4_exit_candidate_r3.py"
R3_SUCCESSOR_NODES = frozenset(
    {
        "tests/test_phase4_exit_candidate_r3.py::test_raw_token_policy_rejects_all_r2_bypass_families",
        "tests/test_phase4_exit_candidate_r3.py::test_external_or_missing_startup_path_fails_closed_without_relative_crash",
        "tests/test_phase4_exit_candidate_r3.py::test_static_transitive_closure_rejects_authority_but_allows_native_vault",
        "tests/test_phase4_exit_candidate_r3.py::test_current_static_closure_and_guarded_fresh_import_are_authority_free",
        "tests/test_phase4_exit_candidate_r3.py::test_selection_sources_are_all_in_r10_union_r3_and_missing_source_denies",
        "tests/test_phase4_exit_candidate_r3.py::test_synthetic_two_manifest_dag_reconstructs_without_self_hash",
        "tests/test_phase4_exit_candidate_r3.py::test_each_evidence_artifact_tamper_fails",
        "tests/test_phase4_exit_candidate_r3.py::test_evidence_manifest_tamper_breaks_source_manifest",
        "tests/test_phase4_exit_candidate_r3.py::test_source_input_tamper_breaks_source_manifest",
        "tests/test_phase4_exit_candidate_r3.py::test_both_manifests_reject_noncanonical_encoding_order_and_format",
        "tests/test_phase4_exit_candidate_r3.py::test_all_flag_readers_on_off_and_environment_restore",
        "tests/test_phase4_exit_candidate_r3.py::test_v1_disable_preserves_bytes_then_reenable_preserves_logical_state",
    }
)


def parse_selection(path: Path = SELECTION_FILE) -> tuple[list[str], set[str]]:
    nodes: list[str] = []
    sources: set[str] = set()
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        source = line.split("::", 1)[0].replace("\\", "/")
        if not source.startswith("tests/") or not source.endswith(".py") or line.startswith("-"):
            raise RuntimeError(f"invalid R4 selection line {number}: {line}")
        if line in nodes:
            raise RuntimeError(f"duplicate R4 selection line: {line}")
        if not (PROJECT / source).is_file():
            raise RuntimeError(f"missing R4 selected source: {source}")
        nodes.append(line)
        sources.add(source)
    if not nodes:
        raise RuntimeError("R4 selection is empty")
    return nodes, sources


def verify_selection_scope(
    *, selection: Path = SELECTION_FILE, r4_paths: frozenset[str] = R4_SOURCE_PATHS
) -> dict[str, int]:
    nodes, sources = parse_selection(selection)
    r11_paths = _manifest_paths(R11_MANIFEST)
    missing = sorted(sources - (r11_paths | set(r4_paths)))
    if missing:
        raise RuntimeError(f"selected test source absent from R11+R4 scope: {missing}")
    r3_nodes, _ = r3.parse_selection()
    retained = set(r3_nodes) - {RETIRED_R3_NODE}
    omitted = sorted(retained - set(nodes))
    if omitted:
        raise RuntimeError(f"R4 selection omitted R3 node: {omitted}")
    if RETIRED_R3_NODE in nodes:
        raise RuntimeError("R4 selection retained obsolete whole-file R3 binding node")
    missing_successors = sorted(R3_SUCCESSOR_NODES - set(nodes))
    if missing_successors:
        raise RuntimeError(f"R4 selection omitted R3 successor node: {missing_successors}")
    return {"nodes": len(nodes), "sources": len(sources)}


def verify_source_only() -> dict[str, object]:
    r11_count, _r11_sha = verify_r11(R11_MANIFEST)
    return {
        "activation": False,
        "e6_accepted": False,
        "flags_default_off": verify_default_off(),
        "fresh_import_probe": verify_fresh_import_probe(),
        "owner_write_probe": verify_disabled_v1_zero_write(),
        "r11_files": r11_count,
        "root_token_sources": verify_root_token_policy(),
        "selection": verify_selection_scope(),
        "static_closure": verify_static_authority_closure(),
        "status": "P4_EXIT_CANDIDATE_R4_SOURCE_OK",
    }


def verify_frozen() -> dict[str, object]:
    source_count, _source_sha = verify_manifest(R4_SOURCE_MANIFEST, R4_SOURCE_PATHS)
    evidence_count, _evidence_sha = verify_manifest(R4_EVIDENCE_MANIFEST, R4_EVIDENCE_PATHS)
    result = verify_source_only()
    result.update(
        {
            "source_manifest_files": source_count,
            "evidence_manifest_files": evidence_count,
            "external_source_anchor": False,
            "status": "P4_EXIT_CANDIDATE_R4_FROZEN_OK",
        }
    )
    return result


def _write_output(path: Path | None, result: dict[str, object]) -> None:
    payload = json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload.encode("utf-8"))
    print(payload, end="")


def run_tests(junitxml: Path, basetemp: Path, raw_log: Path) -> int:
    nodes, _sources = parse_selection()
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        str(basetemp),
        "--junitxml",
        str(junitxml),
        *nodes,
    ]
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=PROJECT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    r3._raw_log(raw_log, command, result, time.perf_counter() - started)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def run_static(raw_log: Path) -> int:
    commands = (
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "scripts/verify_p44_scope_r11.py",
            "scripts/verify_phase4_exit_candidate_r4.py",
            "tests/test_desktop_shortcut.py",
            "tests/test_phase4_exit_candidate_r4.py",
            "--select",
            "F,E9",
        ],
        [
            sys.executable,
            "-m",
            "py_compile",
            "scripts/verify_p44_scope_r11.py",
            "scripts/verify_phase4_exit_candidate_r4.py",
            "tests/test_desktop_shortcut.py",
            "tests/test_phase4_exit_candidate_r4.py",
        ],
        ["git", "diff", "--check"],
    )
    started = time.perf_counter()
    sections: list[str] = []
    exit_code = 0
    for command in commands:
        command_started = time.perf_counter()
        result = subprocess.run(
            command,
            cwd=PROJECT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        sections.append(
            "COMMAND "
            + subprocess.list2cmdline(command)
            + "\n"
            + f"EXIT {result.returncode}\n"
            + f"DURATION_SECONDS {time.perf_counter() - command_started:.6f}\n"
            + "STDOUT\n"
            + result.stdout
            + "STDERR\n"
            + result.stderr
        )
        if result.returncode and not exit_code:
            exit_code = result.returncode
    body = f"EXIT {exit_code}\nDURATION_SECONDS {time.perf_counter() - started:.6f}\n" + "".join(sections)
    raw_log.parent.mkdir(parents=True, exist_ok=True)
    raw_log.write_bytes(body.encode("utf-8"))
    print(body, end="")
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", choices=("source", "frozen", "test", "static"), default="frozen")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--junitxml", type=Path)
    parser.add_argument("--basetemp", type=Path)
    parser.add_argument("--raw-log", type=Path)
    args = parser.parse_args()
    if args.gate == "test":
        if args.junitxml is None or args.basetemp is None or args.raw_log is None:
            parser.error("test requires --junitxml --basetemp --raw-log")
        return run_tests(args.junitxml, args.basetemp, args.raw_log)
    if args.gate == "static":
        if args.raw_log is None:
            parser.error("static requires --raw-log")
        return run_static(args.raw_log)
    result = verify_source_only() if args.gate == "source" else verify_frozen()
    _write_output(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
