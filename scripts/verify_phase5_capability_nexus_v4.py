"""Verify the frozen Phase 5.3 Capability Nexus V4 candidate."""

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
import tempfile
import xml.etree.ElementTree as ET


PROJECT = Path(__file__).resolve().parents[1]
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V4-001.sha256"
ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V4-001.sha256"
EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v4"
BUNDLE = f"{EVIDENCE}/phase5-capability-nexus-v4.bundle.json"
JUNIT = f"{EVIDENCE}/phase5-capability-nexus-v4.junit.xml"
RAW = f"{EVIDENCE}/phase5-capability-nexus-v4.raw.log"
STATIC = f"{EVIDENCE}/phase5-capability-nexus-v4.static.log"
LIVE = f"{EVIDENCE}/phase5-capability-nexus-v4.live-scan.sha256"
V1_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v1/phase5-capability-nexus-v1.live-scan.sha256"
V2_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v2/phase5-capability-nexus-v2.live-scan.sha256"
V3_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v3/phase5-capability-nexus-v3.live-scan.sha256"
CHECKPOINT = f"{EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V4_CHECKPOINT.md"
CORE = "core/capability_nexus_v4.py"
TESTS = "tests/test_capability_nexus_v4.py"
WHITESPACE = "scripts/check_phase5_capability_nexus_v4_whitespace.py"
SELF = "scripts/verify_phase5_capability_nexus_v4.py"
V1_HISTORY = {
    "core/capability_nexus_v1.py": "cd196f8805b7d89923ce98607fe1c49a762c7001456b470677585f60fa27474a",
    "tests/test_capability_nexus_v1.py": "7c4c1a3120c1f856b067547f04d4d73760589ed36750c847a39abb7fc19bbef3",
    "scripts/verify_phase5_capability_nexus_v1.py": "8f8509f920d99bf524b6b0a7073608cd0ccf3470287dbddc376d46ffddaa9c56",
    "scripts/check_phase5_capability_nexus_v1_whitespace.py": "da40012d947b2702c0ae1e95815a65803a723e86afc720670af717b0cd9fedc0",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V1-001.sha256": "1d46529ff185c1389c353cb5a125e5c8cb28bc8cf7fa56a0f0fa106b304501c5",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V1-001.sha256": "e5f7d577cd0916c3df46d5b540668540fc88a1ec7c60130a198b78c75ec4249b",
}
V2_HISTORY = {
    "core/capability_nexus_v2.py": "4493fddc3d1d17da99db08aa98395ae14f0b9050c1d7238b59261e503424235a",
    "tests/test_capability_nexus_v2.py": "fc2063e07b38f34b4d4643a379b14ed7e3bdcb9074b0f2cdd1675bd767d9d5b0",
    "scripts/verify_phase5_capability_nexus_v2.py": "20c9a5638f8612cd03a0ceb098af263b9b0f67361d38f0e452877235cc27553b",
    "scripts/check_phase5_capability_nexus_v2_whitespace.py": "0cfb5ce2610acb0d4431eb688019eea4ef96735f0236d2d02a5b923a1d937b27",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V2-001.sha256": "668c5ced47eb6c1b654fcc5fb11c372e36b279e5a4af9f83121ebd806a7d8e7b",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V2-001.sha256": "72ddcefff3bb5c99ab7850156f9ec108e64237ca32b17d582e3a8669d8087759",
}
V3_HISTORY = {
    "core/capability_nexus_v3.py": "4fed38cc65ecdce2aa4a352465cd91e4c5e36ab2ff4413333531957afa386aa2",
    "tests/test_capability_nexus_v3.py": "11e3b42af4afa411279ce6435ab05655a4c15a0696574653f45bcae23f29e277",
    "scripts/verify_phase5_capability_nexus_v3.py": "bbfacc680cdc12bc6e201b4e57317a19a2926eb457c6138b7f29aa6c332ddae7",
    "scripts/check_phase5_capability_nexus_v3_whitespace.py": "ef9a907cc340847afb97b34fbfc2a300e5972a7730c83214dfa15e8a1b94e150",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V3-001.sha256": "270f2dd2ad0249e33bc0d04fff50ff150e74d75d687cd76fe2a16fae436b32a6",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V3-001.sha256": "071aa8e114db52e13f7381dade398b92bda6e1466514e49298c9b4a7efb91251",
}
HISTORICAL_ROOTS = (
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V1-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V2-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V3-001.sha256",
)
_LINE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9_./-]+)$")


