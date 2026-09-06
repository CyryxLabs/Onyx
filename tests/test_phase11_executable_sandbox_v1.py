from __future__ import annotations

import io
import importlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from core.phase11_executable_sandbox_v1 import (
    FEATURE_FLAG,
    MAX_CONCURRENT_EXECUTIONS,
    OWNER_LABEL,
    ExecutableSandboxRequestV1,
    ExecutableTestSandboxV1,
    SandboxCleanupError,
    SandboxCollisionError,
    SandboxContractError,
    SandboxDisabledError,
    SandboxDockerError,
    feature_enabled,
    verify_executable_sandbox_receipt_v1,
)
from core.phase11_execution_ledger_v1 import Phase11ExecutionLedgerV1


IMAGE = "sha256:" + "a" * 64
CONTAINER_ID = "b" * 64
SIGNING_KEY = b"k" * 32
DOCKER_HOST = "npipe:////./pipe/docker_engine"


def image_inspect(
    image_id: str = IMAGE,
    volumes=None,
    operating_system: str = "linux",
    architecture: str = "amd64",
    entrypoint=None,
) -> bytes:
    return json.dumps(
        [
            {
                "Id": image_id,
                "Os": operating_system,
                "Architecture": architecture,
                "Config": {
                    "Volumes": volumes,
                    "Entrypoint": entrypoint,
                },
            }
        ]
    ).encode("utf-8")


def container_inspect(owner: str, container_id: str = CONTAINER_ID) -> bytes:
    return json.dumps(
        [{"Id": container_id, "Config": {"Labels": {OWNER_LABEL: owner}}}]
    ).encode("utf-8")


def secure_windows_directory(path: Path) -> None:
    if os.name != "nt":
        return
    ntsecuritycon: Any = importlib.import_module("ntsecuritycon")
    win32api: Any = importlib.import_module("win32api")
    win32security: Any = importlib.import_module("win32security")

    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32security.TOKEN_QUERY
    )
    current = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    dacl = win32security.ACL()
    inheritance = win32security.CONTAINER_INHERIT_ACE | win32security.OBJECT_INHERIT_ACE
    for sid in (
        current,
        win32security.ConvertStringSidToSid("S-1-5-18"),
        win32security.ConvertStringSidToSid("S-1-5-32-544"),
    ):
        dacl.AddAccessAllowedAceEx(
            win32security.ACL_REVISION_DS,
            inheritance,
            ntsecuritycon.FILE_ALL_ACCESS,
            sid,
        )
    win32security.SetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION
        | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        dacl,
        None,
    )


class FakeProcess:
    def __init__(
        self,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        *,
        blocked: bool = False,
        stuck: bool = False,
    ) -> None:
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = None if blocked or stuck else returncode
        self._final = returncode
        self._blocked = blocked
        self._stuck = stuck
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self._stuck or (self._blocked and not (self.terminated or self.killed)):
            raise subprocess.TimeoutExpired(["docker"], timeout)
        self.returncode = (
            -9 if self.killed else (-15 if self.terminated else self._final)
        )
        return self.returncode

    def terminate(self):
        self.terminated = True
        if not self._stuck:
            self.returncode = -15

    def kill(self):
        self.killed = True
        if not self._stuck:
            self.returncode = -9


class ChunkedStream(io.BytesIO):
    def __init__(self, value: bytes, chunk_size: int) -> None:
        super().__init__(value)
        self.chunk_size = chunk_size

    def read(self, _size=-1):
        return super().read(self.chunk_size)


