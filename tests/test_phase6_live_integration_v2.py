from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
from pathlib import Path

import pytest

from core import phase6_live_integration_v1 as live_v1
from core.missions import MissionStore
from core.phase5_integration_v3 import (
    CatalogSeedV3,
    IntegrationFlagsV3,
    Phase5IntegrationV3,
)
from core.phase5_runtime_v10 import RuntimeBindingV10
from core.phase6_agentic_core_v1 import (
    AdapterStatusV1,
    DataClassV1,
    GoalV1,
    MissionBudgetV1,
    PlanStateV1,
    WorkspaceScopeV1,
)
from core.phase6_agentic_core_v2 import artifact_root_v2
from core.phase6_agentic_core_v4 import TerminableProcessExecutorV4
from core.phase6_agentic_core_v6 import (
    AgenticCoreV6,
    AgenticFeatureGateV6,
    AgenticStateStoreV6,
)
from core.phase6_live_integration_v2 import (
    CatalogReadRequestV2,
    CurrentTextProviderAdapterV2,
    HostIdentityBindingV2,
    IdentityReceiptStoreV2,
    LiveIntegrationFeatureGateV2,
    Phase6LiveIntegrationV2Denied,
    TextProviderRequestV2,
    create_phase6_live_integration_v2,
)


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = "workspace-integration"
ACCOUNT = "account-integration"
PROFILE = "profile-integration"
PRINCIPAL = "owner-integration"
FROZEN_V1 = {
    "core/phase6_live_integration_v1.py": (
        "d838b3789bd286188f4b8f21426135fe2034459f1382cc68e3568707952a3715"
    ),
    "tests/test_phase6_live_integration_v1.py": (
        "830c3717737aed95bdf9fea10138c87cca3624201120778d496704e6f7990046"
    ),
    "docs/onyx/adrs/ADR-0016-phase6-live-integration-v1.md": (
        "b4257950e3f07bb0930cd832e571c633873ee1c8ae0513071445b8ca4324c6b6"
    ),
    (
        "docs/onyx/checkpoints/phase6-live-integration-v1/"
        "PHASE6_LIVE_INTEGRATION_V1_CHECKPOINT.md"
    ): "f7d7159dd78e213c4eb030a5f73217e22fd3749e46a067df81a707ec42cf808b",
    "docs/onyx/checkpoints/phase6-live-integration-v1/manifest.json": (
        "56b8d2ae00078bd755dab583da922d0530b8d2e5482080704f62bc58f05ed6a7"
    ),
    "scripts/verify_phase6_live_integration_v1.py": (
        "53520a1ae92c9bbed339dc3d56e9319c78082ebe137b77ea9a39e1f4f5733917"
    ),
}


def _identity(**changes: str) -> HostIdentityBindingV2:
    values = {
        "workspace_id": WORKSPACE,
        "account_id": ACCOUNT,
        "profile_id": PROFILE,
        "principal_id": PRINCIPAL,
    }
    values.update(changes)
    return HostIdentityBindingV2(**values)


def _phase5(**changes: str) -> Phase5IntegrationV3:
    values = {
        "workspace_id": WORKSPACE,
        "account_id": ACCOUNT,
        "profile_id": PROFILE,
        "principal_id": PRINCIPAL,
    }
    values.update(changes)
    return Phase5IntegrationV3(
        binding=RuntimeBindingV10(
            "trace-phase6-live-v2",
            "session-phase6-live-v2",
            values["workspace_id"],
            values["account_id"],
            values["profile_id"],
        ),
        principal_id=values["principal_id"],
        flags=IntegrationFlagsV3(
            integration=True,
            runtime=True,
            low_risk=True,
            local_catalog_read=True,
        ),
        catalog=(
            CatalogSeedV3("system_status", "System Status"),
            CatalogSeedV3("memory_search", "Memory Search"),
        ),
    )


def _core(tmp_path: Path, *, workspace: str = WORKSPACE):
    state = AgenticStateStoreV6(tmp_path / "phase6.sqlite3", AgenticFeatureGateV6(True))
    core = AgenticCoreV6(
        state,
        MissionStore(tmp_path / "missions.sqlite3"),
        WorkspaceScopeV1(
            workspace,
            (str(tmp_path.resolve()),),
            DataClassV1.CONFIDENTIAL,
        ),
    )
    return core, state