class V4EvidenceError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(relative: str) -> tuple[tuple[str, str], ...]:
    raw = (PROJECT / relative).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise V4EvidenceError(f"manifest line endings are invalid: {relative}")
    entries = []
    for line in raw.decode().splitlines():
        match = _LINE.fullmatch(line)
        if match is None:
            raise V4EvidenceError(f"manifest line is invalid: {relative}")
        digest, path = match.groups()
        if path.startswith("/") or ".." in Path(path).parts or "\\" in path:
            raise V4EvidenceError("manifest path is unsafe")
        entries.append((digest, path))
    paths = [path for _, path in entries]
    if not entries or paths != sorted(paths) or len(paths) != len(set(paths)):
        raise V4EvidenceError(f"manifest set is invalid: {relative}")
    return tuple(entries)


def _historical_manifest(relative: str) -> tuple[tuple[str, str], ...]:
    """Parse byte-bound legacy manifests without rewriting old line-ending policy."""
    try:
        lines = (PROJECT / relative).read_text(encoding="utf-8").splitlines()
    except UnicodeError as exc:
        raise V4EvidenceError(f"historical manifest encoding is invalid: {relative}") from exc
    entries = []
    for line in lines:
        match = _LINE.fullmatch(line)
        if match is None:
            raise V4EvidenceError(f"historical manifest line is invalid: {relative}")
        digest, path = match.groups()
        if path.startswith("/") or ".." in Path(path).parts or "\\" in path:
            raise V4EvidenceError("historical manifest path is unsafe")
        entries.append((digest, path))
    paths = [path for _, path in entries]
    if not entries or len(paths) != len(set(paths)):
        raise V4EvidenceError(f"historical manifest set is invalid: {relative}")
    return tuple(entries)


def _dag() -> tuple[str, ...]:
    root = _manifest(ROOT_MANIFEST)
    if root != ((_sha(PROJECT / ARTIFACT_MANIFEST), ARTIFACT_MANIFEST),):
        raise V4EvidenceError("root manifest edge is invalid")
    artifacts = _manifest(ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        CORE, TESTS, SELF, WHITESPACE, CHECKPOINT, BUNDLE, JUNIT, RAW,
        STATIC, LIVE, V1_LIVE, V2_LIVE, V3_LIVE,
        *V1_HISTORY, *V2_HISTORY, *V3_HISTORY,
    }
    if not required.issubset(paths) or ARTIFACT_MANIFEST in paths or ROOT_MANIFEST in paths:
        raise V4EvidenceError("artifact manifest closure is invalid")
    for digest, relative in artifacts:
        if not (PROJECT / relative).is_file() or _sha(PROJECT / relative) != digest:
            raise V4EvidenceError(f"artifact hash mismatch: {relative}")
    return paths


