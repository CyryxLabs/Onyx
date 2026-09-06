from __future__ import annotations

import asyncio
import hashlib
import inspect
import secrets
import shutil
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from core import onyx_live_activation_google_workspace_v1 as gws_activation
from core import onyx_live_activation_v24 as v24
from core import permission_broker
from core import paths as paths_module
from core import tool_audit
from core import native_vault
from core import google_workspace_audit_v1 as audit_module
from core import google_workspace_connector_v1 as connector_module
from core import google_workspace_host_v1 as host_module
from core import google_workspace_live_v1 as live_module
from core import phase6_live_wiring_v1 as phase6
from core.google_workspace_connector_v1 import READ_SCOPES, GoogleWorkspaceFeatureGateV1
from core.google_workspace_host_v1 import (
    GoogleWorkspaceHostServiceV1,
    GoogleWorkspaceHostStatusV1,
)


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts" / "bootstrap_onyx_live_google_workspace_v1.pyw"
_BINDING = "b" * 64


def _environment() -> dict[str, str]:
    environment = v24.exact_activation_environment((ROOT,))
    environment.update(
        {
            gws_activation.LIVE_FLAG: "true",
            gws_activation.CONNECTOR_FLAG: "true",
            "ONYX_GOOGLE_WORKSPACE_OWNER_ID": "onyx-owner-profile",
            "ONYX_GOOGLE_WORKSPACE_WORKSPACE_ID": "onyx-local-workspace",
            "ONYX_GOOGLE_WORKSPACE_ACCOUNT_ID": "owner@example.com",
            "ONYX_GOOGLE_WORKSPACE_CLIENT_ID": "client-id.apps.googleusercontent.com",
            "ONYX_GOOGLE_WORKSPACE_CALLBACK_PORT": "8765",
        }
    )
    return environment


def _remove_policy() -> None:
    for registry in (
        permission_broker.MODEL_TOOL_POLICIES,
        permission_broker.MODEL_TOOL_ACTIONS,
        permission_broker._AUTONOMOUS_ACTIONS,
    ):
        registry.pop(gws_activation.TOOL_NAME, None)


def test_actual_manifest_and_seven_file_aggregate_are_exact() -> None:
    assert (
        gws_activation.verify_source_provenance_v1()
        == gws_activation.EXPECTED_AGGREGATE
    )


def test_dependency_drift_fails_before_google_import() -> None:
    temporary = ROOT / ".codex-tmp" / f"gws-provenance-{secrets.token_hex(8)}"
    try:
        for relative in (
            gws_activation.MANIFEST_RELATIVE_PATH,
            *(Path(path) for path in gws_activation._EXPECTED_DEPENDENCIES),
        ):
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        target = temporary / "scripts" / "onyx_google_workspace.py"
        target.write_bytes(target.read_bytes() + b"\n")
        with pytest.raises(
            gws_activation.GoogleWorkspaceActivationV1Error, match="dependency"
        ):
            gws_activation.verify_source_provenance_v1(root=temporary)
    finally:
        if temporary.is_dir() and temporary.parent == ROOT / ".codex-tmp":
            shutil.rmtree(temporary)


@pytest.mark.parametrize(
    "environment",
    [
        {gws_activation.LIVE_FLAG: "true"},
        {gws_activation.CONNECTOR_FLAG: "true"},
        {
            gws_activation.LIVE_FLAG: "True",
            gws_activation.CONNECTOR_FLAG: "true",
        },
        {
            gws_activation.LIVE_FLAG.lower(): "true",
            gws_activation.CONNECTOR_FLAG: "true",
        },
        {
            gws_activation.LIVE_FLAG: " true",
            gws_activation.CONNECTOR_FLAG: "true",
        },
    ],
)
def test_partial_or_noncanonical_flags_fail_without_manifest_or_import(
    monkeypatch: pytest.MonkeyPatch, environment: dict[str, str]
) -> None:
    calls = []
    monkeypatch.setattr(
        gws_activation,
        "verify_source_provenance_v1",
        lambda: calls.append("manifest"),
    )
    with pytest.raises(gws_activation.GoogleWorkspaceActivationV1Error):
            gws_activation.preflight_source_environment_v1(environment)
    assert calls == []


def test_enabled_bootstrap_delegates_preflight_to_authenticated_launcher() -> None:
    result = _clean_subprocess(
        """
        import runpy
        import site
        import sys
        from pathlib import Path

        root = Path.cwd()
        site.addsitedir(site.getusersitepackages())
        sys.path.insert(0, str(root))
        bootstrap = runpy.run_path(
            str(root / "scripts" / "bootstrap_onyx_live_google_workspace_v1.pyw"),
            run_name="gws_preflight_order_probe",
        )
        environment = {
            bootstrap["LIVE_FLAG"]: "true",
            bootstrap["CONNECTOR_FLAG"]: "true",
            "ONYX_GOOGLE_WORKSPACE_OWNER_ID": "owner-primary",
            "ONYX_GOOGLE_WORKSPACE_WORKSPACE_ID": "workspace-personal",
            "ONYX_GOOGLE_WORKSPACE_ACCOUNT_ID": "owner@example.com",
            "ONYX_GOOGLE_WORKSPACE_CLIENT_ID": "client-id.apps.googleusercontent.com",
            "ONYX_GOOGLE_WORKSPACE_CALLBACK_PORT": "8765",
        }
        mode, prepared = bootstrap["_bootstrap_environment"](environment)
        assert mode == "google_workspace_v1"
        assert prepared == environment
        assert "_activation_contract" not in bootstrap
        assert "core.onyx_live_activation_google_workspace_v1" not in sys.modules
        launcher = bootstrap["_execute_verified"](
            bootstrap["LAUNCHER"],
            bootstrap["LAUNCHER_SHA256"],
            "gws_preflight_launcher_probe",
        )
        activation = launcher["_activation_contract"]()
        preflight = activation.preflight_source_environment_v1(environment)
        assert preflight.aggregate_sha256 == activation.EXPECTED_AGGREGATE
        assert len(preflight.runtime_modules) == 8
        preflight.close()
        """
    )
    assert result.returncode == 0, result.stderr


