from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from core import onyx_live_activation_v15 as v15
from core.missions import InvalidTransition, MissionStore
from core.permission_broker import set_permission_callback
from core.phase11_executable_sandbox_v1 import (
    SCHEMA as SANDBOX_SCHEMA,
    ExecutableSandboxHostV1,
    ExecutableSandboxError,
    ExecutableSandboxReceiptV1,
    ExecutableTestSandboxV1,
)
from core.phase11_live_mission_v1 import Phase11LiveMissionV1
from core.phase11_project_autopilot_v1 import ExecutableGateEnvelopeV1


IMAGE_ID = "sha256:" + "4" * 64
PATCH = """diff --git a/demo.txt b/demo.txt
--- a/demo.txt
+++ b/demo.txt
@@ -1 +1 @@
-before
+after
"""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def _keyed(key: bytes, domain: bytes, value: bytes) -> str:
    return hmac.new(
        key, domain + b"\0" + value, hashlib.sha256
    ).hexdigest()


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "owner"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Onyx V15")
    _git(root, "config", "user.email", "onyx-v15@example.invalid")
    (root / "demo.txt").write_bytes(b"before\n")
    _git(root, "add", "demo.txt")
    _git(root, "commit", "-qm", "base")
    return root.resolve()


class _MemoryVault:
    def __init__(self) -> None:
        self.value: bytes | None = None

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, value: bytes | bytearray) -> None:
        self.value = bytes(value)


def _sandbox_receipt(
    key: bytes, request: object
) -> ExecutableSandboxReceiptV1:
    mission_id = str(getattr(request, "mission_id"))
    argv = getattr(request, "argv")
    receipt = ExecutableSandboxReceiptV1(
        schema=SANDBOX_SCHEMA,
        execution_id=str(getattr(request, "execution_id")),
        attempt=int(getattr(request, "attempt", 1)),
        mission_hmac_sha256=_keyed(
            key, b"mission", mission_id.encode("utf-8")
        ),
        image_sha256=str(getattr(request, "image_id")).removeprefix(
            "sha256:"
        ),
        argv_hmac_sha256=_keyed(key, b"argv", _canonical(argv)),
        prelaunch_clone_manifest_hmac_sha256="5" * 64,
        stdout_hmac_sha256="6" * 64,
        stderr_hmac_sha256="7" * 64,
        stdout_bytes=0,
        stderr_bytes=0,
        exit_code=0,
        duration_ms=1,
        verdict="PASS",
        receipt_hmac_sha256="",
    )
    return replace(
        receipt,
        receipt_hmac_sha256=_keyed(
            key,
            b"receipt",
            _canonical(
                {**asdict(receipt), "receipt_hmac_sha256": ""}
            ),
        ),
    )


class _FakeSandbox:
    def __init__(self, binding: dict[str, object]) -> None:
        self.binding = {
            key: value
            for key, value in binding.items()
            if key not in {"signing_key", "execution_ledger"}
        }
        self.key = bytes(binding["signing_key"])
        self.ledger = binding.get("execution_ledger")
        self.requests: list[object] = []

    def integration_binding(self) -> dict[str, object]:
        return dict(self.binding)

    def execute(
        self, request: object, *, cancel: object
    ) -> ExecutableSandboxReceiptV1:
        assert not getattr(cancel, "is_set")()
        clone = Path(str(getattr(request, "clone_root")))
        assert (clone / "demo.txt").read_text(encoding="utf-8") == "after\n"
        self.requests.append(request)
        receipt = _sandbox_receipt(self.key, request)
        if self.ledger is not None:
            ledger_binding = {
                "mission_id": str(getattr(request, "mission_id")),
                "execution_id": str(getattr(request, "execution_id")),
                "workspace_id": "5" * 64,
                "image_digest": str(getattr(request, "image_id")).removeprefix("sha256:"),
                "argv_digest": hashlib.sha256(
                    _canonical(getattr(request, "argv"))
                ).hexdigest(),
                "attempt": int(getattr(request, "attempt", 1)),
            }
            self.ledger.append("intent", **ledger_binding)
            self.ledger.append("dispatch_reserved", **ledger_binding)
            self.ledger.append(
                "receipt",
                receipt=asdict(receipt),
                image_id=str(getattr(request, "image_id")),
                argv=getattr(request, "argv"),
                **ledger_binding,
            )
        return receipt


