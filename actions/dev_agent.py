import base64
import ast
import subprocess
import sys
import json
import copy
import ctypes
import errno
import hashlib
import hmac
import keyword
import os
import re
import shlex
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Callable

from core.paths import config_file, resource_root, user_desktop_dir


def get_base_dir():
    return resource_root()


BASE_DIR         = get_base_dir()
API_CONFIG_PATH  = config_file()
_desktop = user_desktop_dir()
ONYX_PROJECTS_DIR = _desktop / "OnyxProjects"
PROJECTS_DIR = ONYX_PROJECTS_DIR
MODEL_PLANNER    = "gemini-2.5-flash"
MODEL_WRITER     = "gemini-2.5-flash"
_ALLOWED_RUNNERS = {
    "python", "python.exe", "python3", "python3.exe",
}
_approval_callback: Callable[[dict], str | None] | None = None
_PEP508_DEPENDENCY = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.-]*"
    r"(?:\[[A-Za-z0-9][A-Za-z0-9_.-]*(?:,[A-Za-z0-9][A-Za-z0-9_.-]*)*\])?"
    r"(?:\s*(?:===|==|!=|~=|>=|<=|>|<)\s*[A-Za-z0-9][A-Za-z0-9.*+!_-]*"
    r"(?:\s*,\s*(?:===|==|!=|~=|>=|<=|>|<)\s*[A-Za-z0-9][A-Za-z0-9.*+!_-]*)*)?"
)
_IMPORT_BOOTSTRAP_RESERVED = {
    "base64", "builtins", "hashlib", "importlib", "json", "os", "sys", "types",
}
_IN_MEMORY_IMPORT_BOOTSTRAP = r'''
import base64 as _b64
import hashlib as _hashlib
import importlib.abc as _importlib_abc
import importlib.util as _importlib_util
import json as _json
import os as _os
import sys as _sys
import types as _types

_payload = _json.loads(_sys.stdin.buffer.read().decode("ascii"))
if set(_payload) != {"entry_module", "entry_path", "modules"}:
    raise RuntimeError("invalid approved source manifest")
_sources = {}
for _name, _item in _payload["modules"].items():
    if set(_item) != {"path", "package", "sha256", "source"}:
        raise RuntimeError("invalid approved module record")
    _source = _b64.b64decode(_item["source"], validate=True)
    if _hashlib.sha256(_source).hexdigest() != _item["sha256"]:
        raise RuntimeError("approved module digest mismatch")
    _sources[_name] = (_item["path"], _source, bool(_item["package"]))

_cwd = _os.path.normcase(_os.path.realpath(_os.getcwd()))
_sys.path[:] = [
    _path for _path in _sys.path
    if _path and _os.path.normcase(_os.path.realpath(_path)) != _cwd
]
_approved_roots = {_name.partition(".")[0] for _name in _sources}
_stdlib_roots = set(_sys.stdlib_module_names)

class _ApprovedLoader(_importlib_abc.Loader):
    def __init__(self, fullname):
        self.fullname = fullname

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        _path, _source, _is_package = _sources[self.fullname]
        module.__file__ = "<onyx-approved:" + _path + ">"
        if _is_package:
            module.__path__ = []
        exec(compile(_source, module.__file__, "exec", dont_inherit=True), module.__dict__)

class _ApprovedFinder(_importlib_abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        _item = _sources.get(fullname)
        if _item is None:
            return None
        _path, _source, _is_package = _item
        _origin = "<onyx-approved:" + _path + ">"
        return _importlib_util.spec_from_loader(
            fullname, _ApprovedLoader(fullname), origin=_origin,
            is_package=_is_package,
        )

class _StdlibOnlyFinder(_importlib_abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        root = fullname.partition(".")[0]
        if root in _approved_roots or root in _stdlib_roots:
            return None
        raise ModuleNotFoundError(
            "third-party import blocked in Onyx standard-library-only execution: "
            + fullname
        )

for _module_name in sorted(_sources, key=lambda value: value.count("."), reverse=True):
    _sys.modules.pop(_module_name, None)
_sys.meta_path.insert(0, _ApprovedFinder())
_sys.meta_path.insert(1, _StdlibOnlyFinder())

_entry_name = _payload["entry_module"]
_entry_path, _entry_source, _entry_is_package = _sources[_entry_name]
if _entry_is_package or _entry_path != _payload["entry_path"]:
    raise RuntimeError("invalid approved entry module")
_main = _types.ModuleType("__main__")
_main.__file__ = "<onyx-approved:" + _entry_path + ">"
_main.__loader__ = _ApprovedLoader(_entry_name)
_main.__package__ = _entry_name.rpartition(".")[0] or None
_main.__spec__ = None
_sys.modules["__main__"] = _main
_sys.argv = [_entry_path, *_sys.argv[1:]]
exec(compile(_entry_source, _main.__file__, "exec", dont_inherit=True), _main.__dict__)
'''


