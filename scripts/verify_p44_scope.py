"""Verify the immutable P4.4 checkpoint source universe and dependency closure."""
from __future__ import annotations

import argparse
import ast
import hashlib
import re
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()
PRODUCT_PYTHON_DIRS = ("core", "memory", "actions", "dashboard", "config")
TOP_LEVEL_PRODUCT_SOURCES = frozenset({"main.py", "ui.py"})
FOCUSED_TESTS = frozenset({
    "tests/p44_v5_support.py",
    "tests/test_artifact_service.py",
    "tests/test_control_plane_v5.py",
    "tests/test_control_plane_v5_adversarial.py",
    "tests/test_mission_context_v4.py",
    "tests/test_mission_evidence_v5.py",
    "tests/test_mission_evidence_v5_artifacts.py",
    "tests/test_verify_p44_scope.py",
})
# Immutable, shipped inputs consumed by the scoped runtime sources. Mutable owner
# configuration, generated certificates and runtime databases are intentionally
# excluded: they are owner/runtime state, not source evidence.
RUNTIME_INPUTS = frozenset({
    "config/onyx.ico",
    "core/prompt.txt",
    "dashboard/static/app.html",
    "dashboard/static/crypto-js.min.js",
    "dashboard/static/login.html",
    "qml/OnyxOrb.qml",
})
_LINE = re.compile(r"([0-9a-f]{64}) \*([^\r\n]+)")


def _relative(path: Path) -> str:
    return path.resolve().relative_to(PROJECT).as_posix()


def _module_name(path: Path) -> str:
    relative = path.relative_to(PROJECT)
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    if parts and parts[0] == "tests":
        parts.pop(0)
    return ".".join(parts)


def _module_candidates(module: str) -> tuple[Path, ...]:
    if not module:
        return ()
    relative = Path(*module.split("."))
    candidates = [PROJECT / relative.with_suffix(".py"), PROJECT / relative / "__init__.py"]
    # Pytest makes the tests directory importable as a top-level module.
    candidates.extend(
        (PROJECT / "tests" / relative.with_suffix(".py"),
         PROJECT / "tests" / relative / "__init__.py")
    )
    return tuple(candidate for candidate in candidates if candidate.is_file())


def _local_namespaces() -> set[str]:
    """Return local roots at verification time, including newly added sources."""
    return {
        path.name
        for path in PROJECT.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    } | {path.stem for path in PROJECT.glob("*.py")} | {
        path.stem for path in (PROJECT / "tests").glob("*.py")
    }


def _mandatory_inputs() -> set[Path]:
    """Enumerate the checkpoint's product sources independently of imports."""
    paths: set[Path] = set()
    missing_directories: list[str] = []
    for relative in PRODUCT_PYTHON_DIRS:
        directory = PROJECT / relative
        if not directory.is_dir():
            missing_directories.append(relative)
            continue
        paths.update(path.resolve() for path in directory.rglob("*.py"))
    if missing_directories:
        raise RuntimeError(
            "missing required product source directory: "
            + ", ".join(sorted(missing_directories))
        )
    paths.update((PROJECT / relative).resolve() for relative in TOP_LEVEL_PRODUCT_SOURCES)
    paths.update((PROJECT / relative).resolve() for relative in FOCUSED_TESTS)
    paths.update((PROJECT / relative).resolve() for relative in RUNTIME_INPUTS)
    paths.add(SELF.resolve())
    missing = sorted(_relative(path) for path in paths if not path.is_file())
    if missing:
        raise RuntimeError("missing required scope input: " + ", ".join(missing))
    return paths


def _root_inputs() -> set[Path]:
    return _mandatory_inputs()