def test_launcher_primary_failure_survives_three_rollback_failures() -> None:
    result = _clean_subprocess(
        """
        import runpy
        import sys
        from pathlib import Path
        from types import SimpleNamespace

        root = Path.cwd()
        launcher_path = root / "scripts" / "launch_onyx_live_google_workspace_v1.pyw"
        launcher = runpy.run_path(str(launcher_path), run_name="launcher_failure_probe")
        state = {"rollbacks": 0}

        class Controller:
            def run_runtime(self):
                raise RuntimeError("primary secret")
            def rollback_all(self):
                state["rollbacks"] += 1
                raise RuntimeError("rollback secret")

        launcher["run"].__globals__["_activation_contract"] = lambda: SimpleNamespace(
            activate_main=lambda _environment: Controller()
        )
        sys.argv = [str(launcher_path)]
        try:
            launcher["run"]()
        except RuntimeError as error:
            assert str(error) == "Onyx Google Workspace startup failed safely"
            assert state["rollbacks"] == 3
            assert "primary secret" not in repr(error)
            assert "rollback secret" not in repr(error)
            assert error.__notes__ == [
                "Onyx Google Workspace cleanup also remains pending"
            ]
            assert error.__cause__ is None
        else:
            raise AssertionError("primary startup failure was lost")
        """
    )
    assert result.returncode == 0, result.stderr


def test_production_preflight_rejects_preloaded_google_dependencies() -> None:
    with pytest.raises(
        gws_activation.GoogleWorkspaceActivationV1Error, match="imported before"
    ):
        gws_activation.preflight_source_environment_v1(_environment())


