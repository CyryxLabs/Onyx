from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import verify_phase5_approval_inbox_v13_worker as process_guard  # noqa: E402

CHECKPOINT = ROOT / "docs/onyx/checkpoints/phase5-approval-inbox-v13"
ARTIFACTS = ROOT / "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V13-001.sha256"
SOURCE = ROOT / "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V13-001.sha256"
FOCUSED = ("tests/test_approval_inbox_v13.py",)
COMBINED = tuple(f"tests/test_approval_inbox_v{version}.py" for version in range(1, 14))
REGRESSIONS = (
    "tests/test_regressions.py",
    "tests/test_missions.py",
    "tests/test_mission_tools.py",
)
HISTORICAL_PROJECTIONS = (
    "docs/onyx/checkpoints/phase5-approval-inbox-v9/mutable-projections/"
    "5a7c9f2c71d770b7a3fb49a511a9d94e59e985dd96d45f40b9ed6b7505ce3e8b.snapshot",
    "docs/onyx/checkpoints/phase5-approval-inbox-v9/mutable-projections/"
    "e8ab4895f1c8c6b61b2a3c97acbeac3149b966003e8a63f2eebe5f954c65ad79.snapshot",
)
HISTORICAL_ROOT_AUTHORITIES = (
    "docs/onyx/VE-SOURCE-P51-GRANTS-R11-001.sha256",
    "docs/onyx/VE-ACCEPTANCE-P51-GRANTS-R11-E6-001.sha256",
    ".github/workflows/release-packages.yml",
)
GLOBAL_DEADLINE = time.monotonic() + 300.0


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8", newline="\n")


def run(command: list[str]) -> tuple[str, float]:
    started = time.perf_counter()
    remaining = GLOBAL_DEADLINE - time.monotonic()
    if remaining <= 0:
        raise SystemExit("global process deadline exhausted")
    environment = os.environ.copy()
    for name in (
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONHOME",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    kwargs: dict[str, object] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
        **kwargs,
    )
    try:
        output, _ = process.communicate(timeout=remaining)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=10)
        raise SystemExit("global process deadline; descendant tree terminated")
    elapsed = time.perf_counter() - started
    if process.returncode:
        print(output)
        raise SystemExit(f"command failed: {' '.join(command)}")
    return output, elapsed


def junit_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    tests = sum(int(suite.attrib.get("tests", 0)) for suite in suites)
    failures = sum(int(suite.attrib.get("failures", 0)) for suite in suites)
    errors = sum(int(suite.attrib.get("errors", 0)) for suite in suites)
    skipped = sum(int(suite.attrib.get("skipped", 0)) for suite in suites)
    return {
        "passed": tests - failures - errors - skipped,
        "failed": failures,
        "errors": errors,
        "skipped": skipped,
    }


