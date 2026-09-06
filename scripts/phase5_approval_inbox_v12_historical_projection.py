"""Hermetic historical projections for the frozen Approval Inbox lineage.

V12 never reads either mutable live documentation path while materializing the
R11 evidence tree.  The two paths are substituted at source with exact V9
content-addressed snapshots.  Every authority read and every output component
passes one canonical, exact-case, containment and no-reparse gate.

Materialization is allowed only inside a fresh temporary directory created by
this plugin's ``TemporaryDirectory`` proxy.  Targets must not already exist and
are opened exclusively.  The proxy verifies removal when its context exits.
"""

from __future__ import annotations

import functools
import hashlib
import importlib
import importlib.util
import os
import re
import stat
import tempfile as _stdlib_tempfile
import threading
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import BinaryIO


ROOT = Path(__file__).absolute().parents[1]
REPOSITORY_GIT_RELATIVE = ".git"
FROZEN_PROJECTIONS = {
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
ROOT_AUTHORITIES = {
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
HISTORICAL_VERIFIER_SOURCES = {
    2: (
        "scripts/verify_phase5_approval_inbox_v2.py",
        "2024016da88ab94d81942c716c948b6b6b4c1dfb78eddcb7ffcda19d6f8e5a56",
    ),
    3: (
        "scripts/verify_phase5_approval_inbox_v3.py",
        "599533f7836b7dc18556758f914d00da0c1755595c6df8dd88040e60195c9db9",
    ),
    4: (
        "scripts/verify_phase5_approval_inbox_v4.py",
        "da97a9348a9765ba0283e811ca59921b783c10f0cf24194afd7bda1d6d9d22ec",
    ),
    5: (
        "scripts/verify_phase5_approval_inbox_v5.py",
        "93d51b079e8ba8736147d0c09cff18fb65a94dba3bd28c08cb1458266b440967",
    ),
    6: (
        "scripts/verify_phase5_approval_inbox_v6.py",
        "755d75de078052ec933f731763cbe679d5f62d1b95ad337da28cc21fe8326d5b",
    ),
    7: (
        "scripts/verify_phase5_approval_inbox_v7.py",
        "8fe0492830569b1ebc4315f1b22ceb8c805e625c501245b304642b3c6f5d7537",
    ),
}
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_OWNED: set[str] = set()
_OWNED_LOCK = threading.RLock()
_ORIGINAL_TEMPORARY_DIRECTORY = _stdlib_tempfile.TemporaryDirectory


class HistoricalProjectionPathError(RuntimeError):
    """A historical authority or output path crossed the V12 boundary."""


def _canonical_parts(relative: str) -> tuple[str, ...]:
    if type(relative) is not str:
        raise HistoricalProjectionPathError("noncanonical-path")
    pure = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or "\x00" in relative
        or pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise HistoricalProjectionPathError(f"noncanonical-path:{relative!r}")
    return pure.parts


def _component_is_reparse(path: Path) -> bool:
    info = path.lstat()
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & reparse
    )


def _safe_root(root: Path) -> tuple[Path, Path]:
    absolute = root.absolute()
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as error:
        raise HistoricalProjectionPathError("missing-root") from error
    if _component_is_reparse(absolute) or str(absolute) != str(resolved):
        raise HistoricalProjectionPathError("reparse-or-aliased-root")
    return absolute, resolved


def _safe_existing(
    root: Path, relative: str, *, require_directory: bool = False
) -> Path:
    parts = _canonical_parts(relative)
    absolute_root, resolved_root = _safe_root(root)
    current = absolute_root
    for part in parts:
        try:
            entries = {entry.name: entry for entry in current.iterdir()}
        except OSError as error:
            raise HistoricalProjectionPathError(
                f"unreadable-ancestor:{relative}"
            ) from error
        if part not in entries:
            raise HistoricalProjectionPathError(f"missing-or-case-mismatch:{relative}")
        current = entries[part]
        try:
            resolved = current.resolve(strict=True)
        except OSError as error:
            raise HistoricalProjectionPathError(
                f"missing-component:{relative}"
            ) from error
        if _component_is_reparse(current):
            raise HistoricalProjectionPathError(f"reparse-component:{relative}")
        try:
            resolved.relative_to(resolved_root)
        except ValueError as error:
            raise HistoricalProjectionPathError(f"outside-root:{relative}") from error
        if resolved.name != part:
            raise HistoricalProjectionPathError(f"case-or-name-alias:{relative}")
    if require_directory:
        if not current.is_dir():
            raise HistoricalProjectionPathError(f"not-directory:{relative}")
    elif not current.is_file():
        raise HistoricalProjectionPathError(f"not-file:{relative}")
    return current


def _validated_repository_git_directory() -> Path:
    """Return only this exact worktree's regular, non-reparse ``.git`` directory.

    Historical verifiers execute Git inside a materialized temporary tree.  Its
    gitfile must therefore be sourced from the same canonical authority boundary
    as every evidence input, never from ``resolve()`` alone or from a discovered
    parent/alternate repository.
    """

    git_directory = _safe_existing(
        ROOT, REPOSITORY_GIT_RELATIVE, require_directory=True
    )
    expected = ROOT.absolute() / REPOSITORY_GIT_RELATIVE
    if git_directory != expected:
        raise HistoricalProjectionPathError("repository-git-identity-drift")
    return git_directory


def _load_guarded_historical_verifier(version: int) -> ModuleType:
    relative, expected_digest = HISTORICAL_VERIFIER_SOURCES[version]
    module_name = f"scripts.verify_phase5_approval_inbox_v{version}"
    expected = _safe_existing(ROOT, relative)
    spec = importlib.util.find_spec(module_name)
    if spec is None or type(spec.origin) is not str:
        raise HistoricalProjectionPathError(
            f"historical-module-source-missing:{module_name}"
        )
    origin = Path(spec.origin)
    if not origin.is_absolute() or origin != expected:
        raise HistoricalProjectionPathError(
            f"historical-module-source-identity-drift:{module_name}"
        )
    # The source is re-gated and hashed immediately before import inside the
    # combined child process, independently of the parent's launch boundary.
    guarded = _safe_existing(ROOT, origin.relative_to(ROOT.absolute()).as_posix())
    if hashlib.sha256(guarded.read_bytes()).hexdigest() != expected_digest:
        raise HistoricalProjectionPathError(
            f"historical-module-source-drift:{module_name}"
        )
    return importlib.import_module(module_name)


def _root_key(root: Path) -> str:
    return os.path.normcase(str(root.absolute()))


def _claim_fresh_root(root: Path) -> None:
    absolute, _ = _safe_root(root)
    try:
        absolute.relative_to(ROOT.absolute())
    except ValueError as error:
        raise HistoricalProjectionPathError(
            "temporary-root-outside-workspace"
        ) from error
    if any(absolute.iterdir()):
        raise HistoricalProjectionPathError("temporary-root-not-fresh")
    with _OWNED_LOCK:
        key = _root_key(absolute)
        if key in _OWNED:
            raise HistoricalProjectionPathError("temporary-root-already-owned")
        _OWNED.add(key)


def _require_owned_root(root: Path) -> Path:
    absolute, _ = _safe_root(root)
    with _OWNED_LOCK:
        if _root_key(absolute) not in _OWNED:
            raise HistoricalProjectionPathError("temporary-root-not-plugin-owned")
    return absolute


def _safe_parent_for_new_target(root: Path, relative: str) -> Path:
    parts = _canonical_parts(relative)
    absolute_root = _require_owned_root(root)
    current = absolute_root
    for index, part in enumerate(parts[:-1], 1):
        candidate = current / part
        if not candidate.exists() and not candidate.is_symlink():
            candidate.mkdir()
        current = _safe_existing(
            absolute_root,
            PurePosixPath(*parts[:index]).as_posix(),
            require_directory=True,
        )
    target = current / parts[-1]
    try:
        target.lstat()
    except FileNotFoundError:
        return target
    except OSError as error:
        raise HistoricalProjectionPathError(f"unreadable-target:{relative}") from error
    raise HistoricalProjectionPathError(f"preexisting-target:{relative}")


def _read_authority(relative: str) -> bytes:
    selected = FROZEN_PROJECTIONS.get(relative)
    authority_relative = selected[0] if selected is not None else relative
    path = _safe_existing(ROOT, authority_relative)
    data = path.read_bytes()
    if selected is not None:
        actual = hashlib.sha256(data).hexdigest()
        if actual != selected[1]:
            raise HistoricalProjectionPathError(f"frozen-projection-drift:{relative}")
    return data


def _write_new(root: Path, relative: str, data: bytes) -> None:
    target = _safe_parent_for_new_target(root, relative)
    try:
        with target.open("xb") as stream:
            _write_all(stream, data)
    except FileExistsError as error:
        raise HistoricalProjectionPathError(f"preexisting-target:{relative}") from error
    guarded = _safe_existing(root, relative)
    if hashlib.sha256(guarded.read_bytes()).digest() != hashlib.sha256(data).digest():
        raise HistoricalProjectionPathError(f"output-drift:{relative}")


def _write_all(stream: BinaryIO, data: bytes) -> None:
    written = stream.write(data)
    if written != len(data):
        raise HistoricalProjectionPathError("short-output-write")


def _manifest_references(relative: str, data: bytes) -> tuple[tuple[str, str], ...]:
    if not relative.endswith(".sha256"):
        return ()
    if b"\r" in data or not data.endswith(b"\n"):
        raise HistoricalProjectionPathError(f"noncanonical-manifest:{relative}")
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise HistoricalProjectionPathError(
            f"invalid-manifest-utf8:{relative}"
        ) from error
    for line in lines:
        digest, separator, referenced = line.partition("  ")
        _canonical_parts(referenced)
        if not separator or not _HEX64.fullmatch(digest) or referenced in seen:
            raise HistoricalProjectionPathError(f"malformed-manifest:{relative}")
        seen.add(referenced)
        entries.append((digest, referenced))
    if not entries:
        raise HistoricalProjectionPathError(f"empty-manifest:{relative}")
    return tuple(entries)


def _materialize_r12(module: ModuleType, destination: Path) -> tuple[str, ...]:
    root = _require_owned_root(Path(destination))
    queue: list[tuple[str | None, str]] = [
        (ROOT_AUTHORITIES[module.R11_ROOT], module.R11_ROOT),
        (
            ROOT_AUTHORITIES[module.R11_ACCEPTANCE_MANIFEST],
            module.R11_ACCEPTANCE_MANIFEST,
        ),
        *((ROOT_AUTHORITIES[relative], relative) for relative in module.R11_EXTRA_LIVE),
    ]
    copied: set[str] = set()
    expected_by_path: dict[str, str] = {}
    while queue:
        expected, relative = queue.pop(0)
        prior = expected_by_path.get(relative)
        if expected is not None:
            if prior is not None and prior != expected:
                raise HistoricalProjectionPathError(
                    f"conflicting-authority-digest:{relative}"
                )
            expected_by_path[relative] = expected
        if relative in copied:
            continue
        data = _read_authority(relative)
        actual = hashlib.sha256(data).hexdigest()
        if expected is not None and actual != expected:
            raise HistoricalProjectionPathError(f"authority-drift:{relative}")
        _write_new(root, relative, data)
        copied.add(relative)
        queue.extend(_manifest_references(relative, data))
    # This is the final input validation before the temporary gitfile is
    # produced.  The exact .git node and the path root/final components have
    # passed the canonical containment, exact-case and no-reparse gate.
    git_directory = _validated_repository_git_directory()
    git_data = f"gitdir: {git_directory.as_posix()}\n".encode()
    _write_new(root, ".git", git_data)
    return tuple(sorted(copied))


class _OwnedTemporaryDirectory:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self._inner = _ORIGINAL_TEMPORARY_DIRECTORY(*args, **kwargs)
        self.name = self._inner.name
        self._root = Path(self.name)
        _claim_fresh_root(self._root)
        self._cleaned = False

    def __enter__(self) -> str:
        return self.name

    def cleanup(self) -> None:
        if self._cleaned:
            return
        key = _root_key(self._root)
        try:
            self._inner.cleanup()
        finally:
            with _OWNED_LOCK:
                _OWNED.discard(key)
            self._cleaned = True
        if self._root.exists() or self._root.is_symlink():
            raise HistoricalProjectionPathError("temporary-root-cleanup-failed")

    def __exit__(self, exc: object, value: object, traceback: object) -> None:
        self.cleanup()


class _TempfileProxy:
    TemporaryDirectory = _OwnedTemporaryDirectory

    def __getattr__(self, name: str) -> object:
        return getattr(_stdlib_tempfile, name)


_TEMPFILE_PROXY = _TempfileProxy()


def _install_projection_wrapper(module: ModuleType) -> None:
    original = getattr(module, "materialize_r11")
    if getattr(original, "_onyx_v12_frozen_projections", False):
        return

    @functools.wraps(original)
    def materialize_r11(destination: Path) -> tuple[str, ...]:
        return _materialize_r12(module, Path(destination))

    materialize_r11._onyx_v12_frozen_projections = True  # type: ignore[attr-defined]
    module.materialize_r11 = materialize_r11
    module.tempfile = _TEMPFILE_PROXY


def pytest_collection_modifyitems(items: list[object]) -> None:
    evidence_by_stem: dict[str, ModuleType] = {}
    for version in range(2, 8):
        module = _load_guarded_historical_verifier(version)
        _install_projection_wrapper(module)
        evidence_by_stem[f"test_approval_inbox_v{version}.py"] = module
    for item in items:
        path = Path(str(getattr(item, "path", "")))
        if path.name in evidence_by_stem:
            test_module = getattr(item, "module", None)
            if test_module is not None:
                test_module.tempfile = _TEMPFILE_PROXY
