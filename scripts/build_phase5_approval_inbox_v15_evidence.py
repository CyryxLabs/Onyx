from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import signal
import stat
import subprocess
import sys
import sysconfig
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path, PurePosixPath

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import verify_phase5_approval_inbox_v15_worker as process_guard  # noqa: E402

CHECKPOINT = ROOT / "docs/onyx/checkpoints/phase5-approval-inbox-v15"
ARTIFACTS = ROOT / "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V15-001.sha256"
SOURCE = ROOT / "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V15-001.sha256"
FOCUSED = ("tests/test_approval_inbox_v15.py",)
COMBINED = tuple(f"tests/test_approval_inbox_v{version}.py" for version in range(1, 16))
REGRESSIONS = (
    "tests/test_regressions.py",
    "tests/test_missions.py",
    "tests/test_mission_tools.py",
)
HISTORICAL_PROJECTIONS = (
    "docs/onyx/checkpoints/phase5-approval-inbox-v9/mutable-projections/"
    "5a7c9f2c71d770b7a3fb49a511a9d94e59e985dd96d45f40b9ed6b7505ce3e8b.snapshot",
    "docs/onyx/checkpoints/phase5-approval-inbox-v9/mutable-projections/"
    "e8ab4895f1c8c6b61b2a3c97acbeac3149b966003e8a63f2eebe5f954c65ad79.snapshot",
)
HISTORICAL_ROOT_AUTHORITIES = (
    "docs/onyx/VE-SOURCE-P51-GRANTS-R11-001.sha256",
    "docs/onyx/VE-ACCEPTANCE-P51-GRANTS-R11-E6-001.sha256",
    ".github/workflows/release-packages.yml",
)
GLOBAL_DEADLINE = time.monotonic() + 600.0
PRIVATE_RUNTIME = CHECKPOINT / "private-runtime/pytest-runtime.zip"
DEPENDENCY_TCB_BUILD_CACHE = CHECKPOINT / "phase5-approval-inbox-v15.dependency-tcb.build.json"
PRIVATE_RUNTIME_DISTRIBUTIONS = (
    "pytest",
    "pluggy",
    "iniconfig",
    "packaging",
    "Pygments",
    "colorama",
    "defusedxml",
)
APPLICATION_RUNTIME_SEEDS = (
    "PyQt6",
    "sounddevice",
    "google-genai",
    "requests",
    "youtube-transcript-api",
    "pandas",
    "openpyxl",
    "XlsxWriter",
    "fastapi",
    "httpx",
    "cryptography",
    "psutil",
    "Pillow",
    "pdfplumber",
    "pypdf",
    "python-docx",
    "python-pptx",
    "numpy",
    "playwright",
    "python-multipart",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8", newline="\n")


def _normalized_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def build_host_dependency_tcb() -> dict[str, object]:
    """Hash-bind third-party runtime files, without importing from site in tests."""

    queue = list(APPLICATION_RUNTIME_SEEDS)
    selected: dict[str, importlib.metadata.Distribution] = {}
    while queue:
        requested = queue.pop(0)
        normalized = _normalized_distribution_name(requested)
        if normalized in selected:
            continue
        try:
            distribution = importlib.metadata.distribution(requested)
        except importlib.metadata.PackageNotFoundError as error:
            raise SystemExit(f"required V15 test dependency missing: {requested}") from error
        canonical = distribution.metadata.get("Name") or requested
        selected[_normalized_distribution_name(canonical)] = distribution
        for requirement in distribution.requires or ():
            try:
                parsed = Requirement(requirement)
            except Exception:
                continue
            if parsed.marker is not None and not parsed.marker.evaluate({"extra": ""}):
                continue
            dependency = parsed.name
            try:
                importlib.metadata.distribution(dependency)
            except importlib.metadata.PackageNotFoundError:
                continue
            queue.append(dependency)
    files: dict[str, dict[str, str]] = {}
    owners: dict[str, list[str]] = {}
    versions: dict[str, str] = {}
    root_labels: dict[str, str] = {}
    roots: dict[str, str] = {}
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    for normalized, distribution in sorted(selected.items()):
        versions[distribution.metadata.get("Name") or normalized] = distribution.version
        distribution_root = Path(distribution.locate_file("")).absolute().resolve(strict=True)
        root_key = str(distribution_root)
        label = root_labels.get(root_key)
        if label is None:
            label = f"root_{len(root_labels)}"
            root_labels[root_key] = label
            roots[label] = root_key
        for entry in distribution.files or ():
            source = Path(distribution.locate_file(entry)).absolute()
            try:
                resolved = source.resolve(strict=True)
                relative = resolved.relative_to(distribution_root).as_posix()
                info = source.lstat()
            except (OSError, ValueError):
                continue
            pure = PurePosixPath(relative)
            process_guard._reject_dependency_namespace_collision(relative)
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & reparse
                or str(source) != str(resolved)
                or "__pycache__" in pure.parts
                or pure.suffix in {".pyc", ".pyo", ".pth"}
            ):
                continue
            digest = sha(source)
            record = {"root": label, "sha256": digest}
            prior = files.get(relative)
            if prior is not None and prior != record:
                raise SystemExit(f"dependency file collision: {relative}")
            files[relative] = record
            owners.setdefault(relative, []).append(
                distribution.metadata.get("Name") or normalized
            )
    if not files:
        raise SystemExit("empty host dependency TCB")
    return {
        "contract": "OnyxHostDependencyTCB.v15",
        "seeds": list(APPLICATION_RUNTIME_SEEDS),
        "source_roots": dict(sorted(roots.items())),
        "distributions": dict(sorted(versions.items())),
        "files": dict(sorted(files.items())),
        "file_owners": {key: sorted(set(value)) for key, value in sorted(owners.items())},
        "imported_only_from_materialized_copy": True,
    }


