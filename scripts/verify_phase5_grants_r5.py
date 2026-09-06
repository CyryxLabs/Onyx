"""Semantic and byte-exact verifier for the Phase 5.1 R5 evidence DAG."""

from __future__ import annotations

import ast
import hashlib
import json
import platform
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path, PurePosixPath

import pytest

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts import verify_phase5_grants_r4 as r4


TOP_MANIFEST = "docs/onyx/VE-SOURCE-P51-GRANTS-R5-001.sha256"
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P51-GRANTS-R5-001.sha256"
BUNDLE = "docs/onyx/checkpoints/phase5-grants-r5/phase5-grants-r5.bundle.json"
JUNIT = "docs/onyx/checkpoints/phase5-grants-r5/phase5-grants-r5.junit.xml"
RAW_LOG = "docs/onyx/checkpoints/phase5-grants-r5/phase5-grants-r5.raw.log"
STATIC_LOG = "docs/onyx/checkpoints/phase5-grants-r5/phase5-grants-r5.static.log"
CHECKPOINT = "docs/onyx/checkpoints/phase5-grants-r5/PHASE5_1_GRANTS_SHADOW_R5_CHECKPOINT.md"
V1_ROOT = r4.V1_ROOT
V2_ROOT = r4.V2_ROOT
V2_ARTIFACT = r4.V2_ARTIFACT
V3_ROOT = r4.V3_ROOT
V3_ARTIFACT = r4.V3_ARTIFACT
V4_ROOT = "docs/onyx/VE-SOURCE-P51-GRANTS-R4-001.sha256"
V4_ARTIFACT = "docs/onyx/VE-ARTIFACTS-P51-GRANTS-R4-001.sha256"

NORMATIVE_NODES = (
    "core/workspaces.py",
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
    "plans/onyx-advanced-entity-redesign.md",
)
NORMATIVE_GRAPH = {
    "core/workspaces.py": [],
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
        "plans/onyx-advanced-entity-redesign.md",
    ],
    "docs/onyx/OPEN_SOURCE_AND_API_LICENSE_REVIEW.md": [],
    "docs/onyx/TARGET_ARCHITECTURE.md": ["docs/onyx/APPROVAL_POLICY.md"],
    "docs/onyx/THREAT_MODEL.md": ["docs/onyx/APPROVAL_POLICY.md"],
    "docs/onyx/VERIFICATION_EVIDENCE.md": ["docs/onyx/CAPABILITY_MATRIX.md"],
    "plans/onyx-advanced-entity-redesign.md": [
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
    "core/session_grants_v5.py",
    "scripts/check_phase5_grants_r5_whitespace.py",
    "scripts/verify_phase5_grants_r5.py",
    "tests/test_session_grants_v5.py",
)
DECLARED_LOCAL_CLOSURE = (
    "core/__init__.py",
    "core/session_grants_v5.py",
    "memory/__init__.py",
    "memory/store.py",
    "scripts/check_phase5_grants_r5_whitespace.py",
    "scripts/verify_phase5_grants_r4.py",
    "scripts/verify_phase5_grants_r5.py",
    "tests/test_session_grants_v5.py",
)
ARTIFACT_PATHS = (
    "core/__init__.py",
    "core/session_grants_v5.py",
    *NORMATIVE_NODES,
    V1_ROOT,
    V2_ARTIFACT,
    V2_ROOT,
    V3_ARTIFACT,
    V3_ROOT,
    V4_ARTIFACT,
    V4_ROOT,
    CHECKPOINT,
    BUNDLE,
    JUNIT,
    RAW_LOG,
    STATIC_LOG,
    "memory/__init__.py",
    "memory/store.py",
    "scripts/check_phase5_grants_r5_whitespace.py",
    "scripts/verify_phase5_grants_r4.py",
    "scripts/verify_phase5_grants_r5.py",
    "tests/test_session_grants_v5.py",
)
TOP_PATHS = (ARTIFACT_MANIFEST,)
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_BUNDLE_KEYS = frozenset(
    {"base_commit", "claims", "contract", "counts", "dag", "dependency_closure", "environment", "feature_flag", "files", "history", "limits", "normative_graph", "root_anchor", "status", "timestamp", "whitespace_scope"}
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
    "credential_and_vault_generation_bound": True,
    "default_off": True,
    "exact_action_bindings_no_cartesian_product": True,
    "first_snapshot_processed_before_resolver": True,
    "raw_targets_not_persisted": True,
    "shadow_only": True,
    "two_phase_verified_receipt_commit": True,
}
WHITESPACE_SCOPE = list(SOURCE_SEEDS)


class Phase5GrantR5EvidenceError(RuntimeError):
    pass