def _facade(tmp_path: Path, *, phase5: Phase5IntegrationV3 | None = None):
    core, state = _core(tmp_path)
    identity = _identity()
    bridge = phase5 or _phase5()
    receipt_path = tmp_path / "v2-receipts.sqlite3"
    facade = create_phase6_live_integration_v2(
        gate=LiveIntegrationFeatureGateV2(True),
        identity=identity,
        agentic_core=core,
        agentic_state=state,
        phase5=bridge,
        receipt_path=receipt_path,
    )
    assert facade is not None
    return facade, core, state, bridge, receipt_path


def _goal() -> GoalV1:
    return GoalV1(
        "goal_phase6_live_v2",
        "corr_phase6_live_v2",
        WORKSPACE,
        "Read identity-bound local capability metadata",
        ("identity_bound_receipt_observed",),
        ("local_catalog",),
        ("no_network",),
        DataClassV1.INTERNAL,
        MissionBudgetV1(
            max_steps=1,
            wall_seconds=30.0,
            max_retries_per_step=0,
            max_repair_cycles=0,
            max_compute_seconds=5.0,
        ),
    )


def _catalog_step() -> dict[str, object]:
    return {
        "step_id": "step_catalog_v2",
        "capability": "local_catalog_read",
        "arguments": {"page_size": 1},
        "dependencies": [],
        "timeout_seconds": 2.0,
        "max_retries": 0,
        "postconditions": ["identity_bound_receipt_observed"],
    }


def _v1_text_request(
    *,
    request_id: str = "request-text-v2",
    workspace: str = WORKSPACE,
    data_class: DataClassV1 = DataClassV1.INTERNAL,
) -> live_v1.TextProviderRequestV1:
    return live_v1.TextProviderRequestV1(
        request_id,
        workspace,
        data_class,
        "private prompt",
        "private system",
        live_v1.TextProviderBudgetV1(2.0),
    )


def test_v1_candidate_is_exactly_frozen_and_rejection_is_additive() -> None:
    for relative, expected in FROZEN_V1.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected
    rejection = (
        ROOT / "docs/onyx/rejections/PHASE6_LIVE_INTEGRATION_V1_REJECTION.md"
    ).read_text(encoding="utf-8")
    assert "P1" in rejection
    assert "identity" in rejection.lower()
    assert "invoker" in rejection.lower()
    assert (
        FROZEN_V1["docs/onyx/checkpoints/phase6-live-integration-v1/manifest.json"]
        in rejection
    )


def test_v2_is_strict_default_off_and_absent_from_live_surfaces() -> None:
    assert not LiveIntegrationFeatureGateV2.from_environ({}).enabled
    assert not LiveIntegrationFeatureGateV2.from_environ(
        {"ONYX_PHASE6_LIVE_INTEGRATION_V2": "TRUE"}
    ).enabled
    assert LiveIntegrationFeatureGateV2.from_environ(
        {"ONYX_PHASE6_LIVE_INTEGRATION_V2": "true"}
    ).enabled
    assert (
        create_phase6_live_integration_v2(gate=LiveIntegrationFeatureGateV2(False))
        is None
    )
    for relative in ("main.py", "ui.py", "dashboard/server.py"):
        assert "phase6_live_integration_v2" not in (ROOT / relative).read_text(
            encoding="utf-8"
        )


@pytest.mark.parametrize(
    "field",
    ["workspace_id", "account_id", "profile_id", "principal_id"],
)
def test_factory_rejects_every_phase5_identity_divergence_before_side_effects(
    tmp_path: Path, field: str
) -> None:
    core, state = _core(tmp_path)
    changed = {field: f"{field.replace('_', '-')}-other"}
    bridge = _phase5(**changed)
    receipt_path = tmp_path / "must-not-exist.sqlite3"
    with pytest.raises(Phase6LiveIntegrationV2Denied):
        create_phase6_live_integration_v2(
            gate=LiveIntegrationFeatureGateV2(True),
            identity=_identity(),
            agentic_core=core,
            agentic_state=state,
            phase5=bridge,
            receipt_path=receipt_path,
        )
    assert not receipt_path.exists()
    assert not receipt_path.with_name(
        f"{receipt_path.stem}.v1-base{receipt_path.suffix}"
    ).exists()
    core.close()