def _dynamic_import_modules(tree: ast.AST, path: Path) -> set[str]:
    """Find literal local imports hidden behind Python's dynamic import APIs."""
    importlib_names = {"importlib"}
    import_module_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "importlib":
                    importlib_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "importlib":
            for alias in node.names:
                if alias.name == "import_module":
                    import_module_names.add(alias.asname or alias.name)

    current = _module_name(path).split(".") if _module_name(path) else []
    modules: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function = node.func
        is_dynamic_import = (
            isinstance(function, ast.Name)
            and function.id in ({"__import__"} | import_module_names)
        ) or (
            isinstance(function, ast.Attribute)
            and function.attr == "import_module"
            and isinstance(function.value, ast.Name)
            and function.value.id in importlib_names
        )
        if not is_dynamic_import:
            continue
        literal = node.args[0]
        if not isinstance(literal, ast.Constant) or not isinstance(literal.value, str):
            continue
        module = literal.value
        if module.startswith("."):
            level = len(module) - len(module.lstrip("."))
            base = current[:-level]
            tail = module[level:]
            if tail:
                base.extend(tail.split("."))
            module = ".".join(base)
        if module:
            modules.add(module)
    return modules


def _local_imports(path: Path) -> set[Path]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise RuntimeError(f"cannot parse {_relative(path)}") from exc
    current = _module_name(path).split(".") if _module_name(path) else []
    found: set[Path] = set()
    discovered: list[tuple[str, bool]] = []
    for node in ast.walk(tree):
        modules: list[tuple[str, bool]] = []
        if isinstance(node, ast.Import):
            modules.extend((alias.name, True) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = current[:-node.level]
                if node.module:
                    base.extend(node.module.split("."))
                module = ".".join(base)
            else:
                module = node.module or ""
            if module:
                modules.append((module, True))
                modules.extend(
                    (module + "." + alias.name, False)
                    for alias in node.names
                    if alias.name != "*"
                )
        discovered.extend(modules)
    discovered.extend((module, True) for module in _dynamic_import_modules(tree, path))
    local_namespaces = _local_namespaces()
    for module, required in discovered:
        candidates = _module_candidates(module)
        if (
            required
            and not candidates
            and module.split(".", 1)[0] in local_namespaces
        ):
            raise RuntimeError(
                f"unresolved local import {module!r} in {_relative(path)}"
            )
        found.update(candidate.resolve() for candidate in candidates)
        # Importing a submodule also executes each local package initializer.
        pieces = module.split(".")
        for index in range(1, len(pieces)):
            package = PROJECT.joinpath(*pieces[:index], "__init__.py")
            if package.is_file():
                found.add(package.resolve())
    return found


def expected_scope() -> set[str]:
    closure = _root_inputs()
    pending = [path for path in closure if path.suffix == ".py"]
    while pending:
        path = pending.pop()
        for dependency in _local_imports(path):
            if dependency not in closure:
                closure.add(dependency)
                if dependency.suffix == ".py":
                    pending.append(dependency)
    return {_relative(path) for path in closure}


def verify(manifest: Path) -> tuple[int, str]:
    raw = manifest.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise RuntimeError("manifest encoding/newlines are not canonical")
    records: dict[str, str] = {}
    for line in raw.decode("utf-8").splitlines():
        match = _LINE.fullmatch(line)
        if match is None or match.group(2) in records:
            raise RuntimeError("manifest line is malformed or duplicated")
        records[match.group(2)] = match.group(1)
    expected = expected_scope()
    if set(records) != expected:
        missing = sorted(expected - set(records))
        extra = sorted(set(records) - expected)
        raise RuntimeError(f"manifest closure mismatch: missing={missing}, extra={extra}")
    if list(records) != sorted(records):
        raise RuntimeError("manifest paths are not ordinally sorted")
    for relative, expected_digest in records.items():
        actual = hashlib.sha256((PROJECT / relative).read_bytes()).hexdigest()
        if actual != expected_digest:
            raise RuntimeError(f"manifest digest mismatch: {relative}")
    return len(records), hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    count, digest = verify(args.manifest.resolve())
    print(f"P44_SCOPE_OK files={count} manifest_sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
