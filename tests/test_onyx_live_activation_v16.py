from __future__ import annotations

import os
import runpy
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from core import onyx_live_activation_v14 as v14
from core import onyx_live_activation_v15 as v15
from core import onyx_live_activation_v16 as v16
from core import permission_broker
from core.governance_nucleus_v1 import (
    GovernanceIdentityV1,
    GovernanceNucleusV1,
    GovernanceV1Denied,
    create_governance_nucleus_v1,
)
from core.phase6_live_wiring_v1 import Phase6LiveWiringV1Denied


ROOT = Path(__file__).resolve().parents[1]


class _Vault:
    def __init__(self) -> None:
        self.value: bytes | None = None

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, value: bytes | bytearray) -> None:
        self.value = bytes(value)

    def delete(self) -> bool:
        existed = self.value is not None
        self.value = None
        return existed


class _UI:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.muted = True
        self.current_file = None

    def write_log(self, value: str) -> None:
        self.logs.append(value)

    def set_state(self, _value: str) -> None:
        pass


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "v16@invalid.local")
    _git(root, "config", "user.name", "V16 Tests")
    (root / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-qm", "initial")
    return root.resolve()


def _environment(root: Path) -> dict[str, str]:
    result = dict(os.environ)
    for name in v16.CONTROL_FLAGS:
        result.pop(name, None)
    result.update(
        v16.exact_activation_environment(
            (root,), executable_sandbox=False
        )
    )
    result["QT_QPA_PLATFORM"] = "offscreen"
    result["QSG_RHI_BACKEND"] = "software"
    return result


def _nucleus(tmp_path: Path) -> GovernanceNucleusV1:
    vaults = (_Vault(), _Vault(), _Vault())
    return GovernanceNucleusV1(
        path=tmp_path / "governance.sqlite3",
        identity=GovernanceIdentityV1(
            "onyx-owner",
            "onyx-local-workspace",
            "cyryx-local-account",
            "onyx-owner-profile",
        ),
        key_vault=vaults[0],
        head_vault=vaults[1],
        pending_vault=vaults[2],
    )


def _replay_factory(tmp_path: Path):
    vaults = (_Vault(), _Vault(), _Vault())

    def create():
        return v16._GovernanceLedgerV1(
            tmp_path / "downgrade-replay.sqlite3",
            key_vault=vaults[0],
            head_vault=vaults[1],
            pending_vault=vaults[2],
        ).initialize()

    return create


def test_v16_environment_bootstrap_and_owner_authorized_v15_downgrade(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    environment = v16.exact_activation_environment(
        (root,), executable_sandbox=False
    )
    flags = v16.ActivationFlagsV16.from_canonical_environ(environment)
    assert flags.master is True
    assert flags.governance is True
    assert flags.base.workspace_roots == (str(root),)

    bootstrap = runpy.run_path(
        str(ROOT / "scripts" / "bootstrap_onyx_live_v16.pyw"),
        run_name="_test_bootstrap_v16",
    )
    with (
        patch.object(bootstrap["platform"], "system", return_value="Windows"),
        patch.dict(
            bootstrap["_bootstrap_environment"].__globals__,
            {"_default_workspace_root": lambda: root},
        ),
    ):
        default = bootstrap["_bootstrap_environment"]({"PATH": "preserved"})
    assert default["PATH"] == "preserved"
    v16.ActivationFlagsV16.from_canonical_environ(default)

    explicit_v15 = v15.exact_activation_environment(
        (root,), executable_sandbox=False
    )
    with (
        patch.object(bootstrap["platform"], "system", return_value="Linux"),
        pytest.raises(RuntimeError, match=v15.PLATFORM_REFUSAL_SIGNAL),
    ):
        bootstrap["_bootstrap_environment"](explicit_v15)
    with (
        patch.object(bootstrap["platform"], "system", return_value="Windows"),
        pytest.raises(RuntimeError, match="DOWNGRADE_RECEIPT_REQUIRED"),
    ):
        bootstrap["_bootstrap_environment"](explicit_v15)

    receipt_vault = _Vault()
    signing_vault = _Vault()
    nucleus = _nucleus(tmp_path / "downgrade")
    nucleus.begin_session()
    nucleus.approval_inbox.wrap(lambda request: request["digest"])
    nucleus.request_downgrade_receipt(
        "v15",
        receipt_vault=receipt_vault,
        signing_key_vault=signing_vault,
        now_ms=1000,
    )
    with (
        patch.object(bootstrap["platform"], "system", return_value="Windows"),
        patch.object(v16, "_downgrade_vault", return_value=receipt_vault),
        patch.object(
            v16, "_downgrade_signing_vault", return_value=signing_vault
        ),
        patch.object(
            v16,
            "_downgrade_replay_ledger",
            side_effect=_replay_factory(tmp_path / "bootstrap-replay"),
        ),
        patch.object(v16.time, "time_ns", return_value=1000 * 1_000_000),
    ):
        assert bootstrap["_bootstrap_environment"](explicit_v15) == explicit_v15
    assert receipt_vault.get_bytes() is None
    assert v16.consume_bootstrap_downgrade_marker_v1("v15") is True
    assert v16.consume_bootstrap_downgrade_marker_v1("v15") is False

    with (
        patch.object(bootstrap["platform"], "system", return_value="Windows"),
        pytest.raises(RuntimeError, match="DOWNGRADE_RECEIPT_REQUIRED"),
    ):
        bootstrap["_bootstrap_environment"](v14.exact_activation_environment())
    with patch.object(bootstrap["platform"], "system", return_value="Linux"):
        assert bootstrap["_bootstrap_environment"](
            v14.exact_activation_environment()
        ) == v14.exact_activation_environment()
    with (
        patch.object(bootstrap["platform"], "system", return_value="Windows"),
        pytest.raises(RuntimeError, match="DOWNGRADE_RECEIPT_REQUIRED"),
    ):
        bootstrap["_bootstrap_environment"](v16.exact_rollback_environment())
    with pytest.raises(RuntimeError, match="PARTIAL_CONFIGURATION"):
        bootstrap["_bootstrap_environment"](
            {v16.LIVE_MASTER_FLAG: "1"}
        )

    stable = (ROOT / "scripts" / "bootstrap_onyx.pyw").read_text(
        encoding="utf-8"
    )
    assert 'bootstrap_onyx_live_v19.pyw"' in stable


def test_v16_workspace_bindings_are_owner_derived_and_root_distinct(
    tmp_path: Path,
) -> None:
    first = _workspace(tmp_path / "first")
    second = _workspace(tmp_path / "second")
    identity, records = v16.governance_workspace_bindings_v1((first, second))
    assert identity.principal_id.startswith("principal-")
    assert identity.account_id.startswith("account-")
    assert identity.profile_id.startswith("profile-")
    assert identity.workspace_id == records[0].workspace_id
    assert records[0].workspace_id != records[1].workspace_id
    assert {item.workspace_class for item in records} == {
        "personal",
        "professional",
    }
    nucleus = create_governance_nucleus_v1(
        path=tmp_path / "governance.sqlite3",
        principal_id=identity.principal_id,
        workspace_id=identity.workspace_id,
        account_id=identity.account_id,
        profile_id=identity.profile_id,
        workspace_display=identity.workspace_display,
        key_vault=_Vault(),
        head_vault=_Vault(),
        pending_vault=_Vault(),
        require_windows_boundary=False,
        workspace_records=records,
    )
    try:
        assert nucleus.identity == identity
        assert nucleus.workspace_records == records
    finally:
        nucleus.close()


def test_v16_governance_smoke_is_isolated_provider_free_and_complete(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path / "repo")
    data = tmp_path / "data"
    data.mkdir()
    output = data / "governance-smoke-v1.json"
    environment = os.environ.copy()
    for name in v16.CONTROL_FLAGS:
        environment.pop(name, None)
    environment["ONYX_DATA_DIR"] = str(data)
    environment[v16.GOVERNANCE_SMOKE_OUTPUT_ENV] = str(output)
    environment.update(
        v16.exact_activation_environment((root,), executable_sandbox=False)
    )
    with patch.dict(os.environ, environment, clear=True):
        import main

        payload = v16.run_governance_smoke_v1(main)
    assert payload["status"] == "passed"
    assert payload["catalog_reads"] == [
        {"state": "completed", "items": 2},
        {"state": "completed", "items": 2},
    ]
    assert payload["trusted_ui_prompts"] == 0
    assert payload["grant_use_count_after_two"] == 2
    assert payload["grant_revoke_replaced"] is True
    assert payload["grant_expiry_replaced"] is True
    assert payload["global_kill_latched"] is True
    assert payload["late_result_event"] == "action-late-blocked"
    assert payload["restart_kill_denied"] is True
    assert payload["network_calls"] == payload["provider_calls"] == 0
    assert output.is_file()


def test_v16_governance_smoke_refuses_output_outside_data_root(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    with patch.dict(
        os.environ,
        {
            "ONYX_DATA_DIR": str(data),
            v16.GOVERNANCE_SMOKE_OUTPUT_ENV: str(tmp_path / "outside.json"),
        },
        clear=True,
    ):
        with pytest.raises(v16.ActivationV16Error, match="isolated data root"):
            v16._governance_smoke_output_path_v1()
        assert not (tmp_path / "outside.json").exists()


def test_v16_governance_smoke_uses_native_boundaries_and_real_counters(
    tmp_path: Path,
) -> None:
    def original_client(**_kwargs: object) -> object:
        return object()

    module = ModuleType("governance_smoke_instrumentation")
    module.genai = SimpleNamespace(Client=original_client)
    original_socket = socket.socket
    original_connection = socket.create_connection
    isolation = v16._GovernanceSmokeIsolationV1(module)
    isolation.install()
    try:
        with pytest.raises(v16.ActivationV16Error, match="network used"):
            socket.create_connection(("127.0.0.1", 9))
        with pytest.raises(v16.ActivationV16Error, match="provider used"):
            module.genai.Client(api_key="not-a-real-key")
        assert isolation.network_calls == 1
        assert isolation.provider_calls == 1
    finally:
        isolation.close()
    assert socket.socket is original_socket
    assert socket.create_connection is original_connection
    assert module.genai.Client is original_client

    data = tmp_path / "data"
    data.mkdir()
    output = data / "governance-smoke-v1.json"
    failure = v16.GovernanceSmokeExecutionErrorV1(
        "InjectedFailure",
        network_calls=isolation.network_calls,
        provider_calls=isolation.provider_calls,
    )
    with patch.dict(
        os.environ,
        {
            "ONYX_DATA_DIR": str(data),
            v16.GOVERNANCE_SMOKE_OUTPUT_ENV: str(output),
        },
        clear=True,
    ):
        v16.write_governance_smoke_failure_v1(failure)
    payload = output.read_text(encoding="utf-8")
    assert '"network_calls":1' in payload
    assert '"provider_calls":1' in payload

    source = (ROOT / "core" / "onyx_live_activation_v16.py").read_text(
        encoding="utf-8"
    )
    smoke = source[source.index("class _GovernanceSmokeIsolationV1") :]
    assert "_GovernanceSmokeVaultV1" not in smoke
    assert "require_windows_boundary=False" not in smoke
    assert "phase11_native.NativeSecretVault" not in smoke
    assert '"network_calls": isolation.network_calls' in smoke
    assert '"provider_calls": isolation.provider_calls' in smoke
    assert '"network_calls": 0' not in smoke
    assert '"provider_calls": 0' not in smoke


def test_v16_governance_smoke_refuses_non_windows_before_output(
    tmp_path: Path,
) -> None:
    module = ModuleType("governance_smoke_non_windows")
    with (
        patch.object(v16.platform, "system", return_value="Linux"),
        patch.dict(
            os.environ,
            {
                "ONYX_DATA_DIR": str(tmp_path),
                v16.GOVERNANCE_SMOKE_OUTPUT_ENV: str(tmp_path / "result.json"),
            },
            clear=True,
        ),
        pytest.raises(v16.GovernanceSmokePlatformRefusalV1),
    ):
        v16.run_governance_smoke_v1(module)
    assert not (tmp_path / "result.json").exists()


def test_v16_downgrade_receipt_is_trusted_exact_expiring_and_one_time(
    tmp_path: Path,
) -> None:
    vault = _Vault()
    signing = _Vault()
    denied = _nucleus(tmp_path / "denied")
    denied.begin_session()
    denied.approval_inbox.wrap(lambda _request: None)
    with pytest.raises(GovernanceV1Denied, match="not approved"):
        denied.request_downgrade_receipt(
            "v15",
            receipt_vault=vault,
            signing_key_vault=signing,
            now_ms=1000,
        )
    assert vault.get_bytes() is None
    nucleus = _nucleus(tmp_path / "approved")
    nucleus.begin_session()
    nucleus.approval_inbox.wrap(lambda request: request["digest"])
    nucleus.request_downgrade_receipt(
        "v15",
        receipt_vault=vault,
        signing_key_vault=signing,
        now_ms=1000,
    )
    assert not hasattr(v16, "issue_owner_authorized_downgrade_v1")
    assert not hasattr(v16, "verify_and_consume_downgrade_v1")
    replay = _replay_factory(tmp_path / "replay")
    with (
        patch.object(v16, "_downgrade_vault", return_value=vault),
        patch.object(v16, "_downgrade_signing_vault", return_value=signing),
        patch.object(v16, "_downgrade_replay_ledger", side_effect=replay),
        patch.object(
            v16.time,
            "time_ns",
            return_value=(1000 + v16.DOWNGRADE_RECEIPT_TTL_MS + 1)
            * 1_000_000,
        ),
    ):
        assert not v16._consume_host_downgrade_receipt_v1("v15")
    original = vault.get_bytes()
    assert original is not None
    with (
        patch.object(v16, "_downgrade_vault", return_value=vault),
        patch.object(v16, "_downgrade_signing_vault", return_value=signing),
        patch.object(v16, "_downgrade_replay_ledger", side_effect=replay),
        patch.object(v16.time, "time_ns", return_value=1001 * 1_000_000),
    ):
        assert v16._consume_host_downgrade_receipt_v1("v15")
        assert v16.consume_bootstrap_downgrade_marker_v1("v15") is True
        vault.set_bytes(original)
        v16._CONSUMED_DOWNGRADES.clear()
        assert not v16._consume_host_downgrade_receipt_v1("v15")
    assert v16.consume_bootstrap_downgrade_marker_v1("v15") is False


def test_v16_downgrade_concurrent_consume_has_one_durable_winner(
    tmp_path: Path,
) -> None:
    receipt = _Vault()
    signing = _Vault()
    nucleus = _nucleus(tmp_path / "issuer")
    nucleus.begin_session()
    nucleus.approval_inbox.wrap(lambda request: request["digest"])
    nucleus.request_downgrade_receipt(
        "v15",
        receipt_vault=receipt,
        signing_key_vault=signing,
        now_ms=1000,
    )
    replay = _replay_factory(tmp_path / "replay-concurrent")
    with (
        patch.object(v16, "_downgrade_vault", return_value=receipt),
        patch.object(v16, "_downgrade_signing_vault", return_value=signing),
        patch.object(v16, "_downgrade_replay_ledger", side_effect=replay),
        patch.object(v16.time, "time_ns", return_value=1001 * 1_000_000),
        ThreadPoolExecutor(max_workers=8) as pool,
    ):
        outcomes = tuple(
            pool.map(
                lambda _index: v16._consume_host_downgrade_receipt_v1(
                    "v15"
                ),
                range(8),
            )
        )
    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 7
    assert v16.consume_bootstrap_downgrade_marker_v1("v15") is True


def test_v16_real_host_nucleus_precedes_session_and_rolls_back(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    environment = _environment(root)
    phase11_vault = _Vault()

    def trusted(request: dict) -> str:
        return request["digest"]

    with patch.dict(os.environ, environment, clear=True):
        import main

        controller = v16.OnyxLiveActivationV16(
            v16.ActivationFlagsV16.from_canonical_environ(environment),
            v16.preflight_host(main, environment),
            nucleus_factory=lambda: _nucleus(tmp_path),
        )
        permission_broker.set_permission_callback(trusted)
        try:
            controller.install()
            with (
                patch.object(
                    main,
                    "memory_dir",
                    return_value=tmp_path / "data" / "memory",
                ),
                patch.object(
                    main,
                    "runtime_dir",
                    return_value=tmp_path / "data" / "runtime",
                ),
                patch(
                    "core.phase11_live_mission_v1."
                    "native_vault.NativeSecretVault",
                    return_value=phase11_vault,
                ),
                patch.object(
                    socket,
                    "socket",
                    side_effect=AssertionError("network used"),
                ),
                patch.object(
                    socket,
                    "create_connection",
                    side_effect=AssertionError("network used"),
                ),
            ):
                instance = controller.instantiate_live(_UI())
            nucleus = instance._governance_nucleus_v1
            assert type(nucleus) is GovernanceNucleusV1
            assert nucleus.status().session_id is None
            assert controller.governance_capability == "available"
            assert controller.executable_capability == (
                controller._base.executable_capability
            )
            controller.rollback_all()
            assert permission_broker.get_permission_callback() is trusted
        finally:
            if controller.governance_capability == "available":
                controller.rollback_all()
            permission_broker.set_permission_callback(None)
        assert not hasattr(main.OnyxLive, "_governance_activation_v16")


def test_v16_phase5_start_failure_compensates_governance_once(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    environment = _environment(root)
    phase11_vault = _Vault()
    with patch.dict(os.environ, environment, clear=True):
        import main

        controller = v16.OnyxLiveActivationV16(
            v16.ActivationFlagsV16.from_canonical_environ(environment),
            v16.preflight_host(main, environment),
            nucleus_factory=lambda: _nucleus(tmp_path / "governance"),
        )
        permission_broker.set_permission_callback(
            lambda request: request["digest"]
        )
        try:
            controller.install()
            with (
                patch.object(
                    main,
                    "memory_dir",
                    return_value=tmp_path / "data" / "memory",
                ),
                patch.object(
                    main,
                    "runtime_dir",
                    return_value=tmp_path / "data" / "runtime",
                ),
                patch(
                    "core.phase11_live_mission_v1."
                    "native_vault.NativeSecretVault",
                    return_value=phase11_vault,
                ),
            ):
                instance = controller.instantiate_live(_UI())
            nucleus = instance._governance_nucleus_v1
            begin = controller.begin_phase5_session

            def begin_with_grant(host: object) -> dict[str, str]:
                phase5_environment = begin(host)
                token = nucleus.begin_invocation("phase5-start-failure")
                try:
                    allowed, _reason = nucleus.authorization_hook(
                        "system_status", {}
                    )
                finally:
                    nucleus.end_invocation(token)
                assert allowed is True
                assert nucleus.status().active_grants == 1
                return phase5_environment

            with (
                patch.object(
                    controller,
                    "begin_phase5_session",
                    side_effect=begin_with_grant,
                ),
                patch(
                    "core.phase5_integration_v3.create_phase5_integration_v3",
                    side_effect=RuntimeError("injected-create-failure"),
                ),
                pytest.raises(Phase6LiveWiringV1Denied),
            ):
                instance._start_phase5_session()

            assert instance._phase5 is None
            assert nucleus.status().session_id is None
            assert nucleus.status().active_grants == 0
            assert all(
                grant.revoked_reason == "session-ended"
                for grant in nucleus._grants.values()
            )
            ended = [
                event
                for event in nucleus._ledger.events(
                    nucleus.identity.workspace_id
                )
                if event.event_type == "session-ended"
            ]
            assert len(ended) == 1
            assert ended[0].payload["reason"] == "phase5-start-failed"
        finally:
            if controller.governance_capability == "available":
                controller.rollback_all()
            permission_broker.set_permission_callback(None)


def test_v16_each_added_failpoint_rolls_back_to_exact_v15(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    environment = _environment(root)
    with patch.dict(os.environ, environment, clear=True):
        import main

        originals = {
            name: getattr(main.OnyxLive, name)
            for name in (
                "__init__",
                "_start_phase5_session",
                "_stop_phase5_session",
                "_execute_tool",
            )
        }
        for index in range(1, v16.OnyxLiveActivationV16.V16_SEAM_COUNT + 1):
            controller = v16.OnyxLiveActivationV16(
                v16.ActivationFlagsV16.from_canonical_environ(environment),
                v16.preflight_host(main, environment),
            )
            with pytest.raises(v16.ActivationV16Error, match="injected V16"):
                controller.install(
                    fail_after=controller.BASE_SEAM_COUNT + index
                )
            assert {
                name: getattr(main.OnyxLive, name) for name in originals
            } == originals
            assert not hasattr(main.OnyxLive, "_governance_activation_v16")


def test_v16_repeated_instances_preserve_original_trusted_callback(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    environment = _environment(root)
    with patch.dict(os.environ, environment, clear=True):
        import main

        class Host:
            def __init__(self, _ui: object) -> None:
                self._phase5 = None
                self._phase11_missions = None
                self._mission_worker = None
                self._dashboard = None

            def _start_phase5_session(self) -> None:
                pass

            def _stop_phase5_session(self, _reason: str) -> None:
                pass

            async def _execute_tool(self, _fc: object) -> object:
                return object()

        module = ModuleType("v16_repeated_host")
        module.OnyxLive = Host
        paths = iter((tmp_path / "one",))
        contract = v16.HostContractV16(
            module,
            Host,
            root,
            v15.preflight_host(
                main, v16.restore_v15_environment(environment)
            ),
        )

        def trusted(request: dict) -> str:
            return request["digest"]

        controller = v16.OnyxLiveActivationV16(
            v16.ActivationFlagsV16.from_canonical_environ(environment),
            contract,
            nucleus_factory=lambda: _nucleus(next(paths)),
        )
        controller._trusted_callback = trusted
        permission_broker.set_permission_callback(trusted)
        try:
            controller._install_seams()
            first = Host(_UI())
            controller.initialize_host(first)
            first_callback = permission_broker.get_permission_callback()
            with pytest.raises(
                v16.ActivationV16Error, match="already owns governance"
            ):
                controller.initialize_host(Host(_UI()))
            second_callback = permission_broker.get_permission_callback()
            assert getattr(first_callback, "_onyx_governance_inbox_v1") is (
                first._governance_nucleus_v1.approval_inbox
            )
            assert second_callback is first_callback
            assert permission_broker._governance_authorization_hook.__self__ is (
                first._governance_nucleus_v1
            )
            assert controller._trusted_callback is trusted
        finally:
            controller.rollback_installation()
            assert permission_broker.get_permission_callback() is trusted
            assert permission_broker._governance_authorization_hook is None
            permission_broker.set_permission_callback(None)


def test_main_global_kill_reaches_governance_before_phase11_availability() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    start = source.index('elif name == "mission_global_kill":')
    end = source.index('elif name == "mission_run":', start)
    branch = source[start:end]
    assert branch.index("governance.global_kill") < branch.index(
        "elif phase11_bridge is not None:"
    )


def test_main_has_final_governance_fence_between_approval_and_dispatch() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    approval = source.index("authorize_model_tool, name, approval_args")
    first_dispatch = source.index("if name == _DAYOPS_READ_TOOL:", approval)
    guarded = source[approval:first_dispatch]
    assert "governance.assert_dispatch_allowed" in guarded
    assert guarded.index("governance.assert_dispatch_allowed") < len(guarded)


def test_v16_production_ordering_wraps_callback_installed_after_activation(
    tmp_path: Path,
) -> None:
    """The activation chain installs before main() creates the UI.

    `launch_onyx_live_v24.pyw` calls `activate_main(...)` first and only then
    `main()`, which is where `set_permission_callback(ui.request_permission)`
    runs. The trusted callback therefore does not exist at install time, so
    the approval inbox must wrap the callback that arrives afterwards. If it
    does not, a human approval registers no action-intent and every governed
    dispatch fails the fence with GovernanceV1Denied — the approval dialog
    becomes structurally useless.
    """
    root = _workspace(tmp_path)
    environment = _environment(root)
    with patch.dict(os.environ, environment, clear=True):
        import main

        class Host:
            def __init__(self, _ui: object) -> None:
                self._phase5 = None
                self._phase11_missions = None
                self._mission_worker = None
                self._dashboard = None

            def _start_phase5_session(self) -> None:
                pass

            def _stop_phase5_session(self, _reason: str) -> None:
                pass

            async def _execute_tool(self, _fc: object) -> object:
                return object()

        module = ModuleType("v16_production_ordering_host")
        module.OnyxLive = Host
        paths = iter((tmp_path / "one",))
        contract = v16.HostContractV16(
            module,
            Host,
            root,
            v15.preflight_host(
                main, v16.restore_v15_environment(environment)
            ),
        )

        def trusted(request: dict) -> str:
            return request["digest"]

        controller = v16.OnyxLiveActivationV16(
            v16.ActivationFlagsV16.from_canonical_environ(environment),
            contract,
            nucleus_factory=lambda: _nucleus(next(paths)),
        )
        permission_broker.set_permission_callback(None)
        try:
            # activate_main(...): no UI exists yet, so there is nothing to
            # capture. This is the exact production state.
            controller._trusted_callback = (
                permission_broker.get_permission_callback()
            )
            assert controller._trusted_callback is None
            controller._install_seams()
            # main(): the UI is built and installs the real callback.
            permission_broker.set_permission_callback(trusted)
            # OnyxLive(ui): the governed host is constructed.
            host = Host(_UI())
            controller.initialize_host(host)
            installed = permission_broker.get_permission_callback()
            assert installed is not trusted, (
                "the approval inbox never wrapped the trusted callback, so "
                "every human approval fails the governance dispatch fence"
            )
            assert getattr(installed, "_onyx_governance_inbox_v1") is (
                host._governance_nucleus_v1.approval_inbox
            )
            # Rollback must restore the real UI callback, not the None that
            # was current at install time.
            assert controller._trusted_callback is trusted
        finally:
            controller.rollback_installation()
            permission_broker.set_permission_callback(None)
