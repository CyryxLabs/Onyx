from __future__ import annotations

import asyncio
import os
from pathlib import Path
import runpy
import subprocess
import types
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest

from core import dayops_live_integration_v1 as dayops
from core import onyx_live_activation_v14 as live
from core import onyx_live_activation_v19 as stable_live
from core import permission_broker


ROOT = Path(__file__).resolve().parents[1]


class FakeUI:
    def __init__(self) -> None:
        self.logs: list[str] = []
        self.states: list[str] = []
        self.muted = False
        self._win = types.SimpleNamespace(_hud_v5_live=True)

    def write_log(self, value: str) -> None:
        self.logs.append(value)

    def set_state(self, value: str) -> None:
        self.states.append(value)

    def prompt_reconfig(self) -> None:
        pass


def active_environment(*, configured: bool = False) -> dict[str, str]:
    result = dict(os.environ)
    for name in live.CONTROL_FLAGS:
        result.pop(name, None)
    result.update(live.exact_activation_environment())
    if configured:
        result.update(
            {
                dayops.IANA_TIMEZONE_KEY: "America/New_York",
                dayops.OUTLOOK_TIMEZONE_KEY: "Eastern Standard Time",
            }
        )
    return result


def _call():
    return types.SimpleNamespace(
        id="call-1",
        name=dayops.TOOL_NAME,
        args={"date": "2026-07-30"},
    )


def test_v14_environment_bootstrap_launcher_and_v13_restore() -> None:
    environment = live.exact_activation_environment()
    flags = live.ActivationFlagsV14.from_canonical_environ(environment)
    assert flags.master and flags.dayops
    assert environment[live.LIVE_MASTER_FLAG] == "1"
    assert environment[live.DAYOPS_FLAG] == "true"
    assert environment[live.v13.LIVE_MASTER_FLAG] == "1"
    restored = live.restore_v13_environment(environment)
    assert live.LIVE_MASTER_FLAG not in restored
    assert live.DAYOPS_FLAG not in restored
    assert restored[live.v13.LIVE_MASTER_FLAG] == "1"

    bootstrap = runpy.run_path(
        str(ROOT / "scripts/bootstrap_onyx_live_v14.pyw"),
        run_name="_test_bootstrap_v14",
    )
    prepared = bootstrap["_bootstrap_environment"](
        {
            "PATH": "preserved",
            live.LIVE_ROLLBACK_FLAG: "1",
            live.v13.LIVE_ROLLBACK_FLAG: "1",
            live.DAYOPS_FLAG: "TRUE",
        }
    )
    assert prepared["PATH"] == "preserved"
    assert {name: prepared[name] for name in environment} == environment

    launcher = runpy.run_path(
        str(ROOT / "scripts/launch_onyx_live_v14.pyw"),
        run_name="_test_launcher_v14",
    )
    assert launcher["_launch_mode"]({}) == "legacy"
    assert launcher["_launch_mode"](environment) == "active"
    assert launcher["_launch_mode"]({live.LIVE_ROLLBACK_FLAG: "1"}) == "rollback"
    assert launcher["_launch_mode"]({live.LIVE_MASTER_FLAG: "1"}) == "refuse"


def test_v14_denied_authorization_never_constructs_factory() -> None:
    environment = active_environment(configured=True)
    factory_calls: list[int] = []
    authorization_calls: list[str] = []
    controller_calls: list[str] = []
    with patch.dict(os.environ, environment, clear=True):
        import main

        controller = live.OnyxLiveActivationV14(
            live.ActivationFlagsV14.from_canonical_environ(environment),
            live.preflight_host(main, environment),
            dayops_factory=lambda now_ms: factory_calls.append(now_ms),  # type: ignore[arg-type,func-returns-value]
        )
        try:
            controller.install()
            assert any(
                item.get("name") == dayops.TOOL_NAME
                for item in main.TOOL_DECLARATIONS
            )
            instance = controller._base.wiring_controller._host_type(FakeUI())

            def deny(name: str, _args: dict):
                authorization_calls.append(name)
                return False, "Permission denied by test."

            def forbidden_execute(*_args, **_kwargs):
                controller_calls.append("execute")
                raise AssertionError("DayOps controller must not run before authorization")

            with (
                patch.object(main, "authorize_model_tool", deny),
                patch.object(
                    dayops.DayOpsLiveIntegrationV1,
                    "execute",
                    forbidden_execute,
                ),
            ):
                response = asyncio.run(instance._execute_tool(_call()))
            assert response.response["result"] == "Permission denied by test."
            assert authorization_calls == [dayops.TOOL_NAME]
            assert controller_calls == []
            assert factory_calls == []
        finally:
            controller.rollback_all()