def build_workspace_materialization(runtime_relative: str) -> dict[str, object]:
    selected: set[str] = {
        "main.py",
        "ui.py",
        "readme.md",
        "core/prompt.txt",
        "dashboard/static/app.html",
        runtime_relative,
    }
    for folder in ("actions", "core", "dashboard", "memory", "config", "scripts"):
        selected.update(
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / folder).rglob("*.py")
            if path.is_file()
        )
    selected.update(COMBINED)
    selected.update(REGRESSIONS)
    predecessor = json.loads(
        (
            ROOT
            / "docs/onyx/checkpoints/phase5-approval-inbox-v14/phase5-approval-inbox-v14.bundle.json"
        ).read_text(encoding="utf-8")
    )
    selected.update(predecessor["files"])
    queue = [
        *HISTORICAL_ROOT_AUTHORITIES,
        *(
            f"docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V{version}-001.sha256"
            for version in range(1, 15)
        ),
    ]
    closure_seen: set[str] = set()
    while queue:
        relative = queue.pop(0)
        if relative in closure_seen:
            continue
        closure_seen.add(relative)
        selected.add(relative)
        path = ROOT / relative
        if relative.endswith(".sha256") and path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                match = re.fullmatch(r"[0-9a-f]{64}  ([!-~]+)", line)
                if match is None:
                    raise SystemExit(f"noncanonical closure manifest: {relative}")
                queue.append(match.group(1))
    files: dict[str, str] = {}
    for relative in sorted(selected):
        pure = PurePosixPath(relative)
        if "__pycache__" in pure.parts or pure.suffix in {".pyc", ".pyo"}:
            raise SystemExit(f"bytecode in workspace closure: {relative}")
        path = ROOT / Path(*pure.parts)
        if not path.is_file():
            raise SystemExit(f"missing workspace closure file: {relative}")
        files[relative] = sha(path)
    return {
        "contract": "OnyxCleanMaterializedTree.v15",
        "exclusive_fresh_root": True,
        "files": files,
    }


def python_host_tcb() -> dict[str, object]:
    executable = Path(sys.executable).absolute()
    roots: list[str] = []
    for name in ("stdlib", "platstdlib"):
        value = str(Path(sysconfig.get_paths()[name]).resolve(strict=True))
        if value not in roots:
            roots.append(value)
    try:
        entries = process_guard._expected_python_stdlib_entries()
    except process_guard.PathIntegrityError as error:
        raise SystemExit(f"Python stdlib import TCB invalid: {error}") from error
    return {
        "contract": "OnyxPythonHostTCB.v15",
        "executable": str(executable),
        "executable_sha256": sha(executable),
        "version": sys.version,
        "cache_tag": sys.implementation.cache_tag,
        "implementation": sys.implementation.name,
        "stdlib_roots": roots,
        "stdlib_entries": entries,
        "limitation": (
            "Trusted host interpreter, standard library and loaded OS DLLs; "
            "this checkpoint does not claim a hermetic Python distribution."
        ),
    }


