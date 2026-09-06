"""Semantic and byte-exact verifier for the Phase 5.1 R3 evidence DAG."""

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
TOP_MANIFEST = "docs/onyx/VE-SOURCE-P51-GRANTS-R3-001.sha256"
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P51-GRANTS-R3-001.sha256"
BUNDLE = "docs/onyx/checkpoints/phase5-grants-r3/phase5-grants-r3.bundle.json"
JUNIT = "docs/onyx/checkpoints/phase5-grants-r3/phase5-grants-r3.junit.xml"
RAW_LOG = "docs/onyx/checkpoints/phase5-grants-r3/phase5-grants-r3.raw.log"
STATIC_LOG = "docs/onyx/checkpoints/phase5-grants-r3/phase5-grants-r3.static.log"

SOURCE_SEEDS = (
    "core/session_grants_v3.py",
    "scripts/verify_phase5_grants_r3.py",
    "tests/test_session_grants_v3.py",
)
DECLARED_LOCAL_CLOSURE = (
    "core/__init__.py",
    "core/session_grants_v3.py",
    "memory/__init__.py",
    "memory/store.py",
    "scripts/verify_phase5_grants_r3.py",
    "tests/test_session_grants_v3.py",
)
ARTIFACT_PATHS = (
    "core/__init__.py",
    "core/session_grants_v3.py",
    "docs/onyx/checkpoints/phase5-grants-r3/PHASE5_1_GRANTS_SHADOW_R3_CHECKPOINT.md",
    "docs/onyx/checkpoints/phase5-grants-r3/phase5-grants-r3.bundle.json",
    "docs/onyx/checkpoints/phase5-grants-r3/phase5-grants-r3.junit.xml",
    "docs/onyx/checkpoints/phase5-grants-r3/phase5-grants-r3.raw.log",
    "docs/onyx/checkpoints/phase5-grants-r3/phase5-grants-r3.static.log",
    "memory/__init__.py",
    "memory/store.py",
    "scripts/verify_phase5_grants_r3.py",
    "tests/test_session_grants_v3.py",
)
TOP_PATHS = (ARTIFACT_MANIFEST,)
_LINE = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._/-]*)\Z")
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_BUNDLE_KEYS = frozenset(
    {
        "base_commit",
        "contract",
        "counts",
        "dag",
        "dependency_closure",
        "environment",
        "feature_flag",
        "files",
        "limits",
        "root_anchor",
        "status",
        "timestamp",
    }
)
_LIMIT_CONSTANTS = {
    "max_approvals": "MAX_APPROVALS",
    "max_cost_micro": "MAX_COST_MICRO",
    "max_grants": "MAX_GRANTS",
    "max_missions": "MAX_MISSIONS",
    "max_policies": "MAX_POLICIES",
    "max_revocations": "MAX_REVOCATIONS",
    "max_session_lifetime_ms": "MAX_SESSION_LIFETIME_MS",
    "max_targets": "MAX_TARGETS",
    "max_uses": "MAX_USES",
}


class Phase5GrantR3EvidenceError(RuntimeError):
    pass