def test_v14_authorized_dispatch_calls_dayops_after_authorization() -> None:
    environment = active_environment(configured=True)
    order: list[str] = []
    with patch.dict(os.environ, environment, clear=True):
        import main

        controller = live.OnyxLiveActivationV14(
            live.ActivationFlagsV14.from_canonical_environ(environment),
            live.preflight_host(main, environment),
        )
        try:
            controller.install()
            instance = controller._base.wiring_controller._host_type(FakeUI())
            instance._start_phase5_session()
            assert instance._phase5 is not None
            assert controller._base.phase6_wiring_v2.session_for(instance) is not None

            def allow(_name: str, _args: dict):
                order.append("authorize")
                return True, "approved"

            def execute(_self, arguments, *, environ=None, now=None):
                assert arguments == {"date": "2026-07-30"}
                assert environ is os.environ
                assert now is None
                order.append("controller")
                return dayops.DayOpsExecutionV1(
                    "completed",
                    {
                        "status": "completed",
                        "read_only": True,
                        "events": [],
                        "unread_messages": [],
                    },
                )

            with (
                patch.object(main, "authorize_model_tool", allow),
                patch.object(dayops.DayOpsLiveIntegrationV1, "execute", execute),
            ):
                response = asyncio.run(instance._execute_tool(_call()))
            assert order == ["authorize", "controller"]
            assert response.response["status"] == "completed"
            assert response.response["read_only"] is True
            instance._stop_phase5_session("test")
            assert instance._phase5 is None
        finally:
            controller.rollback_all()


def test_v14_missing_config_is_safe_after_authorization_and_zero_factory() -> None:
    environment = active_environment(configured=False)
    factory_calls: list[int] = []
    order: list[str] = []
    with patch.dict(os.environ, environment, clear=True):
        import main

        controller = live.OnyxLiveActivationV14(
            live.ActivationFlagsV14.from_canonical_environ(environment),
            live.preflight_host(main, environment),
            dayops_factory=lambda now_ms: factory_calls.append(now_ms),  # type: ignore[arg-type,func-returns-value]
        )
        try:
            controller.install()
            instance = controller._base.wiring_controller._host_type(FakeUI())

            def allow(_name: str, _args: dict):
                order.append("authorize")
                return True, "approved"

            with patch.object(main, "authorize_model_tool", allow):
                response = asyncio.run(instance._execute_tool(_call()))
            assert response.response["status"] == "configuration_required"
            assert order == ["authorize"]
            assert factory_calls == []
        finally:
            controller.rollback_all()


@pytest.mark.parametrize("offset", [1, 2, 3])
def test_each_v14_failpoint_restores_exact_v13(offset: int) -> None:
    environment = active_environment()
    with patch.dict(os.environ, environment, clear=True):
        import main

        controller = live.OnyxLiveActivationV14(
            live.ActivationFlagsV14.from_canonical_environ(environment),
            live.preflight_host(main, environment),
        )
        try:
            with pytest.raises(live.ActivationV14Error, match="injected V14"):
                controller.install(fail_after=controller.BASE_SEAM_COUNT + offset)
            assert not any(
                item.get("name") == dayops.TOOL_NAME
                for item in main.TOOL_DECLARATIONS
            )
            assert dayops.TOOL_NAME not in permission_broker.MODEL_TOOL_POLICIES
            assert id(controller) not in live._ROLLBACK_AUTHORITIES
            assert live.LIVE_MASTER_FLAG not in os.environ
            assert os.environ[live.v13.LIVE_MASTER_FLAG] == "1"
            assert controller._base.phase6_wiring_v2 is not None
            assert controller._base.phase6_wiring_v2.installed
        finally:
            controller._base.rollback_all()


def test_v14_rollback_restores_declaration_policy_and_exact_v13_dispatch() -> None:
    environment = active_environment()
    with patch.dict(os.environ, environment, clear=True):
        import main

        controller = live.OnyxLiveActivationV14(
            live.ActivationFlagsV14.from_canonical_environ(environment),
            live.preflight_host(main, environment),
        )
        try:
            controller.install()
            protected_execute = main.OnyxLive._execute_tool
            assert dayops.TOOL_NAME in permission_broker.MODEL_TOOL_POLICIES
            assert main.OnyxLive._dayops_controller_v14 is controller.dayops_controller
            controller.rollback_installation()
            assert main.OnyxLive._execute_tool is protected_execute
            assert not hasattr(main.OnyxLive, "_dayops_controller_v14")
            assert not any(
                item.get("name") == dayops.TOOL_NAME
                for item in main.TOOL_DECLARATIONS
            )
            assert dayops.TOOL_NAME not in permission_broker.MODEL_TOOL_POLICIES
            assert controller._base.phase6_wiring_v2 is not None
            assert controller._base.phase6_wiring_v2.installed
        finally:
            controller._base.rollback_all()


