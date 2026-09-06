"""Semantic and byte-exact verifier for the Phase 5.1 R6 evidence DAG."""

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

from scripts import verify_phase5_grants_r5 as r5


TOP_MANIFEST = "docs/onyx/VE-SOURCE-P51-GRANTS-R6-001.sha256"
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P51-GRANTS-R6-001.sha256"
BUNDLE = "docs/onyx/checkpoints/phase5-grants-r6/phase5-grants-r6.bundle.json"
JUNIT = "docs/onyx/checkpoints/phase5-grants-r6/phase5-grants-r6.junit.xml"
RAW_LOG = "docs/onyx/checkpoints/phase5-grants-r6/phase5-grants-r6.raw.log"
STATIC_LOG = "docs/onyx/checkpoints/phase5-grants-r6/phase5-grants-r6.static.log"
CHECKPOINT = "docs/onyx/checkpoints/phase5-grants-r6/PHASE5_1_GRANTS_SHADOW_R6_CHECKPOINT.md"
V1_ROOT = r5.V1_ROOT
V2_ROOT = r5.V2_ROOT
V2_ARTIFACT = r5.V2_ARTIFACT
V3_ROOT = r5.V3_ROOT
V3_ARTIFACT = r5.V3_ARTIFACT
V4_ROOT = r5.V4_ROOT
V4_ARTIFACT = r5.V4_ARTIFACT
V5_ROOT = "docs/onyx/VE-SOURCE-P51-GRANTS-R5-001.sha256"
V5_ARTIFACT = "docs/onyx/VE-ARTIFACTS-P51-GRANTS-R5-001.sha256"