def _clean_subprocess(source: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-B", "-c", textwrap.dedent(source)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_clean_subprocess_rejects_poisoned_production_sys_modules() -> None:
    result = _clean_subprocess(
        """
        import sys
        from pathlib import Path
        from types import ModuleType

        root = Path.cwd()
        sys.path.insert(0, str(root))
        from core import onyx_live_activation_google_workspace_v1 as activation
        environment = {
            activation.LIVE_FLAG: "true",
            activation.CONNECTOR_FLAG: "true",
            "ONYX_GOOGLE_WORKSPACE_OWNER_ID": "owner-primary",
            "ONYX_GOOGLE_WORKSPACE_WORKSPACE_ID": "workspace-personal",
            "ONYX_GOOGLE_WORKSPACE_ACCOUNT_ID": "owner@example.com",
            "ONYX_GOOGLE_WORKSPACE_CLIENT_ID": "client-id.apps.googleusercontent.com",
            "ONYX_GOOGLE_WORKSPACE_CALLBACK_PORT": "8765",
        }
        sys.modules["core.google_workspace_connector_v1"] = ModuleType("poison")
        try:
            activation.preflight_source_environment_v1(environment)
        except activation.GoogleWorkspaceActivationV1Error as error:
            assert "imported before" in str(error)
            assert error.__cause__ is None
            assert error.__context__ is None
        else:
            raise AssertionError("poisoned dependency was accepted")
        """
    )
    assert result.returncode == 0, result.stderr


def test_clean_subprocess_rejects_preloaded_memory_closure_member() -> None:
    result = _clean_subprocess(
        """
        import sys
        from pathlib import Path
        from types import ModuleType

        root = Path.cwd()
        sys.path.insert(0, str(root))
        from core import onyx_live_activation_google_workspace_v1 as activation
        sys.modules["memory.store"] = ModuleType("memory.store")
        environment = {
            activation.LIVE_FLAG: "true",
            activation.CONNECTOR_FLAG: "true",
            "ONYX_GOOGLE_WORKSPACE_OWNER_ID": "owner-primary",
            "ONYX_GOOGLE_WORKSPACE_WORKSPACE_ID": "workspace-personal",
            "ONYX_GOOGLE_WORKSPACE_ACCOUNT_ID": "owner@example.com",
            "ONYX_GOOGLE_WORKSPACE_CLIENT_ID": "client-id.apps.googleusercontent.com",
            "ONYX_GOOGLE_WORKSPACE_CALLBACK_PORT": "8765",
        }
        try:
            activation.preflight_source_environment_v1(environment)
        except activation.GoogleWorkspaceActivationV1Error as error:
            assert "imported before" in str(error)
            assert error.__cause__ is None
            assert error.__context__ is None
        else:
            raise AssertionError("preloaded memory closure was accepted")
        """
    )
    assert result.returncode == 0, result.stderr


def test_clean_subprocess_authenticated_loader_bypasses_meta_path() -> None:
    result = _clean_subprocess(
        """
        import importlib.abc
        import runpy
        import site
        import sys
        from pathlib import Path

        root = Path.cwd()
        site.addsitedir(site.getusersitepackages())
        sys.path.insert(0, str(root))
        from core import onyx_live_activation_google_workspace_v1 as activation
        environment = {
            activation.LIVE_FLAG: "true",
            activation.CONNECTOR_FLAG: "true",
            "ONYX_GOOGLE_WORKSPACE_OWNER_ID": "owner-primary",
            "ONYX_GOOGLE_WORKSPACE_WORKSPACE_ID": "workspace-personal",
            "ONYX_GOOGLE_WORKSPACE_ACCOUNT_ID": "owner@example.com",
            "ONYX_GOOGLE_WORKSPACE_CLIENT_ID": "client-id.apps.googleusercontent.com",
            "ONYX_GOOGLE_WORKSPACE_CALLBACK_PORT": "8765",
        }

        class PoisonFinder(importlib.abc.MetaPathFinder):
            calls = 0
            def find_spec(self, fullname, path=None, target=None):
                if (
                    fullname.startswith("core.")
                    or fullname.startswith("actions.")
                    or fullname.startswith("dashboard.")
                    or fullname.startswith("memory.")
                    or fullname.startswith("scripts.")
                    or fullname in {"main", "ui"}
                ):
                    self.calls += 1
                    raise RuntimeError("poison finder executed")
                return None

        finder = PoisonFinder()
        sys.meta_path.insert(0, finder)
        preflight = activation.preflight_source_environment_v1(environment)
        for name in (
            "core.readiness",
            "memory",
            "main",
            "scripts.launch_onyx_live_v19",
            "scripts.launch_onyx_live_v20",
            "scripts.launch_onyx_live_v21",
            "scripts.launch_onyx_live_v22",
            "scripts.launch_onyx_live_v23",
        ):
            preflight.load(name)
        modules = preflight.runtime_modules
        assert finder.calls == 0
        seal = activation._AUTHENTICATED_SOURCE_SEAL
        assert all(
            module.__dict__.get("__onyx_authenticated_source_seal__") is seal
            for module in modules
        )
        owned_names = tuple(module.__name__ for module in preflight.closure_modules)
        preflight.close()
        assert all(name not in sys.modules for name in owned_names)
        """
    )
    assert result.returncode == 0, result.stderr


def test_clean_subprocess_rejects_concurrent_preflight_and_restores_after_close() -> None:
    result = _clean_subprocess(
        """
        import site
        import sys
        from pathlib import Path

        root = Path.cwd()
        site.addsitedir(site.getusersitepackages())
        sys.path.insert(0, str(root))
        from core import onyx_live_activation_google_workspace_v1 as activation

        environment = {
            activation.LIVE_FLAG: "true",
            activation.CONNECTOR_FLAG: "true",
            "ONYX_GOOGLE_WORKSPACE_OWNER_ID": "owner-primary",
            "ONYX_GOOGLE_WORKSPACE_WORKSPACE_ID": "workspace-personal",
            "ONYX_GOOGLE_WORKSPACE_ACCOUNT_ID": "owner@example.com",
            "ONYX_GOOGLE_WORKSPACE_CLIENT_ID": "client-id.apps.googleusercontent.com",
            "ONYX_GOOGLE_WORKSPACE_CALLBACK_PORT": "8765",
        }
        first = activation.preflight_source_environment_v1(environment)
        try:
            activation.preflight_source_environment_v1(environment)
        except activation.GoogleWorkspaceActivationV1Error as error:
            assert "imported before" in str(error)
        else:
            raise AssertionError("concurrent provenance session was accepted")
        first.close()
        second = activation.preflight_source_environment_v1(environment)
        second.close()
        """
    )
    assert result.returncode == 0, result.stderr


def test_source_session_finder_drift_retains_retry_authority() -> None:
    result = _clean_subprocess(
        """
        import site
        import sys
        from pathlib import Path

        root = Path.cwd()
        site.addsitedir(site.getusersitepackages())
        sys.path.insert(0, str(root))
        from core import onyx_live_activation_google_workspace_v1 as activation

        environment = {
            activation.LIVE_FLAG: "true",
            activation.CONNECTOR_FLAG: "true",
            "ONYX_GOOGLE_WORKSPACE_OWNER_ID": "owner-primary",
            "ONYX_GOOGLE_WORKSPACE_WORKSPACE_ID": "workspace-personal",
            "ONYX_GOOGLE_WORKSPACE_ACCOUNT_ID": "owner@example.com",
            "ONYX_GOOGLE_WORKSPACE_CLIENT_ID": "client-id.apps.googleusercontent.com",
            "ONYX_GOOGLE_WORKSPACE_CALLBACK_PORT": "8765",
        }
        session = activation.preflight_source_environment_v1(environment)
        finder = session._finder
        owned = session.closure_modules
        sys.meta_path.remove(finder)
        try:
            session.close()
        except activation.GoogleWorkspaceActivationV1Error as error:
            assert "rollback is pending" in str(error)
        else:
            raise AssertionError("finder drift was reported as clean rollback")
        assert session._active is True
        assert session._finder is finder
        assert session.closure_modules == owned
        sys.meta_path.insert(0, finder)
        session.close()
        assert session._active is False
        """
    )
    assert result.returncode == 0, result.stderr


def test_source_session_module_drift_retains_retry_authority() -> None:
    result = _clean_subprocess(
        """
        import site
        import sys
        from pathlib import Path
        from types import ModuleType

        root = Path.cwd()
        site.addsitedir(site.getusersitepackages())
        sys.path.insert(0, str(root))
        from core import onyx_live_activation_google_workspace_v1 as activation

        environment = {
            activation.LIVE_FLAG: "true",
            activation.CONNECTOR_FLAG: "true",
            "ONYX_GOOGLE_WORKSPACE_OWNER_ID": "owner-primary",
            "ONYX_GOOGLE_WORKSPACE_WORKSPACE_ID": "workspace-personal",
            "ONYX_GOOGLE_WORKSPACE_ACCOUNT_ID": "owner@example.com",
            "ONYX_GOOGLE_WORKSPACE_CLIENT_ID": "client-id.apps.googleusercontent.com",
            "ONYX_GOOGLE_WORKSPACE_CALLBACK_PORT": "8765",
        }
        session = activation.preflight_source_environment_v1(environment)
        owned = session.closure_modules[-1]
        name = owned.__name__
        sys.modules[name] = ModuleType(name)
        try:
            session.close()
        except activation.GoogleWorkspaceActivationV1Error:
            pass
        else:
            raise AssertionError("module drift was reported as clean rollback")
        assert session._active is True
        assert session._finder is not None
        sys.modules[name] = owned
        session.close()
        assert session._active is False
        """
    )
    assert result.returncode == 0, result.stderr


def test_no_free_caller_supplied_captured_loader_seam_exists() -> None:
    assert not hasattr(gws_activation, "_execute_captured_module")
    assert not hasattr(gws_activation, "_load_enabled_runtime_v1")
    for name, value in vars(gws_activation).items():
        if inspect.isfunction(value) and name != "_captured_local_closure":
            assert "captured" not in inspect.signature(value).parameters


def test_clean_subprocess_stable_reader_rejects_path_swap() -> None:
    result = _clean_subprocess(
        """
        import shutil
        import sys
        import tempfile
        from pathlib import Path

        root = Path.cwd()
        sys.path.insert(0, str(root))
        from core import onyx_live_activation_google_workspace_v1 as activation

        parent = root / ".codex-tmp"
        parent.mkdir(exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix="gws-path-swap-", dir=parent))
        try:
            target = temporary / "target.py"
            replacement = temporary / "replacement.py"
            retired = temporary / "retired.py"
            target.write_bytes(b"trusted = True\\n")
            replacement.write_bytes(b"trusted = False")
            original_open = activation.os.open
            swapped = False
            def swapping_open(path, flags, *args):
                global swapped
                if not swapped and Path(path) == target:
                    swapped = True
                    target.replace(retired)
                    replacement.replace(target)
                return original_open(path, flags, *args)
            activation.os.open = swapping_open
            try:
                activation._stable_regular_bytes(
                    Path("target.py"), root=temporary
                )
            except activation.GoogleWorkspaceActivationV1Error as error:
                assert "changed" in str(error)
                assert error.__cause__ is None
                assert error.__context__ is None
            else:
                raise AssertionError("path swap was accepted")
        finally:
            shutil.rmtree(temporary)
        """
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("global_name", ["V24_SHA256", "_V23_SHA256"])
def test_clean_subprocess_rejects_mutated_activation_globals(
    global_name: str,
) -> None:
    result = _clean_subprocess(
        f"""
        import sys
        from pathlib import Path

        root = Path.cwd()
        sys.path.insert(0, str(root))
        from core import onyx_live_activation_google_workspace_v1 as activation

        activation.{global_name} = "0" * 64
        environment = {{
            activation.LIVE_FLAG: "true",
            activation.CONNECTOR_FLAG: "true",
        }}
        try:
            activation.preflight_source_environment_v1(environment)
        except activation.GoogleWorkspaceActivationV1Error as error:
            assert "critical globals" in str(error)
            assert error.__cause__ is None
            assert error.__context__ is None
        else:
            raise AssertionError("mutable activation globals were accepted")
        """
    )
    assert result.returncode == 0, result.stderr


def test_clean_subprocess_bootstrap_rejects_preloaded_fake_activation() -> None:
    result = _clean_subprocess(
        """
        import runpy
        import site
        import sys
        from pathlib import Path
        from types import ModuleType

        root = Path.cwd()
        site.addsitedir(site.getusersitepackages())
        bootstrap = runpy.run_path(
            str(root / "scripts" / "bootstrap_onyx_live_google_workspace_v1.pyw"),
            run_name="gws_preloaded_activation_probe",
        )
        sys.modules["core.onyx_live_activation_google_workspace_v1"] = ModuleType(
            "core.onyx_live_activation_google_workspace_v1"
        )
        launcher = bootstrap["_execute_verified"](
            bootstrap["LAUNCHER"],
            bootstrap["LAUNCHER_SHA256"],
            "gws_preloaded_activation_launcher_probe",
        )
        try:
            launcher["_activation_contract"]()
        except RuntimeError as error:
            assert "preloaded" in str(error)
            assert error.__cause__ is None
            assert error.__context__ is None
        else:
            raise AssertionError("preloaded fake activation was accepted")
        """
    )
    assert result.returncode == 0, result.stderr


def test_bootstrap_local_verifier_rejects_mutated_activation_class() -> None:
    result = _clean_subprocess(
        """
        import runpy
        import site
        import sys
        from pathlib import Path

        root = Path.cwd()
        site.addsitedir(site.getusersitepackages())
        bootstrap = runpy.run_path(
            str(root / "scripts" / "bootstrap_onyx_live_google_workspace_v1.pyw"),
            run_name="gws_mutated_class_probe",
        )
        launcher = bootstrap["_execute_verified"](
            bootstrap["LAUNCHER"],
            bootstrap["LAUNCHER_SHA256"],
            "gws_mutated_activation_launcher_probe",
        )
        module = launcher["_activation_contract"]()
        source = launcher["_verified_source"](
            launcher["ACTIVATION"], launcher["ACTIVATION_SHA256"]
        )
        module.OnyxLiveActivationGoogleWorkspaceV1.install = lambda self: None
        try:
            launcher["_verify_local_module"](
                module,
                source,
                launcher["ACTIVATION"],
                module.__dict__["_AUTHENTICATED_SOURCE_SEAL"],
            )
        except RuntimeError as error:
            assert "class drifted" in str(error)
            assert error.__cause__ is None
            assert error.__context__ is None
        else:
            raise AssertionError("mutated activation class was accepted")
        """
    )
    assert result.returncode == 0, result.stderr


def test_default_off_bootstrap_delegates_without_manifest_or_google_import(
) -> None:
    result = _clean_subprocess(
        """
        import runpy
        import site
        import sys
        import tempfile
        from pathlib import Path

        root = Path.cwd()
        site.addsitedir(site.getusersitepackages())
        sys.path.insert(0, str(root))
        temporary = tempfile.TemporaryDirectory()
        data_root = Path(temporary.name) / "data"
        data_root.mkdir()
        output = Path(temporary.name) / "native-source-harness.json"
        __import__("os").environ["ONYX_DATA_DIR"] = str(data_root)
        __import__("os").environ["ONYX_NATIVE_STARTUP_SMOKE_OUTPUT"] = str(output)
        import json
        import core.native_startup_smoke_v1 as native_smoke
        def controlled_source_smoke():
            assert sys.argv[1:] == [native_smoke.NATIVE_STARTUP_SMOKE_ARGUMENT]
            payload = {
                "contract": native_smoke.NATIVE_STARTUP_SMOKE_CONTRACT,
                "evidence_scope": "source-only-controlled-launcher-harness",
                "status": "passed",
            }
            output.write_text(json.dumps(payload), encoding="utf-8")
            return payload
        native_smoke.run_terminal_native_startup_smoke_v1 = controlled_source_smoke
        bootstrap_path = root / "scripts" / "bootstrap_onyx_live_google_workspace_v1.pyw"
        for name in (
            "ONYX_GOOGLE_WORKSPACE_LIVE_V1",
            "ONYX_GOOGLE_WORKSPACE_CONNECTOR_V1",
        ):
            __import__("os").environ.pop(name, None)
        before = {
            name for name in sys.modules
            if name.startswith("core.google_workspace_")
        }
        sys.argv = [str(bootstrap_path), "--native-startup-smoke-test"]
        runpy.run_path(str(bootstrap_path), run_name="__main__")
        after = {
            name for name in sys.modules
            if name.startswith("core.google_workspace_")
        }
        assert after == before
        assert output.is_file()
        """
    )
    assert result.returncode == 0, result.stderr


def test_default_tool_audit_schema_has_no_google_objects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tool_audit, "AUDIT_PATH", tmp_path / "tool-audit.sqlite3")
    database = tool_audit._connect()
    try:
        names = {
            str(row[0]).casefold()
            for row in database.execute("SELECT name FROM sqlite_master")
        }
    finally:
        database.close()
    assert not {name for name in names if "google" in name}


def _activation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    close_fails: bool = False,
):
    _remove_policy()
    module = ModuleType("google_workspace_activation_test_host")
    module.TOOL_DECLARATIONS = []

    class Response:
        def __init__(self, *, id, name, response):
            self.id = id
            self.name = name
            self.response = response

    class Host:
        def __init__(self, ui):
            self.ui = ui
            self._external_action_tasks = set()

        async def _execute_tool(self, function_call):
            return Response(
                id=function_call.id,
                name=function_call.name,
                response={"legacy": True},
            )

        async def _run_external_action(self, action, /, *args, **kwargs):
            return action(*args, **kwargs)

        def close(self):
            self.closed = True

        @staticmethod
        def _runtime_input_is_quiesced():
            return False

    module.OnyxLive = Host
    module.types = SimpleNamespace(FunctionResponse=Response)
    module.authorize_model_tool = lambda _tool, _arguments: (True, "c" * 64)

    base_contract = object.__new__(v24.HostContractV24)
    object.__setattr__(base_contract, "module", module)
    object.__setattr__(base_contract, "project", ROOT)
    object.__setattr__(base_contract, "base", SimpleNamespace(onyx_live=Host))
    contract = gws_activation.GoogleWorkspaceHostContractV1(
        module, Host, ROOT, base_contract
    )
    preflight = SimpleNamespace(
        v24=v24,
        configuration=gws_activation.GoogleWorkspaceRawConfigurationV1(
            "owner-primary",
            "workspace-personal",
            "owner@example.com",
            "client-id.apps.googleusercontent.com",
            8765,
        ),
        base_environment=v24.exact_activation_environment((ROOT,)),
        aggregate_sha256=gws_activation.EXPECTED_AGGREGATE,
        runtime_modules=(
            paths_module,
            tool_audit,
            permission_broker,
            native_vault,
            connector_module,
            host_module,
            live_module,
            audit_module,
        ),
        closure_modules=(),
        assert_healthy=lambda: None,
        accept_v24_runtime_mutations=lambda: None,
        close=lambda: None,
    )
    state = SimpleNamespace(
        connected=True,
        service_closed=0,
        base_installed=False,
        base_rollbacks=0,
    )

    def fake_base_init(self, _flags, _contract):
        self.contract = SimpleNamespace(module=module)

    def fake_base_install(self):
        state.base_installed = True

    def fake_base_instantiate(self, ui):
        instance = Host(ui)
        session = object.__new__(phase6.LiveWiringSessionV1)
        object.__setattr__(
            session,
            "identity",
            phase6.LiveWiringIdentityV1(
                "workspace-personal",
                "account-primary",
                "owner-primary",
                "principal-primary",
            ),
        )
        object.__setattr__(session, "_closed", False)
        setattr(instance, phase6.SESSION_ATTRIBUTE, session)
        return instance

    def fake_base_rollback(self):
        state.base_rollbacks += 1
        state.base_installed = False
        if getattr(module, gws_activation.V24_MARKER, None) is self:
            delattr(module, gws_activation.V24_MARKER)

    monkeypatch.setattr(v24.OnyxLiveActivationV24, "__init__", fake_base_init)
    monkeypatch.setattr(v24.OnyxLiveActivationV24, "install", fake_base_install)
    monkeypatch.setattr(
        v24.OnyxLiveActivationV24, "instantiate_live", fake_base_instantiate
    )
    monkeypatch.setattr(v24.OnyxLiveActivationV24, "rollback_all", fake_base_rollback)

    service = object.__new__(GoogleWorkspaceHostServiceV1)
    connector = object.__new__(connector_module.GoogleWorkspaceConnectorV1)
    configuration_binding = connector_module.GoogleWorkspaceBindingV1(
        "owner-primary", "workspace-personal", "owner@example.com"
    )
    connector._binding = configuration_binding
    connector._binding_digest = _BINDING
    service._connector = connector

    def status(_self):
        return GoogleWorkspaceHostStatusV1(
            True,
            True,
            state.connected,
            "source-test",
            _BINDING,
            1,
            "available",
            READ_SCOPES,
            False,
            "connected" if state.connected else "revoked",
        )

    def close(_self):
        state.service_closed += 1
        if close_fails:
            raise RuntimeError("injected close failure secret")

    monkeypatch.setattr(GoogleWorkspaceHostServiceV1, "status", status)
    monkeypatch.setattr(GoogleWorkspaceHostServiceV1, "close", close)
    monkeypatch.setattr(
        permission_broker,
        "authorize_model_tool_decision_only",
        lambda _tool, _arguments: (True, "c" * 64),
    )
    factory_calls = []

    def factory(**kwargs):
        assert module.TOOL_DECLARATIONS == []
        assert not hasattr(Host, gws_activation.HOST_MARKER)
        assert not hasattr(module, gws_activation.MODULE_MARKER)
        assert gws_activation.TOOL_NAME not in permission_broker.MODEL_TOOL_POLICIES
        factory_calls.append(kwargs)
        return service

    class AuditStore:
        def reserve(self, **_kwargs):
            return SimpleNamespace(state="claimed", result=None)

        def record_denied(self, **kwargs):
            return SimpleNamespace(
                trace_id=kwargs["trace_id"], event_hash="9" * 64
            )

        def finalize(self, **_kwargs):
            return SimpleNamespace(event_hash="a" * 64)

        def verify(self, **_kwargs):
            return True

        def close(self):
            state.audit_closed = getattr(state, "audit_closed", 0) + 1

    activation = object.__new__(
        gws_activation.OnyxLiveActivationGoogleWorkspaceV1
    )
    activation._paths_module = paths_module
    activation._permission = permission_broker
    activation._native_vault = native_vault
    activation._connector_module = connector_module
    activation._host_module = host_module
    activation._live_module = live_module
    activation._audit_module = SimpleNamespace(
        GoogleWorkspaceAuditStoreV1=lambda **_kwargs: AuditStore()
    )
    activation.preflight = preflight
    activation.contract = contract
    activation._base = v24.OnyxLiveActivationV24(None, None)
    activation._configuration = host_module.GoogleWorkspaceHostConfigurationV1(
        configuration_binding,
        "client-id.apps.googleusercontent.com",
        8765,
    )
    activation._factory = factory
    activation._host_service_type = GoogleWorkspaceHostServiceV1
    activation._service = None
    activation._adapter = None
    activation._declaration = None
    activation._policy_lease = None
    activation._audit_store = None
    activation._installed = False
    activation._bindings = []
    activation._lock = threading.RLock()
    activation._state = "new"
    activation._accepting_dispatch = False
    activation._executor = None
    activation._futures = set()
    activation._tasks = set()
    activation._pending_instances = []
    activation._base_started = False
    activation._source_session_closed = False
    activation._generation = 0
    monkeypatch.setattr(activation, "_stable_audit_key", lambda _digest: b"k" * 32)
    return module, Host, activation, state, factory_calls