def build_private_pytest_runtime() -> tuple[str, str, int, dict[str, str]]:
    """Materialize one deterministic, pure-Python, content-bound test runtime."""

    files: dict[str, bytes] = {}
    versions: dict[str, str] = {}
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    for distribution_name in PRIVATE_RUNTIME_DISTRIBUTIONS:
        distribution = importlib.metadata.distribution(distribution_name)
        versions[distribution_name] = distribution.version
        for entry in distribution.files or ():
            relative = PurePosixPath(str(entry).replace("\\", "/"))
            if (
                relative.is_absolute()
                or any(part in {"", ".", ".."} for part in relative.parts)
                or relative.suffix in {".pyc", ".pyo", ".exe"}
                or "__pycache__" in relative.parts
            ):
                continue
            source = Path(distribution.locate_file(entry)).absolute()
            try:
                info = source.lstat()
                resolved = source.resolve(strict=True)
            except OSError as error:
                raise SystemExit(f"private runtime source missing: {entry}") from error
            if (
                not stat.S_ISREG(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & reparse
                or str(source) != str(resolved)
                or ROOT == resolved
                or ROOT in resolved.parents
            ):
                raise SystemExit(f"private runtime source is not regular: {entry}")
            archive_name = relative.as_posix()
            data = source.read_bytes()
            prior = files.get(archive_name)
            if prior is not None and prior != data:
                raise SystemExit(f"private runtime member collision: {archive_name}")
            files[archive_name] = data
    required_roots = {
        "pytest",
        "_pytest",
        "pluggy",
        "iniconfig",
        "packaging",
        "pygments",
        "colorama",
    }
    discovered_roots = {PurePosixPath(name).parts[0] for name in files}
    if not required_roots.issubset(discovered_roots):
        raise SystemExit("private runtime dependency closure incomplete")
    manifest = {
        "contract": "OnyxPrivatePytestRuntime.v1",
        "namespaces": list(process_guard.PRIVATE_RUNTIME_NAMESPACES),
        "distributions": versions,
        "files": {
            name: hashlib.sha256(data).hexdigest()
            for name, data in sorted(files.items())
        },
    }
    manifest_bytes = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    PRIVATE_RUNTIME.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        PRIVATE_RUNTIME, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compresslevel=9)
        info = zipfile.ZipInfo(
            process_guard.PRIVATE_RUNTIME_MANIFEST_MEMBER,
            date_time=(1980, 1, 1, 0, 0, 0),
        )
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, manifest_bytes, compresslevel=9)
    return (
        sha(PRIVATE_RUNTIME),
        hashlib.sha256(manifest_bytes).hexdigest(),
        len(files),
        versions,
    )


def run(command: list[str], *, cwd: Path) -> tuple[str, float]:
    started = time.perf_counter()
    remaining = GLOBAL_DEADLINE - time.monotonic()
    if remaining <= 0:
        raise SystemExit("global process deadline exhausted")
    environment = process_guard._sanitize_process_environment(os.environ)
    private_home = cwd.parent / "home"
    private_home.mkdir(mode=0o700, exist_ok=True)
    private_temp = private_home / "tmp"
    private_temp.mkdir(exist_ok=True)
    environment.update(
        {
            "TEMP": str(private_temp),
            "TMP": str(private_temp),
            "PYTHONPYCACHEPREFIX": str(private_home / "pycache"),
            "HOME": str(private_home),
            "USERPROFILE": str(private_home),
            "HOMEDRIVE": private_home.drive,
            "HOMEPATH": str(private_home)[len(private_home.drive) :],
        }
    )
    kwargs: dict[str, object] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
        **kwargs,
    )
    try:
        output, _ = process.communicate(timeout=remaining)
    except subprocess.TimeoutExpired:
        process_guard._terminate_process_tree(process)
        process.communicate(timeout=10)
        raise SystemExit("global process deadline; descendant tree terminated")
    elapsed = time.perf_counter() - started
    if process.returncode:
        print(output)
        raise SystemExit(f"command failed: {' '.join(command)}")
    return output, elapsed


