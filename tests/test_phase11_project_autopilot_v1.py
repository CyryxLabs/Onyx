from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch as mock_patch

import core.phase11_project_autopilot_v1 as autopilot_module
from core.missions import MissionStore
from core.permission_broker import set_permission_callback
from core.phase11_live_mission_v1 import Phase11LiveMissionV1
from core.phase11_handle_patch_v1 import HandlePatchEngineV1
from core.phase11_project_autopilot_v1 import (
    AutopilotEnvelopeV1,
    IndependentAutopilotVerifierV1,
    ProjectAutopilotContractError,
    ProjectAutopilotWaiting,
    ProjectAutopilotV1,
    feature_enabled,
)


PATCH = """diff --git a/demo.txt b/demo.txt
--- a/demo.txt
+++ b/demo.txt
@@ -1 +1 @@
-before
+after
"""

PY_PATCH = """diff --git a/module.py b/module.py
--- a/module.py
+++ b/module.py
@@ -1 +1 @@
-VALUE = 1
+VALUE =
"""

ADD_PATCH = """diff --git a/new.txt b/new.txt
new file mode 100644
--- /dev/null
+++ b/new.txt
@@ -0,0 +1,2 @@
+hello
+world
"""


class MemoryVault:
    def __init__(self):
        self.value = None

    def get_bytes(self):
        return self.value

    def set_bytes(self, value):
        self.value = bytes(value)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


