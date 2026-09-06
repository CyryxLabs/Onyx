from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import subprocess
import threading
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext

import pytest

from core import governance_nucleus_v1 as governance
from core import onyx_live_activation_v15 as v15
from core import onyx_live_activation_v16 as v16
from core import onyx_live_activation_v17 as v17
from core import permission_broker
from core.governance_nucleus_v1 import GovernanceIdentityV1, GovernanceNucleusV1


ROOT = Path(__file__).resolve().parents[1]


def test_v17_import_is_default_off_and_restore_is_exact_v16() -> None:
    inactive = {"UNCHANGED": "yes"}
    assert v17.restore_v16_environment(inactive) == inactive
    with pytest.raises(v17.ActivationV17Error, match="not canonical V17"):
        v17.ActivationFlagsV17.from_canonical_environ(inactive)

    mixed = {
        "UNCHANGED": "yes",
        v17.LIVE_MASTER_FLAG: "1",
        v17.FEATURE_FLAG: "true",
        v17.LIVE_ROLLBACK_FLAG: "1",
    }
    assert v17.restore_v16_environment(mixed) == {"UNCHANGED": "yes"}


def _hollow_base_flags() -> v16.ActivationFlagsV16:
    base = object.__new__(v16.ActivationFlagsV16)
    predecessor = object.__new__(v15.ActivationFlagsV15)
    object.__setattr__(predecessor, "workspace_roots", (str(ROOT),))
    object.__setattr__(base, "base", predecessor)
    return base


def _activation(monkeypatch: pytest.MonkeyPatch):
    module = ModuleType("v17_test_host")

    class Host:
        def _start_phase5_session(self):
            return None

        def _stop_phase5_session(self):
            return None

        def _execute_tool(self):
            return None

    module.OnyxLive = Host
    module.TOOL_DECLARATIONS = []
    base_contract = v16.HostContractV16(module, Host, ROOT, object())  # type: ignore[arg-type]
    contract = v17.HostContractV17(module, Host, ROOT, base_contract)

    def fake_init(self, *_args, **_kwargs):
        self._installed = False

    def fake_install(self, *, fail_after=None):
        self._installed = fail_after is None

    monkeypatch.setattr(v16.OnyxLiveActivationV16, "__init__", fake_init)
    monkeypatch.setattr(v16.OnyxLiveActivationV16, "install", fake_install)
    controller = v17.OnyxLiveActivationV17(
        v17.ActivationFlagsV17(True, True, _hollow_base_flags()),
        contract,
    )
    return module, Host, controller


def test_v17_declaration_has_only_closed_public_arguments() -> None:
    declaration = v17.tool_declaration_v17()
    assert declaration["name"] == v17.TOOL_NAME
    parameters = declaration["parameters"]
    assert parameters["required"] == ["cadence", "manifest_ref"]
    assert set(parameters["properties"]) == {"cadence", "manifest_ref"}
    assert parameters["properties"]["cadence"]["enum"] == ["daily", "weekly"]
    text = repr(declaration).casefold()
    assert "workspace_id" not in text
    assert "principal_id" not in text
    assert "absolute" not in text


