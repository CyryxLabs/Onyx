"""Provider-free, read-only local Git snapshot and verification receipts."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Callable, Iterable, Sequence


SCHEMA_VERSION = "phase11.local_project_audit.v1"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_DIRTY_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_DIRTY_FILES = 2_000

class LocalProjectAuditError(RuntimeError):
    pass


class AuditScopeError(LocalProjectAuditError):
    pass


class AuditGitError(LocalProjectAuditError):
    pass


class AuditTimeoutError(LocalProjectAuditError):
    pass


class AuditLimitError(LocalProjectAuditError):
    pass


class SnapshotTamperError(LocalProjectAuditError):
    pass


class ReceiptTamperError(LocalProjectAuditError):
    pass


@dataclass(frozen=True)
class DirtyFileDigestV1:
    path: str
    state: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ProjectSnapshotV1:
    schema: str
    root: str
    head: str
    status_sha256: str
    dirty_files: tuple[DirtyFileDigestV1, ...]
    dirty_bytes: int
    snapshot_sha256: str
    signature: str


@dataclass(frozen=True)
class VerificationReceiptV1:
    schema: str
    root: str
    baseline_sha256: str
    observed_sha256: str
    verdict: str
    reason: str
    issued_at_ns: int
    signature: str


ProcessFactory = Callable[..., subprocess.Popen[bytes]]
_SNAPSHOT_DOMAIN = b"ONYX/PHASE11/SNAPSHOT/V1\0"
_RECEIPT_DOMAIN = b"ONYX/PHASE11/RECEIPT/V1\0"

def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _is_reparse(path: Path) -> bool:
    try:
        attributes = path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return False
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & flag)


def _reject_link_chain(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.exists() and (current.is_symlink() or _is_reparse(current)):
            raise AuditScopeError("linked or reparse workspace paths are forbidden")


def _snapshot_payload(snapshot: ProjectSnapshotV1) -> dict[str, object]:
    return {
        "schema": snapshot.schema,
        "root": snapshot.root,
        "head": snapshot.head,
        "status_sha256": snapshot.status_sha256,
        "dirty_files": [asdict(item) for item in snapshot.dirty_files],
        "dirty_bytes": snapshot.dirty_bytes,
    }


def _snapshot_digest(snapshot: ProjectSnapshotV1) -> str:
    return hashlib.sha256(_canonical(_snapshot_payload(snapshot))).hexdigest()


def _receipt_payload(receipt: VerificationReceiptV1) -> dict[str, object]:
    return {
        "schema": receipt.schema,
        "root": receipt.root,
        "baseline_sha256": receipt.baseline_sha256,
        "observed_sha256": receipt.observed_sha256,
        "verdict": receipt.verdict,
        "reason": receipt.reason,
        "issued_at_ns": receipt.issued_at_ns,
    }


class LocalProjectAuditV1:
    """Capture and independently verify a bounded, explicitly allowed Git root."""

    def __init__(
        self,
        *,
        allowed_roots: Iterable[str | os.PathLike[str]],
        command_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_dirty_bytes: int = DEFAULT_MAX_DIRTY_BYTES,
        max_dirty_files: int = DEFAULT_MAX_DIRTY_FILES,
        max_git_output_bytes: int = 4 * 1024 * 1024,
        process_factory: ProcessFactory = subprocess.Popen,
        receipt_key: bytes | None = None,
        snapshot_key: bytes | None = None,
    ) -> None:
        roots = tuple(self._validate_allowed_root(Path(item)) for item in allowed_roots)
        if not roots:
            raise AuditScopeError("at least one explicit allowed root is required")
        if command_timeout_seconds <= 0:
            raise ValueError("command_timeout_seconds must be positive")
        if max_dirty_bytes < 0 or max_dirty_files <= 0 or max_git_output_bytes <= 0:
            raise ValueError("audit limits must be non-negative")
        self._allowed_roots = roots
        self._timeout = float(command_timeout_seconds)
        self._max_dirty_bytes = int(max_dirty_bytes)
        self._max_dirty_files = int(max_dirty_files)
        self._max_git_output_bytes = int(max_git_output_bytes)
        self._process_factory = process_factory
        self._receipt_key = receipt_key or secrets.token_bytes(32)
        if len(self._receipt_key) < 16:
            raise ValueError("receipt_key must contain at least 16 bytes")
        self._snapshot_key = snapshot_key or hmac.new(
            self._receipt_key, _SNAPSHOT_DOMAIN + b"KEY", hashlib.sha256
        ).digest()
        if len(self._snapshot_key) < 16:
            raise ValueError("snapshot_key must contain at least 16 bytes")

    @staticmethod
    def _validate_allowed_root(path: Path) -> Path:
        if not path.is_absolute():
            raise AuditScopeError("allowed roots must be absolute")
        absolute = path.absolute()
        _reject_link_chain(absolute)
        if not absolute.is_dir():
            raise AuditScopeError("allowed root must be an existing directory")
        return absolute.resolve()

    def _validate_requested_root(self, root: str | os.PathLike[str]) -> Path:
        requested = Path(root)
        if not requested.is_absolute():
            raise AuditScopeError("project root must be explicit and absolute")
        absolute = requested.absolute()
        _reject_link_chain(absolute)
        if not absolute.is_dir():
            raise AuditScopeError("project root must be an existing directory")
        resolved = absolute.resolve()
        if not any(
            resolved == allowed or resolved.is_relative_to(allowed)
            for allowed in self._allowed_roots
        ):
            raise AuditScopeError("project root is outside the explicit allowlist")
        return resolved

    @staticmethod
    def _git_environment() -> dict[str, str]:
        inherited = ("SystemRoot", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP",
                     "HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
        environment = {key: os.environ[key] for key in inherited if key in os.environ}
        environment.update(GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", LC_ALL="C")
        return environment

    @staticmethod
    def _stop_process(
        process: subprocess.Popen[bytes],
    ) -> tuple[BaseException, ...]:
        failures: list[BaseException] = []
        try:
            process.terminate()
        except BaseException as exc:
            failures.append(exc)
        try:
            process.wait(timeout=0.5)
            return tuple(failures)
        except BaseException as exc:
            failures.append(exc)
        try:
            process.kill()
        except BaseException as exc:
            failures.append(exc)
        try:
            process.wait(timeout=0.5)
        except BaseException as exc:
            failures.append(exc)
        return tuple(failures)

    @staticmethod
    def _close_process_resources(
        process: subprocess.Popen[bytes],
        *,
        failures: Iterable[BaseException] = (),
    ) -> None:
        cleanup_failures = list(failures)
        for stream_name in ("stdin", "stdout", "stderr"):
            stream = getattr(process, stream_name, None)
            close = getattr(stream, "close", None)
            if close is not None:
                try:
                    close()
                except BaseException as exc:
                    cleanup_failures.append(exc)
        handle = getattr(process, "_handle", None)
        close_handle = getattr(handle, "Close", None)
        if close_handle is None:
            close_handle = getattr(handle, "close", None)
        if close_handle is not None:
            try:
                close_handle()
            except BaseException as exc:
                cleanup_failures.append(exc)
        if cleanup_failures and sys.exc_info()[0] is None:
            raise AuditGitError(
                "Git process resources could not be closed"
            ) from cleanup_failures[0]

    def _git(self, root: Path, arguments: Sequence[str]) -> bytes:
        command = ["git", "-C", str(root), *arguments]
        readers: list[threading.Thread] = []
        try:
            process = self._process_factory(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                env=self._git_environment(),
            )
        except (FileNotFoundError, OSError) as exc:
            raise AuditGitError("Git workspace inspection failed") from exc
        try:
            if process.stdout is None or process.stderr is None:
                self._stop_process(process)
                raise AuditGitError("Git pipes were not created")
            chunks: dict[str, list[bytes]] = {"stdout": [], "stderr": []}
            lock = threading.Lock()
            exceeded = threading.Event()
            failures: list[BaseException] = []
            consumed = 0

            def drain(name: str, stream: object) -> None:
                nonlocal consumed
                try:
                    while True:
                        with lock:
                            read_size = min(
                                65_536,
                                self._max_git_output_bytes - consumed + 1,
                            )
                        chunk = stream.read(read_size)  # type: ignore[attr-defined]
                        if not chunk:
                            return
                        if not isinstance(chunk, bytes):
                            failures.append(TypeError("Git stream was not bytes"))
                            exceeded.set()
                            self._stop_process(process)
                            return
                        with lock:
                            if consumed + len(chunk) > self._max_git_output_bytes:
                                exceeded.set()
                            else:
                                consumed += len(chunk)
                                chunks[name].append(chunk)
                        if exceeded.is_set():
                            self._stop_process(process)
                            return
                except BaseException as exc:
                    failures.append(exc)
                    exceeded.set()
                    self._stop_process(process)

            readers = [
                threading.Thread(
                    target=drain,
                    args=("stdout", process.stdout),
                    daemon=True,
                ),
                threading.Thread(
                    target=drain,
                    args=("stderr", process.stderr),
                    daemon=True,
                ),
            ]
            for reader in readers:
                reader.start()
            try:
                process.wait(timeout=self._timeout)
            except subprocess.TimeoutExpired as exc:
                self._stop_process(process)
                for reader in readers:
                    reader.join(timeout=1.0)
                raise AuditTimeoutError("bounded Git command timed out") from exc
            for reader in readers:
                reader.join(timeout=1.0)
            if any(reader.is_alive() for reader in readers):
                self._stop_process(process)
                raise AuditGitError("Git output readers did not terminate")
            if exceeded.is_set():
                raise AuditLimitError("Git output byte budget exceeded")
            if failures:
                raise AuditGitError("Git output could not be read") from failures[0]
            if process.returncode != 0:
                raise AuditGitError("Git workspace inspection failed")
            return b"".join(chunks["stdout"])
        finally:
            cleanup_failures: list[BaseException] = []
            if getattr(process, "returncode", None) is None:
                cleanup_failures.extend(self._stop_process(process))
            for reader in readers:
                reader.join(timeout=1.0)
                if reader.is_alive():
                    cleanup_failures.append(
                        RuntimeError("Git output reader remained active")
                    )
            self._close_process_resources(
                process,
                failures=cleanup_failures,
            )

    def _assert_git_top_level(self, root: Path) -> None:
        raw = self._git(root, ("rev-parse", "--show-toplevel"))
        try:
            top = Path(raw.decode("utf-8", errors="strict").strip()).resolve()
        except (UnicodeDecodeError, OSError) as exc:
            raise AuditGitError("Git top-level could not be decoded") from exc
        if top != root:
            raise AuditGitError("project root must be the exact Git top-level")

    @staticmethod
    def _status_paths(status: bytes) -> tuple[tuple[str, str], ...]:
        records = status.split(b"\0")
        found: list[tuple[str, str]] = []
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            if record.startswith(b"1 "):
                parts = record.split(b" ", 8)
                if len(parts) != 9:
                    raise AuditGitError("malformed Git ordinary status record")
                state, raw_path = parts[1].decode("ascii", "strict"), parts[8]
            elif record.startswith(b"2 "):
                parts = record.split(b" ", 9)
                if len(parts) != 10:
                    raise AuditGitError("malformed Git rename status record")
                state, raw_path = parts[1].decode("ascii", "strict"), parts[9]
                if index >= len(records) or not records[index]:
                    raise AuditGitError("Git rename status omitted the original path")
                index += 1  # the next NUL record is the original path
            elif record.startswith(b"u "):
                parts = record.split(b" ", 10)
                if len(parts) != 11:
                    raise AuditGitError("malformed Git unmerged status record")
                state, raw_path = parts[1].decode("ascii", "strict"), parts[10]
            elif record.startswith(b"? "):
                state, raw_path = "??", record[2:]
            elif record.startswith(b"! "):
                continue
            else:
                raise AuditGitError("unsupported Git porcelain record")
            try:
                path = raw_path.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise AuditGitError("Git path is not strict UTF-8") from exc
            relative = Path(path)
            if not path or relative.is_absolute() or ".." in relative.parts:
                raise AuditScopeError("unsafe path returned by Git")
            found.append((path, state))
        return tuple(sorted(set(found)))

    @staticmethod
    def _read_regular_file(root: Path, relative: str, remaining: int) -> bytes | None:
        path = root / Path(relative)
        _reject_link_chain(path)
        try:
            before = path.lstat()
        except FileNotFoundError:
            return None
        if (
            path.is_symlink()
            or _is_reparse(path)
            or not stat.S_ISREG(before.st_mode)
        ):
            raise AuditScopeError("dirty paths must be regular non-linked files")
        if before.st_size > remaining:
            raise AuditLimitError("dirty-file byte budget exceeded")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise AuditScopeError("dirty file could not be opened safely") from exc
        try:
            held = os.fstat(descriptor)
            if (
                not stat.S_ISREG(held.st_mode)
                or (held.st_dev, held.st_ino) != (before.st_dev, before.st_ino)
                or held.st_size > remaining
            ):
                raise AuditScopeError("dirty file identity changed during capture")
            chunks: list[bytes] = []
            bytes_left = held.st_size + 1
            while bytes_left:
                chunk = os.read(descriptor, min(65_536, bytes_left))
                if not chunk:
                    break
                chunks.append(chunk)
                bytes_left -= len(chunk)
            content = b"".join(chunks)
            after = path.lstat()
            if (
                len(content) != held.st_size
                or (after.st_dev, after.st_ino) != (held.st_dev, held.st_ino)
                or after.st_size != held.st_size
                or after.st_mtime_ns != held.st_mtime_ns
                or path.is_symlink()
                or _is_reparse(path)
            ):
                raise AuditScopeError("dirty file changed during capture")
            return content
        finally:
            os.close(descriptor)

    def capture(self, root: str | os.PathLike[str]) -> ProjectSnapshotV1:
        project_root = self._validate_requested_root(root)
        self._assert_git_top_level(project_root)
        head_raw = self._git(project_root, ("rev-parse", "--verify", "HEAD"))
        try:
            head = head_raw.decode("ascii", errors="strict").strip()
        except UnicodeDecodeError as exc:
            raise AuditGitError("Git HEAD is not ASCII") from exc
        if len(head) not in (40, 64) or any(char not in "0123456789abcdefABCDEF" for char in head):
            raise AuditGitError("Git HEAD is invalid")
        status = self._git(
            project_root,
            ("status", "--porcelain=v2", "-z", "--untracked-files=all"),
        )
        paths = self._status_paths(status)
        if len(paths) > self._max_dirty_files:
            raise AuditLimitError("dirty-file count budget exceeded")
        dirty: list[DirtyFileDigestV1] = []
        total = 0
        for relative, state in paths:
            content = self._read_regular_file(
                project_root, relative, self._max_dirty_bytes - total
            )
            if content is None:
                dirty.append(
                    DirtyFileDigestV1(
                        path=relative,
                        state=state,
                        size=-1,
                        sha256=hashlib.sha256(b"<missing>").hexdigest(),
                    )
                )
                continue
            total += len(content)
            dirty.append(
                DirtyFileDigestV1(
                    path=relative,
                    state=state,
                    size=len(content),
                    sha256=hashlib.sha256(content).hexdigest(),
                )
            )
        unsigned = ProjectSnapshotV1(
            schema=SCHEMA_VERSION,
            root=str(project_root),
            head=head.lower(),
            status_sha256=hashlib.sha256(status).hexdigest(),
            dirty_files=tuple(dirty),
            dirty_bytes=total,
            snapshot_sha256="",
            signature="",
        )
        digest = _snapshot_digest(unsigned)
        signature = hmac.new(
            self._snapshot_key, _SNAPSHOT_DOMAIN + digest.encode("ascii"), hashlib.sha256
        ).hexdigest()
        return replace(unsigned, snapshot_sha256=digest, signature=signature)

    def validate_snapshot(self, snapshot: ProjectSnapshotV1) -> None:
        digest = _snapshot_digest(snapshot)
        signature = hmac.new(
            self._snapshot_key, _SNAPSHOT_DOMAIN + digest.encode("ascii"), hashlib.sha256
        ).hexdigest()
        if snapshot.schema != SCHEMA_VERSION or not hmac.compare_digest(
            snapshot.snapshot_sha256, digest
        ) or not hmac.compare_digest(snapshot.signature, signature):
            raise SnapshotTamperError("snapshot integrity verification failed")

    def verify(self, baseline: ProjectSnapshotV1) -> VerificationReceiptV1:
        self.validate_snapshot(baseline)
        observed = self.capture(baseline.root)
        verdict = (
            "PASS"
            if hmac.compare_digest(baseline.snapshot_sha256, observed.snapshot_sha256)
            else "DRIFT"
        )
        unsigned = VerificationReceiptV1(
            schema=SCHEMA_VERSION,
            root=baseline.root,
            baseline_sha256=baseline.snapshot_sha256,
            observed_sha256=observed.snapshot_sha256,
            verdict=verdict,
            reason="snapshot_match" if verdict == "PASS" else "workspace_drift",
            issued_at_ns=time.time_ns(),
            signature="",
        )
        signature = hmac.new(
            self._receipt_key,
            _RECEIPT_DOMAIN + _canonical(_receipt_payload(unsigned)),
            hashlib.sha256,
        ).hexdigest()
        return replace(unsigned, signature=signature)

    def validate_receipt(self, receipt: VerificationReceiptV1) -> None:
        if receipt.schema != SCHEMA_VERSION or receipt.verdict not in {"PASS", "DRIFT"}:
            raise ReceiptTamperError("receipt fields are invalid")
        expected = hmac.new(
            self._receipt_key,
            _RECEIPT_DOMAIN + _canonical(_receipt_payload(receipt)),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(receipt.signature, expected):
            raise ReceiptTamperError("receipt integrity verification failed")


__all__ = [
    "AuditGitError",
    "AuditLimitError",
    "AuditScopeError",
    "AuditTimeoutError",
    "DirtyFileDigestV1",
    "LocalProjectAuditError",
    "LocalProjectAuditV1",
    "ProjectSnapshotV1",
    "ReceiptTamperError",
    "SnapshotTamperError",
    "VerificationReceiptV1",
]