def _validated_dependency(dep: object) -> tuple[str, str] | None:
    if not isinstance(dep, str) or dep.startswith("-") or not _PEP508_DEPENDENCY.fullmatch(dep):
        return None
    package = re.split(r"\[|[<>=!~]", dep, maxsplit=1)[0].strip()
    return dep, package


def _require_python_language(language: object) -> str:
    if language != "python":
        raise ValueError("language must be exactly 'python'")
    return "python"


def set_dev_approval_callback(callback: Callable[[dict], str | None] | None) -> None:
    """Register a trusted host/UI approval callback.

    The callback must display the supplied exact action and return its ``digest``.
    Model/tool parameters never reach this trust decision. With no callback the
    dev agent is preview-only.
    """
    global _approval_callback
    _approval_callback = callback


def _path_lexists(path: Path) -> bool:
    """Return true for regular paths and dangling links/junctions."""
    return os.path.lexists(os.fspath(path))


def _is_reparse_point(path: Path) -> bool:
    """Detect links and Windows junction/reparse points without following them."""
    if path.is_symlink():
        return True
    is_junction = getattr(os.path, "isjunction", None)
    if is_junction is not None and is_junction(path):
        return True
    try:
        attributes = getattr(os.lstat(path), "st_file_attributes", 0)
    except OSError:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _assert_private_tree(path: Path, root: Path) -> None:
    """Reject any existing link, junction, or non-directory below ``root``."""
    root = root.resolve(strict=True)
    path = path.absolute()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError("private staging path escaped its verified root") from exc
    current = root
    if _is_reparse_point(current) or not current.is_dir():
        raise ValueError("project storage root is a link, junction, or non-directory")
    for part in relative.parts:
        current = current / part
        if not _path_lexists(current):
            continue
        if _is_reparse_point(current) or not current.is_dir():
            raise ValueError(f"unsafe link, junction, or non-directory: {current}")


def _approved_relative_path(value: str) -> Path:
    relative = Path(value)
    if (
        not value
        or relative.is_absolute()
        or relative.drive
        or any(part in ("", ".", "..") for part in relative.parts)
    ):
        raise ValueError(f"unsafe approved file path: {value!r}")
    return relative


def _approved_python_sources(
    artifacts: dict[str, bytes], entry_point: str
) -> tuple[str, dict[str, dict[str, object]]]:
    """Build an unambiguous import map for every approved Python artifact."""
    modules: dict[str, dict[str, object]] = {}
    normalized_names: dict[str, str] = {}
    packages: set[str] = set()
    path_to_module: dict[str, str] = {}
    for path, source in artifacts.items():
        relative = _approved_relative_path(path)
        if relative.suffix.lower() != ".py":
            continue
        if relative.name == "__init__.py":
            if len(relative.parts) == 1:
                raise ValueError("a project-root __init__.py is an unsupported executable layout")
            module_parts = relative.parts[:-1]
            is_package = True
        else:
            module_parts = (*relative.parts[:-1], relative.stem)
            is_package = False
        if any(not part.isidentifier() or keyword.iskeyword(part) for part in module_parts):
            raise ValueError(f"unsupported Python module path: {path}")
        module_name = ".".join(module_parts)
        folded = module_name.casefold()
        previous = normalized_names.get(folded)
        if previous is not None:
            raise ValueError(
                f"ambiguous approved Python module mapping: {previous} and {path}"
            )
        if module_parts[0] in _IMPORT_BOOTSTRAP_RESERVED:
            raise ValueError(f"approved module conflicts with the isolated importer: {path}")
        if module_parts[0] in sys.stdlib_module_names:
            raise ValueError(f"approved module shadows the Python standard library: {path}")
        try:
            compile(source, f"<onyx-approved:{path}>", "exec", dont_inherit=True)
        except (SyntaxError, ValueError) as exc:
            raise ValueError(f"approved Python artifact does not compile: {path}: {exc}") from exc
        normalized_names[folded] = path
        path_to_module[path] = module_name
        modules[module_name] = {
            "path": path,
            "package": is_package,
            "sha256": hashlib.sha256(source).hexdigest(),
            "source": source,
        }
        if is_package:
            packages.add(module_name)

    if entry_point not in path_to_module:
        raise ValueError("approved entry point is not a supported Python source file")
    entry_module = path_to_module[entry_point]
    if bool(modules[entry_module]["package"]):
        raise ValueError("a package __init__.py cannot be the approved entry point")
    for module_name in modules:
        parts = module_name.split(".")
        for index in range(1, len(parts)):
            parent = ".".join(parts[:index])
            if parent not in packages:
                raise ValueError(
                    f"unsupported namespace-package layout; missing {parent.replace('.', '/')}/__init__.py"
                )
    approved_roots = {name.partition(".")[0] for name in modules}
    for item in modules.values():
        source = item["source"]
        path = str(item["path"])
        if not isinstance(source, bytes):
            raise ValueError("approved module source is not bytes")
        tree = ast.parse(source, filename=f"<onyx-approved:{path}>")
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported_roots.add(node.module.partition(".")[0])
        third_party = sorted(
            root
            for root in imported_roots
            if root not in approved_roots and root not in sys.stdlib_module_names
        )
        if third_party:
            raise ValueError(
                f"third-party import requires preview-only dependencies in {path}: "
                + ", ".join(third_party)
            )
    return entry_module, modules


