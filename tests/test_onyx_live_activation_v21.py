from __future__ import annotations

import asyncio
import runpy
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from core import onyx_live_activation_v20 as v20
from core import onyx_live_activation_v19 as v19
from core import onyx_live_activation_v21 as v21
from core import onyx_live_activation_v10 as v10
from core.advanced_operations_controller_v1 import (
    HOST_CONTROLLER,
    AdvancedOperationsControllerV1,
)
from core.phase6_live_wiring_v1 import Phase6LiveWiringV1


def _activation(monkeypatch: pytest.MonkeyPatch):
    module = ModuleType("v21_test_host")
    module.TOOL_DECLARATIONS = []
    module.types = SimpleNamespace(
        FunctionResponse=lambda **values: SimpleNamespace(**values)
    )

    class Host:
        def __init__(self, ui):
            self.ui = ui

        async def _execute_tool(self, fc):
            return ("base", fc.name)

        def _build_config(self):
            return SimpleNamespace(system_instruction="base instruction")

        def _run_live_loop(self):
            return None

        def _send_realtime(self):
            return None

        def _start_phase5_session(self):
            return None

        def _stop_phase5_session(self):
            return None

    module.OnyxLive = Host
    base_contract = object.__new__(v20.HostContractV20)
    contract = v21.HostContractV21(module, Host, Path.cwd(), base_contract)
    base_flags = object.__new__(v20.ActivationFlagsV20)
    wiring = object.__new__(Phase6LiveWiringV1)
    wiring._lock = threading.RLock()
    wiring._protected = {"_execute_tool": Host._execute_tool}

    def fake_init(self, *_args, **_kwargs):
        self._installed = False
        self.wiring_controller = wiring
        self.instances = []

    def fake_install(self, *, fail_after=None):
        self._installed = fail_after is None

    def fake_instantiate(self, ui):
        instance = Host(ui)
        controller = AdvancedOperationsControllerV1(
            instance, owner_authority=lambda *_args: False
        )
        setattr(instance, HOST_CONTROLLER, controller)
        self.instances.append(instance)
        return instance

    def fake_rollback(self):
        for instance in self.instances:
            getattr(instance, HOST_CONTROLLER).close()

    monkeypatch.setattr(v20.OnyxLiveActivationV20, "__init__", fake_init)
    monkeypatch.setattr(v20.OnyxLiveActivationV20, "install", fake_install)
    monkeypatch.setattr(v20.OnyxLiveActivationV20, "instantiate_live", fake_instantiate)
    monkeypatch.setattr(v20.OnyxLiveActivationV20, "rollback_all", fake_rollback)
    monkeypatch.setattr(v21, "append_tool_audit", lambda **_kwargs: None)
    activation = v21.OnyxLiveActivationV21(
        v21.ActivationFlagsV21(True, True, base_flags),
        contract,
    )
    return module, Host, wiring, activation


def test_exact_environment_enables_and_rollback_removes_native_workspace_events(
    tmp_path: Path,
) -> None:
    workspace = tmp_path.resolve()
    environment = v21.exact_activation_environment((workspace,))
    assert environment[v21.NATIVE_WORKSPACE_EVENTS_FLAG] == "true"
    assert v21.NATIVE_WORKSPACE_EVENTS_FLAG not in v21.restore_v20_environment(
        environment
    )


def test_v21_default_off_and_tool_schema_is_bounded() -> None:
    with pytest.raises(v21.ActivationV21Error, match="not canonical V21"):
        v21.ActivationFlagsV21.from_canonical_environ({})
    declaration = v21.tool_declaration_v21()
    assert declaration["name"] == v21.TOOL_NAME
    actions = declaration["parameters"]["properties"]["action"]["enum"]
    assert "status" in actions
    assert "create_goal" in actions
    assert "create_automation_rule" in actions
    assert "create_site_project" in actions
    assert "bind_site_operation" in actions
    assert "suggest_preference" in actions
    assert "promote_preference" in actions
    assert "enroll_device" in actions
    assert "disable_device" in actions
    assert "create_workflow" in actions
    assert "bind_workflow_plan" in actions
    assert "reconcile_workflow" in actions
    assert "run_shell" not in actions
    properties = declaration["parameters"]["properties"]
    assert properties["workflow_nodes"]["items"]["required"] == [
        "node_id",
        "kind",
        "config",
    ]
    assert properties["workflow_edges"]["items"]["properties"]["route"][
        "enum"
    ] == ["next", "true", "false"]


