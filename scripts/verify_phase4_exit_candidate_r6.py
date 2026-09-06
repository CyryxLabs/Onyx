"""Fresh verifier and evidence producer for Phase 4 E1-E5 candidate R6."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts import verify_phase4_exit_candidate_r4 as behavior  # noqa: E402
from scripts import verify_p44_scope_r12 as r12  # noqa: E402


R12_MANIFEST = PROJECT / "docs/onyx/VE-SCOPE-P44-R12-001.sha256"
R6_SOURCE_MANIFEST = PROJECT / "docs/onyx/VE-SCOPE-P4-E1E5-R6-001.sha256"
R6_ARTIFACT_MANIFEST = PROJECT / "docs/onyx/VE-ARTIFACTS-P4-E1E5-R6-001.sha256"
SELECTION_FILE = PROJECT / "tests/phase4_e1e5_r6_selection.txt"
R6_SELF_TEST = "tests/test_phase4_exit_candidate_r6.py"
R6_SOURCE_PATHS = frozenset(
    {
        "docs/onyx/VE-ARTIFACTS-P4-E1E5-R6-001.sha256",
        "docs/onyx/VE-SCOPE-P44-R12-001.sha256",
        "docs/onyx/checkpoints/phase4-e1-e5/PHASE4_E1_E5_CHECKPOINT_R6.md",
        "scripts/verify_phase4_exit_candidate_r3.py",
        "scripts/verify_phase4_exit_candidate_r4.py",
        "scripts/verify_phase4_exit_candidate_r6.py",
        "tests/phase4_e1e5_r6_selection.txt",
        "tests/test_control_plane.py",
        "tests/test_phase4_exit_candidate_r3.py",
        "tests/test_phase4_exit_candidate_r4.py",
        "tests/test_phase4_exit_candidate_r6.py",
        "tests/test_workspace_registry.py",
    }
)
R6_ARTIFACT_PATHS = frozenset(
    {
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-e1-e5-r6.bundle.json",
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-r6-pytest.log",
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-r6-safety.junit.xml",
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-r6-source.json",
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-r6-static.log",
    }
)
_LINE = re.compile(r"([0-9a-f]{64}) \*([^\r\n]+)")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_records(manifest: Path) -> dict[str, str]:
    raw = manifest.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise RuntimeError("manifest encoding/newlines are not canonical")
    records: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        match = _LINE.fullmatch(line)
        if match is None or match.group(2) in records:
            raise RuntimeError("manifest line is malformed or duplicated")
        records[match.group(2)] = match.group(1)
    if list(records) != sorted(records):
        raise RuntimeError("manifest paths are not ordinally sorted")
    return records


def verify_manifest_at(root: Path, manifest: Path, paths: frozenset[str]) -> tuple[int, str]:
    records = manifest_records(manifest)
    if set(records) != set(paths):
        raise RuntimeError(
            f"manifest path mismatch: missing={sorted(set(paths)-set(records))}, "
            f"extra={sorted(set(records)-set(paths))}"
        )
    for relative, expected in records.items():
        path = root / relative
        if not path.is_file() or sha256(path) != expected:
            raise RuntimeError(f"manifest digest mismatch: {relative}")
    return len(records), sha256(manifest)


def verify_two_level_dag(
    *, root: Path, source_manifest: Path, source_paths: frozenset[str],
    artifact_manifest: Path, artifact_paths: frozenset[str],
    external_source_sha256: str | None = None,
) -> dict[str, object]:
    actual = sha256(source_manifest)
    if external_source_sha256 is not None and external_source_sha256 != actual:
        raise RuntimeError("external source-manifest anchor mismatch")
    source_count, _ = verify_manifest_at(root, source_manifest, source_paths)
    artifact_count, _ = verify_manifest_at(root, artifact_manifest, artifact_paths)
    return {
        "source_manifest_files": source_count,
        "artifact_manifest_files": artifact_count,
        "source_manifest_sha256": actual,
        "external_source_anchor_verified": external_source_sha256 is not None,
    }


def parse_selection(path: Path = SELECTION_FILE) -> tuple[list[str], set[str]]:
    nodes: list[str] = []
    sources: set[str] = set()
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        node = raw.strip()
        if not node or node.startswith("#"):
            continue
        source = node.split("::", 1)[0].replace("\\", "/")
        if not source.startswith("tests/") or not source.endswith(".py") or node in nodes:
            raise RuntimeError(f"invalid or duplicate R6 selection line {number}: {node}")
        if not (PROJECT / source).is_file():
            raise RuntimeError(f"missing selected source: {source}")
        nodes.append(node)
        sources.add(source)
    return nodes, sources


def verify_selection_scope() -> dict[str, object]:
    nodes, sources = parse_selection()
    if len(nodes) != 34 or len(sources) != 10:
        raise RuntimeError(f"unexpected R6 selection cardinality: {len(nodes)}/{len(sources)}")
    obsolete = {
        "tests/test_phase4_exit_candidate_r4.py",
        "tests/test_phase4_exit_candidate_r4.py::test_r11_manifest_is_current_and_exact",
        "tests/test_phase4_exit_candidate_r4.py::test_r4_source_only_is_current_nonactivating_and_owner_safe",
    }
    if obsolete & set(nodes):
        raise RuntimeError("R6 selection retained obsolete R11-bound node")
    r12_paths = r12.manifest_records(R12_MANIFEST) if hasattr(r12, "manifest_records") else None
    if r12_paths is None:
        r12_paths = set(r12.expected_scope())
    missing = sorted(sources - (set(r12_paths) | set(R6_SOURCE_PATHS)))
    if missing:
        raise RuntimeError(f"selected source absent from R12+R6: {missing}")
    return {"nodes": len(nodes), "sources": len(sources), "obsolete_bindings": 0}


def verify_source_only() -> dict[str, object]:
    r12_count, r12_sha = r12.verify(R12_MANIFEST)
    return {
        "activation": False,
        "e6_accepted": False,
        "flags_default_off": behavior.verify_default_off(),
        "fresh_import_probe": behavior.verify_fresh_import_probe(),
        "owner_write_probe": behavior.verify_disabled_v1_zero_write(),
        "r12_files": r12_count,
        "r12_manifest_sha256": r12_sha,
        "root_token_sources": behavior.verify_root_token_policy(),
        "selection": verify_selection_scope(),
        "static_closure": behavior.verify_static_authority_closure(),
        "status": "P4_EXIT_CANDIDATE_R6_SOURCE_OK",
    }


def verify_frozen() -> dict[str, object]:
    result = verify_source_only()
    result["dag"] = verify_two_level_dag(
        root=PROJECT,
        source_manifest=R6_SOURCE_MANIFEST,
        source_paths=R6_SOURCE_PATHS,
        artifact_manifest=R6_ARTIFACT_MANIFEST,
        artifact_paths=R6_ARTIFACT_PATHS,
    )
    bundle = json.loads(
        (PROJECT / "docs/onyx/checkpoints/phase4-e1-e5/phase4-e1-e5-r6.bundle.json").read_text(encoding="utf-8")
    )
    if bundle["activation"] or bundle["e6_accepted"] or bundle["phase5_unlocked"]:
        raise RuntimeError("R6 bundle cannot activate or accept itself")
    dag = bundle["manifest_dag"]
    if dag["external_source_anchor_present"] or dag["external_registration_must_store"] != "source_manifest_sha256":
        raise RuntimeError("R6 bundle external-anchor contract invalid")
    result.update({"external_source_anchor_present": False, "phase5_unlocked": False})
    result["status"] = "P4_EXIT_CANDIDATE_R6_FROZEN_OK"
    return result


def _raw_log(path: Path, command: list[str], result: subprocess.CompletedProcess[str], seconds: float) -> None:
    body = (
        "COMMAND " + subprocess.list2cmdline(command) + "\n"
        + f"EXIT {result.returncode}\nDURATION_SECONDS {seconds:.6f}\nSTDOUT\n"
        + result.stdout + ("\n" if result.stdout and not result.stdout.endswith("\n") else "")
        + "STDERR\n" + result.stderr
        + ("\n" if result.stderr and not result.stderr.endswith("\n") else "")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


def run_tests(junitxml: Path, basetemp: Path, raw_log: Path) -> int:
    nodes, _ = parse_selection()
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "--basetemp", str(basetemp), "--junitxml", str(junitxml), *nodes, R6_SELF_TEST]
    started = time.perf_counter()
    result = subprocess.run(command, cwd=PROJECT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
    _raw_log(raw_log, command, result, time.perf_counter() - started)
    print(result.stdout, end=""); print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def run_static(raw_log: Path) -> int:
    commands = (
        [sys.executable, "-m", "ruff", "check", "ui.py", "scripts/verify_p44_scope_r12.py", "scripts/verify_phase4_exit_candidate_r6.py", "tests/test_desktop_shortcut.py", R6_SELF_TEST, "--select", "F,E9"],
        [sys.executable, "-m", "py_compile", "ui.py", "scripts/verify_p44_scope_r12.py", "scripts/verify_phase4_exit_candidate_r6.py", "tests/test_desktop_shortcut.py", R6_SELF_TEST],
        ["git", "diff", "--check"],
    )
    started = time.perf_counter(); sections: list[str] = []; code = 0
    for command in commands:
        tick = time.perf_counter()
        result = subprocess.run(command, cwd=PROJECT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False)
        sections.append("COMMAND " + subprocess.list2cmdline(command) + "\n" + f"EXIT {result.returncode}\nDURATION_SECONDS {time.perf_counter()-tick:.6f}\nSTDOUT\n" + result.stdout + "STDERR\n" + result.stderr)
        if result.returncode and not code: code = result.returncode
    body = f"EXIT {code}\nDURATION_SECONDS {time.perf_counter()-started:.6f}\n" + "".join(sections)
    raw_log.parent.mkdir(parents=True, exist_ok=True); raw_log.write_text(body, encoding="utf-8", newline="\n")
    print(body, end=""); return code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", choices=("source", "frozen", "test", "static"), default="frozen")
    parser.add_argument("--output", type=Path); parser.add_argument("--junitxml", type=Path)
    parser.add_argument("--basetemp", type=Path); parser.add_argument("--raw-log", type=Path)
    args = parser.parse_args()
    if args.gate == "test":
        if not all((args.junitxml, args.basetemp, args.raw_log)): parser.error("test requires output paths")
        return run_tests(args.junitxml, args.basetemp, args.raw_log)
    if args.gate == "static":
        if args.raw_log is None: parser.error("static requires --raw-log")
        return run_static(args.raw_log)
    result = verify_source_only() if args.gate == "source" else verify_frozen()
    payload = json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
    if args.output: args.output.write_text(payload, encoding="utf-8", newline="\n")
    print(payload, end=""); return 0


if __name__ == "__main__":
    raise SystemExit(main())
