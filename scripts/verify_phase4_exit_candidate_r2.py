"""Read-only verifier for the Phase 4 E1-E5 R2 checkpoint candidate.

Startup policy is intentionally fail-closed: startup sources may not use
dynamic import or dynamic execution primitives at all.  They also may not
read an enhanced-module source by a literal path.  Enhanced modules remain
available only to explicit, isolated test/application-service construction;
they are not runtime startup plugins until a later E6 decision.

The R2 scope manifest hashes its exact input set but never hashes itself.
Generated logs/bundles also stay outside the input manifest and carry their own
hashes.  The manifest SHA is only an observation until an E6 reviewer records
it in a separate accepted evidence register.
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
from typing import Callable, Mapping
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
from core.control_plane_v4 import (  # noqa: E402
    CONTROL_PLANE_V4_FLAG,
    control_plane_v4_enabled,
)
from core.control_plane_v5 import (  # noqa: E402
    CONTROL_PLANE_V5_FLAG,
    control_plane_v5_enabled,
)
from core.domain_ledger import (  # noqa: E402
    M2A_DOMAIN_LEDGER_FLAG,
    m2a_domain_ledger_enabled,
)
from core.ledger_anchor import (  # noqa: E402
    LEDGER_ANCHOR_FLAG,
    ledger_anchor_enabled,
)
from core.workspaces import (  # noqa: E402
    M1B_BACKFILL_FLAG,
    WORKSPACE_REGISTRY_FLAG,
    m1b_backfill_enabled,
    workspace_registry_enabled,
)
from scripts.verify_p44_scope import verify as verify_r10  # noqa: E402


R10_MANIFEST = PROJECT / "docs/onyx/VE-SCOPE-P44-R10-001.sha256"
R2_MANIFEST = PROJECT / "docs/onyx/VE-SCOPE-P4-E1E5-R2-001.sha256"
SELECTION_FILE = PROJECT / "tests/phase4_e1e5_r2_selection.txt"
STARTUP_SOURCES = (
    PROJECT / "main.py",
    PROJECT / "ui.py",
    PROJECT / "dashboard/server.py",
    PROJECT / "dashboard/security.py",
)
ENHANCED_MODULES = frozenset(
    {
        "core.control_plane",
        "core.control_plane_v3",
        "core.control_plane_v4",
        "core.control_plane_v5",
        "core.domain_ledger",
        "core.domain_ledger_v3",
        "core.ledger_anchor",
        "core.mission_context_v4",
        "core.mission_evidence_v5",
        "core.native_vault",
        "core.workspaces",
    }
)
ENHANCED_SOURCE_PATHS = frozenset(
    module.replace(".", "/") + ".py" for module in ENHANCED_MODULES
)
EXPECTED_R2_PATHS = frozenset(
    {
        "docs/onyx/CAPABILITY_MATRIX.md",
        "docs/onyx/VE-SCOPE-P44-R10-001.sha256",
        "docs/onyx/checkpoints/phase4-e1-e5/PHASE4_E1_E5_CHECKPOINT_R2.md",
        "scripts/verify_phase4_exit_candidate_r2.py",
        "tests/phase4_e1e5_r2_selection.txt",
        "tests/test_phase4_exit_candidate_r2.py",
    }
)
_MANIFEST_LINE = re.compile(r"([0-9a-f]{64}) \*([^\r\n]+)")

FlagReader = Callable[[Mapping[str, str] | None], bool]
FLAG_SPECS: tuple[tuple[str, FlagReader, frozenset[str]], ...] = (
    (CONTROL_PLANE_FLAG, control_plane_v1_enabled, frozenset({"1", "true"})),
    (WORKSPACE_REGISTRY_FLAG, workspace_registry_enabled, frozenset({"1", "true"})),
    (M1B_BACKFILL_FLAG, m1b_backfill_enabled, frozenset({"1", "true"})),
    (M2A_DOMAIN_LEDGER_FLAG, m2a_domain_ledger_enabled, frozenset({"1", "true"})),
    (LEDGER_ANCHOR_FLAG, ledger_anchor_enabled, frozenset({"1", "true"})),
    (LEDGER_V3_FLAG, ledger_v3_enabled, frozenset({"1", "true"})),
    (
        CONTROL_PLANE_V4_FLAG,
        control_plane_v4_enabled,
        frozenset({"1", "true", "yes", "on"}),
    ),
    (CONTROL_PLANE_V5_FLAG, control_plane_v5_enabled, frozenset({"1", "true"})),
)


def display_path(path: Path) -> str:
    """Render in-project paths relatively and external paths safely."""
    try:
        return path.resolve().relative_to(PROJECT.resolve()).as_posix()
    except (OSError, RuntimeError, ValueError):
        try:
            return path.resolve().as_posix()
        except (OSError, RuntimeError):
            return path.absolute().as_posix()


def _enhanced_module(name: str) -> bool:
    return name in ENHANCED_MODULES or any(
        name.startswith(module + ".") for module in ENHANCED_MODULES
    )


def _literal_text(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and all(
        isinstance(value, ast.Constant) and isinstance(value.value, str)
        for value in node.values
    ):
        return "".join(value.value for value in node.values)  # type: ignore[union-attr]
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Add)):
        left = _literal_text(node.left)
        right = _literal_text(node.right)
        if left is not None and right is not None:
            separator = "/" if isinstance(node.op, ast.Div) else ""
            return left.rstrip("/\\") + separator + right.lstrip("/\\")
    if isinstance(node, ast.Call) and node.args:
        name = node.func.id if isinstance(node.func, ast.Name) else ""
        if name in {"Path", "PurePath", "PurePosixPath", "PureWindowsPath"}:
            return _literal_text(node.args[0])
    return None


def _enhanced_source_path(value: str) -> bool:
    normalized = value.replace("\\", "/").casefold()
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    normalized = normalized.removeprefix("./")
    return any(
        normalized == source.casefold()
        or normalized.endswith("/" + source.casefold())
        for source in ENHANCED_SOURCE_PATHS
    )


class StartupPolicyScanner(ast.NodeVisitor):
    """Detect authority wiring and every forbidden dynamic execution seam."""

    _DYNAMIC_APIS = frozenset(
        {
            "builtins.__import__",
            "importlib.import_module",
            "runpy.run_module",
            "runpy.run_path",
            "builtins.exec",
            "builtins.eval",
            "builtins.compile",
        }
    )
    _PATH_READS = frozenset(
        {"open", "read_text", "read_bytes", "readlink", "read", "readlines"}
    )

    def __init__(self, path: Path, tree: ast.AST):
        self.path = path
        self.tree = tree
        self.module_aliases: dict[str, str] = {
            "builtins": "builtins",
            "importlib": "importlib",
            "runpy": "runpy",
            "pathlib": "pathlib",
        }
        self.path_constructors = {"Path", "PurePath", "PurePosixPath", "PureWindowsPath"}
        self.call_aliases: dict[str, str] = {
            "__import__": "builtins.__import__",
            "exec": "builtins.exec",
            "eval": "builtins.eval",
            "compile": "builtins.compile",
        }
        self.errors: list[str] = []
        self._collect_aliases()

    def _error(self, node: ast.AST, message: str) -> None:
        self.errors.append(f"{display_path(self.path)}:{getattr(node, 'lineno', 0)}: {message}")

    def _resolve_callable(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return self.call_aliases.get(node.id)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            module = self.module_aliases.get(node.value.id)
            if module:
                return f"{module}.{node.attr}"
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
        ):
            module = self.module_aliases.get(node.args[0].id)
            attribute = _literal_text(node.args[1])
            if module and attribute:
                return f"{module}.{attribute}"
        return None

    def _collect_aliases(self) -> None:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".", 1)[0]
                    if alias.name in {"builtins", "importlib", "runpy", "pathlib"}:
                        self.module_aliases[local] = alias.name
            elif isinstance(node, ast.ImportFrom) and node.module == "pathlib":
                for alias in node.names:
                    if alias.name in {"Path", "PurePath", "PurePosixPath", "PureWindowsPath"}:
                        self.path_constructors.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module in {
                "builtins",
                "importlib",
                "runpy",
            }:
                for alias in node.names:
                    local = alias.asname or alias.name
                    target = f"{node.module}.{alias.name}"
                    if target in self._DYNAMIC_APIS:
                        self.call_aliases[local] = target
        changed = True
        while changed:
            changed = False
            for node in ast.walk(self.tree):
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                value = node.value
                if value is None:
                    continue
                resolved = self._resolve_callable(value)
                if resolved not in self._DYNAMIC_APIS:
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and self.call_aliases.get(target.id) != resolved:
                        self.call_aliases[target.id] = resolved
                        changed = True

    def _literal_path(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Add)):
            left = self._literal_path(node.left)
            right = self._literal_path(node.right)
            if left is not None and right is not None:
                separator = "/" if isinstance(node.op, ast.Div) else ""
                return left.rstrip("/\\") + separator + right.lstrip("/\\")
        if isinstance(node, ast.Call) and node.args:
            constructor = False
            if isinstance(node.func, ast.Name):
                constructor = node.func.id in self.path_constructors
            elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                constructor = (
                    self.module_aliases.get(node.func.value.id) == "pathlib"
                    and node.func.attr in {"Path", "PurePath", "PurePosixPath", "PureWindowsPath"}
                )
            if constructor:
                return self._literal_path(node.args[0])
        return None

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if _enhanced_module(alias.name):
                self._error(node, f"enhanced static import forbidden: {alias.name}")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        if _enhanced_module(module):
            self._error(node, f"enhanced static import forbidden: {module}")
        if module == "core":
            for alias in node.names:
                candidate = f"core.{alias.name}"
                if _enhanced_module(candidate):
                    self._error(node, f"enhanced package import forbidden: {candidate}")

    def visit_Call(self, node: ast.Call) -> None:
        resolved = self._resolve_callable(node.func)
        if resolved in self._DYNAMIC_APIS:
            self._error(node, f"dynamic execution forbidden by startup policy: {resolved}")

        literal: str | None = None
        if isinstance(node.func, ast.Name) and node.func.id == "open" and node.args:
            literal = self._literal_path(node.args[0])
        elif isinstance(node.func, ast.Attribute) and node.func.attr in self._PATH_READS:
            literal = self._literal_path(node.func.value)
        if literal is not None and _enhanced_source_path(literal):
            self._error(node, f"enhanced module source read forbidden: {literal}")
        self.generic_visit(node)

    def verify(self) -> list[str]:
        self.visit(self.tree)
        return self.errors


def verify_startup_boundary(sources: tuple[Path, ...] = STARTUP_SOURCES) -> list[str]:
    checked: list[str] = []
    errors: list[str] = []
    for path in sources:
        label = display_path(path)
        if not path.is_file():
            raise RuntimeError(f"missing startup source: {label}")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=label)
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise RuntimeError(f"cannot parse startup source: {label}") from exc
        errors.extend(StartupPolicyScanner(path, tree).verify())
        checked.append(label)
    if errors:
        raise RuntimeError("startup policy violation: " + " | ".join(errors))
    return checked


def verify_default_off(*, require_process_flags_off: bool = True) -> list[str]:
    checked: list[str] = []
    for name, reader, accepted in FLAG_SPECS:
        if reader({}):
            raise RuntimeError(f"feature flag does not default off: {name}")
        for value in ("0", "false", "disabled", "2", "true-ish"):
            if reader({name: value}):
                raise RuntimeError(f"feature flag accepts unknown value: {name}")
        for value in accepted:
            if not reader({name: value}):
                raise RuntimeError(f"feature flag lost explicit opt-in: {name}")
        if require_process_flags_off and reader(os.environ):
            raise RuntimeError(f"feature flag enabled in verifier process: {name}")
        checked.append(name)
    return checked


def verify_disabled_owner_write_boundary() -> str:
    with tempfile.TemporaryDirectory(prefix="onyx-p4-r2-") as temporary:
        root = Path(temporary) / "isolated-root-must-not-exist"
        with patch("core.control_plane.private_control_plane_runtime_dir", return_value=root):
            store = ControlPlaneStore(enabled=False)
            try:
                store.initialize()
            except ControlPlaneDisabled:
                pass
            else:  # pragma: no cover
                raise RuntimeError("disabled control plane initialized")
            finally:
                store.close()
        if root.exists():
            raise RuntimeError("disabled control plane wrote an isolated path")
    return "disabled-v1-zero-writes"


def _safe_manifest_path(relative: str) -> Path:
    if "\\" in relative or relative.startswith(("/", "~")):
        raise RuntimeError(f"unsafe manifest path: {relative}")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise RuntimeError(f"unsafe manifest path: {relative}")
    path = (PROJECT / Path(*pure.parts)).resolve()
    try:
        path.relative_to(PROJECT.resolve())
    except ValueError as exc:
        raise RuntimeError(f"manifest path escapes project: {relative}") from exc
    return path


def verify_r2_manifest(manifest: Path = R2_MANIFEST) -> tuple[int, str]:
    try:
        raw = manifest.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"cannot read R2 manifest: {display_path(manifest)}") from exc
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise RuntimeError("R2 manifest encoding/newlines are not canonical")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise RuntimeError("R2 manifest is not UTF-8") from exc
    records: dict[str, str] = {}
    for line in lines:
        match = _MANIFEST_LINE.fullmatch(line)
        if match is None or match.group(2) in records:
            raise RuntimeError("R2 manifest line malformed or duplicated")
        records[match.group(2)] = match.group(1)
    if list(records) != sorted(records):
        raise RuntimeError("R2 manifest paths are not ordinally sorted")
    if set(records) != EXPECTED_R2_PATHS:
        missing = sorted(EXPECTED_R2_PATHS - set(records))
        extra = sorted(set(records) - EXPECTED_R2_PATHS)
        raise RuntimeError(f"R2 manifest exact-set mismatch: missing={missing}, extra={extra}")
    for relative, expected in records.items():
        actual = hashlib.sha256(_safe_manifest_path(relative).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"R2 manifest digest mismatch: {relative}")
    return len(records), hashlib.sha256(raw).hexdigest()


def verify_all(*, require_process_flags_off: bool = True) -> dict[str, object]:
    r10_count, r10_sha = verify_r10(R10_MANIFEST)
    r2_count, r2_sha = verify_r2_manifest(R2_MANIFEST)
    return {
        "activation": False,
        "e6_accepted": False,
        "flags_default_off": verify_default_off(
            require_process_flags_off=require_process_flags_off
        ),
        "owner_write_probe": verify_disabled_owner_write_boundary(),
        "r10_files": r10_count,
        "r10_manifest_sha256": r10_sha,
        "r2_files": r2_count,
        "r2_manifest_observed_sha256": r2_sha,
        "r2_manifest_external_anchor": False,
        "startup_sources": verify_startup_boundary(),
        "status": "P4_EXIT_CANDIDATE_R2_SOURCE_OK",
    }


def _write_raw_log(
    path: Path,
    command: list[str],
    result: subprocess.CompletedProcess[str],
    seconds: float,
) -> None:
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


def run_selected_tests(*, junitxml: Path, basetemp: Path, raw_log: Path) -> int:
    nodes = [
        line.strip()
        for line in SELECTION_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        str(basetemp),
        "--junitxml",
        str(junitxml),
        *nodes,
    ]
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=PROJECT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    _write_raw_log(raw_log, command, result, time.perf_counter() - started)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode


def run_static_gate(*, raw_log: Path) -> int:
    commands = (
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "scripts/verify_phase4_exit_candidate_r2.py",
            "tests/test_phase4_exit_candidate_r2.py",
            "--select",
            "F,E9",
        ],
        [
            sys.executable,
            "-m",
            "py_compile",
            "scripts/verify_phase4_exit_candidate_r2.py",
            "tests/test_phase4_exit_candidate_r2.py",
        ],
        ["git", "diff", "--check"],
    )
    started = time.perf_counter()
    sections: list[str] = []
    exit_code = 0
    for command in commands:
        command_started = time.perf_counter()
        result = subprocess.run(
            command,
            cwd=PROJECT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        sections.append(
            "COMMAND " + subprocess.list2cmdline(command) + "\n"
            + f"EXIT {result.returncode}\n"
            + f"DURATION_SECONDS {time.perf_counter() - command_started:.6f}\n"
            + "STDOUT\n" + result.stdout
            + ("\n" if result.stdout and not result.stdout.endswith("\n") else "")
            + "STDERR\n" + result.stderr
            + ("\n" if result.stderr and not result.stderr.endswith("\n") else "")
        )
        if result.returncode and not exit_code:
            exit_code = result.returncode
    body = (
        f"EXIT {exit_code}\nDURATION_SECONDS {time.perf_counter() - started:.6f}\n"
        + "".join(sections)
    )
    raw_log.parent.mkdir(parents=True, exist_ok=True)
    raw_log.write_bytes(body.encode("utf-8"))
    print(body, end="")
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate", choices=("verify", "test", "static"), default="verify")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-enabled-process-flag", action="store_true")
    parser.add_argument("--junitxml", type=Path)
    parser.add_argument("--basetemp", type=Path)
    parser.add_argument("--raw-log", type=Path)
    args = parser.parse_args()
    if args.gate == "test":
        if args.junitxml is None or args.basetemp is None or args.raw_log is None:
            parser.error("test gate requires --junitxml, --basetemp and --raw-log")
        return run_selected_tests(
            junitxml=args.junitxml,
            basetemp=args.basetemp,
            raw_log=args.raw_log,
        )
    if args.gate == "static":
        if args.raw_log is None:
            parser.error("static gate requires --raw-log")
        return run_static_gate(raw_log=args.raw_log)
    result = verify_all(
        require_process_flags_off=not args.allow_enabled_process_flag
    )
    payload = json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
    if args.output is not None:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload.encode("utf-8"))
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