def junit_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    tests = sum(int(suite.attrib.get("tests", 0)) for suite in suites)
    failures = sum(int(suite.attrib.get("failures", 0)) for suite in suites)
    errors = sum(int(suite.attrib.get("errors", 0)) for suite in suites)
    skipped = sum(int(suite.attrib.get("skipped", 0)) for suite in suites)
    return {
        "passed": tests - failures - errors - skipped,
        "failed": failures,
        "errors": errors,
        "skipped": skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-regressions-only", action="store_true")
    arguments = parser.parse_args()
    CHECKPOINT.mkdir(parents=True, exist_ok=True)
    (
        runtime_digest,
        runtime_manifest_digest,
        runtime_file_count,
        runtime_versions,
    ) = build_private_pytest_runtime()
    python = sys.executable
    focused_junit = CHECKPOINT / "phase5-approval-inbox-v15.junit.xml"
    combined_junit = CHECKPOINT / "phase5-approval-inbox-v15.combined.junit.xml"
    regressions_junit = CHECKPOINT / "phase5-approval-inbox-v15.regressions.junit.xml"

    process_source_hashes = {
        relative: sha(ROOT / relative)
        for relative in process_guard.PROCESS_MODULE_SOURCES.values()
    }
    process_guard._capture_process_source_bindings(process_source_hashes)
    plugin_digest = process_source_hashes[process_guard.PLUGIN_RELATIVE]
    if DEPENDENCY_TCB_BUILD_CACHE.is_file():
        host_dependencies = json.loads(
            DEPENDENCY_TCB_BUILD_CACHE.read_text(encoding="utf-8")
        )
        if (
            host_dependencies.get("contract") != "OnyxHostDependencyTCB.v15"
            or host_dependencies.get("seeds") != list(APPLICATION_RUNTIME_SEEDS)
        ):
            raise SystemExit("invalid dependency TCB build cache")
    else:
        host_dependencies = build_host_dependency_tcb()
        write(
            DEPENDENCY_TCB_BUILD_CACHE,
            json.dumps(host_dependencies, sort_keys=True, separators=(",", ":"))
            + "\n",
        )
    workspace_materialization = build_workspace_materialization(
        PRIVATE_RUNTIME.relative_to(ROOT).as_posix()
    )
    python_tcb = python_host_tcb()
    process_guard._validate_python_tcb({"python_host_tcb": python_tcb})
    materialization_bundle = {
        "materialized_tree": workspace_materialization,
        "host_dependency_tcb": host_dependencies,
    }
    with process_guard.materialized_tree(materialization_bundle) as clean:
        global GLOBAL_DEADLINE
        GLOBAL_DEADLINE = time.monotonic() + 600.0
        private_junit = clean.parent / "home" / "junit"
        private_junit.mkdir(parents=True)
        focused_private_junit = private_junit / "focused.xml"
        combined_private_junit = private_junit / "combined.xml"
        regressions_private_junit = private_junit / "regressions.xml"
        manifest_digest = sha(clean / process_guard.MATERIALIZED_MANIFEST)
        child = clean / process_guard.CHILD_RELATIVE
        pytest_prefix = [
            python,
            *process_guard.PYTHON_FLAGS,
            str(child),
            "--plugin-sha256",
            plugin_digest,
            "--runtime-sha256",
            runtime_digest,
            "--runtime-manifest-sha256",
            runtime_manifest_digest,
            "--materialized-manifest-sha256",
            manifest_digest,
        ]
        for entry in python_tcb["stdlib_entries"]:
            pytest_prefix.extend(
                [
                    "--stdlib-entry",
                    entry["path"],
                    entry.get("sha256", entry["kind"]),
                ]
            )
        if arguments.check_regressions_only:
            output, seconds = run(
                [
                    *pytest_prefix,
                    *REGRESSIONS,
                    "-q",
                    "-p",
                    "no:cacheprovider",
                ],
                cwd=clean,
            )
            print(output, end="")
            print(f"P52_APPROVAL_INBOX_V15_REGRESSION_CHECK seconds={seconds:.3f}")
            return 0
        focused_output, focused_seconds = run(
            [
                *pytest_prefix,
                *FOCUSED,
                "-q",
                "-p",
                "no:cacheprovider",
                f"--junitxml={focused_private_junit}",
            ],
            cwd=clean,
        )
        process_guard._revalidate_process_source_bindings()
        combined_output, combined_seconds = run(
            [
                *pytest_prefix,
                *COMBINED,
                "-q",
                "-p",
                "no:cacheprovider",
                f"--junitxml={combined_private_junit}",
            ],
            cwd=clean,
        )
        regression_output, regression_seconds = run(
            [
                *pytest_prefix,
                *REGRESSIONS,
                "-q",
                "-p",
                "no:cacheprovider",
                f"--junitxml={regressions_private_junit}",
            ],
            cwd=clean,
        )
        focused_junit.write_bytes(focused_private_junit.read_bytes())
        combined_junit.write_bytes(combined_private_junit.read_bytes())
        regressions_junit.write_bytes(regressions_private_junit.read_bytes())
    write(CHECKPOINT / "phase5-approval-inbox-v15.raw.log", focused_output)
    write(CHECKPOINT / "phase5-approval-inbox-v15.combined.log", combined_output)
    write(CHECKPOINT / "phase5-approval-inbox-v15.regressions.log", regression_output)

    static_started = time.perf_counter()
    static_files = (
        "core/approval_inbox_v15.py",
        "tests/test_approval_inbox_v15.py",
        "scripts/build_phase5_approval_inbox_v15_evidence.py",
        "scripts/phase5_approval_inbox_v15_child.py",
        "scripts/phase5_approval_inbox_v15_historical_projection.py",
        "scripts/verify_phase5_approval_inbox_v15.py",
        "scripts/verify_phase5_approval_inbox_v15_worker.py",
        "scripts/check_phase5_approval_inbox_v15_whitespace.py",
    )
    static_lines = ["V15 deterministic internal static gate"]
    for relative in static_files:
        data = (ROOT / relative).read_bytes()
        if b"\r" in data or any(
            line.endswith((b" ", b"\t")) for line in data.splitlines()
        ):
            raise SystemExit(f"static whitespace failure: {relative}")
        source = data.decode("utf-8")
        compile(source, relative, "exec", dont_inherit=True)
        ast.parse(source, filename=relative)
        static_lines.append(f"OK compile+ast+whitespace {relative}")
    static_seconds = time.perf_counter() - static_started
    write(
        CHECKPOINT / "phase5-approval-inbox-v15.static.log",
        "\n".join(static_lines) + "\n",
    )

    projections: list[dict[str, str]] = []
    projection_directory = CHECKPOINT / "mutable-projections"
    projection_directory.mkdir(exist_ok=True)
    for relative in (
        "docs/onyx/CAPABILITY_MATRIX.md",
        "docs/onyx/VERIFICATION_EVIDENCE.md",
    ):
        source_path = ROOT / relative
        digest = sha(source_path)
        snapshot = projection_directory / f"{digest}.snapshot"
        snapshot.write_bytes(source_path.read_bytes())
        projections.append(
            {
                "source": relative,
                "snapshot": snapshot.relative_to(ROOT).as_posix(),
                "sha256": digest,
            }
        )
    write(
        CHECKPOINT / "mutable-projections.json",
        json.dumps(
            {
                "contract": "ContentAddressedMutableProjections.v1",
                "projections": projections,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )

    live_paths = [ROOT / "main.py", ROOT / "ui.py", ROOT / "scripts/launch_onyx.pyw"]
    for folder in ("actions", "dashboard"):
        live_paths.extend((ROOT / folder).glob("*.py"))
    live_entries = sorted(
        (path.relative_to(ROOT).as_posix(), sha(path))
        for path in live_paths
        if path.is_file()
    )
    write(
        CHECKPOINT / "phase5-approval-inbox-v15.live-scan.sha256",
        "".join(f"{digest}  {relative}\n" for relative, digest in live_entries),
    )

    focused = junit_counts(focused_junit)
    combined = junit_counts(combined_junit)
    regressions = junit_counts(regressions_junit)
    regression_matches = re.findall(r"(\d+) passed", regression_output)
    if not regression_matches:
        raise SystemExit("regression passed count unavailable")
    regression_passed = int(regression_matches[-1])
    subtests = sum(
        int(value) for value in re.findall(r"(\d+) subtests passed", regression_output)
    )
    if any(
        counts[key]
        for counts in (focused, combined, regressions)
        for key in ("failed", "errors", "skipped")
    ):
        raise SystemExit("non-green evidence run")

    checkpoint_text = f"""# Phase 5.2 Approval Inbox V15 checkpoint

Status: **candidate — default-off, read-only, external acceptance pending**

V15 is a clean-room review projection. It preserves V1-V14 as rejected historical
candidates and does not import their core implementation, Session Grants or
Capability Nexus. The
host owns a bootstrap-only `ONYX_APPROVAL_INBOX_V15` gate, flag epoch, exact
source and monotonic clock. No live/startup/UI/dashboard path imports V15.

Every return from a host epoch callback re-enters the gate lock and gives an
already-terminal revocation precedence over the callback value. Page,
continuation, preview and handoff publication hold the gate and projection
locks through their linearization point, then recheck terminal state, exact
source generation/epoch and current snapshot/view membership. A newer source
commit therefore cannot be followed by stale output or stale cache
repopulation from an older concurrent capture.

## Authority boundary

Every page, review item, calm-batch preview and handoff states
`authority_granted=False`, `approval_action_available=False` and
`execution_available=False`. There is no approve, deny, approval-revoke, grant,
dispatch, execute or persistence surface. A handoff contains review identifiers
only and instructs a future approval service to re-resolve every host action
field immediately before any authorization decision.

## Validity and batching

The terminal machine is `DISABLED -> READY -> STALE | REVOKED |
INTEGRITY_LATCHED`. A changed feature epoch, clock rollback, source rollback or
same-epoch equivocation invalidates cached state. The source integrity high-water
retains exactly one current epoch digest: accepting a newer epoch atomically
replaces the prior digest, while same-current equivocation and every older-epoch
rollback still latch. A deterministic 10,000-epoch test proves the integrity
state, snapshot cache and view cache remain constant-cardinality. Exact snapshot reuse preserves
its original local creation/deadline and returned proofs, so refresh never
extends TTL. Source callbacks are bounded single-flight and execute outside the
projection lock.

Pagination tokens bind snapshot, view/query/filter/sort, page size, offset,
ordered item set and fixed deadline. Review proofs bind the complete action and
context fingerprint plus safe human-review fields. Calm batches require exact
returned `(item_id, review_proof)` pairs; selection order is canonicalized.
Duplicate item IDs, action request IDs, action fingerprints and idempotency
identities fail closed. High, critical, always-explicit or otherwise ineligible
items cannot enter a batch.

## Stored evidence

- Focused: {focused["passed"]} passed in {focused_seconds:.3f}s.
- Combined Approval Inbox V1-V15: {combined["passed"]} passed in {combined_seconds:.3f}s.
- Frozen V2-V7 R11 fixtures resolve exactly two mutable documentation paths
  directly from exact V9 content-addressed snapshots bound as V15 artifacts.
  The plugin never reads those live paths and never edits predecessors or live
  documentation. R11 root/acceptance inputs and its extra workflow are also
  direct V15 authorities with fixed digests.
- Relevant regressions: {regression_passed} passed plus {subtests} subtests in {regression_seconds:.3f}s.
- Static gates: deterministic in-memory compile, AST parse and whitespace checks
  passed in {static_seconds:.3f}s. Ruff and py_compile are deliberately not
  imported or executed from the live environment.
- Live reachability scan: {len(live_entries)} files, no V15 flag/module reference.
- Parent, worker and historical plugin authoritative paths reject noncanonical
  spelling, case aliases, containment escapes and root/ancestor/final symlink,
  junction or reparse components before each read, hash or process launch.
  Historical copies use fresh plugin-owned temporary roots, exclusive
  nonpreexisting regular-file targets and verified cleanup; live cardinality is
  fixed at {len(live_entries)}.
- Historical Git checks use a private minimal metadata tree containing only the
  frozen R11 HEAD. The live `.git`, hooks, config, alternates and object database
  are never consumed. The combined child runs under one process-tree deadline,
  Python `-I -S -B`, a sanitized environment and an exclusive clean materialized
  root with pytest autoload, conftest and ambient configuration prohibited.
- Every workspace source, test, helper, package initializer and data authority
  used by the three suites is copied from a bundle hash into that clean root.
  Third-party application dependencies are a separately enumerated file-level
  host TCB and are copied into a private dependency tree; site-packages, `.pth`,
  user-site, cwd and script-directory are never import authority. Loaded module
  origins are audited after each run.
- The parent deadline is 900 seconds and the three child suites share a
  600-second post-materialization process-tree deadline. Timeout still fails
  closed and terminates descendants; dependency copying is outside that child
  execution budget.
- The combined plugin and all six V2-V7 verifier modules execute from exact
  re-gated, digest-bound source bytes under private names. Conventional
  `sys.modules`, dotted import hooks and preloaded modules are not authority.
- Mutable matrix/evidence inputs are represented only by exact content-addressed snapshots and an exact mapping; live projection paths are excluded from the artifact manifest.

## Explicit limitations

- File identity/hash checks are non-atomic and require a stable, nonconcurrently
  mutated authoritative workspace during verification; they are not an
  operating-system handle-based TOCTOU boundary.
- The live reachability result covers exactly `main.py`, `ui.py`,
  `scripts/launch_onyx.pyw`, and current top-level `actions/*.py` and
  `dashboard/*.py` files ({len(live_entries)} paths). It is not a proof about
  unscanned extensions, non-Python launchers or future files.
- The digest-bound ZIP closes pytest, its protected import namespaces and direct
  runtime dependencies. Application dependencies are not claimed hermetic:
  their exact host files are the declared TCB, revalidated and copied before
  each verifier run. The Python executable, exact validated stdlib import
  directories/ZIPs and loaded OS DLLs are also a declared host TCB; the generic
  `sys.base_prefix` root is excluded from child import authority. V15 does not
  claim a hermetic Python distribution.
- Internal Git compatibility implements only the frozen V13/V15 HEAD identity,
  fixed version identity and deterministic whitespace check needed by the
  historical suites. It does not certify or expose a general Git repository.

V15 remains unaccepted and default-off until three independent external reviews
pass. This checkpoint grants no Phase 5 exit or live activation.
"""
    checkpoint_md = CHECKPOINT / "PHASE5_2_APPROVAL_INBOX_V15_CHECKPOINT.md"
    write(checkpoint_md, checkpoint_text)

    historical: list[str] = []
    for version in range(1, 15):
        historical.extend(
            [
                f"core/approval_inbox_v{version}.py",
                f"tests/test_approval_inbox_v{version}.py",
                f"scripts/verify_phase5_approval_inbox_v{version}.py",
                f"scripts/check_phase5_approval_inbox_v{version}_whitespace.py",
                f"docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V{version}-001.sha256",
                f"docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V{version}-001.sha256",
                f"docs/onyx/checkpoints/phase5-approval-inbox-v{version}/PHASE5_2_APPROVAL_INBOX_V{version}_CHECKPOINT.md",
                f"docs/onyx/checkpoints/phase5-approval-inbox-v{version}/phase5-approval-inbox-v{version}.bundle.json",
            ]
        )
    v15_files = [
        "core/approval_inbox_v15.py",
        "tests/test_approval_inbox_v15.py",
        "scripts/build_phase5_approval_inbox_v15_evidence.py",
        "scripts/check_phase5_approval_inbox_v15_whitespace.py",
        "scripts/phase5_approval_inbox_v15_child.py",
        "scripts/phase5_approval_inbox_v15_historical_projection.py",
        "scripts/verify_phase5_approval_inbox_v15.py",
        "scripts/verify_phase5_approval_inbox_v15_worker.py",
        "docs/onyx/APPROVAL_POLICY.md",
        "docs/onyx/IMPLEMENTATION_ROADMAP.md",
        "docs/onyx/adrs/ADR-0003-capability-nexus-and-mcp.md",
        checkpoint_md.relative_to(ROOT).as_posix(),
        focused_junit.relative_to(ROOT).as_posix(),
        combined_junit.relative_to(ROOT).as_posix(),
        regressions_junit.relative_to(ROOT).as_posix(),
        "docs/onyx/checkpoints/phase5-approval-inbox-v15/phase5-approval-inbox-v15.raw.log",
        "docs/onyx/checkpoints/phase5-approval-inbox-v15/phase5-approval-inbox-v15.combined.log",
        "docs/onyx/checkpoints/phase5-approval-inbox-v15/phase5-approval-inbox-v15.regressions.log",
        "docs/onyx/checkpoints/phase5-approval-inbox-v15/phase5-approval-inbox-v15.static.log",
        "docs/onyx/checkpoints/phase5-approval-inbox-v15/phase5-approval-inbox-v15.live-scan.sha256",
        "docs/onyx/checkpoints/phase5-approval-inbox-v15/mutable-projections.json",
        PRIVATE_RUNTIME.relative_to(ROOT).as_posix(),
        *(entry["snapshot"] for entry in projections),
        *HISTORICAL_PROJECTIONS,
        *HISTORICAL_ROOT_AUTHORITIES,
    ]
    files = sorted(set(historical + v15_files))
    missing = [relative for relative in files if not (ROOT / relative).is_file()]
    if missing:
        raise SystemExit(f"missing evidence inputs: {missing}")
    file_hashes = {relative: sha(ROOT / relative) for relative in files}
    predecessor_bundle = json.loads(
        (
            ROOT
            / "docs/onyx/checkpoints/phase5-approval-inbox-v13/phase5-approval-inbox-v13.bundle.json"
        ).read_text(encoding="utf-8")
    )
    head = predecessor_bundle["base_commit"]
    pytest_version = runtime_versions["pytest"]
    bundle = {
        "contract": "Phase52ApprovalInboxEvidence.v15",
        "status": "candidate-default-off-external-acceptance-pending",
        "base_commit": head,
        "feature_flag": {
            "name": "ONYX_APPROVAL_INBOX_V15",
            "default": False,
            "bootstrap_only": True,
        },
        "counts": {
            "focused_passed": focused["passed"],
            "combined_passed": combined["passed"],
            "regression_passed": regression_passed,
            "regression_subtests": subtests,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
        },
        "claims": {
            "read_only_projection": True,
            "authority_always_false": True,
            "future_approval_reresolves_host_fields": True,
            "complete_action_context_binding": True,
            "terminal_state_invalidation": True,
            "snapshot_reuse_never_extends_ttl": True,
            "strict_pagination_and_review_proofs": True,
            "calm_batch_is_non_authoritative": True,
            "bounded_single_flight_callback_outside_lock": True,
            "no_live_wiring": True,
            "historical_v1_v11_preserved": True,
            "constant_cardinality_source_integrity": True,
            "ten_thousand_epoch_stress": True,
            "post_callback_terminal_precedence": True,
            "final_output_publication_barrier": True,
            "source_generation_rechecked_before_publication": True,
            "authoritative_paths_reject_reparse_components": True,
            "direct_v9_historical_projection_authority": True,
            "historical_root_inputs_direct_authority": True,
            "plugin_owned_temporary_outputs": True,
            "historical_projection_no_reparse_gate": True,
            "exclusive_nonpreexisting_output_targets": True,
            "temporary_cleanup_verified": True,
            "hermetic_git_fixture": True,
            "combined_process_sources_identity_bound": True,
            "child_exact_source_execution": True,
            "ambient_pytest_inputs_prohibited": True,
            "process_tree_global_deadline": True,
            "child_root_identity_validated_first": True,
            "private_digest_bound_pytest_runtime": True,
            "exclusive_clean_materialized_root": True,
            "workspace_execution_dependency_closure_hash_bound": True,
            "host_dependencies_copied_not_imported_from_site": True,
            "python_isolated_safe_path_no_site_no_bytecode": True,
            "module_origins_postrun_audited": True,
            "no_workspace_bytecode_read_or_written": True,
            "internal_static_gate_no_live_ruff": True,
            "absolute_validated_taskkill": True,
            "git_subprocess_eliminated": True,
            "git_environment_overrides_rejected": True,
            "external_acceptance_pending": True,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pytest": f"pytest {pytest_version}",
            "static_gate": "internal compile+AST+whitespace v1",
            "executable": sys.executable,
        },
        "mutable_projections": projections,
        "git_boundary": {
            "live_repository_consumed": False,
            "alternates_consumed": False,
            "hooks_consumed": False,
            "git_subprocess_used": False,
            "environment_overrides_consumed": False,
            "hermetic_head": "b2dc0b21f487013cebec34bb148ffb1aeb02611a",
        },
        "private_pytest_runtime": {
            "path": PRIVATE_RUNTIME.relative_to(ROOT).as_posix(),
            "sha256": runtime_digest,
            "manifest_sha256": runtime_manifest_digest,
            "file_count": runtime_file_count,
            "distributions": runtime_versions,
            "source_site_consumed_at_verification": False,
        },
        "python_host_tcb": python_tcb,
        "host_dependency_tcb": host_dependencies,
        "materialized_tree": workspace_materialization,
        "combined_process_sources": {
            module_name: {
                "path": relative,
                "sha256": file_hashes[relative],
            }
            for module_name, relative in process_guard.PROCESS_MODULE_SOURCES.items()
        },
        "live_scan_files": len(live_entries),
        "files": file_hashes,
    }
    bundle_path = CHECKPOINT / "phase5-approval-inbox-v15.bundle.json"
    write(bundle_path, json.dumps(bundle, sort_keys=True, separators=(",", ":")) + "\n")

    artifacts = dict(file_hashes)
    artifacts[bundle_path.relative_to(ROOT).as_posix()] = sha(bundle_path)
    write(
        ARTIFACTS,
        "".join(
            f"{digest}  {relative}\n" for relative, digest in sorted(artifacts.items())
        ),
    )
    write(SOURCE, f"{sha(ARTIFACTS)}  {ARTIFACTS.relative_to(ROOT).as_posix()}\n")
    DEPENDENCY_TCB_BUILD_CACHE.unlink(missing_ok=True)
    print(
        "P52_APPROVAL_INBOX_V15_BUILT "
        f"focused={focused['passed']} combined={combined['passed']} "
        f"regressions={regression_passed} subtests={subtests} "
        f"artifacts={len(artifacts)} root={sha(SOURCE)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