def _bundle(paths: tuple[str, ...]) -> dict[str, object]:
    raw = (PROJECT / BUNDLE).read_text(encoding="utf-8")
    try:
        bundle = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise V4EvidenceError("bundle JSON is invalid") from exc
    if raw != json.dumps(bundle, sort_keys=True, separators=(",", ":")) + "\n":
        raise V4EvidenceError("bundle JSON is not canonical")
    if bundle.get("contract") != "Phase53CapabilityNexusEvidence.v4" or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted":
        raise V4EvidenceError("bundle contract/status is invalid")
    if bundle.get("external_e6") != {"accepted": False, "required_before_acceptance": True, "status": "pending-external-review"}:
        raise V4EvidenceError("bundle overstates acceptance")
    if bundle.get("feature_gate") != {"dispatch_enabled": False, "nexus_enabled": False, "shadow_mode": True}:
        raise V4EvidenceError("bundle feature gate is invalid")
    files = bundle.get("files")
    expected = set(paths) - {BUNDLE}
    if not isinstance(files, dict) or set(files) != expected:
        raise V4EvidenceError("bundle file set is invalid")
    for relative, digest in files.items():
        if digest != _sha(PROJECT / relative):
            raise V4EvidenceError(f"bundle file hash mismatch: {relative}")
    return bundle


def _junit() -> dict[str, int]:
    root = ET.parse(PROJECT / JUNIT).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    tests = sum(int(item.attrib.get("tests", 0)) for item in suites)
    failed = sum(int(item.attrib.get("failures", 0)) for item in suites)
    errors = sum(int(item.attrib.get("errors", 0)) for item in suites)
    skipped = sum(int(item.attrib.get("skipped", 0)) for item in suites)
    return {"errors": errors, "failed": failed, "passed": tests - failed - errors - skipped, "skipped": skipped}


def _static() -> dict[str, int]:
    result = {}
    for line in (PROJECT / STATIC).read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if not separator or not value.isdigit():
            raise V4EvidenceError("static log is invalid")
        result[key] = int(value)
    expected = {
        "COMPILE", "DIFF_CHECK", "FOCUSED", "FROZEN_VERIFIERS",
        "HISTORICAL_TAMPER", "REGRESSIONS", "RUFF", "WHITESPACE",
    }
    if set(result) != expected or any(result.values()):
        raise V4EvidenceError("static gate failed")
    return result


def _history_and_tamper(bundle: dict[str, object]) -> None:
    expected = {
        "phase53_v1": {"decision": "rejected", "hashes": V1_HISTORY},
        "phase53_v2": {"decision": "rejected", "hashes": V2_HISTORY},
        "phase53_v3": {"decision": "rejected", "hashes": V3_HISTORY},
    }
    if bundle.get("history") != expected:
        raise V4EvidenceError("V1/V2/V3 history is not exact or not rejected")
    for version, history in (("V1", V1_HISTORY), ("V2", V2_HISTORY), ("V3", V3_HISTORY)):
        for relative, digest in history.items():
            if _sha(PROJECT / relative) != digest:
                raise V4EvidenceError(f"{version} historical byte drift: {relative}")
    historical_leaves: dict[str, str] = {}
    for root in HISTORICAL_ROOTS:
        leaves: dict[str, str] = {}
        _verify_manifest_tree(root, set(), set(), leaves, 0)
        for relative, digest in leaves.items():
            prior = historical_leaves.setdefault(relative, digest)
            if prior != digest:
                raise V4EvidenceError(f"historical leaf digest conflict: {relative}")
    targets = [
        f"docs/onyx/checkpoints/phase5-capability-nexus-v{version}/phase5-capability-nexus-v{version}.{suffix}"
        for version in (1, 2)
        for suffix in ("bundle.json", "junit.xml", "raw.log", "static.log")
    ] + [
        f"docs/onyx/checkpoints/phase5-capability-nexus-v{version}/PHASE5_3_CAPABILITY_NEXUS_V{version}_CHECKPOINT.md"
        for version in (1, 2)
    ] + ["core/capability_nexus_v3.py"]
    with tempfile.TemporaryDirectory(prefix="onyx-p53-history-tamper-") as directory:
        base = Path(directory)
        for relative in targets:
            expected_digest = historical_leaves.get(relative)
            if expected_digest is None:
                raise V4EvidenceError(f"historical tamper leaf is unbound: {relative}")
            copied = base / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_bytes((PROJECT / relative).read_bytes())
            if _sha(copied) != expected_digest:
                raise V4EvidenceError(f"historical pristine copy mismatch: {relative}")
            copied.write_bytes(copied.read_bytes() + b"\n# disposable tamper\n")
            if _sha(copied) == expected_digest:
                raise V4EvidenceError(f"historical tamper fixture was not rejected: {relative}")
    _run_frozen_verifiers()


