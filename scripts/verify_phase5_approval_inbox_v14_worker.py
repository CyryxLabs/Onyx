from __future__ import annotations

import argparse
import ast
import hashlib
import hmac
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).absolute().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ARTIFACTS = ROOT / "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V14-001.sha256"
SOURCE = ROOT / "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V14-001.sha256"
BUNDLE = (
    ROOT
    / "docs/onyx/checkpoints/phase5-approval-inbox-v14/phase5-approval-inbox-v14.bundle.json"
)
PROJECTIONS = (
    ROOT / "docs/onyx/checkpoints/phase5-approval-inbox-v14/mutable-projections.json"
)
FOCUSED = ("tests/test_approval_inbox_v14.py",)
COMBINED = tuple(f"tests/test_approval_inbox_v{version}.py" for version in range(1, 15))
REGRESSIONS = (
    "tests/test_regressions.py",
    "tests/test_missions.py",
    "tests/test_mission_tools.py",
)
EXPECTED_PUBLIC = {
    "ApprovalInboxFeatureGateV14",
    "MonotonicInboxClockV14",
    "DeterministicInboxClockV14",
    "HostInboxItemV14",
    "HostInboxSnapshotV14",
    "HostInboxSourceV14",
    "InboxQueryV14",
    "ApprovalReviewItemV14",
    "InboxPageV14",
    "CalmBatchPreviewV14",
    "ReviewSelectionHandoffV14",
    "ApprovalInboxProjectionV14",
}
FORBIDDEN_CORE_IMPORTS = (
    "approval_inbox_v1",
    "approval_inbox_v2",
    "approval_inbox_v3",
    "approval_inbox_v4",
    "approval_inbox_v5",
    "approval_inbox_v6",
    "approval_inbox_v7",
    "approval_inbox_v8",
    "approval_inbox_v9",
    "approval_inbox_v10",
    "approval_inbox_v11",
    "session_grants",
    "capability_nexus",
)
EXPECTED_LIVE_FILES = 26
HISTORICAL_PROJECTIONS = {
    "docs/onyx/CAPABILITY_MATRIX.md": (
        "docs/onyx/checkpoints/phase5-approval-inbox-v9/mutable-projections/"
        "5a7c9f2c71d770b7a3fb49a511a9d94e59e985dd96d45f40b9ed6b7505ce3e8b.snapshot",
        "5a7c9f2c71d770b7a3fb49a511a9d94e59e985dd96d45f40b9ed6b7505ce3e8b",
    ),
    "docs/onyx/VERIFICATION_EVIDENCE.md": (
        "docs/onyx/checkpoints/phase5-approval-inbox-v9/mutable-projections/"
        "e8ab4895f1c8c6b61b2a3c97acbeac3149b966003e8a63f2eebe5f954c65ad79.snapshot",
        "e8ab4895f1c8c6b61b2a3c97acbeac3149b966003e8a63f2eebe5f954c65ad79",
    ),
}
HISTORICAL_ROOT_AUTHORITIES = {
    "docs/onyx/VE-SOURCE-P51-GRANTS-R11-001.sha256": (
        "b4759d8840611e2affbd322831ae8dc88ff84ac09701a24b4a6f56df66463071"
    ),
    "docs/onyx/VE-ACCEPTANCE-P51-GRANTS-R11-E6-001.sha256": (
        "36fb198e27ebb7e8e8bb97885d8a823d2a291ed573da3d5513d950715b113bb0"
    ),
    ".github/workflows/release-packages.yml": (
        "84409f0bc2a24ce7c0a6db11419b07d680674df7e77836b51b7cd5509aa03cab"
    ),
}
CHILD_RELATIVE = "scripts/phase5_approval_inbox_v14_child.py"
PLUGIN_RELATIVE = "scripts/phase5_approval_inbox_v14_historical_projection.py"
PRIVATE_RUNTIME_RELATIVE = (
    "docs/onyx/checkpoints/phase5-approval-inbox-v14/private-runtime/pytest-runtime.zip"
)
PRIVATE_RUNTIME_MANIFEST_MEMBER = "_onyx_pytest_runtime_manifest.json"
PRIVATE_RUNTIME_NAMESPACES = (
    "pytest",
    "_pytest",
    "pluggy",
    "iniconfig",
    "packaging",
    "pygments",
    "colorama",
)
PROCESS_MODULE_SOURCES = {
    "isolated_child": CHILD_RELATIVE,
    "exact_plugin": PLUGIN_RELATIVE,
    **{
        f"historical_verifier_v{version}": (
            f"scripts/verify_phase5_approval_inbox_v{version}.py"
        )
        for version in range(2, 8)
    },
}
_PROCESS_SOURCE_BINDINGS: dict[str, tuple[str, tuple[int, int, int, int]]] = {}
_GLOBAL_DEADLINE: float | None = None


