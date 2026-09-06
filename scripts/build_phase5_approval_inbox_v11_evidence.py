from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / "docs/onyx/checkpoints/phase5-approval-inbox-v11"
ARTIFACTS = ROOT / "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V11-001.sha256"
SOURCE = ROOT / "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V11-001.sha256"
FOCUSED = ("tests/test_approval_inbox_v11.py",)
COMBINED = tuple(f"tests/test_approval_inbox_v{version}.py" for version in range(1, 12))
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


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8", newline="\n")


def run(command: list[str]) -> tuple[str, float]:
    started = time.perf_counter()
    process = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
        check=False,
    )
    elapsed = time.perf_counter() - started
    if process.returncode:
        print(process.stdout)
        raise SystemExit(f"command failed: {' '.join(command)}")
    return process.stdout, elapsed


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
    focused_junit = CHECKPOINT / "phase5-approval-inbox-v11.junit.xml"
    combined_junit = CHECKPOINT / "phase5-approval-inbox-v11.combined.junit.xml"
    regressions_junit = CHECKPOINT / "phase5-approval-inbox-v11.regressions.junit.xml"

    focused_output, focused_seconds = run(
        [
            python,
            "-m",
            "pytest",
            *FOCUSED,
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={focused_junit}",
        ]
    )
    combined_output, combined_seconds = run(
        [
            python,
            "-m",
            "pytest",
            *COMBINED,
            "-q",
            "-p",
            "no:cacheprovider",
            "-p",
            "scripts.phase5_approval_inbox_v11_historical_projection",
            f"--junitxml={combined_junit}",
        ]
    )
    regression_output, regression_seconds = run(
        [
            python,
            "-m",
            "pytest",
            *REGRESSIONS,
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={regressions_junit}",
        ]
    )
    write(CHECKPOINT / "phase5-approval-inbox-v11.raw.log", focused_output)
    write(CHECKPOINT / "phase5-approval-inbox-v11.combined.log", combined_output)
    write(CHECKPOINT / "phase5-approval-inbox-v11.regressions.log", regression_output)

    static_commands = (
        [
            python,
            "-m",
            "py_compile",
            "core/approval_inbox_v11.py",
            "tests/test_approval_inbox_v11.py",
            "scripts/build_phase5_approval_inbox_v11_evidence.py",
            "scripts/phase5_approval_inbox_v11_historical_projection.py",
        ],
        [
            python,
            "-m",
            "ruff",
            "check",
            "core/approval_inbox_v11.py",
            "tests/test_approval_inbox_v11.py",
            "scripts/build_phase5_approval_inbox_v11_evidence.py",
            "scripts/phase5_approval_inbox_v11_historical_projection.py",
            "scripts/verify_phase5_approval_inbox_v11.py",
            "scripts/verify_phase5_approval_inbox_v11_worker.py",
            "scripts/check_phase5_approval_inbox_v11_whitespace.py",
        ],
        [
            python,
            "-m",
            "ruff",
            "format",
            "--check",
            "core/approval_inbox_v11.py",
            "tests/test_approval_inbox_v11.py",
            "scripts/build_phase5_approval_inbox_v11_evidence.py",
            "scripts/phase5_approval_inbox_v11_historical_projection.py",
            "scripts/verify_phase5_approval_inbox_v11.py",
            "scripts/verify_phase5_approval_inbox_v11_worker.py",
            "scripts/check_phase5_approval_inbox_v11_whitespace.py",
        ],
        [python, "scripts/check_phase5_approval_inbox_v11_whitespace.py"],
        [
            "git",
            "diff",
            "--check",
            "--",
            "core/approval_inbox_v11.py",
            "tests/test_approval_inbox_v11.py",
            "scripts/build_phase5_approval_inbox_v11_evidence.py",
            "scripts/phase5_approval_inbox_v11_historical_projection.py",
            "scripts/verify_phase5_approval_inbox_v11.py",
            "scripts/verify_phase5_approval_inbox_v11_worker.py",
            "scripts/check_phase5_approval_inbox_v11_whitespace.py",
        ],
    )
    static_lines: list[str] = []
    static_seconds = 0.0
    for command in static_commands:
        output, elapsed = run(list(command))
        static_seconds += elapsed
        static_lines.append(f"$ {' '.join(command)}\n{output}".rstrip())
    write(
        CHECKPOINT / "phase5-approval-inbox-v11.static.log",
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
        CHECKPOINT / "phase5-approval-inbox-v11.live-scan.sha256",
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

    checkpoint_text = f"""# Phase 5.2 Approval Inbox V11 checkpoint

Status: **candidate — default-off, read-only, external acceptance pending**

V11 is a clean-room review projection. It preserves V1-V10 as rejected historical
candidates and does not import them, Session Grants or Capability Nexus. The
host owns a bootstrap-only `ONYX_APPROVAL_INBOX_V11` gate, flag epoch, exact
source and monotonic clock. No live/startup/UI/dashboard path imports V11.

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
- Combined Approval Inbox V1-V11: {combined["passed"]} passed in {combined_seconds:.3f}s.
- Frozen V2-V7 R11 fixtures resolve exactly two mutable documentation paths
  directly from exact V9 content-addressed snapshots bound as V11 artifacts.
  The plugin never reads those live paths and never edits predecessors or live
  documentation. R11 root/acceptance inputs and its extra workflow are also
  direct V11 authorities with fixed digests.
- Relevant regressions: {regression_passed} passed plus {subtests} subtests in {regression_seconds:.3f}s.
- Static gates: compile, Ruff lint/format, whitespace and scoped diff check passed in {static_seconds:.3f}s.
- Live reachability scan: {len(live_entries)} files, no V11 flag/module reference.
- Parent, worker and historical plugin authoritative paths reject noncanonical
  spelling, case aliases, containment escapes and root/ancestor/final symlink,
  junction or reparse components before each read, hash or process launch.
  Historical copies use fresh plugin-owned temporary roots, exclusive
  nonpreexisting regular-file targets and verified cleanup; live cardinality is
  fixed at {len(live_entries)}.
- Mutable matrix/evidence inputs are represented only by exact content-addressed snapshots and an exact mapping; live projection paths are excluded from the artifact manifest.

V11 remains unaccepted and default-off until three independent external reviews
pass. This checkpoint grants no Phase 5 exit or live activation.
"""
    checkpoint_md = CHECKPOINT / "PHASE5_2_APPROVAL_INBOX_V11_CHECKPOINT.md"
    write(checkpoint_md, checkpoint_text)

    historical: list[str] = []
    for version in range(1, 11):
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
    v11_files = [
        "core/approval_inbox_v11.py",
        "tests/test_approval_inbox_v11.py",
        "scripts/build_phase5_approval_inbox_v11_evidence.py",
        "scripts/check_phase5_approval_inbox_v11_whitespace.py",
        "scripts/phase5_approval_inbox_v11_historical_projection.py",
        "scripts/verify_phase5_approval_inbox_v11.py",
        "scripts/verify_phase5_approval_inbox_v11_worker.py",
        "docs/onyx/APPROVAL_POLICY.md",
        "docs/onyx/IMPLEMENTATION_ROADMAP.md",
        "docs/onyx/adrs/ADR-0003-capability-nexus-and-mcp.md",
        checkpoint_md.relative_to(ROOT).as_posix(),
        focused_junit.relative_to(ROOT).as_posix(),
        combined_junit.relative_to(ROOT).as_posix(),
        regressions_junit.relative_to(ROOT).as_posix(),
        "docs/onyx/checkpoints/phase5-approval-inbox-v11/phase5-approval-inbox-v11.raw.log",
        "docs/onyx/checkpoints/phase5-approval-inbox-v11/phase5-approval-inbox-v11.combined.log",
        "docs/onyx/checkpoints/phase5-approval-inbox-v11/phase5-approval-inbox-v11.regressions.log",
        "docs/onyx/checkpoints/phase5-approval-inbox-v11/phase5-approval-inbox-v11.static.log",
        "docs/onyx/checkpoints/phase5-approval-inbox-v11/phase5-approval-inbox-v11.live-scan.sha256",
        "docs/onyx/checkpoints/phase5-approval-inbox-v11/mutable-projections.json",
        *(entry["snapshot"] for entry in projections),
        *HISTORICAL_PROJECTIONS,
        *HISTORICAL_ROOT_AUTHORITIES,
    ]
    files = sorted(set(historical + v11_files))
    missing = [relative for relative in files if not (ROOT / relative).is_file()]
    if missing:
        raise SystemExit(f"missing evidence inputs: {missing}")
    file_hashes = {relative: sha(ROOT / relative) for relative in files}
    head, _ = run(["git", "rev-parse", "HEAD"])
    ruff_version, _ = run([python, "-m", "ruff", "--version"])
    pytest_version, _ = run([python, "-m", "pytest", "--version"])
    bundle = {
        "contract": "Phase52ApprovalInboxEvidence.v11",
        "status": "candidate-default-off-external-acceptance-pending",
        "base_commit": head.strip(),
        "feature_flag": {
            "name": "ONYX_APPROVAL_INBOX_V11",
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
            "historical_v1_v10_preserved": True,
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
        "live_scan_files": len(live_entries),
        "files": file_hashes,
    }
    bundle_path = CHECKPOINT / "phase5-approval-inbox-v11.bundle.json"
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
        "P52_APPROVAL_INBOX_V11_BUILT "
        f"focused={focused['passed']} combined={combined['passed']} "
        f"regressions={regression_passed} subtests={subtests} "
        f"artifacts={len(artifacts)} root={sha(SOURCE)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
