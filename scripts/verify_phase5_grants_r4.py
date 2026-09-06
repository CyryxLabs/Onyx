"""Semantic and byte-exact verifier for the Phase 5.1 R4 evidence DAG."""

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
TOP_MANIFEST = "docs/onyx/VE-SOURCE-P51-GRANTS-R4-001.sha256"
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P51-GRANTS-R4-001.sha256"
BUNDLE = "docs/onyx/checkpoints/phase5-grants-r4/phase5-grants-r4.bundle.json"
JUNIT = "docs/onyx/checkpoints/phase5-grants-r4/phase5-grants-r4.junit.xml"
RAW_LOG = "docs/onyx/checkpoints/phase5-grants-r4/phase5-grants-r4.raw.log"
STATIC_LOG = "docs/onyx/checkpoints/phase5-grants-r4/phase5-grants-r4.static.log"
CHECKPOINT = "docs/onyx/checkpoints/phase5-grants-r4/PHASE5_1_GRANTS_SHADOW_R4_CHECKPOINT.md"

V1_ROOT = "docs/onyx/VE-SCOPE-P51-GRANTS-V1-001.sha256"
V2_ROOT = "docs/onyx/VE-SOURCE-P51-GRANTS-R2-001.sha256"
V2_ARTIFACT = "docs/onyx/VE-ARTIFACTS-P51-GRANTS-R2-001.sha256"
V3_ROOT = "docs/onyx/VE-SOURCE-P51-GRANTS-R3-001.sha256"
V3_ARTIFACT = "docs/onyx/VE-ARTIFACTS-P51-GRANTS-R3-001.sha256"
NORMATIVE_DEPENDENCIES = (
    "core/workspaces.py",
    "docs/onyx/APPROVAL_POLICY.md",
    "docs/onyx/IMPLEMENTATION_ROADMAP.md",
    "docs/onyx/TARGET_ARCHITECTURE.md",
)
SOURCE_SEEDS = (
    "core/session_grants_v4.py",
    "scripts/verify_phase5_grants_r4.py",
    "tests/test_session_grants_v4.py",
)
DECLARED_LOCAL_CLOSURE = (
    "core/__init__.py",
    "core/session_grants_v4.py",
    "memory/__init__.py",
    "memory/store.py",
    "scripts/verify_phase5_grants_r4.py",
    "tests/test_session_grants_v4.py",
)
ARTIFACT_PATHS = (
    "core/__init__.py",
    "core/session_grants_v4.py",
    "core/workspaces.py",
    "docs/onyx/APPROVAL_POLICY.md",
    "docs/onyx/IMPLEMENTATION_ROADMAP.md",
    "docs/onyx/TARGET_ARCHITECTURE.md",
    V1_ROOT,
    V2_ARTIFACT,
    V2_ROOT,
    V3_ARTIFACT,
    V3_ROOT,
    CHECKPOINT,
    BUNDLE,
    JUNIT,
    RAW_LOG,
    STATIC_LOG,
    "memory/__init__.py",
    "memory/store.py",
    "scripts/verify_phase5_grants_r4.py",
    "tests/test_session_grants_v4.py",
)
TOP_PATHS = (ARTIFACT_MANIFEST,)
_LINE = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._/-]*)\Z")
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_BUNDLE_KEYS = frozenset(
    {
        "base_commit", "claims", "contract", "counts", "dag", "dependency_closure",
        "environment", "feature_flag", "files", "history", "limits",
        "normative_dependencies", "root_anchor", "status", "timestamp",
    }
)
_LIMIT_CONSTANTS = {
    "max_approvals": "MAX_APPROVALS",
    "max_cost_micro": "MAX_COST_MICRO",
    "max_effect_length": "MAX_EFFECT_LENGTH",
    "max_grants": "MAX_GRANTS",
    "max_missions": "MAX_MISSIONS",
    "max_payload_summary_length": "MAX_PAYLOAD_SUMMARY_LENGTH",
    "max_payloads": "MAX_PAYLOADS",
    "max_plan_length": "MAX_PLAN_LENGTH",
    "max_policies": "MAX_POLICIES",
    "max_prompt_length": "MAX_PROMPT_LENGTH",
    "max_revocations": "MAX_REVOCATIONS",
    "max_session_lifetime_ms": "MAX_SESSION_LIFETIME_MS",
    "max_target_length": "MAX_TARGET_LENGTH",
    "max_targets": "MAX_TARGETS",
    "max_total_payload_summary_chars": "MAX_TOTAL_PAYLOAD_SUMMARY_CHARS",
    "max_total_target_chars": "MAX_TOTAL_TARGET_CHARS",
    "max_uses": "MAX_USES",
}
_CLAIMS = {
    "actual_payload_digest_bound": True,
    "approval_callbacks_outside_lock": True,
    "approval_challenge_bound": True,
    "budget_overrun_nonterminal": True,
    "default_off": True,
    "exact_known_versions": True,
    "shadow_only": True,
    "semantic_state_fingerprint": True,
}