def _path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or "." in pure.parts or ".." in pure.parts:
        raise Phase5GrantR5EvidenceError(f"unsafe evidence path: {relative}")
    return root / Path(*pure.parts)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_manifest(path: Path, expected: tuple[str, ...] | None = None):
    try:
        return r4._parse_manifest(path, expected)
    except Exception as exc:
        raise Phase5GrantR5EvidenceError(str(exc)) from exc


def _verify_entries(root: Path, entries) -> None:
    try:
        r4._verify_entries(root, entries)
    except Exception as exc:
        raise Phase5GrantR5EvidenceError(str(exc)) from exc


def local_import_closure(root: Path, seeds: tuple[str, ...] = SOURCE_SEEDS) -> tuple[str, ...]:
    try:
        return r4.local_import_closure(root, seeds)
    except Exception as exc:
        raise Phase5GrantR5EvidenceError(str(exc)) from exc


def _read_bundle(root: Path) -> dict[str, object]:
    raw = _path(root, BUNDLE).read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Phase5GrantR5EvidenceError("bundle is not valid JSON") from exc
    canonical = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
    if raw != canonical or not isinstance(value, dict) or frozenset(value) != _BUNDLE_KEYS:
        raise Phase5GrantR5EvidenceError("bundle shape/serialization is noncanonical")
    return value


def _junit_counts(root: Path) -> tuple[dict[str, int], str]:
    try:
        document = ET.fromstring(_path(root, JUNIT).read_bytes())
    except (OSError, ET.ParseError) as exc:
        raise Phase5GrantR5EvidenceError("JUnit is invalid") from exc
    suites = [document] if document.tag == "testsuite" else document.findall("testsuite")
    if len(suites) != 1:
        raise Phase5GrantR5EvidenceError("JUnit must contain exactly one suite")
    suite = suites[0]
    cases = suite.findall("testcase")
    if not cases:
        raise Phase5GrantR5EvidenceError("JUnit contains no testcase evidence")
    actual = {"errors": sum(case.find("error") is not None for case in cases), "failed": sum(case.find("failure") is not None for case in cases), "skipped": sum(case.find("skipped") is not None for case in cases)}
    actual["passed"] = len(cases) - actual["errors"] - actual["failed"] - actual["skipped"]
    try:
        declared = {"errors": int(suite.attrib["errors"]), "failed": int(suite.attrib["failures"]), "skipped": int(suite.attrib["skipped"]), "passed": int(suite.attrib["tests"]) - int(suite.attrib["errors"]) - int(suite.attrib["failures"]) - int(suite.attrib["skipped"])}
        timestamp = suite.attrib["timestamp"]
    except (KeyError, TypeError, ValueError) as exc:
        raise Phase5GrantR5EvidenceError("JUnit declarations are invalid") from exc
    if actual != declared:
        raise Phase5GrantR5EvidenceError("JUnit declarations differ from testcase evidence")
    return actual, timestamp


def _kv_log(root: Path, relative: str) -> dict[str, str]:
    raw = _path(root, relative).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase5GrantR5EvidenceError(f"log is noncanonical: {relative}")
    values: dict[str, str] = {}
    for line in raw.decode().splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise Phase5GrantR5EvidenceError(f"log line is invalid: {relative}")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key) or key in values:
            raise Phase5GrantR5EvidenceError(f"log key is invalid: {relative}")
        values[key] = value
    return values


def _constants(root: Path) -> dict[str, int]:
    tree = ast.parse(_path(root, "core/session_grants_v5.py").read_text(encoding="utf-8"))
    found: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in _LIMIT_CONSTANTS.values():
            name = node.targets[0].id
            try:
                value = ast.literal_eval(node.value)
            except (TypeError, ValueError) as exc:
                raise Phase5GrantR5EvidenceError(f"limit is not literal: {name}") from exc
            if type(value) is not int:
                raise Phase5GrantR5EvidenceError(f"limit is invalid: {name}")
            found[name] = value
    if set(found) != set(_LIMIT_CONSTANTS.values()):
        raise Phase5GrantR5EvidenceError("material limit set is incomplete")
    return {key: found[name] for key, name in _LIMIT_CONSTANTS.items()}


def _class_fields(tree: ast.Module, name: str) -> set[str]:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return {item.target.id for item in node.body if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)}
    return set()