NORMATIVE_NODES = (
    "core/workspaces.py",
    "docs/MISSIONS.md",
    "docs/onyx/APPROVAL_POLICY.md",
    "docs/onyx/CAPABILITY_MATRIX.md",
    "docs/onyx/CURRENT_STATE_AUDIT.md",
    "docs/onyx/DATA_AND_MEMORY_BOUNDARIES.md",
    "docs/onyx/GAP_ANALYSIS.md",
    "docs/onyx/IMPLEMENTATION_ROADMAP.md",
    "docs/onyx/OPEN_SOURCE_AND_API_LICENSE_REVIEW.md",
    "docs/onyx/TARGET_ARCHITECTURE.md",
    "docs/onyx/THREAT_MODEL.md",
    "docs/onyx/VERIFICATION_EVIDENCE.md",
    "docs/onyx/adrs/ADR-0001-stable-core-extension.md",
    "docs/onyx/adrs/ADR-0002-workspace-and-evidence-sidecars.md",
    "docs/onyx/adrs/ADR-0003-capability-nexus-and-mcp.md",
    "docs/onyx/adrs/ADR-0004-model-router-and-provider-adapters.md",
    "docs/onyx/adrs/ADR-0005-qt-quick-shell-migration.md",
    "plans/onyx-advanced-entity-redesign.md",
)
NORMATIVE_GRAPH = {
    "core/workspaces.py": [],
    "docs/MISSIONS.md": [],
    "docs/onyx/APPROVAL_POLICY.md": [],
    "docs/onyx/CAPABILITY_MATRIX.md": [
        "docs/onyx/APPROVAL_POLICY.md",
        "docs/onyx/OPEN_SOURCE_AND_API_LICENSE_REVIEW.md",
        "docs/onyx/TARGET_ARCHITECTURE.md",
        "docs/onyx/THREAT_MODEL.md",
        "docs/onyx/VERIFICATION_EVIDENCE.md",
    ],
    "docs/onyx/CURRENT_STATE_AUDIT.md": [
        "docs/onyx/APPROVAL_POLICY.md",
        "docs/onyx/DATA_AND_MEMORY_BOUNDARIES.md",
        "docs/onyx/OPEN_SOURCE_AND_API_LICENSE_REVIEW.md",
        "docs/onyx/TARGET_ARCHITECTURE.md",
        "docs/onyx/THREAT_MODEL.md",
        "docs/onyx/VERIFICATION_EVIDENCE.md",
        "plans/onyx-advanced-entity-redesign.md",
    ],
    "docs/onyx/DATA_AND_MEMORY_BOUNDARIES.md": [],
    "docs/onyx/GAP_ANALYSIS.md": [
        "docs/onyx/APPROVAL_POLICY.md",
        "docs/onyx/CAPABILITY_MATRIX.md",
        "docs/onyx/DATA_AND_MEMORY_BOUNDARIES.md",
        "docs/onyx/OPEN_SOURCE_AND_API_LICENSE_REVIEW.md",
        "docs/onyx/TARGET_ARCHITECTURE.md",
        "docs/onyx/THREAT_MODEL.md",
        "plans/onyx-advanced-entity-redesign.md",
    ],
    "docs/onyx/IMPLEMENTATION_ROADMAP.md": [
        "docs/onyx/APPROVAL_POLICY.md",
        "docs/onyx/CAPABILITY_MATRIX.md",
        "docs/onyx/GAP_ANALYSIS.md",
        "docs/onyx/OPEN_SOURCE_AND_API_LICENSE_REVIEW.md",
        "docs/onyx/TARGET_ARCHITECTURE.md",
        "docs/onyx/adrs/ADR-0001-stable-core-extension.md",
        "docs/onyx/adrs/ADR-0002-workspace-and-evidence-sidecars.md",
        "docs/onyx/adrs/ADR-0003-capability-nexus-and-mcp.md",
        "docs/onyx/adrs/ADR-0004-model-router-and-provider-adapters.md",
        "docs/onyx/adrs/ADR-0005-qt-quick-shell-migration.md",
        "plans/onyx-advanced-entity-redesign.md",
    ],
    "docs/onyx/OPEN_SOURCE_AND_API_LICENSE_REVIEW.md": [],
    "docs/onyx/TARGET_ARCHITECTURE.md": ["docs/onyx/APPROVAL_POLICY.md"],
    "docs/onyx/THREAT_MODEL.md": ["docs/onyx/APPROVAL_POLICY.md"],
    "docs/onyx/VERIFICATION_EVIDENCE.md": ["docs/onyx/CAPABILITY_MATRIX.md"],
    "docs/onyx/adrs/ADR-0001-stable-core-extension.md": [],
    "docs/onyx/adrs/ADR-0002-workspace-and-evidence-sidecars.md": [],
    "docs/onyx/adrs/ADR-0003-capability-nexus-and-mcp.md": [],
    "docs/onyx/adrs/ADR-0004-model-router-and-provider-adapters.md": [],
    "docs/onyx/adrs/ADR-0005-qt-quick-shell-migration.md": [],
    "plans/onyx-advanced-entity-redesign.md": [
        "docs/MISSIONS.md",
        "docs/onyx/APPROVAL_POLICY.md",
        "docs/onyx/CAPABILITY_MATRIX.md",
        "docs/onyx/CURRENT_STATE_AUDIT.md",
        "docs/onyx/DATA_AND_MEMORY_BOUNDARIES.md",
        "docs/onyx/GAP_ANALYSIS.md",
        "docs/onyx/IMPLEMENTATION_ROADMAP.md",
        "docs/onyx/OPEN_SOURCE_AND_API_LICENSE_REVIEW.md",
        "docs/onyx/TARGET_ARCHITECTURE.md",
        "docs/onyx/THREAT_MODEL.md",
    ],
}
SOURCE_SEEDS = (
    "core/session_grants_v6.py",
    "scripts/check_phase5_grants_r6_whitespace.py",
    "scripts/verify_phase5_grants_r6.py",
    "tests/test_session_grants_v6.py",
)
DECLARED_LOCAL_CLOSURE = (
    "core/__init__.py",
    "core/session_grants_v6.py",
    "memory/__init__.py",
    "memory/store.py",
    "scripts/check_phase5_grants_r6_whitespace.py",
    "scripts/verify_phase5_grants_r4.py",
    "scripts/verify_phase5_grants_r5.py",
    "scripts/verify_phase5_grants_r6.py",
    "tests/test_session_grants_v6.py",
)
ARTIFACT_PATHS = (
    "core/__init__.py",
    "core/session_grants_v6.py",
    *NORMATIVE_NODES,
    V1_ROOT,
    V2_ARTIFACT,
    V2_ROOT,
    V3_ARTIFACT,
    V3_ROOT,
    V4_ARTIFACT,
    V4_ROOT,
    V5_ARTIFACT,
    V5_ROOT,
    CHECKPOINT,
    BUNDLE,
    JUNIT,
    RAW_LOG,
    STATIC_LOG,
    "memory/__init__.py",
    "memory/store.py",
    "scripts/check_phase5_grants_r6_whitespace.py",
    "scripts/verify_phase5_grants_r4.py",
    "scripts/verify_phase5_grants_r5.py",
    "scripts/verify_phase5_grants_r6.py",
    "tests/test_session_grants_v6.py",
)
TOP_PATHS = (ARTIFACT_MANIFEST,)
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_BUNDLE_KEYS = frozenset(
    {"base_commit", "claims", "contract", "counts", "dag", "dependency_closure", "environment", "external_e6", "feature_flag", "files", "history", "limits", "normative_graph", "root_anchor", "static_gates", "status", "timestamp", "whitespace_scope"}
)
_LIMIT_CONSTANTS = {
    "max_approvals": "MAX_APPROVALS",
    "max_bindings": "MAX_BINDINGS",
    "max_cost_micro": "MAX_COST_MICRO",
    "max_effect_length": "MAX_EFFECT_LENGTH",
    "max_grants": "MAX_GRANTS",
    "max_missions": "MAX_MISSIONS",
    "max_monotonic_ms": "MAX_MONOTONIC_MS",
    "max_outcomes": "MAX_OUTCOMES",
    "max_payload_summary_length": "MAX_PAYLOAD_SUMMARY_LENGTH",
    "max_plan_length": "MAX_PLAN_LENGTH",
    "max_policies": "MAX_POLICIES",
    "max_prompt_length": "MAX_PROMPT_LENGTH",
    "max_receipts": "MAX_RECEIPTS",
    "max_reservation_lifetime_ms": "MAX_RESERVATION_LIFETIME_MS",
    "max_reservations": "MAX_RESERVATIONS",
    "max_revocations": "MAX_REVOCATIONS",
    "max_session_lifetime_ms": "MAX_SESSION_LIFETIME_MS",
    "max_target_display_length": "MAX_TARGET_DISPLAY_LENGTH",
    "max_total_payload_summary_chars": "MAX_TOTAL_PAYLOAD_SUMMARY_CHARS",
    "max_total_target_display_chars": "MAX_TOTAL_TARGET_DISPLAY_CHARS",
    "max_uses": "MAX_USES",
}
_CLAIMS = {
    "callbacks_normalized_typed": True,
    "canonical_aliases_rejected": True,
    "credential_and_vault_generation_bound": True,
    "default_off": True,
    "exact_action_bindings_no_cartesian_product": True,
    "first_snapshot_processed_before_resolver": True,
    "idempotency_lifecycle_enforced": True,
    "raw_targets_not_persisted": True,
    "receipt_exact_action_binding": True,
    "receipt_replay_protected": True,
    "shadow_only": True,
    "typed_receipt_verifier_required_for_commit": True,
}
WHITESPACE_SCOPE = list(SOURCE_SEEDS)
LIVE_ENTRYPOINTS = (
    ".github/workflows/release-packages.yml",
    "dashboard/__init__.py",
    "dashboard/server.py",
    "main.py",
    "packaging/linux/onyx.desktop",
    "packaging/macos/entitlements.plist",
    "packaging/onyx.spec",
    "packaging/windows/onyx.iss",
    "ui.py",
)