class Phase5GrantR4EvidenceError(RuntimeError):
    pass


def _path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or "." in pure.parts or ".." in pure.parts:
        raise Phase5GrantR4EvidenceError(f"unsafe evidence path: {relative}")
    return root / Path(*pure.parts)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_manifest(path: Path, expected: tuple[str, ...] | None = None) -> tuple[tuple[str, str], ...]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Phase5GrantR4EvidenceError(f"manifest unavailable: {path.name}") from exc
    if b"\r" in raw or not raw.endswith(b"\n") or raw.startswith(b"\xef\xbb\xbf"):
        raise Phase5GrantR4EvidenceError(f"manifest encoding is noncanonical: {path.name}")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise Phase5GrantR4EvidenceError(f"manifest is not UTF-8: {path.name}") from exc
    entries: list[tuple[str, str]] = []
    for line in lines:
        match = _LINE.fullmatch(line)
        if match is None:
            raise Phase5GrantR4EvidenceError(f"manifest line is noncanonical: {path.name}")
        entries.append((match.group(1), match.group(2)))
    paths = tuple(relative for _digest, relative in entries)
    if not entries or len(set(paths)) != len(paths):
        raise Phase5GrantR4EvidenceError(f"manifest set is invalid: {path.name}")
    if expected is not None and paths != expected:
        raise Phase5GrantR4EvidenceError(f"manifest exact set/order mismatch: {path.name}")
    return tuple(entries)


def _verify_entries(root: Path, entries: tuple[tuple[str, str], ...]) -> None:
    for expected, relative in entries:
        candidate = _path(root, relative)
        if not candidate.is_file() or _sha(candidate) != expected:
            raise Phase5GrantR4EvidenceError(f"evidence leaf mismatch: {relative}")


def _module_paths(root: Path, parts: tuple[str, ...]) -> tuple[str, ...]:
    found: list[str] = []
    for index in range(1, len(parts) + 1):
        package = root.joinpath(*parts[:index], "__init__.py")
        if package.is_file():
            found.append(package.relative_to(root).as_posix())
    module = root.joinpath(*parts).with_suffix(".py")
    if module.is_file():
        found.append(module.relative_to(root).as_posix())
    return tuple(dict.fromkeys(found))


def _imports(root: Path, relative: str) -> tuple[str, ...]:
    try:
        tree = ast.parse(_path(root, relative).read_text(encoding="utf-8"), filename=relative)
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise Phase5GrantR4EvidenceError(f"cannot parse dependency source: {relative}") from exc
    current = PurePosixPath(relative)
    package = list(current.parent.parts)
    if current.name == "__init__.py":
        package = list(current.parent.parts)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.update(_module_paths(root, tuple(alias.name.split("."))))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = len(package) - (node.level - 1)
                if keep < 0:
                    raise Phase5GrantR4EvidenceError(f"relative import escapes project: {relative}")
                base = tuple(package[:keep])
            else:
                base = ()
            if node.module:
                base += tuple(node.module.split("."))
            found.update(_module_paths(root, base))
            for alias in node.names:
                if alias.name != "*":
                    found.update(_module_paths(root, base + tuple(alias.name.split("."))))
    return tuple(sorted(found))


def local_import_closure(root: Path, seeds: tuple[str, ...] = SOURCE_SEEDS) -> tuple[str, ...]:
    pending = list(seeds)
    seen: set[str] = set()
    while pending:
        relative = pending.pop()
        if relative in seen:
            continue
        if not _path(root, relative).is_file():
            raise Phase5GrantR4EvidenceError(f"dependency seed/target missing: {relative}")
        seen.add(relative)
        pending.extend(item for item in _imports(root, relative) if item not in seen)
    return tuple(sorted(seen))


