"""Freeze and verify Phase 5.2 Approval Inbox V2 candidate evidence."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[1]
TOP_MANIFEST = "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V2-001.sha256"
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V2-001.sha256"
EVIDENCE_DIR = "docs/onyx/checkpoints/phase5-approval-inbox-v2"
CHECKPOINT = f"{EVIDENCE_DIR}/PHASE5_2_APPROVAL_INBOX_V2_CHECKPOINT.md"
BUNDLE = f"{EVIDENCE_DIR}/phase5-approval-inbox-v2.bundle.json"
JUNIT = f"{EVIDENCE_DIR}/phase5-approval-inbox-v2.junit.xml"
RAW_LOG = f"{EVIDENCE_DIR}/phase5-approval-inbox-v2.raw.log"
STATIC_LOG = f"{EVIDENCE_DIR}/phase5-approval-inbox-v2.static.log"
LIVE_SCAN_MANIFEST = f"{EVIDENCE_DIR}/phase5-approval-inbox-v2.live-scan.sha256"

V1_ROOT = "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V1-001.sha256"
V1_ARTIFACT = "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V1-001.sha256"
V1_VERIFIER = "scripts/verify_phase5_approval_inbox_v1.py"
R11_ROOT = "docs/onyx/VE-SOURCE-P51-GRANTS-R11-001.sha256"
R11_ARTIFACT = "docs/onyx/VE-ARTIFACTS-P51-GRANTS-R11-001.sha256"
R11_ACCEPTANCE_MANIFEST = "docs/onyx/VE-ACCEPTANCE-P51-GRANTS-R11-E6-001.sha256"
R11_ACCEPTANCE = "docs/onyx/acceptance/VE-P51-GRANTS-R11-E6-001.md"
R11_VERIFIER = "scripts/verify_phase5_grants_r11.py"
R11_EXTRA_LIVE = (".github/workflows/release-packages.yml",)
V1_SHA256 = {
    V1_ROOT: "c0a2a7d4d0314d2b061b826463ac9bf6828bc27a0e7ef00dd0d47ab55d19ced8",
    V1_ARTIFACT: "d67c15e1644fd1de16d485714509ca11ec01f458a1464f7457378a00f6c82e21",
    V1_VERIFIER: "ed2cb194492943f70722d203e896d52088a772b3b9651b2a6c800daa8f98d029",
    "core/approval_inbox_v1.py": "01435dee3c5f2122afa05245efac73950b78fe50264c372b53ca61dabc9ad560",
    "tests/test_approval_inbox_v1.py": "605be42da065683e5b107372b4cade271e32ec7002526520dda3a7db947efcaf",
}
R11_SHA256 = {
    R11_ROOT: "b4759d8840611e2affbd322831ae8dc88ff84ac09701a24b4a6f56df66463071",
    R11_ARTIFACT: "0253aba6b0fed67bbac6b1eda55ea32a9928f44b036b2fbc0c5daec78e0b33d7",
    R11_ACCEPTANCE_MANIFEST: "36fb198e27ebb7e8e8bb97885d8a823d2a291ed573da3d5513d950715b113bb0",
    R11_ACCEPTANCE: "ff703416675653b4f1611e7f9ee633fac974c3bdf4225a16d84f302233b824d4",
}

SOURCE_SEEDS = (
    "core/approval_inbox_v2.py",
    "scripts/check_phase5_approval_inbox_v2_whitespace.py",
    "scripts/verify_phase5_approval_inbox_v2.py",
    "tests/test_approval_inbox_v2.py",
)
NORMATIVE_SEEDS = (
    "docs/onyx/APPROVAL_POLICY.md",
    "docs/onyx/IMPLEMENTATION_ROADMAP.md",
    "plans/onyx-advanced-entity-redesign.md",
)
LIVE_ROOTS = (
    "main.py",
    "ui.py",
    "actions",
    "core",
    "dashboard",
    "memory",
    "packaging",
    "qml",
    "runtime",
    "scripts",
)
LIVE_SUFFIXES = frozenset(
    {".desktop", ".html", ".iss", ".js", ".json", ".plist", ".py", ".pyw", ".qml", ".spec", ".toml", ".yaml", ".yml"}
)
LIVE_EXCLUDED_PARTS = frozenset(
    {"__pycache__", ".pytest_cache", "evidence", "evidences", "test", "tests"}
)
LIVE_FORBIDDEN_TOKENS = (
    "ONYX_APPROVAL_INBOX_V2",
    "approval_inbox_v2",
    "ApprovalInboxProjection(",
)
_HISTORICAL_GRANT = re.compile(r"session_grants_v[0-9]+\.py\Z", re.I)
_APPROVAL_MODULE = re.compile(r"approval_inbox_v[0-9]+\.py\Z", re.I)
_PHASE_SCRIPT = re.compile(r"(?:verify_phase.*|check_phase.*_whitespace)\.py\Z", re.I)
_MARKDOWN_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_-])([A-Za-z0-9_./-]+\.md)(?=$|[#)`\]\s,:;])",
    re.I,
)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")

EXPECTED_TEST_COUNT = 51
REQUIRED_TESTS = frozenset(
    {
        "test_strict_default_off_has_no_clock_or_source_callback",
        "test_explicit_host_composition_is_pinned_but_not_claimed_as_same_process_secrecy",
        "test_read_apis_accept_no_source_items_or_authority_fields",
        "test_exact_source_output_types_only_no_subclass_or_custom_mapping",
        "test_bounds_are_checked_before_any_item_traversal_or_copy_hook",
        "test_raw_callback_exception_is_not_chained_or_recoverable",
        "test_complete_review_fields_are_immutable_non_authority_and_digest_internal",
        "test_source_timestamps_are_metadata_not_token_validity",
        "test_projection_owned_deadline_expires_without_source_callback_and_never_resurrects",
        "test_monotonic_clock_rollback_latches_and_cannot_resurrect",
        "test_same_source_epoch_content_drift_and_epoch_rollback_fail_closed",
        "test_query_sort_page_size_and_allowed_ids_are_bound_into_view_and_token",
        "test_batch_cannot_select_hidden_workspace_or_filtered_item",
        "test_pagination_is_stable_exact_set_without_duplicate_or_omission",
        "test_source_drift_cannot_mix_pages",
        "test_calm_batch_canonical_reorder_add_remove_substitute_and_non_authority",
        "test_host_cannot_mislabel_high_or_always_explicit_as_batch_eligible",
        "test_batch_forbids_wildcards_categories_duplicates_and_unbounded_sequences",
        "test_outer_token_validation_occurs_before_hmac_and_normalizes_all_malformed_inputs",
        "test_encode_rejects_incomplete_or_noncanonical_payload_before_hmac",
        "test_valid_hmac_with_malformed_payload_normalizes_to_stale",
        "test_tampered_token_and_restart_old_token_fail_before_source_callback",
        "test_source_concurrency_is_capped_at_one_and_excess_fails_closed",
        "test_source_callbacks_never_run_under_projection_lock",
        "test_result_constructors_reject_forged_or_contradictory_inputs",
        "test_limits_and_bounded_snapshot_view_caches",
        "test_no_mutation_grant_import_persistence_or_live_wiring",
        "test_v1_and_r11_frozen_anchor_bytes_remain_exact",
        "test_r11_transitive_tamper_fixture_rejects_v10_before_recursive_execution",
    }
)
REQUIRED_PREFIX_COUNTS = {
    "test_every_recoverable_display_field_rejects_secrets[": 11,
    "test_high_critical_always_explicit_or_ineligible_never_enters_batch[": 4,
    "test_unknown_identity_safety_and_schema_state_fail_closed[": 7,
}


class Phase52V2EvidenceError(RuntimeError):
    pass


def _path(relative: str, root: Path = PROJECT) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise Phase52V2EvidenceError(f"unsafe evidence path: {relative}")
    return root / Path(*pure.parts)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def _write(relative: str, content: bytes) -> None:
    path = _path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def _parse_manifest(
    relative: str,
    expected: tuple[str, ...] | None = None,
    root: Path = PROJECT,
) -> tuple[tuple[str, str], ...]:
    raw = _path(relative, root).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase52V2EvidenceError(f"manifest is noncanonical: {relative}")
    entries: list[tuple[str, str]] = []
    for line in raw.decode("utf-8").splitlines():
        digest, separator, path = line.partition("  ")
        if not separator or not _HEX64.fullmatch(digest):
            raise Phase52V2EvidenceError(f"manifest line is malformed: {relative}")
        _path(path, root)
        entries.append((digest, path))
    paths = tuple(path for _digest, path in entries)
    if not entries or paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
        raise Phase52V2EvidenceError(f"manifest order/set is invalid: {relative}")
    if expected is not None and paths != expected:
        raise Phase52V2EvidenceError(f"manifest exact set drifted: {relative}")
    return tuple(entries)


def _verify_entries(entries: tuple[tuple[str, str], ...], root: Path = PROJECT) -> None:
    for expected, relative in entries:
        path = _path(relative, root)
        if not path.is_file() or _sha(path) != expected:
            raise Phase52V2EvidenceError(f"artifact digest drifted: {relative}")


def _manifest_bytes(paths: tuple[str, ...]) -> bytes:
    return "".join(f"{_sha(_path(relative))}  {relative}\n" for relative in paths).encode()


def _historical_manifest_entries(
    relative: str,
    root: Path = PROJECT,
) -> tuple[tuple[str, str], ...]:
    """Read legacy ordering without weakening V2's own strict manifests."""
    raw = _path(relative, root).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase52V2EvidenceError(f"historical manifest is malformed: {relative}")
    entries: list[tuple[str, str]] = []
    for line in raw.decode("utf-8").splitlines():
        digest, separator, referenced = line.partition("  ")
        if not separator or not _HEX64.fullmatch(digest):
            raise Phase52V2EvidenceError(f"historical manifest line is malformed: {relative}")
        _path(referenced, root)
        entries.append((digest, referenced))
    references = tuple(referenced for _digest, referenced in entries)
    if not references or len(references) != len(set(references)):
        raise Phase52V2EvidenceError(f"historical manifest set is invalid: {relative}")
    return tuple(entries)