def test_public_controller_constructor_is_not_a_production_injection_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, activation, _state, _calls = _activation(monkeypatch)
    assert tuple(
        inspect.signature(
            gws_activation.OnyxLiveActivationGoogleWorkspaceV1.__init__
        ).parameters
    ) == ("self", "environ")
    assert tuple(inspect.signature(gws_activation.activate_main).parameters) == (
        "environ",
    )
    for forbidden in (
        "_construct_controller",
        "_controller_authority",
        "_activate_main_with_capability",
    ):
        assert not hasattr(gws_activation, forbidden)
    with pytest.raises(TypeError):
        gws_activation.OnyxLiveActivationGoogleWorkspaceV1(
            preflight=activation.preflight,
            contract=activation.contract,
        )


def test_activate_main_retains_deterministic_pending_cleanup_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, activation, _state, _calls = _activation(monkeypatch)
    original_type = gws_activation.OnyxLiveActivationGoogleWorkspaceV1
    attempts = 0
    allow_cleanup = False

    def install() -> None:
        activation._state = "rollback_pending"
        raise RuntimeError("construction secret")

    def rollback() -> None:
        nonlocal attempts
        attempts += 1
        if not allow_cleanup:
            raise gws_activation.GoogleWorkspaceActivationV1Error(
                "cleanup secret"
            )
        activation._state = "rolled_back"

    activation.install = install
    activation.rollback_all = rollback
    monkeypatch.setattr(
        gws_activation,
        "OnyxLiveActivationGoogleWorkspaceV1",
        lambda _environment=None: activation,
    )
    with pytest.raises(gws_activation.GoogleWorkspaceActivationV1Error):
        gws_activation.activate_main(_environment())
    assert attempts == 3
    assert gws_activation._PENDING_ACTIVATION_CONTROLLER is activation
    monkeypatch.setattr(
        gws_activation, "OnyxLiveActivationGoogleWorkspaceV1", original_type
    )
    allow_cleanup = True
    assert gws_activation.retry_pending_activation_cleanup_v1() is True
    assert gws_activation._PENDING_ACTIVATION_CONTROLLER is None