def _validate_code_claims(root: Path) -> None:
    source = _path(root, "core/session_grants_v5.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    binding = {"target_identity", "target_display", "payload_digest", "payload_summary", "payload_rule_id", "egress", "idempotency_key"}
    if binding != _class_fields(tree, "ActionBinding"):
        raise Phase5GrantR5EvidenceError("exact action binding claim differs from code")
    scope_fields = _class_fields(tree, "ResolvedGrantScope")
    if "bindings" not in scope_fields or {"targets", "payloads"} & scope_fields:
        raise Phase5GrantR5EvidenceError("no-Cartesian-product claim differs from code")
    if not {"credential_epoch", "vault_generation"} <= _class_fields(tree, "HostState"):
        raise Phase5GrantR5EvidenceError("credential generation claim differs from code")
    if not {"reservation_id", "status", "callback_approved", "dispatched", "receipt_verified", "receipt_digest"} <= _class_fields(tree, "ResolvedOutcome"):
        raise Phase5GrantR5EvidenceError("verified outcome claim differs from code")
    required = ("def evaluate(", "def reserve(", "def record_outcome(", "_pre_snapshot()", "_checked_expiry", "self._approvals: set[str]", "raw URI backslash", "self._reservations.clear()")
    if any(marker not in source for marker in required):
        raise Phase5GrantR5EvidenceError("R5 semantic claim differs from code")


_FULL_REFERENCE = re.compile(r"`((?:docs/onyx|plans)/[A-Za-z0-9_-]+\.md)`")
_BARE_REFERENCE = re.compile(r"`([A-Z][A-Z0-9_]+\.md)`")


def derive_normative_graph(root: Path, nodes: tuple[str, ...] = NORMATIVE_NODES) -> dict[str, list[str]]:
    allowed = set(nodes)
    graph: dict[str, list[str]] = {}
    for relative in nodes:
        if not _path(root, relative).is_file():
            raise Phase5GrantR5EvidenceError(f"normative node missing: {relative}")
        if not relative.endswith(".md"):
            graph[relative] = []
            continue
        text = _path(root, relative).read_text(encoding="utf-8")
        references = set(_FULL_REFERENCE.findall(text))
        references.update(f"docs/onyx/{name}" for name in _BARE_REFERENCE.findall(text))
        material = {item for item in references if _path(root, item).is_file()}
        omitted = material - allowed
        if omitted:
            raise Phase5GrantR5EvidenceError(f"explicit normative parent omitted: {sorted(omitted)}")
        graph[relative] = sorted(material - {relative})
    return graph


def _run_history(root: Path) -> dict[str, object]:
    try:
        history = r4._history(root)
    except Exception as exc:
        raise Phase5GrantR5EvidenceError("V1-R3 historical reconstruction failed") from exc
    v4_top = _parse_manifest(_path(root, V4_ROOT), (V4_ARTIFACT,))
    v4_artifacts = _parse_manifest(_path(root, V4_ARTIFACT))
    _verify_entries(root, v4_top + v4_artifacts)
    result = subprocess.run([sys.executable, str(_path(root, "scripts/verify_phase5_grants_r4.py"))], cwd=root, capture_output=True, text=True, timeout=60, check=False)
    marker = "P51_GRANTS_R4_EVIDENCE_OK root=1 artifacts=20 dependencies=6 normative=4 tests=64"
    if result.returncode or marker not in result.stdout:
        raise Phase5GrantR5EvidenceError("R4 historical verifier failed")
    history["v4"] = {"artifact_manifest": V4_ARTIFACT, "artifact_sha256": _sha(_path(root, V4_ARTIFACT)), "artifacts": len(v4_artifacts), "root": V4_ROOT, "root_sha256": _sha(_path(root, V4_ROOT))}
    return history


def _current_commit(root: Path) -> str:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False)
    value = result.stdout.strip().casefold()
    if result.returncode or not _HEX40.fullmatch(value):
        raise Phase5GrantR5EvidenceError("current git base commit is unavailable")
    return value


def _environment() -> dict[str, str]:
    return {"executable": str(Path(sys.executable).resolve()), "platform": platform.platform(), "pytest": pytest.__version__, "python": sys.version.split()[0]}


def _require_equal(claim: object, actual: object, label: str) -> None:
    if claim != actual:
        raise Phase5GrantR5EvidenceError(f"{label} binding is false or incomplete")