def _verify_manifest_tree(
    relative: str,
    active: set[str],
    verified: set[str],
    leaves: dict[str, str],
    depth: int,
) -> None:
    if depth > 32 or len(verified) > 256 or len(leaves) > 4096:
        raise V4EvidenceError("historical manifest traversal budget exceeded")
    if relative in active:
        raise V4EvidenceError(f"historical manifest cycle detected: {relative}")
    if relative in verified:
        return
    active.add(relative)
    entries = _historical_manifest(relative)
    for digest, child in entries:
        path = PROJECT / child
        if not path.is_file() or _sha(path) != digest:
            raise V4EvidenceError(f"historical recursive leaf mismatch: {child}")
        if child.endswith(".sha256"):
            _verify_manifest_tree(child, active, verified, leaves, depth + 1)
        else:
            prior = leaves.setdefault(child, digest)
            if prior != digest:
                raise V4EvidenceError(f"historical recursive digest conflict: {child}")
    active.remove(relative)
    verified.add(relative)


def _run_frozen_verifiers() -> None:
    if int(os.environ.get("ONYX_P53_HISTORY_VERIFY_DEPTH", "0")) != 0:
        raise V4EvidenceError("historical verifier recursion detected")
    env = os.environ.copy()
    env["ONYX_P53_HISTORY_VERIFY_DEPTH"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for version in (1, 2, 3):
        verifier = f"scripts/verify_phase5_capability_nexus_v{version}.py"
        completed = subprocess.run(
            [sys.executable, verifier], cwd=PROJECT, env=env, text=True,
            capture_output=True, check=False, timeout=90,
        )
        marker = f"P53_CAPABILITY_NEXUS_V{version}_EVIDENCE_OK"
        if completed.returncode or marker not in completed.stdout:
            raise V4EvidenceError(f"frozen V{version} verifier failed")


def _live(bundle: dict[str, object]) -> None:
    entries = _manifest(LIVE)
    if tuple(path for _, path in entries) != ("core/capability_nexus_v3.py", V3_LIVE):
        raise V4EvidenceError("V4 live scan anchors are invalid")
    v3_entries = _manifest(V3_LIVE)
    if tuple(path for _, path in v3_entries) != ("core/capability_nexus_v2.py", V2_LIVE):
        raise V4EvidenceError("V3 live scan anchors are invalid")
    v2_entries = _manifest(V2_LIVE)
    if tuple(path for _, path in v2_entries) != ("core/capability_nexus_v1.py", V1_LIVE):
        raise V4EvidenceError("V2 live scan anchors are invalid")
    expanded = _manifest(V1_LIVE) + (
        (V1_HISTORY["core/capability_nexus_v1.py"], "core/capability_nexus_v1.py"),
        (V2_HISTORY["core/capability_nexus_v2.py"], "core/capability_nexus_v2.py"),
        (V3_HISTORY["core/capability_nexus_v3.py"], "core/capability_nexus_v3.py"),
    )
    if bundle.get("live_scan") != {"count": len(expanded), "manifest_sha256": _sha(PROJECT / LIVE)}:
        raise V4EvidenceError("live scan summary drift")
    for digest, relative in expanded:
        path = PROJECT / relative
        if _sha(path) != digest or "capability_nexus_v4" in path.read_text(encoding="utf-8"):
            raise V4EvidenceError(f"live boundary drift/wiring: {relative}")


def _assignment(path: Path, name: str) -> object:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(item, ast.Name) and item.id == name for item in node.targets):
            return ast.literal_eval(node.value)
    raise V4EvidenceError(f"missing assignment: {name}")