class PathIntegrityError(RuntimeError):
    pass


def _safe_path_at(
    root: Path, relative: str, *, require_directory: bool = False
) -> Path:
    pure = PurePosixPath(relative)
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or "\x00" in relative
        or pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise PathIntegrityError(f"noncanonical-path:{relative!r}")
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    root = root.absolute()
    try:
        root_info = root.lstat()
        root_resolved = root.resolve(strict=True)
    except OSError as error:
        raise PathIntegrityError(f"missing-root:{relative}") from error
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or getattr(root_info, "st_file_attributes", 0) & reparse
        or str(root) != str(root_resolved)
    ):
        raise PathIntegrityError(f"reparse-or-aliased-root:{relative}")
    current = root
    for part in pure.parts:
        try:
            entries = {entry.name: entry for entry in current.iterdir()}
        except OSError as error:
            raise PathIntegrityError(f"unreadable-ancestor:{relative}") from error
        if part not in entries:
            raise PathIntegrityError(f"missing-or-case-mismatch:{relative}")
        current = entries[part]
        try:
            info = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as error:
            raise PathIntegrityError(f"missing-component:{relative}") from error
        if (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & reparse
        ):
            raise PathIntegrityError(f"reparse-component:{relative}")
        try:
            resolved.relative_to(root_resolved)
        except ValueError as error:
            raise PathIntegrityError(f"outside-root:{relative}") from error
        if resolved.name != part:
            raise PathIntegrityError(f"case-or-name-alias:{relative}")
    if require_directory:
        if not current.is_dir():
            raise PathIntegrityError(f"not-directory:{relative}")
    elif not current.is_file():
        raise PathIntegrityError(f"not-file:{relative}")
    return current