def test_v21_routes_only_advanced_operations_and_restores_exact_base(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, host, wiring, activation = _activation(monkeypatch)
    original = host._execute_tool
    activation.install()
    instance = activation.instantiate_live(SimpleNamespace())
    try:
        assert [item["name"] for item in module.TOOL_DECLARATIONS] == [v21.TOOL_NAME]
        response = asyncio.run(
            instance._execute_tool(
                SimpleNamespace(
                    name=v21.TOOL_NAME,
                    args={"action": "status"},
                    id="call-1",
                )
            )
        )
        assert response.name == v21.TOOL_NAME
        assert response.response["status"] == "waiting_for_live_session"
        assert response.response.get("external_dispatch") is None
        assert asyncio.run(
            instance._execute_tool(
                SimpleNamespace(name="existing_tool", args={}, id="call-2")
            )
        ) == ("base", "existing_tool")
    finally:
        activation.rollback_all()
    assert host._execute_tool is original
    assert wiring._protected["_execute_tool"] is original
    assert host._build_config.__name__ == "_build_config"
    assert module.TOOL_DECLARATIONS == []


@pytest.mark.parametrize("offset", [1, 2, 3, 4])
def test_v21_install_failpoints_restore_v20_exactly(
    monkeypatch: pytest.MonkeyPatch, offset: int
) -> None:
    module, host, wiring, activation = _activation(monkeypatch)
    original = host._execute_tool
    with pytest.raises(v21.ActivationV21Error, match="injected V21"):
        activation.install(fail_after=activation.BASE_SEAM_COUNT + offset)
    assert host._execute_tool is original
    assert wiring._protected["_execute_tool"] is original
    assert module.TOOL_DECLARATIONS == []
    assert not hasattr(host, v21.HOST_MARKER)


def test_v21_projects_only_owner_approved_preferences_into_next_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, _wiring, activation = _activation(monkeypatch)
    activation.install()
    instance = activation.instantiate_live(SimpleNamespace())
    controller = getattr(instance, HOST_CONTROLLER)
    monkeypatch.setattr(
        controller,
        "preference_prompt_projection",
        lambda: (
            "Owner-approved interaction preferences: response_detail=concise. "
            "These affect style only."
        ),
    )
    try:
        config = instance._build_config()
        assert config.system_instruction.startswith("base instruction")
        assert "response_detail=concise" in config.system_instruction
        assert "OWNER-APPROVED INTERACTION PREFERENCES" in config.system_instruction
    finally:
        activation.rollback_all()


def test_v21_rejects_unsupported_action_without_external_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, _wiring, activation = _activation(monkeypatch)
    activation.install()
    instance = activation.instantiate_live(SimpleNamespace())
    try:
        response = asyncio.run(
            instance._execute_tool(
                SimpleNamespace(
                    name=v21.TOOL_NAME,
                    args={"action": "run_shell"},
                    id="call-3",
                )
            )
        )
        assert response.response["status"] == "rejected"
        assert response.response["external_dispatch"] is False
    finally:
        activation.rollback_all()


def test_v21_stable_bootstrap_migrates_installed_workspace_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "bootstrap_onyx_live_v21.pyw"
        ),
        run_name="onyx_v21_bootstrap_test",
    )
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Windows")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    mode, environment = namespace["_bootstrap_environment"](
        {
            "KEEP": "yes",
            "ONYX_WORKSPACE_ROOTS": str(workspace),
            "ONYX_PHASE11_LOCAL_PROJECT_AUDIT_V1": "true",
        }
    )
    assert mode == "v21"
    assert environment["KEEP"] == "yes"
    assert environment[v21.LIVE_MASTER_FLAG] == "1"
    assert environment[v21.FEATURE_FLAG] == "true"
    assert environment["ONYX_WORKSPACE_ROOTS"] == str(workspace.resolve())


def test_v21_stable_bootstrap_preserves_complete_v20_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "bootstrap_onyx_live_v21.pyw"
        ),
        run_name="onyx_v21_bootstrap_v20_migration_test",
    )
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Windows")
    previous = v20.exact_activation_environment(
        (tmp_path,), executable_sandbox=False
    )
    mode, environment = namespace["_bootstrap_environment"](previous)
    assert mode == "v21"
    assert environment[v21.LIVE_MASTER_FLAG] == "1"
    flags = v21.ActivationFlagsV21.from_canonical_environ(environment)
    assert flags.base.base.base.base.base.base.workspace_roots == (
        str(tmp_path.resolve()),
    )


def test_v21_stable_bootstrap_refuses_unrecognized_partial_predecessor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "bootstrap_onyx_live_v21.pyw"
        ),
        run_name="onyx_v21_bootstrap_partial_test",
    )
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Windows")
    with pytest.raises(
        RuntimeError, match="ONYX_LIVE_V21_PARTIAL_CONFIGURATION_REFUSED"
    ):
        namespace["_bootstrap_environment"]({v20.LIVE_MASTER_FLAG: "1"})