def _serialized_source_manifest(
    entry_point: str, entry_module: str, modules: dict[str, dict[str, object]]
) -> bytes:
    payload_modules: dict[str, dict[str, object]] = {}
    for module_name, item in modules.items():
        source = item["source"]
        if not isinstance(source, bytes):
            raise ValueError("approved module source is not bytes")
        payload_modules[module_name] = {
            "path": item["path"],
            "package": item["package"],
            "sha256": item["sha256"],
            "source": base64.b64encode(source).decode("ascii"),
        }
    return json.dumps(
        {
            "entry_module": entry_module,
            "entry_path": entry_point,
            "modules": payload_modules,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _write_snapshot(snapshot: Path, expected: dict[str, bytes], root: Path) -> None:
    """Create a new artifact tree using exclusive writes only."""
    for name, content in expected.items():
        relative = _approved_relative_path(name)
        parent = snapshot
        for part in relative.parent.parts:
            parent = parent / part
            if _path_lexists(parent):
                if _is_reparse_point(parent) or not parent.is_dir():
                    raise ValueError(f"unsafe snapshot parent: {parent}")
            else:
                parent.mkdir()
        _assert_private_tree(parent, root)
        target = snapshot / relative
        with target.open("xb") as handle:
            handle.write(content)


def _verify_snapshot(snapshot: Path, expected: dict[str, bytes], root: Path) -> dict[str, bytes]:
    """Verify the complete tree and return the bytes actually read from it."""
    _assert_private_tree(snapshot, root)
    allowed_files = {Path(name) for name in expected}
    allowed_dirs = {Path(".")}
    for relative in allowed_files:
        allowed_dirs.update(relative.parents)
    actual_files: set[Path] = set()
    for item in snapshot.rglob("*"):
        if _is_reparse_point(item):
            raise ValueError(f"snapshot contains a link or junction: {item}")
        relative = item.relative_to(snapshot)
        if item.is_dir():
            if relative not in allowed_dirs:
                raise ValueError(f"snapshot contains an unapproved directory: {relative}")
        elif item.is_file():
            actual_files.add(relative)
        else:
            raise ValueError(f"snapshot contains a non-regular artifact: {relative}")
    if actual_files != allowed_files:
        raise ValueError("snapshot file manifest differs from the approved artifact list")
    verified: dict[str, bytes] = {}
    for name, approved in expected.items():
        actual = (snapshot / _approved_relative_path(name)).read_bytes()
        if not hmac.compare_digest(actual, approved):
            raise ValueError(f"approved artifact changed: {name}")
        verified[name] = actual
    return verified


def _atomic_publish_noreplace(snapshot: Path, target: Path) -> None:
    """Atomically publish a directory and never replace an existing target."""
    if _path_lexists(target):
        raise FileExistsError(errno.EEXIST, "approved project target already exists", target)
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise OSError(errno.ENOTSUP, "atomic no-replace rename is unavailable")
        renameat2.argtypes = [
            ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        if renameat2(-100, os.fsencode(snapshot), -100, os.fsencode(target), 1) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), target)
        return
    if sys.platform == "win32":
        # MoveFile (used by os.rename) fails when the destination already exists.
        os.rename(snapshot, target)
        return
    if sys.platform == "darwin":
        # Darwin's renamex_np(RENAME_EXCL) is the native atomic equivalent of
        # Linux renameat2(RENAME_NOREPLACE). A preflight exists check alone is
        # insufficient because another process can create the target after it.
        libc = ctypes.CDLL(None, use_errno=True)
        renamex_np = getattr(libc, "renamex_np", None)
        if renamex_np is None:
            raise OSError(errno.ENOTSUP, "atomic no-replace rename is unavailable")
        renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        renamex_np.restype = ctypes.c_int
        ctypes.set_errno(0)
        rename_excl = 0x00000004
        if renamex_np(os.fsencode(snapshot), os.fsencode(target), rename_excl) != 0:
            error = ctypes.get_errno()
            if not error:
                error = errno.EIO
            raise OSError(error, os.strerror(error), target)
        return
    raise OSError(errno.ENOTSUP, "atomic no-replace publish is unsupported on this platform")


def _cleanup_stage(stage: Path, root: Path) -> None:
    """Remove only the random staging directory created by this execution."""
    if not _path_lexists(stage):
        return
    if stage.parent != root or not stage.name.startswith(".onyx-stage-"):
        return
    if _is_reparse_point(stage):
        try:
            stage.rmdir()
        except OSError:
            pass
        return
    shutil.rmtree(stage, ignore_errors=True)


def _parse_safe_python_command(
    run_command: str,
    project_dir: Path,
    entry_point: str | None = None,
) -> list[str] | None:
    try:
        parts = shlex.split(run_command, posix=sys.platform != "win32")
    except (TypeError, ValueError):
        return None
    if sys.platform == "win32":
        parts = [
            item[1:-1] if len(item) >= 2 and item[0] == item[-1] and item[0] in "\"'" else item
            for item in parts
        ]
    if len(parts) < 2 or Path(parts[0]).name != parts[0]:
        return None
    if parts[0].lower() not in _ALLOWED_RUNNERS or parts[1].startswith("-"):
        return None
    script = (project_dir / parts[1]).resolve()
    root = project_dir.resolve()
    if script.suffix.lower() != ".py" or not script.is_relative_to(root):
        return None
    if entry_point is not None and script != (root / entry_point).resolve():
        return None
    return parts


def _approval_request(
    description: str,
    language: str,
    project_name: str,
    timeout: int,
    plan: dict,
    project_dir: Path,
    artifacts: dict[str, str],
) -> dict:
    language = _require_python_language(language)
    exact_files = [
        {
            "path": path,
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "content": content,
        }
        for path, content in sorted(artifacts.items())
    ]
    action = {
        "description": description,
        "language": language,
        "project_name": project_name,
        "timeout": timeout,
        "project_path": str(project_dir.resolve()),
        "files": exact_files,
        "dependencies": copy.deepcopy(plan["dependencies"]),
        "entry_point": plan.get("entry_point", ""),
        "run_command": plan.get("run_command", ""),
    }
    canonical = json.dumps(action, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {**action, "digest": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def _request_digest(request: dict) -> str:
    payload = {key: copy.deepcopy(value) for key, value in request.items() if key != "digest"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_approval_request(request: object) -> dict:
    """Validate and canonicalize the complete host-approved execution payload."""
    if not isinstance(request, dict):
        raise ValueError("approval request must be an object")
    required = {
        "description", "language", "project_name", "timeout", "project_path",
        "files", "dependencies", "entry_point", "run_command", "digest",
    }
    if set(request) != required:
        raise ValueError("approval request has missing or unsupported fields")
    if any(
        not isinstance(request[key], str) or not request[key].strip()
        for key in ("description", "language", "project_name", "project_path", "entry_point")
    ):
        raise ValueError("approval request contains an invalid text field")
    _require_python_language(request["language"])
    timeout = request["timeout"]
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 300:
        raise ValueError("approval timeout must be an integer from 1 to 300")
    project_name = request["project_name"]
    if re.sub(r"[^\w\-]", "_", project_name) != project_name:
        raise ValueError("approval project name is unsafe")
    root = PROJECTS_DIR.resolve()
    project_dir = Path(request["project_path"]).resolve()
    if project_dir != (root / project_name).resolve() or not project_dir.is_relative_to(root):
        raise ValueError("approval project path does not match the project name")

    dependencies = request["dependencies"]
    if not isinstance(dependencies, list):
        raise ValueError("approval dependencies must be a list")
    canonical_dependencies: list[str] = []
    for dependency in dependencies:
        validated = _validated_dependency(dependency)
        if validated is None:
            raise ValueError(f"unsafe approved dependency: {dependency!r}")
        canonical_dependencies.append(validated[0])
    if canonical_dependencies:
        raise ValueError(
            "third-party dependencies are preview-only and cannot be approved for automatic "
            f"execution: {', '.join(canonical_dependencies)}"
        )

    files = request["files"]
    if not isinstance(files, list) or not files:
        raise ValueError("approval files must be a non-empty list")
    canonical_files: list[dict] = []
    seen: set[str] = set()
    for artifact in files:
        if not isinstance(artifact, dict) or set(artifact) != {"path", "sha256", "content"}:
            raise ValueError("each approved file must contain exactly path, sha256, and content")
        path = artifact["path"]
        content = artifact["content"]
        digest = artifact["sha256"]
        if not isinstance(path, str) or not path or path in seen:
            raise ValueError("approved file paths must be unique non-empty strings")
        target = (project_dir / path).resolve()
        if target == project_dir or not target.is_relative_to(project_dir):
            raise ValueError(f"unsafe approved file path: {path!r}")
        if not isinstance(content, str) or not isinstance(digest, str):
            raise ValueError("approved file content and digest must be strings")
        expected_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(digest, expected_digest):
            raise ValueError(f"approved artifact digest mismatch: {path!r}")
        seen.add(path)
        canonical_files.append(copy.deepcopy(artifact))

    if request["entry_point"] not in seen:
        raise ValueError("approved entry point is not in the file list")
    _approved_python_sources(
        {item["path"]: item["content"].encode("utf-8") for item in canonical_files},
        request["entry_point"],
    )
    run_command = request["run_command"]
    if not isinstance(run_command, str) or _parse_safe_python_command(
        run_command, project_dir, request["entry_point"]
    ) is None:
        raise ValueError("approved run command must execute the exact approved entry point")
    digest = request["digest"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("approval digest is invalid")
    if not hmac.compare_digest(_request_digest(request), digest):
        raise ValueError("approval payload digest mismatch")
    return {
        "description": request["description"],
        "language": request["language"],
        "project_name": project_name,
        "timeout": timeout,
        "project_path": str(project_dir),
        "files": canonical_files,
        "dependencies": canonical_dependencies,
        "entry_point": request["entry_point"],
        "run_command": run_command,
        "digest": digest,
    }


def _validate_plan(plan: object, project_dir: Path) -> dict:
    """Return a canonical deep copy of a complete, safe planner schema."""
    if not isinstance(plan, dict):
        raise ValueError("plan must be an object")
    required = {"project_name", "entry_point", "files", "run_command", "dependencies"}
    if set(plan) != required:
        raise ValueError("plan schema has missing or unsupported fields")
    if not isinstance(plan["project_name"], str) or not plan["project_name"].strip():
        raise ValueError("project_name must be a non-empty string")
    if not isinstance(plan["entry_point"], str) or not plan["entry_point"].strip():
        raise ValueError("entry_point must be a non-empty string")
    if not isinstance(plan["run_command"], str):
        raise ValueError("run_command must be a string")
    if not isinstance(plan["dependencies"], list):
        raise ValueError("dependencies must be a list")
    dependencies: list[str] = []
    for dep in plan["dependencies"]:
        validated = _validated_dependency(dep)
        if validated is None:
            raise ValueError(f"unsafe dependency specification: {dep!r}")
        dependencies.append(validated[0])
    files = plan["files"]
    if not isinstance(files, list) or not files:
        raise ValueError("files must be a non-empty list")
    canonical_files: list[dict] = []
    seen: set[str] = set()
    root = project_dir.resolve()
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "description", "imports"}:
            raise ValueError("each file must contain exactly path, description, and imports")
        path = item["path"]
        if not isinstance(path, str) or not path or path in seen:
            raise ValueError("file paths must be unique non-empty strings")
        target = (root / path).resolve()
        if target == root or not target.is_relative_to(root):
            raise ValueError(f"unsafe project file path: {path!r}")
        if not isinstance(item["description"], str) or not isinstance(item["imports"], list):
            raise ValueError("file description/imports have invalid types")
        if any(not isinstance(value, str) for value in item["imports"]):
            raise ValueError("file imports must contain strings")
        seen.add(path)
        canonical_files.append(copy.deepcopy(item))
    if plan["entry_point"] not in seen:
        raise ValueError("entry_point is not in files")
    if _parse_safe_python_command(
        plan["run_command"], project_dir, plan["entry_point"]
    ) is None:
        raise ValueError("run_command must execute the exact planned entry_point")
    return {
        "project_name": plan["project_name"].strip(),
        "entry_point": plan["entry_point"],
        "files": canonical_files,
        "run_command": plan["run_command"],
        "dependencies": dependencies,
    }


def _format_approval_preview(request: dict) -> str:
    files = [str(item.get("path", "")) for item in request["files"] if isinstance(item, dict)]
    deps = [str(item) for item in request["dependencies"]]
    if deps:
        return (
            "Development preview generated in preview-only mode; automatic approval, execution, and publishing "
            "are disabled because third-party dependencies are required.\n"
            f"Dependencies requiring manual review: {', '.join(deps)}\n"
            "Review each dependency's source, ownership, release, and build metadata; then install "
            "and run the preview manually in a new isolated environment outside Onyx. Onyx did "
            "not invoke a package manager, subprocess, download, install, or build hook.\n"
            f"Preview ID: {request['digest']}\n"
            f"Project: {request['project_name']}\n"
            f"Files: {', '.join(files) or '(none)'}\n"
            f"Command (manual review only): {request['run_command']}"
        )
    return (
        "Development execution is preview-only until the trusted host UI approves this exact "
        "standard-library-only action.\n"
        f"Approval ID: {request['digest']}\n"
        f"Project: {request['project_name']}\n"
        f"Files: {', '.join(files) or '(none)'}\n"
        f"Dependencies: {', '.join(deps) or '(none)'}\n"
        f"Command: {request['run_command']}"
    )

def _get_api_key() -> str:
    from core.credentials import get
    return get(required=True) or ""


def _get_model(model_name: str):
    from google import genai
    _c = genai.Client(api_key=_get_api_key())

    class _W:
        def generate_content(self, contents):
            return _c.models.generate_content(model=model_name, contents=contents)

    return _W()


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\r?\n?", "", text)
    text = re.sub(r"\r?\n?```\s*$", "", text)
    return text.strip()


def _is_rate_limit(error: Exception) -> bool:
    msg = str(error).lower()
    return "429" in msg or "quota" in msg or "resource_exhausted" in msg


def _classify_error(output: str) -> str:

    low = output.lower()

    if any(x in low for x in ("no module named", "modulenotfounderror", "importerror")):
        return "dependency_error"

    if "syntaxerror" in low or "invalid syntax" in low:
        return "syntax_error"
    
    if "cannot import" in low or "importerror" in low:
        return "import_error"

    if any(x in low for x in (
        "traceback", "exception", "error:", "nameerror", "typeerror",
        "attributeerror", "valueerror", "keyerror", "indexerror",
        "zerodivisionerror", "filenotfounderror", "permissionerror",
    )):
        return "runtime_error"

    return "none"


def _has_error(output: str, run_command: str) -> bool:
    
    low = output.lower()

    if "timed out" in low:
        return False

    if not output.strip():
        return False

    error_type = _classify_error(output)
    return error_type != "none"

class RateLimitError(Exception):
    pass


def _plan_project(description: str, language: str) -> dict:
    _require_python_language(language)
    model = _get_model(MODEL_PLANNER)

    prompt = f"""You are a senior software architect. Create a minimal, complete file plan for this project.

Language: python (the only supported automatic-execution language)
Description: {description}

Return ONLY valid JSON — no markdown, no explanation:
{{
  "project_name": "snake_case_name",
  "entry_point": "main.py",
  "files": [
    {{
      "path": "main.py",
      "description": "Entry point — what it does and which modules it imports",
      "imports": ["utils.helpers", "core.engine"]
    }},
    {{
      "path": "utils/helpers.py",
      "description": "Helper utilities — what functions it exposes",
      "imports": []
    }}
  ],
  "run_command": "python main.py",
  "dependencies": []
}}

Critical rules:
1. List files in DEPENDENCY ORDER — files with no imports come first, entry point comes last.
2. The "imports" field must list every other project module this file imports (dot-notation, e.g. "utils.helpers").
3. Keep it minimal — only files truly needed.
4. Entry point must be in the files list.
5. Use relative paths only (e.g. "utils/helpers.py", not absolute paths).
6. Standard library modules (os, sys, json, etc.) do NOT go in "dependencies".
7. Prefer a Python-standard-library-only design with an empty "dependencies" list.
8. If the requested project truly requires a third-party package, list its exact requirement in
   "dependencies". Onyx will generate a preview but will never approve, install, execute, or
   publish a dependency-bearing plan automatically.

JSON:"""

    try:
        response = model.generate_content(prompt)
        raw = _strip_fences(response.text)
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Planner returned invalid JSON: {e}\nRaw: {response.text[:300]}")
    except Exception as e:
        if _is_rate_limit(e):
            raise RateLimitError(str(e))
        raise

def _write_file(
    file_info: dict,
    project_description: str,
    all_files: list[dict],
    language: str,
    project_dir: Path,
    already_written: dict[str, str],
) -> str:
    _require_python_language(language)
    model = _get_model(MODEL_WRITER)

    file_path = file_info["path"]
    full_path = (project_dir / file_path).resolve()
    project_root = project_dir.resolve()
    if full_path == project_root or not full_path.is_relative_to(project_root):
        raise ValueError(f"Unsafe project file path: {file_path}")
    file_desc = file_info.get("description", "")
    file_imports = file_info.get("imports", [])

    file_list = "\n".join(
        f"  [{i+1}] {f['path']}: {f.get('description', '')}"
        for i, f in enumerate(all_files)
    )

    dependency_context = ""
    for dep_dotted in file_imports:
        dep_path = dep_dotted.replace(".", "/") + ".py"
        if dep_path in already_written:
            code_snippet = already_written[dep_path][:2000]
            dependency_context += f"\n\n--- {dep_path} (you must import from this) ---\n{code_snippet}"

    lang_rules = """
Python-specific rules:
- Use type hints for all function signatures.
- Add docstrings for all public functions and classes.
- Use if __name__ == "__main__": guard in the entry point.
- For relative imports within the project, use: from utils.helpers import foo  (match the project structure exactly).
- Do NOT use implicit relative imports (from . import ...) unless it's a proper package with __init__.py.
- If this is a package subdirectory, create __init__.py files where needed."""

    prompt = f"""You are a senior {language} developer writing production-quality code for a real project.

Project goal: {project_description}

Complete project file structure (in dependency order):
{file_list}

{f"Dependencies this file must import from other project files:{dependency_context}" if dependency_context else ""}

Your task: Write the complete, working code for: {file_path}
Purpose of this file: {file_desc}
{f"This file imports from: {', '.join(file_imports)}" if file_imports else "This file has no project-internal imports."}

{lang_rules}

General rules:
- Output ONLY raw code. Absolutely no explanation, no markdown, no triple backticks.
- Write COMPLETE, RUNNABLE code — no placeholders, no "# TODO", no "pass" stubs.
- Every import must either be from the Python standard library, an exact dependency from the
  preview-only plan, or the project files shown above. A dependency-bearing preview will never be
  installed, executed, or published automatically by Onyx.
- Match import paths EXACTLY to the file paths in the project structure (e.g. if file is "utils/helpers.py", import as "from utils.helpers import ...").
- Use proper error handling (try/except) where I/O or network calls are made.
- The code must work correctly when the project entry point is run from the project root directory.

Code for {file_path}:"""

    try:
        response = model.generate_content(prompt)
        code = _strip_fences(response.text)

        print(f"[DevAgent] Generated preview: {file_path} ({len(code)} chars)")
        return code

    except Exception as e:
        if _is_rate_limit(e):
            raise RateLimitError(str(e))
        raise

def _run_verified_entry(
    python: Path,
    entry_bytes: bytes,
    args: list[str],
    snapshot: Path,
    timeout: int,
    source_manifest: bytes,
) -> tuple[str, bool]:
    """Run held sources through an isolated in-memory importer."""
    try:
        payload = json.loads(source_manifest.decode("ascii"))
        manifest_entry = base64.b64decode(
            payload["modules"][payload["entry_module"]]["source"], validate=True
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return f"Run error: invalid approved source manifest: {exc}", False
    if not hmac.compare_digest(manifest_entry, entry_bytes):
        return "Run error: approved entry bytes differ from the source manifest.", False
    environment = {
        key: os.environ[key]
        for key in (
            "COMSPEC", "LANG", "LC_ALL", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP",
            "TMPDIR", "WINDIR",
        )
        if key in os.environ
    }
    environment.update({"PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"})
    try:
        result = subprocess.run(
            [str(python), "-I", "-S", "-c", _IN_MEMORY_IMPORT_BOOTSTRAP, *args],
            input=source_manifest,
            capture_output=True,
            timeout=timeout,
            cwd=str(snapshot),
            env=environment,
        )
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s; the project was not published.", False
    except (OSError, ValueError) as exc:
        return f"Run error: {exc}", False
    stdout = result.stdout.decode("utf-8", errors="replace").strip()
    stderr = result.stderr.decode("utf-8", errors="replace").strip()
    output = []
    if result.returncode != 0:
        output.append(f"Process failed with exit code {result.returncode}.")
    if stdout:
        output.append(f"STDOUT:\n{stdout}")
    if stderr:
        output.append(f"STDERR:\n{stderr}")
    return "\n\n".join(output) if output else "Ran with no output.", result.returncode == 0

def _execute_approved_artifacts(
    request: dict,
    approved_digest: str,
    player=None,
    speak=None,
) -> str:
    """Execute a private approved snapshot, then atomically publish exact bytes.

    The requested destination remains absent until an exit-zero run and a final
    full-manifest verification. Dependency-bearing requests fail closed before
    staging. Every approved Python source is held in an authenticated in-memory
    import manifest; no project module is imported from the mutable staging
    filesystem, and third-party imports are blocked statically and at runtime.
    """
    try:
        request = _validate_approval_request(request)
    except (TypeError, ValueError) as exc:
        return f"Development execution rejected: {exc}."
    if not isinstance(approved_digest, str) or not hmac.compare_digest(
        request["digest"], approved_digest
    ):
        return "Development execution rejected: host approval digest does not match."
    project_dir = Path(request["project_path"])
    try:
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        if _is_reparse_point(PROJECTS_DIR):
            raise ValueError("project storage root is a link or junction")
        root = PROJECTS_DIR.resolve(strict=True)
        _assert_private_tree(root, root)
    except (OSError, ValueError) as exc:
        return f"Development execution rejected: unsafe project storage: {exc}."
    resolved = project_dir.absolute()
    if resolved.parent != root or resolved.name != request["project_name"]:
        return "Development execution rejected: unsafe project path."
    if _path_lexists(resolved):
        return (
            "Development execution rejected: the approved project directory already exists; "
            "a new isolated directory is required."
        )
    expected: dict[str, bytes] = {}
    for artifact in request["files"]:
        content = artifact["content"].encode("utf-8")
        if hashlib.sha256(content).hexdigest() != artifact["sha256"]:
            return "Development execution rejected: artifact digest mismatch."
        try:
            _approved_relative_path(artifact["path"])
        except ValueError:
            return "Development execution rejected: unsafe artifact path."
        expected[artifact["path"]] = content
    stage: Path | None = None
    try:
        stage = Path(tempfile.mkdtemp(prefix=".onyx-stage-", dir=str(root)))
        if stage.parent != root or _is_reparse_point(stage):
            raise ValueError("private staging directory is unsafe")
        snapshot = stage / "project"
        snapshot.mkdir()
        _write_snapshot(snapshot, expected, root)
        _verify_snapshot(snapshot, expected, root)
        if not hmac.compare_digest(_request_digest(request), approved_digest):
            raise ValueError("approval payload changed before run")
        verified = _verify_snapshot(snapshot, expected, root)
        if not hmac.compare_digest(_request_digest(request), approved_digest):
            raise ValueError("approval payload changed before run")
        parts = _parse_safe_python_command(
            request["run_command"], resolved, request["entry_point"]
        )
        if parts is None:
            raise ValueError("approved run command is no longer valid")
        entry_bytes = verified[request["entry_point"]]
        entry_module, source_modules = _approved_python_sources(
            verified, request["entry_point"]
        )
        source_manifest = _serialized_source_manifest(
            request["entry_point"], entry_module, source_modules
        )
        output, succeeded = _run_verified_entry(
            Path(sys.executable),
            entry_bytes,
            parts[2:],
            snapshot,
            request["timeout"],
            source_manifest,
        )
        if not succeeded:
            return (
                "The approved project failed and was not published. Automatic repair is "
                f"disabled because mutations require a new approval.\n\n{output[:1200]}"
            )
        _verify_snapshot(snapshot, expected, root)
        if not hmac.compare_digest(_request_digest(request), approved_digest):
            raise ValueError("approval payload changed before publish")
        if _path_lexists(resolved):
            raise FileExistsError("approved project target appeared before publish")
        _atomic_publish_noreplace(snapshot, resolved)
        message = f"Approved project '{request['project_name']}' created at {resolved}."
        if player:
            player.write_log(f"[DevAgent] {message}")
        if speak:
            speak(message)
        return f"{message}\n\nStandard-library-only isolated execution.\n\n{output}"
    except FileExistsError:
        return "Development execution rejected: project target appeared before publish."
    except (OSError, RuntimeError, ValueError) as exc:
        return f"Development execution rejected: {exc}."
    finally:
        if stage is not None:
            _cleanup_stage(stage, root)


def dev_agent(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    p            = parameters or {}
    description  = p.get("description", "").strip()
    language     = p.get("language", "python")
    project_name = p.get("project_name", "").strip()
    try:
        timeout = max(1, min(300, int(p.get("timeout", 30))))
    except (TypeError, ValueError):
        return "Planning rejected: timeout must be an integer from 1 to 300 seconds."

    if not description:
        return "Please describe the project you want me to build, sir."
    try:
        language = _require_python_language(language)
    except ValueError as exc:
        return f"Planning rejected: {exc}."
    try:
        raw_plan = _plan_project(description, language)
    except RateLimitError:
        return "Rate limit reached, sir. Please try again in a moment."
    except (ValueError, KeyError, TypeError) as exc:
        return f"Planning failed: {exc}"

    proj_name = re.sub(r"[^\w\-]", "_", project_name or str(raw_plan.get("project_name", "")))
    if not proj_name:
        return "Planning rejected: project name is empty."
    project_dir = PROJECTS_DIR / proj_name
    if project_dir.exists():
        return (
            "Planning rejected: that project directory already exists. Choose a new project "
            "name so no pre-existing code or virtual environment can be executed."
        )
    try:
        raw_plan = copy.deepcopy(raw_plan)
        raw_plan["project_name"] = proj_name
        plan = _validate_plan(raw_plan, project_dir)
    except (KeyError, TypeError, ValueError) as exc:
        return f"Planning rejected: {exc}"

    artifacts: dict[str, str] = {}
    for file_info in sorted(plan["files"], key=lambda item: len(item["imports"])):
        try:
            artifacts[file_info["path"]] = _write_file(
                file_info, description, plan["files"], language, project_dir, artifacts
            )
        except RateLimitError:
            return "Rate limit reached while generating the exact preview. Nothing was written."
        except Exception as exc:
            return f"Artifact generation failed before approval: {exc}"

    approval = _approval_request(
        description, language, proj_name, timeout, plan, project_dir, artifacts
    )
    if approval["dependencies"]:
        return _format_approval_preview(approval)
    callback = _approval_callback
    if callback is None:
        return _format_approval_preview(approval)
    try:
        decision = callback(copy.deepcopy(approval))
    except Exception as exc:
        return f"Trusted host approval failed: {exc}"
    if not isinstance(decision, str) or not hmac.compare_digest(decision, approval["digest"]):
        return "Development execution was not approved by the trusted host UI."

    if not hmac.compare_digest(_request_digest(approval), approval["digest"]):
        return "Development execution rejected: approval payload changed."
    return _execute_approved_artifacts(approval, decision, player, speak)