def _read_bundle(root: Path) -> dict[str, object]:
    raw = _path(root, BUNDLE).read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Phase5GrantR4EvidenceError("bundle is not valid JSON") from exc
    canonical = (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
    if raw != canonical or not isinstance(value, dict) or frozenset(value) != _BUNDLE_KEYS:
        raise Phase5GrantR4EvidenceError("bundle shape/serialization is noncanonical")
    return value


def _junit_counts(root: Path) -> tuple[dict[str, int], str]:
    try:
        document = ET.fromstring(_path(root, JUNIT).read_bytes())
    except (OSError, ET.ParseError) as exc:
        raise Phase5GrantR4EvidenceError("JUnit is invalid") from exc
    suites = [document] if document.tag == "testsuite" else document.findall("testsuite")
    if len(suites) != 1:
        raise Phase5GrantR4EvidenceError("JUnit must contain exactly one suite")
    suite = suites[0]
    cases = suite.findall("testcase")
    if not cases:
        raise Phase5GrantR4EvidenceError("JUnit contains no testcase evidence")
    actual = {
        "errors": sum(case.find("error") is not None for case in cases),
        "failed": sum(case.find("failure") is not None for case in cases),
        "skipped": sum(case.find("skipped") is not None for case in cases),
    }
    actual["passed"] = len(cases) - actual["errors"] - actual["failed"] - actual["skipped"]
    try:
        declared = {
            "errors": int(suite.attrib["errors"]),
            "failed": int(suite.attrib["failures"]),
            "skipped": int(suite.attrib["skipped"]),
            "passed": int(suite.attrib["tests"])
            - int(suite.attrib["errors"])
            - int(suite.attrib["failures"])
            - int(suite.attrib["skipped"]),
        }
        timestamp = suite.attrib["timestamp"]
    except (KeyError, TypeError, ValueError) as exc:
        raise Phase5GrantR4EvidenceError("JUnit declarations are invalid") from exc
    if declared != actual:
        raise Phase5GrantR4EvidenceError("JUnit declarations differ from testcase evidence")
    return actual, timestamp


def _kv_log(root: Path, relative: str) -> dict[str, str]:
    raw = _path(root, relative).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase5GrantR4EvidenceError(f"log is noncanonical: {relative}")
    values: dict[str, str] = {}
    for line in raw.decode().splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise Phase5GrantR4EvidenceError(f"log line is invalid: {relative}")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key) or key in values:
            raise Phase5GrantR4EvidenceError(f"log key is invalid/duplicate: {relative}")
        values[key] = value
    return values


def _constants(root: Path) -> dict[str, int]:
    tree = ast.parse(_path(root, "core/session_grants_v4.py").read_text(encoding="utf-8"))
    found: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in _LIMIT_CONSTANTS.values():
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, TypeError) as exc:
                    raise Phase5GrantR4EvidenceError(f"limit is not literal: {name}") from exc
                if isinstance(value, bool) or not isinstance(value, int):
                    raise Phase5GrantR4EvidenceError(f"limit is invalid: {name}")
                found[name] = value
    if set(found) != set(_LIMIT_CONSTANTS.values()):
        raise Phase5GrantR4EvidenceError("material limit set is incomplete")
    return {key: found[name] for key, name in _LIMIT_CONSTANTS.items()}


def _validate_code_claims(root: Path) -> None:
    source = _path(root, "core/session_grants_v4.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    classes = {
        node.name: {
            item.target.id
            for item in node.body
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
        }
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
    required_action = {
        "payload_digest", "payload_summary", "payload_rule_id", "egress",
        "idempotency_key", "reversible", "verification_plan", "rollback_plan",
        "cost_currency", "cost_unit", "cost_micro",
    }
    required_response = {
        "approved", "attestation_id", "attestation_sequence", "challenge_digest",
        "scope_digest", "prompt_digest",
    }
    required_prompt = {"scope", "scope_digest", "challenge_digest", "human_summary", "prompt_digest"}
    if not required_action <= classes.get("ResolvedAction", set()):
        raise Phase5GrantR4EvidenceError("actual payload/action binding claim is false")
    if not required_response <= classes.get("HostApprovalResponse", set()) or not required_prompt <= classes.get("ApprovalPrompt", set()):
        raise Phase5GrantR4EvidenceError("approval challenge/prompt binding claim is false")
    required_text = (
        "secrets.token_bytes", "state.fingerprint()", "what leaves device",
        "verification", "rollback", "cost_currency", "callback_required",
        "authority_granted", "grant_evaluator_enabled",
    )
    if any(marker not in source for marker in required_text):
        raise Phase5GrantR4EvidenceError("bundle semantic/prompt claim differs from code")


def _validate_history_binding(claim: object, actual: dict[str, object]) -> None:
    if claim != actual:
        raise Phase5GrantR4EvidenceError("historical evidence binding is false or incomplete")


def _validate_dependency_binding(claim: object, actual: tuple[str, ...]) -> None:
    if claim != list(actual):
        raise Phase5GrantR4EvidenceError("transitive local dependency closure is incomplete")


def _validate_limit_binding(claim: object, actual: dict[str, int]) -> None:
    if claim != actual:
        raise Phase5GrantR4EvidenceError("bundle limits differ from code")


def _current_commit(root: Path) -> str:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False)
    value = result.stdout.strip().casefold()
    if result.returncode or not _HEX40.fullmatch(value):
        raise Phase5GrantR4EvidenceError("current git base commit is unavailable")
    return value