def test_v17_install_is_official_marker_only_and_rolls_back_to_v16(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, host, controller = _activation(monkeypatch)
    protected = tuple(getattr(host, name) for name in v17._PROTECTED_SEAMS)
    prior_policy = permission_broker.MODEL_TOOL_POLICIES.get(v17.TOOL_NAME)
    controller.install()
    try:
        assert getattr(host, v17.HOST_MARKER) is controller
        assert tuple(getattr(host, name) for name in v17._PROTECTED_SEAMS) == protected
        assert [item["name"] for item in module.TOOL_DECLARATIONS] == [v17.TOOL_NAME]
        assert permission_broker.MODEL_TOOL_POLICIES[v17.TOOL_NAME] == "always_confirm"
    finally:
        controller.rollback_to_v16()
    assert not hasattr(host, v17.HOST_MARKER)
    assert module.TOOL_DECLARATIONS == []
    assert permission_broker.MODEL_TOOL_POLICIES.get(v17.TOOL_NAME) == prior_policy


@pytest.mark.parametrize("added_seam", [1, 2, 3])
def test_v17_each_added_failpoint_restores_exact_v16(
    monkeypatch: pytest.MonkeyPatch, added_seam: int
) -> None:
    module, host, controller = _activation(monkeypatch)
    with pytest.raises(v17.ActivationV17Error, match="injected V17"):
        controller.install(fail_after=controller.BASE_SEAM_COUNT + added_seam)
    assert not hasattr(host, v17.HOST_MARKER)
    assert module.TOOL_DECLARATIONS == []
    assert v17.TOOL_NAME not in permission_broker.MODEL_TOOL_POLICIES


def test_v17_refuses_non_windows_before_host_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(v17.os, "name", "posix")
    monkeypatch.setattr(
        v17.ActivationFlagsV17,
        "from_canonical_environ",
        classmethod(lambda cls, _source=None: object()),
    )
    with pytest.raises(v17.ActivationV17PlatformDenied, match="boundary_denied"):
        v17.preflight_host(ModuleType("unused"), {})


def test_founder_policy_is_exact_low_risk_read_and_not_always_explicit() -> None:
    policy = governance._policy_for(
        v17.TOOL_NAME,
        {"cadence": "daily", "manifest_ref": "manifests/daily.json"},
        "account-owner",
    )
    assert (policy.tool, policy.operation, policy.risk) == (
        "founder-brief-read",
        "read",
        "low",
    )
    assert policy.always_explicit is False
    assert policy.egress == "none"
    assert policy.data_class == "confidential"


def test_main_founder_dispatch_is_after_authorization_and_final_governance_fence() -> (
    None
):
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    approval = source.index("authorize_model_tool, name, approval_args")
    fence = source.index("governance.assert_dispatch_allowed", approval)
    branch = source.index("if name == _FOUNDER_BRIEF_READ_TOOL", fence)
    execute = source.index("controller.execute", branch)
    assert approval < fence < branch < execute
    assert "task.cancelling()" in source[branch:execute]


def test_v17_source_never_wraps_protected_host_seams() -> None:
    source = (ROOT / "core/onyx_live_activation_v17.py").read_text(encoding="utf-8")
    for name in v17._PROTECTED_SEAMS:
        assert f'setattr(self.contract.onyx_live, "{name}"' not in source
        assert f".{name} =" not in source


def test_bootstrap_non_windows_falls_back_to_v16() -> None:
    bootstrap = runpy.run_path(
        str(ROOT / "scripts/bootstrap_onyx_live_v17.pyw"),
        run_name="v17_bootstrap_test",
    )
    with patch("platform.system", return_value="Linux"):
        mode, prepared = bootstrap["_bootstrap_environment"]({})
    assert mode == "v16"
    assert prepared == {}


def test_broker_denies_founder_when_audit_is_unhealthy_before_hook() -> None:
    called = False

    def governed(_tool, _args):
        nonlocal called
        called = True
        return True, "proof"

    previous = permission_broker.MODEL_TOOL_POLICIES.get(v17.TOOL_NAME)
    permission_broker.MODEL_TOOL_POLICIES[v17.TOOL_NAME] = "always_confirm"
    permission_broker.set_governance_authorization_hook(governed)
    permission_broker._audit_healthy = False
    try:
        allowed, reason = permission_broker.authorize_model_tool(
            v17.TOOL_NAME,
            {"cadence": "daily", "manifest_ref": "manifests/daily.json"},
        )
        assert allowed is False
        assert "audit is unhealthy" in reason
        assert called is False
    finally:
        permission_broker._audit_healthy = True
        permission_broker.set_governance_authorization_hook(None)
        if previous is None:
            permission_broker.MODEL_TOOL_POLICIES.pop(v17.TOOL_NAME, None)
        else:
            permission_broker.MODEL_TOOL_POLICIES[v17.TOOL_NAME] = previous


def _hollow_controller(tmp_path: Path, *, cadence: str = "daily"):
    identity = GovernanceIdentityV1(
        "principal-owner",
        "workspace-owner",
        "account-owner",
        "profile-owner",
        "Owner Workspace",
    )
    nucleus = SimpleNamespace(
        killed=False,
        local_commit_fence=lambda: nullcontext(),
    )
    item = SimpleNamespace(
        claim_id="m2a-claim-" + "1" * 64,
        project_name="Onyx",
        subject_name="Founder Brief",
        owner="Pedro",
        status="in_progress",
        blockers=(),
        next_milestone="Validate the cited brief.",
        definition_of_done="The local read is verified.",
        verification_status="supported",
        citations=("https://evidence.cyryxlabs.com/report",),
    )
    action = SimpleNamespace(
        title="Validate Founder Brief",
        evidence_class="known",
        known_context="The approved source is current.",
        inference=None,
        unknowns=(),
        recommended_action="Review the cited local result.",
        verification_method="Open the cited evidence.",
        completion_evidence="Owner review recorded.",
        downside="None beyond review time.",
        citations=("https://evidence.cyryxlabs.com/report",),
    )
    brief = SimpleNamespace(
        generated_at_ms=1_785_000_000_000,
        items=(item,),
        recommended_top_actions=(action,),
        revenue_opportunities=(),
        portfolio=(
            SimpleNamespace(
                project_name="Onyx",
                claim_ids=(item.claim_id,),
                status_claim_ids=(item.claim_id,),
                blocker_claim_ids=(),
                dependency_claim_ids=(),
                risk_claim_ids=(),
                decision_claim_ids=(),
                stale_claim_ids=(),
            ),
        ),
        critical_blocker_claim_ids=(),
        decision_queue_claim_ids=(),
        risk_register_claim_ids=(),
        delta=SimpleNamespace(
            baseline=True,
            previous_brief_sha256=None,
            added_claim_ids=(item.claim_id,),
            removed_claim_ids=(),
            changed_subjects=(),
        ),
        abstentions=(),
    )
    result = SimpleNamespace(cadence=cadence, brief=brief)

    class Snapshot:
        def __init__(self):
            self.preflight_calls = []
            self.calls = []

        def preflight_manifest(self, reference):
            self.preflight_calls.append(reference)
            return SimpleNamespace(cadence=cadence)

        def generate(self, reference, *, preflight, commit_guard):
            self.calls.append(reference)
            assert preflight.cadence == cadence
            with commit_guard():
                return result

    snapshot = Snapshot()
    controller = object.__new__(v17.FounderBriefControllerV17)
    controller.identity = identity
    controller.workspace_root = tmp_path
    controller.snapshot_root = tmp_path / ".onyx/founder-snapshot-v1"
    controller._nucleus = nucleus
    controller._snapshot = snapshot
    controller._store = object()
    controller._closed = False
    return controller, snapshot, nucleus


def test_controller_returns_cited_redacted_brief_and_rejects_path_escape(
    tmp_path: Path,
) -> None:
    controller, snapshot, _nucleus = _hollow_controller(tmp_path)
    public = controller.execute(
        {"cadence": "daily", "manifest_ref": "manifests/daily.json"}
    )
    assert public["read_only"] is True
    assert public["citations"] == ["https://evidence.cyryxlabs.com/report"]
    rendered = repr(public)
    for forbidden in (
        controller.identity.principal_id,
        controller.identity.workspace_id,
        controller.identity.account_id,
        controller.identity.profile_id,
        str(tmp_path),
    ):
        assert forbidden not in rendered
    assert snapshot.calls == ["manifests/daily.json"]
    assert snapshot.preflight_calls == ["manifests/daily.json"]
    for manifest_ref in ("../outside.json", str(tmp_path / "absolute.json"), "bad.txt"):
        with pytest.raises(v17.ActivationV17Error, match="manifest reference"):
            controller.execute({"cadence": "daily", "manifest_ref": manifest_ref})
    assert snapshot.calls == ["manifests/daily.json"]


def test_controller_kill_and_argument_contract_refuse_before_snapshot(
    tmp_path: Path,
) -> None:
    controller, snapshot, nucleus = _hollow_controller(tmp_path)
    with pytest.raises(v17.ActivationV17Error, match="arguments are not exact"):
        controller.execute(
            {"cadence": "daily", "manifest_ref": "x.json", "workspace_id": "forged"}
        )
    nucleus.killed = True
    with pytest.raises(v17.ActivationV17Error, match="global kill"):
        controller.execute({"cadence": "daily", "manifest_ref": "x.json"})
    assert snapshot.calls == []
    assert snapshot.preflight_calls == []


def test_cadence_mismatch_refuses_before_generate_or_commit(tmp_path: Path) -> None:
    controller, snapshot, _nucleus = _hollow_controller(tmp_path, cadence="weekly")
    lease = v17.FounderCommitLeaseV17()
    with pytest.raises(v17.ActivationV17Error, match="cadence does not match"):
        controller.execute(
            {"cadence": "daily", "manifest_ref": "manifests/weekly.json"},
            commit_lease=lease,
        )
    assert snapshot.preflight_calls == ["manifests/weekly.json"]
    assert snapshot.calls == []
    assert lease.state == "open"


def test_commit_lease_cancel_before_guard_prevents_generation(tmp_path: Path) -> None:
    controller, snapshot, _nucleus = _hollow_controller(tmp_path)
    lease = v17.FounderCommitLeaseV17()
    assert lease.cancel() is True
    with pytest.raises(PermissionError, match="cancelled before commit"):
        controller.execute(
            {"cadence": "daily", "manifest_ref": "manifests/daily.json"},
            commit_lease=lease,
        )
    assert snapshot.preflight_calls == ["manifests/daily.json"]
    assert snapshot.calls == ["manifests/daily.json"]
    assert lease.state == "cancelled"


def test_commit_lease_cancel_after_permit_reconciles_completed(tmp_path: Path) -> None:
    controller, _snapshot, _nucleus = _hollow_controller(tmp_path)
    lease = v17.FounderCommitLeaseV17()
    lease.permit_commit()
    assert lease.cancel() is False
    public = controller.execute(
        {"cadence": "daily", "manifest_ref": "manifests/daily.json"},
        commit_lease=lease,
    )
    assert public["status"] == "completed"
    assert lease.state == "completed"


def test_cancel_before_commit_barrier_has_no_late_commit(tmp_path: Path) -> None:
    controller, snapshot, _nucleus = _hollow_controller(tmp_path)
    lease = v17.FounderCommitLeaseV17()
    entered = threading.Event()
    release = threading.Event()
    original = snapshot.generate

    def blocked(reference, *, preflight, commit_guard):
        entered.set()
        assert release.wait(5)
        return original(reference, preflight=preflight, commit_guard=commit_guard)

    snapshot.generate = blocked
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            controller.execute,
            {"cadence": "daily", "manifest_ref": "manifests/daily.json"},
            commit_lease=lease,
        )
        assert entered.wait(5)
        assert lease.cancel() is True
        release.set()
        with pytest.raises(PermissionError, match="cancelled before commit"):
            future.result(timeout=5)
    assert lease.state == "cancelled"