def _sanitize_process_environment(source: dict[str, str]) -> dict[str, str]:
    environment = dict(source)
    exact = {
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONHOME",
        "HOME",
        "USERPROFILE",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
    }
    for name in tuple(environment):
        if name in exact or name.startswith("GIT_") or name.startswith("GIT_CONFIG"):
            environment.pop(name, None)
    environment.update(
        {
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return environment


def _verify_private_runtime(
    bundle: dict[str, object], artifacts: dict[str, str]
) -> None:
    descriptor = bundle.get("private_pytest_runtime")
    if type(descriptor) is not dict:
        fail("private-runtime-descriptor")
    path_value = descriptor.get("path")
    digest = descriptor.get("sha256")
    manifest_digest = descriptor.get("manifest_sha256")
    if (
        path_value != PRIVATE_RUNTIME_RELATIVE
        or type(digest) is not str
        or type(manifest_digest) is not str
        or artifacts.get(PRIVATE_RUNTIME_RELATIVE) != digest
    ):
        fail("private-runtime-authority")
    path = safe_path(PRIVATE_RUNTIME_RELATIVE)
    identity = _file_identity(path)
    if not hmac.compare_digest(hashlib.sha256(path.read_bytes()).hexdigest(), digest):
        fail("private-runtime-drift")
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if (
                len(names) != len(set(names))
                or PRIVATE_RUNTIME_MANIFEST_MEMBER not in names
            ):
                fail("private-runtime-members")
            manifest_bytes = archive.read(PRIVATE_RUNTIME_MANIFEST_MEMBER)
            if hashlib.sha256(manifest_bytes).hexdigest() != manifest_digest:
                fail("private-runtime-manifest-drift")
            manifest = json.loads(manifest_bytes)
            files = manifest.get("files") if type(manifest) is dict else None
            if (
                manifest.get("contract") != "OnyxPrivatePytestRuntime.v1"
                or manifest.get("namespaces") != list(PRIVATE_RUNTIME_NAMESPACES)
                or type(files) is not dict
                or set(names) != set(files) | {PRIVATE_RUNTIME_MANIFEST_MEMBER}
                or descriptor.get("file_count") != len(files)
            ):
                fail("private-runtime-contract")
            for name, expected in files.items():
                if (
                    type(name) is not str
                    or type(expected) is not str
                    or not re.fullmatch(r"[0-9a-f]{64}", expected)
                    or hashlib.sha256(archive.read(name)).hexdigest() != expected
                ):
                    fail("private-runtime-member-drift")
    except (OSError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as error:
        fail(f"private-runtime-invalid:{error}")
    if _file_identity(safe_path(PRIVATE_RUNTIME_RELATIVE)) != identity:
        fail("private-runtime-identity-drift")


def sha(path: Path) -> str:
    try:
        relative = path.absolute().relative_to(ROOT.absolute()).as_posix()
        guarded = _safe_path_at(ROOT, relative)
    except (ValueError, PathIntegrityError) as error:
        fail(f"authority-path:{error}")
    return hashlib.sha256(guarded.read_bytes()).hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"P52_APPROVAL_INBOX_V14_EVIDENCE_FAIL {message}")


def safe_path(relative: str) -> Path:
    try:
        return _safe_path_at(ROOT, relative)
    except PathIntegrityError as error:
        fail(f"authority-path:{error}")


def _file_identity(path: Path) -> tuple[int, int, int, int]:
    info = path.lstat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _resolve_bound_process_source(label: str, expected_relative: str) -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", label):
        raise PathIntegrityError(f"noncanonical-source-label:{label!r}")
    return _safe_path_at(ROOT, expected_relative)


def _capture_process_source_bindings(expected_hashes: dict[str, str]) -> None:
    bindings: dict[str, tuple[str, tuple[int, int, int, int]]] = {}
    for module_name, relative in PROCESS_MODULE_SOURCES.items():
        expected_digest = expected_hashes.get(relative)
        if type(expected_digest) is not str:
            fail(f"process-source-not-authoritative:{relative}")
        try:
            path = _resolve_bound_process_source(module_name, relative)
        except (OSError, ValueError, PathIntegrityError) as error:
            fail(f"process-source:{error}")
        actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if not hmac.compare_digest(actual_digest, expected_digest):
            fail(f"process-source-drift:{relative}")
        bindings[module_name] = (expected_digest, _file_identity(path))
    _PROCESS_SOURCE_BINDINGS.clear()
    _PROCESS_SOURCE_BINDINGS.update(bindings)


def _revalidate_process_source_bindings() -> None:
    if set(_PROCESS_SOURCE_BINDINGS) != set(PROCESS_MODULE_SOURCES):
        fail("process-source-bindings-missing")
    for module_name, relative in PROCESS_MODULE_SOURCES.items():
        expected_digest, expected_identity = _PROCESS_SOURCE_BINDINGS[module_name]
        try:
            path = _resolve_bound_process_source(module_name, relative)
        except (OSError, ValueError, PathIntegrityError) as error:
            fail(f"process-source:{error}")
        if _file_identity(path) != expected_identity:
            fail(f"process-source-identity-drift:{relative}")
        actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if not hmac.compare_digest(actual_digest, expected_digest):
            fail(f"process-source-drift:{relative}")


def read_manifest(path: Path) -> dict[str, str]:
    try:
        relative = path.absolute().relative_to(ROOT.absolute()).as_posix()
    except ValueError:
        fail(f"manifest-outside-root:{path}")
    path = safe_path(relative)
    result: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64})  ([!-~]+)", line)
        if match is None:
            fail(f"malformed-manifest:{path.name}:{number}")
        digest, relative = match.groups()
        if relative in result:
            fail(f"duplicate-manifest-path:{relative}")
        result[relative] = digest
    if not result:
        fail(f"empty-manifest:{path.name}")
    return result


def verify_manifests() -> tuple[dict[str, object], int]:
    source = read_manifest(SOURCE)
    expected_source = {ARTIFACTS.relative_to(ROOT).as_posix(): sha(ARTIFACTS)}
    if source != expected_source:
        fail("source-root-relation")
    artifacts = read_manifest(ARTIFACTS)
    for relative, expected in artifacts.items():
        actual = sha(safe_path(relative))
        if not hmac.compare_digest(actual, expected):
            fail(f"artifact-drift:{relative}")
    bundle = json.loads(
        safe_path(BUNDLE.relative_to(ROOT).as_posix()).read_text(encoding="utf-8")
    )
    if (
        type(bundle) is not dict
        or bundle.get("contract") != "Phase52ApprovalInboxEvidence.v14"
    ):
        fail("bundle-contract")
    files = bundle.get("files")
    if type(files) is not dict:
        fail("bundle-files")
    for relative, expected in files.items():
        if type(relative) is not str or type(expected) is not str:
            fail("bundle-file-entry")
        if sha(safe_path(relative)) != expected:
            fail(f"bundle-file-drift:{relative}")
        if artifacts.get(relative) != expected:
            fail(f"bundle-artifact-disagreement:{relative}")
    return bundle, len(artifacts)