class _Factory:
    def __init__(self) -> None:
        self.instances: list[_FakeSandbox] = []

    def __call__(self, **binding: object) -> _FakeSandbox:
        instance = _FakeSandbox(dict(binding))
        self.instances.append(instance)
        return instance


class _UnknownSandbox(_FakeSandbox):
    def execute(self, request: object, *, cancel: object):
        self.requests.append(request)
        if self.ledger is not None:
            ledger_binding = {
                "mission_id": str(getattr(request, "mission_id")),
                "execution_id": str(getattr(request, "execution_id")),
                "workspace_id": "5" * 64,
                "image_digest": str(getattr(request, "image_id")).removeprefix("sha256:"),
                "argv_digest": hashlib.sha256(
                    _canonical(getattr(request, "argv"))
                ).hexdigest(),
                "attempt": int(getattr(request, "attempt", 1)),
            }
            self.ledger.append("intent", **ledger_binding)
            self.ledger.append("dispatch_reserved", **ledger_binding)
            self.ledger.append("unknown", **ledger_binding)
        raise ExecutableSandboxError("simulated_unknown_after_dispatch")


class _UnknownFactory(_Factory):
    def __call__(self, **binding: object) -> _UnknownSandbox:
        instance = _UnknownSandbox(dict(binding))
        self.instances.append(instance)
        return instance


def _official_host(tmp_path: Path) -> ExecutableSandboxHostV1:
    return ExecutableSandboxHostV1(
        docker_cli=str(Path(sys.executable).resolve()),
        docker_host="npipe:////./pipe/onyx-test",
    )


def _official_fake_execute(
    sandbox: ExecutableTestSandboxV1,
    request: object,
    *,
    cancel: object,
) -> ExecutableSandboxReceiptV1:
    fake = _FakeSandbox(
        {
            **sandbox.integration_binding(),
            "signing_key": sandbox._signing_key,
            "execution_ledger": sandbox._execution_ledger,
        }
    )
    return fake.execute(request, cancel=cancel)


def _official_unknown_execute(
    sandbox: ExecutableTestSandboxV1,
    request: object,
    *,
    cancel: object,
) -> ExecutableSandboxReceiptV1:
    fake = _UnknownSandbox(
        {
            **sandbox.integration_binding(),
            "signing_key": sandbox._signing_key,
            "execution_ledger": sandbox._execution_ledger,
        }
    )
    return fake.execute(request, cancel=cancel)