class Phase5GrantR6EvidenceError(RuntimeError):
    pass


def _path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or "." in pure.parts or ".." in pure.parts:
        raise Phase5GrantR6EvidenceError(f"unsafe evidence path: {relative}")
    return root / Path(*pure.parts)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_manifest(path: Path, expected: tuple[str, ...] | None = None):
    try:
        return r5._parse_manifest(path, expected)
    except Exception as exc:
        raise Phase5GrantR6EvidenceError(str(exc)) from exc


def _verify_entries(root: Path, entries) -> None:
    try:
        r5._verify_entries(root, entries)
    except Exception as exc:
        raise Phase5GrantR6EvidenceError(str(exc)) from exc


def local_import_closure(root: Path, seeds: tuple[str, ...] = SOURCE_SEEDS) -> tuple[str, ...]:
    try:
        return r5.local_import_closure(root, seeds)
    except Exception as exc:
        raise Phase5GrantR6EvidenceError(str(exc)) from exc


def _read_bundle(root: Path) -> dict[str, object]:
    raw = _path(root, BUNDLE).read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Phase5GrantR6EvidenceError("bundle is not valid JSON") from exc
    canonical = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
    if raw != canonical or not isinstance(value, dict) or frozenset(value) != _BUNDLE_KEYS:
        raise Phase5GrantR6EvidenceError("bundle shape/serialization is noncanonical")
    return value