def verify_projection_snapshots() -> None:
    mapping = json.loads(
        safe_path(PROJECTIONS.relative_to(ROOT).as_posix()).read_text(encoding="utf-8")
    )
    if mapping.get("contract") != "ContentAddressedMutableProjections.v1":
        fail("projection-map-contract")
    exact_sources = {
        "docs/onyx/CAPABILITY_MATRIX.md",
        "docs/onyx/VERIFICATION_EVIDENCE.md",
    }
    entries = mapping.get("projections")
    if (
        type(entries) is not list
        or {entry.get("source") for entry in entries} != exact_sources
    ):
        fail("projection-map-sources")
    artifacts = read_manifest(ARTIFACTS)
    if exact_sources.intersection(artifacts):
        fail("mutable-live-projection-in-artifacts")
    for entry in entries:
        source = entry.get("source")
        snapshot = entry.get("snapshot")
        digest = entry.get("sha256")
        if not all(type(value) is str for value in (source, snapshot, digest)):
            fail("projection-map-entry")
        path = safe_path(snapshot)
        if sha(path) != digest or artifacts.get(snapshot) != digest:
            fail(f"projection-snapshot-drift:{source}")


def verify_historical_projection_authority(bundle: dict[str, object]) -> None:
    artifacts = read_manifest(ARTIFACTS)
    plugin_relative = "scripts/phase5_approval_inbox_v14_historical_projection.py"
    plugin = safe_path(plugin_relative)
    if artifacts.get(plugin_relative) != sha(plugin):
        fail("historical-plugin-not-authoritative")
    for source, (snapshot, digest) in HISTORICAL_PROJECTIONS.items():
        if artifacts.get(snapshot) != digest or sha(safe_path(snapshot)) != digest:
            fail(f"historical-projection-not-direct-authority:{source}")
    for relative, digest in HISTORICAL_ROOT_AUTHORITIES.items():
        if artifacts.get(relative) != digest or sha(safe_path(relative)) != digest:
            fail(f"historical-root-not-direct-authority:{relative}")
    if bundle.get("git_boundary") != {
        "live_repository_consumed": False,
        "alternates_consumed": False,
        "hooks_consumed": False,
        "git_subprocess_used": False,
        "environment_overrides_consumed": False,
        "hermetic_head": "b2dc0b21f487013cebec34bb148ffb1aeb02611a",
    }:
        fail("hermetic-git-authority")
    expected_process_sources = {
        module_name: {
            "path": relative,
            "sha256": artifacts.get(relative),
        }
        for module_name, relative in PROCESS_MODULE_SOURCES.items()
    }
    if bundle.get("combined_process_sources") != expected_process_sources:
        fail("combined-process-source-authority")
    _capture_process_source_bindings(artifacts)
    text = plugin.read_text(encoding="utf-8")
    tree = ast.parse(text)
    if "FROZEN_PROJECTIONS" not in {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }:
        fail("historical-projection-map-missing")
    required = (
        "temporary-root-not-plugin-owned",
        "preexisting-target",
        "reparse-component",
        'target.open("xb")',
        "_safe_existing(ROOT, authority_relative)",
        '".git/HEAD"',
        "FROZEN_BASE_COMMIT",
        "_load_exact_authoritative_module",
    )
    if any(literal not in text for literal in required):
        fail("historical-projection-gate-shape")
    claims = bundle.get("claims")
    required_claims = (
        "historical_v1_v11_preserved",
        "direct_v9_historical_projection_authority",
        "historical_root_inputs_direct_authority",
        "plugin_owned_temporary_outputs",
        "historical_projection_no_reparse_gate",
        "exclusive_nonpreexisting_output_targets",
        "temporary_cleanup_verified",
        "hermetic_git_fixture",
        "combined_process_sources_identity_bound",
        "child_exact_source_execution",
        "ambient_pytest_inputs_prohibited",
        "process_tree_global_deadline",
        "child_root_identity_validated_first",
        "private_digest_bound_pytest_runtime",
        "git_subprocess_eliminated",
        "git_environment_overrides_rejected",
    )
    if type(claims) is not dict or any(
        claims.get(name) is not True for name in required_claims
    ):
        fail("historical-projection-claims")


