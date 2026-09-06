"""Verify the frozen Phase 5.3 Capability Nexus V1 candidate evidence."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import xml.etree.ElementTree as ET


PROJECT = Path(__file__).resolve().parents[1]
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V1-001.sha256"
ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V1-001.sha256"
EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v1"
BUNDLE = f"{EVIDENCE}/phase5-capability-nexus-v1.bundle.json"
JUNIT = f"{EVIDENCE}/phase5-capability-nexus-v1.junit.xml"
RAW_LOG = f"{EVIDENCE}/phase5-capability-nexus-v1.raw.log"
STATIC_LOG = f"{EVIDENCE}/phase5-capability-nexus-v1.static.log"
LIVE_SCAN = f"{EVIDENCE}/phase5-capability-nexus-v1.live-scan.sha256"
CHECKPOINT = f"{EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V1_CHECKPOINT.md"
CORE = "core/capability_nexus_v1.py"
TESTS = "tests/test_capability_nexus_v1.py"
WHITESPACE = "scripts/check_phase5_capability_nexus_v1_whitespace.py"
SELF = "scripts/verify_phase5_capability_nexus_v1.py"
_HASH = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_LINE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9_./-]+)$")


class EvidenceError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(relative: str) -> tuple[tuple[str, str], ...]:
    path = PROJECT / relative
    raw = path.read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise EvidenceError(f"manifest line endings are noncanonical: {relative}")
    entries: list[tuple[str, str]] = []
    for line in raw.decode("utf-8").splitlines():
        match = _MANIFEST_LINE.fullmatch(line)
        if match is None:
            raise EvidenceError(f"invalid manifest line: {relative}")
        digest, item = match.groups()
        if item.startswith("/") or ".." in Path(item).parts or "\\" in item:
            raise EvidenceError(f"unsafe manifest path: {item}")
        entries.append((digest, item))
    paths = [item for _, item in entries]
    if not entries or paths != sorted(paths) or len(set(paths)) != len(paths):
        raise EvidenceError(f"manifest entries are empty, duplicate, or unsorted: {relative}")
    return tuple(entries)


def _verify_dag() -> tuple[str, ...]:
    root = _manifest(ROOT_MANIFEST)
    if root != ((_sha(PROJECT / ARTIFACT_MANIFEST), ARTIFACT_MANIFEST),):
        raise EvidenceError("root manifest must contain the exact artifact-manifest edge")
    artifacts = _manifest(ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {BUNDLE, JUNIT, RAW_LOG, STATIC_LOG, LIVE_SCAN, CHECKPOINT, CORE, TESTS, WHITESPACE, SELF}
    if not required.issubset(paths):
        raise EvidenceError("artifact manifest is missing a required candidate leaf")
    if ARTIFACT_MANIFEST in paths or ROOT_MANIFEST in paths:
        raise EvidenceError("artifact manifest has a circular manifest edge")
    for digest, relative in artifacts:
        path = PROJECT / relative
        if not path.is_file() or _sha(path) != digest:
            raise EvidenceError(f"artifact hash mismatch: {relative}")
    return paths


def _bundle(paths: tuple[str, ...]) -> dict[str, object]:
    raw = (PROJECT / BUNDLE).read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise EvidenceError("bundle is invalid JSON") from exc
    if raw != json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n":
        raise EvidenceError("bundle JSON is not canonical")
    if value.get("contract") != "Phase53CapabilityNexusEvidence.v1":
        raise EvidenceError("bundle contract is invalid")
    if value.get("status") != "candidate-default-off-shadow-only-not-accepted":
        raise EvidenceError("bundle status is invalid")
    if value.get("feature_gate") != {
        "dispatch_enabled": False,
        "nexus_enabled": False,
        "shadow_mode": True,
    }:
        raise EvidenceError("bundle feature gate is not exact")
    if value.get("external_e6") != {
        "accepted": False,
        "required_before_acceptance": True,
        "status": "pending-external-review",
    }:
        raise EvidenceError("bundle overstates external acceptance")
    files = value.get("files")
    expected_files = set(paths) - {BUNDLE}
    if not isinstance(files, dict) or set(files) != expected_files:
        raise EvidenceError("bundle leaf set is not exact")
    for relative, digest in files.items():
        if not isinstance(digest, str) or digest != _sha(PROJECT / relative):
            raise EvidenceError(f"bundle file hash mismatch: {relative}")
    return value


def _junit() -> dict[str, int]:
    root = ET.parse(PROJECT / JUNIT).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise EvidenceError("JUnit contains no suites")
    tests = sum(int(suite.attrib.get("tests", "0")) for suite in suites)
    failures = sum(int(suite.attrib.get("failures", "0")) for suite in suites)
    errors = sum(int(suite.attrib.get("errors", "0")) for suite in suites)
    skipped = sum(int(suite.attrib.get("skipped", "0")) for suite in suites)
    return {"errors": errors, "failed": failures, "passed": tests - failures - errors - skipped, "skipped": skipped}


def _static() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in (PROJECT / STATIC_LOG).read_text(encoding="utf-8").splitlines():
        key, separator, raw = line.partition("=")
        if not separator or not key or not raw.isdigit():
            raise EvidenceError("static log is malformed")
        values[key] = int(raw)
    required = {"COMPILE", "DIFF_CHECK", "FOCUSED", "REGRESSIONS", "RUFF", "WHITESPACE"}
    if set(values) != required or any(values.values()):
        raise EvidenceError("a frozen static gate did not pass")
    return values


def _live_scan(bundle: dict[str, object]) -> None:
    entries = _manifest(LIVE_SCAN)
    paths = tuple(path for _, path in entries)
    if bundle.get("live_scan") != {"count": len(paths), "manifest_sha256": _sha(PROJECT / LIVE_SCAN)}:
        raise EvidenceError("bundle live-scan summary drifted")
    if CORE in paths or TESTS in paths or SELF in paths:
        raise EvidenceError("candidate/evidence file entered the live boundary")
    for digest, relative in entries:
        path = PROJECT / relative
        if not path.is_file() or _sha(path) != digest:
            raise EvidenceError(f"live scan hash mismatch: {relative}")
        if "capability_nexus_v1" in path.read_text(encoding="utf-8", errors="strict"):
            raise EvidenceError(f"live source references the V1 candidate: {relative}")


def _assignment(path: Path, name: str) -> object:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise EvidenceError(f"missing source assignment: {name}")


def _semantic_checks(bundle: dict[str, object]) -> None:
    tree = ast.parse((PROJECT / CORE).read_text(encoding="utf-8"))
    forbidden_import_roots = {
        "actions", "browser", "dashboard", "httpx", "main", "memory", "mcp", "pathlib",
        "requests", "socket", "subprocess", "urllib", "webbrowser",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = {alias.name.split(".", 1)[0] for alias in node.names}
            if names & forbidden_import_roots:
                raise EvidenceError("candidate imports a forbidden runtime/provider surface")
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".", 1)[0] in forbidden_import_roots:
            raise EvidenceError("candidate imports a forbidden runtime/provider surface")
    source = (PROJECT / CORE).read_text(encoding="utf-8")
    if re.search(r"(?<![.\w])(?:open|exec|eval|compile)\s*\(", source):
        raise EvidenceError("candidate contains a forbidden file/code execution call")
    sys.path.insert(0, str(PROJECT))
    try:
        from core.capability_nexus_v1 import (  # noqa: PLC0415
            CapabilityNexusV1,
            NexusFeatureGateV1,
            OperationKind,
            build_legacy_descriptors,
        )
    finally:
        sys.path.pop(0)
    nexus = CapabilityNexusV1(NexusFeatureGateV1())
    if hasattr(nexus, "execute") or hasattr(nexus, "dispatch"):
        raise EvidenceError("registry exposes a dispatch surface")
    if {item.value for item in OperationKind} != {"read", "draft", "mutate", "verify", "reconcile"}:
        raise EvidenceError("operation separation drifted")
    declarations = _assignment(PROJECT / "main.py", "TOOL_DECLARATIONS")
    policies = _assignment(PROJECT / "core" / "permission_broker.py", "MODEL_TOOL_POLICIES")
    built = build_legacy_descriptors(
        declarations, policies, workspace_id="workspace-verifier", account_id="account-verifier",
        profile_id="profile-verifier",
    )
    if len(built.descriptors) != 26 or built.declarations() != tuple(
        sorted(declarations, key=lambda item: item["name"])
    ):
        # The builder returns deterministic name order; compare by name below to
        # avoid treating source declaration order as dispatch behavior.
        if {item["name"]: item for item in built.declarations()} != {
            item["name"]: item for item in declarations
        }:
            raise EvidenceError("legacy declaration parity drifted")
    if dict(built.policy_mapping()) != policies:
        raise EvidenceError("legacy policy parity drifted")
    expected_claims = {
        "default_off_shadow_only",
        "descriptor_never_authorizes_or_dispatches",
        "exact_legacy_declaration_and_policy_parity",
        "immutable_versioned_descriptor_contract",
        "local_provider_free_metadata_read_only",
        "no_live_wiring",
        "secret_shape_rejection",
        "signed_bounded_cursor_and_exact_binding",
        "truthful_health_quota_cost_degraded_reconcile",
    }
    claims = bundle.get("claims")
    if not isinstance(claims, dict) or set(claims) != expected_claims or not all(claims.values()):
        raise EvidenceError("bundle semantic claims are not exact")


def _environment(bundle: dict[str, object]) -> None:
    expected = {
        "executable": sys.executable,
        "platform": platform.platform(),
        "python": platform.python_version(),
    }
    recorded = bundle.get("environment")
    if not isinstance(recorded, dict) or any(recorded.get(key) != value for key, value in expected.items()):
        raise EvidenceError("verification environment drifted")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True, capture_output=True, check=True
    ).stdout.strip()
    if bundle.get("base_commit") != commit:
        raise EvidenceError("base commit drifted")


def _fresh_focused() -> None:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", TESTS, "--disable-warnings", "--maxfail=1"],
        cwd=PROJECT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0 or "59 passed" not in completed.stdout:
        raise EvidenceError("fresh focused contract suite failed")


def verify() -> dict[str, object]:
    paths = _verify_dag()
    bundle = _bundle(paths)
    counts = _junit()
    if counts != bundle.get("counts") or counts != {"errors": 0, "failed": 0, "passed": 59, "skipped": 0}:
        raise EvidenceError("JUnit counts drifted")
    if _static() != bundle.get("static_gates"):
        raise EvidenceError("static gate evidence drifted")
    _live_scan(bundle)
    _semantic_checks(bundle)
    _environment(bundle)
    _fresh_focused()
    return {
        "artifacts": len(paths),
        "focused_passed": counts["passed"],
        "live_scan_files": len(_manifest(LIVE_SCAN)),
        "root_sha256": _sha(PROJECT / ROOT_MANIFEST),
    }


def main() -> int:
    result = verify()
    print("P53_CAPABILITY_NEXUS_V1_EVIDENCE_OK " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