def test_policy_lease_registration_is_failure_atomic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = "google_workspace_failure_atomic_probe"

    class FailingActions(dict):
        def __setitem__(self, key, value):
            if key == tool:
                raise RuntimeError("injected registry failure")
            return super().__setitem__(key, value)

    monkeypatch.setattr(
        permission_broker,
        "MODEL_TOOL_ACTIONS",
        FailingActions(permission_broker.MODEL_TOOL_ACTIONS),
    )
    with pytest.raises(RuntimeError, match="injected registry failure"):
        permission_broker.register_model_tool_policy_lease(
            tool=tool,
            policy="action_policy",
            actions=frozenset({"connect"}),
            autonomous_actions=frozenset(),
        )
    assert tool not in permission_broker.MODEL_TOOL_POLICIES
    assert tool not in permission_broker.MODEL_TOOL_ACTIONS
    assert tool not in permission_broker._AUTONOMOUS_ACTIONS


def test_unhealthy_audit_denies_consequential_policy_decision() -> None:
    tool = "google_workspace_audit_health_probe"
    lease = permission_broker.register_model_tool_policy_lease(
        tool=tool,
        policy="action_policy",
        actions=frozenset({"connect", "status"}),
        autonomous_actions=frozenset({"status"}),
    )
    healthy = permission_broker._audit_healthy
    try:
        permission_broker._audit_healthy = False
        allowed, reason = permission_broker.authorize_model_tool_decision_only(
            tool, {"action": "connect"}
        )
        assert allowed is False
        assert "audit is unhealthy" in reason
    finally:
        permission_broker._audit_healthy = healthy
        permission_broker.release_model_tool_policy_lease(lease)