def verify_evidence(root: Path = PROJECT, *, current_base_commit: str | None = None, current_environment: dict[str, str] | None = None) -> dict[str, object]:
    root = root.resolve()
    top = _parse_manifest(_path(root, TOP_MANIFEST), TOP_PATHS)
    _verify_entries(root, top)
    artifacts = _parse_manifest(_path(root, ARTIFACT_MANIFEST), ARTIFACT_PATHS)
    _verify_entries(root, artifacts)
    bundle = _read_bundle(root)
    if bundle.get("contract") != "Phase5SessionGrantShadowEvidence.v5" or bundle.get("status") != "candidate-default-off-not-accepted":
        raise Phase5GrantR5EvidenceError("bundle contract/status is invalid")
    _require_equal(bundle.get("claims"), _CLAIMS, "semantic claims")
    _validate_code_claims(root)
    _require_equal(bundle.get("feature_flag"), {"default": False, "name": "ONYX_GRANT_EVALUATOR"}, "feature flag")
    _require_equal(bundle.get("root_anchor"), {"externally_anchored": False, "required_before_acceptance": True}, "root anchor")
    _require_equal(bundle.get("dag"), {"artifact_points_to": list(ARTIFACT_PATHS), "bundle_excludes_manifest_and_self_hashes": True, "root": TOP_MANIFEST, "root_points_to": [ARTIFACT_MANIFEST]}, "evidence DAG")
    leaf_paths = tuple(path for path in ARTIFACT_PATHS if path != BUNDLE)
    files = bundle.get("files")
    if not isinstance(files, dict) or tuple(sorted(files)) != tuple(sorted(leaf_paths)):
        raise Phase5GrantR5EvidenceError("bundle leaf set is not exact")
    for relative, digest in files.items():
        if type(digest) is not str or not _HEX64.fullmatch(digest) or _sha(_path(root, relative)) != digest:
            raise Phase5GrantR5EvidenceError(f"bundle leaf hash mismatch: {relative}")
    closure = local_import_closure(root)
    _require_equal(closure, DECLARED_LOCAL_CLOSURE, "declared dependency closure")
    _require_equal(bundle.get("dependency_closure"), list(closure), "bundle dependency closure")
    graph = derive_normative_graph(root)
    _require_equal(graph, NORMATIVE_GRAPH, "actual normative graph")
    _require_equal(bundle.get("normative_graph"), graph, "bundle normative graph")
    history = _run_history(root)
    _require_equal(bundle.get("history"), history, "historical evidence")
    counts, junit_timestamp = _junit_counts(root)
    _require_equal(bundle.get("counts"), counts, "JUnit counts")
    if counts["failed"] or counts["errors"]:
        raise Phase5GrantR5EvidenceError("focused suite is not green")
    raw = _kv_log(root, RAW_LOG)
    if raw.get("timestamp") != junit_timestamp or raw.get("exit_code") != "0" or raw.get("result") != f"{counts['passed']} passed" or any(raw.get(key) != str(counts[key]) for key in ("passed", "failed", "errors", "skipped")):
        raise Phase5GrantR5EvidenceError("raw/JUnit evidence differs")
    static = _kv_log(root, STATIC_LOG)
    expected_static = {"diff_check_command": "python scripts/check_phase5_grants_r5_whitespace.py", "diff_check_exit_code": "0", "diff_check_scope": ";".join(WHITESPACE_SCOPE), "py_compile_exit_code": "0", "ruff_exit_code": "0", "v1_historical_files": "10", "v2_evidence_artifacts": "8", "v2_evidence_root": "1", "v3_evidence_artifacts": "11", "v3_evidence_root": "1", "v4_evidence_artifacts": "20", "v4_evidence_root": "1"}
    if any(static.get(key) != value for key, value in expected_static.items()):
        raise Phase5GrantR5EvidenceError("static/log scope evidence is false")
    _require_equal(bundle.get("whitespace_scope"), WHITESPACE_SCOPE, "whitespace scope")
    _require_equal(bundle.get("limits"), _constants(root), "code limits")
    base = current_base_commit or _current_commit(root)
    if not _HEX40.fullmatch(base) or bundle.get("base_commit") != base:
        raise Phase5GrantR5EvidenceError("bundle base commit is invalid or stale")
    _require_equal(bundle.get("environment"), current_environment or _environment(), "runtime environment")
    timestamp = bundle.get("timestamp")
    if type(timestamp) is not str or timestamp != junit_timestamp:
        raise Phase5GrantR5EvidenceError("bundle timestamp differs from JUnit")
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise Phase5GrantR5EvidenceError("bundle timestamp is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Phase5GrantR5EvidenceError("bundle timestamp lacks timezone")
    return {"artifact_files": len(artifacts), "artifact_manifest_sha256": _sha(_path(root, ARTIFACT_MANIFEST)), "dependencies": len(closure), "normative": len(graph), "root_files": len(top), "root_manifest_sha256": _sha(_path(root, TOP_MANIFEST)), "tests": counts["passed"]}


def main() -> int:
    result = verify_evidence()
    print(f"P51_GRANTS_R5_EVIDENCE_OK root={result['root_files']} artifacts={result['artifact_files']} dependencies={result['dependencies']} normative={result['normative']} tests={result['tests']} root_sha256={result['root_manifest_sha256']} artifact_sha256={result['artifact_manifest_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
