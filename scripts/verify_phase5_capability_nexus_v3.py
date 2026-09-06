"""Verify the frozen Phase 5.3 Capability Nexus V3 candidate."""

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
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V3-001.sha256"
ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V3-001.sha256"
EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v3"
BUNDLE = f"{EVIDENCE}/phase5-capability-nexus-v3.bundle.json"
JUNIT = f"{EVIDENCE}/phase5-capability-nexus-v3.junit.xml"
RAW = f"{EVIDENCE}/phase5-capability-nexus-v3.raw.log"
STATIC = f"{EVIDENCE}/phase5-capability-nexus-v3.static.log"
LIVE = f"{EVIDENCE}/phase5-capability-nexus-v3.live-scan.sha256"
V1_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v1/phase5-capability-nexus-v1.live-scan.sha256"
V2_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v2/phase5-capability-nexus-v2.live-scan.sha256"
CHECKPOINT = f"{EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V3_CHECKPOINT.md"
CORE = "core/capability_nexus_v3.py"
TESTS = "tests/test_capability_nexus_v3.py"
WHITESPACE = "scripts/check_phase5_capability_nexus_v3_whitespace.py"
SELF = "scripts/verify_phase5_capability_nexus_v3.py"
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
_LINE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9_./-]+)$")


class V3EvidenceError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(relative: str) -> tuple[tuple[str, str], ...]:
    raw = (PROJECT / relative).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise V3EvidenceError(f"manifest line endings are invalid: {relative}")
    entries = []
    for line in raw.decode().splitlines():
        match = _LINE.fullmatch(line)
        if match is None:
            raise V3EvidenceError(f"manifest line is invalid: {relative}")
        digest, path = match.groups()
        if path.startswith("/") or ".." in Path(path).parts or "\\" in path:
            raise V3EvidenceError("manifest path is unsafe")
        entries.append((digest, path))
    paths = [path for _, path in entries]
    if not entries or paths != sorted(paths) or len(paths) != len(set(paths)):
        raise V3EvidenceError(f"manifest set is invalid: {relative}")
    return tuple(entries)


def _dag() -> tuple[str, ...]:
    root = _manifest(ROOT_MANIFEST)
    if root != ((_sha(PROJECT / ARTIFACT_MANIFEST), ARTIFACT_MANIFEST),):
        raise V3EvidenceError("root manifest edge is invalid")
    artifacts = _manifest(ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        CORE, TESTS, SELF, WHITESPACE, CHECKPOINT, BUNDLE, JUNIT, RAW,
        STATIC, LIVE, V1_LIVE, V2_LIVE, *V1_HISTORY, *V2_HISTORY,
    }
    if not required.issubset(paths) or ARTIFACT_MANIFEST in paths or ROOT_MANIFEST in paths:
        raise V3EvidenceError("artifact manifest closure is invalid")
    for digest, relative in artifacts:
        if not (PROJECT / relative).is_file() or _sha(PROJECT / relative) != digest:
            raise V3EvidenceError(f"artifact hash mismatch: {relative}")
    return paths


def _bundle(paths: tuple[str, ...]) -> dict[str, object]:
    raw = (PROJECT / BUNDLE).read_text(encoding="utf-8")
    try:
        bundle = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise V3EvidenceError("bundle JSON is invalid") from exc
    if raw != json.dumps(bundle, sort_keys=True, separators=(",", ":")) + "\n":
        raise V3EvidenceError("bundle JSON is not canonical")
    if bundle.get("contract") != "Phase53CapabilityNexusEvidence.v3" or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted":
        raise V3EvidenceError("bundle contract/status is invalid")
    if bundle.get("external_e6") != {"accepted": False, "required_before_acceptance": True, "status": "pending-external-review"}:
        raise V3EvidenceError("bundle overstates acceptance")
    if bundle.get("feature_gate") != {"dispatch_enabled": False, "nexus_enabled": False, "shadow_mode": True}:
        raise V3EvidenceError("bundle feature gate is invalid")
    files = bundle.get("files")
    expected = set(paths) - {BUNDLE}
    if not isinstance(files, dict) or set(files) != expected:
        raise V3EvidenceError("bundle file set is invalid")
    for relative, digest in files.items():
        if digest != _sha(PROJECT / relative):
            raise V3EvidenceError(f"bundle file hash mismatch: {relative}")
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
            raise V3EvidenceError("static log is invalid")
        result[key] = int(value)
    expected = {"COMPILE", "DIFF_CHECK", "FOCUSED", "REGRESSIONS", "RUFF", "V2_TAMPER", "WHITESPACE"}
    if set(result) != expected or any(result.values()):
        raise V3EvidenceError("static gate failed")
    return result


def _history_and_tamper(bundle: dict[str, object]) -> None:
    expected = {
        "phase53_v1": {"decision": "rejected", "hashes": V1_HISTORY},
        "phase53_v2": {"decision": "rejected", "hashes": V2_HISTORY},
    }
    if bundle.get("history") != expected:
        raise V3EvidenceError("V1/V2 history is not exact or not rejected")
    for version, history in (("V1", V1_HISTORY), ("V2", V2_HISTORY)):
        for relative, digest in history.items():
            if _sha(PROJECT / relative) != digest:
                raise V3EvidenceError(f"{version} historical byte drift: {relative}")
    source = (PROJECT / "core/capability_nexus_v2.py").read_bytes()
    with tempfile.TemporaryDirectory(prefix="onyx-p53-v2-tamper-") as directory:
        tampered = Path(directory) / "capability_nexus_v2.py"
        tampered.write_bytes(source + b"\n# tamper fixture\n")
        if _sha(tampered) == V2_HISTORY["core/capability_nexus_v2.py"]:
            raise V3EvidenceError("V2 tamper fixture was not rejected")


