from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import core as core_package
import main as onyx_main
from core import onyx_live_activation_v24 as v24


def test_v24_authenticates_the_exact_v23_source() -> None:
    assert v24._authenticate_v23(onyx_main) == Path(onyx_main.__file__).resolve().parent
    assert v24.V23_SHA256 == v24._sha256(Path(v24.v23.__file__).resolve())


def test_v24_ignores_normal_import_and_private_sys_modules_substitution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_normal = ModuleType("core.onyx_live_activation_v23")
    fake_normal.ActivationFlagsV23 = object
    fake_private = ModuleType(v24._PRIVATE_V23_NAME)
    monkeypatch.setitem(sys.modules, "core.onyx_live_activation_v23", fake_normal)
    monkeypatch.setattr(
        core_package,
        "onyx_live_activation_v23",
        fake_normal,
        raising=False,
    )
    monkeypatch.setitem(sys.modules, v24._PRIVATE_V23_NAME, fake_private)

    authenticated = v24._load_authenticated_v23()

    assert authenticated is not fake_normal
    assert authenticated is not fake_private
    assert authenticated.ActivationFlagsV23 is not object
    assert authenticated.__name__ == v24._PRIVATE_V23_NAME
    assert authenticated.__onyx_authenticated_source_sha256__ == v24.V23_SHA256
    assert sys.modules["core.onyx_live_activation_v23"] is fake_normal
    assert sys.modules[v24._PRIVATE_V23_NAME] is fake_private