def test_source_only_enabled_smoke_constructs_service_instance_and_protected_dispatcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, host, activation, state, factory_calls = _activation(monkeypatch)
    original_dispatch = host._execute_tool
    activation.install()
    assert activation._service is not None
    assert activation._audit_store is not None
    assert activation._adapter is not None
    assert activation._executor is not None
    assert len(factory_calls) == 1
    instance = activation.instantiate_live(
        SimpleNamespace(muted=True, set_state=lambda _state: None)
    )
    assert len(factory_calls) == 1
    assert type(factory_calls[0]["gate"]) is GoogleWorkspaceFeatureGateV1
    assert factory_calls[0]["gate"].enabled is True
    assert [item["name"] for item in module.TOOL_DECLARATIONS] == [
        gws_activation.TOOL_NAME
    ]
    assert permission_broker.MODEL_TOOL_POLICIES[gws_activation.TOOL_NAME] == (
        "action_policy"
    )
    assert permission_broker._AUTONOMOUS_ACTIONS[gws_activation.TOOL_NAME] == (
        frozenset({"status", "list_gmail_messages", "list_calendar_events"})
    )
    result = asyncio.run(
        instance._execute_tool(
            SimpleNamespace(
                id="gws-status",
                name=gws_activation.TOOL_NAME,
                args={"action": "status"},
            )
        )
    )
    legacy = asyncio.run(
        instance._execute_tool(
            SimpleNamespace(id="legacy", name="legacy", args={})
        )
    )
    assert result.response["status"] == "succeeded"
    assert legacy.response == {"legacy": True}
    activation.rollback_all()
    assert type(instance) is host
    assert host._execute_tool is original_dispatch
    assert module.TOOL_DECLARATIONS == []
    assert gws_activation.TOOL_NAME not in permission_broker.MODEL_TOOL_POLICIES
    assert state.service_closed == 1
    assert state.base_rollbacks == 1


@pytest.mark.parametrize("fail_after", [1, 2, 3, 4, 5, 6])
def test_every_install_boundary_rolls_back_only_owned_resources(
    monkeypatch: pytest.MonkeyPatch, fail_after: int
) -> None:
    module, host, activation, state, _factory_calls = _activation(monkeypatch)
    original_dispatch = host._execute_tool
    with pytest.raises(gws_activation.GoogleWorkspaceActivationV1Error):
        activation.install(fail_after=fail_after)
    assert module.TOOL_DECLARATIONS == []
    assert host._execute_tool is original_dispatch
    assert not hasattr(host, gws_activation.HOST_MARKER)
    assert not hasattr(module, gws_activation.MODULE_MARKER)
    assert gws_activation.TOOL_NAME not in permission_broker.MODEL_TOOL_POLICIES
    assert state.base_rollbacks == 1
    assert state.service_closed == (0 if fail_after == 1 else 1)
    assert getattr(state, "audit_closed", 0) == (0 if fail_after == 1 else 1)


