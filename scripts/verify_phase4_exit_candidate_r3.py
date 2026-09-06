"""Sound, acyclic verifier for the Phase 4 E1-E5 R3 candidate.

The source policy is intentionally narrower than a general malware detector.
It rejects every literal authority-bearing module/leaf/path token in startup
sources, computes the complete local *static* import closure, and confirms the
actual current import set in a guarded offline subprocess.  Arbitrarily
obfuscated future code is not claimed solved by static analysis; any source
change is instead rejected by the externally reviewed source-manifest anchor.

Evidence has two one-way manifests.  The source manifest hashes the evidence
artifact manifest but not generated evidence.  The artifact manifest hashes
the bundle/source/JUnit/raw logs.  Neither manifest hashes itself; the source
manifest SHA is accepted externally only by a later E6 decision.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Mapping
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from core.control_plane import (  # noqa: E402
    CONTROL_PLANE_FLAG,
    ControlPlaneDisabled,
    ControlPlaneStore,
    control_plane_v1_enabled,
)
from core.control_plane_v3 import LEDGER_V3_FLAG, ledger_v3_enabled  # noqa: E402
from core.control_plane_v4 import CONTROL_PLANE_V4_FLAG, control_plane_v4_enabled  # noqa: E402
from core.control_plane_v5 import CONTROL_PLANE_V5_FLAG, control_plane_v5_enabled  # noqa: E402
from core.domain_ledger import M2A_DOMAIN_LEDGER_FLAG, m2a_domain_ledger_enabled  # noqa: E402
from core.ledger_anchor import LEDGER_ANCHOR_FLAG, ledger_anchor_enabled  # noqa: E402
from core.workspaces import (  # noqa: E402
    M1B_BACKFILL_FLAG,
    WORKSPACE_REGISTRY_FLAG,
    m1b_backfill_enabled,
    workspace_registry_enabled,
)
from scripts.verify_p44_scope import verify as verify_r10  # noqa: E402


AUTHORITY_BEARING = frozenset(
    {
        "core.control_plane",
        "core.control_plane_v3",
        "core.control_plane_v4",
        "core.control_plane_v5",
        "core.workspaces",
        "core.domain_ledger",
        "core.domain_ledger_v3",
        "core.ledger_anchor",
        "core.mission_context_contracts",
        "core.mission_context_v4",
        "core.mission_evidence_v5",
    }
)
# `core.native_vault` is intentionally absent.  It is an already integrated,
# side-effect-free primitive imported by credentials, not an authority-bearing
# Phase 4 service.
AUTHORITY_LEAVES = frozenset(module.rsplit(".", 1)[-1] for module in AUTHORITY_BEARING)
STARTUP_SOURCES = (
    PROJECT / "main.py",
    PROJECT / "ui.py",
    PROJECT / "dashboard/server.py",
    PROJECT / "dashboard/security.py",
)
STARTUP_MODULES = ("main", "ui", "dashboard.server", "dashboard.security")
R10_MANIFEST = PROJECT / "docs/onyx/VE-SCOPE-P44-R10-001.sha256"
R3_SOURCE_MANIFEST = PROJECT / "docs/onyx/VE-SCOPE-P4-E1E5-R3-001.sha256"
R3_EVIDENCE_MANIFEST = PROJECT / "docs/onyx/VE-ARTIFACTS-P4-E1E5-R3-001.sha256"
SELECTION_FILE = PROJECT / "tests/phase4_e1e5_r3_selection.txt"
R3_SOURCE_PATHS = frozenset(
    {
        "docs/onyx/CAPABILITY_MATRIX.md",
        "docs/onyx/VE-ARTIFACTS-P4-E1E5-R3-001.sha256",
        "docs/onyx/VE-SCOPE-P44-R10-001.sha256",
        "docs/onyx/checkpoints/phase4-e1-e5/PHASE4_E1_E5_CHECKPOINT_R3.md",
        "scripts/verify_phase4_exit_candidate_r3.py",
        "tests/phase4_e1e5_r3_selection.txt",
        "tests/test_control_plane.py",
        "tests/test_phase4_exit_candidate_r3.py",
        "tests/test_workspace_registry.py",
    }
)
R3_EVIDENCE_PATHS = frozenset(
    {
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-e1-e5-r3.bundle.json",
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-r3-pytest.log",
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-r3-safety.junit.xml",
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-r3-source.json",
        "docs/onyx/checkpoints/phase4-e1-e5/phase4-r3-static.log",
    }
)
_MANIFEST_LINE = re.compile(r"([0-9a-f]{64}) \*([^\r\n]+)")
_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(
        re.escape(value) for value in sorted(AUTHORITY_LEAVES, key=len, reverse=True)
    ) + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)

FlagReader = Callable[[Mapping[str, str] | None], bool]
FLAG_SPECS: tuple[tuple[str, FlagReader, frozenset[str]], ...] = (
    (CONTROL_PLANE_FLAG, control_plane_v1_enabled, frozenset({"1", "true"})),
    (WORKSPACE_REGISTRY_FLAG, workspace_registry_enabled, frozenset({"1", "true"})),
    (M1B_BACKFILL_FLAG, m1b_backfill_enabled, frozenset({"1", "true"})),
    (M2A_DOMAIN_LEDGER_FLAG, m2a_domain_ledger_enabled, frozenset({"1", "true"})),
    (LEDGER_ANCHOR_FLAG, ledger_anchor_enabled, frozenset({"1", "true"})),
    (LEDGER_V3_FLAG, ledger_v3_enabled, frozenset({"1", "true"})),
    (CONTROL_PLANE_V4_FLAG, control_plane_v4_enabled, frozenset({"1", "true", "yes", "on"})),
    (CONTROL_PLANE_V5_FLAG, control_plane_v5_enabled, frozenset({"1", "true"})),
)


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT.resolve()).as_posix()
    except (OSError, RuntimeError, ValueError):
        try:
            return path.resolve().as_posix()
        except (OSError, RuntimeError):
            return path.absolute().as_posix()


def _is_authority(module: str) -> bool:
    return module in AUTHORITY_BEARING or any(
        module.startswith(value + ".") for value in AUTHORITY_BEARING
    )


def _module_name(path: Path, root: Path = PROJECT) -> str:
    relative = path.resolve().relative_to(root.resolve())
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _module_candidates(module: str, root: Path = PROJECT) -> tuple[Path, ...]:
    if not module:
        return ()
    relative = Path(*module.split("."))
    candidates = (root / relative.with_suffix(".py"), root / relative / "__init__.py")
    return tuple(path.resolve() for path in candidates if path.is_file())


def _static_local_imports(path: Path, root: Path = PROJECT) -> set[Path]:
    label = display_path(path) if root == PROJECT else path.as_posix()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=label)
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise RuntimeError(f"cannot parse local source: {label}") from exc
    current = _module_name(path, root).split(".")
    found: set[Path] = set()
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = current[:-node.level]
                if node.module:
                    base.extend(node.module.split("."))
                module = ".".join(base)
            else:
                module = node.module or ""
            if module:
                modules.append(module)
                modules.extend(
                    module + "." + alias.name
                    for alias in node.names
                    if alias.name != "*"
                )
        for module in modules:
            found.update(_module_candidates(module, root))
            pieces = module.split(".")
            for index in range(1, len(pieces)):
                initializer = root.joinpath(*pieces[:index], "__init__.py")
                if initializer.is_file():
                    found.add(initializer.resolve())
    return found


def static_import_closure(
    roots: Iterable[Path] = STARTUP_SOURCES, project: Path = PROJECT
) -> set[Path]:
    closure = {path.resolve() for path in roots}
    pending = list(closure)
    while pending:
        path = pending.pop()
        for dependency in _static_local_imports(path, project):
            if dependency not in closure:
                closure.add(dependency)
                pending.append(dependency)
    return closure


def _fold_strings(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _fold_strings(node.left) + _fold_strings(node.right)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return " ".join(_fold_strings(element) for element in node.elts)
    if isinstance(node, ast.Dict):
        return " ".join(
            _fold_strings(value)
            for pair in zip(node.keys, node.values)
            for value in pair
            if value is not None
        )
    return ""


def verify_root_token_policy(sources: Iterable[Path] = STARTUP_SOURCES) -> list[str]:
    checked: list[str] = []
    dynamic_names = {
        "__import__", "import_module", "run_module", "run_path",
        "exec", "eval", "compile", "Popen", "run", "call", "check_call", "check_output",
    }
    for path in sources:
        label = display_path(path)
        if not path.is_file():
            raise RuntimeError(f"missing startup source: {label}")
        source = path.read_text(encoding="utf-8")
        token = _TOKEN.search(source)
        if token:
            raise RuntimeError(f"authority token forbidden in startup source {label}: {token.group(1)}")
        try:
            tree = ast.parse(source, filename=label)
        except SyntaxError as exc:
            raise RuntimeError(f"cannot parse startup source: {label}") from exc
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            folded = " ".join(_fold_strings(value) for value in (*node.args, *node.keywords))
            if name in dynamic_names and _TOKEN.search(folded):
                raise RuntimeError(
                    f"authority target passed to dynamic API in startup source {label}:{node.lineno}"
                )
        checked.append(label)
    return checked


def verify_static_authority_closure(
    roots: Iterable[Path] = STARTUP_SOURCES, project: Path = PROJECT
) -> dict[str, object]:
    closure = static_import_closure(roots, project)
    modules = sorted(_module_name(path, project) for path in closure)
    authority = sorted(module for module in modules if _is_authority(module))
    if authority:
        raise RuntimeError(f"authority-bearing module in startup static closure: {authority}")
    return {
        "files": len(closure),
        "modules_sha256": hashlib.sha256(("\n".join(modules) + "\n").encode()).hexdigest(),
        "native_vault_present": "core.native_vault" in modules,
    }


def verify_fresh_import_probe(timeout_seconds: int = 45) -> dict[str, object]:
    child = (
        "import importlib,json,os,socket,subprocess,sys\n"
        f"sys.path.insert(0,{str(PROJECT)!r})\n"
        "def blocked(*a,**k): raise RuntimeError('offline import probe blocked side effect')\n"
        "socket.create_connection=blocked\n"
        "socket.socket.connect=blocked\n"
        "class OfflinePopen(subprocess.Popen):\n"
        " def __init__(self,*a,**k): blocked(*a,**k)\n"
        "subprocess.Popen=OfflinePopen\n"
        f"targets={list(STARTUP_MODULES)!r}\n"
        f"authority={sorted(AUTHORITY_BEARING)!r}\n"
        "[importlib.import_module(name) for name in targets]\n"
        "seen=sorted(name for name in sys.modules if name in authority or any(name.startswith(x+'.') for x in authority))\n"
        "print('ONYX_R3_IMPORT_PROBE '+json.dumps({'authority':seen,'loaded':targets},sort_keys=True))\n"
        "raise SystemExit(2 if seen else 0)\n"
    )
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["QT_QPA_PLATFORM"] = "offscreen"
    for name, _reader, _accepted in FLAG_SPECS:
        environment[name] = "0"
    command = [sys.executable, "-I", "-c", child]
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("fresh startup import probe timed out") from exc
    marker = "ONYX_R3_IMPORT_PROBE "
    line = next((line for line in result.stdout.splitlines() if line.startswith(marker)), None)
    if result.returncode or line is None:
        raise RuntimeError(
            f"fresh startup import probe failed: exit={result.returncode} stderr={result.stderr[-500:]}"
        )
    payload = json.loads(line[len(marker):])
    if payload.get("authority"):
        raise RuntimeError(f"fresh startup import loaded authority modules: {payload['authority']}")
    return {"loaded": payload["loaded"], "authority": [], "offline_guarded": True}


def _safe_path(root: Path, relative: str) -> Path:
    if "\\" in relative or relative.startswith(("/", "~")):
        raise RuntimeError(f"unsafe manifest path: {relative}")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise RuntimeError(f"unsafe manifest path: {relative}")
    path = root.joinpath(*pure.parts).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"manifest path escapes root: {relative}") from exc
    return path


def verify_manifest(
    manifest: Path, expected_paths: frozenset[str], *, root: Path = PROJECT
) -> tuple[int, str]:
    try:
        raw = manifest.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"cannot read manifest: {display_path(manifest)}") from exc
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise RuntimeError("manifest encoding/newlines are not canonical")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise RuntimeError("manifest is not UTF-8") from exc
    records: dict[str, str] = {}
    for line in lines:
        match = _MANIFEST_LINE.fullmatch(line)
        if match is None or match.group(2) in records:
            raise RuntimeError("manifest line malformed or duplicated")
        records[match.group(2)] = match.group(1)
    if list(records) != sorted(records):
        raise RuntimeError("manifest paths are not ordinally sorted")
    if set(records) != expected_paths:
        raise RuntimeError(
            f"manifest exact-set mismatch: missing={sorted(expected_paths-set(records))}, "
            f"extra={sorted(set(records)-expected_paths)}"
        )
    for relative, expected in records.items():
        actual = hashlib.sha256(_safe_path(root, relative).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"manifest digest mismatch: {relative}")
    return len(records), hashlib.sha256(raw).hexdigest()


def _manifest_paths(manifest: Path) -> set[str]:
    paths: set[str] = set()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        match = _MANIFEST_LINE.fullmatch(line)
        if match:
            paths.add(match.group(2))
    return paths


def parse_selection(path: Path = SELECTION_FILE) -> tuple[list[str], set[str]]:
    nodes: list[str] = []
    sources: set[str] = set()
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        source = line.split("::", 1)[0].replace("\\", "/")
        if not source.startswith("tests/") or not source.endswith(".py") or line.startswith("-"):
            raise RuntimeError(f"invalid R3 selection line {number}: {line}")
        if line in nodes:
            raise RuntimeError(f"duplicate R3 selection line: {line}")
        if not (PROJECT / source).is_file():
            raise RuntimeError(f"missing R3 selected source: {source}")
        nodes.append(line)
        sources.add(source)
    if not nodes:
        raise RuntimeError("R3 selection is empty")
    return nodes, sources


def verify_selection_scope(
    *, selection: Path = SELECTION_FILE, r3_paths: frozenset[str] = R3_SOURCE_PATHS
) -> dict[str, int]:
    nodes, sources = parse_selection(selection)
    r10_paths = _manifest_paths(R10_MANIFEST)
    missing = sorted(sources - (r10_paths | set(r3_paths)))
    if missing:
        raise RuntimeError(f"selected test source absent from R10+R3 scope: {missing}")
    return {"nodes": len(nodes), "sources": len(sources)}


def verify_default_off(require_process_flags_off: bool = True) -> list[str]:
    checked: list[str] = []
    for name, reader, accepted in FLAG_SPECS:
        if reader({}):
            raise RuntimeError(f"flag does not default off: {name}")
        for value in accepted:
            if not reader({name: value}):
                raise RuntimeError(f"flag lost opt-in value: {name}")
        if require_process_flags_off and reader(os.environ):
            raise RuntimeError(f"flag enabled in verifier process: {name}")
        checked.append(name)
    return checked


def verify_disabled_v1_zero_write() -> str:
    with tempfile.TemporaryDirectory(prefix="onyx-r3-") as temporary:
        root = Path(temporary) / "absent"
        with patch("core.control_plane.private_control_plane_runtime_dir", return_value=root):
            store = ControlPlaneStore(enabled=False)
            try:
                store.initialize()
            except ControlPlaneDisabled:
                pass
            else:
                raise RuntimeError("disabled V1 initialized")
        if root.exists():
            raise RuntimeError("disabled V1 wrote isolated path")
    return "disabled-v1-zero-write"


def verify_source_only() -> dict[str, object]:
    r10_count, _r10_sha = verify_r10(R10_MANIFEST)
    return {
        "activation": False,
        "e6_accepted": False,
        "flags_default_off": verify_default_off(),
        "fresh_import_probe": verify_fresh_import_probe(),
        "owner_write_probe": verify_disabled_v1_zero_write(),
        "r10_files": r10_count,
        "root_token_sources": verify_root_token_policy(),
        "selection": verify_selection_scope(),
        "static_closure": verify_static_authority_closure(),
        "status": "P4_EXIT_CANDIDATE_R3_SOURCE_OK",
    }


def verify_frozen() -> dict[str, object]:
    source_count, _source_sha = verify_manifest(R3_SOURCE_MANIFEST, R3_SOURCE_PATHS)
    evidence_count, _evidence_sha = verify_manifest(R3_EVIDENCE_MANIFEST, R3_EVIDENCE_PATHS)
    result = verify_source_only()
    result.update(
        {
            "source_manifest_files": source_count,
            "evidence_manifest_files": evidence_count,
            "external_source_anchor": False,
            "status": "P4_EXIT_CANDIDATE_R3_FROZEN_OK",
        }
    )
    return result


def _write_output(path: Path | None, result: dict[str, object]) -> None:
    payload = json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload.encode("utf-8"))
    print(payload, end="")


def _raw_log(path: Path, command: list[str], result: subprocess.CompletedProcess[str], seconds: float) -> None:
    body = (
        "COMMAND " + subprocess.list2cmdline(command) + "\n"
        + f"EXIT {result.returncode}\nDURATION_SECONDS {seconds:.6f}\n"
        + "STDOUT\n" + result.stdout
        + ("\n" if result.stdout and not result.stdout.endswith("\n") else "")
        + "STDERR\n" + result.stderr
        + ("\n" if result.stderr and not result.stderr.endswith("\n") else "")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.encode("utf-8"))


def run_tests(junitxml: Path, basetemp: Path, raw_log: Path) -> int:
    nodes, _sources = parse_selection()
    command = [
        sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "--basetemp", str(basetemp), "--junitxml", str(junitxml), *nodes,
    ]
    started = time.perf_counter()
    result = subprocess.run(
        command, cwd=PROJECT, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False,
    )
    _raw_log(raw_log, command, result, time.perf_counter() - started)
    print(result.stdout, end=""); print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def run_static(raw_log: Path) -> int:
    commands = (
        [sys.executable, "-m", "ruff", "check", "scripts/verify_phase4_exit_candidate_r3.py", "tests/test_phase4_exit_candidate_r3.py", "--select", "F,E9"],
        [sys.executable, "-m", "py_compile", "scripts/verify_phase4_exit_candidate_r3.py", "tests/test_phase4_exit_candidate_r3.py"],
        ["git", "diff", "--check"],
    )
    started = time.perf_counter(); sections: list[str] = []; exit_code = 0
    for command in commands:
        command_started = time.perf_counter()
        result = subprocess.run(
            command, cwd=PROJECT, text=True, encoding="utf-8", errors="replace",
            capture_output=True, check=False,
        )
        sections.append(
            "COMMAND " + subprocess.list2cmdline(command) + "\n"
            + f"EXIT {result.returncode}\nDURATION_SECONDS {time.perf_counter()-command_started:.6f}\n"
            + "STDOUT\n" + result.stdout + "STDERR\n" + result.stderr
        )
        if result.returncode and not exit_code: exit_code = result.returncode
    body = f"EXIT {exit_code}\nDURATION_SECONDS {time.perf_counter()-started:.6f}\n" + "".join(sections)
    raw_log.parent.mkdir(parents=True, exist_ok=True); raw_log.write_bytes(body.encode("utf-8"))
    print(body, end=""); return exit_code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", choices=("source", "frozen", "test", "static"), default="frozen")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--junitxml", type=Path)
    parser.add_argument("--basetemp", type=Path)
    parser.add_argument("--raw-log", type=Path)
    args = parser.parse_args()
    if args.gate == "test":
        if args.junitxml is None or args.basetemp is None or args.raw_log is None:
            parser.error("test requires --junitxml --basetemp --raw-log")
        return run_tests(args.junitxml, args.basetemp, args.raw_log)
    if args.gate == "static":
        if args.raw_log is None: parser.error("static requires --raw-log")
        return run_static(args.raw_log)
    result = verify_source_only() if args.gate == "source" else verify_frozen()
    _write_output(args.output, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
