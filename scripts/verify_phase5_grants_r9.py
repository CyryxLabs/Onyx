"""Semantic, live-surface, and byte-exact verifier for Phase 5.1 R9."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path, PurePosixPath

import pytest

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts import verify_phase5_grants_r8 as r8


TOP_MANIFEST = "docs/onyx/VE-SOURCE-P51-GRANTS-R9-001.sha256"
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P51-GRANTS-R9-001.sha256"
EVIDENCE_DIR = "docs/onyx/checkpoints/phase5-grants-r9"
BUNDLE = f"{EVIDENCE_DIR}/phase5-grants-r9.bundle.json"
JUNIT = f"{EVIDENCE_DIR}/phase5-grants-r9.junit.xml"
RAW_LOG = f"{EVIDENCE_DIR}/phase5-grants-r9.raw.log"
STATIC_LOG = f"{EVIDENCE_DIR}/phase5-grants-r9.static.log"
LIVE_SCAN_MANIFEST = f"{EVIDENCE_DIR}/phase5-grants-r9.live-scan.sha256"
CHECKPOINT = f"{EVIDENCE_DIR}/PHASE5_1_GRANTS_SHADOW_R9_CHECKPOINT.md"
R8_ROOT = r8.TOP_MANIFEST
R8_ARTIFACT = r8.ARTIFACT_MANIFEST

SOURCE_SEEDS = (
    "core/session_grants_v9.py",
    "scripts/check_phase5_grants_r9_whitespace.py",
    "scripts/verify_phase5_grants_r9.py",
    "tests/test_session_grants_v9.py",
)
WHITESPACE_SCOPE = list(SOURCE_SEEDS)
NORMATIVE_SEEDS = r8.NORMATIVE_SEEDS
LIVE_ROOTS = ("main.py", "ui.py", "dashboard", "actions", "memory", "runtime", "qml", "packaging", "core", "scripts")
LIVE_SUFFIXES = frozenset({".desktop", ".html", ".iss", ".js", ".json", ".plist", ".py", ".pyw", ".qml", ".spec", ".toml", ".yaml", ".yml"})
LIVE_EXCLUDED_PARTS = frozenset({"__pycache__", ".pytest_cache", "evidence", "evidences", "test", "tests"})
LIVE_FORBIDDEN_TOKENS = ("ONYX_GRANT_EVALUATOR", "SessionGrantShadowStore", "session_grants_v9")
_MARKDOWN_REFERENCE = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_./-]+\.md)(?=$|[#)`\]\s,:;])", re.IGNORECASE)
_HISTORICAL_GRANT = re.compile(r"session_grants_v[0-9]+\.py\Z", re.IGNORECASE)
_HISTORICAL_PHASE_SCRIPT = re.compile(r"(?:verify_phase.*|check_phase.*_whitespace)\.py\Z", re.IGNORECASE)
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_BUNDLE_KEYS = frozenset({
    "base_commit", "claims", "contract", "counts", "dag", "dependency_closure", "environment",
    "external_e6", "feature_flag", "files", "history", "limits", "live_scan", "normative_graph",
    "root_anchor", "static_gates", "status", "timestamp", "whitespace_scope",
})
_CLAIMS = {
    "action_fingerprint_immutable_across_all_ledger_states": True,
    "bounded_external_mutation_ledger_fail_closed": True,
    "bounded_per_identity_reconciliation_history": True,
    "consumed_and_uncertain_survive_grant_cleanup": True,
    "default_off_shadow_only": True,
    "default_off_reconciliation_has_no_callback_or_mutation": True,
    "definite_no_dispatch_or_no_effect_is_releasable": True,
    "dispatch_ambiguity_is_never_released": True,
    "external_mutation_identity_excludes_grant_and_binding": True,
    "external_mutation_identity_permanently_binds_exact_action": True,
    "fresh_exact_reconciliation_callback": True,
    "immutable_self_sufficient_receipt_and_uncertain_records": True,
    "reconciliation_concurrency_and_replay_protected": True,
    "reconciliation_revision_prevents_aba": True,
    "scoped_grant_generations": True,
    "verified_outcome_material_precedes_fallible_post_snapshot": True,
    "zero_aggregate_semantics_match_direct_and_reconciled_commit": True,
    "exact_raw_feature_gate_linearizes_every_public_operation": True,
    "no_separate_reconciliation_cardinality_limit": True,
    "receipt_verification_audit_precedes_fallible_commit_snapshot": True,
    "scripts_and_pyw_are_in_live_nonwiring_freeze": True,
}
_LIMIT_CONSTANTS = {
    **{key: value for key, value in r8._LIMIT_CONSTANTS.items() if value != "MAX_RECONCILIATIONS"},
}
_REQUIRED_TESTS = {
    "test_concurrent_reconciliation_only_one_response_applies",
    "test_confirmed_effect_consumes_with_full_receipt",
    "test_confirmed_effect_preserves_known_quarantined_receipt_evidence",
    "test_confirmed_no_effect_releases_quarantine",
    "test_dispatch_attempt_is_quarantined_and_cannot_retry_across_successor_grant",
    "test_flag_removed_after_verified_outcome_capture_stops_callbacks_but_keeps_uncertainty",
    "test_identity_contract_has_minimum_namespace_and_no_grant_or_binding_fields",
    "test_pre_dispatch_transition_survives_absence_timeout_and_terminal",
    "test_relevant_revoke_after_dispatch_leaves_uncertain",
    "test_relevant_semantic_drift_after_dispatch_quarantines_verified_effect",
    "test_reconciliation_after_terminal_resolves_once_and_replay_is_denied",
    "test_same_external_namespace_key_cannot_reserve_across_distinct_bindings",
    "test_still_uncertain_stays_quarantined",
    "test_terminal_controls_release_pending_but_preserve_uncertain",
    "test_unrelated_revoke_does_not_invalidate_other_grant_commit",
    "test_unverified_receipt_remains_uncertain",
    "test_verified_effect_consumes_and_receipt_is_self_sufficient",
    "test_consumed_external_namespace_key_survives_successor_grant_and_binding",
    "test_default_off_reconciliation_preserves_uncertainty_without_callback",
    "test_reconciliation_history_is_bounded_per_identity_and_full_capacity_still_resolves",
    "test_two_concurrent_still_uncertain_callbacks_cannot_aba_double_apply",
    "test_verified_effect_post_snapshot_failure_preserves_material_for_reconciliation",
    "test_zero_cost_zero_aggregate_direct_and_reconciled_commits_do_not_exhaust_aggregate",
    "test_grant_issue_toggle_after_approval_aborts_without_assignment",
    "test_callback_toggle_then_failure_does_not_run_fail_closed_mutation",
    "test_revoke_and_snapshot_toggle_at_finalization_abort_without_mutation",
    "test_receipt_verifier_toggle_aborts_commit_without_use_or_receipt",
    "test_reconciliation_toggle_after_callback_aborts_without_history_mutation",
    "test_verified_material_is_persisted_before_post_verifier_snapshot_failure",
}
_REQUIRED_PREFIX_COUNTS = {
    "test_action_callback_toggle_aborts_evaluate_and_reserve_without_mutation[": 2,
    "test_released_identity_retries_only_identical_action_fingerprint[": 2,
    "test_terminal_control_toggle_at_finalization_aborts_without_mutation[": 3,
}


class Phase5GrantR9EvidenceError(RuntimeError):
    pass


def _path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or "." in pure.parts or ".." in pure.parts:
        raise Phase5GrantR9EvidenceError(f"unsafe evidence path: {relative}")
    return root / Path(*pure.parts)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize_relative(candidate: PurePosixPath) -> str | None:
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


def _markdown_references(root: Path, relative: str) -> set[str]:
    references: set[str] = set()
    text = _path(root, relative).read_text(encoding="utf-8")
    for raw in _MARKDOWN_REFERENCE.findall(text):
        raw_path = PurePosixPath(raw.replace("\\", "/"))
        candidates = [raw_path] if raw.startswith(("docs/", "plans/")) else [PurePosixPath(relative).parent / raw_path, raw_path]
        for candidate in candidates:
            normalized = _normalize_relative(candidate)
            if normalized is not None and normalized.casefold().endswith(".md") and _path(root, normalized).is_file():
                references.add(normalized)
                break
    return references


def derive_normative_graph(root: Path) -> dict[str, list[str]]:
    discovered = set(NORMATIVE_SEEDS)
    queue = list(NORMATIVE_SEEDS)
    graph: dict[str, list[str]] = {}
    while queue:
        relative = queue.pop(0)
        if not _path(root, relative).is_file():
            raise Phase5GrantR9EvidenceError(f"normative node missing: {relative}")
        references = _markdown_references(root, relative)
        graph[relative] = sorted(references - {relative})
        for reference in graph[relative]:
            if reference not in discovered:
                discovered.add(reference)
                queue.append(reference)
    return {relative: graph[relative] for relative in sorted(graph)}


def derive_live_scan_paths(root: Path) -> tuple[str, ...]:
    found: set[str] = set()
    for entry in LIVE_ROOTS:
        path = _path(root, entry)
        candidates = (path,) if path.is_file() else path.rglob("*") if path.is_dir() else ()
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix.casefold() not in LIVE_SUFFIXES:
                continue
            relative = candidate.relative_to(root).as_posix()
            parts = {part.casefold() for part in PurePosixPath(relative).parts}
            if (
                parts & LIVE_EXCLUDED_PARTS
                or _HISTORICAL_GRANT.fullmatch(candidate.name)
                or _HISTORICAL_PHASE_SCRIPT.fullmatch(candidate.name)
            ):
                continue
            found.add(relative)
    paths = tuple(sorted(found))
    if "scripts/launch_onyx.pyw" not in paths:
        raise Phase5GrantR9EvidenceError("operational launcher is absent from live scan")
    return paths


def local_import_closure(root: Path) -> tuple[str, ...]:
    try:
        return r8.r7.r6.local_import_closure(root, SOURCE_SEEDS)
    except Exception as exc:
        raise Phase5GrantR9EvidenceError(str(exc)) from exc


def artifact_paths(root: Path) -> tuple[str, ...]:
    graph = derive_normative_graph(root)
    closure = local_import_closure(root)
    return tuple(sorted(set((
        *closure, *graph, R8_ARTIFACT, R8_ROOT, CHECKPOINT, BUNDLE, JUNIT, RAW_LOG,
        STATIC_LOG, LIVE_SCAN_MANIFEST,
    ))))


def _parse_manifest(path: Path, expected: tuple[str, ...] | None = None):
    try:
        return r8._parse_manifest(path, expected)
    except Exception as exc:
        raise Phase5GrantR9EvidenceError(str(exc)) from exc


def _verify_entries(root: Path, entries) -> None:
    try:
        r8._verify_entries(root, entries)
    except Exception as exc:
        raise Phase5GrantR9EvidenceError(str(exc)) from exc


def _read_bundle(root: Path) -> dict[str, object]:
    raw = _path(root, BUNDLE).read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Phase5GrantR9EvidenceError("bundle is not valid JSON") from exc
    canonical = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
    if raw != canonical or not isinstance(value, dict) or frozenset(value) != _BUNDLE_KEYS:
        raise Phase5GrantR9EvidenceError("bundle shape/serialization is noncanonical")
    return value


def _junit(root: Path) -> tuple[dict[str, int], str, set[str]]:
    try:
        document = ET.fromstring(_path(root, JUNIT).read_bytes())
    except (OSError, ET.ParseError) as exc:
        raise Phase5GrantR9EvidenceError("JUnit is invalid") from exc
    suites = [document] if document.tag == "testsuite" else document.findall("testsuite")
    if len(suites) != 1:
        raise Phase5GrantR9EvidenceError("JUnit must contain exactly one suite")
    suite = suites[0]
    cases = suite.findall("testcase")
    names = {case.attrib.get("name", "") for case in cases}
    actual = {
        "errors": sum(case.find("error") is not None for case in cases),
        "failed": sum(case.find("failure") is not None for case in cases),
        "skipped": sum(case.find("skipped") is not None for case in cases),
    }
    actual["passed"] = len(cases) - actual["errors"] - actual["failed"] - actual["skipped"]
    declared = {
        "errors": int(suite.attrib["errors"]),
        "failed": int(suite.attrib["failures"]),
        "skipped": int(suite.attrib["skipped"]),
        "passed": int(suite.attrib["tests"]) - int(suite.attrib["errors"]) - int(suite.attrib["failures"]) - int(suite.attrib["skipped"]),
    }
    if actual != declared or not names or "" in names:
        raise Phase5GrantR9EvidenceError("JUnit declarations or names are invalid")
    return actual, suite.attrib["timestamp"], names


def _kv_log(root: Path, relative: str) -> dict[str, str]:
    raw = _path(root, relative).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase5GrantR9EvidenceError(f"log is noncanonical: {relative}")
    values: dict[str, str] = {}
    for line in raw.decode().splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise Phase5GrantR9EvidenceError(f"log line is invalid: {relative}")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key) or key in values:
            raise Phase5GrantR9EvidenceError(f"log key is invalid: {relative}")
        values[key] = value
    return values


def _class_fields(tree: ast.Module, name: str) -> set[str]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return {item.target.id for item in node.body if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)}
    return set()


def _method(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "SessionGrantShadowStore":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == name:
                    return item
    raise Phase5GrantR9EvidenceError(f"required method is missing: {name}")


def _validate_code_claims(root: Path) -> None:
    source = _path(root, "core/session_grants_v9.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    identity = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "canonical_idempotency_identity"), None)
    if identity is None:
        raise Phase5GrantR9EvidenceError("external mutation identity function is missing")
    identity_literals = {node.value for node in ast.walk(identity) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    required_identity = {"session_id", "workspace_id", "provider", "provider_namespace", "account", "tool", "operation", "idempotency_key", "ExternalMutationIdentity.v9"}
    forbidden_identity = {"grant_id", "binding_digest", "scope_digest", "target_identity", "payload_digest"}
    if not required_identity <= identity_literals or identity_literals & forbidden_identity:
        raise Phase5GrantR9EvidenceError("external mutation identity namespace is unsafe")
    action_fingerprint = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "canonical_external_action_fingerprint"), None)
    if action_fingerprint is None:
        raise Phase5GrantR9EvidenceError("immutable external action fingerprint is missing")
    action_literals = {node.value for node in ast.walk(action_fingerprint) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    required_action = {"provider", "provider_namespace", "account", "operation", "tool", "target_identity", "payload_digest", "binding_digest", "action_contract_digest", "ImmutableExternalActionFingerprint.v9"}
    if not required_action <= action_literals:
        raise Phase5GrantR9EvidenceError("external action fingerprint omits material action context")
    required_services = {"verify_receipt", "reconcile", "resolve_outcome"}
    if not required_services <= _class_fields(tree, "HostServices"):
        raise Phase5GrantR9EvidenceError("pinned outcome/receipt/reconciliation services are incomplete")
    uncertain = _class_fields(tree, "UncertainRecord")
    receipt = _class_fields(tree, "ReceiptRecord")
    context = {"session_id", "workspace_id", "provider", "provider_namespace", "account", "tool", "operation", "scope_digest", "binding_digest", "action_audit_digest", "idempotency_key", "idempotency_identity_digest", "action_fingerprint", "reservation_id", "grant_id", "cost_micro", "reconciliation_count", "reconciliation_history_root", "latest_reconciliation_sequence"}
    if not context <= uncertain or not context <= receipt:
        raise Phase5GrantR9EvidenceError("immutable mutation records are not self-sufficient")
    ledger_fields = _class_fields(tree, "MutationLedgerEntry")
    if not {"identity_digest", "action_fingerprint", "state", "reconciliation_count", "reconciliation_history_root", "latest_reconciliation_sequence"} <= ledger_fields:
        raise Phase5GrantR9EvidenceError("mutation ledger omits immutable binding or compact history")
    if not {"revision", "reconciliation_count", "reconciliation_history_root", "latest_reconciliation_sequence"} <= uncertain:
        raise Phase5GrantR9EvidenceError("uncertain record omits ABA revision history")
    verification_audit = {
        "verification_digest", "verification_audit_digest", "verification_verified",
        "verification_sequence", "verification_receipt_id", "verification_challenge",
    }
    if not verification_audit <= uncertain:
        raise Phase5GrantR9EvidenceError("uncertainty omits self-sufficient receipt-verification audit")
    record_outcome = _method(tree, "record_outcome")
    outcome_calls = {node.func.attr for node in ast.walk(record_outcome) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    if not {"_call_outcome_resolver", "_quarantine_reservation_locked", "_call_receipt_verifier", "_verification_is_exact", "_persist_verification_audit_locked"} <= outcome_calls:
        raise Phase5GrantR9EvidenceError("dispatch uncertainty path is incomplete")
    ordered_calls = [node for node in ast.walk(record_outcome) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    quarantine_lines = [node.lineno for node in ordered_calls if node.func.attr == "_quarantine_reservation_locked"]
    snapshot_lines = [node.lineno for node in ordered_calls if node.func.attr == "_snapshot_outside_lock"]
    if not quarantine_lines or not snapshot_lines or min(quarantine_lines) >= min(snapshot_lines):
        raise Phase5GrantR9EvidenceError("returned outcome material is not quarantined before the fallible post-snapshot")
    verifier_lines = [node.lineno for node in ordered_calls if node.func.attr == "_call_receipt_verifier"]
    audit_lines = [node.lineno for node in ordered_calls if node.func.attr == "_persist_verification_audit_locked"]
    if not verifier_lines or not audit_lines or not verifier_lines[0] < audit_lines[0] < max(snapshot_lines):
        raise Phase5GrantR9EvidenceError("verified receipt audit is not persisted before commit snapshot")
    dispatch_calls = {node.func.attr for node in ast.walk(_method(tree, "mark_dispatch_attempted")) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    if "_quarantine_reservation_locked" not in dispatch_calls:
        raise Phase5GrantR9EvidenceError("pre-dispatch uncertainty transition is missing")
    reconcile = _method(tree, "reconcile_uncertain")
    reconcile_calls = {node.func.attr for node in ast.walk(reconcile) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    if not {"_call_reconciliation", "_verification_is_exact", "_receipt_replayed_locked", "_set_uncertain_ledger_state_locked", "_advance_reconciliation_locked"} <= reconcile_calls:
        raise Phase5GrantR9EvidenceError("reconciliation path is incomplete")
    reconcile_names = {node.id for node in ast.walk(reconcile) if isinstance(node, ast.Name)}
    if "MAX_RECONCILIATIONS" in reconcile_names:
        raise Phase5GrantR9EvidenceError("reconciliation is capacity-blocked")
    advance = _method(tree, "_advance_reconciliation_locked")
    advance_calls = {node.func.id if isinstance(node.func, ast.Name) else node.func.attr for node in ast.walk(advance) if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))}
    if not {"_roll_reconciliation_history", "replace"} <= advance_calls:
        raise Phase5GrantR9EvidenceError("reconciliation revision does not roll immutable history")
    raw_gate = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_raw_feature_flag_enabled"), None)
    raw_source = ast.get_source_segment(source, raw_gate) if raw_gate is not None else ""
    validate_source = ast.get_source_segment(source, _method(tree, "_gate_validate_locked"))
    if not raw_source or "type(raw_value) is str" not in raw_source or '.strip().casefold() in {"1", "true"}' not in raw_source:
        raise Phase5GrantR9EvidenceError("raw feature flag parser is not exact and closed")
    if not validate_source or "hmac.compare_digest(current, lease)" not in validate_source:
        raise Phase5GrantR9EvidenceError("feature gate lease does not preserve the exact raw token")
    public_methods = (
        "request_session_grant", "evaluate", "reserve", "mark_dispatch_attempted", "record_outcome",
        "reconcile_uncertain", "revoke", "kill", "mark_audit_unhealthy", "end_session", "snapshot_counts",
    )
    callback_names = {
        "_call_resolver", "_call_outcome_resolver", "_call_receipt_verifier", "_call_reconciliation",
        "_snapshot_outside_lock", "approve", "monotonic_ms",
    }
    for method_name in public_methods:
        method = _method(tree, method_name)
        calls = [node for node in ast.walk(method) if isinstance(node, ast.Call)]
        attrs = [node.func.attr for node in calls if isinstance(node.func, ast.Attribute)]
        if "_gate_entry_locked" not in attrs or "_gate_validate_locked" not in attrs:
            raise Phase5GrantR9EvidenceError(f"public method lacks entry/final gate linearization: {method_name}")
        validation_lines = [node.lineno for node in calls if isinstance(node.func, ast.Attribute) and node.func.attr == "_gate_validate_locked"]
        callback_lines = [node.lineno for node in calls if isinstance(node.func, ast.Attribute) and node.func.attr in callback_names]
        if any(not any(line > callback_line for line in validation_lines) for callback_line in callback_lines):
            raise Phase5GrantR9EvidenceError(f"callback lacks a later feature gate sample: {method_name}")
    if any(token in source for token in ("MAX_RECONCILIATIONS", "ReconciliationRecord", "self._reconciliations")):
        raise Phase5GrantR9EvidenceError("false reconciliation cardinality remains in the implementation")
    revoke_calls = {node.func.id if isinstance(node.func, ast.Name) else node.func.attr for node in ast.walk(_method(tree, "_revoke_locked")) if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))}
    if "_enum" not in revoke_calls or '"reconciled-effect"' in source:
        raise Phase5GrantR9EvidenceError("revocation reasons are not closed and validated")
    cleanup_attrs = {node.attr for node in ast.walk(_method(tree, "_cleanup_grant_capacity_locked")) if isinstance(node, ast.Attribute)}
    if cleanup_attrs & {"_mutation_ledger", "_uncertain_records", "_receipts"}:
        raise Phase5GrantR9EvidenceError("grant cleanup erases durable mutation evidence")
    if "_global_generation" not in source or "_grant_generations" not in source:
        raise Phase5GrantR9EvidenceError("scoped generation barriers are missing")
    if "uncertain_needs_reconciliation" not in source or "consumed_verified" not in source:
        raise Phase5GrantR9EvidenceError("required mutation lifecycle states are missing")


def _constants(root: Path) -> dict[str, int]:
    tree = ast.parse(_path(root, "core/session_grants_v9.py").read_text(encoding="utf-8"))
    found: dict[str, int] = {}
    wanted = set(_LIMIT_CONSTANTS.values())
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in wanted:
            value = ast.literal_eval(node.value)
            if type(value) is not int:
                raise Phase5GrantR9EvidenceError(f"limit is invalid: {node.targets[0].id}")
            found[node.targets[0].id] = value
    if set(found) != wanted:
        raise Phase5GrantR9EvidenceError("material limit set is incomplete")
    return {key: found[name] for key, name in _LIMIT_CONSTANTS.items()}


def _run_history(root: Path) -> dict[str, object]:
    try:
        history = r8._run_history(root)
        top = _parse_manifest(_path(root, R8_ROOT), (R8_ARTIFACT,))
        artifacts = _parse_manifest(_path(root, R8_ARTIFACT))
        _verify_entries(root, top + artifacts)
        result = r8.verify_evidence(root, current_base_commit=_current_commit(root), current_environment=_environment())
    except Exception as exc:
        raise Phase5GrantR9EvidenceError("V1-R8 historical verification failed") from exc
    expected = {"artifact_files": 39, "dependencies": 11, "live_scan": 69, "normative": 20, "root_files": 1, "tests": 29}
    if any(result.get(key) != value for key, value in expected.items()):
        raise Phase5GrantR9EvidenceError("V8 historical result is incomplete")
    history["v8"] = {
        "artifact_manifest": R8_ARTIFACT,
        "artifact_sha256": _sha(_path(root, R8_ARTIFACT)),
        "artifacts": len(artifacts),
        "root": R8_ROOT,
        "root_sha256": _sha(_path(root, R8_ROOT)),
    }
    return history


def _current_commit(root: Path) -> str:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False)
    value = result.stdout.strip().casefold()
    if result.returncode or not _HEX40.fullmatch(value):
        raise Phase5GrantR9EvidenceError("current git base commit is unavailable")
    return value


def _environment() -> dict[str, str]:
    return {"executable": str(Path(sys.executable).resolve()), "platform": platform.platform(), "pytest": pytest.__version__, "python": sys.version.split()[0]}


def _run_static_gates(root: Path, live_paths: tuple[str, ...]) -> dict[str, object]:
    compile_scope = tuple(sorted(set(WHITESPACE_SCOPE) | {path for path in live_paths if path.endswith((".py", ".pyw"))}))
    for relative in compile_scope:
        try:
            compile(_path(root, relative).read_text(encoding="utf-8"), relative, "exec", dont_inherit=True)
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise Phase5GrantR9EvidenceError(f"live compile gate failed: {relative}") from exc
    ruff_candidates = (root / ".venv" / "Scripts" / "ruff.exe", root / ".venv" / "bin" / "ruff")
    ruff = next((str(path) for path in ruff_candidates if path.is_file()), shutil.which("ruff"))
    if not ruff:
        raise Phase5GrantR9EvidenceError("live Ruff gate is unavailable")
    ruff_result = subprocess.run([ruff, "check", "--no-cache", "--select", "F,E9", *WHITESPACE_SCOPE], cwd=root, capture_output=True, text=True, timeout=60, check=False)
    if ruff_result.returncode:
        raise Phase5GrantR9EvidenceError(f"live Ruff gate failed: {ruff_result.stdout}{ruff_result.stderr}")
    whitespace = subprocess.run([sys.executable, str(_path(root, "scripts/check_phase5_grants_r9_whitespace.py"))], cwd=root, capture_output=True, text=True, timeout=60, check=False, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    if whitespace.returncode or whitespace.stdout.strip() != "P51_GRANTS_R9_WHITESPACE_OK files=4":
        raise Phase5GrantR9EvidenceError("live whitespace gate failed")
    for relative in live_paths:
        text = _path(root, relative).read_text(encoding="utf-8", errors="strict")
        if any(token in text for token in LIVE_FORBIDDEN_TOKENS):
            raise Phase5GrantR9EvidenceError(f"R9 is wired into live surface: {relative}")
    if _sha(_path(root, "scripts/launch_onyx.pyw")) == "0" * 64:
        raise Phase5GrantR9EvidenceError("operational launcher hash is invalid")
    return {
        "compile": 0,
        "compile_files": len(compile_scope),
        "live_scan": 0,
        "live_scan_files": len(live_paths),
        "ruff_f_e9": 0,
        "whitespace": 0,
    }


def _require_equal(claim: object, actual: object, label: str) -> None:
    if claim != actual:
        raise Phase5GrantR9EvidenceError(f"{label} binding is false or incomplete")


def verify_evidence(root: Path = PROJECT, *, current_base_commit: str | None = None, current_environment: dict[str, str] | None = None) -> dict[str, object]:
    root = root.resolve()
    expected_artifacts = artifact_paths(root)
    top = _parse_manifest(_path(root, TOP_MANIFEST), (ARTIFACT_MANIFEST,))
    _verify_entries(root, top)
    artifacts = _parse_manifest(_path(root, ARTIFACT_MANIFEST), expected_artifacts)
    _verify_entries(root, artifacts)
    live_paths = derive_live_scan_paths(root)
    live_entries = _parse_manifest(_path(root, LIVE_SCAN_MANIFEST), live_paths)
    _verify_entries(root, live_entries)
    bundle = _read_bundle(root)
    if bundle.get("contract") != "Phase5SessionGrantShadowEvidence.v9" or bundle.get("status") != "candidate-default-off-not-accepted":
        raise Phase5GrantR9EvidenceError("bundle contract/status is invalid")
    _require_equal(bundle.get("claims"), _CLAIMS, "semantic claims")
    _validate_code_claims(root)
    _require_equal(bundle.get("feature_flag"), {"default": False, "name": "ONYX_GRANT_EVALUATOR"}, "feature flag")
    _require_equal(bundle.get("external_e6"), {"accepted": False, "required_before_acceptance": True, "status": "pending-external-review"}, "external E6 status")
    _require_equal(bundle.get("root_anchor"), {"externally_anchored": False, "required_before_acceptance": True}, "root anchor")
    _require_equal(bundle.get("dag"), {"artifact_points_to": list(expected_artifacts), "bundle_excludes_manifest_and_self_hashes": True, "root": TOP_MANIFEST, "root_points_to": [ARTIFACT_MANIFEST]}, "evidence DAG")
    leaf_paths = tuple(path for path in expected_artifacts if path != BUNDLE)
    files = bundle.get("files")
    if not isinstance(files, dict) or tuple(sorted(files)) != tuple(sorted(leaf_paths)):
        raise Phase5GrantR9EvidenceError("bundle leaf set is not exact")
    for relative, digest in files.items():
        if type(digest) is not str or not _HEX64.fullmatch(digest) or _sha(_path(root, relative)) != digest:
            raise Phase5GrantR9EvidenceError(f"bundle leaf hash mismatch: {relative}")
    closure = local_import_closure(root)
    _require_equal(bundle.get("dependency_closure"), list(closure), "dependency closure")
    graph = derive_normative_graph(root)
    if "readme.md" not in graph:
        raise Phase5GrantR9EvidenceError("bare root readme normative fallback was not resolved recursively")
    _require_equal(bundle.get("normative_graph"), graph, "recursive normative graph")
    history = _run_history(root)
    _require_equal(bundle.get("history"), history, "historical evidence")
    counts, junit_timestamp, names = _junit(root)
    if counts["failed"] or counts["errors"] or not _REQUIRED_TESTS <= names:
        raise Phase5GrantR9EvidenceError("focused semantic JUnit evidence is incomplete")
    for prefix, expected in _REQUIRED_PREFIX_COUNTS.items():
        if sum(name.startswith(prefix) for name in names) != expected:
            raise Phase5GrantR9EvidenceError(f"focused parametrized JUnit evidence differs: {prefix}")
    _require_equal(bundle.get("counts"), counts, "JUnit counts")
    raw = _kv_log(root, RAW_LOG)
    if raw.get("timestamp") != junit_timestamp or raw.get("exit_code") != "0" or raw.get("result") != f"{counts['passed']} passed" or any(raw.get(key) != str(counts[key]) for key in ("passed", "failed", "errors", "skipped")):
        raise Phase5GrantR9EvidenceError("raw/JUnit evidence differs")
    static = _kv_log(root, STATIC_LOG)
    expected_static = {
        "compile_mode": "recursive-live-in-memory-built-in-compile",
        "compile_exit_code": "0",
        "diff_check_command": "python scripts/check_phase5_grants_r9_whitespace.py",
        "diff_check_exit_code": "0",
        "diff_check_scope": ";".join(WHITESPACE_SCOPE),
        "live_scan_exit_code": "0",
        "live_scan_manifest": LIVE_SCAN_MANIFEST,
        "live_scan_scope": ";".join(LIVE_ROOTS),
        "ruff_command": "ruff check --no-cache --select F,E9",
        "ruff_exit_code": "0",
        "v8_evidence_artifacts": "39",
        "v8_evidence_root": "1",
    }
    _require_equal(static, expected_static, "static log")
    live_static = _run_static_gates(root, live_paths)
    _require_equal(bundle.get("static_gates"), live_static, "live static gates")
    _require_equal(bundle.get("live_scan"), {"forbidden_tokens": list(LIVE_FORBIDDEN_TOKENS), "manifest": LIVE_SCAN_MANIFEST, "paths": list(live_paths)}, "live scan freeze")
    _require_equal(bundle.get("whitespace_scope"), WHITESPACE_SCOPE, "whitespace scope")
    _require_equal(bundle.get("limits"), _constants(root), "code limits")
    base = current_base_commit or _current_commit(root)
    if not _HEX40.fullmatch(base) or bundle.get("base_commit") != base:
        raise Phase5GrantR9EvidenceError("bundle base commit is invalid or stale")
    _require_equal(bundle.get("environment"), current_environment or _environment(), "runtime environment")
    timestamp = bundle.get("timestamp")
    if type(timestamp) is not str or timestamp != junit_timestamp:
        raise Phase5GrantR9EvidenceError("bundle timestamp differs from JUnit")
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise Phase5GrantR9EvidenceError("bundle timestamp is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Phase5GrantR9EvidenceError("bundle timestamp lacks timezone")
    return {
        "artifact_files": len(artifacts),
        "artifact_manifest_sha256": _sha(_path(root, ARTIFACT_MANIFEST)),
        "dependencies": len(closure),
        "live_scan": len(live_paths),
        "normative": len(graph),
        "root_files": len(top),
        "root_manifest_sha256": _sha(_path(root, TOP_MANIFEST)),
        "tests": counts["passed"],
    }


def main() -> int:
    result = verify_evidence()
    print(
        f"P51_GRANTS_R9_EVIDENCE_OK root={result['root_files']} artifacts={result['artifact_files']} "
        f"dependencies={result['dependencies']} normative={result['normative']} live_scan={result['live_scan']} "
        f"tests={result['tests']} root_sha256={result['root_manifest_sha256']} "
        f"artifact_sha256={result['artifact_manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