def test_cleanup_failure_never_becomes_success_and_preserves_clean_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, activation, _state, _factory_calls = _activation(
        monkeypatch, close_fails=True
    )
    activation.install()
    activation.instantiate_live(
        SimpleNamespace(muted=True, set_state=lambda _state: None)
    )
    with pytest.raises(gws_activation.GoogleWorkspaceActivationV1Error) as raised:
        activation.rollback_all()
    assert "secret" not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_partial_service_construction_cleanup_is_retained_and_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, activation, state, _factory_calls = _activation(monkeypatch)
    failures = 1

    def close_once(_self):
        nonlocal failures
        state.service_closed += 1
        if failures:
            failures -= 1
            raise RuntimeError("construction close secret")

    monkeypatch.setattr(GoogleWorkspaceHostServiceV1, "close", close_once)
    activation._audit_module = SimpleNamespace(
        GoogleWorkspaceAuditStoreV1=lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("audit construction secret")
        )
    )
    with pytest.raises(gws_activation.GoogleWorkspaceActivationV1Error) as raised:
        activation.install()
    assert activation._service is None
    assert activation._adapter is None
    assert state.service_closed == 2
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert activation._state == "rolled_back"
    assert activation.contract.module.TOOL_DECLARATIONS == []
    assert state.base_rollbacks == 1


def test_partial_audit_store_cleanup_is_retained_and_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, activation, state, _factory_calls = _activation(monkeypatch)

    class RetryingAuditStore:
        def __init__(self) -> None:
            self.close_calls = 0

        def close(self) -> None:
            self.close_calls += 1
            if self.close_calls == 1:
                raise RuntimeError("audit close secret")

    audit_store = RetryingAuditStore()
    activation._audit_module = SimpleNamespace(
        GoogleWorkspaceAuditStoreV1=lambda **_kwargs: audit_store
    )
    monkeypatch.setattr(
        live_module,
        "GoogleWorkspaceLiveAdapterV1",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("adapter secret")),
    )
    with pytest.raises(gws_activation.GoogleWorkspaceActivationV1Error) as raised:
        activation.install()
    assert activation._service is None
    assert activation._audit_store is None
    assert audit_store.close_calls == 2
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert activation._state == "rolled_back"
    assert activation.contract.module.TOOL_DECLARATIONS == []
    assert state.base_rollbacks == 1


def test_failed_instance_close_is_retained_and_retried_by_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, activation, state, _factory_calls = _activation(monkeypatch)
    activation.install()
    instance = activation._base.instantiate_live(
        SimpleNamespace(muted=True, set_state=lambda _state: None)
    )
    close_calls = 0

    def close_once():
        nonlocal close_calls
        close_calls += 1
        if close_calls == 1:
            raise RuntimeError("instance close secret")
        instance.closed = True

    instance.close = close_once
    monkeypatch.setattr(
        activation._base, "instantiate_live", lambda _ui: instance
    )
    monkeypatch.setattr(
        activation,
        "_bind_instance",
        lambda _instance: (_ for _ in ()).throw(RuntimeError("bind secret")),
    )
    with pytest.raises(gws_activation.GoogleWorkspaceActivationV1Error) as raised:
        activation.instantiate_live(instance.ui)
    assert activation._pending_instances == [instance]
    assert close_calls == 1
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    with pytest.raises(gws_activation.GoogleWorkspaceActivationV1Error):
        activation.instantiate_live(instance.ui)
    activation.rollback_all()
    assert close_calls == 2
    assert instance.closed is True
    assert activation._pending_instances == []
    assert state.base_rollbacks == 1


def test_base_install_exception_always_attempts_predecessor_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, activation, state, _factory_calls = _activation(monkeypatch)

    def fail_install(_self):
        raise RuntimeError("base secret")

    monkeypatch.setattr(v24.OnyxLiveActivationV24, "install", fail_install)
    with pytest.raises(gws_activation.GoogleWorkspaceActivationV1Error) as raised:
        activation.install()
    assert state.base_rollbacks == 1
    assert activation._state == "rolled_back"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_foreign_equal_policy_replacement_is_never_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, activation, state, _factory_calls = _activation(monkeypatch)
    activation.install()
    owned_policy = permission_broker.MODEL_TOOL_POLICIES[
        gws_activation.TOOL_NAME
    ]
    permission_broker.MODEL_TOOL_POLICIES[gws_activation.TOOL_NAME] = (
        "action_policy"
    )
    with pytest.raises(gws_activation.GoogleWorkspaceActivationV1Error):
        activation.rollback_all()
    assert (
        permission_broker.MODEL_TOOL_POLICIES[gws_activation.TOOL_NAME]
        == "action_policy"
    )
    assert state.base_rollbacks == 0
    permission_broker.MODEL_TOOL_POLICIES[gws_activation.TOOL_NAME] = (
        owned_policy
    )
    activation.rollback_all()
    assert state.base_rollbacks == 1


def test_foreign_equal_declaration_replacement_is_never_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, _host, activation, state, _factory_calls = _activation(monkeypatch)
    activation.install()
    owned = activation._declaration
    foreign = dict(owned)
    module.TOOL_DECLARATIONS[0] = foreign
    with pytest.raises(gws_activation.GoogleWorkspaceActivationV1Error):
        activation.rollback_all()
    assert module.TOOL_DECLARATIONS == [foreign]
    assert state.base_rollbacks == 0
    module.TOOL_DECLARATIONS[0] = owned
    activation.rollback_all()
    assert state.base_rollbacks == 1


def test_owner_attestation_failure_closes_instance_before_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, host, activation, state, factory_calls = _activation(monkeypatch)
    activation.install()
    instance = host(SimpleNamespace(muted=True, set_state=lambda _state: None))
    session = object.__new__(phase6.LiveWiringSessionV1)
    object.__setattr__(
        session,
        "identity",
        phase6.LiveWiringIdentityV1(
            "workspace-foreign",
            "account-primary",
            "owner-primary",
            "principal-primary",
        ),
    )
    object.__setattr__(session, "_closed", False)
    setattr(instance, phase6.SESSION_ATTRIBUTE, session)
    monkeypatch.setattr(
        activation._base, "instantiate_live", lambda _ui: instance
    )
    with pytest.raises(gws_activation.GoogleWorkspaceActivationV1Error):
        activation.instantiate_live(instance.ui)
    assert instance.closed is True
    assert len(factory_calls) == 1
    activation.rollback_all()
    assert state.base_rollbacks == 1


