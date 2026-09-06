from __future__ import annotations

import hashlib
import hmac
import io
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Mapping

from core.phase11_executable_sandbox_v1 import (
    SCHEMA as SANDBOX_SCHEMA,
    ExecutableSandboxHostV1,
    ExecutableSandboxReceiptV1,
    OWNER_LABEL,
    SandboxContractError,
    SandboxDockerError,
    verify_executable_sandbox_receipt_v1,
)
from core.phase11_execution_ledger_v1 import Phase11ExecutionLedgerV1
from core.phase11_project_autopilot_v1 import (
    AutopilotEnvelopeV1,
    ExecutableGateEnvelopeV1,
    ExecutableGatePlanV1,
    IndependentAutopilotVerifierV1,
    ProjectAutopilotContractError,
    ProjectAutopilotV1,
    derive_executable_sandbox_subkey_v1,
)


PATCH = """diff --git a/demo.txt b/demo.txt
--- a/demo.txt
+++ b/demo.txt
@@ -1 +1 @@
-before
+after
"""
IMAGE_ID = "sha256:" + "1" * 64


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def _keyed(key: bytes, domain: bytes, value: bytes) -> str:
    return hmac.new(key, domain + b"\0" + value, hashlib.sha256).hexdigest()


def _sandbox_receipt(
    *,
    key: bytes,
    request: object,
    verdict: str,
) -> ExecutableSandboxReceiptV1:
    mission_id = str(getattr(request, "mission_id"))
    image_id = str(getattr(request, "image_id"))
    argv = getattr(request, "argv")
    receipt = ExecutableSandboxReceiptV1(
        schema=SANDBOX_SCHEMA,
        execution_id=str(getattr(request, "execution_id")),
        attempt=int(getattr(request, "attempt", 1)),
        mission_hmac_sha256=_keyed(key, b"mission", mission_id.encode("utf-8")),
        image_sha256=image_id.removeprefix("sha256:"),
        argv_hmac_sha256=_keyed(key, b"argv", _canonical(argv)),
        prelaunch_clone_manifest_hmac_sha256="2" * 64,
        stdout_hmac_sha256="3" * 64,
        stderr_hmac_sha256="4" * 64,
        stdout_bytes=0,
        stderr_bytes=0,
        exit_code=0 if verdict == "PASS" else 1,
        duration_ms=1,
        verdict=verdict,
        receipt_hmac_sha256="",
    )
    signature = _keyed(
        key,
        b"receipt",
        _canonical({**asdict(receipt), "receipt_hmac_sha256": ""}),
    )
    return replace(receipt, receipt_hmac_sha256=signature)


class _MemoryVault:
    def __init__(self) -> None:
        self.value: bytes | None = None

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, value: bytes | bytearray) -> None:
        self.value = bytes(value)


class _FakeProcess:
    def __init__(
        self,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        *,
        blocked: bool = False,
    ) -> None:
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.returncode = None if blocked else returncode
        self._final = returncode
        self._blocked = blocked
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self._blocked and not (self.terminated or self.killed):
            raise subprocess.TimeoutExpired(["docker"], timeout)
        self.returncode = -9 if self.killed else (-15 if self.terminated else self._final)
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9