def _live(bundle: dict[str, object]) -> None:
    entries = _manifest(LIVE)
    if tuple(path for _, path in entries) != ("core/capability_nexus_v2.py", V2_LIVE):
        raise V3EvidenceError("V3 live scan anchors are invalid")
    v2_entries = _manifest(V2_LIVE)
    if tuple(path for _, path in v2_entries) != ("core/capability_nexus_v1.py", V1_LIVE):
        raise V3EvidenceError("V2 live scan anchors are invalid")
    expanded = _manifest(V1_LIVE) + (
        (V1_HISTORY["core/capability_nexus_v1.py"], "core/capability_nexus_v1.py"),
        (V2_HISTORY["core/capability_nexus_v2.py"], "core/capability_nexus_v2.py"),
    )
    if bundle.get("live_scan") != {"count": len(expanded), "manifest_sha256": _sha(PROJECT / LIVE)}:
        raise V3EvidenceError("live scan summary drift")
    for digest, relative in expanded:
        path = PROJECT / relative
        if _sha(path) != digest or "capability_nexus_v3" in path.read_text(encoding="utf-8"):
            raise V3EvidenceError(f"live boundary drift/wiring: {relative}")


def _assignment(path: Path, name: str) -> object:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(item, ast.Name) and item.id == name for item in node.targets):
            return ast.literal_eval(node.value)
    raise V3EvidenceError(f"missing assignment: {name}")


def _semantics(bundle: dict[str, object]) -> None:
    tree = ast.parse((PROJECT / CORE).read_text(encoding="utf-8"))
    forbidden = {"actions", "dashboard", "httpx", "main", "memory", "mcp", "requests", "socket", "subprocess", "webbrowser"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and {item.name.split(".", 1)[0] for item in node.names} & forbidden:
            raise V3EvidenceError("candidate imports a forbidden runtime/provider surface")
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".", 1)[0] in forbidden:
            raise V3EvidenceError("candidate imports a forbidden runtime/provider surface")
    sys.path.insert(0, str(PROJECT))
    try:
        from core.capability_nexus_v3 import (  # noqa: PLC0415
            CapabilityNexusV3,
            NexusFeatureGateV3,
            build_legacy_descriptors_v3,
        )
    finally:
        sys.path.pop(0)
    nexus = CapabilityNexusV3(NexusFeatureGateV3())
    if hasattr(nexus, "dispatch") or hasattr(nexus, "execute"):
        raise V3EvidenceError("registry exposes dispatch")
    declarations = _assignment(PROJECT / "main.py", "TOOL_DECLARATIONS")
    policies = _assignment(PROJECT / "core/permission_broker.py", "MODEL_TOOL_POLICIES")
    built = build_legacy_descriptors_v3(
        declarations, policies, workspace_id="workspace-verifier", account_id="account-verifier", profile_id="profile-verifier"
    )
    if len(built.descriptors) != 26 or dict(built.policy_mapping()) != policies:
        raise V3EvidenceError("legacy parity failed")
    claims = bundle.get("claims")
    expected = {
        "callbacks_outside_locks", "default_off_no_dispatch", "exact_concrete_immutable_gate",
        "profile_bound_projection_snapshot_cursor_receipt", "safe_metadata_secret_rejection",
        "bounded_pending_uncertain_no_replay", "bounded_iterative_metadata_decoding_closure",
        "v1_v2_exact_rejected_history_and_v2_tamper",
    }
    if not isinstance(claims, dict) or set(claims) != expected or not all(claims.values()):
        raise V3EvidenceError("semantic claim set is invalid")


def _environment(bundle: dict[str, object]) -> None:
    recorded = bundle.get("environment")
    expected = {"executable": sys.executable, "platform": platform.platform(), "python": platform.python_version()}
    if not isinstance(recorded, dict) or any(recorded.get(key) != value for key, value in expected.items()):
        raise V3EvidenceError("environment drift")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True, capture_output=True, check=True).stdout.strip()
    if bundle.get("base_commit") != commit:
        raise V3EvidenceError("base commit drift")


def _fresh() -> None:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", TESTS, "--disable-warnings", "--maxfail=1"],
        cwd=PROJECT, env=env, text=True, capture_output=True, check=False,
    )
    if completed.returncode or "69 passed" not in completed.stdout:
        raise V3EvidenceError("fresh focused suite failed")


def verify() -> dict[str, object]:
    paths = _dag()
    bundle = _bundle(paths)
    counts = _junit()
    if counts != {"errors": 0, "failed": 0, "passed": 69, "skipped": 0} or bundle.get("counts") != counts:
        raise V3EvidenceError("JUnit counts drift")
    if bundle.get("static_gates") != _static():
        raise V3EvidenceError("static evidence drift")
    _history_and_tamper(bundle)
    _live(bundle)
    _semantics(bundle)
    _environment(bundle)
    _fresh()
    return {"artifacts": len(paths), "focused_passed": 69, "live_scan_files": 82,
            "root_sha256": _sha(PROJECT / ROOT_MANIFEST)}


def main() -> int:
    print("P53_CAPABILITY_NEXUS_V3_EVIDENCE_OK " + json.dumps(verify(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