def _junit_counts(root: Path) -> tuple[dict[str, int], str]:
    try:
        document = ET.fromstring(_path(root, JUNIT).read_bytes())
    except (OSError, ET.ParseError) as exc:
        raise Phase5GrantR6EvidenceError("JUnit is invalid") from exc
    suites = [document] if document.tag == "testsuite" else document.findall("testsuite")
    if len(suites) != 1:
        raise Phase5GrantR6EvidenceError("JUnit must contain exactly one suite")
    suite = suites[0]
    cases = suite.findall("testcase")
    if not cases:
        raise Phase5GrantR6EvidenceError("JUnit contains no testcase evidence")
    actual = {"errors": sum(case.find("error") is not None for case in cases), "failed": sum(case.find("failure") is not None for case in cases), "skipped": sum(case.find("skipped") is not None for case in cases)}
    actual["passed"] = len(cases) - actual["errors"] - actual["failed"] - actual["skipped"]
    try:
        declared = {"errors": int(suite.attrib["errors"]), "failed": int(suite.attrib["failures"]), "skipped": int(suite.attrib["skipped"]), "passed": int(suite.attrib["tests"]) - int(suite.attrib["errors"]) - int(suite.attrib["failures"]) - int(suite.attrib["skipped"])}
        timestamp = suite.attrib["timestamp"]
    except (KeyError, TypeError, ValueError) as exc:
        raise Phase5GrantR6EvidenceError("JUnit declarations are invalid") from exc
    if actual != declared:
        raise Phase5GrantR6EvidenceError("JUnit declarations differ from testcase evidence")
    return actual, timestamp


def _junit_case_names(root: Path) -> tuple[str, ...]:
    try:
        document = ET.fromstring(_path(root, JUNIT).read_bytes())
    except (OSError, ET.ParseError) as exc:
        raise Phase5GrantR6EvidenceError("JUnit is invalid") from exc
    suites = [document] if document.tag == "testsuite" else document.findall("testsuite")
    names = tuple(case.attrib.get("name", "") for suite in suites for case in suite.findall("testcase"))
    if not names or any(not name for name in names) or len(names) != len(set(names)):
        raise Phase5GrantR6EvidenceError("JUnit testcase names are missing or duplicated")
    return names


def _validate_test_evidence(root: Path) -> None:
    names = _junit_case_names(root)
    required = {
        "test_concurrent_duplicate_outcome_commits_exactly_once",
        "test_concurrent_same_idempotency_reservation_has_single_winner",
        "test_default_off_is_inert_and_opaque",
        "test_duplicate_provider_receipt_identity_is_rejected_by_lifetime_high_water",
        "test_idempotency_releases_on_cancel_and_consumes_only_after_verified_commit",
        "test_outcome_status_alone_never_commits_without_typed_receipt_verifier",
        "test_receipt_high_water_survives_bounded_cleanup",
        "test_receipt_challenges_are_distinct_nonreserved_and_not_host_selected",
        "test_receipt_replay_cannot_commit_distinct_reservation",
        "test_receipt_verifier_exception_is_typed_and_fail_closed",
        "test_receipt_verifier_requires_exact_concrete_type",
        "test_r6_canonicalization_accepts_uppercase_allowed_percent_escape",
        "test_store_and_prompt_never_retain_raw_secret_target",
        "test_unverified_receipt_releases_idempotency_for_retry",
    }
    missing = required - set(names)
    if missing:
        raise Phase5GrantR6EvidenceError(f"required semantic JUnit cases are missing: {sorted(missing)}")
    required_prefix_counts = {
        "test_concurrent_commit_vs_terminal_control_is_atomic[": 4,
        "test_credential_rotation_invalidates_permanently[": 2,
        "test_r6_canonicalization_rejects_posix_double_slash_and_percent_aliases[": 5,
        "test_receipt_verification_binds_every_exact_echo[": 10,
        "test_reserved_digest_rejected_at_receipt_and_action_boundaries[": 2,
    }
    for prefix, expected in required_prefix_counts.items():
        if sum(name.startswith(prefix) for name in names) != expected:
            raise Phase5GrantR6EvidenceError(f"required parametrized JUnit evidence differs: {prefix}")