class _Factory:
    def __init__(self, verdicts: list[str], events: list[str]) -> None:
        self.verdicts = verdicts
        self.events = events
        self.calls: list[tuple[tuple[str, ...], dict[str, object]]] = []
        self.run_calls = 0
        self._cancel_active = False

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_active

    def __call__(self, command, **options):
        normalized = tuple(command)
        self.calls.append((normalized, dict(options)))
        action = normalized[3:]
        verdict = self.verdicts[0] if self.verdicts else "PASS"
        if action[:2] == ("image", "inspect"):
            if verdict == "PRELAUNCH_CANCEL":
                self.verdicts.pop(0)
                raise SandboxContractError("sandbox_clone_manifest_cancelled")
            if verdict == "PRELAUNCH_DEADLINE":
                self.verdicts.pop(0)
                raise SandboxContractError("sandbox_clone_manifest_timeout")
            payload = [{
                "Id": IMAGE_ID,
                "Os": "linux",
                "Architecture": "amd64",
                "Config": {"Volumes": None, "Entrypoint": None},
            }]
            return _FakeProcess(json.dumps(payload).encode("utf-8"))
        if action[:2] == ("container", "inspect"):
            return _FakeProcess(
                stderr=b"Error: No such container: absent", returncode=1
            )
        if action and action[0] == "run":
            self.run_calls += 1
            verdict = self.verdicts.pop(0)
            entrypoint = action[action.index("--entrypoint") + 1]
            self.events.append(f"execute:{entrypoint}")
            if verdict == "ERROR":
                raise SandboxDockerError("simulated_unavailable")
            if verdict == "PASS_DRIFT":
                mount = action[action.index("--mount") + 1]
                source = mount.split("source=", 1)[1].split(",target=", 1)[0]
                (Path(source) / "demo.txt").write_bytes(b"drifted\n")
                verdict = "PASS"
            if verdict in {"TIMEOUT", "CANCELLED"}:
                self._cancel_active = verdict == "CANCELLED"
                return _FakeProcess(blocked=True)
            return _FakeProcess(returncode=0 if verdict == "PASS" else 1)
        owner = ""
        if action and action[0] == "container" and "--filter" in action:
            owner = action[action.index("--filter") + 1].removeprefix(
                f"label={OWNER_LABEL}="
            )
        return _FakeProcess(json.dumps([{"Config": {"Labels": {OWNER_LABEL: owner}}}]).encode())


