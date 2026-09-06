"""Freeze and verify Phase 5.2 approval-inbox v1 candidate evidence."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[1]
TOP_MANIFEST = "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V1-001.sha256"
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V1-001.sha256"
EVIDENCE_DIR = "docs/onyx/checkpoints/phase5-approval-inbox-v1"
CHECKPOINT = f"{EVIDENCE_DIR}/PHASE5_2_APPROVAL_INBOX_V1_CHECKPOINT.md"
BUNDLE = f"{EVIDENCE_DIR}/phase5-approval-inbox-v1.bundle.json"
JUNIT = f"{EVIDENCE_DIR}/phase5-approval-inbox-v1.junit.xml"
RAW_LOG = f"{EVIDENCE_DIR}/phase5-approval-inbox-v1.raw.log"
STATIC_LOG = f"{EVIDENCE_DIR}/phase5-approval-inbox-v1.static.log"
LIVE_SCAN_MANIFEST = f"{EVIDENCE_DIR}/phase5-approval-inbox-v1.live-scan.sha256"

R11_ROOT = "docs/onyx/VE-SOURCE-P51-GRANTS-R11-001.sha256"
R11_ARTIFACT = "docs/onyx/VE-ARTIFACTS-P51-GRANTS-R11-001.sha256"
R11_ACCEPTANCE_MANIFEST = "docs/onyx/VE-ACCEPTANCE-P51-GRANTS-R11-E6-001.sha256"
R11_ACCEPTANCE = "docs/onyx/acceptance/VE-P51-GRANTS-R11-E6-001.md"
R11_SHA256 = {
    R11_ROOT: "b4759d8840611e2affbd322831ae8dc88ff84ac09701a24b4a6f56df66463071",
    R11_ARTIFACT: "0253aba6b0fed67bbac6b1eda55ea32a9928f44b036b2fbc0c5daec78e0b33d7",
    R11_ACCEPTANCE_MANIFEST: "36fb198e27ebb7e8e8bb97885d8a823d2a291ed573da3d5513d950715b113bb0",
    R11_ACCEPTANCE: "ff703416675653b4f1611e7f9ee633fac974c3bdf4225a16d84f302233b824d4",
}

SOURCE_SEEDS = (
    "core/approval_inbox_v1.py",
    "scripts/check_phase5_approval_inbox_v1_whitespace.py",
    "scripts/verify_phase5_approval_inbox_v1.py",
    "tests/test_approval_inbox_v1.py",
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
    "ONYX_APPROVAL_INBOX_V1",
    "approval_inbox_v1",
    "ApprovalInbox(",
)
_HISTORICAL_GRANT = re.compile(r"session_grants_v[0-9]+\.py\Z", re.I)
_PHASE_SCRIPT = re.compile(r"(?:verify_phase.*|check_phase.*_whitespace)\.py\Z", re.I)
_MARKDOWN_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_-])([A-Za-z0-9_./-]+\.md)(?=$|[#)`\]\s,:;])",
    re.I,
)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")

EXPECTED_TEST_COUNT = 48
REQUIRED_TEST_NAMES = frozenset(
    {
        "test_flag_is_strict_and_disabled_mode_never_calls_source",
        "test_trusted_source_and_items_cannot_be_caller_constructed",
        "test_model_style_authority_fields_and_raw_payload_are_rejected",
        "test_workspace_pattern_exactly_matches_authoritative_registry_shape",
        "test_page_exposes_every_required_safe_review_field_and_no_raw_fields",
        "test_snapshot_digest_is_deterministic_and_input_order_independent",
        "test_stable_sorting_and_exact_filters",
        "test_pagination_is_exact_set_without_duplicates_or_omissions",
        "test_tampered_cursor_and_stale_cursor_fail_before_source_callback",
        "test_source_drift_invalidates_cursor_without_mixing_pages",
        "test_same_epoch_content_or_time_drift_is_rejected",
        "test_expiry_and_epoch_rollback_fail_closed",
        "test_unknown_schema_fields_types_and_duplicate_authority_records_fail_closed",
        "test_source_principal_or_session_drift_fails_closed",
        "test_calm_batch_is_canonical_read_only_and_reorder_invariant",
        "test_batch_add_remove_and_substitute_change_manifest_digest",
        "test_host_cannot_mark_high_or_always_explicit_item_batch_eligible",
        "test_batch_requires_finite_exact_ids_and_forbids_wildcards_categories",
        "test_batch_selection_is_bound_to_item_digest_idempotency_and_snapshot",
        "test_batch_token_rejects_source_drift_and_disabled_mode_calls_no_source",
        "test_all_host_callbacks_run_outside_internal_lock",
        "test_concurrent_continuations_never_mix_drifted_source_pages",
        "test_collection_page_batch_snapshot_and_string_limits",
        "test_no_mutation_authority_or_grant_import_surface",
        "test_no_startup_dashboard_provider_or_runtime_wiring",
        "test_restart_is_empty_and_old_tokens_cannot_be_restored",
        "test_r11_accepted_anchor_and_frozen_roots_remain_exact",
    }
)
REQUIRED_PREFIX_COUNTS = {
    "test_secret_like_material_is_rejected_from_every_recoverable_display_field[": 11,
    "test_secret_like_or_pathish_identifiers_are_rejected[": 3,
    "test_unhealthy_host_state_fails_closed[": 3,
    "test_high_always_explicit_and_ineligible_items_cannot_enter_batch[": 4,
}


class Phase52EvidenceError(RuntimeError):
    pass


def _path(relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise Phase52EvidenceError(f"unsafe evidence path: {relative}")
    return PROJECT / Path(*pure.parts)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _write(relative: str, content: bytes) -> None:
    path = _path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def _manifest_bytes(paths: tuple[str, ...]) -> bytes:
    return "".join(f"{_sha(_path(relative))}  {relative}\n" for relative in paths).encode()


def _parse_manifest(relative: str, expected: tuple[str, ...] | None = None) -> tuple[tuple[str, str], ...]:
    raw = _path(relative).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase52EvidenceError(f"manifest is noncanonical: {relative}")
    entries: list[tuple[str, str]] = []
    for line in raw.decode("utf-8").splitlines():
        if "  " not in line:
            raise Phase52EvidenceError(f"manifest line is malformed: {relative}")
        digest, path = line.split("  ", 1)
        if not _HEX64.fullmatch(digest):
            raise Phase52EvidenceError(f"manifest digest is malformed: {relative}")
        _path(path)
        entries.append((digest, path))
    paths = tuple(path for _digest, path in entries)
    if not entries or paths != tuple(sorted(paths)) or len(set(paths)) != len(paths):
        raise Phase52EvidenceError(f"manifest set/order is invalid: {relative}")
    if expected is not None and paths != expected:
        raise Phase52EvidenceError(f"manifest exact set drifted: {relative}")
    return tuple(entries)


def _verify_entries(entries: tuple[tuple[str, str], ...]) -> None:
    for expected, relative in entries:
        path = _path(relative)
        if not path.is_file() or _sha(path) != expected:
            raise Phase52EvidenceError(f"artifact digest drifted: {relative}")


def _resolve_module(parts: tuple[str, ...]) -> tuple[str, ...]:
    relative = "/".join(parts)
    candidates: list[str] = []
    for index in range(1, len(parts)):
        initializer = f"{'/'.join(parts[:index])}/__init__.py"
        if _path(initializer).is_file():
            candidates.append(initializer)
    package = f"{relative}/__init__.py"
    module = f"{relative}.py"
    if _path(package).is_file():
        candidates.append(package)
    if _path(module).is_file():
        candidates.append(module)
    return tuple(candidates)


def local_import_closure() -> tuple[str, ...]:
    discovered = set(SOURCE_SEEDS)
    queue = list(SOURCE_SEEDS)
    while queue:
        relative = queue.pop(0)
        path = _path(relative)
        if not path.is_file():
            raise Phase52EvidenceError(f"source dependency is missing: {relative}")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (SyntaxError, UnicodeError) as exc:
            raise Phase52EvidenceError(f"source dependency cannot be parsed: {relative}") from exc
        current_package = tuple(PurePosixPath(relative).parts[:-1])
        for node in ast.walk(tree):
            targets: list[tuple[str, ...]] = []
            if isinstance(node, ast.Import):
                targets.extend(tuple(alias.name.split(".")) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = tuple((node.module or "").split(".")) if node.module else ()
                if node.level:
                    parent = current_package[: max(0, len(current_package) - node.level + 1)]
                    base = parent + base
                targets.append(base)
                targets.extend(base + tuple(alias.name.split(".")) for alias in node.names if alias.name != "*")
            for target in targets:
                for dependency in _resolve_module(tuple(part for part in target if part)):
                    if dependency not in discovered:
                        discovered.add(dependency)
                        queue.append(dependency)
    return tuple(sorted(discovered))


def _normalize_reference(candidate: PurePosixPath) -> str | None:
    parts: list[str] = []
    for part in candidate.parts:
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
    discovered = set(NORMATIVE_SEEDS)
    queue = list(NORMATIVE_SEEDS)
    graph: dict[str, list[str]] = {}
    while queue:
        relative = queue.pop(0)
        path = _path(relative)
        if not path.is_file():
            raise Phase52EvidenceError(f"normative dependency is missing: {relative}")
        text = path.read_text(encoding="utf-8")
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
            if reference not in discovered:
                discovered.add(reference)
                queue.append(reference)
    return {key: graph[key] for key in sorted(graph)}


def live_scan_paths() -> tuple[str, ...]:
    found: set[str] = set()
    for root in LIVE_ROOTS:
        path = _path(root)
        candidates = (path,) if path.is_file() else path.rglob("*") if path.is_dir() else ()
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix.casefold() not in LIVE_SUFFIXES:
                continue
            relative = candidate.relative_to(PROJECT).as_posix()
            parts = {part.casefold() for part in PurePosixPath(relative).parts}
            if (
                parts & LIVE_EXCLUDED_PARTS
                or relative == "core/approval_inbox_v1.py"
                or _HISTORICAL_GRANT.fullmatch(candidate.name)
                or _PHASE_SCRIPT.fullmatch(candidate.name)
            ):
                continue
            found.add(relative)
    paths = tuple(sorted(found))
    if "scripts/launch_onyx.pyw" not in paths:
        raise Phase52EvidenceError("operational launcher is absent from live scan")
    return paths


def artifact_paths() -> tuple[str, ...]:
    return tuple(
        sorted(
            set(
                (
                    *local_import_closure(),
                    *normative_graph(),
                    R11_ROOT,
                    R11_ARTIFACT,
                    R11_ACCEPTANCE_MANIFEST,
                    R11_ACCEPTANCE,
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


def _verify_r11() -> None:
    for relative, expected in R11_SHA256.items():
        if _sha(_path(relative)) != expected:
            raise Phase52EvidenceError(f"accepted Phase 5.1 R11 anchor drifted: {relative}")
    top = _parse_manifest(R11_ROOT, (R11_ARTIFACT,))
    _verify_entries(top)
    _verify_entries(_parse_manifest(R11_ARTIFACT))
    _verify_entries(_parse_manifest(R11_ACCEPTANCE_MANIFEST, (R11_ACCEPTANCE,)))


def _junit() -> tuple[dict[str, int], str, set[str]]:
    try:
        document = ET.fromstring(_path(JUNIT).read_bytes())
    except (OSError, ET.ParseError) as exc:
        raise Phase52EvidenceError("JUnit is invalid") from exc
    suites = [document] if document.tag == "testsuite" else document.findall("testsuite")
    if len(suites) != 1:
        raise Phase52EvidenceError("JUnit must contain exactly one suite")
    suite = suites[0]
    cases = suite.findall("testcase")
    names = {case.attrib.get("name", "") for case in cases}
    errors = sum(case.find("error") is not None for case in cases)
    failed = sum(case.find("failure") is not None for case in cases)
    skipped = sum(case.find("skipped") is not None for case in cases)
    counts = {"errors": errors, "failed": failed, "passed": len(cases) - errors - failed - skipped, "skipped": skipped}
    if len(cases) != EXPECTED_TEST_COUNT or counts != {"errors": 0, "failed": 0, "passed": EXPECTED_TEST_COUNT, "skipped": 0}:
        raise Phase52EvidenceError("focused JUnit count/result is invalid")
    if not REQUIRED_TEST_NAMES <= names:
        raise Phase52EvidenceError("focused JUnit is missing a required test")
    for prefix, expected in REQUIRED_PREFIX_COUNTS.items():
        if sum(name.startswith(prefix) for name in names) != expected:
            raise Phase52EvidenceError(f"focused JUnit parameter coverage drifted: {prefix}")
    return counts, suite.attrib.get("timestamp", ""), names


def _verify_static_log() -> None:
    raw = _path(STATIC_LOG).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase52EvidenceError("static log is noncanonical")
    expected = {
        "COMPILE": "0",
        "DIFF_CHECK": "0",
        "R11_CLOSURE": "0",
        "RUFF_F_E9": "0",
        "WHITESPACE": "0",
    }
    values: dict[str, str] = {}
    for line in raw.decode().splitlines():
        key, separator, value = line.partition("=")
        if not separator or key in values:
            raise Phase52EvidenceError("static log shape is invalid")
        values[key] = value
    if values != expected:
        raise Phase52EvidenceError("static gates are not all green")


def _verify_live_scan() -> tuple[str, ...]:
    paths = live_scan_paths()
    entries = _parse_manifest(LIVE_SCAN_MANIFEST, paths)
    _verify_entries(entries)
    for relative in paths:
        try:
            text = _path(relative).read_text(encoding="utf-8")
        except UnicodeError as exc:
            raise Phase52EvidenceError(f"live scan file is not UTF-8: {relative}") from exc
        for token in LIVE_FORBIDDEN_TOKENS:
            if token in text:
                raise Phase52EvidenceError(f"approval inbox is wired into live surface: {relative}")
    return paths


def _verify_module_contract() -> None:
    path = _path("core/approval_inbox_v1.py")
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    if any(name.startswith("core.session_grants") for name in imports):
        raise Phase52EvidenceError("approval inbox imports the accepted R11 grant runtime")
    if {"pathlib", "sqlite3"} & imports:
        raise Phase52EvidenceError("approval inbox has a file/database dependency")
    if "APPROVAL_INBOX_FLAG = \"ONYX_APPROVAL_INBOX_V1\"" not in text:
        raise Phase52EvidenceError("strict approval-inbox feature flag is missing")
    public_methods = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"approve", "deny", "revoke", "dispatch", "execute", "persist", "delete", "write"}
    }
    if public_methods:
        raise Phase52EvidenceError("approval inbox exposes a mutation operation")


def _read_bundle() -> dict[str, object]:
    raw = _path(BUNDLE).read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Phase52EvidenceError("bundle is invalid JSON") from exc
    if type(value) is not dict or raw != _canonical_json(value):
        raise Phase52EvidenceError("bundle is not canonical JSON")
    return value


def verify() -> dict[str, object]:
    _verify_r11()
    closure = local_import_closure()
    graph = normative_graph()
    expected_artifacts = artifact_paths()
    top = _parse_manifest(TOP_MANIFEST, (ARTIFACT_MANIFEST,))
    _verify_entries(top)
    artifacts = _parse_manifest(ARTIFACT_MANIFEST, expected_artifacts)
    _verify_entries(artifacts)
    counts, junit_timestamp, _names = _junit()
    _verify_static_log()
    live_paths = _verify_live_scan()
    _verify_module_contract()
    bundle = _read_bundle()
    expected_files = {
        relative: _sha(_path(relative))
        for relative in expected_artifacts
        if relative != BUNDLE
    }
    expected_claims = {
        "batch_preview_only_no_approval_action": True,
        "callbacks_outside_projection_lock": True,
        "complete_secret_free_review_fields": True,
        "default_off_no_source_callback": True,
        "deterministic_snapshot_and_snapshot_bound_cursor": True,
        "drift_expiry_audit_and_unknown_fail_closed": True,
        "exact_finite_calm_batch_manifest": True,
        "high_critical_always_explicit_not_batchable": True,
        "no_grant_runtime_import_or_activation": True,
        "no_mutation_persistence_or_live_authority": True,
        "no_startup_ui_dashboard_provider_or_tool_wiring": True,
        "restart_restores_no_snapshot_or_token": True,
        "stable_exact_sort_filter_and_pagination": True,
        "trusted_host_materialization_boundary": True,
    }
    if bundle.get("contract") != "Phase52ApprovalInboxEvidence.v1":
        raise Phase52EvidenceError("bundle contract is invalid")
    if bundle.get("status") != "candidate-default-off-not-accepted":
        raise Phase52EvidenceError("bundle status is invalid")
    if bundle.get("counts") != counts or bundle.get("junit_timestamp") != junit_timestamp:
        raise Phase52EvidenceError("bundle test evidence drifted")
    if bundle.get("files") != expected_files:
        raise Phase52EvidenceError("bundle file map drifted")
    if bundle.get("dependency_closure") != list(closure):
        raise Phase52EvidenceError("bundle dependency closure drifted")
    if bundle.get("normative_graph") != graph:
        raise Phase52EvidenceError("bundle normative graph drifted")
    if bundle.get("live_scan_paths") != list(live_paths):
        raise Phase52EvidenceError("bundle live scan closure drifted")
    if bundle.get("claims") != expected_claims:
        raise Phase52EvidenceError("bundle claims drifted")
    if bundle.get("feature_flag") != {"default": False, "name": "ONYX_APPROVAL_INBOX_V1"}:
        raise Phase52EvidenceError("bundle feature-flag claim is invalid")
    if bundle.get("external_e6") != {"accepted": False, "required_before_acceptance": True, "status": "pending-external-review"}:
        raise Phase52EvidenceError("bundle external-review status is invalid")
    if bundle.get("accepted_phase51_anchor") != R11_SHA256:
        raise Phase52EvidenceError("bundle R11 anchor drifted")
    if bundle.get("dag") != {
        "artifact_points_to": list(expected_artifacts),
        "bundle_excludes_manifest_and_self_hashes": True,
        "root": TOP_MANIFEST,
        "root_points_to": [ARTIFACT_MANIFEST],
    }:
        raise Phase52EvidenceError("bundle DAG claim drifted")
    print(
        "P52_APPROVAL_INBOX_V1_FROZEN_OK "
        f"tests={counts['passed']} artifacts={len(expected_artifacts)} "
        f"dependencies={len(closure)} normative={len(graph)} live={len(live_paths)}"
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
    )


def freeze() -> None:
    _verify_r11()
    _path(EVIDENCE_DIR).mkdir(parents=True, exist_ok=True)
    pytest_run = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            "tests/test_approval_inbox_v1.py",
            f"--junitxml={JUNIT}",
        ]
    )
    raw = (pytest_run.stdout + pytest_run.stderr).replace("\r\n", "\n").replace("\r", "\n")
    _write(RAW_LOG, raw.encode("utf-8"))
    if pytest_run.returncode:
        raise Phase52EvidenceError("focused tests failed during freeze")

    ruff = _run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "F,E9",
            "core/approval_inbox_v1.py",
            "scripts/check_phase5_approval_inbox_v1_whitespace.py",
            "scripts/verify_phase5_approval_inbox_v1.py",
            "tests/test_approval_inbox_v1.py",
        ]
    )
    compile_run = _run(
        [
            sys.executable,
            "-m",
            "py_compile",
            "core/approval_inbox_v1.py",
            "scripts/check_phase5_approval_inbox_v1_whitespace.py",
            "scripts/verify_phase5_approval_inbox_v1.py",
            "tests/test_approval_inbox_v1.py",
        ]
    )
    whitespace = _run([sys.executable, "scripts/check_phase5_approval_inbox_v1_whitespace.py"])
    diff_check = _run(
        [
            "git",
            "diff",
            "--check",
            "--",
            "core/approval_inbox_v1.py",
            "scripts/check_phase5_approval_inbox_v1_whitespace.py",
            "scripts/verify_phase5_approval_inbox_v1.py",
            "tests/test_approval_inbox_v1.py",
        ]
    )
    gates = {
        "COMPILE": compile_run.returncode,
        "DIFF_CHECK": diff_check.returncode,
        "R11_CLOSURE": 0,
        "RUFF_F_E9": ruff.returncode,
        "WHITESPACE": whitespace.returncode,
    }
    details = ruff.stdout + ruff.stderr + compile_run.stdout + compile_run.stderr + whitespace.stdout + whitespace.stderr + diff_check.stdout + diff_check.stderr
    if any(gates.values()):
        raise Phase52EvidenceError(f"static gate failed: {gates}\n{details}")
    _write(STATIC_LOG, "".join(f"{key}={gates[key]}\n" for key in sorted(gates)).encode())

    live_paths = live_scan_paths()
    for relative in live_paths:
        text = _path(relative).read_text(encoding="utf-8")
        for token in LIVE_FORBIDDEN_TOKENS:
            if token in text:
                raise Phase52EvidenceError(f"approval inbox is wired into live surface: {relative}")
    _write(LIVE_SCAN_MANIFEST, _manifest_bytes(live_paths))

    counts, junit_timestamp, _names = _junit()
    closure = local_import_closure()
    graph = normative_graph()
    claims = {
        "batch_preview_only_no_approval_action": True,
        "callbacks_outside_projection_lock": True,
        "complete_secret_free_review_fields": True,
        "default_off_no_source_callback": True,
        "deterministic_snapshot_and_snapshot_bound_cursor": True,
        "drift_expiry_audit_and_unknown_fail_closed": True,
        "exact_finite_calm_batch_manifest": True,
        "high_critical_always_explicit_not_batchable": True,
        "no_grant_runtime_import_or_activation": True,
        "no_mutation_persistence_or_live_authority": True,
        "no_startup_ui_dashboard_provider_or_tool_wiring": True,
        "restart_restores_no_snapshot_or_token": True,
        "stable_exact_sort_filter_and_pagination": True,
        "trusted_host_materialization_boundary": True,
    }
    paths = artifact_paths()
    files = {relative: _sha(_path(relative)) for relative in paths if relative != BUNDLE}
    try:
        base_commit = _run(["git", "rev-parse", "HEAD"]).stdout.strip()
    except OSError:
        base_commit = ""
    bundle = {
        "accepted_phase51_anchor": R11_SHA256,
        "base_commit": base_commit,
        "claims": claims,
        "contract": "Phase52ApprovalInboxEvidence.v1",
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
        "feature_flag": {"default": False, "name": "ONYX_APPROVAL_INBOX_V1"},
        "files": files,
        "junit_timestamp": junit_timestamp,
        "limits": {
            "max_batch_items": 32,
            "max_cursor": 2_048,
            "max_items": 128,
            "max_item_lifetime_ms": 86_400_000,
            "max_page_size": 50,
            "max_snapshot_lifetime_ms": 900_000,
            "max_snapshots": 8,
            "max_summary": 1_024,
            "max_text": 512,
        },
        "live_scan_paths": list(live_paths),
        "normative_graph": graph,
        "status": "candidate-default-off-not-accepted",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    _write(BUNDLE, _canonical_json(bundle))
    paths = artifact_paths()
    _write(ARTIFACT_MANIFEST, _manifest_bytes(paths))
    _write(TOP_MANIFEST, _manifest_bytes((ARTIFACT_MANIFEST,)))
    verify()


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