def test_factory_rejects_core_workspace_divergence_before_side_effects(
    tmp_path: Path,
) -> None:
    core, state = _core(tmp_path, workspace="workspace-other")
    path = tmp_path / "must-not-exist.sqlite3"
    with pytest.raises(Phase6LiveIntegrationV2Denied):
        create_phase6_live_integration_v2(
            gate=LiveIntegrationFeatureGateV2(True),
            identity=_identity(),
            agentic_core=core,
            agentic_state=state,
            phase5=_phase5(),
            receipt_path=path,
        )
    assert not path.exists()
    core.close()


def test_operational_factory_has_no_invoker_executor_or_adapter_injection(
    tmp_path: Path,
) -> None:
    parameters = inspect.signature(create_phase6_live_integration_v2).parameters
    assert "invoke" not in parameters
    assert "invoker" not in parameters
    assert "executor" not in parameters
    assert "text" not in parameters
    assert "catalog" not in parameters
    assert tuple(inspect.signature(CurrentTextProviderAdapterV2).parameters) == (
        "identity",
    )
    facade, _core_value, _state, _bridge, _path = _facade(tmp_path)
    try:
        adapter = facade._text
        assert type(adapter) is CurrentTextProviderAdapterV2
        assert adapter._delegate._invoke is live_v1._current_llm_text_call
        assert type(adapter._delegate._executor) is TerminableProcessExecutorV4
    finally:
        facade.close()


def test_arbitrary_text_invoker_and_executor_tamper_fail_closed(
    tmp_path: Path,
) -> None:
    facade, _core_value, _state, _bridge, _path = _facade(tmp_path)
    adapter = facade._text
    original_invoker = adapter._delegate._invoke
    adapter._delegate._invoke = lambda *_args: "forged"
    with pytest.raises(Phase6LiveIntegrationV2Denied):
        adapter.invoke(TextProviderRequestV2(_identity(), _v1_text_request()))
    adapter._delegate._invoke = original_invoker
    original_executor = adapter._delegate._executor
    adapter._delegate._executor = object()
    with pytest.raises(Phase6LiveIntegrationV2Denied):
        adapter.invoke(TextProviderRequestV2(_identity(), _v1_text_request()))
    adapter._delegate._executor = original_executor
    facade.close()


@pytest.mark.parametrize(
    "field",
    ["account_id", "profile_id", "principal_id"],
)
def test_text_request_rejects_cross_identity_before_provider(
    tmp_path: Path, field: str
) -> None:
    facade, _core_value, _state, _bridge, _path = _facade(tmp_path)
    changed = {field: f"{field.replace('_', '-')}-other"}
    request = TextProviderRequestV2(_identity(**changed), _v1_text_request())
    try:
        with pytest.raises(Phase6LiveIntegrationV2Denied):
            facade.generate_text(request)
    finally:
        facade.close()


def test_text_cancellation_and_privacy_block_without_network_and_bind_identity(
    tmp_path: Path,
) -> None:
    facade, _core_value, _state, _bridge, _path = _facade(tmp_path)
    token = live_v1.CancellationTokenV1()
    token.cancel()
    try:
        request = TextProviderRequestV2(_identity(), _v1_text_request())
        cancelled = facade.generate_text(request, token)
        assert cancelled.result.status == "cancelled"
        assert cancelled.result.provider_calls == 0
        assert cancelled.identity.payload() == _identity().payload()
        assert cancelled.receipt_payload()["identity"] == _identity().payload()
        assert cancelled.receipt_payload()["identity_digest"] == _identity().digest
        restricted = facade.generate_text(
            TextProviderRequestV2(
                _identity(),
                _v1_text_request(
                    request_id="request-text-restricted",
                    data_class=DataClassV1.RESTRICTED,
                ),
            )
        )
        assert restricted.result.status == "blocked"
        assert restricted.result.provider_calls == 0
    finally:
        facade.close()


def test_operational_factory_characterizes_endpoint_model_and_exact_executor(
    tmp_path: Path, monkeypatch
) -> None:
    config = live_v1.TextProviderConfigV1(
        "openai", "https://remote.example.test", "pinned-model"
    )
    monkeypatch.setattr(live_v1, "_current_llm_config", lambda: config)
    facade, _core_value, _state, _bridge, _path = _facade(tmp_path)
    try:
        adapter = facade._text
        assert adapter.descriptor.status is AdapterStatusV1.BLOCKED_BY_POLICY
        assert adapter._delegate._config == config
        assert adapter._delegate._invoke is live_v1._current_llm_text_call
        assert type(adapter._delegate._executor) is TerminableProcessExecutorV4
        result = facade.generate_text(
            TextProviderRequestV2(_identity(), _v1_text_request())
        )
        assert result.result.status == "blocked"
        assert result.result.provider_calls == 0
    finally:
        facade.close()