class ProjectAutopilotV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.repo = base / "owner"
        self.repo.mkdir()
        _git(self.repo, "init")
        _git(self.repo, "config", "user.name", "Onyx Test")
        _git(self.repo, "config", "user.email", "onyx@example.invalid")
        (self.repo / "demo.txt").write_bytes(b"before\n")
        (self.repo / "module.py").write_bytes(b"VALUE = 1\n")
        (self.repo / ".gitattributes").write_bytes(b"module.py filter=evil\n")
        (self.repo / "conftest.py").write_bytes(
            b"from pathlib import Path\n"
            b"Path(__file__).with_name('CONFTST_EXECUTED').write_text('bad')\n"
        )
        (self.repo / "test_malicious.py").write_bytes(
            b"import os, socket, subprocess\n"
            b"open('TEST_EXECUTED', 'w').write('bad')\n"
            b"subprocess.Popen(['cmd', '/c', 'echo bad']) if os.name == 'nt' else None\n"
            b"socket.socket().connect(('127.0.0.1', 9))\n"
        )
        _git(
            self.repo,
            "add",
            "demo.txt",
            "module.py",
            ".gitattributes",
            "conftest.py",
            "test_malicious.py",
        )
        _git(self.repo, "commit", "-m", "base")
        self.head = _git(self.repo, "rev-parse", "HEAD").lower()
        self.control = base / "control"
        self.vaults: dict[str, MemoryVault] = {}
        self.vault_factory = lambda reference: self.vaults.setdefault(
            reference.account, MemoryVault()
        )
        self.engine = ProjectAutopilotV1(
            worktree_root=self.control,
            signing_key=b"k" * 32,
            enabled=True,
            checkpoint_vault_factory=self.vault_factory,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _envelope(
        self,
        gates: list[dict[str, object]] | None = None,
        *,
        patch_text: str = PATCH,
        max_output_bytes: int = 512_000,
    ):
        return AutopilotEnvelopeV1.build(
            root=str(self.repo.resolve()),
            base_head=self.head,
            owner_git_sha256=self.engine.capture_owner_git_state(self.repo),
            patch=patch_text,
            gates=gates
            or [{"argv": ["onyx-static", "diff-check"], "timeout_seconds": 30}],
            max_seconds=120,
            max_output_bytes=max_output_bytes,
        )

    def _cleanup_enabled_engine(
        self, terminal_state: list[str]
    ) -> ProjectAutopilotV1:
        target = Path(self.temporary.name) / (
            f"cleanup-control-{len(terminal_state)}-{len(self.vaults)}"
        )
        with mock_patch.dict(
            os.environ,
            {"ONYX_PHASE11_HANDLE_SAFE_CLONE_CLEANUP_V1": "true"},
        ):
            return ProjectAutopilotV1(
                worktree_root=target,
                signing_key=b"k" * 32,
                enabled=True,
                checkpoint_vault_factory=self.vault_factory,
                terminal_state_resolver=lambda _mission_id: (
                    terminal_state[0]
                ),
            )

    def test_bound_git_retry_is_bounded_and_never_replays_repository_code(self):
        mission_id = "mis_" + ("a" * 32)
        transient = {
            "status": "waiting",
            "data": {
                "checkpoint_stage": "bound",
                "repository_code_execution_state": "not_started",
            },
            "waiting_for": "trusted_git_command_failed",
        }
        succeeded = {
            "status": "succeeded",
            "data": {"repository_code_execution_state": "executed_receipt"},
            "waiting_for": None,
        }
        with (
            mock_patch.object(self.engine, "_mission_lock", return_value=nullcontext()),
            mock_patch.object(
                self.engine, "_mission_process_lock", return_value=nullcontext()
            ),
            mock_patch.object(
                self.engine,
                "_execute_locked",
                side_effect=(transient, succeeded),
            ) as execute_locked,
            mock_patch.object(autopilot_module.time, "sleep") as sleep,
        ):
            result = self.engine.execute(mission_id=mission_id)
        self.assertEqual(result, succeeded)
        self.assertEqual(execute_locked.call_count, 2)
        sleep.assert_called_once_with(0.05)

        attempted_unknown = {
            "status": "waiting",
            "data": {
                "checkpoint_stage": "executable_gate_pending",
                "repository_code_execution_state": "attempted_unknown",
            },
            "waiting_for": "trusted_git_command_failed",
        }
        with (
            mock_patch.object(self.engine, "_mission_lock", return_value=nullcontext()),
            mock_patch.object(
                self.engine, "_mission_process_lock", return_value=nullcontext()
            ),
            mock_patch.object(
                self.engine, "_execute_locked", return_value=attempted_unknown
            ) as execute_locked,
            mock_patch.object(autopilot_module.time, "sleep") as sleep,
        ):
            result = self.engine.execute(mission_id=mission_id)
        self.assertEqual(result, attempted_unknown)
        execute_locked.assert_called_once()
        sleep.assert_not_called()

        with (
            mock_patch.object(self.engine, "_mission_lock", return_value=nullcontext()),
            mock_patch.object(
                self.engine, "_mission_process_lock", return_value=nullcontext()
            ),
            mock_patch.object(
                self.engine, "_execute_locked", return_value=transient
            ) as execute_locked,
            mock_patch.object(autopilot_module.time, "sleep") as sleep,
        ):
            result = self.engine.execute(mission_id=mission_id)
        self.assertEqual(result, transient)
        self.assertEqual(execute_locked.call_count, 3)
        self.assertEqual([call.args for call in sleep.call_args_list], [(0.05,), (0.15,)])

    def test_private_git_environment_enables_windows_long_paths(self):
        environment = self.engine._environment()
        self.assertEqual(environment["GIT_CONFIG_COUNT"], "5")
        self.assertEqual(environment["GIT_CONFIG_KEY_4"], "core.longpaths")
        self.assertEqual(environment["GIT_CONFIG_VALUE_4"], "true")

    def test_bound_git_retry_requires_exact_safe_waiting_contract(self):
        mission_id = "mis_" + ("b" * 32)
        safe_data = {
            "checkpoint_stage": "bound",
            "repository_code_execution_state": "not_started",
        }
        cases = {
            "terminal_status": {
                "status": "succeeded",
                "data": safe_data,
                "waiting_for": "trusted_git_command_failed",
            },
            "different_waiting_reason": {
                "status": "waiting",
                "data": safe_data,
                "waiting_for": "owner_confirmation_required",
            },
            "non_mapping_data": {
                "status": "waiting",
                "data": None,
                "waiting_for": "trusted_git_command_failed",
            },
            "different_checkpoint_stage": {
                "status": "waiting",
                "data": {
                    **safe_data,
                    "checkpoint_stage": "static_gate_pending",
                },
                "waiting_for": "trusted_git_command_failed",
            },
            "repository_code_may_have_started": {
                "status": "waiting",
                "data": {
                    **safe_data,
                    "repository_code_execution_state": "executed_receipt",
                },
                "waiting_for": "trusted_git_command_failed",
            },
        }

        for label, candidate in cases.items():
            with self.subTest(label=label):
                with (
                    mock_patch.object(
                        self.engine,
                        "_mission_lock",
                        return_value=nullcontext(),
                    ),
                    mock_patch.object(
                        self.engine,
                        "_mission_process_lock",
                        return_value=nullcontext(),
                    ),
                    mock_patch.object(
                        self.engine,
                        "_execute_locked",
                        return_value=candidate,
                    ) as execute_locked,
                    mock_patch.object(autopilot_module.time, "sleep") as sleep,
                ):
                    result = self.engine.execute(mission_id=mission_id)
                self.assertEqual(result, candidate)
                execute_locked.assert_called_once()
                sleep.assert_not_called()

    def test_flag_absent_and_disabled_constructor_have_zero_side_effects(self):
        self.assertFalse(feature_enabled({}))
        target = Path(self.temporary.name) / "disabled"
        ProjectAutopilotV1(
            worktree_root=target,
            signing_key=b"k" * 32,
            enabled=False,
        )
        self.assertFalse(target.exists())

    @unittest.skipUnless(os.name == "nt", "Windows Job Object contract")
    def test_windows_kill_job_ctypes_signatures_preserve_high_handles(self):
        class Function:
            def __init__(self, callback):
                self.callback = callback
                self.argtypes = None
                self.restype = None

            def __call__(self, *args):
                return self.callback(*args)

        job_handle = 0xF123456789ABCDEF
        snapshot_handle = 0xE123456789ABCDE1
        thread_handle = 0xD123456789ABCDE2
        closed = []
        assigned = []
        terminated = []

        class Kernel:
            pass

        kernel = Kernel()
        kernel.CreateJobObjectW = Function(
            lambda *_args: job_handle
        )
        kernel.SetInformationJobObject = Function(
            lambda *_args: True
        )
        kernel.AssignProcessToJobObject = Function(
            lambda job, process: assigned.append(
                (job, process)
            )
            or True
        )
        kernel.CreateToolhelp32Snapshot = Function(
            lambda *_args: snapshot_handle
        )

        def first(_snapshot, entry_pointer):
            entry_pointer._obj.th32OwnerProcessID = 4123
            entry_pointer._obj.th32ThreadID = 99
            return True

        kernel.Thread32First = Function(first)
        kernel.Thread32Next = Function(lambda *_args: False)
        kernel.OpenThread = Function(
            lambda *_args: thread_handle
        )
        kernel.ResumeThread = Function(lambda *_args: 0)
        kernel.TerminateJobObject = Function(
            lambda job, code: terminated.append((job, code)) or True
        )
        kernel.CloseHandle = Function(
            lambda handle: closed.append(handle) or True
        )
        process = SimpleNamespace(
            _handle=0xC123456789ABCDE3,
            pid=4123,
        )
        with mock_patch.object(
            autopilot_module.ctypes,
            "WinDLL",
            return_value=kernel,
        ):
            job = autopilot_module._WindowsKillJob(process)
            job.terminate()
            job.close()
        self.assertEqual(
            assigned, [(job_handle, process._handle)]
        )
        self.assertEqual(
            terminated, [(job_handle, 1)]
        )
        self.assertIn(thread_handle, closed)
        self.assertIn(snapshot_handle, closed)
        self.assertIn(job_handle, closed)
        self.assertEqual(
            kernel.CreateToolhelp32Snapshot.argtypes,
            [
                autopilot_module.wintypes.DWORD,
                autopilot_module.wintypes.DWORD,
            ],
        )
        self.assertIs(
            kernel.CreateToolhelp32Snapshot.restype,
            autopilot_module.wintypes.HANDLE,
        )
        self.assertIs(
            kernel.OpenThread.restype,
            autopilot_module.wintypes.HANDLE,
        )

    @unittest.skipUnless(os.name == "nt", "Windows Job Object contract")
    def test_windows_kill_job_failure_seams_close_every_resource(self):
        import io
        import warnings

        class Function:
            def __init__(self, callback):
                self.callback = callback
                self.argtypes = None
                self.restype = None

            def __call__(self, *args):
                return self.callback(*args)

        class NativeHandle:
            def __init__(self):
                self.closed = 0

            def __int__(self):
                return 0xC123456789ABCDE3

            def Close(self):
                self.closed += 1

        class Process:
            def __init__(self):
                self._handle = NativeHandle()
                self.pid = 4123
                self.stdin = io.BytesIO()
                self.stdout = io.BytesIO()
                self.stderr = io.BytesIO()
                self.returncode = None
                self.terminated = 0
                self.killed = 0

            def terminate(self):
                self.terminated += 1
                self.returncode = -1

            def kill(self):
                self.killed += 1
                self.returncode = -9

            def wait(self, timeout=None):
                del timeout
                return self.returncode

        def build(failure):
            closed = []

            class Kernel:
                pass

            kernel = Kernel()
            kernel.CreateJobObjectW = Function(
                lambda *_args: (
                    0 if failure == "create" else 0xF123456789ABCDEF
                )
            )
            kernel.SetInformationJobObject = Function(
                lambda *_args: False if failure == "set" else True
            )
            kernel.AssignProcessToJobObject = Function(
                lambda *_args: False if failure == "assign" else True
            )
            kernel.CreateToolhelp32Snapshot = Function(
                lambda *_args: (
                    autopilot_module.ctypes.c_void_p(-1).value
                    if failure == "snapshot"
                    else 0xE123456789ABCDE1
                )
            )

            def first(_snapshot, pointer):
                if failure == "thread":
                    return False
                pointer._obj.th32OwnerProcessID = 4123
                pointer._obj.th32ThreadID = 99
                return True

            kernel.Thread32First = Function(first)
            kernel.Thread32Next = Function(lambda *_args: False)
            kernel.OpenThread = Function(
                lambda *_args: (
                    0 if failure == "open" else 0xD123456789ABCDE2
                )
            )
            kernel.ResumeThread = Function(
                lambda *_args: (
                    0xFFFFFFFF if failure == "resume" else 0
                )
            )
            kernel.TerminateJobObject = Function(lambda *_args: True)
            kernel.CloseHandle = Function(
                lambda handle: closed.append(handle) or True
            )
            return kernel, closed

        for failure in (
            "create",
            "set",
            "assign",
            "snapshot",
            "thread",
            "open",
            "resume",
        ):
            with self.subTest(failure=failure):
                process = Process()
                kernel, closed = build(failure)
                with mock_patch.object(
                    autopilot_module.ctypes,
                    "WinDLL",
                    return_value=kernel,
                ):
                    with self.assertRaises(OSError):
                        autopilot_module._WindowsKillJob(process)
                self.assertEqual(process._handle.closed, 1)
                self.assertTrue(process.stdout.closed)
                self.assertTrue(process.stderr.closed)
                self.assertEqual(process.terminated, 1)
                self.assertLessEqual(
                    closed.count(0xF123456789ABCDEF), 1
                )
                self.assertLessEqual(
                    closed.count(0xE123456789ABCDE1), 1
                )
                self.assertLessEqual(
                    closed.count(0xD123456789ABCDE2), 1
                )

        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always", ResourceWarning)
            for _ in range(100):
                process = Process()
                kernel, closed = build("resume")
                with mock_patch.object(
                    autopilot_module.ctypes,
                    "WinDLL",
                    return_value=kernel,
                ):
                    with self.assertRaises(OSError):
                        autopilot_module._WindowsKillJob(process)
                self.assertEqual(process._handle.closed, 1)
                self.assertEqual(len(closed), 3)
        self.assertFalse(
            any(item.category is ResourceWarning for item in observed)
        )

    def test_run_job_boundary_base_exception_identity_and_exact_close(self):
        import io

        class NativeHandle:
            def __init__(self):
                self.closed = 0

            def Close(self):
                self.closed += 1

        class Process:
            def __init__(self):
                self._handle = NativeHandle()
                self.stdout = io.BytesIO()
                self.stderr = io.BytesIO()
                self.stdin = None
                self.returncode = None
                self.terminated = 0

            def terminate(self):
                self.terminated += 1
                self.returncode = -1

            def kill(self):
                self.returncode = -9

            def wait(self, timeout=None):
                del timeout
                return self.returncode

        process = Process()
        engine = ProjectAutopilotV1(
            worktree_root=Path(self.temporary.name) / "boundary-failure",
            signing_key=b"k" * 32,
            enabled=True,
            process_factory=lambda *_args, **_kwargs: process,
            checkpoint_vault_factory=self.vault_factory,
        )
        primary = KeyboardInterrupt("primary")
        with mock_patch.object(
            autopilot_module,
            "_WindowsKillJob",
            side_effect=primary,
        ):
            with self.assertRaises(KeyboardInterrupt) as raised:
                engine._run(
                    "mis_" + "8" * 32,
                    (str(engine.git_executable), "status"),
                    cwd=self.repo,
                    timeout_seconds=10,
                    output_limit=1_024,
                    cancel=lambda: False,
                )
        self.assertIs(raised.exception, primary)
        self.assertEqual(process._handle.closed, 1)
        self.assertEqual(process.terminated, 1)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)

    def test_posix_semantics_imports_are_inert_and_cleanup_refuses(self):
        source = r"""
import os
from pathlib import Path
import core.phase11_windows_clone_cleanup_v1 as cleanup
import core.phase11_windows_namespace_v1 as namespace
import core.phase11_project_autopilot_v1 as project
import core.phase11_live_mission_v1 as live

class PosixOs:
    name = "posix"

    def __getattr__(self, attribute):
        return getattr(os, attribute)

posix_os = PosixOs()
cleanup.os = posix_os
namespace.os = posix_os
project.os = posix_os
live.os = posix_os

root = Path.cwd().anchor
target = Path(root) / "__onyx_phase11_posix_import_sim__"
namespace.WindowsNamespaceV1(worktree_root=target, enabled=False)
cleanup.WindowsCloneCleanupV1(
    worktree_root=Path(root),
    signing_key=b"k" * 32,
    enabled=False,
)
project.ProjectAutopilotV1(
    worktree_root=target,
    signing_key=b"k" * 32,
    enabled=False,
)
live.Phase11LiveMissionV1(
    object(),
    binding_dir=target,
    allowed_roots=(Path(root),),
    enabled=False,
    key=b"k" * 32,
)
assert not target.exists()
try:
    cleanup.WindowsCloneCleanupV1(
        worktree_root=Path(root),
        signing_key=b"k" * 32,
        enabled=True,
    )
except cleanup.CloneCleanupContractError:
    pass
else:
    raise AssertionError("enabled cleanup accepted POSIX")
print("PHASE11_POSIX_IMPORT_OK")
"""
        completed = subprocess.run(
            [sys.executable, "-c", source],
            cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )
        self.assertIn("PHASE11_POSIX_IMPORT_OK", completed.stdout)

    def test_handle_safe_cleanup_flag_is_exact_and_windows_only(self):
        target = Path(self.temporary.name) / "cleanup-not-exact"
        with mock_patch.dict(
            os.environ,
            {"ONYX_PHASE11_HANDLE_SAFE_CLONE_CLEANUP_V1": "True"},
        ):
            engine = ProjectAutopilotV1(
                worktree_root=target,
                signing_key=b"k" * 32,
                enabled=True,
                checkpoint_vault_factory=self.vault_factory,
            )
        self.assertIsNone(engine._clone_cleanup)

    def test_applies_patch_in_clone_without_executing_repository_code(self):
        mission_id = "mis_" + "1" * 32
        owner_git_before = self.engine.capture_owner_git_state(self.repo)
        outcome = self.engine.execute(
            mission_id=mission_id,
            binding_digest="b" * 64,
            envelope=self._envelope(),
            patch=PATCH,
            cancel=lambda: False,
        )
        self.assertEqual(outcome["status"], "succeeded", outcome)
        self.assertEqual((self.repo / "demo.txt").read_text(encoding="utf-8"), "before\n")
        self.assertEqual(_git(self.repo, "rev-parse", "HEAD").lower(), self.head)
        self.assertEqual(_git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(
            self.engine.capture_owner_git_state(self.repo), owner_git_before
        )
        clone = self.control / mission_id / "clone"
        self.assertEqual((clone / "demo.txt").read_text(encoding="utf-8"), "after\n")
        self.assertFalse((clone / "CONFTST_EXECUTED").exists())
        self.assertFalse((clone / "TEST_EXECUTED").exists())
        self.assertFalse((self.repo / "CONFTST_EXECUTED").exists())
        self.assertFalse((self.repo / "TEST_EXECUTED").exists())
        self.assertFalse(outcome["data"]["repository_code_executed"])
        checkpoint = json.loads(
            (self.control / mission_id / "checkpoint.json").read_text(encoding="utf-8")
        )
        self.assertEqual(checkpoint["stage"], "verified")
        self.assertEqual(checkpoint["gate_index"], 1)
        self.assertTrue(checkpoint["signature"])

    def test_invalid_python_waits_and_retains_resumable_clone(self):
        mission_id = "mis_" + "2" * 32
        envelope = self._envelope(
            [
                {
                    "argv": ["onyx-static", "python-ast", "module.py"],
                    "timeout_seconds": 30,
                }
            ],
            patch_text=PY_PATCH,
        )
        outcome = self.engine.execute(
            mission_id=mission_id,
            binding_digest="c" * 64,
            envelope=envelope,
            patch=PY_PATCH,
            cancel=lambda: False,
        )
        self.assertEqual(outcome["status"], "waiting")
        self.assertEqual(outcome["waiting_for"], "static_python_ast_failed")
        self.assertTrue((self.control / mission_id / "clone").is_dir())
        checkpoint = self.engine._read_checkpoint(mission_id)
        self.assertEqual(checkpoint["gate_index"], 0)
        self.assertEqual(checkpoint["waiting_reason"], "static_python_ast_failed")

    def test_trusted_git_timeout_and_output_exhaustion_stop_process(self):
        with self.assertRaisesRegex(ProjectAutopilotWaiting, "output_budget"):
            self.engine._run(
                "mis_" + "4" * 32,
                (str(self.engine.git_executable), "help", "-a"),
                cwd=self.repo,
                timeout_seconds=10,
                output_limit=1,
                cancel=lambda: False,
            )

        class EmptyStream:
            def read(self, _size):
                return b""

        class InputSink:
            def write(self, value):
                return len(value)

            def flush(self):
                return None

            def close(self):
                return None

        class HangingProcess:
            def __init__(self, *_args, **_kwargs):
                self.stdout = EmptyStream()
                self.stderr = EmptyStream()
                self.stdin = InputSink()
                self.returncode = None
                self.terminated = False

            def poll(self):
                return self.returncode

            def terminate(self):
                self.terminated = True
                self.returncode = -1

            def kill(self):
                self.terminated = True
                self.returncode = -9

            def wait(self, timeout=None):
                del timeout
                return self.returncode

        class FakeJob:
            def __init__(self, _process):
                self.terminated = False

            def terminate(self):
                self.terminated = True
                hanging.terminate()

            def close(self):
                return None

        hanging = HangingProcess()
        engine = ProjectAutopilotV1(
            worktree_root=Path(self.temporary.name) / "timeout-control",
            signing_key=b"t" * 32,
            enabled=True,
            process_factory=lambda *_args, **_kwargs: hanging,
            checkpoint_vault_factory=self.vault_factory,
        )
        with mock_patch(
            "core.phase11_project_autopilot_v1._WindowsKillJob", FakeJob
        ):
            with self.assertRaisesRegex(ProjectAutopilotWaiting, "timeout"):
                engine._run(
                    "mis_" + "5" * 32,
                    (str(engine.git_executable), "status"),
                    cwd=self.repo,
                    timeout_seconds=0.05,
                    output_limit=1_024,
                    cancel=lambda: False,
                )
        self.assertTrue(hanging.terminated)
        self.assertNotIn("mis_" + "5" * 32, engine._active)

        hanging.returncode = None
        hanging.terminated = False
        cancel_checks = 0

        def crash_cancel():
            nonlocal cancel_checks
            cancel_checks += 1
            return cancel_checks > 1

        with mock_patch(
            "core.phase11_project_autopilot_v1._WindowsKillJob", FakeJob
        ):
            with self.assertRaisesRegex(ProjectAutopilotWaiting, "kill_requested"):
                engine._run(
                    "mis_" + "5" * 32,
                    (str(engine.git_executable), "apply", "-"),
                    cwd=self.repo,
                    timeout_seconds=10,
                    output_limit=1_024,
                    cancel=crash_cancel,
                    input_bytes=b"ONYX_STDIN_CRASH_CANARY",
                )
        for path in engine.worktree_root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                self.assertNotIn(
                    b"ONYX_STDIN_CRASH_CANARY", path.read_bytes()
                )
        self.assertFalse(
            any(engine.worktree_root.rglob("patch.diff"))
        )
        hanging.returncode = None
        hanging.terminated = False
        disk_root = Path(self.temporary.name) / "monitored-output"
        disk_root.mkdir()
        (disk_root / "oversized.bin").write_bytes(b"xx")
        with mock_patch(
            "core.phase11_project_autopilot_v1._WindowsKillJob", FakeJob
        ):
            with self.assertRaisesRegex(
                ProjectAutopilotWaiting, "controlled_disk_budget"
            ):
                engine._run(
                    "mis_" + "5" * 32,
                    (str(engine.git_executable), "status"),
                    cwd=self.repo,
                    timeout_seconds=10,
                    output_limit=1_024,
                    cancel=lambda: False,
                    disk_root=disk_root,
                    disk_limit=1,
                )
        self.assertTrue(hanging.terminated)

    def test_active_registry_rejects_nested_run_and_preserves_kill_target(
        self,
    ):
        mission_id = "mis_" + "0" * 32

        class ActiveProcess:
            def __init__(self):
                self.terminated = False

            def terminate(self):
                self.terminated = True

            def wait(self, timeout=None):
                del timeout
                return 0

            def kill(self):
                self.terminated = True

        active = ActiveProcess()
        with self.engine._process_lock:
            self.engine._active[mission_id] = active
        original_factory = self.engine._process_factory
        self.engine._process_factory = lambda *_args, **_kwargs: (
            self.fail("nested process factory must not be called")
        )
        try:
            with self.assertRaisesRegex(
                ProjectAutopilotWaiting,
                "trusted_git_mission_active",
            ):
                self.engine._run(
                    mission_id,
                    (str(self.engine.git_executable), "status"),
                    cwd=self.repo,
                    timeout_seconds=10,
                    output_limit=1_024,
                    cancel=lambda: False,
                )
            self.assertIs(self.engine._active[mission_id], active)
            self.engine.kill(mission_id)
            self.assertTrue(active.terminated)
            self.assertIs(self.engine._active[mission_id], active)
        finally:
            self.engine._process_factory = original_factory
            with self.engine._process_lock:
                self.engine._active.pop(mission_id, None)

    def test_mission_lock_registry_is_refcounted_bounded_and_released(self):
        first = "mis_" + "a" * 32
        second = "mis_" + "b" * 32
        with mock_patch.object(
            autopilot_module, "MAX_MISSION_LOCK_ENTRIES", 1
        ):
            with self.engine._mission_lock(first):
                entry = self.engine._mission_locks[first]
                self.assertEqual(entry.references, 1)
                with self.engine._mission_lock(first):
                    self.assertIs(
                        self.engine._mission_locks[first], entry
                    )
                    self.assertEqual(entry.references, 2)
                with self.assertRaisesRegex(
                    ProjectAutopilotWaiting, "capacity"
                ):
                    with self.engine._mission_lock(second):
                        self.fail("split mission lock admitted")
            self.assertEqual(self.engine._mission_locks, {})

    def test_checkpoint_high_water_capacity_fails_closed_without_eviction(
        self,
    ):
        existing = "mis_" + "c" * 32
        candidate = "mis_" + "d" * 32
        with autopilot_module._PROCESS_HIGH_WATER_LOCK:
            saved = dict(autopilot_module._PROCESS_HIGH_WATER)
            autopilot_module._PROCESS_HIGH_WATER.clear()
            autopilot_module._PROCESS_HIGH_WATER[existing] = (1, "e" * 64)
        try:
            with mock_patch.object(
                autopilot_module,
                "MAX_PROCESS_HIGH_WATER_ENTRIES",
                1,
            ):
                with self.assertRaisesRegex(
                    ProjectAutopilotWaiting, "capacity"
                ):
                    self.engine._write_checkpoint(
                        candidate,
                        {"mission_id": candidate},
                    )
            self.assertEqual(
                autopilot_module._PROCESS_HIGH_WATER,
                {existing: (1, "e" * 64)},
            )
            self.assertFalse(
                self.engine._mission_dir(candidate).exists()
            )
        finally:
            with autopilot_module._PROCESS_HIGH_WATER_LOCK:
                autopilot_module._PROCESS_HIGH_WATER.clear()
                autopilot_module._PROCESS_HIGH_WATER.update(saved)

    def test_cancel_before_side_effect_leaves_bound_checkpoint_only(self):
        mission_id = "mis_" + "6" * 32
        outcome = self.engine.execute(
            mission_id=mission_id,
            binding_digest="1" * 64,
            envelope=self._envelope(),
            patch=PATCH,
            cancel=lambda: True,
        )
        self.assertEqual(outcome["status"], "waiting")
        self.assertEqual(outcome["waiting_for"], "kill_requested")
        self.assertFalse((self.control / mission_id / "clone").exists())
        self.assertTrue((self.control / mission_id / "checkpoint.json").is_file())

    def test_owner_drift_stops_before_controlled_worktree_creation(self):
        mission_id = "mis_" + "7" * 32
        envelope = self._envelope()
        (self.repo / "demo.txt").write_bytes(b"owner drift\n")
        outcome = self.engine.execute(
            mission_id=mission_id,
            binding_digest="2" * 64,
            envelope=envelope,
            patch=PATCH,
            cancel=lambda: False,
        )
        self.assertEqual(outcome["status"], "waiting")
        self.assertEqual(outcome["waiting_for"], "owner_worktree_not_clean")
        self.assertFalse((self.control / mission_id / "clone").exists())

    def test_cleanup_scrubs_plaintext_but_retains_clone_fail_closed(self):
        mission_id = "mis_" + "3" * 32
        outcome = self.engine.execute(
            mission_id=mission_id,
            binding_digest="d" * 64,
            envelope=self._envelope(),
            patch=PATCH,
            cancel=lambda: False,
        )
        self.assertEqual(outcome["status"], "succeeded")
        with self.assertRaisesRegex(
            ProjectAutopilotWaiting,
            "controlled_clone_cleanup_requires_handle_safe_deleter",
        ):
            self.engine.cleanup(
                mission_id=mission_id,
                binding_digest="d" * 64,
                owner_root=str(self.repo),
            )
        self.assertTrue((self.control / mission_id / "clone").is_dir())
        self.assertFalse((self.control / mission_id / "patch.diff").exists())
        self.assertFalse((self.control / mission_id / "source.bundle").exists())
        checkpoint = self.engine._read_checkpoint(mission_id)
        self.assertEqual(checkpoint["stage"], "cleanup_refused")
        self.assertEqual(
            checkpoint["waiting_reason"],
            "controlled_clone_cleanup_requires_handle_safe_deleter",
        )
        self.assertTrue(self.repo.is_dir())
        self.assertEqual(
            (self.repo / "demo.txt").read_text(encoding="utf-8"),
            "before\n",
        )

    def test_executor_refuses_every_cleanup_only_checkpoint_without_mutation(
        self,
    ):
        mission_id = "mis_" + "9" * 32
        envelope = self._envelope()
        result = self.engine.execute(
            mission_id=mission_id,
            binding_digest="9" * 64,
            envelope=envelope,
            patch=PATCH,
            cancel=lambda: False,
        )
        self.assertEqual(result["status"], "succeeded")
        checkpoint_path = self.engine._checkpoint_path(mission_id)
        clone = self.engine._clone_path(mission_id)

        for stage in (
            "cleanup_planned",
            "deleting",
            "finalizing",
            "root_removed",
            "cleaned",
        ):
            current = self.engine._read_checkpoint(mission_id)
            payload = {
                key: value
                for key, value in current.items()
                if key
                not in {
                    "sequence",
                    "checkpoint_digest",
                    "signature",
                }
            }
            payload["stage"] = stage
            self.engine._write_checkpoint(mission_id, payload)
            checkpoint_before = checkpoint_path.read_bytes()
            clone_before = {
                path.relative_to(clone).as_posix(): path.read_bytes()
                for path in clone.rglob("*")
                if path.is_file()
            }
            with self.subTest(stage=stage), self.assertRaisesRegex(
                ProjectAutopilotContractError,
                "cleanup_checkpoint_execution_refused",
            ):
                self.engine.execute(
                    mission_id=mission_id,
                    binding_digest="9" * 64,
                    envelope=envelope,
                    patch=PATCH,
                    cancel=lambda: False,
                )
            self.assertEqual(
                checkpoint_path.read_bytes(), checkpoint_before
            )
            self.assertTrue(clone.is_dir())
            self.assertEqual(
                {
                    path.relative_to(clone).as_posix(): path.read_bytes()
                    for path in clone.rglob("*")
                    if path.is_file()
                },
                clone_before,
            )

    def test_handle_safe_cleanup_real_clone_and_cleaned_replay(self):
        terminal_state = ["succeeded"]
        engine = self._cleanup_enabled_engine(terminal_state)
        mission_id = "mis_" + "e" * 32
        envelope = AutopilotEnvelopeV1.build(
            root=str(self.repo.resolve()),
            base_head=self.head,
            owner_git_sha256=engine.capture_owner_git_state(self.repo),
            patch=PATCH,
            gates=[
                {
                    "argv": ["onyx-static", "diff-check"],
                    "timeout_seconds": 30,
                }
            ],
            max_seconds=120,
        )
        outcome = engine.execute(
            mission_id=mission_id,
            binding_digest="e" * 64,
            envelope=envelope,
            patch=PATCH,
            cancel=lambda: False,
        )
        self.assertEqual(outcome["status"], "succeeded")
        clone = engine._clone_path(mission_id)
        self.assertTrue((clone / ".git").is_dir())
        self.assertEqual(_git(clone, "rev-parse", "HEAD").lower(), self.head)
        cleaned = False
        borrowed_during_cleanup = []
        original_cleanup = engine._clone_cleanup.cleanup

        def observe_cleanup_session(**kwargs):
            borrowed = kwargs["containment_handles"]
            active = engine._namespace_sessions[mission_id]
            self.assertEqual(
                borrowed, active.borrowed_containment_handles
            )
            self.assertTrue(all(not item.closed for item in borrowed))
            borrowed_during_cleanup.append(borrowed)
            return original_cleanup(**kwargs)

        with mock_patch.object(
            engine._clone_cleanup,
            "cleanup",
            side_effect=observe_cleanup_session,
        ):
            for _attempt in range(20):
                try:
                    cleaned = engine.cleanup(
                        mission_id=mission_id,
                        binding_digest="e" * 64,
                        envelope=envelope,
                    )
                    break
                except ProjectAutopilotWaiting as exc:
                    if exc.reason != "cleanup_entry_handle_busy":
                        raise
                    time.sleep(0.05)
        self.assertTrue(cleaned)
        self.assertTrue(borrowed_during_cleanup)
        self.assertNotIn(mission_id, engine._namespace_sessions)
        self.assertTrue(
            all(
                item.closed
                for borrowed in borrowed_during_cleanup
                for item in borrowed
            )
        )
        self.assertFalse(clone.exists())
        self.assertFalse(
            engine.cleanup(
                mission_id=mission_id,
                binding_digest="e" * 64,
                envelope=envelope,
            )
        )
        checkpoint = engine._read_checkpoint(mission_id)
        self.assertEqual(checkpoint["stage"], "cleaned")
        self.assertIn("cleanup_manifest_digest", checkpoint)

    def test_stage_c_enabled_path_adds_by_handle_and_never_calls_git_apply(
        self,
    ):
        engine = self._cleanup_enabled_engine(["succeeded"])
        mission_id = "mis_" + "4a" * 16
        envelope = AutopilotEnvelopeV1.build(
            root=str(self.repo.resolve()),
            base_head=self.head,
            owner_git_sha256=engine.capture_owner_git_state(
                self.repo
            ),
            patch=ADD_PATCH,
            gates=[
                {
                    "argv": ["onyx-static", "diff-check"],
                    "timeout_seconds": 30,
                }
            ],
            max_seconds=120,
        )
        calls: list[tuple[str, ...]] = []
        original_git = engine._git

        def observe_git(*args, **kwargs):
            calls.append(tuple(args[2]))
            return original_git(*args, **kwargs)

        with mock_patch.object(
            engine, "_git", side_effect=observe_git
        ):
            outcome = engine.execute(
                mission_id=mission_id,
                binding_digest="4a" * 32,
                envelope=envelope,
                patch=ADD_PATCH,
                cancel=lambda: False,
            )
        self.assertEqual(outcome["status"], "succeeded")
        self.assertEqual(
            (engine._clone_path(mission_id) / "new.txt").read_bytes(),
            b"hello\nworld\n",
        )
        self.assertFalse(any(call[0] == "apply" for call in calls))
        self.assertFalse((self.repo / "TEST_EXECUTED").exists())
        self.assertFalse((self.repo / "CONFTST_EXECUTED").exists())
        self.assertFalse(
            (engine._clone_path(mission_id) / "TEST_EXECUTED").exists()
        )
        self.assertFalse(
            (
                engine._clone_path(mission_id) / "CONFTST_EXECUTED"
            ).exists()
        )

    def test_stage_c_project_crash_journal_replays_inside_same_guard(
        self,
    ):
        engine = self._cleanup_enabled_engine(["succeeded"])
        mission_id = "mis_" + "4b" * 16
        envelope = AutopilotEnvelopeV1.build(
            root=str(self.repo.resolve()),
            base_head=self.head,
            owner_git_sha256=engine.capture_owner_git_state(
                self.repo
            ),
            patch=PATCH,
            gates=[
                {
                    "argv": ["onyx-static", "diff-check"],
                    "timeout_seconds": 30,
                }
            ],
            max_seconds=120,
        )
        original_apply = HandlePatchEngineV1.apply
        crashed = False

        def crash_apply(instance, patch, **kwargs):
            def fault(point):
                nonlocal crashed
                if not crashed and point == "after_truncate":
                    crashed = True
                    raise RuntimeError("project patch crash")

            kwargs["fault_hook"] = fault
            return original_apply(instance, patch, **kwargs)

        with mock_patch.object(
            HandlePatchEngineV1,
            "apply",
            autospec=True,
            side_effect=crash_apply,
        ):
            with self.assertRaisesRegex(
                RuntimeError, "project patch crash"
            ):
                engine.execute(
                    mission_id=mission_id,
                    binding_digest="4b" * 32,
                    envelope=envelope,
                    patch=PATCH,
                    cancel=lambda: False,
                )
        self.assertEqual(
            engine._read_checkpoint(mission_id)["stage"],
            "clone_ready",
        )
        outcome = engine.execute(
            mission_id=mission_id,
            binding_digest="4b" * 32,
            envelope=envelope,
            patch=PATCH,
            cancel=lambda: False,
        )
        self.assertEqual(outcome["status"], "succeeded", outcome)
        self.assertEqual(
            (engine._clone_path(mission_id) / "demo.txt").read_bytes(),
            b"after\n",
        )

    def test_stage_c_population_pins_clone_root_and_git_config(
        self,
    ):
        engine = self._cleanup_enabled_engine(["succeeded"])
        mission_id = "mis_" + "4c" * 16
        envelope = AutopilotEnvelopeV1.build(
            root=str(self.repo.resolve()),
            base_head=self.head,
            owner_git_sha256=engine.capture_owner_git_state(
                self.repo
            ),
            patch=PATCH,
            gates=[
                {
                    "argv": ["onyx-static", "diff-check"],
                    "timeout_seconds": 30,
                }
            ],
            max_seconds=120,
        )
        original_populate = engine._populate_prepared_clone
        original_git = engine._git
        root_denied = config_denied = hooks_denied = False
        verifier_root_denied = False
        original_verify = IndependentAutopilotVerifierV1._verify_locked

        def guarded_populate(*args, **kwargs):
            nonlocal root_denied
            with self.assertRaises(PermissionError):
                engine._clone_path(mission_id).rename(
                    engine._clone_path(mission_id).with_name(
                        "clone-moved"
                    )
                )
            root_denied = True
            return original_populate(*args, **kwargs)

        def guarded_git(*args, **kwargs):
            nonlocal config_denied, hooks_denied
            arguments = tuple(args[2])
            if arguments and arguments[0] == "fetch":
                config = (
                    engine._clone_path(mission_id)
                    / ".git"
                    / "config"
                )
                with self.assertRaises(PermissionError):
                    config.rename(config.with_name("config-moved"))
                config_denied = True
                hooks = (
                    engine._clone_path(mission_id)
                    / ".git"
                    / "hooks"
                )
                with self.assertRaises(PermissionError):
                    hooks.rename(hooks.with_name("hooks-moved"))
                hooks_denied = True
            return original_git(*args, **kwargs)

        def guarded_verify(instance, *args, **kwargs):
            nonlocal verifier_root_denied
            clone = engine._clone_path(mission_id)
            with self.assertRaises(PermissionError):
                clone.rename(clone.with_name("clone-verify-moved"))
            verifier_root_denied = True
            return original_verify(instance, *args, **kwargs)

        with (
            mock_patch.object(
                engine,
                "_populate_prepared_clone",
                side_effect=guarded_populate,
            ),
            mock_patch.object(
                engine, "_git", side_effect=guarded_git
            ),
            mock_patch.object(
                IndependentAutopilotVerifierV1,
                "_verify_locked",
                autospec=True,
                side_effect=guarded_verify,
            ),
        ):
            outcome = engine.execute(
                mission_id=mission_id,
                binding_digest="4c" * 32,
                envelope=envelope,
                patch=PATCH,
                cancel=lambda: False,
            )
        self.assertEqual(outcome["status"], "succeeded", outcome)
        self.assertTrue(root_denied)
        self.assertTrue(config_denied)
        self.assertTrue(hooks_denied)
        self.assertTrue(verifier_root_denied)

    def test_stage_c_bundle_preseed_links_fail_without_sentinel_mutation(
        self,
    ):
        for suffix, kind in (("4d", "hardlink"), ("4e", "symlink")):
            with self.subTest(kind=kind):
                engine = self._cleanup_enabled_engine(["failed"])
                mission_id = "mis_" + suffix * 16
                envelope = AutopilotEnvelopeV1.build(
                    root=str(self.repo.resolve()),
                    base_head=self.head,
                    owner_git_sha256=(
                        engine.capture_owner_git_state(self.repo)
                    ),
                    patch=PATCH,
                    gates=[
                        {
                            "argv": [
                                "onyx-static",
                                "diff-check",
                            ],
                            "timeout_seconds": 30,
                        }
                    ],
                    max_seconds=120,
                )
                original = engine._populate_prepared_clone
                sentinel = (
                    Path(self.temporary.name)
                    / f"bundle-sentinel-{kind}"
                )
                sentinel.write_bytes(b"sentinel")
                poisoned = False

                def poison(*args, **kwargs):
                    nonlocal poisoned
                    if not poisoned:
                        poisoned = True
                        target = engine._bundle_path(mission_id)
                        if kind == "hardlink":
                            os.link(sentinel, target)
                        else:
                            os.symlink(sentinel, target)
                    return original(*args, **kwargs)

                try:
                    with mock_patch.object(
                        engine,
                        "_populate_prepared_clone",
                        side_effect=poison,
                    ):
                        with self.assertRaises(
                            ProjectAutopilotContractError
                        ):
                            engine.execute(
                                mission_id=mission_id,
                                binding_digest=suffix * 32,
                                envelope=envelope,
                                patch=PATCH,
                                cancel=lambda: False,
                            )
                except OSError:
                    if kind == "symlink":
                        continue
                    raise
                self.assertEqual(
                    sentinel.read_bytes(), b"sentinel"
                )
                target = engine._bundle_path(mission_id)
                if target.exists() or target.is_symlink():
                    target.unlink()
                self.assertTrue(
                    engine.cleanup(
                        mission_id=mission_id,
                        binding_digest=suffix * 32,
                        envelope=envelope,
                    )
                )
                self.assertFalse(
                    engine._clone_path(mission_id).exists()
                )

    def test_stage_c_malicious_filter_config_is_refused_before_git(
        self,
    ):
        marker = Path(self.temporary.name) / "FILTER_EXECUTED"
        _git(
            self.repo,
            "config",
            "filter.evil.clean",
            f'cmd /c "echo bad>{marker}"',
        )
        _git(
            self.repo,
            "config",
            "filter.evil.required",
            "true",
        )
        engine = self._cleanup_enabled_engine(["failed"])
        envelope = AutopilotEnvelopeV1.build(
            root=str(self.repo.resolve()),
            base_head=self.head,
            owner_git_sha256=engine.capture_owner_git_state(
                self.repo
            ),
            patch=PATCH,
            gates=[
                {
                    "argv": ["onyx-static", "diff-check"],
                    "timeout_seconds": 30,
                }
            ],
            max_seconds=120,
        )
        with self.assertRaisesRegex(
            ProjectAutopilotContractError,
            "owner_git_executable_config_refused",
        ):
            engine.execute(
                mission_id="mis_" + "4f" * 16,
                binding_digest="4f" * 32,
                envelope=envelope,
                patch=PATCH,
                cancel=lambda: False,
            )
        self.assertFalse(marker.exists())

    def test_old_style_filter_canary_is_refused_before_any_owner_git(
        self,
    ):
        marker = Path(self.temporary.name) / "OLD_FILTER_EXECUTED"
        config = self.repo / ".git" / "config"
        with config.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                "\n[filter.evil]\n"
                f'    clean = cmd /c "echo bad>{marker}"\n'
                "    required = true\n"
            )
        engine = self._cleanup_enabled_engine(["failed"])
        envelope = AutopilotEnvelopeV1.build(
            root=str(self.repo.resolve()),
            base_head=self.head,
            owner_git_sha256=engine.capture_owner_git_state(
                self.repo
            ),
            patch=PATCH,
            gates=[
                {
                    "argv": ["onyx-static", "diff-check"],
                    "timeout_seconds": 30,
                }
            ],
            max_seconds=120,
        )
        with mock_patch.object(
            engine, "_git", wraps=engine._git
        ) as owner_git:
            with self.assertRaisesRegex(
                ProjectAutopilotContractError,
                "owner_git_executable_config_refused",
            ):
                engine.execute(
                    mission_id="mis_" + "5f" * 16,
                    binding_digest="5f" * 32,
                    envelope=envelope,
                    patch=PATCH,
                    cancel=lambda: False,
                )
        self.assertEqual(owner_git.call_count, 0)
        self.assertFalse(marker.exists())
        self.assertFalse(
            engine._checkpoint_path("mis_" + "5f" * 16).exists()
        )
        self.assertFalse(
            engine._clone_path("mis_" + "5f" * 16).exists()
        )

    def test_executable_git_config_section_syntaxes_fail_closed(self):
        config = self.repo / ".git" / "config"
        original = config.read_bytes()
        sections = (
            '[filter "evil"]',
            "[filter.evil]",
            '[diff "evil"]',
            "[diff.evil]",
            '[merge "evil"]',
            "[merge.evil]",
            "[include]",
            '[includeIf "gitdir:C:/owner/"]',
        )
        for index, section in enumerate(sections):
            with self.subTest(section=section):
                config.write_bytes(
                    original
                    + (
                        f"\n{section} # canary-{index}\n"
                        "    command = cmd /c echo bad\n"
                    ).encode("utf-8")
                )
                with self.assertRaisesRegex(
                    ProjectAutopilotContractError,
                    "owner_git_executable_config_refused",
                ):
                    self.engine._assert_owner_git_config_nonexecuting(
                        self.repo
                    )
        config.write_bytes(original)
        worktree_config = self.repo / ".git" / "config.worktree"
        worktree_config.write_text(
            "[filter.evil]\n"
            "    clean = cmd /c echo bad\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            ProjectAutopilotContractError,
            "owner_git_executable_config_refused",
        ):
            self.engine._assert_owner_git_config_nonexecuting(
                self.repo
            )

    def test_namespace_session_preserves_primary_and_closes_owned_handles(
        self,
    ):
        engine = self._cleanup_enabled_engine(["succeeded"])
        mission_id = "mis_" + "9" * 32
        engine._mission_dir(mission_id).mkdir(parents=True)
        primary = KeyboardInterrupt("primary")
        borrowed = None
        with self.assertRaises(KeyboardInterrupt) as observed:
            with engine._mission_process_lock(mission_id):
                borrowed = engine._borrowed_containment_handles(
                    mission_id
                )
                self.assertTrue(
                    all(not item.closed for item in borrowed)
                )
                raise primary
        self.assertIs(observed.exception, primary)
        self.assertNotIn(mission_id, engine._namespace_sessions)
        self.assertIsNotNone(borrowed)
        self.assertTrue(all(item.closed for item in borrowed))

    def test_handle_safe_cleanup_refuses_hardlinked_plaintext_artifact(
        self,
    ):
        engine = self._cleanup_enabled_engine(["succeeded"])
        mission_id = "mis_" + "8" * 32
        envelope = AutopilotEnvelopeV1.build(
            root=str(self.repo.resolve()),
            base_head=self.head,
            owner_git_sha256=engine.capture_owner_git_state(
                self.repo
            ),
            patch=PATCH,
            gates=[
                {
                    "argv": ["onyx-static", "diff-check"],
                    "timeout_seconds": 30,
                }
            ],
            max_seconds=120,
        )
        outcome = engine.execute(
            mission_id=mission_id,
            binding_digest="8" * 64,
            envelope=envelope,
            patch=PATCH,
            cancel=lambda: False,
        )
        self.assertEqual(outcome["status"], "succeeded")
        sentinel = Path(self.temporary.name) / "outside-secret"
        sentinel.write_bytes(b"do-not-touch")
        os.link(sentinel, engine._patch_path(mission_id))
        with self.assertRaisesRegex(
            ProjectAutopilotContractError,
            "cleanup_hardlink_refused",
        ):
            engine.cleanup(
                mission_id=mission_id,
                binding_digest="8" * 64,
                envelope=envelope,
            )
        self.assertEqual(sentinel.read_bytes(), b"do-not-touch")
        self.assertTrue(engine._clone_path(mission_id).is_dir())

    def test_handle_safe_cleanup_uses_terminal_resolver_and_active_gate(self):
        terminal_state = ["running"]
        engine = self._cleanup_enabled_engine(terminal_state)
        mission_id = "mis_" + "f" * 32
        envelope = AutopilotEnvelopeV1.build(
            root=str(self.repo.resolve()),
            base_head=self.head,
            owner_git_sha256=engine.capture_owner_git_state(self.repo),
            patch=PATCH,
            gates=[
                {
                    "argv": ["onyx-static", "diff-check"],
                    "timeout_seconds": 30,
                }
            ],
            max_seconds=120,
        )
        outcome = engine.execute(
            mission_id=mission_id,
            binding_digest="f" * 64,
            envelope=envelope,
            patch=PATCH,
            cancel=lambda: False,
        )
        self.assertEqual(outcome["status"], "succeeded")
        with self.assertRaisesRegex(
            ProjectAutopilotWaiting,
            "cleanup_terminal_gate_incomplete",
        ):
            engine.cleanup(
                mission_id=mission_id,
                binding_digest="f" * 64,
                envelope=envelope,
            )
        terminal_state[0] = "succeeded"
        with engine._process_lock:
            engine._active[mission_id] = object()
        try:
            with self.assertRaisesRegex(
                ProjectAutopilotWaiting, "cleanup_mission_active"
            ):
                engine.cleanup(
                    mission_id=mission_id,
                    binding_digest="f" * 64,
                    envelope=envelope,
                )
        finally:
            with engine._process_lock:
                engine._active.pop(mission_id, None)

    def test_terminal_patch_and_gate_stages_cleanup_clone_and_artifacts(
        self,
    ):
        for stage, suffix in (
            ("patch_applied", "6a"),
            ("gates_running", "6b"),
            ("executable_gate_pending", "6c"),
            ("executable_gates_running", "6d"),
            ("executable_gate_terminal", "6e"),
        ):
            with self.subTest(stage=stage):
                engine = self._cleanup_enabled_engine(["failed"])
                mission_id = "mis_" + suffix * 16
                envelope = AutopilotEnvelopeV1.build(
                    root=str(self.repo.resolve()),
                    base_head=self.head,
                    owner_git_sha256=engine.capture_owner_git_state(
                        self.repo
                    ),
                    patch=PATCH,
                    gates=[
                        {
                            "argv": ["onyx-static", "diff-check"],
                            "timeout_seconds": 30,
                        }
                    ],
                    max_seconds=120,
                )
                owner_before = engine.capture_owner_git_state(
                    self.repo
                )
                outcome = engine.execute(
                    mission_id=mission_id,
                    binding_digest=suffix * 32,
                    envelope=envelope,
                    patch=PATCH,
                    cancel=lambda: False,
                )
                self.assertEqual(outcome["status"], "succeeded")
                checkpoint = engine._read_checkpoint(mission_id)
                payload = {
                    key: value
                    for key, value in checkpoint.items()
                    if key
                    not in {
                        "checkpoint_digest",
                        "signature",
                        "sequence",
                    }
                }
                payload["stage"] = stage
                engine._write_checkpoint(mission_id, payload)
                engine._patch_path(mission_id).write_bytes(
                    PATCH.encode("utf-8")
                )
                engine._bundle_path(mission_id).write_bytes(
                    b"terminal recovery bundle"
                )
                self.assertTrue(
                    engine.cleanup(
                        mission_id=mission_id,
                        binding_digest=suffix * 32,
                        envelope=envelope,
                    )
                )
                self.assertFalse(
                    engine._clone_path(mission_id).exists()
                )
                self.assertFalse(
                    engine._patch_path(mission_id).exists()
                )
                self.assertFalse(
                    engine._bundle_path(mission_id).exists()
                )
                self.assertEqual(
                    engine._read_checkpoint(mission_id)["stage"],
                    "cleaned",
                )
                self.assertEqual(
                    engine.capture_owner_git_state(self.repo),
                    owner_before,
                )

    def test_stage_b_cross_store_fault_seams_reconcile_and_cleanup(
        self,
    ):
        seams = (
            ("clone_preparing", None, "1a"),
            ("before_prepare", None, "1b"),
            ("after_clone_intent", "intent", "1c"),
            ("after_provenance_slot_write", "intent", "1d"),
            ("clone_building", "prepared", "1e"),
            ("clone_ready", "finalized", "1f"),
        )
        for seam, expected_provenance, suffix in seams:
            terminal_state = ["succeeded"]
            engine = self._cleanup_enabled_engine(terminal_state)
            mission_id = "mis_" + suffix * 16
            envelope = AutopilotEnvelopeV1.build(
                root=str(self.repo.resolve()),
                base_head=self.head,
                owner_git_sha256=engine.capture_owner_git_state(
                    self.repo
                ),
                patch=PATCH,
                gates=[
                    {
                        "argv": ["onyx-static", "diff-check"],
                        "timeout_seconds": 30,
                    }
                ],
                max_seconds=120,
            )
            owner_before = engine.capture_owner_git_state(self.repo)
            if seam in {
                "clone_preparing",
                "clone_building",
                "clone_ready",
            }:
                original_write = engine._write_checkpoint
                failed = False

                def fail_checkpoint(target_id, payload):
                    nonlocal failed
                    if not failed and payload.get("stage") == seam:
                        failed = True
                        raise RuntimeError("stage-b seam")
                    return original_write(target_id, payload)

                context = mock_patch.object(
                    engine,
                    "_write_checkpoint",
                    side_effect=fail_checkpoint,
                )
            else:
                original_prepare = (
                    engine._clone_cleanup.prepare_provenance
                )

                def fail_prepare(**kwargs):
                    if seam == "before_prepare":
                        raise RuntimeError("stage-b seam")

                    def fault(point):
                        if point == seam:
                            raise RuntimeError("stage-b seam")

                    kwargs["fault_hook"] = fault
                    return original_prepare(**kwargs)

                context = mock_patch.object(
                    engine._clone_cleanup,
                    "prepare_provenance",
                    side_effect=fail_prepare,
                )
            with context:
                with self.assertRaisesRegex(
                    RuntimeError, "stage-b seam"
                ):
                    engine.execute(
                        mission_id=mission_id,
                        binding_digest=suffix * 32,
                        envelope=envelope,
                        patch=PATCH,
                        cancel=lambda: False,
                    )
            checkpoint = engine._read_checkpoint(mission_id)
            self.assertIsNotNone(checkpoint)
            if seam == "clone_preparing":
                self.assertEqual(checkpoint["stage"], "bound")
            elif seam in {
                "before_prepare",
                "after_clone_intent",
                "after_provenance_slot_write",
                "clone_building",
            }:
                self.assertEqual(
                    checkpoint["stage"], "clone_preparing"
                )
            else:
                self.assertEqual(
                    checkpoint["stage"], "clone_building"
                )
            with engine._mission_process_lock(mission_id):
                provenance = (
                    engine._clone_cleanup.inspect_provenance(
                        mission_id=mission_id,
                        containment_handles=(
                            engine._borrowed_containment_handles(
                                mission_id
                            )
                        ),
                    )
                )
            self.assertEqual(
                None
                if provenance is None
                else provenance.get("state"),
                expected_provenance,
            )
            self.assertEqual(
                engine.capture_owner_git_state(self.repo),
                owner_before,
            )
            outcome = engine.execute(
                mission_id=mission_id,
                binding_digest=suffix * 32,
                envelope=envelope,
                patch=PATCH,
                cancel=lambda: False,
            )
            self.assertEqual(outcome["status"], "succeeded")
            self.assertTrue(
                engine.cleanup(
                    mission_id=mission_id,
                    binding_digest=suffix * 32,
                    envelope=envelope,
                )
            )
            self.assertFalse(engine._clone_path(mission_id).exists())
            self.assertEqual(
                engine.capture_owner_git_state(self.repo),
                owner_before,
            )

    def test_stage_b_terminal_cleanup_of_checkpoint_only_and_intent(
        self,
    ):
        for suffix, seam in (
            ("2a", "bound"),
            ("2b", "before_prepare"),
            ("2c", "intent"),
        ):
            terminal_state = ["failed"]
            engine = self._cleanup_enabled_engine(terminal_state)
            mission_id = "mis_" + suffix * 16
            envelope = AutopilotEnvelopeV1.build(
                root=str(self.repo.resolve()),
                base_head=self.head,
                owner_git_sha256=engine.capture_owner_git_state(
                    self.repo
                ),
                patch=PATCH,
                gates=[
                    {
                        "argv": ["onyx-static", "diff-check"],
                        "timeout_seconds": 30,
                    }
                ],
                max_seconds=120,
            )
            owner_before = engine.capture_owner_git_state(self.repo)
            original_prepare = engine._clone_cleanup.prepare_provenance

            def fail_prepare(**kwargs):
                if seam == "before_prepare":
                    raise RuntimeError("terminal seam")

                def fault(point):
                    if point == "after_clone_intent":
                        raise RuntimeError("terminal seam")

                kwargs["fault_hook"] = fault
                return original_prepare(**kwargs)

            if seam == "bound":
                original_write = engine._write_checkpoint

                def fail_clone_preparing(target_id, payload):
                    if payload.get("stage") == "clone_preparing":
                        raise RuntimeError("terminal seam")
                    return original_write(target_id, payload)

                context = mock_patch.object(
                    engine,
                    "_write_checkpoint",
                    side_effect=fail_clone_preparing,
                )
            else:
                context = mock_patch.object(
                    engine._clone_cleanup,
                    "prepare_provenance",
                    side_effect=fail_prepare,
                )
            with context:
                with self.assertRaisesRegex(
                    RuntimeError, "terminal seam"
                ):
                    engine.execute(
                        mission_id=mission_id,
                        binding_digest=suffix * 32,
                        envelope=envelope,
                        patch=PATCH,
                        cancel=lambda: False,
                    )
            cleaned = engine.cleanup(
                mission_id=mission_id,
                binding_digest=suffix * 32,
                envelope=envelope,
            )
            self.assertEqual(cleaned, seam == "intent")
            self.assertFalse(engine._clone_path(mission_id).exists())
            self.assertEqual(
                engine._read_checkpoint(mission_id)["stage"],
                "cleaned",
            )
            self.assertEqual(
                engine.capture_owner_git_state(self.repo),
                owner_before,
            )

    def test_stage_b_clone_ready_before_finalized_is_execute_invalid_but_cleanable(
        self,
    ):
        engine = self._cleanup_enabled_engine(["failed"])
        mission_id = "mis_" + "3a" * 16
        binding = "3a" * 32
        envelope = AutopilotEnvelopeV1.build(
            root=str(self.repo.resolve()),
            base_head=self.head,
            owner_git_sha256=engine.capture_owner_git_state(
                self.repo
            ),
            patch=PATCH,
            gates=[
                {
                    "argv": ["onyx-static", "diff-check"],
                    "timeout_seconds": 30,
                }
            ],
            max_seconds=120,
        )
        original_write = engine._write_checkpoint

        def stop_before_clone_building(target_id, payload):
            if payload.get("stage") == "clone_building":
                raise RuntimeError("prepared seam")
            return original_write(target_id, payload)

        with mock_patch.object(
            engine,
            "_write_checkpoint",
            side_effect=stop_before_clone_building,
        ):
            with self.assertRaisesRegex(
                RuntimeError, "prepared seam"
            ):
                engine.execute(
                    mission_id=mission_id,
                    binding_digest=binding,
                    envelope=envelope,
                    patch=PATCH,
                    cancel=lambda: False,
                )
        engine._write_checkpoint(
            mission_id,
            engine._checkpoint_payload(
                mission_id=mission_id,
                binding_digest=binding,
                envelope=envelope,
                stage="clone_ready",
                gate_index=0,
                gate_receipts=[],
                state_receipt=None,
                waiting_reason=None,
            ),
        )
        with self.assertRaisesRegex(
            ProjectAutopilotContractError,
            "cross_store_state_order_invalid",
        ):
            engine.execute(
                mission_id=mission_id,
                binding_digest=binding,
                envelope=envelope,
                patch=PATCH,
                cancel=lambda: False,
            )
        self.assertTrue(
            engine.cleanup(
                mission_id=mission_id,
                binding_digest=binding,
                envelope=envelope,
            )
        )
        self.assertFalse(engine._clone_path(mission_id).exists())

    def test_owner_git_lazy_capture_preserves_digest_and_bounds_next(
        self,
    ):
        root = Path(self.temporary.name) / "lazy-owner"
        git_dir = root / ".git"
        nested = git_dir / "a"
        nested.mkdir(parents=True)
        (git_dir / "b").write_bytes(b"b")
        (nested / "x").write_bytes(b"x")
        mode_a = stat.S_IMODE(nested.lstat().st_mode)
        mode_b = stat.S_IMODE((git_dir / "b").lstat().st_mode)
        mode_x = stat.S_IMODE((nested / "x").lstat().st_mode)
        expected = autopilot_module._digest(
            {
                "entries": [
                    {"path": "a", "kind": "dir", "mode": mode_a},
                    {
                        "path": "b",
                        "kind": "file",
                        "mode": mode_b,
                        "size": 1,
                        "sha256": hashlib.sha256(b"b").hexdigest(),
                    },
                    {
                        "path": "a/x",
                        "kind": "file",
                        "mode": mode_x,
                        "size": 1,
                        "sha256": hashlib.sha256(b"x").hexdigest(),
                    },
                ],
                "bytes": 2,
            }
        )
        self.assertEqual(
            ProjectAutopilotV1.capture_owner_git_state(root),
            expected,
        )

        bounded = Path(self.temporary.name) / "bounded-owner"
        bounded_git = bounded / ".git"
        bounded_git.mkdir(parents=True)
        for index in range(100):
            (bounded_git / f"{index:03}.dat").write_bytes(b"x")
        original_scandir = os.scandir
        next_calls = 0

        class CountingScandir:
            def __init__(self, path):
                self.inner = original_scandir(path)

            def __enter__(self):
                self.inner.__enter__()
                return self

            def __exit__(self, *args):
                return self.inner.__exit__(*args)

            def __iter__(self):
                return self

            def __next__(self):
                nonlocal next_calls
                next_calls += 1
                return next(self.inner)

        with (
            mock_patch.object(
                autopilot_module, "MAX_OWNER_GIT_FILES", 2
            ),
            mock_patch.object(
                autopilot_module.os,
                "scandir",
                side_effect=CountingScandir,
            ),
        ):
            with self.assertRaisesRegex(
                ProjectAutopilotContractError,
                "owner_git_file_budget_exhausted",
            ):
                ProjectAutopilotV1.capture_owner_git_state(
                    bounded
                )
        self.assertEqual(next_calls, 3)

    def test_rejects_traversal_and_shell_string_gates(self):
        unsafe_patch = """diff --git a/../outside.txt b/../outside.txt
--- a/../outside.txt
+++ b/../outside.txt
@@ -0,0 +1 @@
+no
"""
        with self.assertRaises(ProjectAutopilotContractError):
            AutopilotEnvelopeV1.build(
                root=str(self.repo),
                base_head=self.head,
                owner_git_sha256=self.engine.capture_owner_git_state(self.repo),
                patch=unsafe_patch,
                gates=[{"argv": ["python", "-m", "pytest"], "timeout_seconds": 10}],
                max_seconds=60,
            )
        with self.assertRaises(ProjectAutopilotContractError):
            AutopilotEnvelopeV1.build(
                root=str(self.repo),
                base_head=self.head,
                owner_git_sha256=self.engine.capture_owner_git_state(self.repo),
                patch=PATCH,
                gates=[{"argv": ["cmd", "/c", "pytest"], "timeout_seconds": 10}],
                max_seconds=60,
            )

    def test_patch_parser_tracks_hunks_and_rejects_appended_legacy_block(self):
        content_markers = """diff --git a/demo.txt b/demo.txt
--- a/demo.txt
+++ b/demo.txt
@@ -1,2 +1,2 @@
---- old
-keep
++++ new
+keep
"""
        envelope = self._envelope(patch_text=content_markers)
        self.assertEqual(envelope.patch_paths, ("demo.txt",))

        appended_legacy = (
            PATCH
            + """--- a/module.py
+++ b/module.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""
        )
        with self.assertRaisesRegex(
            ProjectAutopilotContractError, "noncanonical"
        ):
            self._envelope(patch_text=appended_legacy)

    def test_replayed_valid_checkpoint_fails_against_vault_high_water(self):
        mission_id = "mis_" + "8" * 32
        envelope = self._envelope()
        outcome = self.engine.execute(
            mission_id=mission_id,
            binding_digest="8" * 64,
            envelope=envelope,
            patch=PATCH,
            cancel=lambda: False,
        )
        self.assertEqual(outcome["status"], "succeeded")
        path = self.control / mission_id / "checkpoint.json"
        old_valid = path.read_bytes()
        anchor_vault = self.vaults[f"cp-{mission_id}"]
        old_anchor = anchor_vault.value
        current = self.engine._read_checkpoint(mission_id)
        payload = {
            key: value
            for key, value in current.items()
            if key not in {"checkpoint_digest", "signature", "sequence"}
        }
        self.engine._write_checkpoint(mission_id, payload)
        path.write_bytes(old_valid)
        anchor_vault.value = old_anchor
        with self.assertRaisesRegex(
            ProjectAutopilotContractError, "rollback|replay|tamper"
        ):
            self.engine._read_checkpoint(mission_id)

    def test_persisted_checkpoint_requires_fresh_approval_after_restart(self):
        mission_id = "mis_" + "7" * 32
        outcome = self.engine.execute(
            mission_id=mission_id,
            binding_digest="7" * 64,
            envelope=self._envelope(),
            patch=PATCH,
            cancel=lambda: False,
        )
        self.assertEqual(outcome["status"], "succeeded")
        with autopilot_module._PROCESS_HIGH_WATER_LOCK:
            autopilot_module._PROCESS_HIGH_WATER.pop(mission_id, None)
        with self.assertRaisesRegex(
            ProjectAutopilotWaiting, "fresh_owner_reapproval_required"
        ):
            self.engine._read_checkpoint(mission_id)

    def test_checkpoint_transaction_recovers_each_crash_seam(self):
        envelope = self._envelope()
        original_write = autopilot_module._atomic_descriptor_write
        original_scrub = autopilot_module._secure_scrub_regular
        for suffix, seam in (("4", "checkpoint"), ("5", "vault"), ("a", "scrub")):
            mission_id = "mis_" + suffix * 32
            payload = self.engine._checkpoint_payload(
                mission_id=mission_id,
                binding_digest=suffix * 64,
                envelope=envelope,
                stage="bound",
                gate_index=0,
                gate_receipts=[],
                state_receipt=None,
                waiting_reason=None,
            )
            self.engine._write_checkpoint(mission_id, payload)
            payload["waiting_reason"] = f"after-{seam}"
            if seam == "checkpoint":
                failed = False

                def fail_checkpoint(path, content):
                    nonlocal failed
                    if path.name == "checkpoint.json" and not failed:
                        failed = True
                        raise OSError("simulated crash")
                    return original_write(path, content)

                context = mock_patch.object(
                    autopilot_module,
                    "_atomic_descriptor_write",
                    side_effect=fail_checkpoint,
                )
            elif seam == "vault":
                context = mock_patch.object(
                    self.vaults[f"cp-{mission_id}"],
                    "set_bytes",
                    side_effect=OSError("simulated crash"),
                )
            else:
                failed = False

                def fail_transaction_scrub(path, limit):
                    nonlocal failed
                    if path.name == "checkpoint.transaction.json" and not failed:
                        failed = True
                        raise OSError("simulated crash")
                    return original_scrub(path, limit)

                context = mock_patch.object(
                    autopilot_module,
                    "_secure_scrub_regular",
                    side_effect=fail_transaction_scrub,
                )
            with context:
                with self.assertRaises(OSError):
                    self.engine._write_checkpoint(mission_id, payload)
            recovered = self.engine._read_checkpoint(mission_id)
            self.assertEqual(recovered["waiting_reason"], f"after-{seam}")
            self.assertFalse(
                self.engine._transaction_path(mission_id).exists()
            )

    def test_mission_interprocess_lock_fails_closed_when_busy(self):
        mission_id = "mis_" + "b" * 32
        envelope = self._envelope()
        outcome = self.engine.execute(
            mission_id=mission_id,
            binding_digest="b" * 64,
            envelope=envelope,
            patch=PATCH,
            cancel=lambda: False,
        )
        self.assertEqual(outcome["status"], "succeeded")
        checkpoint_path = self.engine._checkpoint_path(mission_id)
        checkpoint_before = checkpoint_path.read_bytes()
        with self.engine._mission_process_lock(mission_id):
            with self.assertRaisesRegex(
                ProjectAutopilotWaiting, "mission_interprocess_lock_busy"
            ):
                self.engine._read_checkpoint(mission_id)
            with self.assertRaisesRegex(
                ProjectAutopilotWaiting, "mission_interprocess_lock_busy"
            ):
                IndependentAutopilotVerifierV1(self.engine).verify(
                    mission_id=mission_id,
                    binding_digest="b" * 64,
                    envelope=envelope,
                    cancel=lambda: False,
                )
        self.assertEqual(checkpoint_path.read_bytes(), checkpoint_before)
        self.assertEqual(
            self.engine._read_checkpoint(mission_id)["stage"], "verified"
        )

    def test_kill_during_terminal_verification_never_returns_success(self):
        for suffix, seam in (("c", "before_checkpoint"), ("d", "before_return")):
            mission_id = "mis_" + suffix * 32
            killed = False
            original_write = self.engine._write_checkpoint
            original_verify = IndependentAutopilotVerifierV1._verify_locked

            def verify_then_kill(verifier, *args, **kwargs):
                nonlocal killed
                result = original_verify(verifier, *args, **kwargs)
                killed = True
                return result

            def write_then_kill(target_mission_id, payload):
                nonlocal killed
                result = original_write(target_mission_id, payload)
                if payload.get("stage") == "verified":
                    killed = True
                return result

            if seam == "before_checkpoint":
                context = mock_patch.object(
                    IndependentAutopilotVerifierV1,
                    "_verify_locked",
                    autospec=True,
                    side_effect=verify_then_kill,
                )
            else:
                context = mock_patch.object(
                    self.engine,
                    "_write_checkpoint",
                    side_effect=write_then_kill,
                )
            with self.subTest(seam=seam), context:
                outcome = self.engine.execute(
                    mission_id=mission_id,
                    binding_digest=suffix * 64,
                    envelope=self._envelope(),
                    patch=PATCH,
                    cancel=lambda: killed,
                )
            self.assertEqual(outcome["status"], "waiting")
            self.assertEqual(outcome["waiting_for"], "kill_requested")
            checkpoint = self.engine._read_checkpoint(mission_id)
            self.assertNotEqual(checkpoint["stage"], "verified")
            self.assertEqual(checkpoint["waiting_reason"], "kill_requested")

    def test_same_size_clone_file_swap_is_detected_by_verifier(self):
        mission_id = "mis_" + "9" * 32
        envelope = self._envelope()
        outcome = self.engine.execute(
            mission_id=mission_id,
            binding_digest="9" * 64,
            envelope=envelope,
            patch=PATCH,
            cancel=lambda: False,
        )
        self.assertEqual(outcome["status"], "succeeded")
        target = self.control / mission_id / "clone" / "demo.txt"
        replacement = target.with_suffix(".swap")
        replacement.write_bytes(b"evil!\n")
        os.replace(replacement, target)
        with self.assertRaisesRegex(ProjectAutopilotWaiting, "drift"):
            IndependentAutopilotVerifierV1(self.engine).verify(
                mission_id=mission_id,
                binding_digest="9" * 64,
                envelope=envelope,
                cancel=lambda: False,
            )

    def test_unsigned_extra_dirty_path_is_refused(self):
        mission_id = "mis_" + "6" * 32
        envelope = self._envelope()
        outcome = self.engine.execute(
            mission_id=mission_id,
            binding_digest="6" * 64,
            envelope=envelope,
            patch=PATCH,
            cancel=lambda: False,
        )
        self.assertEqual(outcome["status"], "succeeded")
        clone = self.control / mission_id / "clone"
        (clone / "unsigned-extra.txt").write_text("extra", encoding="utf-8")
        with self.assertRaisesRegex(
            ProjectAutopilotWaiting, "dirty_paths_diverge_from_signed_patch"
        ):
            IndependentAutopilotVerifierV1(self.engine).verify(
                mission_id=mission_id,
                binding_digest="6" * 64,
                envelope=envelope,
                cancel=lambda: False,
            )

    def test_checkpoint_and_patch_symlink_swaps_fail_closed(self):
        for suffix, filename in (("a", "checkpoint.json"), ("b", "patch.diff")):
            mission_id = "mis_" + suffix * 32
            mission_dir = self.control / mission_id
            mission_dir.mkdir(parents=True)
            outside = Path(self.temporary.name) / f"outside-{suffix}"
            outside.write_text(PATCH, encoding="utf-8")
            try:
                os.symlink(outside, mission_dir / filename)
            except OSError:
                self.skipTest("symlink creation is unavailable on this host")
            if filename == "checkpoint.json":
                with self.assertRaises(ProjectAutopilotContractError):
                    self.engine._read_checkpoint(mission_id)
            else:
                with self.assertRaises(ProjectAutopilotContractError):
                    self.engine.execute(
                        mission_id=mission_id,
                        binding_digest=suffix * 64,
                        envelope=self._envelope(),
                        patch=PATCH,
                        cancel=lambda: False,
                    )

    def test_preseeded_clone_and_cleanup_swap_are_refused(self):
        mission_id = "mis_" + "c" * 32
        clone = self.control / mission_id / "clone"
        clone.mkdir(parents=True)
        with self.assertRaisesRegex(ProjectAutopilotContractError, "preseeded"):
            self.engine.execute(
                mission_id=mission_id,
                binding_digest="c" * 64,
                envelope=self._envelope(),
                patch=PATCH,
                cancel=lambda: False,
            )

        clean_id = "mis_" + "d" * 32
        envelope = self._envelope()
        outcome = self.engine.execute(
            mission_id=clean_id,
            binding_digest="d" * 64,
            envelope=envelope,
            patch=PATCH,
            cancel=lambda: False,
        )
        self.assertEqual(outcome["status"], "succeeded")
        controlled = self.control / clean_id / "clone"
        displaced = self.control / clean_id / "clone-real"
        controlled.rename(displaced)
        outside = Path(self.temporary.name) / "outside-cleanup"
        outside.mkdir()
        marker = outside / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        try:
            os.symlink(outside, controlled, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlink creation is unavailable")
        with self.assertRaises(ProjectAutopilotContractError):
            self.engine.cleanup(
                mission_id=clean_id,
                binding_digest="d" * 64,
                owner_root=str(self.repo),
            )
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_fake_git_and_malicious_global_config_are_ignored(self):
        hostile = Path(self.temporary.name) / "hostile"
        hostile.mkdir()
        (hostile / "git.exe").write_text("not git", encoding="utf-8")
        marker = hostile / "FILTER_EXECUTED"
        config = hostile / "gitconfig"
        config.write_text(
            "[core]\n"
            f"    fsmonitor = powershell -NoProfile -Command \"Set-Content '{marker}' bad\"\n"
            "[filter \"evil\"]\n"
            f"    process = powershell -NoProfile -Command \"Set-Content '{marker}' bad\"\n"
            "    required = true\n",
            encoding="utf-8",
        )
        with mock_patch.dict(
            os.environ,
            {
                "PATH": str(hostile),
                "HOME": str(hostile),
                "USERPROFILE": str(hostile),
                "GIT_CONFIG_GLOBAL": str(config),
            },
        ):
            mission_id = "mis_" + "e" * 32
            outcome = self.engine.execute(
                mission_id=mission_id,
                binding_digest="e" * 64,
                envelope=self._envelope(),
                patch=PATCH,
                cancel=lambda: False,
            )
        self.assertEqual(outcome["status"], "succeeded")
        self.assertFalse(marker.exists())
        self.assertNotEqual(self.engine.git_executable.parent, hostile)

    def test_drive_ads_and_resource_exhaustion_fail_closed(self):
        owner_digest = self.engine.capture_owner_git_state(self.repo)
        for unsafe in ("C:/escape.py", "module.py:stream"):
            unsafe_patch = (
                f"diff --git a/{unsafe} b/{unsafe}\n"
                f"--- a/{unsafe}\n+++ b/{unsafe}\n"
                "@@ -0,0 +1 @@\n+bad\n"
            )
            with self.assertRaises(ProjectAutopilotContractError):
                AutopilotEnvelopeV1.build(
                    root=str(self.repo),
                    base_head=self.head,
                    owner_git_sha256=owner_digest,
                    patch=unsafe_patch,
                    gates=[
                        {
                            "argv": ["onyx-static", "diff-check"],
                            "timeout_seconds": 10,
                        }
                    ],
                    max_seconds=60,
                )
        with mock_patch(
            "core.phase11_project_autopilot_v1.MAX_OWNER_GIT_BYTES", 1
        ):
            with self.assertRaises(ProjectAutopilotContractError):
                self.engine.capture_owner_git_state(self.repo)
        with mock_patch(
            "core.phase11_project_autopilot_v1.MAX_CLONE_BYTES", 1
        ):
            outcome = self.engine.execute(
                mission_id="mis_" + "f" * 32,
                binding_digest="f" * 64,
                envelope=self._envelope(),
                patch=PATCH,
                cancel=lambda: False,
            )
        self.assertEqual(outcome["status"], "waiting")
        self.assertIn("disk_budget", outcome["waiting_for"])
        directory_envelope = self._envelope()
        with mock_patch(
            "core.phase11_project_autopilot_v1.MAX_CLONE_DIRS", 1
        ):
            outcome = self.engine.execute(
                mission_id="mis_" + "0" * 32,
                binding_digest="0" * 64,
                envelope=directory_envelope,
                patch=PATCH,
                cancel=lambda: False,
            )
        self.assertEqual(outcome["status"], "waiting")
        self.assertIn("directory_budget", outcome["waiting_for"])

    def test_sparse_and_compression_bomb_are_refused_before_bundle(self):
        sparse = self.repo / "sparse.bin"
        with sparse.open("wb") as stream:
            stream.seek((4 * 1024 * 1024) - 1)
            stream.write(b"\0")
        (self.repo / "compressible.bin").write_bytes(b"A" * (2 * 1024 * 1024))
        _git(self.repo, "add", "sparse.bin", "compressible.bin")
        _git(self.repo, "commit", "-m", "quota fixtures")
        self.head = _git(self.repo, "rev-parse", "HEAD").lower()
        mission_id = "mis_" + "0" * 32
        with mock_patch(
            "core.phase11_project_autopilot_v1.MAX_CLONE_BYTES",
            3 * 1024 * 1024,
        ):
            outcome = self.engine.execute(
                mission_id=mission_id,
                binding_digest="0" * 64,
                envelope=self._envelope(),
                patch=PATCH,
                cancel=lambda: False,
            )
        self.assertEqual(outcome["status"], "waiting")
        self.assertEqual(
            outcome["waiting_for"],
            "controlled_clone_preflight_disk_budget_exhausted",
        )
        self.assertFalse(self.engine._bundle_path(mission_id).exists())
        self.assertFalse(self.engine._clone_path(mission_id).exists())

    def test_logical_disk_monitor_bounds_entries_depth_and_time(self):
        root = Path(self.temporary.name) / "monitor-bounds"
        nested = root / "nested"
        nested.mkdir(parents=True)
        (root / "one").write_bytes(b"1")
        (root / "two").write_bytes(b"2")
        with mock_patch.object(autopilot_module, "MAX_MONITOR_FILES", 1):
            with self.assertRaisesRegex(
                ProjectAutopilotWaiting, "file_budget"
            ):
                autopilot_module._logical_tree_bytes(root, 1024)
        with mock_patch.object(autopilot_module, "MAX_MONITOR_DIRS", 1):
            with self.assertRaisesRegex(
                ProjectAutopilotWaiting, "directory_budget"
            ):
                autopilot_module._logical_tree_bytes(root, 1024)
        with mock_patch.object(autopilot_module, "MAX_MONITOR_DEPTH", 0):
            with self.assertRaisesRegex(
                ProjectAutopilotWaiting, "depth_budget"
            ):
                autopilot_module._logical_tree_bytes(root, 1024)
        with mock_patch.object(autopilot_module, "MAX_MONITOR_SECONDS", -1):
            with self.assertRaisesRegex(
                ProjectAutopilotWaiting, "time_budget"
            ):
                autopilot_module._logical_tree_bytes(root, 1024)

    def test_logical_disk_monitor_stops_lazy_scan_at_directory_limit(self):
        root = Path(self.temporary.name) / "monitor-lazy"
        children = [root / f"child-{index}" for index in range(3)]
        for child in children:
            child.mkdir(parents=True)

        class Entry:
            def __init__(self, path):
                self.path = str(path)

        class CanaryScandir:
            def __init__(self):
                self.yielded = 0
                self.closed = False

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.closed = True

            def __iter__(self):
                return self

            def __next__(self):
                self.yielded += 1
                if self.yielded > 1:
                    raise AssertionError("directory scan was over-consumed")
                return Entry(children[0])

        scanner = CanaryScandir()
        with (
            mock_patch.object(autopilot_module.os, "scandir", return_value=scanner),
            mock_patch.object(autopilot_module, "MAX_MONITOR_DIRS", 1),
        ):
            with self.assertRaisesRegex(
                ProjectAutopilotWaiting, "directory_budget"
            ):
                autopilot_module._logical_tree_bytes(root, 1024)
        self.assertEqual(scanner.yielded, 1)
        self.assertTrue(scanner.closed)

    def test_clone_tree_budget_restarts_complete_scan_after_atomic_replace(self):
        root = Path(self.temporary.name) / "clone-tree-retry"
        root.mkdir()
        target = root / "pack-transient.pack"
        target.write_bytes(b"stable")
        original_lstat = Path.lstat
        attempts = 0

        def transient_lstat(path: Path):
            nonlocal attempts
            if path.name == target.name and attempts == 0:
                attempts += 1
                raise FileNotFoundError(str(path))
            return original_lstat(path)

        with (
            mock_patch.object(Path, "lstat", transient_lstat),
            mock_patch.object(autopilot_module.time, "sleep"),
        ):
            usage = autopilot_module._bounded_tree_usage(root)
        self.assertEqual(usage, (1, 1, len(b"stable")))
        self.assertEqual(attempts, 1)

    def test_clone_tree_budget_fails_closed_when_tree_never_stabilizes(self):
        root = Path(self.temporary.name) / "clone-tree-unstable"
        root.mkdir()
        target = root / "pack-churning.pack"
        target.write_bytes(b"moving")
        original_lstat = Path.lstat

        def unstable_lstat(path: Path):
            if path.name == target.name:
                raise FileNotFoundError(str(path))
            return original_lstat(path)

        with (
            mock_patch.object(Path, "lstat", unstable_lstat),
            mock_patch.object(autopilot_module.time, "sleep"),
            self.assertRaisesRegex(
                ProjectAutopilotWaiting, "controlled_clone_tree_unstable"
            ),
        ):
            autopilot_module._bounded_tree_usage(root)

    @unittest.skipUnless(os.name == "nt", "Win32 extended paths are Windows-only")
    def test_clone_tree_budget_supports_pack_path_beyond_legacy_max_path(self):
        first = Path(self.temporary.name) / ("a" * 120)
        root = first / ("b" * 70)
        root.mkdir(parents=True)
        target = root / ("pack-" + ("c" * 40) + ".pack")
        self.assertGreater(len(str(target)), 260)
        extended_target = autopilot_module._extended_length_path(target)
        extended_target.write_bytes(b"pack")
        try:
            self.assertEqual(
                autopilot_module._bounded_tree_usage(root),
                (1, 1, len(b"pack")),
            )
        finally:
            extended_target.unlink(missing_ok=True)

    def test_existing_phase11_bridge_runs_signed_autopilot_step(self):
        vaults: dict[str, MemoryVault] = {}

        def vault_factory(reference):
            return vaults.setdefault(reference.account, MemoryVault())

        store = MissionStore(Path(self.temporary.name) / "missions.sqlite3")
        bridge = Phase11LiveMissionV1(
            store,
            binding_dir=Path(self.temporary.name) / "bindings",
            allowed_roots=(self.repo,),
            enabled=True,
            key=b"z" * 32,
            anchor_vault_factory=vault_factory,
            autopilot_enabled=True,
        )
        set_permission_callback(lambda request: request["digest"])
        mission = None
        replacement = None
        try:
            secret_canary = "ONYX_SECRET_CANARY_7E923C0C"
            canary_patch = PATCH.replace("+after", f"+{secret_canary}")
            mission = bridge.create_autopilot(
                title="Apply isolated change",
                workspace_root=str(self.repo),
                patch=canary_patch,
                gates=[
                    {
                        "argv": ["onyx-static", "diff-check"],
                        "timeout_seconds": 30,
                    }
                ],
                max_seconds=120,
            )
            binding = bridge._read_binding(mission.id)
            self.assertEqual(binding["mission_type"], "project_autopilot_v1")
            self.assertNotIn("patch", binding)
            self.assertEqual(
                binding["patch_artifact"]["schema"],
                "onyx.phase11.patch_artifact.v1",
            )
            canary_bytes = secret_canary.encode("utf-8")
            for path in Path(self.temporary.name).rglob("*"):
                if path.is_file() and not path.is_symlink():
                    self.assertNotIn(
                        canary_bytes,
                        path.read_bytes(),
                        f"plaintext patch leaked into {path}",
                    )
            visible_plan = binding["fixed_steps"][0]["args"]
            self.assertEqual(visible_plan["patch_paths"], ["demo.txt"])
            self.assertEqual(
                visible_plan["static_gates"],
                [["onyx-static", "diff-check"]],
            )
            self.assertFalse(visible_plan["repository_code_execution"])
            self.assertEqual(
                visible_plan["mutation_boundary"], "standalone_clone"
            )
            bridge.approve(mission.id)
            completed = store.run(mission.id, bridge.runner, backoff=lambda _: None)
            self.assertEqual(completed.state, "succeeded", completed.error)
            status = bridge.status(mission.id)
            self.assertEqual(status["mission_type"], "project_autopilot_v1")
            self.assertEqual(status["autopilot"]["stage"], "verified")
            self.assertEqual((self.repo / "demo.txt").read_text(), "before\n")
            clone_root = bridge.autopilot._clone_path(mission.id)
            for path in Path(self.temporary.name).rglob("*"):
                if (
                    path.is_file()
                    and not path.is_symlink()
                    and clone_root not in path.parents
                ):
                    self.assertNotIn(
                        canary_bytes,
                        path.read_bytes(),
                        f"plaintext patch leaked into {path}",
                    )
            self.assertFalse(
                any(Path(self.temporary.name).rglob("patch.diff"))
            )
            with autopilot_module._PROCESS_HIGH_WATER_LOCK:
                autopilot_module._PROCESS_HIGH_WATER.pop(mission.id, None)
            with self.assertRaisesRegex(
                ProjectAutopilotWaiting, "fresh_owner_reapproval_required"
            ):
                bridge.autopilot._read_checkpoint(mission.id)
            replacement = bridge.reseed_autopilot(mission.id)
            self.assertEqual(replacement.state, "awaiting_approval")
            with self.assertRaisesRegex(
                ProjectAutopilotWaiting, "fresh_owner_reapproval_required"
            ):
                bridge.autopilot._read_checkpoint(mission.id)
            replacement_binding = bridge._read_binding(replacement.id)
            self.assertEqual(
                replacement_binding["autopilot"]["input_digest"],
                binding["autopilot"]["input_digest"],
            )
            self.assertNotEqual(
                bridge._kill_event_name(
                    mission.id, binding["binding_digest"]
                ),
                bridge._kill_event_name(
                    replacement.id,
                    replacement_binding["binding_digest"],
                ),
            )
            self.assertNotEqual(
                replacement_binding["autopilot"]["runtime_nonce"],
                binding["autopilot"]["runtime_nonce"],
            )
            bridge.approve(replacement.id)
            replacement_done = store.run(
                replacement.id, bridge.runner, backoff=lambda _: None
            )
            self.assertEqual(
                replacement_done.state,
                "succeeded",
                replacement_done.error,
            )
            with self.assertRaisesRegex(
                ProjectAutopilotWaiting,
                "controlled_clone_cleanup_requires_handle_safe_deleter",
            ):
                bridge.cleanup_autopilot(replacement.id)
        finally:
            set_permission_callback(None)
            retained = [
                item
                for item in (mission, replacement)
                if item is not None
                and bridge.autopilot is not None
                and bridge.autopilot._clone_path(item.id).exists()
            ]
            if retained:
                import shutil

                def make_writable(function, path, _error):
                    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
                    function(path)

                for item in retained:
                    shutil.rmtree(
                        bridge.autopilot._clone_path(item.id),
                        onexc=make_writable,
                    )
            bridge.close()
if __name__ == "__main__":
    unittest.main()