def _historical_manifest_references(relative: str) -> tuple[str, ...]:
    return tuple(
        referenced
        for _digest, referenced in _historical_manifest_entries(relative)
    )


def verify_historical_manifest_tree(
    root: Path,
    roots: tuple[str, ...],
) -> tuple[str, ...]:
    """Verify every transitive legacy-manifest edge before recursive execution."""
    queue: list[tuple[str | None, str]] = [(None, relative) for relative in roots]
    visited_manifests: set[str] = set()
    verified: set[str] = set()
    while queue:
        expected, relative = queue.pop(0)
        path = _path(relative, root)
        if not path.is_file():
            raise Phase52V2EvidenceError(f"historical artifact missing: {relative}")
        if expected is not None and _sha(path) != expected:
            raise Phase52V2EvidenceError(f"historical artifact digest drifted: {relative}")
        verified.add(relative)
        if relative.endswith(".sha256") and relative not in visited_manifests:
            visited_manifests.add(relative)
            queue.extend(_historical_manifest_entries(relative, root))
    return tuple(sorted(verified))


def materialize_manifest_tree(
    destination: Path,
    roots: tuple[str, ...],
) -> tuple[str, ...]:
    """Copy only frozen manifest-reachable files; successor files stay absent."""
    destination.mkdir(parents=True, exist_ok=True)
    queue = list(roots)
    copied: set[str] = set()
    while queue:
        relative = queue.pop(0)
        if relative in copied:
            continue
        source = _path(relative)
        if not source.is_file():
            raise Phase52V2EvidenceError(f"frozen materialization source missing: {relative}")
        target = _path(relative, destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied.add(relative)
        if relative.endswith(".sha256"):
            for referenced in _historical_manifest_references(relative):
                if referenced not in copied:
                    queue.append(referenced)
    git_dir = PROJECT / ".git"
    if git_dir.is_dir():
        (destination / ".git").write_text(
            f"gitdir: {git_dir.resolve().as_posix()}\n", encoding="utf-8"
        )
    return tuple(sorted(copied))


def materialize_r11(destination: Path) -> tuple[str, ...]:
    return materialize_manifest_tree(
        destination,
        (R11_ROOT, R11_ACCEPTANCE_MANIFEST, *R11_EXTRA_LIVE),
    )


def materialize_v1(destination: Path) -> tuple[str, ...]:
    return materialize_manifest_tree(destination, (V1_ROOT,))


def execute_frozen_verifier(root: Path, relative: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    scripts = PROJECT / ".venv" / "Scripts"
    environment["PATH"] = str(scripts) + os.pathsep + environment.get("PATH", "")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    bundle_relative = (
        "docs/onyx/checkpoints/phase5-grants-r11/phase5-grants-r11.bundle.json"
        if relative == R11_VERIFIER
        else "docs/onyx/checkpoints/phase5-approval-inbox-v1/phase5-approval-inbox-v1.bundle.json"
    )
    bundle = json.loads(_path(bundle_relative, root).read_text(encoding="utf-8"))
    executable = bundle.get("environment", {}).get("executable")
    if type(executable) is not str or not Path(executable).is_file():
        raise Phase52V2EvidenceError("frozen verifier interpreter is unavailable")
    return subprocess.run(
        [executable, str(_path(relative, root))],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=360,
        env=environment,
    )


def verify_r11_recursively() -> str:
    with tempfile.TemporaryDirectory(
        prefix=".onyx-p52-v2-r11-", dir=PROJECT
    ) as directory:
        root = Path(directory)
        materialize_r11(root)
        verify_historical_manifest_tree(
            root,
            (R11_ROOT, R11_ACCEPTANCE_MANIFEST),
        )
        result = execute_frozen_verifier(root, R11_VERIFIER)
        if result.returncode:
            raise Phase52V2EvidenceError(
                "recursive R11 verifier failed\n" + result.stdout + result.stderr
            )
        return result.stdout.strip()


def verify_v1_recursively() -> str:
    with tempfile.TemporaryDirectory(
        prefix=".onyx-p52-v2-v1-", dir=PROJECT
    ) as directory:
        root = Path(directory)
        materialize_v1(root)
        result = execute_frozen_verifier(root, V1_VERIFIER)
        if result.returncode:
            raise Phase52V2EvidenceError(
                "recursive V1 verifier failed\n" + result.stdout + result.stderr
            )
        return result.stdout.strip()


def _resolve_module(parts: tuple[str, ...]) -> tuple[str, ...]:
    candidates: list[str] = []
    for index in range(1, len(parts)):
        initializer = f"{'/'.join(parts[:index])}/__init__.py"
        if _path(initializer).is_file():
            candidates.append(initializer)
    relative = "/".join(parts)
    for candidate in (f"{relative}/__init__.py", f"{relative}.py"):
        if _path(candidate).is_file():
            candidates.append(candidate)
    return tuple(candidates)


def local_import_closure() -> tuple[str, ...]:
    found = set(SOURCE_SEEDS)
    queue = list(SOURCE_SEEDS)
    while queue:
        relative = queue.pop(0)
        try:
            tree = ast.parse(_path(relative).read_text(encoding="utf-8"), filename=relative)
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise Phase52V2EvidenceError(f"source dependency cannot be parsed: {relative}") from exc
        package = tuple(PurePosixPath(relative).parts[:-1])
        for node in ast.walk(tree):
            targets: list[tuple[str, ...]] = []
            if isinstance(node, ast.Import):
                targets.extend(tuple(alias.name.split(".")) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = tuple((node.module or "").split(".")) if node.module else ()
                if node.level:
                    base = package[: max(0, len(package) - node.level + 1)] + base
                targets.append(base)
                targets.extend(base + tuple(alias.name.split(".")) for alias in node.names if alias.name != "*")
            for target in targets:
                for dependency in _resolve_module(tuple(part for part in target if part)):
                    if dependency not in found:
                        found.add(dependency)
                        queue.append(dependency)
    return tuple(sorted(found))


def _normalize_reference(value: PurePosixPath) -> str | None:
    parts: list[str] = []
    for part in value.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts) or None


def normative_graph() -> dict[str, list[str]]:
    found = set(NORMATIVE_SEEDS)
    queue = list(NORMATIVE_SEEDS)
    graph: dict[str, list[str]] = {}
    while queue:
        relative = queue.pop(0)
        text = _path(relative).read_text(encoding="utf-8")
        references: set[str] = set()
        for raw in _MARKDOWN_REFERENCE.findall(text):
            pure = PurePosixPath(raw.replace("\\", "/"))
            candidates = (
                (pure,) if raw.startswith(("docs/", "plans/")) else (PurePosixPath(relative).parent / pure, pure)
            )
            for candidate in candidates:
                normalized = _normalize_reference(candidate)
                if normalized and normalized.endswith(".md") and _path(normalized).is_file():
                    references.add(normalized)
                    break
        references.discard(relative)
        graph[relative] = sorted(references)
        for reference in graph[relative]:
            if reference not in found:
                found.add(reference)
                queue.append(reference)
    return {key: graph[key] for key in sorted(graph)}


def live_scan_paths() -> tuple[str, ...]:
    found: set[str] = set()
    for relative_root in LIVE_ROOTS:
        path = _path(relative_root)
        candidates = (path,) if path.is_file() else path.rglob("*") if path.is_dir() else ()
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix.casefold() not in LIVE_SUFFIXES:
                continue
            relative = candidate.relative_to(PROJECT).as_posix()
            parts = {part.casefold() for part in PurePosixPath(relative).parts}
            if (
                parts & LIVE_EXCLUDED_PARTS
                or _HISTORICAL_GRANT.fullmatch(candidate.name)
                or _APPROVAL_MODULE.fullmatch(candidate.name)
                or _PHASE_SCRIPT.fullmatch(candidate.name)
            ):
                continue
            found.add(relative)
    paths = tuple(sorted(found))
    if "scripts/launch_onyx.pyw" not in paths:
        raise Phase52V2EvidenceError("operational launcher is absent from live scan")
    return paths


def artifact_paths() -> tuple[str, ...]:
    return tuple(
        sorted(
            set(
                (
                    *local_import_closure(),
                    *normative_graph(),
                    *V1_SHA256,
                    *R11_SHA256,
                    *R11_EXTRA_LIVE,
                    CHECKPOINT,
                    BUNDLE,
                    JUNIT,
                    RAW_LOG,
                    STATIC_LOG,
                    LIVE_SCAN_MANIFEST,
                )
            )
        )
    )


def _junit() -> tuple[dict[str, int], str, set[str]]:
    try:
        document = ET.fromstring(_path(JUNIT).read_bytes())
    except (OSError, ET.ParseError) as exc:
        raise Phase52V2EvidenceError("JUnit is invalid") from exc
    suites = [document] if document.tag == "testsuite" else document.findall("testsuite")
    if len(suites) != 1:
        raise Phase52V2EvidenceError("JUnit must contain exactly one suite")
    suite = suites[0]
    cases = suite.findall("testcase")
    names = {case.attrib.get("name", "") for case in cases}
    errors = sum(case.find("error") is not None for case in cases)
    failed = sum(case.find("failure") is not None for case in cases)
    skipped = sum(case.find("skipped") is not None for case in cases)
    counts = {"errors": errors, "failed": failed, "passed": len(cases) - errors - failed - skipped, "skipped": skipped}
    if len(cases) != EXPECTED_TEST_COUNT or counts != {"errors": 0, "failed": 0, "passed": EXPECTED_TEST_COUNT, "skipped": 0}:
        raise Phase52V2EvidenceError("focused JUnit count/result is invalid")
    if not REQUIRED_TESTS <= names:
        raise Phase52V2EvidenceError("focused JUnit lacks a required test")
    for prefix, expected in REQUIRED_PREFIX_COUNTS.items():
        if sum(name.startswith(prefix) for name in names) != expected:
            raise Phase52V2EvidenceError(f"focused parameter coverage drifted: {prefix}")
    return counts, suite.attrib.get("timestamp", ""), names


def _verify_static() -> None:
    expected = {
        "COMPILE": "0",
        "DIFF_CHECK": "0",
        "R11_RECURSIVE": "0",
        "RUFF_F_E9": "0",
        "V1_RECURSIVE": "0",
        "WHITESPACE": "0",
    }
    raw = _path(STATIC_LOG).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase52V2EvidenceError("static log is noncanonical")
    values: dict[str, str] = {}
    for line in raw.decode().splitlines():
        key, separator, value = line.partition("=")
        if not separator or key in values:
            raise Phase52V2EvidenceError("static log shape is invalid")
        values[key] = value
    if values != expected:
        raise Phase52V2EvidenceError("static gates are not all green")


def _verify_live() -> tuple[str, ...]:
    paths = live_scan_paths()
    entries = _parse_manifest(LIVE_SCAN_MANIFEST, paths)
    _verify_entries(entries)
    for relative in paths:
        text = _path(relative).read_text(encoding="utf-8")
        for token in LIVE_FORBIDDEN_TOKENS:
            if token in text:
                raise Phase52V2EvidenceError(f"V2 is wired into live surface: {relative}")
    return paths


def _verify_anchors() -> None:
    for relative, expected in {**V1_SHA256, **R11_SHA256}.items():
        if _sha(_path(relative)) != expected:
            raise Phase52V2EvidenceError(f"historical/accepted anchor drifted: {relative}")


def _read_bundle() -> dict[str, object]:
    raw = _path(BUNDLE).read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Phase52V2EvidenceError("bundle is invalid JSON") from exc
    if type(value) is not dict or raw != _canonical(value):
        raise Phase52V2EvidenceError("bundle is not canonical")
    return value


def verify(*, recursive: bool = True) -> dict[str, object]:
    _verify_anchors()
    if recursive:
        r11_output = verify_r11_recursively()
        v1_output = verify_v1_recursively()
        if "P51_GRANTS_R11_EVIDENCE_OK" not in r11_output:
            raise Phase52V2EvidenceError("recursive R11 verifier did not report success")
        if "P52_APPROVAL_INBOX_V1_FROZEN_OK" not in v1_output:
            raise Phase52V2EvidenceError("recursive V1 verifier did not report success")
    closure = local_import_closure()
    graph = normative_graph()
    expected_artifacts = artifact_paths()
    _verify_entries(_parse_manifest(TOP_MANIFEST, (ARTIFACT_MANIFEST,)))
    _verify_entries(_parse_manifest(ARTIFACT_MANIFEST, expected_artifacts))
    counts, timestamp, _names = _junit()
    _verify_static()
    live = _verify_live()
    bundle = _read_bundle()
    claims = {
        "bounds_before_traversal_no_arbitrary_copy_hooks": True,
        "callback_exception_secret_context_removed": True,
        "computed_result_digests_and_relational_invariants": True,
        "default_off_no_clock_or_source_callback": True,
        "exact_host_output_types_and_pinned_composition": True,
        "historical_v1_byte_exact_rejected": True,
        "local_monotonic_deadline_nonresurrection": True,
        "no_live_wiring_mutation_or_authority": True,
        "recursive_r11_v1_through_v10_verification": True,
        "secret_free_complete_review_fields": True,
        "single_source_callback_concurrency_cap": True,
        "source_callbacks_outside_projection_lock": True,
        "strict_token_parse_and_malformed_normalization": True,
        "view_bound_query_sort_page_size_and_item_set": True,
        "view_scoped_exact_calm_batch_only": True,
    }
    files = {
        relative: _sha(_path(relative))
        for relative in expected_artifacts
        if relative != BUNDLE
    }
    expected_dag = {
        "artifact_points_to": list(expected_artifacts),
        "bundle_excludes_manifest_and_self_hashes": True,
        "root": TOP_MANIFEST,
        "root_points_to": [ARTIFACT_MANIFEST],
    }
    if bundle.get("contract") != "Phase52ApprovalInboxEvidence.v2" or bundle.get("status") != "candidate-default-off-not-accepted":
        raise Phase52V2EvidenceError("bundle contract/status is invalid")
    if bundle.get("counts") != counts or bundle.get("junit_timestamp") != timestamp:
        raise Phase52V2EvidenceError("bundle test evidence drifted")
    if bundle.get("claims") != claims or bundle.get("files") != files:
        raise Phase52V2EvidenceError("bundle claims/files drifted")
    if bundle.get("dependency_closure") != list(closure) or bundle.get("normative_graph") != graph:
        raise Phase52V2EvidenceError("bundle dependency/normative closure drifted")
    if bundle.get("live_scan_paths") != list(live) or bundle.get("dag") != expected_dag:
        raise Phase52V2EvidenceError("bundle live/DAG closure drifted")
    if bundle.get("history") != {
        "phase51_r11": {"decision": "accepted-default-off", "anchors": R11_SHA256},
        "phase52_v1": {"decision": "historical-rejected", "anchors": V1_SHA256},
    }:
        raise Phase52V2EvidenceError("bundle history claim drifted")
    if bundle.get("external_e6") != {"accepted": False, "required_before_acceptance": True, "status": "pending-external-review"}:
        raise Phase52V2EvidenceError("bundle external acceptance status is invalid")
    if bundle.get("feature_flag") != {"default": False, "name": "ONYX_APPROVAL_INBOX_V2"}:
        raise Phase52V2EvidenceError("bundle feature flag claim is invalid")
    print(
        "P52_APPROVAL_INBOX_V2_FROZEN_OK "
        f"tests={counts['passed']} artifacts={len(expected_artifacts)} "
        f"dependencies={len(closure)} normative={len(graph)} live={len(live)} "
        "r11_recursive=ok v1_recursive=ok"
    )
    return bundle


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PROJECT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
    )


def freeze() -> None:
    _verify_anchors()
    _path(EVIDENCE_DIR).mkdir(parents=True, exist_ok=True)
    focused = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            "tests/test_approval_inbox_v2.py",
            f"--junitxml={JUNIT}",
        ]
    )
    raw = (focused.stdout + focused.stderr).replace("\r\n", "\n").replace("\r", "\n")
    _write(RAW_LOG, raw.encode())
    if focused.returncode:
        raise Phase52V2EvidenceError("focused tests failed during freeze")
    commands = {
        "RUFF_F_E9": [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "F,E9",
            *SOURCE_SEEDS,
        ],
        "COMPILE": [sys.executable, "-m", "py_compile", *SOURCE_SEEDS],
        "WHITESPACE": [sys.executable, "scripts/check_phase5_approval_inbox_v2_whitespace.py"],
        "DIFF_CHECK": ["git", "diff", "--check", "--", *SOURCE_SEEDS],
    }
    gates: dict[str, int] = {}
    detail = ""
    for name, command in commands.items():
        result = _run(command)
        gates[name] = result.returncode
        detail += result.stdout + result.stderr
    try:
        verify_r11_recursively()
        gates["R11_RECURSIVE"] = 0
    except Phase52V2EvidenceError as exc:
        gates["R11_RECURSIVE"] = 1
        detail += str(exc)
    try:
        verify_v1_recursively()
        gates["V1_RECURSIVE"] = 0
    except Phase52V2EvidenceError as exc:
        gates["V1_RECURSIVE"] = 1
        detail += str(exc)
    if any(gates.values()):
        raise Phase52V2EvidenceError(f"static gate failed: {gates}\n{detail}")
    _write(STATIC_LOG, "".join(f"{key}={gates[key]}\n" for key in sorted(gates)).encode())

    live = live_scan_paths()
    for relative in live:
        text = _path(relative).read_text(encoding="utf-8")
        for token in LIVE_FORBIDDEN_TOKENS:
            if token in text:
                raise Phase52V2EvidenceError(f"V2 is wired into live surface: {relative}")
    _write(LIVE_SCAN_MANIFEST, _manifest_bytes(live))
    counts, timestamp, _names = _junit()
    closure = local_import_closure()
    graph = normative_graph()
    paths = artifact_paths()
    claims = {
        "bounds_before_traversal_no_arbitrary_copy_hooks": True,
        "callback_exception_secret_context_removed": True,
        "computed_result_digests_and_relational_invariants": True,
        "default_off_no_clock_or_source_callback": True,
        "exact_host_output_types_and_pinned_composition": True,
        "historical_v1_byte_exact_rejected": True,
        "local_monotonic_deadline_nonresurrection": True,
        "no_live_wiring_mutation_or_authority": True,
        "recursive_r11_v1_through_v10_verification": True,
        "secret_free_complete_review_fields": True,
        "single_source_callback_concurrency_cap": True,
        "source_callbacks_outside_projection_lock": True,
        "strict_token_parse_and_malformed_normalization": True,
        "view_bound_query_sort_page_size_and_item_set": True,
        "view_scoped_exact_calm_batch_only": True,
    }
    files = {relative: _sha(_path(relative)) for relative in paths if relative != BUNDLE}
    bundle = {
        "base_commit": _run(["git", "rev-parse", "HEAD"]).stdout.strip(),
        "claims": claims,
        "contract": "Phase52ApprovalInboxEvidence.v2",
        "counts": counts,
        "dag": {
            "artifact_points_to": list(paths),
            "bundle_excludes_manifest_and_self_hashes": True,
            "root": TOP_MANIFEST,
            "root_points_to": [ARTIFACT_MANIFEST],
        },
        "dependency_closure": list(closure),
        "environment": {
            "executable": sys.executable,
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "external_e6": {
            "accepted": False,
            "required_before_acceptance": True,
            "status": "pending-external-review",
        },
        "feature_flag": {"default": False, "name": "ONYX_APPROVAL_INBOX_V2"},
        "files": files,
        "history": {
            "phase51_r11": {"decision": "accepted-default-off", "anchors": R11_SHA256},
            "phase52_v1": {"decision": "historical-rejected", "anchors": V1_SHA256},
        },
        "junit_timestamp": timestamp,
        "limits": {
            "max_batch_items": 32,
            "max_items": 128,
            "max_page_size": 50,
            "max_snapshots": 8,
            "max_snapshot_age_ms": 300_000,
            "max_source_callbacks": 1,
            "max_summary": 1_024,
            "max_text": 512,
            "max_token": 2_048,
            "max_views": 16,
        },
        "live_scan_paths": list(live),
        "normative_graph": graph,
        "status": "candidate-default-off-not-accepted",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _write(BUNDLE, _canonical(bundle))
    paths = artifact_paths()
    _write(ARTIFACT_MANIFEST, _manifest_bytes(paths))
    _write(TOP_MANIFEST, _manifest_bytes((ARTIFACT_MANIFEST,)))
    verify(recursive=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.freeze:
        freeze()
    else:
        verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