def _environment() -> dict[str, str]:
    return {
        "executable": str(Path(sys.executable).resolve()),
        "platform": platform.platform(),
        "pytest": pytest.__version__,
        "python": sys.version.split()[0],
    }


def _run_history_verifiers(root: Path) -> None:
    for script, marker in (
        ("scripts/verify_phase5_grants_r2.py", "P51_GRANTS_R2_EVIDENCE_OK root=1 artifacts=8"),
        ("scripts/verify_phase5_grants_r3.py", "P51_GRANTS_R3_EVIDENCE_OK root=1 artifacts=11 dependencies=6 tests=54"),
    ):
        result = subprocess.run([sys.executable, str(_path(root, script))], cwd=root, capture_output=True, text=True, timeout=30, check=False)
        if result.returncode or marker not in result.stdout:
            raise Phase5GrantR4EvidenceError(f"historical verifier failed: {script}")


def _history(root: Path) -> dict[str, object]:
    v1 = _parse_manifest(_path(root, V1_ROOT))
    if len(v1) != 10:
        raise Phase5GrantR4EvidenceError("V1 historical manifest count is invalid")
    _verify_entries(root, v1)
    v2_top = _parse_manifest(_path(root, V2_ROOT), (V2_ARTIFACT,))
    v2_artifact = _parse_manifest(_path(root, V2_ARTIFACT))
    v3_top = _parse_manifest(_path(root, V3_ROOT), (V3_ARTIFACT,))
    v3_artifact = _parse_manifest(_path(root, V3_ARTIFACT))
    _verify_entries(root, v2_top + v2_artifact + v3_top + v3_artifact)
    _run_history_verifiers(root)
    return {
        "v1": {"files": 10, "root": V1_ROOT, "root_sha256": _sha(_path(root, V1_ROOT))},
        "v2": {"artifacts": len(v2_artifact), "root": V2_ROOT, "root_sha256": _sha(_path(root, V2_ROOT)), "artifact_manifest": V2_ARTIFACT, "artifact_sha256": _sha(_path(root, V2_ARTIFACT))},
        "v3": {"artifacts": len(v3_artifact), "root": V3_ROOT, "root_sha256": _sha(_path(root, V3_ROOT)), "artifact_manifest": V3_ARTIFACT, "artifact_sha256": _sha(_path(root, V3_ARTIFACT))},
    }