class ExecutableSandboxV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self._ledger_boundaries = []
        self.base = Path(self.temporary.name).resolve()
        self.clone_parent = self.base / "clones"
        self.clone_parent.mkdir()
        secure_windows_directory(self.clone_parent)
        self.clone = self.clone_parent / "mission-clone"
        self.clone.mkdir()
        self.control = self.base / "control"
        self.control.mkdir()
        secure_windows_directory(self.control)
        self.docker = self.base / "docker.exe"
        self.docker.write_bytes(b"trusted test executable")

    def tearDown(self) -> None:
        for boundary in self._ledger_boundaries:
            boundary.close()
        self.temporary.cleanup()

    def request(self, **changes) -> ExecutableSandboxRequestV1:
        values: dict[str, Any] = {
            "mission_id": "mis_test_1",
            "execution_id": "e" * 64,
            "clone_root": str(self.clone),
            "image_id": IMAGE,
            "argv": ("python", "-m", "pytest"),
            "timeout_seconds": 1.0,
            "max_output_bytes": 1024,
        }
        values.update(changes)
        return ExecutableSandboxRequestV1(**values)

    def sandbox(self, factory, **changes) -> ExecutableTestSandboxV1:
        values: dict[str, Any] = {
            "docker_cli": str(self.docker),
            "docker_host": DOCKER_HOST,
            "container_platform": "linux/amd64",
            "control_root": str(self.control),
            "clone_parent": str(self.clone_parent),
            "signing_key": SIGNING_KEY,
            "enabled": True,
            "process_factory": factory,
        }
        values.update(changes)
        return ExecutableTestSandboxV1(**values)

    @staticmethod
    def action(command) -> tuple[str, ...]:
        return tuple(command[3:])

    def successful_factory(self, calls, stdout=b"tests passed\n", stderr=b""):
        def factory(command, **kwargs):
            calls.append((tuple(command), kwargs))
            action = self.action(command)
            if action[:2] == ("image", "inspect"):
                return FakeProcess(image_inspect())
            if action[:2] == ("container", "inspect"):
                return FakeProcess(
                    stderr=b"Error: No such container: absent", returncode=1
                )
            return FakeProcess(stdout, stderr)

        return factory

    def test_default_off_is_exact_and_has_zero_side_effects(self):
        calls = []
        with patch.dict(os.environ, {FEATURE_FLAG: "true"}, clear=False):
            self.assertTrue(feature_enabled(None))
            self.assertFalse(feature_enabled({}))
        for value in ("1", "TRUE", " true", "true ", "yes", "on", ""):
            with self.subTest(value=value):
                self.assertFalse(feature_enabled({FEATURE_FLAG: value}))
        self.assertTrue(feature_enabled({FEATURE_FLAG: "true"}))
        sandbox = ExecutableTestSandboxV1(
            docker_cli="relative-docker",
            docker_host="tcp://remote:2375",
            control_root="relative",
            clone_parent="relative",
            signing_key=b"short",
            process_factory=lambda *_a, **_k: calls.append("process"),
            path_resolver=lambda value: calls.append(value) or value,
        )
        with self.assertRaises(SandboxDisabledError):
            sandbox.execute(self.request())
        self.assertEqual(calls, [])

    def test_constructor_requires_key_roots_and_local_pinned_endpoint(self):
        base = {
            "docker_cli": str(self.docker),
            "container_platform": "linux/amd64",
            "control_root": str(self.control),
            "clone_parent": str(self.clone_parent),
            "signing_key": SIGNING_KEY,
            "enabled": True,
        }
        for host in (
            None,
            "tcp://127.0.0.1:2375",
            "ssh://localhost",
            "http://localhost",
            "unix://relative.sock",
        ):
            with self.subTest(host=host):
                with self.assertRaises(SandboxContractError):
                    ExecutableTestSandboxV1(docker_host=host, **base)
        with self.assertRaises(SandboxContractError):
            ExecutableTestSandboxV1(
                docker_host=DOCKER_HOST, **{**base, "signing_key": b"x" * 31}
            )
        for platform in (None, "linux", "windows/amd64", "linux/386"):
            with self.subTest(platform=platform):
                with self.assertRaises(SandboxContractError):
                    ExecutableTestSandboxV1(
                        docker_host=DOCKER_HOST,
                        **{**base, "container_platform": platform},
                    )
        if os.name == "nt":
            ExecutableTestSandboxV1(docker_host=DOCKER_HOST, **base)
        elif Path("/var/run/docker.sock").exists():
            ExecutableTestSandboxV1(docker_host="unix:///var/run/docker.sock", **base)

    def test_optional_execution_ledger_records_dispatch_and_receipt(self):
        calls = []
        if os.name == "nt":
            from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1

            boundary = WindowsTrustedDirectoryV1(
                root=self.base / "execution-ledger", enabled=True
            )
        else:
            from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1

            boundary = PosixTrustedDirectoryV1(
                root=self.base / "execution-ledger", enabled=True
            )
        ledger = Phase11ExecutionLedgerV1(
            host_secret=b"ledger-host-secret" * 2,
            trusted_directory=boundary,
            receipt_signing_key=SIGNING_KEY,
            receipt_verifier=verify_executable_sandbox_receipt_v1,
            enabled=True,
        )
        sandbox = self.sandbox(
            self.successful_factory(calls), execution_ledger=ledger
        )

        self._ledger_boundaries.append(boundary)
        sandbox.execute(self.request(attempt=1))

        records = ledger.read()
        self.assertEqual(
            [record.kind for record in records],
            ["intent", "dispatch_reserved", "receipt"],
        )
        self.assertTrue(all(record.attempt == 1 for record in records))
        self.assertEqual(
            ledger.execution_state(
                mission_id="mis_test_1", execution_id="e" * 64, attempt=1
            ),
            "receipt",
        )

    def test_exact_image_hardened_run_and_pinned_host_every_call(self):
        calls = []
        sandbox = self.sandbox(self.successful_factory(calls))
        receipt = sandbox.execute(self.request())
        self.assertEqual(receipt.verdict, "PASS")
        self.assertEqual(receipt.image_sha256, "a" * 64)
        self.assertNotIn("tests passed", repr(receipt))
        self.assertNotIn(str(self.clone), repr(receipt))
        self.assertNotIn("mis_test_1", repr(receipt))
        self.assertTrue(receipt.receipt_hmac_sha256)
        self.assertEqual(len(calls), 3)
        for command, options in calls:
            self.assertEqual(command[:3], (str(self.docker), "--host", DOCKER_HOST))
            self.assertFalse(options["shell"])
            self.assertNotIn("DOCKER_HOST", options["env"])
            self.assertNotIn("DOCKER_CONTEXT", options["env"])
        command = calls[1][0]
        self.assertEqual(command[3], "run")
        self.assertEqual(command.count("--mount"), 1)
        mount = command[command.index("--mount") + 1]
        self.assertEqual(
            mount,
            f"type=bind,source={self.clone},target=/workspace,"
            "readonly,bind-propagation=rprivate,bind-recursive=disabled",
        )
        for sequence in (
            ("--pull", "never"),
            ("--platform", "linux/amd64"),
            ("--network", "none"),
            ("--log-driver", "none"),
            ("--cap-drop", "ALL"),
            ("--security-opt", "no-new-privileges:true"),
            ("--user", "65532:65532"),
            ("--pids-limit", "64"),
            ("--memory", "256m"),
            ("--memory-swap", "256m"),
            ("--cpus", "1.0"),
            ("--workdir", "/workspace"),
        ):
            index = command.index(sequence[0])
            self.assertEqual(command[index : index + 2], sequence)
        self.assertIn("--read-only", command)
        self.assertIn("--no-healthcheck", command)
        self.assertIn("--tmpfs", command)
        self.assertEqual(
            command[command.index("--entrypoint") : command.index("--entrypoint") + 2],
            ("--entrypoint", "python"),
        )
        image_index = command.index(IMAGE)
        self.assertEqual(command[image_index + 1 :], ("-m", "pytest"))
        self.assertNotIn("/var/run/docker.sock", " ".join(command))
        self.assertRegex(
            command[command.index("--name") + 1], r"^onyx-p11-[0-9a-f]{32}$"
        )
        label = command[command.index("--label") + 1]
        self.assertRegex(label, rf"^{re_escape(OWNER_LABEL)}=[0-9a-f]{{64}}$")
        self.assertNotIn(label.split("=", 1)[1], repr(receipt))
        self.assertRegex(
            receipt.prelaunch_clone_manifest_hmac_sha256, r"^[0-9a-f]{64}$"
        )

    def test_image_id_and_declared_volumes_fail_closed(self):
        def factory(command, **_kwargs):
            action = self.action(command)
            if action[:2] == ("image", "inspect"):
                return FakeProcess(image_inspect(volumes={"/data": {}}))
            return FakeProcess(stderr=b"Error: No such container: absent", returncode=1)

        sandbox = self.sandbox(factory)
        with self.assertRaises(SandboxContractError):
            sandbox.execute(self.request(image_id="redis:latest"))
        with self.assertRaisesRegex(SandboxContractError, "declared_volumes"):
            sandbox.execute(self.request())

    def test_image_entrypoint_must_match_bound_exact_entrypoint(self):
        for entrypoint in (["/mailpit"], ["python", "-m"], "python"):
            with self.subTest(entrypoint=entrypoint):
                calls = []

                def factory(command, **kwargs):
                    calls.append((tuple(command), kwargs))
                    action = self.action(command)
                    if action[:2] == ("image", "inspect"):
                        return FakeProcess(
                            image_inspect(entrypoint=entrypoint)
                        )
                    return FakeProcess(
                        stderr=b"Error: No such container: absent",
                        returncode=1,
                    )

                with self.assertRaisesRegex(
                    SandboxContractError, "entrypoint_mismatch"
                ):
                    self.sandbox(factory).execute(
                        self.request(
                            mission_id=(
                                "mis_entry_" + str(len(repr(entrypoint)))
                            )
                        )
                    )
        calls = []
        receipt = self.sandbox(
            self.successful_factory(calls)
        ).execute(self.request(mission_id="mis_entry_null"))
        self.assertEqual(receipt.verdict, "PASS")

        matching_calls = []

        def matching_factory(command, **kwargs):
            matching_calls.append((tuple(command), kwargs))
            action = self.action(command)
            if action[:2] == ("image", "inspect"):
                return FakeProcess(image_inspect(entrypoint=["python"]))
            if action[:2] == ("container", "inspect"):
                return FakeProcess(
                    stderr=b"Error: No such container: absent",
                    returncode=1,
                )
            return FakeProcess()

        matching = self.sandbox(matching_factory).execute(
            self.request(mission_id="mis_entry_matching")
        )
        self.assertEqual(matching.verdict, "PASS")

    def test_image_os_must_be_explicit_linux(self):
        for payload in (
            image_inspect(operating_system="windows"),
            json.dumps([{"Id": IMAGE, "Config": {"Volumes": None}}]).encode(),
            json.dumps([{"Id": IMAGE, "Os": 7, "Config": {"Volumes": None}}]).encode(),
        ):
            with self.subTest(payload=payload):

                def factory(command, **_kwargs):
                    action = self.action(command)
                    if action[:2] == ("image", "inspect"):
                        return FakeProcess(payload)
                    return FakeProcess(
                        stderr=b"Error: No such container: absent", returncode=1
                    )

                with self.assertRaises((SandboxContractError, SandboxDockerError)):
                    self.sandbox(factory).execute(
                        self.request(mission_id=f"mis_os_{len(payload)}")
                    )

        def architecture_factory(command, **_kwargs):
            if self.action(command)[:2] == ("image", "inspect"):
                return FakeProcess(image_inspect(architecture="arm64"))
            return FakeProcess(stderr=b"No such container", returncode=1)

        with self.assertRaisesRegex(SandboxContractError, "architecture_mismatch"):
            self.sandbox(architecture_factory).execute(
                self.request(mission_id="mis_arch_mismatch")
            )

    def test_strict_request_types_all_raise_contract_error(self):
        sandbox = self.sandbox(lambda *_a, **_k: FakeProcess())
        malformed = (
            {"mission_id": 7},
            {"clone_root": Path(self.clone)},
            {"image_id": 7},
            {"argv": ["echo"]},
            {"argv": ("echo", 7)},
            {"timeout_seconds": True},
            {"timeout_seconds": float("nan")},
            {"timeout_seconds": float("inf")},
            {"max_output_bytes": True},
            {"max_output_bytes": 1.5},
        )
        for change in malformed:
            with self.subTest(change=change):
                with self.assertRaises(SandboxContractError):
                    sandbox.execute(self.request(**change))

    def test_clone_is_direct_child_and_identity_is_rechecked(self):
        outside = self.base / "outside"
        outside.mkdir()
        sandbox = self.sandbox(lambda *_a, **_k: FakeProcess())
        with self.assertRaisesRegex(SandboxContractError, "direct_child"):
            sandbox.execute(self.request(clone_root=str(outside)))

        calls = 0

        def resolver(value):
            nonlocal calls
            calls += 1
            return str(Path(value).resolve(strict=True))

        active = self.sandbox(
            lambda command, **_k: (
                FakeProcess(image_inspect())
                if self.action(command)[:2] == ("image", "inspect")
                else FakeProcess(stderr=b"No such container", returncode=1)
            ),
            path_resolver=resolver,
        )
        original_identity = __import__(
            "core.phase11_executable_sandbox_v1",
            fromlist=["_path_identity"],
        )._path_identity
        clone_checks = 0

        def changed_clone_identity(path):
            nonlocal clone_checks
            if Path(path) == self.clone:
                clone_checks += 1
                return (1, 2, 3, 4 + clone_checks)
            return original_identity(path)

        with patch(
            "core.phase11_executable_sandbox_v1._path_identity",
            side_effect=changed_clone_identity,
        ):
            with self.assertRaisesRegex(SandboxContractError, "identity_changed"):
                active.execute(self.request(mission_id="mis_identity"))
        self.assertGreaterEqual(calls, 5)

    def test_clone_manifest_detects_mutation_and_refuses_links_and_hardlinks(self):
        tracked = self.clone / "tracked.txt"
        tracked.write_text("before", encoding="utf-8")

        def mutating_factory(command, **_kwargs):
            action = self.action(command)
            if action[:2] == ("image", "inspect"):
                tracked.write_text("after", encoding="utf-8")
                return FakeProcess(image_inspect())
            return FakeProcess(stderr=b"No such container", returncode=1)

        with self.assertRaisesRegex(SandboxContractError, "manifest_changed"):
            self.sandbox(mutating_factory).execute(
                self.request(mission_id="mis_manifest_mutation")
            )

        tracked.write_text("stable", encoding="utf-8")
        hardlink = self.clone / "hardlink.txt"
        try:
            os.link(tracked, hardlink)
        except OSError:
            hardlink = None
        if hardlink is not None:
            with self.assertRaisesRegex(SandboxContractError, "hardlink_refused"):
                self.sandbox(lambda *_a, **_k: FakeProcess()).execute(
                    self.request(mission_id="mis_manifest_hardlink")
                )
            hardlink.unlink()

        symlink = self.clone / "symlink.txt"
        try:
            symlink.symlink_to(tracked)
        except OSError:
            return
        with self.assertRaisesRegex(SandboxContractError, "link_refused"):
            self.sandbox(lambda *_a, **_k: FakeProcess()).execute(
                self.request(mission_id="mis_manifest_symlink")
            )

    def test_manifest_is_slot_admitted_cancelled_deadlined_and_actual_byte_bounded(
        self,
    ):
        sandbox = self.sandbox(lambda *_a, **_k: FakeProcess())
        held = sandbox._acquire_slot("mis_admitted_first")
        try:
            with patch.object(
                sandbox,
                "_clone_manifest",
                side_effect=AssertionError("manifest must not run"),
            ):
                with self.assertRaises(SandboxCollisionError):
                    sandbox.execute(self.request(mission_id="mis_admitted_first"))
        finally:
            sandbox._release_slot("mis_admitted_first", held)

        cancelled = __import__("threading").Event()
        cancelled.set()
        with self.assertRaisesRegex(SandboxContractError, "manifest_cancelled"):
            sandbox.execute(
                self.request(mission_id="mis_manifest_cancel"), cancel=cancelled
            )
        self.assertFalse(sandbox._mission_lock_path("mis_manifest_cancel").exists())

        clock_value = 0.0

        def deadline_clock():
            nonlocal clock_value
            clock_value += 31.0
            return clock_value

        deadline = self.sandbox(lambda *_a, **_k: FakeProcess(), clock=deadline_clock)
        with self.assertRaisesRegex(SandboxContractError, "manifest_timeout"):
            deadline.execute(self.request(mission_id="mis_manifest_deadline"))
        self.assertFalse(deadline._mission_lock_path("mis_manifest_deadline").exists())

        content = self.clone / "bounded.bin"
        content.write_bytes(b"x")
        bounded = self.sandbox(lambda *_a, **_k: FakeProcess())
        with (
            patch("core.phase11_executable_sandbox_v1.MAX_CLONE_BYTES", 4),
            patch(
                "core.phase11_executable_sandbox_v1.os.read",
                return_value=b"12345",
            ),
        ):
            with self.assertRaisesRegex(SandboxContractError, "actual_byte_limit"):
                bounded.execute(self.request(mission_id="mis_manifest_actual_bytes"))

    def test_manifest_scandir_collection_stops_at_cap_and_checks_cancel(self):
        for index in range(3):
            (self.clone / f"entry-{index}.txt").write_text("x", encoding="ascii")
        original_entries = list(os.scandir(self.clone))

        class ControlledScandir:
            def __init__(self, *, cancel=None):
                self.index = 0
                self.cancel = cancel

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def __iter__(self):
                return self

            def __next__(self):
                if self.index >= len(original_entries):
                    raise StopIteration
                if self.index >= 3:
                    raise AssertionError("scandir advanced beyond bounded stop")
                entry = original_entries[self.index]
                self.index += 1
                if self.cancel is not None:
                    self.cancel.set()
                return entry

        capped_iterator = ControlledScandir()
        capped = self.sandbox(lambda *_a, **_k: FakeProcess())
        with (
            patch("core.phase11_executable_sandbox_v1.MAX_CLONE_ENTRIES", 2),
            patch(
                "core.phase11_executable_sandbox_v1.os.scandir",
                return_value=capped_iterator,
            ),
        ):
            with self.assertRaisesRegex(SandboxContractError, "entry_limit"):
                capped.execute(self.request(mission_id="mis_scandir_cap"))
        self.assertEqual(capped_iterator.index, 3)

        cancel = __import__("threading").Event()
        cancelled_iterator = ControlledScandir(cancel=cancel)
        cancelled = self.sandbox(lambda *_a, **_k: FakeProcess())
        with patch(
            "core.phase11_executable_sandbox_v1.os.scandir",
            return_value=cancelled_iterator,
        ):
            with self.assertRaisesRegex(SandboxContractError, "manifest_cancelled"):
                cancelled.execute(
                    self.request(mission_id="mis_scandir_cancel"),
                    cancel=cancel,
                )
        self.assertEqual(cancelled_iterator.index, 1)

    def test_output_hmacs_are_chunking_independent_and_keyed(self):
        def run_with_chunks(chunk_size, key):
            calls = []

            def factory(command, **kwargs):
                calls.append(command)
                action = self.action(command)
                if action[:2] == ("image", "inspect"):
                    return FakeProcess(image_inspect())
                if action[:2] == ("container", "inspect"):
                    return FakeProcess(stderr=b"No such container", returncode=1)
                process = FakeProcess()
                process.stdout = ChunkedStream(b"abcdef", chunk_size)
                process.stderr = ChunkedStream(b"uvwxyz", chunk_size)
                return process

            return self.sandbox(factory, signing_key=key).execute(
                self.request(mission_id=f"mis_chunk_{chunk_size}_{key[0]}")
            )

        first = run_with_chunks(1, SIGNING_KEY)
        second = run_with_chunks(5, SIGNING_KEY)
        self.assertEqual(first.stdout_hmac_sha256, second.stdout_hmac_sha256)
        self.assertEqual(first.stderr_hmac_sha256, second.stderr_hmac_sha256)
        other_key = run_with_chunks(1, b"z" * 32)
        self.assertNotEqual(first.stdout_hmac_sha256, other_key.stdout_hmac_sha256)
        self.assertNotEqual(first.argv_hmac_sha256, other_key.argv_hmac_sha256)

    def test_timeout_cleanup_verifies_owner_removes_by_id_and_proves_absence(self):
        calls = []
        owner = None
        inspect_count = 0

        def factory(command, **_kwargs):
            nonlocal owner, inspect_count
            calls.append(tuple(command))
            action = self.action(command)
            if action[:2] == ("image", "inspect"):
                return FakeProcess(image_inspect())
            if action[0] == "run":
                owner = command[command.index("--label") + 1].split("=", 1)[1]
                return FakeProcess(blocked=True)
            if action[:2] == ("container", "inspect"):
                inspect_count += 1
                if inspect_count == 1:
                    return FakeProcess(container_inspect(owner))
                return FakeProcess(stderr=b"No such container", returncode=1)
            if action[0] == "rm":
                return FakeProcess()
            raise AssertionError(action)

        receipt = self.sandbox(factory).execute(
            self.request(timeout_seconds=0.02, mission_id="mis_timeout")
        )
        self.assertEqual(receipt.verdict, "TIMEOUT")
        rm = next(command for command in calls if self.action(command)[0] == "rm")
        self.assertEqual(self.action(rm), ("rm", "--force", "--volumes", CONTAINER_ID))

    def test_cleanup_label_mismatch_never_deletes(self):
        calls = []

        def factory(command, **_kwargs):
            calls.append(tuple(command))
            action = self.action(command)
            if action[:2] == ("image", "inspect"):
                return FakeProcess(image_inspect())
            if action[0] == "run":
                return FakeProcess(blocked=True)
            if action[:2] == ("container", "inspect"):
                return FakeProcess(container_inspect("foreign-owner"))
            raise AssertionError(action)

        with self.assertRaisesRegex(SandboxCleanupError, "ownership_mismatch"):
            self.sandbox(factory).execute(
                self.request(timeout_seconds=0.02, mission_id="mis_mismatch")
            )
        self.assertFalse(any(self.action(command)[0] == "rm" for command in calls))

    def test_cleanup_failure_preserves_primary_as_explicit_cause(self):
        def factory(command, **_kwargs):
            action = self.action(command)
            if action[:2] == ("image", "inspect"):
                return FakeProcess(image_inspect())
            if action[0] == "run":
                raise OSError("primary")
            return FakeProcess(stderr=b"daemon unavailable", returncode=1)

        with self.assertRaises(SandboxCleanupError) as caught:
            self.sandbox(factory).execute(self.request(mission_id="mis_chain"))
        self.assertIsInstance(caught.exception.__cause__, SandboxDockerError)

    def test_hard_stop_terminate_kill_and_stuck(self):
        terminated = FakeProcess(blocked=True)
        ExecutableTestSandboxV1._stop_process(terminated)
        self.assertTrue(terminated.terminated)
        killed = FakeProcess(blocked=True)
        killed.terminate = lambda: None
        ExecutableTestSandboxV1._stop_process(killed)
        self.assertTrue(killed.killed)
        stuck = FakeProcess(stuck=True)
        with self.assertRaisesRegex(SandboxDockerError, "process_stuck"):
            ExecutableTestSandboxV1._stop_process(stuck)

    def test_in_process_cap_cross_process_lock_and_cleanup(self):
        sandbox = self.sandbox(lambda *_a, **_k: FakeProcess())
        lock = sandbox._mission_lock_path("mis_locked")
        lock.write_text("stale", encoding="ascii")
        with self.assertRaisesRegex(SandboxCollisionError, "cross_process"):
            sandbox.execute(self.request(mission_id="mis_locked"))
        lock.unlink()
        acquired = []
        try:
            for index in range(MAX_CONCURRENT_EXECUTIONS):
                acquired.append(
                    (
                        f"mis_cap_{index}",
                        sandbox._acquire_slot(f"mis_cap_{index}"),
                    )
                )
            with self.assertRaisesRegex(SandboxCollisionError, "concurrency_limit"):
                sandbox._acquire_slot("mis_over_cap")
        finally:
            for mission, path in acquired:
                sandbox._release_slot(mission, path)
        self.assertEqual(
            list((self.control / "phase11-mission-locks").glob("*.lock")), []
        )

    def test_os_held_global_slots_are_shared_across_instances(self):
        first = self.sandbox(lambda *_a, **_k: FakeProcess())
        second = self.sandbox(lambda *_a, **_k: FakeProcess())
        held = []
        try:
            for _index in range(MAX_CONCURRENT_EXECUTIONS):
                held.append(first._acquire_global_slot()[0])
            with self.assertRaisesRegex(SandboxCollisionError, "global_concurrency"):
                second._acquire_global_slot()
        finally:
            for stream in held:
                first._unlock_global(stream)
                stream.close()

    def test_unlock_failure_still_closes_stream_and_releases_process_slot(self):
        sandbox = self.sandbox(lambda *_a, **_k: FakeProcess())
        lease = sandbox._acquire_slot("mis_unlock_failure")
        with patch.object(
            sandbox,
            "_unlock_global",
            side_effect=OSError("forced unlock failure"),
        ):
            with self.assertRaisesRegex(OSError, "forced unlock"):
                sandbox._release_slot("mis_unlock_failure", lease)
        self.assertTrue(lease.slot_stream.closed)
        replacement = sandbox._acquire_slot("mis_unlock_failure")
        sandbox._release_slot("mis_unlock_failure", replacement)

    def test_public_release_failures_are_normalized_and_preserve_primary_cause(self):
        calls = []
        release_only = self.sandbox(self.successful_factory(calls))
        with patch.object(
            release_only,
            "_unlock_global",
            side_effect=OSError("release-only failure"),
        ):
            with self.assertRaises(SandboxCleanupError) as caught:
                release_only.execute(
                    self.request(mission_id="mis_release_only_failure")
                )
        self.assertIsInstance(caught.exception.__cause__, OSError)
        self.assertIn("release-only", str(caught.exception.__cause__))
        replacement = release_only._acquire_slot("mis_release_only_failure")
        release_only._release_slot("mis_release_only_failure", replacement)

        primary_and_release = self.sandbox(lambda *_a, **_k: FakeProcess())
        with (
            patch(
                "core.phase11_executable_sandbox_v1.secrets.token_hex",
                side_effect=OSError("primary token failure"),
            ),
            patch.object(
                primary_and_release,
                "_unlock_global",
                side_effect=OSError("secondary release failure"),
            ),
        ):
            with self.assertRaises(SandboxCleanupError) as caught:
                primary_and_release.execute(
                    self.request(mission_id="mis_primary_release_failure")
                )
        self.assertIsInstance(caught.exception.__cause__, OSError)
        self.assertIn("primary token", str(caught.exception.__cause__))
        replacement = primary_and_release._acquire_slot("mis_primary_release_failure")
        primary_and_release._release_slot("mis_primary_release_failure", replacement)

    def test_post_admission_token_and_clock_failures_release_all_slots(self):
        sandbox = self.sandbox(lambda *_a, **_k: FakeProcess())
        for source, target in (
            (
                "token",
                "core.phase11_executable_sandbox_v1.secrets.token_hex",
            ),
            ("clock", None),
        ):
            with self.subTest(source=source):
                mission = f"mis_post_admission_{source}"
                if target is not None:
                    context = patch(target, side_effect=OSError("token failed"))
                else:
                    context = patch.object(
                        sandbox, "_clock", side_effect=OSError("clock failed")
                    )
                with context:
                    with self.assertRaisesRegex(OSError, "failed"):
                        sandbox.execute(self.request(mission_id=mission))
                self.assertFalse(sandbox._mission_lock_path(mission).exists())
                replacement = sandbox._acquire_slot(mission)
                sandbox._release_slot(mission, replacement)

    @unittest.skipIf(os.name == "nt", "POSIX ownership boundary")
    def test_posix_permissive_clone_descendant_is_refused(self):
        target = self.clone / "world-writable.txt"
        target.write_text("data", encoding="ascii")
        target.chmod(0o666)
        with self.assertRaisesRegex(SandboxContractError, "permissions_invalid"):
            self.sandbox(lambda *_a, **_k: FakeProcess()).execute(
                self.request(mission_id="mis_posix_permissions")
            )

    @unittest.skipUnless(os.name == "nt", "Windows LOCALAPPDATA boundary")
    def test_windows_trusted_roots_outside_localappdata_are_refused(self):
        outside = Path("C:/MAAX_Assistant")
        if not outside.is_dir():
            self.skipTest("outside test root unavailable")
        with self.assertRaisesRegex(SandboxContractError, "outside_localappdata"):
            ExecutableTestSandboxV1(
                docker_cli=str(self.docker),
                docker_host=DOCKER_HOST,
                container_platform="linux/amd64",
                control_root=str(outside),
                clone_parent=str(self.clone_parent),
                signing_key=SIGNING_KEY,
                enabled=True,
            )

    @unittest.skipUnless(os.name == "nt", "Windows DACL boundary")
    def test_windows_permissive_localappdata_subdir_is_refused(self):
        ntsecuritycon: Any = importlib.import_module("ntsecuritycon")
        win32security: Any = importlib.import_module("win32security")

        permissive = self.base / "permissive-control"
        permissive.mkdir()
        security = win32security.GetNamedSecurityInfo(
            str(permissive),
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
        )
        dacl = security.GetSecurityDescriptorDacl()
        everyone = win32security.ConvertStringSidToSid("S-1-1-0")
        dacl.AddAccessAllowedAceEx(
            win32security.ACL_REVISION_DS,
            0,
            ntsecuritycon.FILE_GENERIC_WRITE,
            everyone,
        )
        win32security.SetNamedSecurityInfo(
            str(permissive),
            win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION,
            None,
            None,
            dacl,
            None,
        )
        with self.assertRaisesRegex(SandboxContractError, "foreign_write"):
            ExecutableTestSandboxV1(
                docker_cli=str(self.docker),
                docker_host=DOCKER_HOST,
                container_platform="linux/amd64",
                control_root=str(permissive),
                clone_parent=str(self.clone_parent),
                signing_key=SIGNING_KEY,
                enabled=True,
            )

    @unittest.skipUnless(os.name == "nt", "Windows descendant DACL boundary")
    def test_windows_permissive_clone_descendants_are_refused(self):
        ntsecuritycon: Any = importlib.import_module("ntsecuritycon")
        win32security: Any = importlib.import_module("win32security")

        def grant_foreign_write(path):
            security = win32security.GetNamedSecurityInfo(
                str(path),
                win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION,
            )
            dacl = security.GetSecurityDescriptorDacl()
            dacl.AddAccessAllowedAceEx(
                win32security.ACL_REVISION_DS,
                0,
                ntsecuritycon.FILE_GENERIC_WRITE,
                win32security.ConvertStringSidToSid("S-1-1-0"),
            )
            win32security.SetNamedSecurityInfo(
                str(path),
                win32security.SE_FILE_OBJECT,
                win32security.DACL_SECURITY_INFORMATION,
                None,
                None,
                dacl,
                None,
            )

        for kind in ("file", "directory"):
            with self.subTest(kind=kind):
                target = self.clone / f"permissive-{kind}"
                if kind == "file":
                    target.write_text("data", encoding="ascii")
                else:
                    target.mkdir()
                grant_foreign_write(target)
                with self.assertRaisesRegex(SandboxContractError, "foreign_write"):
                    self.sandbox(lambda *_a, **_k: FakeProcess()).execute(
                        self.request(mission_id=f"mis_foreign_{kind}")
                    )
                if kind == "file":
                    target.unlink()
                else:
                    target.rmdir()

    @unittest.skipUnless(os.name == "nt", "Windows ACE parser boundary")
    def test_windows_unsupported_allow_aces_fail_closed_and_object_sid_is_final(self):
        ntsecuritycon: Any = importlib.import_module("ntsecuritycon")
        win32security: Any = importlib.import_module("win32security")
        real_security = win32security.GetNamedSecurityInfo(
            str(self.control),
            win32security.SE_FILE_OBJECT,
            win32security.OWNER_SECURITY_INFORMATION
            | win32security.DACL_SECURITY_INFORMATION,
        )
        owner = real_security.GetSecurityDescriptorOwner()
        foreign = win32security.ConvertStringSidToSid("S-1-1-0")

        class FakeDacl:
            def __init__(self, ace):
                self.ace = ace

            def GetAceCount(self):
                return 1

            def GetAce(self, _index):
                return self.ace

        class FakeSecurity:
            def __init__(self, ace):
                self.dacl = FakeDacl(ace)

            def GetSecurityDescriptorOwner(self):
                return owner

            def GetSecurityDescriptorDacl(self):
                return self.dacl

        for ace, expected in (
            (((4, 0), ntsecuritycon.FILE_GENERIC_WRITE, foreign), "unsupported_ace"),
            (
                (
                    (win32security.ACCESS_ALLOWED_OBJECT_ACE_TYPE, 0),
                    ntsecuritycon.FILE_GENERIC_WRITE,
                    None,
                    None,
                    foreign,
                ),
                "foreign_write",
            ),
        ):
            with self.subTest(expected=expected):
                with patch.object(
                    win32security,
                    "GetNamedSecurityInfo",
                    return_value=FakeSecurity(ace),
                ):
                    with self.assertRaisesRegex(SandboxContractError, expected):
                        self.sandbox(lambda *_a, **_k: FakeProcess())

    def test_new_lock_is_rolled_back_on_write_or_close_failure(self):
        sandbox = self.sandbox(lambda *_a, **_k: FakeProcess())
        for failure in ("write", "close"):
            with self.subTest(failure=failure):
                mission = f"mis_lock_{failure}"
                lock_path = sandbox._mission_lock_path(mission)
                if failure == "write":
                    context = patch(
                        "core.phase11_executable_sandbox_v1.os.write",
                        side_effect=OSError("write failed"),
                    )
                else:
                    original_close = os.close
                    close_calls = 0

                    def fail_close_once(descriptor):
                        nonlocal close_calls
                        close_calls += 1
                        if close_calls == 1:
                            raise OSError("close failed")
                        return original_close(descriptor)

                    context = patch(
                        "core.phase11_executable_sandbox_v1.os.close",
                        side_effect=fail_close_once,
                    )
                with context:
                    with self.assertRaisesRegex(
                        SandboxContractError, "mission_lock_failed"
                    ):
                        sandbox._acquire_slot(mission)
                self.assertFalse(lock_path.exists())
                acquired = sandbox._acquire_slot(mission)
                sandbox._release_slot(mission, acquired)

        foreign_mission = "mis_foreign_lock"
        foreign = sandbox._mission_lock_path(foreign_mission)
        foreign.write_text("FOREIGN", encoding="ascii")
        with self.assertRaises(SandboxCollisionError):
            sandbox._acquire_slot(foreign_mission)
        self.assertEqual(foreign.read_text(encoding="ascii"), "FOREIGN")
        foreign.unlink()