def test_cancel_after_commit_permit_barrier_returns_completed(tmp_path: Path) -> None:
    controller, snapshot, _nucleus = _hollow_controller(tmp_path)
    lease = v17.FounderCommitLeaseV17()
    permitted = threading.Event()
    release = threading.Event()
    original = snapshot.generate

    def blocked(reference, *, preflight, commit_guard):
        with commit_guard():
            permitted.set()
            assert release.wait(5)
            return original(reference, preflight=preflight, commit_guard=commit_guard)

    snapshot.generate = blocked
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            controller.execute,
            {"cadence": "daily", "manifest_ref": "manifests/daily.json"},
            commit_lease=lease,
        )
        assert permitted.wait(5)
        assert lease.cancel() is False
        release.set()
        public = future.result(timeout=5)
    assert public["status"] == "completed"
    assert lease.state == "completed"


def test_v17_singleton_refuses_second_host_before_controller_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, _host, controller = _activation(monkeypatch)
    hollow = object.__new__(v17.FounderBriefControllerV17)
    hollow._closed = True
    calls = 0

    def factory(_instance, _roots):
        nonlocal calls
        calls += 1
        return hollow

    controller._founder_factory = factory
    controller.install()
    first = SimpleNamespace(_governance_nucleus_v1=object.__new__(GovernanceNucleusV1))
    second = SimpleNamespace(_governance_nucleus_v1=object.__new__(GovernanceNucleusV1))
    try:
        controller.initialize_host(first)
        with pytest.raises(v17.ActivationV17Error, match="already owns"):
            controller.initialize_host(second)
        assert calls == 1
        assert first._founder_brief_controller_v17 is hollow
        assert not hasattr(second, "_founder_brief_controller_v17")
    finally:
        controller.rollback_to_v16()