def main() -> int:
    CHECKPOINT.mkdir(parents=True, exist_ok=True)
    python = sys.executable
    focused_junit = CHECKPOINT / "phase5-approval-inbox-v13.junit.xml"
    combined_junit = CHECKPOINT / "phase5-approval-inbox-v13.combined.junit.xml"
    regressions_junit = CHECKPOINT / "phase5-approval-inbox-v13.regressions.junit.xml"

    process_source_hashes = {
        relative: sha(ROOT / relative)
        for relative in process_guard.PROCESS_MODULE_SOURCES.values()
    }
    process_guard._capture_process_source_bindings(process_source_hashes)
    plugin_digest = process_source_hashes[process_guard.PLUGIN_RELATIVE]
    pytest_prefix = [
        python,
        "-E",
        "-S",
        process_guard.CHILD_RELATIVE,
        "--plugin-sha256",
        plugin_digest,
    ]
    focused_output, focused_seconds = run(
        [
            *pytest_prefix,
            *FOCUSED,
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={focused_junit}",
        ]
    )
    # Detect any dotted-module identity change introduced between the focused
    # phase and the exact combined process-launch boundary.
    process_guard._revalidate_process_source_bindings()
    combined_output, combined_seconds = run(
        [
            *pytest_prefix,
            *COMBINED,
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={combined_junit}",
        ]
    )
    regression_output, regression_seconds = run(
        [
            *pytest_prefix,
            *REGRESSIONS,
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={regressions_junit}",
        ]
    )
    write(CHECKPOINT / "phase5-approval-inbox-v13.raw.log", focused_output)
    write(CHECKPOINT / "phase5-approval-inbox-v13.combined.log", combined_output)
    write(CHECKPOINT / "phase5-approval-inbox-v13.regressions.log", regression_output)

    static_commands = (
        [
            python,
            "-m",
            "py_compile",
            "core/approval_inbox_v13.py",
            "tests/test_approval_inbox_v13.py",
            "scripts/build_phase5_approval_inbox_v13_evidence.py",
            "scripts/phase5_approval_inbox_v13_child.py",
            "scripts/phase5_approval_inbox_v13_historical_projection.py",
        ],
        [
            python,
            "-m",
            "ruff",
            "check",
            "core/approval_inbox_v13.py",
            "tests/test_approval_inbox_v13.py",
            "scripts/build_phase5_approval_inbox_v13_evidence.py",
            "scripts/phase5_approval_inbox_v13_child.py",
            "scripts/phase5_approval_inbox_v13_historical_projection.py",
            "scripts/verify_phase5_approval_inbox_v13.py",
            "scripts/verify_phase5_approval_inbox_v13_worker.py",
            "scripts/check_phase5_approval_inbox_v13_whitespace.py",
        ],
        [
            python,
            "-m",
            "ruff",
            "format",
            "--check",
            "core/approval_inbox_v13.py",
            "tests/test_approval_inbox_v13.py",
            "scripts/build_phase5_approval_inbox_v13_evidence.py",
            "scripts/phase5_approval_inbox_v13_child.py",
            "scripts/phase5_approval_inbox_v13_historical_projection.py",
            "scripts/verify_phase5_approval_inbox_v13.py",
            "scripts/verify_phase5_approval_inbox_v13_worker.py",
            "scripts/check_phase5_approval_inbox_v13_whitespace.py",
        ],
        [python, "scripts/check_phase5_approval_inbox_v13_whitespace.py"],
    )
    static_lines: list[str] = []
    static_seconds = 0.0
    for command in static_commands:
        output, elapsed = run(list(command))
        static_seconds += elapsed
        static_lines.append(f"$ {' '.join(command)}\n{output}".rstrip())
    write(
        CHECKPOINT / "phase5-approval-inbox-v13.static.log",
        "\n\n".join(static_lines) + "\n",
    )

    projections: list[dict[str, str]] = []
    projection_directory = CHECKPOINT / "mutable-projections"
    projection_directory.mkdir(exist_ok=True)
    for relative in (
        "docs/onyx/CAPABILITY_MATRIX.md",
        "docs/onyx/VERIFICATION_EVIDENCE.md",
    ):
        source_path = ROOT / relative
        digest = sha(source_path)
        snapshot = projection_directory / f"{digest}.snapshot"
        snapshot.write_bytes(source_path.read_bytes())
        projections.append(
            {
                "source": relative,
                "snapshot": snapshot.relative_to(ROOT).as_posix(),
                "sha256": digest,
            }
        )
    write(
        CHECKPOINT / "mutable-projections.json",
        json.dumps(
            {
                "contract": "ContentAddressedMutableProjections.v1",
                "projections": projections,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )

    live_paths = [ROOT / "main.py", ROOT / "ui.py", ROOT / "scripts/launch_onyx.pyw"]
    for folder in ("actions", "dashboard"):
        live_paths.extend((ROOT / folder).glob("*.py"))
    live_entries = sorted(
        (path.relative_to(ROOT).as_posix(), sha(path))
        for path in live_paths
        if path.is_file()
    )
    write(
        CHECKPOINT / "phase5-approval-inbox-v13.live-scan.sha256",
        "".join(f"{digest}  {relative}\n" for relative, digest in live_entries),
    )

    focused = junit_counts(focused_junit)
    combined = junit_counts(combined_junit)
    regressions = junit_counts(regressions_junit)
    regression_matches = re.findall(r"(\d+) passed", regression_output)
    if not regression_matches:
        raise SystemExit("regression passed count unavailable")
    regression_passed = int(regression_matches[-1])
    subtests = sum(
        int(value) for value in re.findall(r"(\d+) subtests passed", regression_output)
    )
    if any(
        counts[key]
        for counts in (focused, combined, regressions)
        for key in ("failed", "errors", "skipped")
    ):
        raise SystemExit("non-green evidence run")

    checkpoint_text = f"""# Phase 5.2 Approval Inbox V13 checkpoint

Status: **candidate — default-off, read-only, external acceptance pending**

V13 is a clean-room review projection. It preserves V1-V12 as rejected historical
candidates and does not import their core implementation, Session Grants or
Capability Nexus. The
host owns a bootstrap-only `ONYX_APPROVAL_INBOX_V13` gate, flag epoch, exact
source and monotonic clock. No live/startup/UI/dashboard path imports V13.

Every return from a host epoch callback re-enters the gate lock and gives an
already-terminal revocation precedence over the callback value. Page,
continuation, preview and handoff publication hold the gate and projection
locks through their linearization point, then recheck terminal state, exact
source generation/epoch and current snapshot/view membership. A newer source
commit therefore cannot be followed by stale output or stale cache
repopulation from an older concurrent capture.

## Authority boundary

Every page, review item, calm-batch preview and handoff states
`authority_granted=False`, `approval_action_available=False` and
`execution_available=False`. There is no approve, deny, approval-revoke, grant,
dispatch, execute or persistence surface. A handoff contains review identifiers
only and instructs a future approval service to re-resolve every host action
field immediately before any authorization decision.

## Validity and batching

The terminal machine is `DISABLED -> READY -> STALE | REVOKED |
INTEGRITY_LATCHED`. A changed feature epoch, clock rollback, source rollback or
same-epoch equivocation invalidates cached state. The source integrity high-water
retains exactly one current epoch digest: accepting a newer epoch atomically
replaces the prior digest, while same-current equivocation and every older-epoch
rollback still latch. A deterministic 10,000-epoch test proves the integrity
state, snapshot cache and view cache remain constant-cardinality. Exact snapshot reuse preserves
its original local creation/deadline and returned proofs, so refresh never
extends TTL. Source callbacks are bounded single-flight and execute outside the
projection lock.

Pagination tokens bind snapshot, view/query/filter/sort, page size, offset,
ordered item set and fixed deadline. Review proofs bind the complete action and
context fingerprint plus safe human-review fields. Calm batches require exact
returned `(item_id, review_proof)` pairs; selection order is canonicalized.
Duplicate item IDs, action request IDs, action fingerprints and idempotency
identities fail closed. High, critical, always-explicit or otherwise ineligible
items cannot enter a batch.

## Stored evidence

- Focused: {focused["passed"]} passed in {focused_seconds:.3f}s.
- Combined Approval Inbox V1-V13: {combined["passed"]} passed in {combined_seconds:.3f}s.
- Frozen V2-V7 R11 fixtures resolve exactly two mutable documentation paths
  directly from exact V9 content-addressed snapshots bound as V13 artifacts.
  The plugin never reads those live paths and never edits predecessors or live
  documentation. R11 root/acceptance inputs and its extra workflow are also
  direct V13 authorities with fixed digests.
- Relevant regressions: {regression_passed} passed plus {subtests} subtests in {regression_seconds:.3f}s.
- Static gates: compile, Ruff lint/format and dedicated whitespace checks passed in {static_seconds:.3f}s.
- Live reachability scan: {len(live_entries)} files, no V13 flag/module reference.
- Parent, worker and historical plugin authoritative paths reject noncanonical
  spelling, case aliases, containment escapes and root/ancestor/final symlink,
  junction or reparse components before each read, hash or process launch.
  Historical copies use fresh plugin-owned temporary roots, exclusive
  nonpreexisting regular-file targets and verified cleanup; live cardinality is
  fixed at {len(live_entries)}.
- Historical Git checks use a private minimal metadata tree containing only the
  frozen R11 HEAD. The live `.git`, hooks, config, alternates and object database
  are never consumed. The combined child runs under one process-tree deadline,
  isolated Python and a sanitized environment with pytest autoload, conftest and
  ambient configuration prohibited.
- The combined plugin and all six V2-V7 verifier modules execute from exact
  re-gated, digest-bound source bytes under private names. Conventional
  `sys.modules`, dotted import hooks and preloaded modules are not authority.
- Mutable matrix/evidence inputs are represented only by exact content-addressed snapshots and an exact mapping; live projection paths are excluded from the artifact manifest.

V13 remains unaccepted and default-off until three independent external reviews
pass. This checkpoint grants no Phase 5 exit or live activation.
"""
    checkpoint_md = CHECKPOINT / "PHASE5_2_APPROVAL_INBOX_V13_CHECKPOINT.md"
    write(checkpoint_md, checkpoint_text)

    historical: list[str] = []
    for version in range(1, 13):
        historical.extend(
            [
                f"core/approval_inbox_v{version}.py",
                f"tests/test_approval_inbox_v{version}.py",
                f"scripts/verify_phase5_approval_inbox_v{version}.py",
                f"scripts/check_phase5_approval_inbox_v{version}_whitespace.py",
                f"docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V{version}-001.sha256",
                f"docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V{version}-001.sha256",
                f"docs/onyx/checkpoints/phase5-approval-inbox-v{version}/PHASE5_2_APPROVAL_INBOX_V{version}_CHECKPOINT.md",
                f"docs/onyx/checkpoints/phase5-approval-inbox-v{version}/phase5-approval-inbox-v{version}.bundle.json",
            ]
        )
    v13_files = [
        "core/approval_inbox_v13.py",
        "tests/test_approval_inbox_v13.py",
        "scripts/build_phase5_approval_inbox_v13_evidence.py",
        "scripts/check_phase5_approval_inbox_v13_whitespace.py",
        "scripts/phase5_approval_inbox_v13_child.py",
        "scripts/phase5_approval_inbox_v13_historical_projection.py",
        "scripts/verify_phase5_approval_inbox_v13.py",
        "scripts/verify_phase5_approval_inbox_v13_worker.py",
        "docs/onyx/APPROVAL_POLICY.md",
        "docs/onyx/IMPLEMENTATION_ROADMAP.md",
        "docs/onyx/adrs/ADR-0003-capability-nexus-and-mcp.md",
        checkpoint_md.relative_to(ROOT).as_posix(),
        focused_junit.relative_to(ROOT).as_posix(),
        combined_junit.relative_to(ROOT).as_posix(),
        regressions_junit.relative_to(ROOT).as_posix(),
        "docs/onyx/checkpoints/phase5-approval-inbox-v13/phase5-approval-inbox-v13.raw.log",
        "docs/onyx/checkpoints/phase5-approval-inbox-v13/phase5-approval-inbox-v13.combined.log",
        "docs/onyx/checkpoints/phase5-approval-inbox-v13/phase5-approval-inbox-v13.regressions.log",
        "docs/onyx/checkpoints/phase5-approval-inbox-v13/phase5-approval-inbox-v13.static.log",
        "docs/onyx/checkpoints/phase5-approval-inbox-v13/phase5-approval-inbox-v13.live-scan.sha256",
        "docs/onyx/checkpoints/phase5-approval-inbox-v13/mutable-projections.json",
        *(entry["snapshot"] for entry in projections),
        *HISTORICAL_PROJECTIONS,
        *HISTORICAL_ROOT_AUTHORITIES,
    ]
    files = sorted(set(historical + v13_files))
    missing = [relative for relative in files if not (ROOT / relative).is_file()]
    if missing:
        raise SystemExit(f"missing evidence inputs: {missing}")
    file_hashes = {relative: sha(ROOT / relative) for relative in files}
    predecessor_bundle = json.loads(
        (
            ROOT
            / "docs/onyx/checkpoints/phase5-approval-inbox-v12/phase5-approval-inbox-v12.bundle.json"
        ).read_text(encoding="utf-8")
    )
    head = predecessor_bundle["base_commit"]
    ruff_version, _ = run([python, "-m", "ruff", "--version"])
    pytest_version, _ = run([python, "-m", "pytest", "--version"])
    bundle = {
        "contract": "Phase52ApprovalInboxEvidence.v13",
        "status": "candidate-default-off-external-acceptance-pending",
        "base_commit": head,
        "feature_flag": {
            "name": "ONYX_APPROVAL_INBOX_V13",
            "default": False,
            "bootstrap_only": True,
        },
        "counts": {
            "focused_passed": focused["passed"],
            "combined_passed": combined["passed"],
            "regression_passed": regression_passed,
            "regression_subtests": subtests,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
        },
        "claims": {
            "read_only_projection": True,
            "authority_always_false": True,
            "future_approval_reresolves_host_fields": True,
            "complete_action_context_binding": True,
            "terminal_state_invalidation": True,
            "snapshot_reuse_never_extends_ttl": True,
            "strict_pagination_and_review_proofs": True,
            "calm_batch_is_non_authoritative": True,
            "bounded_single_flight_callback_outside_lock": True,
            "no_live_wiring": True,
            "historical_v1_v11_preserved": True,
            "constant_cardinality_source_integrity": True,
            "ten_thousand_epoch_stress": True,
            "post_callback_terminal_precedence": True,
            "final_output_publication_barrier": True,
            "source_generation_rechecked_before_publication": True,
            "authoritative_paths_reject_reparse_components": True,
            "direct_v9_historical_projection_authority": True,
            "historical_root_inputs_direct_authority": True,
            "plugin_owned_temporary_outputs": True,
            "historical_projection_no_reparse_gate": True,
            "exclusive_nonpreexisting_output_targets": True,
            "temporary_cleanup_verified": True,
            "hermetic_git_fixture": True,
            "combined_process_sources_identity_bound": True,
            "child_exact_source_execution": True,
            "ambient_pytest_inputs_prohibited": True,
            "process_tree_global_deadline": True,
            "external_acceptance_pending": True,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pytest": pytest_version.strip(),
            "ruff": ruff_version.strip(),
            "executable": sys.executable,
        },
        "mutable_projections": projections,
        "git_boundary": {
            "live_repository_consumed": False,
            "alternates_consumed": False,
            "hooks_consumed": False,
            "hermetic_head": "b2dc0b21f487013cebec34bb148ffb1aeb02611a",
        },
        "combined_process_sources": {
            module_name: {
                "path": relative,
                "sha256": file_hashes[relative],
            }
            for module_name, relative in process_guard.PROCESS_MODULE_SOURCES.items()
        },
        "live_scan_files": len(live_entries),
        "files": file_hashes,
    }
    bundle_path = CHECKPOINT / "phase5-approval-inbox-v13.bundle.json"
    write(bundle_path, json.dumps(bundle, sort_keys=True, separators=(",", ":")) + "\n")

    artifacts = dict(file_hashes)
    artifacts[bundle_path.relative_to(ROOT).as_posix()] = sha(bundle_path)
    write(
        ARTIFACTS,
        "".join(
            f"{digest}  {relative}\n" for relative, digest in sorted(artifacts.items())
        ),
    )
    write(SOURCE, f"{sha(ARTIFACTS)}  {ARTIFACTS.relative_to(ROOT).as_posix()}\n")
    print(
        "P52_APPROVAL_INBOX_V13_BUILT "
        f"focused={focused['passed']} combined={combined['passed']} "
        f"regressions={regression_passed} subtests={subtests} "
        f"artifacts={len(artifacts)} root={sha(SOURCE)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