@pytest.mark.skipif(os.name != "nt", reason="live Phase 11 is Windows-only")
def test_live_missionstore_executes_only_bound_authenticated_envelope(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    vaults: dict[str, _MemoryVault] = {}
    requests: list[object] = []

    def execute(sandbox, request, *, cancel):
        requests.append(request)
        return _official_fake_execute(sandbox, request, cancel=cancel)

    bridge = Phase11LiveMissionV1(
        store,
        binding_dir=tmp_path / "bindings",
        allowed_roots=(repo,),
        enabled=True,
        key=b"k" * 32,
        anchor_vault_factory=lambda reference: vaults.setdefault(
            reference.account, _MemoryVault()
        ),
        autopilot_enabled=True,
        executable_sandbox_enabled=True,
        executable_sandbox_host=_official_host(tmp_path),
        approved_executable_image_ids=(IMAGE_ID,),
        executable_platform="linux/amd64",
    )
    set_permission_callback(lambda request: request["digest"])
    observed: list[object] = []
    original_normalize = bridge.autopilot._normalize_executable_plan

    def capture(value: object, **kwargs: Any) -> object:
        observed.append(value)
        return original_normalize(value, **kwargs)

    bridge.autopilot._normalize_executable_plan = capture
    try:
        mission = bridge.create_autopilot(
            title="Authenticated executable gate",
            workspace_root=str(repo),
            patch=PATCH,
            gates=[
                {
                    "argv": ["onyx-static", "diff-check"],
                    "timeout_seconds": 30,
                }
            ],
            executable_image_id=IMAGE_ID,
            executable_platform="linux/amd64",
            executable_gates=[
                {
                    "argv": ["python", "-m", "pytest", "-q"],
                    "timeout_seconds": 30,
                    "max_output_bytes": 64_000,
                }
            ],
            max_seconds=120,
        )
        binding = bridge._read_binding(mission.id)
        assert binding is not None
        fixed = binding["fixed_steps"][0]["args"]
        assert fixed["repository_code_execution"] is True
        assert fixed["executable_plan_digest"] == (
            binding["executable_autopilot"]["plan_digest"]
        )
        serialized_binding = json.dumps(binding, sort_keys=True)
        serialized_store = json.dumps(
            store.authority_plan_steps_v1(mission.id), sort_keys=True
        )
        for protected_value in (
            "authorization_hmac_sha256",
            '"executable_gates"',
            '"argv": ["python", "-m", "pytest"',
        ):
            assert protected_value not in serialized_binding
            assert protected_value not in serialized_store
        artifact_reference = binding["executable_plan_artifact"]
        artifact_path = bridge.binding_dir / artifact_reference["name"]
        assert artifact_path.is_file()
        ciphertext = artifact_path.read_bytes()
        assert hashlib.sha256(ciphertext).hexdigest() == (
            artifact_reference["ciphertext_sha256"]
        )
        assert b"python" not in ciphertext
        assert b"pytest" not in ciphertext
        assert store.get(mission.id).state == "awaiting_approval"

        bridge.approve(mission.id)
        with patch.object(ExecutableTestSandboxV1, "execute", execute):
            completed = store.run(
                mission.id, bridge.runner, backoff=lambda _: None
            )
        assert completed.state == "succeeded", (
            completed.error,
            bridge.status(mission.id),
            bridge.autopilot.checkpoint_status(mission.id),
        )
        assert len(observed) == 1
        authority = observed[0]
        assert isinstance(authority, ExecutableGateEnvelopeV1)
        assert authority.mission_id == mission.id
        assert authority.gate_index == 0
        authority.verify(
            approved_image_ids=(IMAGE_ID,),
            mission_id=mission.id,
            gate_index=0,
            primary_envelope=bridge._autopilot_envelope(binding),
            binding_digest=binding["binding_digest"],
            signing_key=b"k" * 32,
        )
        assert len(requests) == 1
        ledger = bridge._execution_ledger
        assert ledger is not None
        assert [record.kind for record in ledger.read()] == [
            "intent",
            "dispatch_reserved",
            "receipt",
        ]
        request = requests[0]
        assert ledger.authenticated_receipt(
            mission_id=mission.id,
            execution_id=str(getattr(request, "execution_id")),
            attempt=int(getattr(request, "attempt", 1)),
        ) is not None
        checkpoint = bridge.autopilot.checkpoint_status(mission.id)
        assert checkpoint is not None
        assert checkpoint["repository_code_execution_state"] == (
            "executed_receipt"
        )
        status = bridge.status(mission.id)
        assert status["autopilot"]["repository_code_execution_state"] == (
            "executed_receipt"
        )
        assert (repo / "demo.txt").read_text(encoding="utf-8") == "before\n"
    finally:
        set_permission_callback(None)
        bridge.close()


@pytest.mark.skipif(os.name != "nt", reason="live Phase 11 is Windows-only")
def test_attempted_unknown_reconciliation_survives_real_cold_restarts(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    store_path = tmp_path / "missions.sqlite3"
    binding_dir = tmp_path / "bindings"
    vaults: dict[str, _MemoryVault] = {}
    requests: list[object] = []

    def execute(sandbox, request, *, cancel):
        requests.append(request)
        return _official_unknown_execute(sandbox, request, cancel=cancel)

    def open_bridge() -> Phase11LiveMissionV1:
        return Phase11LiveMissionV1(
            MissionStore(store_path),
            binding_dir=binding_dir,
            allowed_roots=(repo,),
            enabled=True,
            key=b"k" * 32,
            anchor_vault_factory=lambda reference: vaults.setdefault(
                reference.account, _MemoryVault()
            ),
            autopilot_enabled=True,
            executable_sandbox_enabled=True,
            executable_sandbox_host=_official_host(tmp_path),
            approved_executable_image_ids=(IMAGE_ID,),
            executable_platform="linux/amd64",
        )

    set_permission_callback(lambda request: request["digest"])
    first = open_bridge()
    try:
        mission = first.create_autopilot(
            title="Durable unknown reconciliation",
            workspace_root=str(repo),
            patch=PATCH,
            gates=[
                {
                    "argv": ["onyx-static", "diff-check"],
                    "timeout_seconds": 30,
                }
            ],
            executable_image_id=IMAGE_ID,
            executable_platform="linux/amd64",
            executable_gates=[
                {
                    "argv": ["python", "-m", "pytest", "-q"],
                    "timeout_seconds": 30,
                    "max_output_bytes": 64_000,
                }
            ],
            max_seconds=120,
        )
        first.approve(mission.id)
        with patch.object(ExecutableTestSandboxV1, "execute", execute):
            waiting = first.store.run(
                mission.id, first.runner, backoff=lambda _: None
            )
        assert waiting.state == "waiting"
        original_checkpoint = first.autopilot.checkpoint_status(mission.id)
        assert original_checkpoint is not None
        original_intent = dict(
            original_checkpoint["executable_gate_intent"]
        )
        assert (
            original_checkpoint["repository_code_execution_state"]
            == "attempted_unknown"
        )
        assert len(requests) == 1
    finally:
        first.close()

    second = open_bridge()
    try:
        outcome = second.reconcile_executable_attempt(
            mission.id, decision="still_unknown"
        )
        assert outcome["dispatch_permitted"] is False
        persisted = second.autopilot.checkpoint_status(mission.id)
        assert persisted is not None
        assert persisted["executable_gate_intent"] == original_intent
        assert len(requests) == 1
        with pytest.raises(
            Exception, match="fresh reapproval is forbidden"
        ):
            second.reseed_autopilot(mission.id)
    finally:
        second.close()

    third = open_bridge()
    try:
        status = third.status(mission.id)
        assert status["autopilot"]["reconciliation"]["decision"] == (
            "still_unknown"
        )

        def crash_after_reconciliation_anchor(point: str) -> None:
            if point == "after_reconciliation_anchor":
                raise RuntimeError("simulated cold restart after anchor")

        third._reconciliation_fault = crash_after_reconciliation_anchor
        with pytest.raises(
            RuntimeError, match="simulated cold restart after anchor"
        ):
            third.reconcile_executable_attempt(
                mission.id, decision="abandon"
            )
        assert third.store.get(mission.id).state == "waiting"
        names = [
            event["event"] for event in third.store.events(mission.id)
        ]
        assert names[-1] == "phase11.reconciliation"
        assert "phase11.kill" not in names
        anchor = json.loads(vaults[mission.id].value.decode("utf-8"))
        snapshot = third.store.authority_snapshot(mission.id)
        assert anchor["event_seq"] == snapshot.event_seq
        assert anchor["event_hash"] == snapshot.event_hash
    finally:
        third.close()

    fourth = open_bridge()
    try:
        outcome = fourth.reconcile_executable_attempt(
            mission.id, decision="abandon"
        )
        assert outcome["terminal"] is True
        assert fourth.store.get(mission.id).state == "cancelled"
        events = fourth.store.events(mission.id)
        names = [event["event"] for event in events]
        abandon_index = max(
            index
            for index, event in enumerate(events)
            if event["event"] == "phase11.reconciliation"
            and event["detail"]["decision"] == "abandon"
        )
        assert abandon_index < names.index("phase11.kill")
        assert names.index("phase11.kill") < names.index(
            "mission.cancelled"
        )
        assert len(requests) == 1
        with pytest.raises(InvalidTransition):
            fourth.store.resolve(mission.id, "succeeded")
        assert fourth.store.get(mission.id).state == "cancelled"
        with pytest.raises(
            Exception, match="fresh reapproval is forbidden"
        ):
            fourth.reseed_autopilot(mission.id)
    finally:
        set_permission_callback(None)
        fourth.close()


@pytest.mark.skipif(os.name != "nt", reason="live Phase 11 is Windows-only")
def test_secret_shaped_executable_argv_is_rejected_before_persistence(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    vaults: dict[str, _MemoryVault] = {}
    binding_dir = tmp_path / "bindings"
    bridge = Phase11LiveMissionV1(
        store,
        binding_dir=binding_dir,
        allowed_roots=(repo,),
        enabled=True,
        key=b"k" * 32,
        anchor_vault_factory=lambda reference: vaults.setdefault(
            reference.account, _MemoryVault()
        ),
        autopilot_enabled=True,
        executable_sandbox_enabled=True,
        executable_sandbox_host=_official_host(tmp_path),
        approved_executable_image_ids=(IMAGE_ID,),
        executable_platform="linux/amd64",
    )
    try:
        with pytest.raises(Exception, match="secret"):
            bridge.create_autopilot(
                title="Secret refusal",
                workspace_root=str(repo),
                patch=PATCH,
                gates=[
                    {
                        "argv": ["onyx-static", "diff-check"],
                        "timeout_seconds": 30,
                    }
                ],
                executable_image_id=IMAGE_ID,
                executable_platform="linux/amd64",
                executable_gates=[
                    {
                        "argv": [
                            "pytest",
                            "--api-key=sk-example-secret-value",
                        ],
                        "timeout_seconds": 30,
                        "max_output_bytes": 64_000,
                    }
                ],
                max_seconds=120,
            )
        assert store.list() == []
        assert list(binding_dir.glob("*.binding.json")) == []
        assert list((binding_dir / "artifacts").glob("*")) == []
    finally:
        bridge.close()


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / ".venv/Scripts/pythonw.exe").is_file(),
    reason="source freeze intentionally excludes the local virtualenv",
)
def test_v15_exact_flags_and_runtime_seam_are_fully_reversible(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    environment = dict(os.environ)
    for name in v15.CONTROL_FLAGS:
        environment.pop(name, None)
    docker = (tmp_path / "docker.exe").resolve()
    docker.write_bytes(b"MZ")
    environment.update(
        v15.exact_activation_environment(
            (repo,),
            executable_docker_cli=str(docker),
            executable_docker_host="npipe:////./pipe/onyx-test",
            executable_platform="linux/amd64",
            executable_image_ids=(IMAGE_ID,),
        )
    )
    with patch.dict(os.environ, environment, clear=True):
        import main

        original_init = Phase11LiveMissionV1.__init__
        controller = v15.OnyxLiveActivationV15(
            v15.ActivationFlagsV15.from_canonical_environ(environment),
            v15.preflight_host(main, environment),
            executable_sandbox_process_factory=_Factory(),
        )
        controller.install()
        try:
            assert Phase11LiveMissionV1.__init__ is not original_init
        finally:
            controller.rollback_all()
        assert Phase11LiveMissionV1.__init__ is original_init
        assert not hasattr(main.OnyxLive, "_phase11_activation_v15")


@pytest.mark.parametrize(
    "flag",
    [
        v15.PROJECT_AUTOPILOT_FLAG,
        v15.EXECUTABLE_SANDBOX_FLAG,
        v15.EXECUTABLE_DOCKER_CLI_FLAG,
        v15.EXECUTABLE_DOCKER_HOST_FLAG,
        v15.EXECUTABLE_PLATFORM_FLAG,
        v15.EXECUTABLE_IMAGE_IDS_FLAG,
    ],
)
def test_v15_partial_executable_configuration_fails_closed(
    tmp_path: Path, flag: str
) -> None:
    repo = _repo(tmp_path)
    environment = v15.exact_activation_environment((repo,))
    environment.pop(flag)
    with pytest.raises(v15.ActivationV15Error, match="executable|Docker"):
        v15.ActivationFlagsV15.from_canonical_environ(environment)


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / ".venv/Scripts/pythonw.exe").is_file(),
    reason="source freeze intentionally excludes the local virtualenv",
)
def test_v15_all_local_failpoints_restore_phase11_constructor(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    environment = dict(os.environ)
    for name in v15.CONTROL_FLAGS:
        environment.pop(name, None)
    environment.update(v15.exact_activation_environment((repo,)))
    with patch.dict(os.environ, environment, clear=True):
        import main

        original_init = Phase11LiveMissionV1.__init__
        for failpoint in range(
            v15.OnyxLiveActivationV15.BASE_SEAM_COUNT + 1,
            v15.OnyxLiveActivationV15.TOTAL_SEAM_COUNT + 1,
        ):
            controller = v15.OnyxLiveActivationV15(
                v15.ActivationFlagsV15.from_canonical_environ(
                    environment
                ),
                v15.preflight_host(main, environment),
                executable_sandbox_process_factory=_Factory(),
            )
            with pytest.raises(v15.ActivationV15Error, match="injected V15"):
                controller.install(fail_after=failpoint)
            assert Phase11LiveMissionV1.__init__ is original_init
            assert not hasattr(main.OnyxLive, "_phase11_activation_v15")


def test_windows_sandbox_dynamic_imports_are_packaged() -> None:
    root = Path(__file__).resolve().parents[1]
    spec = (root / "packaging" / "onyx.spec").read_text(encoding="utf-8")
    smoke = (root / "main.py").read_text(encoding="utf-8")
    for module in ("ntsecuritycon", "win32api", "win32security"):
        assert f'"{module}"' in spec
        assert f"import {module}" in smoke
    # pywintypes imports this dynamically during the frozen host's pinned
    # executable health probe, so static PyInstaller analysis cannot see it.
    assert '"win32timezone"' in spec