def test_founder_smoke_refuses_non_windows_before_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "must-not-exist.json"
    monkeypatch.setenv(v17.FOUNDER_SMOKE_OUTPUT_ENV, str(output))
    monkeypatch.setattr(v17.platform, "system", lambda: "Linux")
    with pytest.raises(
        v17.FounderSmokePlatformRefusalV17,
        match="windows_required",
    ):
        v17.run_founder_smoke_v17(SimpleNamespace())  # type: ignore[arg-type]
    assert not output.exists()


def test_founder_smoke_argument_is_routed_by_stable_v17_chain() -> None:
    stable = (ROOT / "scripts/bootstrap_onyx.pyw").read_text(encoding="utf-8")
    bootstrap = (ROOT / "scripts/bootstrap_onyx_live_v17.pyw").read_text(
        encoding="utf-8"
    )
    launcher = (ROOT / "scripts/launch_onyx_live_v17.pyw").read_text(encoding="utf-8")
    assert v17.FOUNDER_SMOKE_ARGUMENT in stable
    assert v17.FOUNDER_SMOKE_ARGUMENT in bootstrap
    assert v17.FOUNDER_SMOKE_ARGUMENT in launcher
    assert "run_founder_smoke_v17" in launcher
    assert "write_founder_smoke_failure_v17" in launcher