def re_escape(value: str) -> str:
    import re

    return re.escape(value)


@unittest.skipUnless(
    os.environ.get("ONYX_PHASE11_DOCKER_SMOKE") == "1",
    "set ONYX_PHASE11_DOCKER_SMOKE=1 for already-local Docker smoke tests",
)
class ExecutableSandboxDockerSmokeTests(unittest.TestCase):
    REDIS_WITH_VOLUME = (
        "sha256:6ab0b6e7381779332f97b8ca76193e45b0756f38d4c0dcda72dbb3c32061ab99"
    )
    MAILPIT_NO_VOLUME = (
        "sha256:37a38e48e9338cd7e89dfeb487f37b02ebfcd9cb23111bed2d345e79d37d6dd6"
    )

    def setUp(self) -> None:
        import shutil

        docker = shutil.which("docker")
        if not docker:
            self.skipTest("Docker CLI unavailable")
        self.docker = str(Path(docker).resolve())
        self.host = (
            "npipe:////./pipe/docker_engine"
            if os.name == "nt"
            else "unix:///var/run/docker.sock"
        )

    def test_local_redis_is_rejected_for_declared_data_volume(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            clone_parent = base / "clones"
            clone_parent.mkdir()
            secure_windows_directory(clone_parent)
            clone = clone_parent / "redis"
            clone.mkdir()
            control = base / "control"
            control.mkdir()
            secure_windows_directory(control)
            sandbox = ExecutableTestSandboxV1(
                docker_cli=self.docker,
                docker_host=self.host,
                container_platform="linux/amd64",
                control_root=str(control),
                clone_parent=str(clone_parent),
                signing_key=SIGNING_KEY,
                enabled=True,
            )
            with self.assertRaisesRegex(SandboxContractError, "declared_volumes"):
                sandbox.execute(
                    ExecutableSandboxRequestV1(
                        mission_id="mis_optional_redis_rejection",
                        execution_id="e" * 64,
                        clone_root=str(clone),
                        image_id=self.REDIS_WITH_VOLUME,
                        # Validation must permit the request far enough to prove
                        # that the pinned image's declared volume is refused.
                        argv=("pytest",),
                    )
                )

    def test_already_local_no_volume_image_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            clone_parent = base / "clones"
            clone_parent.mkdir()
            secure_windows_directory(clone_parent)
            clone = clone_parent / "mailpit"
            clone.mkdir()
            control = base / "control"
            control.mkdir()
            secure_windows_directory(control)
            receipt = ExecutableTestSandboxV1(
                docker_cli=self.docker,
                docker_host=self.host,
                container_platform="linux/amd64",
                control_root=str(control),
                clone_parent=str(clone_parent),
                signing_key=SIGNING_KEY,
                enabled=True,
            ).execute(
                ExecutableSandboxRequestV1(
                    mission_id="mis_optional_mailpit_smoke",
                    execution_id="e" * 64,
                    clone_root=str(clone),
                    image_id=self.MAILPIT_NO_VOLUME,
                    # Mailpit declares /mailpit as its exact image entrypoint;
                    # the sandbox binds that executable explicitly.
                    argv=("/mailpit", "version", "--no-release-check"),
                )
            )
        self.assertEqual(receipt.verdict, "PASS")
