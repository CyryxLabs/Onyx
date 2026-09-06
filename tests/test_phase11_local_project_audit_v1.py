import io
import gc
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import warnings
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from core.phase11_local_project_audit_v1 import (
    AuditGitError,
    AuditScopeError,
    AuditTimeoutError,
    LocalProjectAuditV1,
    ReceiptTamperError,
    SnapshotTamperError,
    _snapshot_digest,
)


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    ).stdout


class LocalProjectAuditV1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "repo"
        self.root.mkdir()
        _git(self.root, "init", "-q")
        _git(self.root, "config", "user.email", "onyx-tests@invalid.local")
        _git(self.root, "config", "user.name", "Onyx Tests")
        (self.root / "tracked.txt").write_bytes(b"committed\n")
        _git(self.root, "add", "tracked.txt")
        _git(self.root, "commit", "-qm", "initial")
        self.audit = LocalProjectAuditV1(
            allowed_roots=(self.base,), receipt_key=b"r" * 32
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_root_passes_and_commands_are_fixed_read_only(self):
        calls = []

        def factory(command, **kwargs):
            calls.append((tuple(command), dict(kwargs)))
            return subprocess.Popen(command, **kwargs)

        audit = LocalProjectAuditV1(
            allowed_roots=(self.base,),
            receipt_key=b"k" * 32,
            process_factory=factory,
        )
        snapshot = audit.capture(self.root)
        receipt = audit.verify(snapshot)
        audit.validate_receipt(receipt)
        self.assertEqual(receipt.verdict, "PASS")
        self.assertEqual(snapshot.dirty_files, ())
        self.assertTrue(calls)
        self.assertTrue(
            all(
                command[:3] == ("git", "-C", str(self.root))
                and options["shell"] is False
                and options["env"]["GIT_OPTIONAL_LOCKS"] == "0"
                and options["env"]["GIT_TERMINAL_PROMPT"] == "0"
                and options["env"]["LC_ALL"] == "C"
                for command, options in calls
            )
        )

    def test_capture_preserves_git_index_bytes_and_mtime(self):
        index = self.root / ".git" / "index"
        before = (index.read_bytes(), index.stat().st_mtime_ns)
        self.audit.capture(self.root)
        after = (index.read_bytes(), index.stat().st_mtime_ns)
        self.assertEqual(after, before)

    def test_dirty_and_untracked_bytes_are_preserved(self):
        tracked = self.root / "tracked.txt"
        untracked = self.root / "new file.bin"
        tracked.write_bytes(b"locally edited\x00bytes")
        untracked.write_bytes(b"\x00\xffuntracked")
        before_tracked = tracked.read_bytes()
        before_untracked = untracked.read_bytes()
        before_status = _git(
            self.root, "status", "--porcelain=v2", "-z", "--untracked-files=all"
        )

        snapshot = self.audit.capture(self.root)
        receipt = self.audit.verify(snapshot)

        self.assertEqual(receipt.verdict, "PASS")
        self.assertEqual(tracked.read_bytes(), before_tracked)
        self.assertEqual(untracked.read_bytes(), before_untracked)
        self.assertEqual(
            _git(self.root, "status", "--porcelain=v2", "-z", "--untracked-files=all"),
            before_status,
        )
        self.assertEqual(
            {item.path for item in snapshot.dirty_files},
            {"new file.bin", "tracked.txt"},
        )

    def test_content_change_with_same_dirty_status_is_drift(self):
        target = self.root / "tracked.txt"
        target.write_bytes(b"first dirty value")
        baseline = self.audit.capture(self.root)
        target.write_bytes(b"other dirty value")

        receipt = self.audit.verify(baseline)

        self.assertEqual(receipt.verdict, "DRIFT")
        self.assertEqual(receipt.reason, "workspace_drift")
        self.audit.validate_receipt(receipt)

    def test_non_git_relative_nested_and_outside_roots_are_rejected(self):
        nongit = self.base / "nongit"
        nongit.mkdir()
        outside_tmp = tempfile.TemporaryDirectory()
        try:
            with self.assertRaises(AuditScopeError):
                self.audit.capture("repo")
            with self.assertRaises(AuditGitError):
                self.audit.capture(nongit)
            with self.assertRaises(AuditScopeError):
                self.audit.capture(Path(outside_tmp.name).resolve())
            nested = self.root / "nested"
            nested.mkdir()
            with self.assertRaises(AuditGitError):
                self.audit.capture(nested)
        finally:
            outside_tmp.cleanup()

    def test_symlink_root_is_rejected_when_supported(self):
        link = self.base / "repo-link"
        try:
            link.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlinks are unavailable")
        with self.assertRaises(AuditScopeError):
            self.audit.capture(link)

    def test_timeout_is_closed_and_injectable(self):
        class TimedOutProcess:
            def __init__(self):
                self.stdout = io.BytesIO()
                self.stderr = io.BytesIO()
                self.returncode = None
                self.killed = False

            def wait(self, timeout=None):
                raise subprocess.TimeoutExpired(["git"], timeout)

            def terminate(self):
                pass

            def kill(self):
                self.killed = True

        processes = []
        def factory(*_args, **_kwargs):
            process = TimedOutProcess()
            processes.append(process)
            return process
        audit = LocalProjectAuditV1(
            allowed_roots=(self.base,),
            command_timeout_seconds=0.01,
            process_factory=factory,
        )
        with self.assertRaises(AuditTimeoutError):
            audit.capture(self.root)
        self.assertTrue(processes[0].killed)
        self.assertTrue(processes[0].stdout.closed)
        self.assertTrue(processes[0].stderr.closed)

    def test_large_git_output_is_bounded_and_process_is_stopped(self):
        class LargeProcess:
            def __init__(self):
                self.stdout = io.BytesIO(b"x" * 4096)
                self.stderr = io.BytesIO()
                self.returncode = 0
                self.terminated = threading.Event()

            def wait(self, timeout=None):
                self.terminated.wait(timeout)
                return self.returncode

            def terminate(self):
                self.terminated.set()

            def kill(self):
                self.terminated.set()

        process = LargeProcess()
        audit = LocalProjectAuditV1(
            allowed_roots=(self.base,),
            max_git_output_bytes=64,
            process_factory=lambda *_args, **_kwargs: process,
        )
        from core.phase11_local_project_audit_v1 import AuditLimitError
        with self.assertRaises(AuditLimitError):
            audit.capture(self.root)
        self.assertTrue(process.terminated.is_set())

    def test_real_process_over_cap_is_killed_reaped_and_fails_quickly(self):
        processes = []

        def factory(_command, **kwargs):
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "import os,time;os.write(1,b'x'*65);time.sleep(30)",
                ],
                **kwargs,
            )
            processes.append(process)
            return process

        audit = LocalProjectAuditV1(
            allowed_roots=(self.base,),
            max_git_output_bytes=64,
            command_timeout_seconds=10,
            process_factory=factory,
        )
        started = time.monotonic()
        from core.phase11_local_project_audit_v1 import AuditLimitError
        with self.assertRaises(AuditLimitError):
            audit.capture(self.root)
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertIsNotNone(processes[0].poll())

    def test_git_closes_streams_and_process_handle_on_all_paths(self):
        class Handle:
            def __init__(self):
                self.closed = False

            def Close(self):
                self.closed = True

        class Process:
            def __init__(self, *, returncode=0, failure=None):
                self.stdin = None
                self.stdout = io.BytesIO(b"ok")
                self.stderr = io.BytesIO()
                self.returncode = returncode
                self._handle = Handle()
                self.failure = failure
                self.terminated = False
                self.killed = False

            def wait(self, timeout=None):
                del timeout
                if self.failure is not None:
                    failure, self.failure = self.failure, None
                    raise failure
                if self.returncode is None:
                    self.returncode = -1 if self.terminated else -9
                return self.returncode

            def terminate(self):
                self.terminated = True
                self.returncode = -1

            def kill(self):
                self.killed = True
                self.returncode = -9

        successful = Process()
        audit = LocalProjectAuditV1(
            allowed_roots=(self.base,),
            process_factory=lambda *_args, **_kwargs: successful,
        )
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always", ResourceWarning)
            self.assertEqual(audit._git(self.root, ("status",)), b"ok")
            gc.collect()
        self.assertFalse(
            any(item.category is ResourceWarning for item in observed)
        )
        self.assertTrue(successful.stdout.closed)
        self.assertTrue(successful.stderr.closed)
        self.assertTrue(successful._handle.closed)

        nonzero = Process(returncode=1)
        audit._process_factory = lambda *_args, **_kwargs: nonzero
        with self.assertRaises(AuditGitError):
            audit._git(self.root, ("status",))
        self.assertTrue(nonzero.stdout.closed)
        self.assertTrue(nonzero.stderr.closed)
        self.assertTrue(nonzero._handle.closed)

        primary = KeyboardInterrupt("primary")
        failed = Process(returncode=None, failure=primary)
        audit._process_factory = lambda *_args, **_kwargs: failed
        with self.assertRaises(KeyboardInterrupt) as raised:
            audit._git(self.root, ("status",))
        self.assertIs(raised.exception, primary)
        self.assertTrue(failed.terminated)
        self.assertIsNotNone(failed.returncode)
        self.assertTrue(failed.stdout.closed)
        self.assertTrue(failed.stderr.closed)
        self.assertTrue(failed._handle.closed)

    def test_rename_without_original_nul_record_is_rejected(self):
        malformed = (
            b"2 R. N... 100644 100644 100644 "
            b"0123456789012345678901234567890123456789 "
            b"0123456789012345678901234567890123456789 R100 new.txt\0"
        )
        with self.assertRaises(AuditGitError):
            self.audit._status_paths(malformed)

    def test_snapshot_and_receipt_tamper_are_detected(self):
        baseline = self.audit.capture(self.root)
        with self.assertRaises(SnapshotTamperError):
            self.audit.verify(replace(baseline, head="0" * 40))
        recomputed = replace(baseline, head="1" * 40)
        recomputed = replace(
            recomputed, snapshot_sha256=_snapshot_digest(recomputed)
        )
        with self.assertRaises(SnapshotTamperError):
            self.audit.verify(recomputed)
        receipt = self.audit.verify(baseline)
        with self.assertRaises(ReceiptTamperError):
            self.audit.validate_receipt(replace(receipt, verdict="DRIFT"))
        with self.assertRaises(ReceiptTamperError):
            self.audit.validate_receipt(replace(receipt, signature="0" * 64))

    def test_capture_and_verify_do_not_open_network(self):
        with (
            patch.object(socket, "socket", side_effect=AssertionError("network used")),
            patch.object(
                socket, "create_connection", side_effect=AssertionError("network used")
            ),
        ):
            baseline = self.audit.capture(self.root)
            receipt = self.audit.verify(baseline)
        self.assertEqual(receipt.verdict, "PASS")


if __name__ == "__main__":
    unittest.main()