def verify_core_shape() -> None:
    path = safe_path("core/approval_inbox_v14.py")
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    public = {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_")
    }
    if not EXPECTED_PUBLIC.issubset(public):
        fail("missing-public-contract")
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    if any(fragment in name for name in imports for fragment in FORBIDDEN_CORE_IMPORTS):
        fail("forbidden-predecessor-import")
    projection = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ApprovalInboxProjectionV14"
    )
    methods = {
        node.name
        for node in projection.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    forbidden = {
        "approve",
        "deny",
        "revoke",
        "grant",
        "dispatch",
        "execute",
        "persist",
        "save",
        "write",
    }
    if methods.intersection(forbidden):
        fail("authority-method-present")
    required_literals = (
        'APPROVAL_INBOX_V14_FLAG = "ONYX_APPROVAL_INBOX_V14"',
        'DISABLED = "DISABLED"',
        'READY = "READY"',
        'STALE = "STALE"',
        'REVOKED = "REVOKED"',
        'INTEGRITY_LATCHED = "INTEGRITY_LATCHED"',
        "default=False, init=False",
        "future-approval-must-re-resolve-all-host-action-fields",
        "_current_integrity_digest",
        "for epoch in range(1, 10_001)",
    )
    for literal in required_literals:
        source = (
            safe_path("tests/test_approval_inbox_v14.py").read_text(encoding="utf-8")
            if literal == "for epoch in range(1, 10_001)"
            else text
        )
        if literal not in source:
            fail(f"missing-core-invariant:{literal}")
    if "_integrity_by_epoch" in text:
        fail("unbounded-epoch-integrity-state")


def verify_no_live_reachability() -> int:
    flattened = ["main.py", "ui.py", "scripts/launch_onyx.pyw"]
    for folder in ("actions", "dashboard"):
        try:
            directory = _safe_path_at(ROOT, folder, require_directory=True)
        except PathIntegrityError as error:
            fail(f"authority-path:{error}")
        for path in directory.glob("*.py"):
            flattened.append(path.relative_to(ROOT).as_posix())
    scanned = 0
    for relative in flattened:
        path = safe_path(relative)
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="strict")
        if "approval_inbox_v14" in text or "ONYX_APPROVAL_INBOX_V14" in text:
            fail(f"live-reachability:{path.relative_to(ROOT).as_posix()}")
        ast.parse(text)
    if scanned != EXPECTED_LIVE_FILES:
        fail(f"live-cardinality:{scanned}:{EXPECTED_LIVE_FILES}")
    return scanned


def run(command: list[str]) -> str:
    global _GLOBAL_DEADLINE
    for argument in command[1:]:
        if type(argument) is str and not argument.startswith("-") and "/" in argument:
            safe_path(argument)
    if _GLOBAL_DEADLINE is None:
        _GLOBAL_DEADLINE = time.monotonic() + 300.0
    remaining = _GLOBAL_DEADLINE - time.monotonic()
    if remaining <= 0:
        fail("global-process-deadline")
    environment = _sanitize_process_environment(os.environ)
    kwargs: dict[str, object] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
        **kwargs,
    )
    try:
        output, _ = process.communicate(timeout=remaining)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=10)
        fail("global-process-deadline-tree-terminated")
    if process.returncode:
        print(output)
        fail(f"command:{' '.join(command)}")
    return output


def passed_count(output: str) -> int:
    matches = re.findall(r"(\d+) passed", output)
    if not matches:
        fail("pytest-count-missing")
    return int(matches[-1])