def test_v1_terminable_timeout_closure_remains_in_cumulative_suite() -> None:
    source = (ROOT / "tests/test_phase6_live_integration_v1.py").read_text(
        encoding="utf-8"
    )
    assert "test_text_timeout_terminates_provider_process" in source
    module = (ROOT / "core/phase6_live_integration_v2.py").read_text(encoding="utf-8")
    assert "TerminableProcessExecutorV4()" in module
    assert "_attest_operational()" in module


def test_catalog_receipt_binds_all_identity_fields_and_is_durable(
    tmp_path: Path,
) -> None:
    facade, _core_value, state, _bridge, path = _facade(tmp_path)
    try:
        projection = facade.submit(
            _goal(), "request-key-phase6-live-v2", [_catalog_step()]
        )
        outcome = facade.execute_local_catalog_plan(
            projection.plan_id, "request-catalog-v2"
        )
        assert outcome.state is PlanStateV1.WAITING_FOR_PHASE5
        assert outcome.receipt is not None
        receipt = outcome.receipt
        assert receipt.identity.payload() == _identity().payload()
        assert receipt.payload()["identity"] == _identity().payload()
        assert receipt.payload()["identity_digest"] == _identity().digest
        assert receipt.request_digest != receipt.v1_receipt_digest
        assert state.get_projection(projection.plan_id).mission_id is None
    finally:
        facade.close()
    reopened = IdentityReceiptStoreV2(path)
    persisted = reopened.get("request-catalog-v2")
    assert persisted is not None
    assert persisted.identity == _identity()


@pytest.mark.parametrize(
    "field",
    ["account_id", "profile_id", "principal_id"],
)
def test_catalog_request_rejects_cross_identity_before_phase5(
    tmp_path: Path, field: str
) -> None:
    facade, _core_value, _state, _bridge, _path = _facade(tmp_path)
    changed = {field: f"{field.replace('_', '-')}-other"}
    request = CatalogReadRequestV2(
        _identity(**changed),
        live_v1.CatalogReadRequestV1(
            "request-catalog-cross",
            WORKSPACE,
            DataClassV1.INTERNAL,
            {},
        ),
    )
    try:
        with pytest.raises(Phase6LiveIntegrationV2Denied):
            facade._catalog.execute(request)
    finally:
        facade.close()


def test_identity_mutation_after_factory_fails_closed(
    tmp_path: Path,
) -> None:
    bridge = _phase5()
    facade, _core_value, _state, _bridge, _path = _facade(tmp_path, phase5=bridge)
    bridge._principal_id = "owner-diverged"
    with pytest.raises(Phase6LiveIntegrationV2Denied):
        facade.generate_text(TextProviderRequestV2(_identity(), _v1_text_request()))
    bridge._principal_id = PRINCIPAL
    facade.close()


def test_v2_receipt_schema_tamper_fails_before_repair(
    tmp_path: Path,
) -> None:
    path = tmp_path / "v2-store.sqlite3"
    IdentityReceiptStoreV2(path)
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TRIGGER catalog_receipts_no_delete")
        connection.commit()
    finally:
        connection.close()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(Exception):
        IdentityReceiptStoreV2(path)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_external_agent_remains_disabled_and_blocked_by_access(
    tmp_path: Path,
) -> None:
    facade, _core_value, _state, _bridge, _path = _facade(tmp_path)
    try:
        assert facade.external_agent.adapter_id == "external_agent_disabled"
        assert facade.external_agent.status is AdapterStatusV1.BLOCKED_BY_ACCESS
    finally:
        facade.close()


def test_v2_manifest_recomputes_artifact_root() -> None:
    manifest_path = (
        ROOT / "docs/onyx/checkpoints/phase6-live-integration-v2/manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifacts = {item["path"]: item["sha256"] for item in manifest["artifacts"]}
    assert len(artifacts) == len(manifest["artifacts"])
    assert all(
        hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
        for path, digest in artifacts.items()
    )
    assert artifact_root_v2(artifacts) == manifest["artifact_root_sha256"]