@pytest.mark.skipif(os.name != "nt", reason="native Windows Founder smoke")
def test_founder_smoke_is_real_isolated_and_survives_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core import control_plane as control_plane_module
    from core import paths as paths_module

    def persistent_control_plane_refused() -> Path:
        raise AssertionError("Founder smoke reached the persistent Control Plane")

    monkeypatch.setattr(
        paths_module,
        "private_control_plane_runtime_dir",
        persistent_control_plane_refused,
    )
    monkeypatch.setattr(
        control_plane_module,
        "private_control_plane_runtime_dir",
        persistent_control_plane_refused,
    )
    data = tmp_path / "data"
    workspace = data / "workspace"
    corpus = data / "corpus"
    workspace.mkdir(parents=True)
    corpus.mkdir()
    output = data / "founder-smoke-v1.json"
    environment = os.environ.copy()
    for name in v17.CONTROL_FLAGS:
        environment.pop(name, None)
    environment.update(v17.exact_activation_environment((workspace,)))
    environment["ONYX_DATA_DIR"] = str(data)
    environment[v17.FOUNDER_SMOKE_CORPUS_ENV] = str(corpus)
    environment[v17.FOUNDER_SMOKE_OUTPUT_ENV] = str(output)
    with patch.dict(os.environ, environment, clear=True):
        import main
        from core.dayops_graph_factory_v1 import (
            create_canonical_dayops_graph_factory_v1,
        )

        payload = v17.run_founder_smoke_v17(
            main,
            dayops_factory=create_canonical_dayops_graph_factory_v1(
                environ=os.environ,
                project_root=ROOT,
            ),
        )
    assert (
        paths_module.private_control_plane_runtime_dir
        is persistent_control_plane_refused
    )
    assert (
        control_plane_module.private_control_plane_runtime_dir
        is persistent_control_plane_refused
    )
    assert payload["status"] == "passed"
    assert payload["grant_reused"] is True
    assert payload["trusted_ui_prompts"] == 0
    assert payload["network_calls"] == 0
    assert payload["provider_calls"] == 0
    assert payload["process_calls"] == 0
    assert payload["daily"]["status"] == "completed"
    assert payload["weekly"]["status"] == "completed"
    assert payload["restart"]["delta"]["baseline"] is False
    assert payload["restart"]["delta"]["has_previous"] is True
    assert payload["daily"]["portfolio"]
    assert payload["daily"]["citations"]
    corpus_result = payload["corpus"]
    assert corpus_result["alias"] == "founder-smoke-corpus-v17"
    assert corpus_result["citation"].startswith(
        "onyx-artifact://v1/alias/founder-smoke-corpus-v17/sha256/"
    )
    assert corpus_result["citation"].endswith(corpus_result["sha256"])
    assert corpus_result["citation"] in payload["daily"]["citations"]
    assert corpus_result["citation"] in payload["weekly"]["citations"]
    assert corpus_result["citation"] in payload["restart"]["citations"]
    assert all(
        payload["fences"][name] is True
        for name in (
            "cancel_wins",
            "commit_wins",
            "kill_wins",
            "kill_latched",
        )
    )
    serialized = json.dumps(payload, sort_keys=True)
    assert str(tmp_path) not in serialized
    assert ".invalid" not in serialized
    assert "onyx-artifact://v1/workspace-" not in serialized
    assert not any(
        name in serialized
        for name in (
            "workspace_id",
            "principal_id",
            "account_id",
            "profile_id",
            "source_identity_sha256",
        )
    )
    assert json.loads(output.read_text(encoding="utf-8")) == payload