def _semantics(bundle: dict[str, object]) -> None:
    tree = ast.parse((PROJECT / CORE).read_text(encoding="utf-8"))
    forbidden = {"actions", "dashboard", "httpx", "main", "memory", "mcp", "requests", "socket", "subprocess", "webbrowser"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and {item.name.split(".", 1)[0] for item in node.names} & forbidden:
            raise V4EvidenceError("candidate imports a forbidden runtime/provider surface")
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".", 1)[0] in forbidden:
            raise V4EvidenceError("candidate imports a forbidden runtime/provider surface")
    sys.path.insert(0, str(PROJECT))
    try:
        from core.capability_nexus_v4 import (  # noqa: PLC0415
            CapabilityNexusV4,
            NexusFeatureGateV4,
            build_legacy_descriptors_v4,
        )
    finally:
        sys.path.pop(0)
    nexus = CapabilityNexusV4(NexusFeatureGateV4())
    if hasattr(nexus, "dispatch") or hasattr(nexus, "execute"):
        raise V4EvidenceError("registry exposes dispatch")
    declarations = _assignment(PROJECT / "main.py", "TOOL_DECLARATIONS")
    policies = _assignment(PROJECT / "core/permission_broker.py", "MODEL_TOOL_POLICIES")
    built = build_legacy_descriptors_v4(
        declarations, policies, workspace_id="workspace-verifier", account_id="account-verifier", profile_id="profile-verifier"
    )
    if len(built.descriptors) != 26 or dict(built.policy_mapping()) != policies:
        raise V4EvidenceError("legacy parity failed")
    claims = bundle.get("claims")
    expected = {
        "callbacks_outside_locks", "default_off_no_dispatch", "exact_concrete_immutable_gate",
        "profile_bound_projection_snapshot_cursor_receipt", "safe_metadata_secret_rejection",
        "bounded_pending_uncertain_no_replay", "bounded_iterative_metadata_decoding_closure",
        "bounded_raw_credentials_and_unicode_confusable_skeleton",
        "per_adapter_thread_local_hook_reentrancy_guard",
        "recursive_v1_v2_v3_rejected_history_and_disposable_tamper",
    }
    if not isinstance(claims, dict) or set(claims) != expected or not all(claims.values()):
        raise V4EvidenceError("semantic claim set is invalid")


def _environment(bundle: dict[str, object]) -> None:
    recorded = bundle.get("environment")
    expected = {"executable": sys.executable, "platform": platform.platform(), "python": platform.python_version()}
    if not isinstance(recorded, dict) or any(recorded.get(key) != value for key, value in expected.items()):
        raise V4EvidenceError("environment drift")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True, capture_output=True, check=True).stdout.strip()
    if bundle.get("base_commit") != commit:
        raise V4EvidenceError("base commit drift")


def _fresh() -> None:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", TESTS, "--disable-warnings", "--maxfail=1"],
        cwd=PROJECT, env=env, text=True, capture_output=True, check=False,
    )
    if completed.returncode or "108 passed" not in completed.stdout:
        raise V4EvidenceError("fresh focused suite failed")


def verify() -> dict[str, object]:
    paths = _dag()
    bundle = _bundle(paths)
    counts = _junit()
    if counts != {"errors": 0, "failed": 0, "passed": 108, "skipped": 0} or bundle.get("counts") != counts:
        raise V4EvidenceError("JUnit counts drift")
    if bundle.get("static_gates") != _static():
        raise V4EvidenceError("static evidence drift")
    _history_and_tamper(bundle)
    _live(bundle)
    _semantics(bundle)
    _environment(bundle)
    _fresh()
    return {"artifacts": len(paths), "focused_passed": 108, "live_scan_files": 83,
            "root_sha256": _sha(PROJECT / ROOT_MANIFEST)}


def main() -> int:
    print("P53_CAPABILITY_NEXUS_V4_EVIDENCE_OK " + json.dumps(verify(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