def _kv_log(root: Path, relative: str) -> dict[str, str]:
    raw = _path(root, relative).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase5GrantR6EvidenceError(f"log is noncanonical: {relative}")
    values: dict[str, str] = {}
    for line in raw.decode().splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise Phase5GrantR6EvidenceError(f"log line is invalid: {relative}")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key) or key in values:
            raise Phase5GrantR6EvidenceError(f"log key is invalid: {relative}")
        values[key] = value
    return values


def _constants(root: Path) -> dict[str, int]:
    tree = ast.parse(_path(root, "core/session_grants_v6.py").read_text(encoding="utf-8"))
    found: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in _LIMIT_CONSTANTS.values():
            name = node.targets[0].id
            try:
                value = ast.literal_eval(node.value)
            except (TypeError, ValueError) as exc:
                raise Phase5GrantR6EvidenceError(f"limit is not literal: {name}") from exc
            if type(value) is not int:
                raise Phase5GrantR6EvidenceError(f"limit is invalid: {name}")
            found[name] = value
    if set(found) != set(_LIMIT_CONSTANTS.values()):
        raise Phase5GrantR6EvidenceError("material limit set is incomplete")
    return {key: found[name] for key, name in _LIMIT_CONSTANTS.items()}


def _class_fields(tree: ast.Module, name: str) -> set[str]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return {item.target.id for item in node.body if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)}
    return set()


def _validate_code_claims(root: Path) -> None:
    tree = ast.parse(_path(root, "core/session_grants_v6.py").read_text(encoding="utf-8"))
    binding = {"target_identity", "target_display", "payload_digest", "payload_summary", "payload_rule_id", "egress", "idempotency_key"}
    if binding != _class_fields(tree, "ActionBinding"):
        raise Phase5GrantR6EvidenceError("exact action binding claim differs from code")
    scope_fields = _class_fields(tree, "ResolvedGrantScope")
    if "bindings" not in scope_fields or {"targets", "payloads"} & scope_fields:
        raise Phase5GrantR6EvidenceError("no-Cartesian-product claim differs from code")
    if not {"credential_epoch", "vault_generation"} <= _class_fields(tree, "HostState"):
        raise Phase5GrantR6EvidenceError("credential generation claim differs from code")
    if _class_fields(tree, "ResolvedOutcome") != {"reservation_id", "status", "result_digest", "provider_receipt_id", "receipt_digest"}:
        raise Phase5GrantR6EvidenceError("outcome claim differs from exact type")
    request_fields = {"receipt_challenge", "reservation_id", "grant_id", "scope_digest", "binding_digest", "action_audit_digest", "idempotency_key", "provider_receipt_id", "result_digest", "receipt_digest"}
    if _class_fields(tree, "ReceiptVerificationRequest") != request_fields:
        raise Phase5GrantR6EvidenceError("receipt request binding is incomplete")
    verification_fields = request_fields | {"verified", "receipt_sequence", "receipt_id", "verification_digest"}
    if _class_fields(tree, "HostReceiptVerification") != verification_fields:
        raise Phase5GrantR6EvidenceError("receipt verification binding is incomplete")
    reservation_fields = request_fields - {"provider_receipt_id", "result_digest", "receipt_digest", "reservation_id"}
    reservation_fields |= {"reservation_id", "cost_micro", "state_fingerprint", "created_at_ms", "expires_at_ms", "sequence"}
    if _class_fields(tree, "ActionReservation") != reservation_fields:
        raise Phase5GrantR6EvidenceError("reservation binding is incomplete")
    if "verify_receipt" not in _class_fields(tree, "HostServices"):
        raise Phase5GrantR6EvidenceError("pinned receipt verifier service is missing")
    record = next(
        (
            item
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "SessionGrantShadowStore"
            for item in node.body
            if isinstance(item, ast.FunctionDef) and item.name == "record_outcome"
        ),
        None,
    )
    if record is None:
        raise Phase5GrantR6EvidenceError("record_outcome is missing")
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(record)
        if isinstance(node, ast.Call) and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    required_calls = {"_call_receipt_verifier", "canonical_receipt_digest", "canonical_verification_digest", "compare_digest", "_release_reservation_locked"}
    if not required_calls <= calls:
        raise Phase5GrantR6EvidenceError("receipt commit path omits a required semantic operation")
    module_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    required_names = {"_RESERVED_DIGESTS", "_UNRESERVED", "_last_receipt_sequence", "_reserved_idempotency", "_consumed_idempotency"}
    if not required_names <= module_names | {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}:
        raise Phase5GrantR6EvidenceError("R6 replay/idempotency/canonicalization state is incomplete")