def _path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or "." in pure.parts or ".." in pure.parts:
        raise Phase5GrantR3EvidenceError(f"unsafe evidence path: {relative}")
    return root / Path(*pure.parts)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_manifest(path: Path, expected: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Phase5GrantR3EvidenceError(f"manifest unavailable: {path.name}") from exc
    if b"\r" in raw or not raw.endswith(b"\n") or raw.startswith(b"\xef\xbb\xbf"):
        raise Phase5GrantR3EvidenceError(f"manifest encoding is noncanonical: {path.name}")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise Phase5GrantR3EvidenceError(f"manifest is not UTF-8: {path.name}") from exc
    entries: list[tuple[str, str]] = []
    for line in lines:
        match = _LINE.fullmatch(line)
        if match is None:
            raise Phase5GrantR3EvidenceError(f"manifest line is noncanonical: {path.name}")
        entries.append((match.group(1), match.group(2)))
    paths = tuple(relative for _digest, relative in entries)
    if paths != expected or len(set(paths)) != len(paths):
        raise Phase5GrantR3EvidenceError(f"manifest exact set/order mismatch: {path.name}")
    return tuple(entries)


def _verify_entries(root: Path, entries: tuple[tuple[str, str], ...]) -> None:
    for expected, relative in entries:
        candidate = _path(root, relative)
        if not candidate.is_file():
            raise Phase5GrantR3EvidenceError(f"evidence leaf missing: {relative}")
        if _sha(candidate) != expected:
            raise Phase5GrantR3EvidenceError(f"evidence hash mismatch: {relative}")


def _module_paths(root: Path, module: str) -> tuple[str, ...]:
    parts = module.split(".")
    module_file = root.joinpath(*parts).with_suffix(".py")
    package_file = root.joinpath(*parts, "__init__.py")
    values: list[str] = []
    if module_file.is_file():
        values.append(module_file.relative_to(root).as_posix())
    elif package_file.is_file():
        values.append(package_file.relative_to(root).as_posix())
    for index in range(1, len(parts)):
        init = root.joinpath(*parts[:index], "__init__.py")
        if init.is_file():
            values.append(init.relative_to(root).as_posix())
    return tuple(values)


def _imports(root: Path, relative: str) -> tuple[str, ...]:
    try:
        tree = ast.parse(_path(root, relative).read_text(encoding="utf-8"), filename=relative)
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise Phase5GrantR3EvidenceError(f"cannot parse dependency source: {relative}") from exc
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.update(_module_paths(root, alias.name))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            base = node.module
            candidates = list(_module_paths(root, base))
            for alias in node.names:
                candidates.extend(_module_paths(root, f"{base}.{alias.name}"))
            found.update(candidates)
    return tuple(sorted(found))


def local_import_closure(root: Path, seeds: tuple[str, ...] = SOURCE_SEEDS) -> tuple[str, ...]:
    pending = list(seeds)
    seen: set[str] = set()
    while pending:
        relative = pending.pop()
        if relative in seen:
            continue
        candidate = _path(root, relative)
        if not candidate.is_file():
            raise Phase5GrantR3EvidenceError(f"dependency seed/target missing: {relative}")
        seen.add(relative)
        pending.extend(item for item in _imports(root, relative) if item not in seen)
    return tuple(sorted(seen))


def _read_bundle(root: Path) -> dict[str, object]:
    raw = _path(root, BUNDLE).read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Phase5GrantR3EvidenceError("bundle is not valid JSON") from exc
    canonical = (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"
    ).encode("utf-8")
    if raw != canonical or not isinstance(value, dict) or frozenset(value) != _BUNDLE_KEYS:
        raise Phase5GrantR3EvidenceError("bundle shape/serialization is noncanonical")
    return value


def _junit_counts(root: Path) -> tuple[dict[str, int], str]:
    try:
        suite = ET.fromstring(_path(root, JUNIT).read_bytes()).find("testsuite")
    except (OSError, ET.ParseError) as exc:
        raise Phase5GrantR3EvidenceError("JUnit is invalid") from exc
    if suite is None:
        raise Phase5GrantR3EvidenceError("JUnit suite is missing")
    try:
        counts = {
            "errors": int(suite.attrib["errors"]),
            "failed": int(suite.attrib["failures"]),
            "passed": int(suite.attrib["tests"])
            - int(suite.attrib["failures"])
            - int(suite.attrib["errors"])
            - int(suite.attrib["skipped"]),
            "skipped": int(suite.attrib["skipped"]),
        }
        timestamp = suite.attrib["timestamp"]
    except (KeyError, TypeError, ValueError) as exc:
        raise Phase5GrantR3EvidenceError("JUnit counts/timestamp are invalid") from exc
    return counts, timestamp


def _kv_log(root: Path, relative: str) -> dict[str, str]:
    raw = _path(root, relative).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase5GrantR3EvidenceError(f"log is noncanonical: {relative}")
    result: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise Phase5GrantR3EvidenceError(f"log line is invalid: {relative}")
        key, value = line.split("=", 1)
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key) or key in result:
            raise Phase5GrantR3EvidenceError(f"log key is invalid/duplicate: {relative}")
        result[key] = value
    return result


def _constants(root: Path) -> dict[str, int]:
    source = _path(root, "core/session_grants_v3.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    values: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in _LIMIT_CONSTANTS.values():
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, TypeError) as exc:
                    raise Phase5GrantR3EvidenceError(f"limit constant is not literal: {name}") from exc
                if isinstance(value, bool) or not isinstance(value, int):
                    raise Phase5GrantR3EvidenceError(f"limit constant is invalid: {name}")
                values[name] = value
    if set(values) != set(_LIMIT_CONSTANTS.values()):
        raise Phase5GrantR3EvidenceError("declared limit constant set is incomplete")
    return {key: values[name] for key, name in _LIMIT_CONSTANTS.items()}


def _current_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    value = result.stdout.strip().casefold()
    if result.returncode != 0 or not _HEX40.fullmatch(value):
        raise Phase5GrantR3EvidenceError("current git base commit is unavailable")
    return value


def _environment() -> dict[str, str]:
    return {
        "executable": str(Path(sys.executable).resolve()),
        "platform": platform.platform(),
        "pytest": pytest.__version__,
        "python": sys.version.split()[0],
    }