def verify_evidence(root: Path = PROJECT, *, current_base_commit: str | None = None, current_environment: dict[str, str] | None = None) -> dict[str, object]:
    root = root.resolve()
    top = _parse_manifest(_path(root, TOP_MANIFEST), TOP_PATHS)
    _verify_entries(root, top)
    artifacts = _parse_manifest(_path(root, ARTIFACT_MANIFEST), ARTIFACT_PATHS)
    _verify_entries(root, artifacts)
    bundle = _read_bundle(root)
    if bundle.get("contract") != "Phase5SessionGrantShadowEvidence.v4" or bundle.get("status") != "candidate-default-off-not-accepted":
        raise Phase5GrantR4EvidenceError("bundle contract/status is invalid")
    if bundle.get("feature_flag") != {"default": False, "name": "ONYX_GRANT_EVALUATOR"}:
        raise Phase5GrantR4EvidenceError("feature flag declaration is invalid")
    if bundle.get("root_anchor") != {"externally_anchored": False, "required_before_acceptance": True}:
        raise Phase5GrantR4EvidenceError("root anchor status is not honest")
    if bundle.get("claims") != _CLAIMS:
        raise Phase5GrantR4EvidenceError("bundle semantic claims are false or incomplete")
    _validate_code_claims(root)
    if bundle.get("dag") != {"artifact_points_to": list(ARTIFACT_PATHS), "bundle_excludes_manifest_and_self_hashes": True, "root": TOP_MANIFEST, "root_points_to": [ARTIFACT_MANIFEST]}:
        raise Phase5GrantR4EvidenceError("evidence DAG declaration is invalid")
    leaf_paths = tuple(path for path in ARTIFACT_PATHS if path != BUNDLE)
    files = bundle.get("files")
    if not isinstance(files, dict) or tuple(sorted(files)) != tuple(sorted(leaf_paths)):
        raise Phase5GrantR4EvidenceError("bundle leaf set is not exact")
    for relative, digest in files.items():
        if not isinstance(digest, str) or not _HEX64.fullmatch(digest) or _sha(_path(root, relative)) != digest:
            raise Phase5GrantR4EvidenceError(f"bundle leaf hash mismatch: {relative}")
    if any(key in bundle for key in ("root_manifest_sha256", "artifact_manifest_sha256", "self_sha256")):
        raise Phase5GrantR4EvidenceError("bundle introduces a cycle/self hash")
    closure = local_import_closure(root)
    if closure != DECLARED_LOCAL_CLOSURE:
        raise Phase5GrantR4EvidenceError("transitive local dependency closure is incomplete")
    _validate_dependency_binding(bundle.get("dependency_closure"), closure)
    if bundle.get("normative_dependencies") != list(NORMATIVE_DEPENDENCIES):
        raise Phase5GrantR4EvidenceError("normative dependency set is incomplete")
    history = _history(root)
    _validate_history_binding(bundle.get("history"), history)
    counts, junit_timestamp = _junit_counts(root)
    if bundle.get("counts") != counts or counts["failed"] or counts["errors"]:
        raise Phase5GrantR4EvidenceError("bundle/JUnit counts are false")
    raw = _kv_log(root, RAW_LOG)
    if raw.get("timestamp") != junit_timestamp or raw.get("exit_code") != "0" or raw.get("result") != f"{counts['passed']} passed":
        raise Phase5GrantR4EvidenceError("raw/JUnit result differs")
    for key in ("passed", "failed", "errors", "skipped"):
        if raw.get(key) != str(counts[key]):
            raise Phase5GrantR4EvidenceError("raw/JUnit counts differ")
    static = _kv_log(root, STATIC_LOG)
    expected_static = {"diff_check_exit_code": "0", "py_compile_exit_code": "0", "ruff_exit_code": "0", "v1_historical_files": "10", "v2_evidence_artifacts": "8", "v2_evidence_root": "1", "v3_evidence_artifacts": "11", "v3_evidence_dependencies": "6", "v3_evidence_root": "1", "v3_evidence_tests": "54"}
    if any(static.get(key) != value for key, value in expected_static.items()):
        raise Phase5GrantR4EvidenceError("static/historical log is false")
    _validate_limit_binding(bundle.get("limits"), _constants(root))
    base = current_base_commit or _current_commit(root)
    if not _HEX40.fullmatch(base) or bundle.get("base_commit") != base:
        raise Phase5GrantR4EvidenceError("bundle base commit is invalid or stale")
    environment = current_environment or _environment()
    if bundle.get("environment") != environment:
        raise Phase5GrantR4EvidenceError("bundle environment is false")
    timestamp = bundle.get("timestamp")
    if not isinstance(timestamp, str) or timestamp != junit_timestamp:
        raise Phase5GrantR4EvidenceError("bundle timestamp differs from JUnit")
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise Phase5GrantR4EvidenceError("bundle timestamp is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Phase5GrantR4EvidenceError("bundle timestamp lacks a timezone")
    return {"artifact_files": len(artifacts), "artifact_manifest_sha256": _sha(_path(root, ARTIFACT_MANIFEST)), "dependencies": len(closure), "normative": len(NORMATIVE_DEPENDENCIES), "root_files": len(top), "root_manifest_sha256": _sha(_path(root, TOP_MANIFEST)), "tests": counts["passed"]}


def main() -> int:
    result = verify_evidence()
    print(
        "P51_GRANTS_R4_EVIDENCE_OK "
        f"root={result['root_files']} artifacts={result['artifact_files']} dependencies={result['dependencies']} "
        f"normative={result['normative']} tests={result['tests']} root_sha256={result['root_manifest_sha256']} "
        f"artifact_sha256={result['artifact_manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