@pytest.mark.parametrize("dependency_name", tuple(v24._DIRECT_DEPENDENCIES))
def test_v24_rejects_spoofed_direct_dependency_module(
    dependency_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    relative, _sha256 = v24._DIRECT_DEPENDENCIES[dependency_name]
    fake = ModuleType(dependency_name)
    fake.__file__ = str((v24._PROJECT_ROOT / relative).resolve())
    monkeypatch.setitem(sys.modules, dependency_name, fake)
    if dependency_name == "core.onyx_live_activation_v22":
        monkeypatch.setattr(
            core_package,
            "onyx_live_activation_v22",
            fake,
            raising=False,
        )

    with pytest.raises(v24.ActivationV24Error, match="dependency"):
        v24._load_authenticated_v23()


@pytest.mark.asyncio
async def test_real_v23_chain_is_outer_guarded_after_shutdown(
    tmp_path: Path,
) -> None:
    project = Path(__file__).resolve().parents[1]
    if not (project / ".venv/Scripts/pythonw.exe").is_file():
        pytest.skip("source freeze intentionally excludes the local virtualenv")
    environment = v24.exact_activation_environment((tmp_path,))
    contract = v24.preflight_host(onyx_main, environment)
    controller = v24.OnyxLiveActivationV24(
        v24.ActivationFlagsV24.from_canonical_environ(environment),
        contract,
    )
    previous = dict(os.environ)
    os.environ.clear()
    os.environ.update(environment)
    try:
        controller.install()
        setattr(contract.module, v24.HOST_MARKER, controller)
        instance = object.__new__(onyx_main.OnyxLive)
        instance._shutdown_input_quiesced = threading.Event()
        instance._shutdown_input_quiesced.set()
        instance._external_action_tasks = set()
        controller._bind_instance(instance)
        guarded_class = type(instance)

        direct = await instance._execute_tool(
            SimpleNamespace(name="open_app", args={}, id="direct")
        )

        async def reentrant() -> object:
            return await instance._execute_tool(
                SimpleNamespace(name="browser_control", args={}, id="reentrant")
            )

        nested = await reentrant()
        class_call = await type(instance)._execute_tool(
            instance,
            SimpleNamespace(name="class_call", args={}, id="class"),
        )
        batch = await asyncio.gather(
            *(
                instance._execute_tool(
                    SimpleNamespace(name=f"batch_{index}", args={}, id=f"b{index}")
                )
                for index in range(3)
            )
        )
        assert "shutdown is already in progress" in direct.response["result"]
        assert "shutdown is already in progress" in nested.response["result"]
        assert "shutdown is already in progress" in class_call.response["result"]
        assert all(
            "shutdown is already in progress" in response.response["result"]
            for response in batch
        )
        assert [row[1] for row in instance._final_tool_dispatch_denials_v24] == [
            "direct",
            "reentrant",
            "class",
            "b0",
            "b1",
            "b2",
        ]
        assert instance._external_action_tasks == set()
        terminal = v24._capture_terminal_rollback(controller._base)
        controller.rollback_all()
        assert type(instance) is onyx_main.OnyxLive
        assert guarded_class is not type(instance)
        assert not hasattr(terminal.ui_module, "_ONYX_HUD_V6_INSTALLATION")
        for version, hud_module in terminal.hud_modules:
            assert not hasattr(
                terminal.ui_module,
                f"_ONYX_HUD_V{version}_INSTALLATION",
            )
            assert id(terminal.ui_module) not in hud_module._ACTIVE_INSTALLATIONS
    finally:
        try:
            if controller._installed:
                controller.rollback_all()
        finally:
            os.environ.clear()
            os.environ.update(previous)


def test_v24_partial_dynamic_class_bind_restores_exact_instance_state() -> None:
    async def instance_dispatch(_function_call: object) -> object:
        return object()

    class RefusesDispatchDeletion:
        async def _execute_tool(self, _function_call: object) -> object:
            return object()

        def __delattr__(self, name: str) -> None:
            if name == "_execute_tool":
                raise RuntimeError("injected delete failure")
            super().__delattr__(name)

    instance = RefusesDispatchDeletion()
    instance._execute_tool = instance_dispatch
    original_class = type(instance)
    original_dispatch = instance.__dict__["_execute_tool"]
    controller = object.__new__(v24.OnyxLiveActivationV24)
    controller._bindings = []

    with pytest.raises(v24.ActivationV24Error, match="binding failed"):
        controller._bind_instance(instance)

    assert type(instance) is original_class
    assert instance.__dict__["_execute_tool"] is original_dispatch
    assert controller._bindings == []


@pytest.mark.asyncio
async def test_guard_denies_shadow_and_rollback_is_fail_closed_retryable() -> None:
    class Base:
        def __init__(self) -> None:
            self.rollback_calls = 0

        def rollback_all(self) -> None:
            self.rollback_calls += 1

    class Host:
        async def _execute_tool(self, function_call: object) -> object:
            return getattr(function_call, "id", None)

    module = ModuleType("v24_test_host")
    base = Base()
    controller = object.__new__(v24.OnyxLiveActivationV24)
    controller.contract = SimpleNamespace(module=module)
    controller._base = base
    controller._installed = True
    controller._rollback_pending = False
    controller._bindings = []
    setattr(module, v24.HOST_MARKER, controller)
    instance = Host()
    controller._bind_instance(instance)

    async def substituted(_function_call: object) -> object:
        return "substituted"

    with pytest.raises(v24.ActivationV24Error, match="cannot be shadowed"):
        instance._execute_tool = substituted
    with pytest.raises(v24.ActivationV24Error, match="cannot be shadowed"):
        object.__setattr__(instance, "_execute_tool", substituted)

    instance.__dict__["_execute_tool"] = substituted
    assert await instance._execute_tool(SimpleNamespace(id="authentic")) == "authentic"
    with pytest.raises(v24.ActivationV24Error, match="restoration failed"):
        controller.rollback_all()
    assert controller._installed is True
    assert controller._rollback_pending is True
    assert len(controller._bindings) == 1
    assert getattr(module, v24.HOST_MARKER) is controller
    assert base.rollback_calls == 0

    instance.__dict__.pop("_execute_tool")
    controller.rollback_all()
    assert type(instance) is Host
    assert controller._bindings == []
    assert controller._installed is False
    assert controller._rollback_pending is False
    assert not hasattr(module, v24.HOST_MARKER)
    assert base.rollback_calls == 1


def test_dispatch_restore_failure_keeps_recovery_state_for_retry() -> None:
    class Base:
        rollback_calls = 0

        def rollback_all(self) -> None:
            self.rollback_calls += 1

    class Host:
        refuse_dispatch = False

        async def _execute_tool(self, _function_call: object) -> object:
            return object()

        def __setattr__(self, name: str, value: object) -> None:
            if name == "_execute_tool" and self.refuse_dispatch:
                raise RuntimeError("injected restoration failure")
            super().__setattr__(name, value)

    async def instance_dispatch(_function_call: object) -> object:
        return object()

    module = ModuleType("v24_retry_host")
    base = Base()
    controller = object.__new__(v24.OnyxLiveActivationV24)
    controller.contract = SimpleNamespace(module=module)
    controller._base = base
    controller._installed = True
    controller._rollback_pending = False
    controller._bindings = []
    setattr(module, v24.HOST_MARKER, controller)
    instance = Host()
    instance._execute_tool = instance_dispatch
    controller._bind_instance(instance)
    instance.refuse_dispatch = True

    with pytest.raises(v24.ActivationV24Error, match="restoration failed"):
        controller.rollback_all()
    assert type(instance) is Host
    assert controller._bindings[0].class_restored is True
    assert base.rollback_calls == 0
    assert getattr(module, v24.HOST_MARKER) is controller

    instance.refuse_dispatch = False
    controller.rollback_all()
    assert instance.__dict__["_execute_tool"] is instance_dispatch
    assert base.rollback_calls == 1
    assert not hasattr(module, v24.HOST_MARKER)


def test_v23_rollback_failure_retains_v24_marker_and_retries() -> None:
    class Base:
        rollback_calls = 0

        def rollback_all(self) -> None:
            self.rollback_calls += 1
            if self.rollback_calls == 1:
                raise RuntimeError("injected V23 rollback failure")

    class Host:
        async def _execute_tool(self, _function_call: object) -> object:
            return object()

    module = ModuleType("v24_base_retry_host")
    base = Base()
    controller = object.__new__(v24.OnyxLiveActivationV24)
    controller.contract = SimpleNamespace(module=module)
    controller._base = base
    controller._installed = True
    controller._rollback_pending = False
    controller._bindings = []
    setattr(module, v24.HOST_MARKER, controller)
    instance = Host()
    controller._bind_instance(instance)

    with pytest.raises(v24.ActivationV24Error, match="V23 rollback failed"):
        controller.rollback_all()
    assert type(instance) is Host
    assert controller._bindings == []
    assert controller._installed is True
    assert controller._rollback_pending is True
    assert getattr(module, v24.HOST_MARKER) is controller

    controller.rollback_all()
    assert base.rollback_calls == 2
    assert controller._installed is False
    assert controller._rollback_pending is False
    assert not hasattr(module, v24.HOST_MARKER)
