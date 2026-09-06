"""Hermetic historical projections for the frozen Approval Inbox lineage.

V13 never reads either mutable live documentation path while materializing the
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
import importlib.machinery
import os
import re
import secrets
import stat
import sys
import tempfile as _stdlib_tempfile
import threading
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import BinaryIO

from scripts import verify_r11_projection_retirement_v1 as r11_retirement


ROOT = Path(__file__).absolute().parents[1]
FROZEN_BASE_COMMIT = "b2dc0b21f487013cebec34bb148ffb1aeb02611a"
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
    """A historical authority or output path crossed the V13 boundary."""


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


def _load_guarded_historical_verifier(version: int) -> ModuleType:
    relative, expected_digest = HISTORICAL_VERIFIER_SOURCES[version]
    return _load_exact_authoritative_module(
        relative, expected_digest, f"historical_verifier_v{version}"
    )


class _ExactSourceLoader:
    """Identity marker for source executed from bytes read through our gate."""

    def __init__(self, path: Path, digest: str) -> None:
        self.path = str(path)
        self.digest = digest


def _load_exact_authoritative_module(
    relative: str, expected_digest: str, label: str
) -> ModuleType:
    """Execute exactly one bound source without consulting import caches/hooks."""

    guarded = _safe_existing(ROOT, relative)
    before = guarded.lstat()
    source = guarded.read_bytes()
    if hashlib.sha256(source).hexdigest() != expected_digest:
        raise HistoricalProjectionPathError(f"module-source-drift:{label}")
    # Re-enter immediately before compile/exec.  A stable authoritative tree is
    # required across these non-atomic filesystem operations.
    guarded = _safe_existing(ROOT, relative)
    after = guarded.lstat()
    identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
        raise HistoricalProjectionPathError(f"module-source-identity-drift:{label}")
    private_name = f"_onyx_p52_v13_{label}_{secrets.token_hex(16)}"
    if private_name in sys.modules:
        sys.modules.pop(private_name, None)
        raise HistoricalProjectionPathError(f"private-module-preexisting:{label}")
    loader = _ExactSourceLoader(guarded, expected_digest)
    spec = importlib.machinery.ModuleSpec(
        private_name, loader, origin=str(guarded), is_package=False
    )
    module = ModuleType(private_name)
    module.__file__ = str(guarded)
    module.__loader__ = loader
    module.__package__ = ""
    module.__spec__ = spec
    try:
        code = compile(source, str(guarded), "exec", dont_inherit=True)
        exec(code, module.__dict__)
        regated = _safe_existing(ROOT, relative)
        current = regated.lstat()
        if (
            (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
            != identity
            or hashlib.sha256(regated.read_bytes()).hexdigest() != expected_digest
            or module.__file__ != str(regated)
            or module.__spec__ is not spec
            or module.__spec__.origin != str(regated)
            or module.__loader__ is not loader
            or private_name in sys.modules
        ):
            raise HistoricalProjectionPathError(f"loaded-module-identity-drift:{label}")
        return module
    finally:
        sys.modules.pop(private_name, None)


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


def _materialize_r13(module: ModuleType, destination: Path) -> tuple[str, ...]:
    root = _require_owned_root(Path(destination))
    try:
        copied = r11_retirement.materialize_r11(
            module,
            root,
            write=lambda destination, relative, data: _write_new(
                destination, relative, data
            ),
        )
    except r11_retirement.R11ProjectionRetirementError as error:
        raise HistoricalProjectionPathError(str(error)) from error
    # Historical verifiers need only a deterministic HEAD identity and a clean
    # diff-check surface.  A minimal private Git metadata tree avoids consuming
    # the live repository, its config, hooks, alternates or object database.
    _write_new(root, ".git/HEAD", b"ref: refs/heads/onyx-v13\n")
    _write_new(root, ".git/refs/heads/onyx-v13", FROZEN_BASE_COMMIT.encode() + b"\n")
    _write_new(
        root,
        ".git/config",
        b"[core]\n\trepositoryformatversion = 0\n\tbare = false\n",
    )
    _write_new(root, ".git/objects/info/.onyx-private", b"")
    return copied


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
    if getattr(original, "_onyx_v13_frozen_projections", False):
        return

    @functools.wraps(original)
    def materialize_r11(destination: Path) -> tuple[str, ...]:
        return _materialize_r13(module, Path(destination))

    materialize_r11._onyx_v13_frozen_projections = True  # type: ignore[attr-defined]
    module.materialize_r11 = materialize_r11

    original_verify = module.verify_historical_manifest_tree

    @functools.wraps(original_verify)
    def verify_historical_manifest_tree(
        root: Path, roots: tuple[str, ...]
    ) -> tuple[str, ...]:
        if roots == (module.R11_ROOT, module.R11_ACCEPTANCE_MANIFEST):
            try:
                return r11_retirement.verify_r11(module, root, roots)
            except r11_retirement.R11ProjectionRetirementError as error:
                raise HistoricalProjectionPathError(str(error)) from error
        return original_verify(root, roots)

    module.verify_historical_manifest_tree = verify_historical_manifest_tree
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
                test_module.evidence = evidence_by_stem[path.name]