def verify_fresh(bundle: dict[str, object]) -> tuple[int, int, int, int]:
    python = sys.executable
    artifacts = read_manifest(ARTIFACTS)
    plugin_digest = artifacts.get(PLUGIN_RELATIVE)
    if type(plugin_digest) is not str:
        fail("plugin-not-authoritative")
    runtime_descriptor = bundle.get("private_pytest_runtime")
    if type(runtime_descriptor) is not dict:
        fail("private-runtime-descriptor")
    runtime_digest = runtime_descriptor.get("sha256")
    runtime_manifest_digest = runtime_descriptor.get("manifest_sha256")
    if type(runtime_digest) is not str or type(runtime_manifest_digest) is not str:
        fail("private-runtime-digests")
    _revalidate_process_source_bindings()
    pytest_prefix = [
        python,
        "-E",
        "-S",
        CHILD_RELATIVE,
        "--plugin-sha256",
        plugin_digest,
        "--runtime-sha256",
        runtime_digest,
        "--runtime-manifest-sha256",
        runtime_manifest_digest,
    ]
    focused_output = run([*pytest_prefix, *FOCUSED, "-q", "-p", "no:cacheprovider"])
    combined_output = run(
        [
            *pytest_prefix,
            *COMBINED,
            "-q",
            "-p",
            "no:cacheprovider",
        ]
    )
    regression_output = run(
        [*pytest_prefix, *REGRESSIONS, "-q", "-p", "no:cacheprovider"]
    )
    focused = passed_count(focused_output)
    combined = passed_count(combined_output)
    regressions = passed_count(regression_output)
    subtests = sum(
        int(value) for value in re.findall(r"(\d+) subtests passed", regression_output)
    )
    expected = bundle.get("counts")
    if type(expected) is not dict or (
        focused != expected.get("focused_passed")
        or combined != expected.get("combined_passed")
        or regressions != expected.get("regression_passed")
        or subtests != expected.get("regression_subtests")
    ):
        fail(f"fresh-counts:{focused}:{combined}:{regressions}:{subtests}")
    static_commands = (
        [
            python,
            "-m",
            "py_compile",
            "core/approval_inbox_v14.py",
            "tests/test_approval_inbox_v14.py",
            "scripts/build_phase5_approval_inbox_v14_evidence.py",
            "scripts/phase5_approval_inbox_v14_child.py",
            "scripts/phase5_approval_inbox_v14_historical_projection.py",
        ],
        [
            python,
            "-m",
            "ruff",
            "check",
            "core/approval_inbox_v14.py",
            "tests/test_approval_inbox_v14.py",
            "scripts/build_phase5_approval_inbox_v14_evidence.py",
            "scripts/phase5_approval_inbox_v14_child.py",
            "scripts/phase5_approval_inbox_v14_historical_projection.py",
            "scripts/verify_phase5_approval_inbox_v14.py",
            "scripts/verify_phase5_approval_inbox_v14_worker.py",
            "scripts/check_phase5_approval_inbox_v14_whitespace.py",
        ],
        [
            python,
            "-m",
            "ruff",
            "format",
            "--check",
            "core/approval_inbox_v14.py",
            "tests/test_approval_inbox_v14.py",
            "scripts/build_phase5_approval_inbox_v14_evidence.py",
            "scripts/phase5_approval_inbox_v14_child.py",
            "scripts/phase5_approval_inbox_v14_historical_projection.py",
            "scripts/verify_phase5_approval_inbox_v14.py",
            "scripts/verify_phase5_approval_inbox_v14_worker.py",
            "scripts/check_phase5_approval_inbox_v14_whitespace.py",
        ],
        [python, "scripts/check_phase5_approval_inbox_v14_whitespace.py"],
    )
    for command in static_commands:
        run(list(command))
    return focused, combined, regressions, subtests


def main() -> int:
    global _GLOBAL_DEADLINE
    _GLOBAL_DEADLINE = time.monotonic() + 300.0
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest-only", action="store_true")
    arguments = parser.parse_args()
    bundle, artifacts = verify_manifests()
    _verify_private_runtime(bundle, read_manifest(ARTIFACTS))
    verify_projection_snapshots()
    verify_historical_projection_authority(bundle)
    verify_core_shape()
    live_files = verify_no_live_reachability()
    if bundle.get("live_scan_files") != EXPECTED_LIVE_FILES:
        fail(f"bundle-live-cardinality:{bundle.get('live_scan_files')}")
    if arguments.manifest_only:
        print(
            f"P52_APPROVAL_INBOX_V14_MANIFEST_OK artifacts={artifacts} "
            f"live_files={live_files} root={sha(SOURCE)}"
        )
        return 0
    focused, combined, regressions, subtests = verify_fresh(bundle)
    print(
        "P52_APPROVAL_INBOX_V14_EVIDENCE_OK "
        f"focused={focused} combined={combined} regressions={regressions} "
        f"subtests={subtests} artifacts={artifacts} live_files={live_files} "
        f"root={sha(SOURCE)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
