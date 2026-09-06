from __future__ import annotations

import json
import os
import runpy
import subprocess
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from core import governance_nucleus_v1 as governance
from core import onyx_live_activation_v16 as v16
from core import onyx_live_activation_v17 as v17
from core import onyx_live_activation_v18 as v18
from core import permission_broker


ROOT = Path(__file__).resolve().parents[1]


def _hollow_v17_flags() -> v17.ActivationFlagsV17:
    governance_flags = object.__new__(v16.ActivationFlagsV16)
    object.__setattr__(governance_flags, "base", object())
    return v17.ActivationFlagsV17(True, True, governance_flags)


def _activation(monkeypatch: pytest.MonkeyPatch):
    module = ModuleType("v18_test_host")

    class Host:
        def _start_phase5_session(self):
            return None

        def _stop_phase5_session(self):
            return None

        def _execute_tool(self):
            return None

    module.OnyxLive = Host
    module.TOOL_DECLARATIONS = []
    base_contract = v17.HostContractV17(module, Host, ROOT, object())  # type: ignore[arg-type]
    contract = v18.HostContractV18(module, Host, ROOT, base_contract)

    def fake_init(self, *_args, **_kwargs):
        self._installed = False

    def fake_install(self, *, fail_after=None):
        self._installed = fail_after is None

    monkeypatch.setattr(v17.OnyxLiveActivationV17, "__init__", fake_init)
    monkeypatch.setattr(v17.OnyxLiveActivationV17, "install", fake_install)
    controller = v18.OnyxLiveActivationV18(
        v18.ActivationFlagsV18(True, True, _hollow_v17_flags()),
        contract,
    )
    return module, Host, controller


def test_v18_import_is_default_off_and_restores_exact_v17() -> None:
    inactive = {"UNCHANGED": "yes"}
    assert v18.restore_v17_environment(inactive) == inactive
    with pytest.raises(v18.ActivationV18Error, match="not canonical V18"):
        v18.ActivationFlagsV18.from_canonical_environ(inactive)
    mixed = {
        "UNCHANGED": "yes",
        v18.LIVE_MASTER_FLAG: "1",
        v18.FEATURE_FLAG: "true",
        v18.LIVE_ROLLBACK_FLAG: "1",
    }
    assert v18.restore_v17_environment(mixed) == {"UNCHANGED": "yes"}