def test_founder_smoke_process_counter_and_failure_output_are_real(
    tmp_path: Path,
) -> None:
    module = ModuleType("founder_smoke_instrumentation")
    module.genai = SimpleNamespace(Client=lambda **_kwargs: object())
    original_popen = subprocess.Popen
    isolation = v17._FounderSmokeIsolationV17(module)
    isolation.install()
    try:
        with pytest.raises(v17.ActivationV17Error, match="child process refused"):
            subprocess.Popen(["not-started-by-founder-smoke"])
        assert isolation.process_calls == 1
    finally:
        isolation.close()
    assert subprocess.Popen is original_popen

    data = tmp_path / "data"
    workspace = data / "workspace"
    corpus = data / "corpus"
    workspace.mkdir(parents=True)
    corpus.mkdir()
    output = data / "failure.json"
    environment = v17.exact_activation_environment((workspace,))
    environment.update(
        {
            "ONYX_DATA_DIR": str(data),
            v17.FOUNDER_SMOKE_CORPUS_ENV: str(corpus),
            v17.FOUNDER_SMOKE_OUTPUT_ENV: str(output),
        }
    )
    failure = v17.FounderSmokeExecutionErrorV17(
        "InjectedFailure",
        network_calls=isolation.network_calls,
        provider_calls=isolation.provider_calls,
        process_calls=isolation.process_calls,
    )
    with patch.dict(os.environ, environment, clear=True):
        v17.write_founder_smoke_failure_v17(failure)
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "contract": "OnyxFounderSmoke.v1",
        "error_type": "InjectedFailure",
        "network_calls": 0,
        "process_calls": 1,
        "provider_calls": 0,
        "status": "failed",
    }

    source = (ROOT / "core" / "onyx_live_activation_v17.py").read_text(encoding="utf-8")
    smoke = source[source.index("class _FounderSmokeIsolationV17") :]
    assert "require_windows_boundary=False" not in smoke
    assert "phase11_native.NativeSecretVault" not in smoke
    assert '"process_calls": isolation.process_calls' in smoke
    assert '"process_calls": 0' not in smoke