class ProjectAutopilotExecutableV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.repo = base / "owner"
        self.repo.mkdir()
        _git(self.repo, "init")
        _git(self.repo, "config", "user.name", "Onyx Test")
        _git(self.repo, "config", "user.email", "onyx@example.invalid")
        (self.repo / "demo.txt").write_bytes(b"before\n")
        _git(self.repo, "add", "demo.txt")
        _git(self.repo, "commit", "-m", "base")
        self.head = _git(self.repo, "rev-parse", "HEAD").lower()
        self.control = base / "control"
        self.vaults: dict[str, _MemoryVault] = {}
        self.vault_factory = lambda reference: self.vaults.setdefault(
            reference.account, _MemoryVault()
        )
        self.key = b"e" * 32
        self.ledger_boundaries: list[object] = []

    def tearDown(self) -> None:
        for boundary in self.ledger_boundaries:
            boundary.close()
        self.temporary.cleanup()

    def _official_ledger(self) -> Phase11ExecutionLedgerV1:
        ledger_root = Path(self.temporary.name) / "execution-ledger"
        if sys.platform == "win32":
            from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1

            boundary = WindowsTrustedDirectoryV1(root=ledger_root, enabled=True)
        else:
            from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1

            boundary = PosixTrustedDirectoryV1(root=ledger_root, enabled=True)
        self.ledger_boundaries.append(boundary)
        return Phase11ExecutionLedgerV1(
            host_secret=b"official-ledger-host-key" * 2,
            trusted_directory=boundary,
            receipt_signing_key=derive_executable_sandbox_subkey_v1(self.key),
            receipt_verifier=verify_executable_sandbox_receipt_v1,
            enabled=True,
        )

    def test_execution_ledger_requires_exact_official_enabled_type(self) -> None:
        with self.assertRaisesRegex(
            ProjectAutopilotContractError,
            "execution_ledger_binding_invalid",
        ):
            ProjectAutopilotV1(
                worktree_root=self.control,
                signing_key=self.key,
                execution_ledger=object(),  # type: ignore[arg-type]
            )

        ledger = self._official_ledger()
        engine = ProjectAutopilotV1(
            worktree_root=self.control,
            signing_key=self.key,
            execution_ledger=ledger,
            require_execution_ledger=True,
        )
        self.assertIs(engine._validated_execution_ledger(), ledger)

    def _engine(
        self,
        *,
        factory: Any | None,
        executable_enabled: bool = True,
    ) -> ProjectAutopilotV1:
        host = None
        if factory is not None:
            host = ExecutableSandboxHostV1(
                docker_cli=str(Path(sys.executable).resolve()),
                docker_host="npipe:////./pipe/onyx-autopilot-test",
                process_factory=factory,
            )
        return ProjectAutopilotV1(
            worktree_root=self.control,
            signing_key=self.key,
            enabled=True,
            checkpoint_vault_factory=self.vault_factory,
            executable_sandbox_enabled=executable_enabled,
            executable_sandbox_host=host,
            approved_executable_image_ids=(IMAGE_ID,),
        )

    def _envelope(self, engine: ProjectAutopilotV1) -> AutopilotEnvelopeV1:
        return AutopilotEnvelopeV1.build(
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
            max_output_bytes=512_000,
        )

    @staticmethod
    def _plan(*commands: str) -> ExecutableGatePlanV1:
        return ExecutableGatePlanV1.build(
            image_id=IMAGE_ID,
            platform="linux/amd64",
            gates=[
                {
                    "argv": (command,),
                    "timeout_seconds": 1,
                    "max_output_bytes": 10_000,
                }
                for command in commands
            ],
            approved_image_ids=(IMAGE_ID,),
        )

    def _authorized(
        self,
        engine: ProjectAutopilotV1,
        primary: AutopilotEnvelopeV1,
        binding_digest: str,
        *commands: str,
    ) -> ExecutableGateEnvelopeV1:
        return ExecutableGateEnvelopeV1.build(
            image_id=IMAGE_ID,
            platform="linux/amd64",
            gates=[
                {
                    "argv": (command,),
                    "timeout_seconds": 1,
                    "max_output_bytes": 10_000,
                }
                for command in commands
            ],
            approved_image_ids=(IMAGE_ID,),
            mission_id="mis_" + binding_digest[:32],
            gate_index=0,
            primary_envelope=primary,
            binding_digest=binding_digest,
            signing_key=engine._key,
        )

    def test_plan_is_separate_strict_and_default_off(self) -> None:
        with self.assertRaisesRegex(
            ProjectAutopilotContractError, "image_not_approved"
        ):
            ExecutableGatePlanV1.build(
                image_id="sha256:" + "f" * 64,
                platform="linux/amd64",
                gates=[
                    {
                        "argv": ("pytest",),
                        "timeout_seconds": 20,
                        "max_output_bytes": 10_000,
                    }
                ],
                approved_image_ids=(IMAGE_ID,),
            )
        with self.assertRaisesRegex(ProjectAutopilotContractError, "shell_refused"):
            ExecutableGatePlanV1.build(
                image_id=IMAGE_ID,
                platform="linux/amd64",
                gates=[
                    {
                        "argv": ("sh", "-c", "pytest"),
                        "timeout_seconds": 20,
                        "max_output_bytes": 10_000,
                    }
                ],
                approved_image_ids=(IMAGE_ID,),
            )
        refused_commands = (
            (("env", "sh", "-c", "pytest"), "shell_refused"),
            (("python", "-c", "print('dynamic')"), "inline_code_refused"),
            (("python", "-m", "pip", "install", "x"), "module_refused"),
            (("node", "-e", "process.exit(0)"), "inline_code_refused"),
            (
                ("pytest", "--api-key=sk-example-secret-value"),
                "secret_shaped_argument_refused",
            ),
        )
        for argv, reason in refused_commands:
            with self.subTest(argv=argv):
                with self.assertRaisesRegex(
                    ProjectAutopilotContractError, reason
                ):
                    ExecutableGatePlanV1.build(
                        image_id=IMAGE_ID,
                        platform="linux/amd64",
                        gates=[
                            {
                                "argv": argv,
                                "timeout_seconds": 20,
                                "max_output_bytes": 10_000,
                            }
                        ],
                        approved_image_ids=(IMAGE_ID,),
                    )
        engine = self._engine(factory=None, executable_enabled=False)
        with self.assertRaisesRegex(
            ProjectAutopilotContractError, "authorized_envelope_required"
        ):
            primary = self._envelope(engine)
            engine.execute(
                mission_id="mis_" + "1" * 32,
                binding_digest="1" * 64,
                envelope=primary,
                patch=PATCH,
                cancel=lambda: False,
                executable_plan=self._plan("pytest"),
            )
        primary = self._envelope(engine)
        authorized = self._authorized(engine, primary, "1" * 64, "pytest")
        with self.assertRaisesRegex(
            ProjectAutopilotContractError, "not_explicitly_enabled"
        ):
            engine.execute(
                mission_id="mis_" + "1" * 32,
                binding_digest="1" * 64,
                envelope=primary,
                patch=PATCH,
                cancel=lambda: False,
                executable_plan=authorized,
            )
        with self.assertRaisesRegex(ProjectAutopilotContractError, "envelope_invalid"):
            engine._normalize_executable_plan(
                authorized,
                mission_id="mis_" + "1" * 32,
                primary_envelope=primary,
                binding_digest="a" * 64,
            )
        substituted = replace(authorized, plan=self._plan("ruff"))
        with self.assertRaisesRegex(ProjectAutopilotContractError, "envelope_invalid"):
            engine._normalize_executable_plan(
                substituted,
                mission_id="mis_" + "1" * 32,
                primary_envelope=primary,
                binding_digest="1" * 64,
            )
        for replayed in (
            replace(authorized, mission_id="mis_" + "f" * 32),
            replace(authorized, gate_index=1),
        ):
            with self.assertRaisesRegex(
                ProjectAutopilotContractError, "envelope_invalid"
            ):
                engine._normalize_executable_plan(
                    replayed,
                    mission_id="mis_" + "1" * 32,
                    primary_envelope=primary,
                    binding_digest="1" * 64,
                )

    def test_legacy_path_keeps_executable_extension_absent(self) -> None:
        engine = self._engine(factory=None, executable_enabled=False)
        mission_id = "mis_" + "9" * 32
        outcome = engine.execute(
            mission_id=mission_id,
            binding_digest="9" * 64,
            envelope=self._envelope(engine),
            patch=PATCH,
            cancel=lambda: False,
        )
        self.assertEqual(outcome["status"], "succeeded", outcome)
        self.assertFalse(outcome["data"]["repository_code_executed"])
        self.assertNotIn("executable_gates_passed", outcome["data"])
        checkpoint = engine.checkpoint_status(mission_id)
        assert checkpoint is not None
        self.assertTrue(
            {
                "executable_plan_digest",
                "executable_gate_index",
                "executable_gate_receipts",
            }.isdisjoint(checkpoint)
        )

    def test_official_host_execution_follows_static_verification(self) -> None:
        events: list[str] = []
        factory = _Factory(["PASS"], events)
        engine = self._engine(factory=factory)
        original_static_gate = engine._static_gate

        def ordered_static_gate(*arguments: Any, **kwargs: Any) -> dict[str, Any]:
            events.append("static")
            return original_static_gate(*arguments, **kwargs)

        engine._static_gate = ordered_static_gate  # type: ignore[method-assign]
        mission_id = "mis_" + "2" * 32
        binding = "2" * 64
        primary = self._envelope(engine)
        outcome = engine.execute(
            mission_id=mission_id,
            binding_digest=binding,
            envelope=primary,
            patch=PATCH,
            cancel=lambda: False,
            executable_plan=self._authorized(engine, primary, binding, "pytest"),
        )
        self.assertEqual(outcome["status"], "succeeded", outcome)
        self.assertTrue(outcome["data"]["repository_code_executed"])
        self.assertEqual(events, ["static", "execute:pytest"])
        self.assertEqual(factory.run_calls, 1)
        self.assertTrue(factory.calls)
        self.assertTrue(
            all("signing_key" not in options for _command, options in factory.calls)
        )
        checkpoint = engine.checkpoint_status(mission_id)
        assert checkpoint is not None
        self.assertEqual(checkpoint["stage"], "verified")
        self.assertEqual(checkpoint["executable_gate_index"], 1)
        self.assertEqual(len(checkpoint["executable_gate_receipts"]), 1)

    def test_checkpoint_resume_and_receipt_tamper_detection(self) -> None:
        events: list[str] = []
        factory = _Factory(["PASS", "PRELAUNCH_CANCEL", "PASS"], events)
        engine = self._engine(factory=factory)
        raw_plan = self._plan("pytest", "ruff")
        mission_id = "mis_" + "3" * 32
        binding = "3" * 64
        primary = self._envelope(engine)
        plan = self._authorized(engine, primary, binding, "pytest", "ruff")
        arguments = {
            "mission_id": mission_id,
            "binding_digest": binding,
            "envelope": primary,
            "patch": PATCH,
            "cancel": lambda: False,
            "executable_plan": plan,
        }
        waiting = engine.execute(**arguments)
        self.assertEqual(waiting["status"], "waiting", waiting)
        self.assertEqual(waiting["waiting_for"], "kill_requested")
        self.assertTrue(waiting["data"]["repository_code_executed"])
        checkpoint = engine.checkpoint_status(mission_id)
        assert checkpoint is not None
        self.assertEqual(checkpoint["executable_gate_index"], 1)
        self.assertEqual(len(checkpoint["executable_gate_receipts"]), 1)

        resumed = engine.execute(**arguments)
        self.assertEqual(resumed["status"], "succeeded", resumed)
        self.assertEqual(
            events,
            ["execute:pytest", "execute:ruff"],
            # The first ruff attempt was cancelled before Docker launch, so
            # resumption performs the only dispatch for that gate.
        )
        verified = IndependentAutopilotVerifierV1(engine)._verify_executable_locked(
            mission_id=mission_id,
            binding_digest=binding,
            primary_input_digest=primary.input_digest,
            plan=raw_plan,
        )
        self.assertEqual(len(verified), 2)
        tampered = dict(verified[0])
        tampered["verdict"] = "FAIL"
        with self.assertRaisesRegex(ProjectAutopilotContractError, "receipt_invalid"):
            engine._verify_executable_receipt(
                mission_id=mission_id,
                binding_digest=binding,
                primary_input_digest=primary.input_digest,
                plan=raw_plan,
                index=0,
                receipt=tampered,
            )

    def test_non_pass_verdicts_wait_and_pre_execution_cancel_is_truthful(self) -> None:
        expected = {
            "FAIL": ("executable_gate_failed", True, "executed_receipt"),
            "TIMEOUT": ("executable_gate_timeout", True, "executed_receipt"),
            "CANCELLED": ("kill_requested", True, "executed_receipt"),
            "ERROR": (
                "executable_gate_reconciliation_required",
                True,
                "attempted_unknown",
            ),
            "PRELAUNCH_CANCEL": (
                "kill_requested",
                False,
                "not_started",
            ),
            "PRELAUNCH_DEADLINE": (
                "mission_time_budget_exhausted",
                False,
                "not_started",
            ),
        }
        for offset, (verdict, expected_result) in enumerate(expected.items(), start=4):
            with self.subTest(verdict=verdict):
                reason, executed, execution_state = expected_result
                factory = _Factory(
                    [verdict, "PASS"]
                    if verdict in {"PRELAUNCH_CANCEL", "PRELAUNCH_DEADLINE"}
                    else [verdict],
                    [],
                )
                engine = self._engine(factory=factory)
                binding = str(offset) * 64
                primary = self._envelope(engine)
                authorized = self._authorized(engine, primary, binding, "pytest")
                outcome = engine.execute(
                    mission_id="mis_" + str(offset) * 32,
                    binding_digest=binding,
                    envelope=primary,
                    patch=PATCH,
                    cancel=(
                        (lambda: factory.cancel_requested)
                        if verdict == "CANCELLED"
                        else (lambda: False)
                    ),
                    executable_plan=authorized,
                )
                self.assertEqual(outcome["status"], "waiting", outcome)
                self.assertEqual(outcome["waiting_for"], reason)
                self.assertIs(outcome["data"]["repository_code_executed"], executed)
                self.assertEqual(
                    outcome["data"]["repository_code_execution_state"],
                    execution_state,
                )
                before = list(factory.events)
                repeated = engine.execute(
                    mission_id="mis_" + str(offset) * 32,
                    binding_digest=binding,
                    envelope=primary,
                    patch=PATCH,
                    cancel=lambda: False,
                    executable_plan=authorized,
                )
                if verdict in {
                    "PRELAUNCH_CANCEL",
                    "PRELAUNCH_DEADLINE",
                }:
                    self.assertEqual(repeated["status"], "succeeded")
                    self.assertEqual(len(factory.events), len(before) + 1)
                else:
                    self.assertEqual(repeated["status"], "waiting")
                    self.assertEqual(factory.events, before)

        factory = _Factory(["PASS"], [])
        engine = self._engine(factory=factory)
        binding = "a" * 64
        primary = self._envelope(engine)
        cancelled = engine.execute(
            mission_id="mis_" + "a" * 32,
            binding_digest=binding,
            envelope=primary,
            patch=PATCH,
            cancel=lambda: True,
            executable_plan=self._authorized(engine, primary, binding, "pytest"),
        )
        self.assertEqual(cancelled["status"], "waiting", cancelled)
        self.assertEqual(cancelled["waiting_for"], "kill_requested")
        self.assertFalse(cancelled["data"]["repository_code_executed"])
        self.assertEqual(factory.run_calls, 0)

    def test_intent_write_failure_never_dispatches(self) -> None:
        events: list[str] = []
        factory = _Factory(["PASS"], events)
        engine = self._engine(factory=factory)
        binding = "b" * 64
        primary = self._envelope(engine)
        authorized = self._authorized(engine, primary, binding, "pytest")
        original_write = engine._write_checkpoint

        def fail_intent(mission_id: str, payload: Mapping[str, Any]) -> None:
            if payload.get("stage") == "executable_gate_pending":
                raise ProjectAutopilotContractError("simulated_intent_write_failure")
            original_write(mission_id, payload)

        engine._write_checkpoint = fail_intent  # type: ignore[method-assign]
        with self.assertRaisesRegex(
            ProjectAutopilotContractError, "intent_write_failure"
        ):
            engine.execute(
                mission_id="mis_" + "b" * 32,
                binding_digest=binding,
                envelope=primary,
                patch=PATCH,
                cancel=lambda: False,
                executable_plan=authorized,
            )
        self.assertEqual(events, [])

    def test_outcome_write_failure_leaves_intent_and_never_reexecutes(
        self,
    ) -> None:
        events: list[str] = []
        factory = _Factory(["PASS"], events)
        engine = self._engine(factory=factory)
        binding = "e" * 64
        primary = self._envelope(engine)
        authorized = self._authorized(engine, primary, binding, "pytest")
        original_write = engine._write_checkpoint

        def fail_outcome(mission_id: str, payload: Mapping[str, Any]) -> None:
            if payload.get("stage") == "executable_gates_running":
                raise ProjectAutopilotContractError("simulated_outcome_write_failure")
            original_write(mission_id, payload)

        engine._write_checkpoint = fail_outcome  # type: ignore[method-assign]
        with self.assertRaisesRegex(
            ProjectAutopilotContractError, "outcome_write_failure"
        ):
            engine.execute(
                mission_id="mis_" + "e" * 32,
                binding_digest=binding,
                envelope=primary,
                patch=PATCH,
                cancel=lambda: False,
                executable_plan=authorized,
            )
        self.assertEqual(events, ["execute:pytest"])
        engine._write_checkpoint = original_write  # type: ignore[method-assign]
        resumed = engine.execute(
            mission_id="mis_" + "e" * 32,
            binding_digest=binding,
            envelope=primary,
            patch=PATCH,
            cancel=lambda: False,
            executable_plan=authorized,
        )
        self.assertEqual(resumed["status"], "waiting")
        self.assertEqual(
            resumed["waiting_for"],
            "executable_gate_reconciliation_required",
        )
        self.assertEqual(events, ["execute:pytest"])

    def test_identical_argv_has_unique_execution_ids_and_no_replay(self) -> None:
        factory = _Factory(["PASS", "PASS"], [])
        engine = self._engine(factory=factory)
        binding = "c" * 64
        primary = self._envelope(engine)
        raw_plan = self._plan("pytest", "pytest")
        outcome = engine.execute(
            mission_id="mis_" + "c" * 32,
            binding_digest=binding,
            envelope=primary,
            patch=PATCH,
            cancel=lambda: False,
            executable_plan=self._authorized(
                engine, primary, binding, "pytest", "pytest"
            ),
        )
        self.assertEqual(outcome["status"], "succeeded", outcome)
        checkpoint = engine.checkpoint_status("mis_" + "c" * 32)
        assert checkpoint is not None
        receipts = checkpoint["executable_gate_receipts"]
        self.assertNotEqual(receipts[0]["execution_id"], receipts[1]["execution_id"])
        with self.assertRaisesRegex(ProjectAutopilotContractError, "receipt_invalid"):
            engine._verify_executable_receipt(
                mission_id="mis_" + "c" * 32,
                binding_digest=binding,
                primary_input_digest=primary.input_digest,
                plan=raw_plan,
                index=1,
                receipt=receipts[0],
            )

    def test_post_return_clone_drift_fails_final_reverification(self) -> None:
        factory = _Factory(["PASS_DRIFT"], [])
        engine = self._engine(factory=factory)
        binding = "d" * 64
        primary = self._envelope(engine)
        outcome = engine.execute(
            mission_id="mis_" + "d" * 32,
            binding_digest=binding,
            envelope=primary,
            patch=PATCH,
            cancel=lambda: False,
            executable_plan=self._authorized(engine, primary, binding, "pytest"),
        )
        self.assertEqual(outcome["status"], "waiting", outcome)
        self.assertEqual(outcome["waiting_for"], "controlled_clone_drift")
        self.assertEqual(
            outcome["data"]["repository_code_execution_state"],
            "executed_receipt",
        )