def verify_evidence(
    root: Path = PROJECT,
    *,
    current_base_commit: str | None = None,
    current_environment: dict[str, str] | None = None,
) -> dict[str, object]:
    root = root.resolve()
    top = _parse_manifest(_path(root, TOP_MANIFEST), TOP_PATHS)
    _verify_entries(root, top)
    artifacts = _parse_manifest(_path(root, ARTIFACT_MANIFEST), ARTIFACT_PATHS)
    _verify_entries(root, artifacts)
    bundle = _read_bundle(root)
    if bundle.get("contract") != "Phase5SessionGrantShadowEvidence.v3":
        raise Phase5GrantR3EvidenceError("bundle contract is invalid")
    if bundle.get("status") != "candidate-default-off-not-accepted":
        raise Phase5GrantR3EvidenceError("bundle status is invalid")
    if bundle.get("feature_flag") != {"default": False, "name": "ONYX_GRANT_EVALUATOR"}:
        raise Phase5GrantR3EvidenceError("feature flag declaration is invalid")
    if bundle.get("root_anchor") != {
        "externally_anchored": False,
        "required_before_acceptance": True,
    }:
        raise Phase5GrantR3EvidenceError("root anchor status is not honest")
    if bundle.get("dag") != {
        "artifact_points_to": list(ARTIFACT_PATHS),
        "bundle_excludes_manifest_and_self_hashes": True,
        "root": TOP_MANIFEST,
        "root_points_to": [ARTIFACT_MANIFEST],
    }:
        raise Phase5GrantR3EvidenceError("evidence DAG declaration is invalid")
    files = bundle.get("files")
    leaf_paths = tuple(path for path in ARTIFACT_PATHS if path != BUNDLE)
    if not isinstance(files, dict) or tuple(sorted(files)) != tuple(sorted(leaf_paths)):
        raise Phase5GrantR3EvidenceError("bundle leaf set is not exact")
    for relative, digest in files.items():
        if not isinstance(digest, str) or not _HEX64.fullmatch(digest):
            raise Phase5GrantR3EvidenceError("bundle leaf digest is invalid")
        if _sha(_path(root, relative)) != digest:
            raise Phase5GrantR3EvidenceError(f"bundle leaf hash mismatch: {relative}")
    if any(key in bundle for key in ("root_manifest_sha256", "artifact_manifest_sha256", "self_sha256")):
        raise Phase5GrantR3EvidenceError("bundle introduces a cycle/self hash")
    closure = local_import_closure(root)
    if closure != DECLARED_LOCAL_CLOSURE or bundle.get("dependency_closure") != list(closure):
        raise Phase5GrantR3EvidenceError("transitive local dependency closure is incomplete")
    counts, junit_timestamp = _junit_counts(root)
    if bundle.get("counts") != counts or counts["failed"] or counts["errors"]:
        raise Phase5GrantR3EvidenceError("bundle/JUnit counts are false")
    raw = _kv_log(root, RAW_LOG)
    if raw.get("timestamp") != junit_timestamp:
        raise Phase5GrantR3EvidenceError("raw/JUnit timestamps differ")
    for key in ("passed", "failed", "errors", "skipped"):
        if raw.get(key) != str(counts[key]):
            raise Phase5GrantR3EvidenceError("raw/JUnit counts differ")
    if raw.get("exit_code") != "0" or raw.get("result") != f"{counts['passed']} passed":
        raise Phase5GrantR3EvidenceError("raw test result is false")
    static = _kv_log(root, STATIC_LOG)
    expected_static = {
        "diff_check_exit_code": "0",
        "py_compile_exit_code": "0",
        "ruff_exit_code": "0",
        "v1_historical_files": "10",
        "v2_evidence_artifacts": "8",
        "v2_evidence_root": "1",
    }
    if any(static.get(key) != value for key, value in expected_static.items()):
        raise Phase5GrantR3EvidenceError("static/historical log is false")
    if bundle.get("limits") != _constants(root):
        raise Phase5GrantR3EvidenceError("bundle limits differ from code")
    base = current_base_commit or _current_commit(root)
    if not _HEX40.fullmatch(base) or bundle.get("base_commit") != base:
        raise Phase5GrantR3EvidenceError("bundle base commit is invalid or stale")
    environment = current_environment or _environment()
    if bundle.get("environment") != environment:
        raise Phase5GrantR3EvidenceError("bundle environment is false")
    timestamp = bundle.get("timestamp")
    if not isinstance(timestamp, str) or timestamp != junit_timestamp:
        raise Phase5GrantR3EvidenceError("bundle timestamp differs from JUnit")
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise Phase5GrantR3EvidenceError("bundle timestamp is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Phase5GrantR3EvidenceError("bundle timestamp lacks a timezone")
    return {
        "artifact_files": len(artifacts),
        "artifact_manifest_sha256": _sha(_path(root, ARTIFACT_MANIFEST)),
        "dependencies": len(closure),
        "root_files": len(top),
        "root_manifest_sha256": _sha(_path(root, TOP_MANIFEST)),
        "tests": counts["passed"],
    }


def main() -> int:
    result = verify_evidence()
    print(
        "P51_GRANTS_R3_EVIDENCE_OK "
        f"root={result['root_files']} artifacts={result['artifact_files']} "
        f"dependencies={result['dependencies']} tests={result['tests']} "
        f"root_sha256={result['root_manifest_sha256']} "
        f"artifact_sha256={result['artifact_manifest_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