def test_v18_install_is_official_and_rolls_back_exactly_to_v17(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, host, controller = _activation(monkeypatch)
    protected = tuple(getattr(host, name) for name in v18._PROTECTED_SEAMS)
    prior = permission_broker.MODEL_TOOL_POLICIES.get("document_intake_read")
    controller.install()
    try:
        assert getattr(host, v18.HOST_MARKER) is controller
        assert tuple(getattr(host, name) for name in v18._PROTECTED_SEAMS) == protected
        assert [item["name"] for item in module.TOOL_DECLARATIONS] == [
            "document_intake_read"
        ]
        assert (
            permission_broker.MODEL_TOOL_POLICIES["document_intake_read"]
            == "always_confirm"
        )
    finally:
        controller.rollback_to_v17()
    assert not hasattr(host, v18.HOST_MARKER)
    assert module.TOOL_DECLARATIONS == []
    assert permission_broker.MODEL_TOOL_POLICIES.get("document_intake_read") == prior


class _CloseableController:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_v18_rollback_restores_none_while_current_barrier_governs_legacy_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading

    from ui import _dispatch_selected_file

    _module, _host, controller = _activation(monkeypatch)
    live_controller = _CloseableController()
    monkeypatch.setattr(
        controller, "_create_controller", lambda _instance: live_controller
    )
    ui = SimpleNamespace(on_file_attachment=None)
    instance = SimpleNamespace(ui=ui)
    owned_calls: list[str] = []
    legacy_calls: list[str] = []
    legacy_called = threading.Event()
    owned = owned_calls.append

    def legacy(message: str) -> None:
        legacy_calls.append(message)
        legacy_called.set()
    controller.install()
    controller.initialize_host(instance)
    controller.bind_file_attachment_callback(instance, owned)
    assert ui.on_file_attachment is owned

    controller.rollback_to_v17()

    assert live_controller.closed is True
    assert ui.on_file_attachment is None
    quiesced_mode = _dispatch_selected_file(
        host_callback=ui.on_file_attachment,
        legacy_model_callback=legacy,
        path=r"C:\owner\legacy.txt",
        filename="legacy.txt",
        suffix="txt",
        size="1 B",
    )
    assert quiesced_mode == "quiesced"
    assert not legacy_called.is_set()
    assert legacy_calls == []

    def dispatch(_label: str, callback, _on_refusal) -> bool:
        callback()
        return True

    live_mode = _dispatch_selected_file(
        host_callback=ui.on_file_attachment,
        legacy_model_callback=legacy,
        path=r"C:\owner\legacy.txt",
        filename="legacy.txt",
        suffix="txt",
        size="1 B",
        runtime_dispatch=dispatch,
    )
    assert live_mode == "legacy-model"
    assert legacy_called.wait(timeout=1)
    assert owned_calls == []
    assert len(legacy_calls) == 1


def test_v18_rollback_restores_exact_prior_callback_without_clobbering_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, controller = _activation(monkeypatch)
    monkeypatch.setattr(
        controller,
        "_create_controller",
        lambda _instance: _CloseableController(),
    )
    def prior(_path):
        return None

    def owned(_path):
        return None

    ui = SimpleNamespace(on_file_attachment=prior)
    instance = SimpleNamespace(ui=ui)
    controller.install()
    controller.initialize_host(instance)
    controller.bind_file_attachment_callback(instance, owned)
    controller.rollback_to_v17()
    assert ui.on_file_attachment is prior

    _module, _host, controller = _activation(monkeypatch)
    monkeypatch.setattr(
        controller,
        "_create_controller",
        lambda _instance: _CloseableController(),
    )
    def replacement(_path):
        return None

    ui = SimpleNamespace(on_file_attachment=prior)
    instance = SimpleNamespace(ui=ui)
    controller.install()
    controller.initialize_host(instance)
    controller.bind_file_attachment_callback(instance, owned)
    ui.on_file_attachment = replacement
    controller.rollback_to_v17()
    assert ui.on_file_attachment is replacement


def test_v18_callback_readback_failure_restores_prior_during_bind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingReadbackUI:
        def __init__(self, prior):
            self._callback = prior
            self._reads = 0

        @property
        def on_file_attachment(self):
            self._reads += 1
            if self._reads > 1:
                raise RuntimeError("injected callback readback failure")
            return self._callback

        @on_file_attachment.setter
        def on_file_attachment(self, value):
            self._callback = value

    _module, _host, controller = _activation(monkeypatch)
    monkeypatch.setattr(
        controller,
        "_create_controller",
        lambda _instance: _CloseableController(),
    )
    def prior(_path):
        return None

    ui = FailingReadbackUI(prior)
    instance = SimpleNamespace(ui=ui)
    controller.install()
    controller.initialize_host(instance)
    with pytest.raises(RuntimeError, match="readback failure"):
        controller.bind_file_attachment_callback(
            instance, lambda _path: None
        )
    assert ui._callback is prior
    assert controller._attachment_callbacks == []
    controller.rollback_to_v17()


@pytest.mark.parametrize("added_seam", [1, 2, 3])
def test_v18_failpoints_restore_exact_v17(
    monkeypatch: pytest.MonkeyPatch, added_seam: int
) -> None:
    module, host, controller = _activation(monkeypatch)
    with pytest.raises(v18.ActivationV18Error, match="injected V18"):
        controller.install(fail_after=controller.BASE_SEAM_COUNT + added_seam)
    assert not hasattr(host, v18.HOST_MARKER)
    assert module.TOOL_DECLARATIONS == []
    assert "document_intake_read" not in permission_broker.MODEL_TOOL_POLICIES


def test_document_intake_policy_is_low_risk_local_read() -> None:
    policy = governance._policy_for(
        "document_intake_read",
        {
            "alias": "strategy",
            "source": "company-strategy",
            "logical_document_id": "strategy",
            "revision_id": "rev-1",
            "filename": "strategy.md",
            "media_type": "text/markdown",
        },
        "account-owner",
    )
    assert (policy.operation, policy.risk, policy.always_explicit) == (
        "read",
        "low",
        False,
    )
    assert policy.egress == "none"


def test_dispatch_is_after_authorization_and_governance_fence() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    approval = source.index("authorize_model_tool, name, approval_args")
    fence = source.index("governance.assert_dispatch_allowed", approval)
    branch = source.index("if name == _DOCUMENT_INTAKE_READ_TOOL", fence)
    read = source.index("controller.execute", branch)
    assert approval < fence < branch < read


def test_production_factory_uses_public_host_authority_only() -> None:
    source = (ROOT / "core/onyx_live_activation_v18.py").read_text(
        encoding="utf-8"
    )
    assert "_authorize_root_for_testing" not in source
    assert "successor_authorities_v17()" in source
    assert "authorize_host_root_v1" in source
    for name in v18._PROTECTED_SEAMS:
        assert f'setattr(self.contract.onyx_live, "{name}"' not in source


def test_v17_successor_authority_is_sealed_and_nonserializable() -> None:
    with pytest.raises(v17.ActivationV17Error, match="binding drift"):
        v17.FounderSuccessorAuthoritiesV17(  # type: ignore[arg-type]
            object(),
            identity=object(),
            workspace_root=ROOT,
            nucleus=object(),
            store=object(),
            aliases=object(),
            sources=object(),
            integrity_key=b"x" * 32,
        )


def _bootstrap_namespace() -> dict[str, object]:
    return runpy.run_path(
        str(ROOT / "scripts/bootstrap_onyx_live_v18.pyw"),
        run_name="onyx_v18_bootstrap_test",
    )


def _launcher_namespace() -> dict[str, object]:
    return runpy.run_path(
        str(ROOT / "scripts/launch_onyx_live_v18.pyw"),
        run_name="onyx_v18_launcher_test",
    )


class _FakeSingleInstance:
    def __init__(
        self, *, acquire_result: bool = True, acquire_error: BaseException | None = None
    ) -> None:
        self.acquire_result = acquire_result
        self.acquire_error = acquire_error
        self.acquire_calls = 0
        self.close_calls = 0

    def acquire(self) -> bool:
        self.acquire_calls += 1
        if self.acquire_error is not None:
            raise self.acquire_error
        return self.acquire_result

    def close(self) -> None:
        self.close_calls += 1


def test_v18_normal_gui_mutex_first_acquires_and_second_exits_cleanly() -> None:
    launcher = _launcher_namespace()
    acquire = launcher["_acquire_gui_mutex_for_mode_v18"]
    first = _FakeSingleInstance()
    guard, proceed = acquire((), factory=lambda: first)
    assert guard is first
    assert proceed is True
    assert (first.acquire_calls, first.close_calls) == (1, 0)
    guard.close()
    assert first.close_calls == 1

    second = _FakeSingleInstance(acquire_result=False)
    guard, proceed = acquire((), factory=lambda: second)
    assert guard is None
    assert proceed is False
    assert (second.acquire_calls, second.close_calls) == (1, 1)


@pytest.mark.parametrize(
    "arguments",
    [
        ("--preflight-only",),
        ("--document-intake-smoke-test",),
        ("--governance-smoke-test",),
        ("--founder-smoke-test",),
    ],
)
def test_v18_diagnostic_modes_do_not_acquire_gui_mutex(
    arguments: tuple[str, ...],
) -> None:
    launcher = _launcher_namespace()
    acquire = launcher["_acquire_gui_mutex_for_mode_v18"]

    def forbidden_factory():
        raise AssertionError("diagnostic modes must not acquire the GUI mutex")

    guard, proceed = acquire(arguments, factory=forbidden_factory)
    assert guard is None
    assert proceed is True


def test_v18_gui_mutex_acquisition_failure_closes_before_propagating() -> None:
    launcher = _launcher_namespace()
    acquire = launcher["_acquire_gui_mutex_for_mode_v18"]
    failed = _FakeSingleInstance(
        acquire_error=RuntimeError("injected mutex acquisition failure")
    )
    with pytest.raises(RuntimeError, match="mutex acquisition failure"):
        acquire((), factory=lambda: failed)
    assert (failed.acquire_calls, failed.close_calls) == (1, 1)


def test_v18_launcher_reuses_v17_mutex_before_live_host_imports() -> None:
    source = (ROOT / "scripts/launch_onyx_live_v18.pyw").read_text(
        encoding="utf-8"
    )
    run_body = source[source.index("def run()") :]
    assert "launch_onyx_live_v17.pyw" in source
    assert "_WindowsSingleInstanceV17" in source
    assert run_body.index("_acquire_gui_mutex_for_mode_v18") < run_body.index(
        "from core.dayops_graph_factory_v1"
    )


def test_v18_bootstrap_non_windows_and_lower_phase_fall_back_to_v17(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = _bootstrap_namespace()
    platform_module = bootstrap["platform"]
    monkeypatch.setattr(platform_module, "system", lambda: "Linux")
    mode, environment = bootstrap["_bootstrap_environment"]({"UNCHANGED": "yes"})
    assert (mode, environment) == ("v17", {"UNCHANGED": "yes"})

    monkeypatch.setattr(platform_module, "system", lambda: "Windows")
    mode, environment = bootstrap["_bootstrap_environment"](
        {"UNCHANGED": "yes", v17.LIVE_MASTER_FLAG: "1"}
    )
    assert (mode, environment) == (
        "v17",
        {"UNCHANGED": "yes", v17.LIVE_MASTER_FLAG: "1"},
    )


def test_v18_bootstrap_windows_default_and_explicit_rollback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bootstrap = _bootstrap_namespace()
    monkeypatch.setattr(bootstrap["platform"], "system", lambda: "Windows")
    bootstrap["_default_workspace_root"] = lambda: tmp_path

    mode, environment = bootstrap["_bootstrap_environment"]({"KEEP": "yes"})
    assert mode == "v18"
    assert environment["KEEP"] == "yes"
    assert environment[v18.LIVE_MASTER_FLAG] == "1"
    assert environment[v18.FEATURE_FLAG] == "true"
    assert v18.LIVE_ROLLBACK_FLAG not in environment

    mode, environment = bootstrap["_bootstrap_environment"](
        {"KEEP": "yes", v18.LIVE_ROLLBACK_FLAG: "1"}
    )
    assert (mode, environment) == ("v17", {"KEEP": "yes"})


def test_v18_bootstrap_refuses_partial_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap = _bootstrap_namespace()
    monkeypatch.setattr(bootstrap["platform"], "system", lambda: "Windows")
    with pytest.raises(RuntimeError, match="PARTIAL_CONFIGURATION_REFUSED"):
        bootstrap["_bootstrap_environment"]({v18.LIVE_MASTER_FLAG: "1"})


def test_stable_bootstrap_advances_to_v24_and_retains_v18() -> None:
    stable = (ROOT / "scripts/bootstrap_onyx.pyw").read_text(encoding="utf-8")
    hygiene = (ROOT / "scripts/package_hygiene.py").read_text(encoding="utf-8")
    build = (ROOT / "scripts/build_release.py").read_text(encoding="utf-8")
    spec = (ROOT / "packaging/onyx.spec").read_text(encoding="utf-8")

    assert 'CURRENT_BOOTSTRAP = ROOT / "scripts" / "bootstrap_onyx_live_v24.pyw"' in stable
    assert "range(8, 25)" in hygiene
    assert "from core.onyx_live_activation_v21 import" in build
    assert '"core.onyx_live_activation_v18"' in spec
    assert '"core.onyx_live_activation_v19"' in spec
    assert '"core.onyx_live_activation_v20"' in spec
    assert '"core.onyx_live_activation_v21"' in spec
    assert '"core.onyx_live_activation_v22"' in spec
    assert '"core.onyx_live_activation_v23"' in spec
    assert '"core.onyx_live_activation_v24"' in spec
    assert '"core.document_intake_live_v1"' in spec


def test_document_intake_smoke_is_routed_and_is_a_release_gate() -> None:
    stable = (ROOT / "scripts/bootstrap_onyx.pyw").read_text(encoding="utf-8")
    bootstrap = (ROOT / "scripts/bootstrap_onyx_live_v18.pyw").read_text(
        encoding="utf-8"
    )
    launcher = (ROOT / "scripts/launch_onyx_live_v18.pyw").read_text(
        encoding="utf-8"
    )
    build = (ROOT / "scripts/build_release.py").read_text(encoding="utf-8")
    for source in (stable, bootstrap, launcher):
        assert v18.DOCUMENT_INTAKE_SMOKE_ARGUMENT in source
    assert "run_document_intake_smoke_v181" in launcher
    assert "write_document_intake_smoke_failure_v181" in launcher
    assert "package_document_intake_smoke_test(validation_bundle)" in build


@pytest.mark.skipif(os.name != "nt", reason="native Windows Document Intake smoke")
def test_document_intake_smoke_bootstrap_is_real_and_reopens() -> None:
    with tempfile.TemporaryDirectory(
        prefix="onyx-v181-pytest-smoke-"
    ) as temporary:
        root = Path(temporary)
        data = root / "data"
        workspace = data / "workspace"
        corpus = data / "attachment-corpus"
        output = data / "document-intake-smoke-v1.json"
        workspace.mkdir(parents=True)
        corpus.mkdir()
        environment = os.environ.copy()
        for name in v18.CONTROL_FLAGS:
            environment.pop(name, None)
        environment.update(v18.exact_activation_environment((workspace,)))
        environment.update(
            {
                "ONYX_DATA_DIR": str(data),
                "QT_QPA_PLATFORM": "offscreen",
                v18.DOCUMENT_INTAKE_SMOKE_CORPUS_ENV: str(corpus),
                v18.DOCUMENT_INTAKE_SMOKE_OUTPUT_ENV: str(output),
            }
        )
        completed = subprocess.run(
            [
                str(ROOT / ".venv/Scripts/python.exe"),
                "scripts/bootstrap_onyx.pyw",
                v18.DOCUMENT_INTAKE_SMOKE_ARGUMENT,
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["contract"] == "OnyxDocumentIntakeSmoke.v1"
    assert payload["status"] == "passed"
    assert payload["first"]["status"] == "completed"
    assert payload["controller_reopen"] == {
        "citations": 4,
        "reopened": True,
        "status": "completed",
    }
    assert payload["trusted_ui_prompts"] == 0
    assert payload["network_calls"] == 0
    assert payload["provider_calls"] == 0
    assert payload["process_calls"] == 0
    serialized = json.dumps(payload, sort_keys=True)
    assert str(root) not in serialized
    assert "artifact_id" not in serialized
    assert "workspace_id" not in serialized