NORMATIVE_SEEDS = tuple(item for item in NORMATIVE_NODES if "/adrs/" not in item and item != "docs/MISSIONS.md")
_MARKDOWN_REFERENCE = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_./-]+\.md)(?=$|[#)`\]\s,:;])")


def _markdown_references(root: Path, relative: str) -> set[str]:
    references: set[str] = set()
    text = _path(root, relative).read_text(encoding="utf-8")
    for raw in _MARKDOWN_REFERENCE.findall(text):
        candidate = PurePosixPath(raw) if raw.startswith(("docs/", "plans/")) else PurePosixPath(relative).parent / PurePosixPath(raw)
        parts: list[str] = []
        for part in candidate.parts:
            if part == ".":
                continue
            if part == "..":
                if not parts:
                    continue
                parts.pop()
            else:
                parts.append(part)
        resolved = "/".join(parts)
        if resolved.startswith(("docs/", "plans/")) and _path(root, resolved).is_file():
            references.add(resolved)
    return references


def derive_normative_graph(root: Path, nodes: tuple[str, ...] = NORMATIVE_NODES) -> dict[str, list[str]]:
    discovered = set(NORMATIVE_SEEDS)
    queue = list(NORMATIVE_SEEDS)
    graph: dict[str, list[str]] = {}
    while queue:
        relative = queue.pop(0)
        if not _path(root, relative).is_file():
            raise Phase5GrantR6EvidenceError(f"normative node missing: {relative}")
        references = set() if not relative.endswith(".md") else _markdown_references(root, relative)
        graph[relative] = sorted(references - {relative})
        for reference in sorted(references):
            if reference not in discovered:
                discovered.add(reference)
                queue.append(reference)
    if discovered != set(nodes):
        raise Phase5GrantR6EvidenceError(f"recursive normative set differs: missing={sorted(discovered - set(nodes))} extra={sorted(set(nodes) - discovered)}")
    return {relative: graph[relative] for relative in nodes}


def _run_history(root: Path) -> dict[str, object]:
    try:
        history = r5._run_history(root)
    except Exception as exc:
        raise Phase5GrantR6EvidenceError("V1-R4 historical reconstruction failed") from exc
    v5_top = _parse_manifest(_path(root, V5_ROOT), (V5_ARTIFACT,))
    v5_artifacts = _parse_manifest(_path(root, V5_ARTIFACT))
    _verify_entries(root, v5_top + v5_artifacts)
    try:
        result = r5.verify_evidence(root, current_base_commit=_current_commit(root), current_environment=_environment())
    except Exception as exc:
        raise Phase5GrantR6EvidenceError("V5 historical verifier failed") from exc
    if result != {
        "artifact_files": 32,
        "artifact_manifest_sha256": _sha(_path(root, V5_ARTIFACT)),
        "dependencies": 8,
        "normative": 12,
        "root_files": 1,
        "root_manifest_sha256": _sha(_path(root, V5_ROOT)),
        "tests": 68,
    }:
        raise Phase5GrantR6EvidenceError("V5 historical result is incomplete")
    history["v5"] = {"artifact_manifest": V5_ARTIFACT, "artifact_sha256": _sha(_path(root, V5_ARTIFACT)), "artifacts": len(v5_artifacts), "root": V5_ROOT, "root_sha256": _sha(_path(root, V5_ROOT))}
    return history


def _current_commit(root: Path) -> str:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False)
    value = result.stdout.strip().casefold()
    if result.returncode or not _HEX40.fullmatch(value):
        raise Phase5GrantR6EvidenceError("current git base commit is unavailable")
    return value


def _environment() -> dict[str, str]:
    return {"executable": str(Path(sys.executable).resolve()), "platform": platform.platform(), "pytest": pytest.__version__, "python": sys.version.split()[0]}


def _run_static_gates(root: Path) -> dict[str, object]:
    for relative in WHITESPACE_SCOPE:
        try:
            source = _path(root, relative).read_text(encoding="utf-8")
            compile(source, relative, "exec", dont_inherit=True)
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise Phase5GrantR6EvidenceError(f"live compile gate failed: {relative}") from exc
    ruff_candidates = (
        root / ".venv" / "Scripts" / "ruff.exe",
        root / ".venv" / "bin" / "ruff",
    )
    ruff = next((str(path) for path in ruff_candidates if path.is_file()), shutil.which("ruff"))
    if not ruff:
        raise Phase5GrantR6EvidenceError("live Ruff gate is unavailable")
    ruff_result = subprocess.run(
        [ruff, "check", "--no-cache", "--select", "F,E9", *WHITESPACE_SCOPE],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if ruff_result.returncode:
        raise Phase5GrantR6EvidenceError(f"live Ruff gate failed: {ruff_result.stdout}{ruff_result.stderr}")
    whitespace = subprocess.run(
        [sys.executable, str(_path(root, "scripts/check_phase5_grants_r6_whitespace.py"))],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    if whitespace.returncode or whitespace.stdout.strip() != "P51_GRANTS_R6_WHITESPACE_OK files=4":
        raise Phase5GrantR6EvidenceError("live whitespace gate failed")
    forbidden = ("session_grants_v6", "SessionGrantShadowStore")
    for relative in LIVE_ENTRYPOINTS:
        path = _path(root, relative)
        if not path.is_file():
            raise Phase5GrantR6EvidenceError(f"authoritative live entrypoint is missing: {relative}")
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in forbidden):
            raise Phase5GrantR6EvidenceError(f"R6 is wired into live entrypoint: {relative}")
    return {
        "compile": 0,
        "live_entrypoint_scan": 0,
        "live_entrypoints": list(LIVE_ENTRYPOINTS),
        "ruff_f_e9": 0,
        "whitespace": 0,
    }


def _require_equal(claim: object, actual: object, label: str) -> None:
    if claim != actual:
        raise Phase5GrantR6EvidenceError(f"{label} binding is false or incomplete")


def verify_evidence(root: Path = PROJECT, *, current_base_commit: str | None = None, current_environment: dict[str, str] | None = None) -> dict[str, object]:
    root = root.resolve()
    top = _parse_manifest(_path(root, TOP_MANIFEST), TOP_PATHS)
    _verify_entries(root, top)
    artifacts = _parse_manifest(_path(root, ARTIFACT_MANIFEST), ARTIFACT_PATHS)
    _verify_entries(root, artifacts)
    bundle = _read_bundle(root)
    if bundle.get("contract") != "Phase5SessionGrantShadowEvidence.v6" or bundle.get("status") != "candidate-default-off-not-accepted":
        raise Phase5GrantR6EvidenceError("bundle contract/status is invalid")
    _require_equal(bundle.get("claims"), _CLAIMS, "semantic claims")
    _validate_code_claims(root)
    _require_equal(bundle.get("feature_flag"), {"default": False, "name": "ONYX_GRANT_EVALUATOR"}, "feature flag")
    _require_equal(bundle.get("external_e6"), {"accepted": False, "required_before_acceptance": True, "status": "pending-external-review"}, "external E6 status")
    _require_equal(bundle.get("root_anchor"), {"externally_anchored": False, "required_before_acceptance": True}, "root anchor")
    _require_equal(bundle.get("dag"), {"artifact_points_to": list(ARTIFACT_PATHS), "bundle_excludes_manifest_and_self_hashes": True, "root": TOP_MANIFEST, "root_points_to": [ARTIFACT_MANIFEST]}, "evidence DAG")
    leaf_paths = tuple(path for path in ARTIFACT_PATHS if path != BUNDLE)
    files = bundle.get("files")
    if not isinstance(files, dict) or tuple(sorted(files)) != tuple(sorted(leaf_paths)):
        raise Phase5GrantR6EvidenceError("bundle leaf set is not exact")
    for relative, digest in files.items():
        if type(digest) is not str or not _HEX64.fullmatch(digest) or _sha(_path(root, relative)) != digest:
            raise Phase5GrantR6EvidenceError(f"bundle leaf hash mismatch: {relative}")
    closure = local_import_closure(root)
    _require_equal(closure, DECLARED_LOCAL_CLOSURE, "declared dependency closure")
    _require_equal(bundle.get("dependency_closure"), list(closure), "bundle dependency closure")
    graph = derive_normative_graph(root)
    _require_equal(graph, NORMATIVE_GRAPH, "actual normative graph")
    _require_equal(bundle.get("normative_graph"), graph, "bundle normative graph")
    history = _run_history(root)
    _require_equal(bundle.get("history"), history, "historical evidence")
    counts, junit_timestamp = _junit_counts(root)
    _validate_test_evidence(root)
    _require_equal(bundle.get("counts"), counts, "JUnit counts")
    if counts["failed"] or counts["errors"]:
        raise Phase5GrantR6EvidenceError("focused suite is not green")
    raw = _kv_log(root, RAW_LOG)
    if raw.get("timestamp") != junit_timestamp or raw.get("exit_code") != "0" or raw.get("result") != f"{counts['passed']} passed" or any(raw.get(key) != str(counts[key]) for key in ("passed", "failed", "errors", "skipped")):
        raise Phase5GrantR6EvidenceError("raw/JUnit evidence differs")
    static = _kv_log(root, STATIC_LOG)
    expected_static = {
        "compile_mode": "in-memory-built-in-compile",
        "compile_exit_code": "0",
        "diff_check_command": "python scripts/check_phase5_grants_r6_whitespace.py",
        "diff_check_exit_code": "0",
        "diff_check_scope": ";".join(WHITESPACE_SCOPE),
        "live_entrypoint_scan_exit_code": "0",
        "live_entrypoint_scan_scope": ";".join(LIVE_ENTRYPOINTS),
        "ruff_command": "ruff check --no-cache --select F,E9",
        "ruff_exit_code": "0",
        "v1_historical_files": "10",
        "v2_evidence_artifacts": "8",
        "v2_evidence_root": "1",
        "v3_evidence_artifacts": "11",
        "v3_evidence_root": "1",
        "v4_evidence_artifacts": "20",
        "v4_evidence_root": "1",
        "v5_evidence_artifacts": "32",
        "v5_evidence_root": "1",
    }
    if static != expected_static:
        raise Phase5GrantR6EvidenceError("static/log scope evidence is false")
    live_static = _run_static_gates(root)
    _require_equal(bundle.get("static_gates"), live_static, "live static gates")
    _require_equal(bundle.get("whitespace_scope"), WHITESPACE_SCOPE, "whitespace scope")
    _require_equal(bundle.get("limits"), _constants(root), "code limits")
    base = current_base_commit or _current_commit(root)
    if not _HEX40.fullmatch(base) or bundle.get("base_commit") != base:
        raise Phase5GrantR6EvidenceError("bundle base commit is invalid or stale")
    _require_equal(bundle.get("environment"), current_environment or _environment(), "runtime environment")
    timestamp = bundle.get("timestamp")
    if type(timestamp) is not str or timestamp != junit_timestamp:
        raise Phase5GrantR6EvidenceError("bundle timestamp differs from JUnit")
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise Phase5GrantR6EvidenceError("bundle timestamp is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Phase5GrantR6EvidenceError("bundle timestamp lacks timezone")
    return {"artifact_files": len(artifacts), "artifact_manifest_sha256": _sha(_path(root, ARTIFACT_MANIFEST)), "dependencies": len(closure), "normative": len(graph), "root_files": len(top), "root_manifest_sha256": _sha(_path(root, TOP_MANIFEST)), "tests": counts["passed"]}


def main() -> int:
    result = verify_evidence()
    print(f"P51_GRANTS_R6_EVIDENCE_OK root={result['root_files']} artifacts={result['artifact_files']} dependencies={result['dependencies']} normative={result['normative']} tests={result['tests']} root_sha256={result['root_manifest_sha256']} artifact_sha256={result['artifact_manifest_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