def test_unexpected_worker_exception_is_unknown_external_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, activation, _state, _factory_calls = _activation(monkeypatch)
    activation.install()
    instance = activation.instantiate_live(
        SimpleNamespace(muted=True, set_state=lambda _state: None)
    )
    calls = 0

    def explode(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("worker secret")

    monkeypatch.setattr(activation._adapter, "execute", explode)
    result = asyncio.run(
        instance._execute_tool(
            SimpleNamespace(
                id="worker-failure",
                name=gws_activation.TOOL_NAME,
                args={"action": "status"},
            )
        )
    )
    assert result.response["status"] == "attempted_unknown"
    assert result.response["external_dispatch"] is True
    assert result.response["idempotency_digest"] == (
        live_module.idempotency_digest_v1("worker-failure")
    )
    assert calls == 1
    activation.rollback_all()


def test_finder_precedence_drift_denies_dispatch_before_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, activation, _state, _factory_calls = _activation(monkeypatch)
    healthy = {"value": True}

    def attest() -> None:
        if not healthy["value"]:
            raise gws_activation.GoogleWorkspaceActivationV1Error(
                "finder precedence drift"
            )

    activation.preflight.assert_healthy = attest
    activation.install()
    instance = activation.instantiate_live(
        SimpleNamespace(muted=True, set_state=lambda _state: None)
    )
    calls = 0

    def execute(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {"unexpected": True}

    monkeypatch.setattr(activation._adapter, "execute", execute)
    healthy["value"] = False
    result = asyncio.run(
        instance._execute_tool(
            SimpleNamespace(
                id="source-drift",
                name=gws_activation.TOOL_NAME,
                args={"action": "status"},
            )
        )
    )
    assert result.response["status"] == "denied"
    assert result.response["external_dispatch"] is False
    assert calls == 0
    healthy["value"] = True
    activation.rollback_all()


def test_dispatch_timeout_reports_exact_reservation_digest_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, activation, _state, _factory_calls = _activation(monkeypatch)
    activation.install()
    instance = activation.instantiate_live(
        SimpleNamespace(muted=True, set_state=lambda _state: None)
    )
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def wait_for_reconciliation(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        release.wait(5)
        return {"unexpected": True}

    monkeypatch.setattr(activation._adapter, "execute", wait_for_reconciliation)
    monkeypatch.setattr(gws_activation, "_DISPATCH_TIMEOUT_SECONDS", 0.01)
    result = asyncio.run(
        instance._execute_tool(
            SimpleNamespace(
                id="timeout-logical-id",
                name=gws_activation.TOOL_NAME,
                args={"action": "status"},
            )
        )
    )
    assert started.is_set()
    assert result.response["status"] == "attempted_unknown"
    assert result.response["external_dispatch"] is True
    assert result.response["idempotency_digest"] == (
        live_module.idempotency_digest_v1("timeout-logical-id")
    )
    assert calls == 1
    release.set()
    activation.rollback_all()


def test_rollback_timeout_is_pending_and_retry_drains_before_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, activation, state, _factory_calls = _activation(monkeypatch)
    activation.install()
    activation.instantiate_live(
        SimpleNamespace(muted=True, set_state=lambda _state: None)
    )
    started = threading.Event()
    release = threading.Event()

    def work():
        started.set()
        release.wait(5)

    future = activation._executor.submit(work)
    activation._futures.add(future)
    assert started.wait(2)
    monkeypatch.setattr(gws_activation, "_ROLLBACK_DRAIN_SECONDS", 0.01)
    with pytest.raises(gws_activation.GoogleWorkspaceActivationV1Error):
        activation.rollback_all()
    assert activation._state == "rollback_pending"
    assert state.service_closed == 0
    assert state.base_rollbacks == 0
    release.set()
    future.result(timeout=2)
    activation.rollback_all()
    assert state.service_closed == 1
    assert state.base_rollbacks == 1


def test_service_close_failure_is_retryable_before_v24_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, activation, state, _factory_calls = _activation(monkeypatch)
    failures = 1

    def close_once(_self):
        nonlocal failures
        state.service_closed += 1
        if failures:
            failures -= 1
            raise RuntimeError("close secret")

    monkeypatch.setattr(GoogleWorkspaceHostServiceV1, "close", close_once)
    activation.install()
    activation.instantiate_live(
        SimpleNamespace(muted=True, set_state=lambda _state: None)
    )
    with pytest.raises(gws_activation.GoogleWorkspaceActivationV1Error):
        activation.rollback_all()
    assert activation._state == "rollback_pending"
    assert state.base_rollbacks == 0
    activation.rollback_all()
    assert state.service_closed == 2
    assert state.base_rollbacks == 1


def test_source_close_retry_never_repeats_successful_v24_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, _host, activation, state, _factory_calls = _activation(monkeypatch)
    source_close_calls = 0

    def nonrepeatable_base_rollback(_self):
        if state.base_rollbacks:
            raise AssertionError("V24 rollback was repeated")
        state.base_rollbacks += 1
        state.base_installed = False
        if getattr(module, gws_activation.V24_MARKER, None) is activation._base:
            delattr(module, gws_activation.V24_MARKER)

    def source_close_once():
        nonlocal source_close_calls
        source_close_calls += 1
        if source_close_calls == 1:
            raise RuntimeError("source close secret")

    monkeypatch.setattr(
        v24.OnyxLiveActivationV24,
        "rollback_all",
        nonrepeatable_base_rollback,
    )
    activation.preflight.close = source_close_once
    activation.install()

    with pytest.raises(
        gws_activation.GoogleWorkspaceActivationV1Error,
        match="source session rollback is pending",
    ):
        activation.rollback_all()
    assert activation._state == "rollback_pending"
    assert activation._base_started is False
    assert activation._source_session_closed is False
    assert state.base_rollbacks == 1
    assert source_close_calls == 1

    activation.rollback_all()
    assert activation._state == "rolled_back"
    assert activation._source_session_closed is True
    assert state.base_rollbacks == 1
    assert source_close_calls == 2


def test_v24_source_and_scripts_remain_byte_exact() -> None:
    expected = {
        "core/onyx_live_activation_v24.py": gws_activation.V24_SHA256,
        "scripts/bootstrap_onyx_live_v24.pyw": (
                "9bf8bbb7b1417d733d5218845c35ebe8daa39b22b8ac2d5102c3e44ccc343228"
        ),
        "scripts/launch_onyx_live_v24.pyw": (
            "713a7812b110364f2846d9a9571d059e26a8d224a2a765f0ba46e1661ea4ed27"
        ),
    }
    assert {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in expected
    } == expected