def test_v21_stable_bootstrap_migrates_recognized_v19_without_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "bootstrap_onyx_live_v21.pyw"
        ),
        run_name="onyx_v21_bootstrap_v19_migration_test",
    )
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Windows")
    previous_root = tmp_path / "previous"
    previous_root.mkdir()
    default_root = tmp_path / "default"
    default_root.mkdir()
    monkeypatch.setitem(
        namespace["_bootstrap_environment"].__globals__,
        "_default_workspace_root",
        lambda: default_root,
    )
    legacy = v19.exact_activation_environment(
        (previous_root,), executable_sandbox=False
    )
    legacy.pop("ONYX_WORKSPACE_ROOTS")
    legacy.pop("ONYX_PHASE11_LOCAL_PROJECT_AUDIT_V1")

    mode, environment = namespace["_bootstrap_environment"](legacy)

    assert mode == "v21"
    assert environment[v21.LIVE_MASTER_FLAG] == "1"
    flags = v21.ActivationFlagsV21.from_canonical_environ(environment)
    assert flags.base.base.base.base.base.base.workspace_roots == (
        str(default_root.resolve()),
    )
    assert flags.base.base.base.base.base.base.executable_sandbox is False


def test_v21_stable_bootstrap_refuses_divergent_recognized_v19(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "bootstrap_onyx_live_v21.pyw"
        ),
        run_name="onyx_v21_bootstrap_v19_drift_test",
    )
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Windows")
    default_root = tmp_path / "default"
    default_root.mkdir()
    monkeypatch.setitem(
        namespace["_bootstrap_environment"].__globals__,
        "_default_workspace_root",
        lambda: default_root,
    )
    legacy = v19.exact_activation_environment(
        (tmp_path,), executable_sandbox=False
    )
    legacy.pop("ONYX_WORKSPACE_ROOTS")
    legacy.pop("ONYX_PHASE11_LOCAL_PROJECT_AUDIT_V1")
    legacy["ONYX_HUD_V9_LIVE"] = "0"

    with pytest.raises(
        RuntimeError, match="ONYX_LIVE_V21_PARTIAL_CONFIGURATION_REFUSED"
    ):
        namespace["_bootstrap_environment"](legacy)


def test_v21_stable_bootstrap_migrates_before_v20_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = runpy.run_path(
        str(
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "bootstrap_onyx_live_v21.pyw"
        ),
        run_name="onyx_v21_bootstrap_diagnostic_migration_test",
    )
    globals_ = namespace["run"].__globals__
    canonical_v21 = v21.exact_activation_environment(
        (tmp_path,), executable_sandbox=False
    )
    captured: list[dict[str, str]] = []
    monkeypatch.setattr(
        globals_["sys"],
        "argv",
        ["bootstrap_onyx_live_v21.pyw", "--governance-smoke-test"],
    )
    monkeypatch.setitem(
        globals_,
        "_bootstrap_environment",
        lambda _environ: ("v21", canonical_v21),
    )
    monkeypatch.setitem(
        globals_,
        "_run_v20",
        lambda environment: captured.append(dict(environment)),
    )

    namespace["run"]()

    assert len(captured) == 1
    assert v21.LIVE_MASTER_FLAG not in captured[0]
    assert v21.FEATURE_FLAG not in captured[0]
    flags = v20.ActivationFlagsV20.from_canonical_environ(captured[0])
    assert flags.base.base.base.base.base.workspace_roots == (
        str(tmp_path.resolve()),
    )


def test_v21_activation_routes_phase6_state_to_owner_private_runtime_and_restores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = v10._prepare_state_root
    private_runtime = tmp_path / "private-runtime"
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(v21, "runtime_dir", lambda: private_runtime)

    with v21.phase6_owner_private_state_boundary_v21(project) as state_root:
        assert v10._prepare_state_root is not original
        resolved = v10._prepare_state_root(project)
        assert resolved == (
            private_runtime / "phase6-live-wiring-v1"
        ).resolve()
        assert state_root.resolve() == resolved
        assert not resolved.is_relative_to(project)

    assert v10._prepare_state_root is original


def test_v21_activation_installs_base_inside_phase6_private_state_boundary() -> None:
    source = Path(v21.__file__).read_text(encoding="utf-8")
    assert (
        "with phase6_owner_private_state_boundary_v21(self.contract.project):\n"
        "                self._base.install(fail_after=base_failpoint)"
    ) in source


def test_v21_activation_phase6_state_boundary_refuses_project_drift_and_restores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = v10._prepare_state_root
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr(v21, "runtime_dir", lambda: tmp_path / "private")
    divergent = tmp_path / "different-project"
    divergent.mkdir()

    with v21.phase6_owner_private_state_boundary_v21(project):
        with pytest.raises(v21.ActivationV21Error, match="project root diverged"):
            v10._prepare_state_root(divergent)

    assert v10._prepare_state_root is original