def test_v14_invalid_date_is_audited_rejected_and_restores_listening() -> None:
    environment = active_environment(configured=True)
    with patch.dict(os.environ, environment, clear=True):
        import main

        controller = live.OnyxLiveActivationV14(
            live.ActivationFlagsV14.from_canonical_environ(environment),
            live.preflight_host(main, environment),
        )
        try:
            controller.install()
            ui = FakeUI()
            instance = controller._base.wiring_controller._host_type(ui)
            call = types.SimpleNamespace(
                id="call-invalid",
                name=dayops.TOOL_NAME,
                args={"date": "30/07/2026"},
            )
            with patch.object(
                main,
                "authorize_model_tool",
                lambda _name, _args: (True, "approved"),
            ):
                response = asyncio.run(instance._execute_tool(call))
            assert response.response["status"] == "rejected"
            assert response.response["read_only"] is True
            assert response.response["result"] == "DayOps request is invalid."
            assert ui.states[-1] == "LISTENING"
        finally:
            controller.rollback_all()


def test_dayops_requires_callback_when_cautious_but_owner_autonomy_is_audited() -> None:
    environment = active_environment()
    callback_calls: list[str] = []
    audit_calls: list[dict] = []
    with patch.dict(os.environ, environment, clear=True):
        import main

        controller = live.OnyxLiveActivationV14(
            live.ActivationFlagsV14.from_canonical_environ(environment),
            live.preflight_host(main, environment),
        )
        try:
            controller.install()
            permission_broker._audit_healthy = True
            permission_broker.configure_owner_autonomy(False, ())
            permission_broker.set_trust_profile("cautious")

            def approve(request: dict) -> str:
                callback_calls.append(request["action"])
                return request["digest"]

            permission_broker.set_permission_callback(approve)
            cautious, _reason = permission_broker.authorize_model_tool(
                dayops.TOOL_NAME,
                {"date": "2026-07-30"},
            )
            assert cautious is True
            assert callback_calls == [dayops.TOOL_NAME]

            permission_broker.configure_owner_autonomy(True, ())
            permission_broker.set_trust_profile("autonomous")
            permission_broker.set_permission_callback(
                lambda _request: (_ for _ in ()).throw(
                    AssertionError("autonomous read must not open approval UI")
                )
            )
            with patch.object(
                permission_broker,
                "append_tool_audit",
                lambda **record: audit_calls.append(record),
            ):
                autonomous, reason = permission_broker.authorize_model_tool(
                    dayops.TOOL_NAME,
                    {"date": "2026-07-30"},
                )
            assert autonomous is True
            assert reason == "autonomous:day_brief_read"
            assert audit_calls[0]["decision"] == "allow"
            assert audit_calls[0]["reason"] == "autonomous:day_brief_read"
        finally:
            permission_broker.set_permission_callback(None)
            permission_broker.configure_owner_autonomy(False, ())
            permission_broker.set_trust_profile("cautious")
            permission_broker._audit_healthy = True
            controller.rollback_all()


def test_stable_bootstrap_selects_current_and_v14_fallback_stays_provider_free() -> None:
    # This subprocess proves the default desktop path.  Do not let an activation
    # environment deliberately installed by an earlier in-process test turn it
    # into a rollback/partial-configuration probe.  The stable control flags close
    # over every predecessor flag, so this retains unrelated user/process state
    # while making the two bootstrap assertions hermetic.
    bootstrap_environment = dict(os.environ)
    for name in stable_live.CONTROL_FLAGS:
        bootstrap_environment.pop(name, None)

    result = subprocess.run(
        [
            str(ROOT / ".venv/Scripts/python.exe"),
            "-B",
            "scripts/bootstrap_onyx.pyw",
            "--preflight-only",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=bootstrap_environment,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ONYX_LIVE_V20_HOST_PREFLIGHT_OK" in result.stdout
    assert "base=v19-exact" in result.stdout
    assert "advanced_operations=lazy-zero-polling" in result.stdout
    assert "phase6=single-core" in result.stdout
    assert "mission_store=single-authority" in result.stdout
    assert "network_calls=0" in result.stdout
    assert "provider_calls=0" in result.stdout
    assert "process_calls=0" in result.stdout

    fallback = subprocess.run(
        [
            str(ROOT / ".venv/Scripts/python.exe"),
            "-B",
            "scripts/bootstrap_onyx_live_v14.pyw",
            "--preflight-only",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=bootstrap_environment,
    )
    assert fallback.returncode == 0, fallback.stdout + fallback.stderr
    assert "ONYX_LIVE_V14_HOST_PREFLIGHT_OK" in fallback.stdout
    assert "dayops=read-only" in fallback.stdout
    assert "factory=canonical-configurable" in fallback.stdout
    assert "lifecycle=install-rollback" in fallback.stdout
    assert "provider_calls=0" in fallback.stdout
    assert "network_calls=0" in fallback.stdout
