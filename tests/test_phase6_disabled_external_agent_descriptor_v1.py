from __future__ import annotations

import ast
import hashlib
import hmac
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

import core.capability_nexus_v32 as nexus_v32
import core.phase6_disabled_external_agent_descriptor_v1 as external_module
import core.phase6_provider_registry_v1 as provider_v1
from core.capability_nexus_v32 import CapabilityStatusV32, TransportKindV32
from core.phase6_agentic_core_v1 import AdapterStatusV1, DataClassV1
from core.phase6_disabled_external_agent_descriptor_v1 import (
    ACCESS_REASON,
    CANDIDATE,
    COMPONENT_ACCEPTANCE_ROOTS,
    DESCRIPTOR_VERSION,
    FEATURE_FLAG,
    DisabledExternalAgentDescriptorCatalogV1,
    DisabledExternalAgentDescriptorV1,
    DisabledExternalAgentDescriptorV1Conflict,
    DisabledExternalAgentDescriptorV1ContractError,
    DisabledExternalAgentDescriptorV1Denied,
    DisabledExternalAgentFeatureGateV1,
    ExternalAgentAuthenticationStateV1,
    ExternalAgentCancellationSemanticsV1,
    ExternalAgentDescriptorIdentityV1,
    ExternalAgentDescriptorQueryV1,
    ExternalAgentReceiptSemanticsV1,
    create_disabled_external_agent_descriptor_v1,
)


ROOT = Path(__file__).resolve().parents[1]
KEY = b"disabled-external-agent-key-v1!!"


def identity(**changes: str) -> ExternalAgentDescriptorIdentityV1:
    values = {
        "adapter_id": "external-agent-disabled",
        "provider_id": "external-agent-provider",
        "workspace_id": "workspace-agent",
        "account_id": "account-agent",
        "profile_id": "profile-agent",
        "principal_id": "principal-agent",
    }
    values.update(changes)
    return ExternalAgentDescriptorIdentityV1(**values)


def catalog(
    item: ExternalAgentDescriptorIdentityV1 | None = None,
    *,
    key: bytes = KEY,
) -> DisabledExternalAgentDescriptorCatalogV1:
    result = create_disabled_external_agent_descriptor_v1(
        gate=DisabledExternalAgentFeatureGateV1(True),
        identity=identity() if item is None else item,
        project_root=ROOT,
        receipt_authentication_key=key,
    )
    assert type(result) is DisabledExternalAgentDescriptorCatalogV1
    return result


def query(
    item: DisabledExternalAgentDescriptorCatalogV1,
    *,
    request_id: str = "request-agent",
    query_identity: ExternalAgentDescriptorIdentityV1 | None = None,
    expected_version: str | None = None,
    expected_digest: str | None = None,
    cancelled: bool = False,
) -> ExternalAgentDescriptorQueryV1:
    descriptor = item.descriptor
    return ExternalAgentDescriptorQueryV1(
        request_id=request_id,
        identity=descriptor.identity if query_identity is None else query_identity,
        expected_version=(
            descriptor.descriptor_version
            if expected_version is None
            else expected_version
        ),
        expected_descriptor_digest=(
            descriptor.digest if expected_digest is None else expected_digest
        ),
        cancelled=cancelled,
    )


@pytest.mark.parametrize(
    "value",
    [None, "", "1", "TRUE", "True", " true", "true "],
)
def test_exact_flag_is_default_off_and_disabled_factory_is_dependency_free(
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
):
    env = {} if value is None else {FEATURE_FLAG: value}
    gate = DisabledExternalAgentFeatureGateV1.from_environ(env)
    assert gate.enabled is False
    monkeypatch.setattr(
        external_module,
        "_verify_component_roots",
        lambda _root: pytest.fail("disabled factory read component roots"),
    )
    assert (
        create_disabled_external_agent_descriptor_v1(
            gate=gate,
            identity=None,
            project_root=None,
            receipt_authentication_key=b"",
        )
        is None
    )
    assert (
        DisabledExternalAgentFeatureGateV1.from_environ(
            {FEATURE_FLAG: "true"}
        ).enabled
        is True
    )


def test_candidate_identity_and_component_roots_are_exact():
    assert CANDIDATE == "phase6-disabled-external-agent-descriptor-candidate-001"
    assert DESCRIPTOR_VERSION == "v1"
    assert ACCESS_REASON == "no_accepted_installed_authenticated_adapter"
    assert len(COMPONENT_ACCEPTANCE_ROOTS) == 5
    assert {item[0] for item in COMPONENT_ACCEPTANCE_ROOTS} == {
        "capability_nexus_v32",
        "provider_registry_v1",
    }
    for _component, relative, expected in COMPONENT_ACCEPTANCE_ROOTS:
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_factory_only_exact_inputs_absolute_root_and_key():
    item = catalog()
    descriptor = item.descriptor
    with pytest.raises(DisabledExternalAgentDescriptorV1Denied):
        DisabledExternalAgentDescriptorV1(
            _construction_key=object(),
            identity=descriptor.identity,
            capability_contract=descriptor.capability_contract,
            provider_contract=descriptor.provider_contract,
        )
    with pytest.raises(DisabledExternalAgentDescriptorV1Denied):
        DisabledExternalAgentDescriptorCatalogV1(
            _construction_key=object(),
            descriptor=descriptor,
            project_root=ROOT,
            receipt_authentication_key=KEY,
        )
    with pytest.raises(DisabledExternalAgentDescriptorV1ContractError):
        create_disabled_external_agent_descriptor_v1(
            gate=DisabledExternalAgentFeatureGateV1(True),
            identity=identity(),
            project_root=".",
            receipt_authentication_key=KEY,
        )
    with pytest.raises(DisabledExternalAgentDescriptorV1ContractError):
        catalog(key=b"short")


def test_descriptor_projects_exact_nexus_and_provider_blocked_contracts():
    descriptor = catalog().descriptor
    capability = descriptor.capability_contract
    provider = descriptor.provider_contract
    model = provider.descriptor
    assert descriptor.health is CapabilityStatusV32.BLOCKED_BY_ACCESS
    assert descriptor.access_reason == ACCESS_REASON
    assert descriptor.required_scopes == ()
    assert descriptor.granted_scopes == ()
    assert descriptor.authentication is ExternalAgentAuthenticationStateV1.ABSENT
    assert (
        descriptor.cancellation_semantics
        is ExternalAgentCancellationSemanticsV1.NO_SESSION_CANCEL_IS_FINAL
    )
    assert (
        descriptor.receipt_semantics
        is ExternalAgentReceiptSemanticsV1.AUTHENTICATED_BLOCKED_PROJECTION
    )
    assert type(capability) is nexus_v32.CapabilityDescriptorV32
    assert capability.status is CapabilityStatusV32.BLOCKED_BY_ACCESS
    assert capability.status_reason == ACCESS_REASON
    assert capability.transport is TransportKindV32.LEGACY
    assert capability.credential_alias is None
    assert capability.metadata == ()
    assert len(capability.operations) == 1
    assert capability.operations[0].required_scopes == ()
    assert type(provider) is provider_v1.ProviderRecordV1
    assert model.status is AdapterStatusV1.BLOCKED_BY_ACCESS
    assert model.modalities == ("external_agent",)
    assert model.maximum_data_class is DataClassV1.PUBLIC
    assert model.workspace_allowlist == (descriptor.identity.workspace_id,)


def test_descriptor_has_no_executable_path_environment_or_credential_fields():
    descriptor = catalog().descriptor
    forbidden = ("command", "executable", "path", "environment", "env", "credential")
    public_names = {
        name
        for name, value in vars(type(descriptor)).items()
        if isinstance(value, property)
    }
    payload_names = set(descriptor.payload())
    for name in public_names | payload_names:
        assert not any(token == name or name.startswith(f"{token}_") for token in forbidden)
    assert descriptor.capability_contract.credential_alias is None


def test_descriptor_and_identity_are_immutable():
    item = catalog()
    with pytest.raises(AttributeError):
        item.descriptor._health = CapabilityStatusV32.AVAILABLE
    with pytest.raises(FrozenInstanceError):
        item.descriptor.identity.workspace_id = "workspace-other"


def test_projection_is_blocked_content_free_and_has_zero_operational_calls():
    item = catalog()
    projection, receipt = item.describe(query(item))
    assert projection.descriptor is item.descriptor
    assert projection.health is CapabilityStatusV32.BLOCKED_BY_ACCESS
    assert projection.access_reason == ACCESS_REASON
    assert projection.required_scopes == ()
    assert projection.granted_scopes == ()
    assert projection.authentication is ExternalAgentAuthenticationStateV1.ABSENT
    assert projection.runtime_available is False
    assert projection.authority_granted is False
    assert (
        projection.provider_calls,
        projection.process_calls,
        projection.network_calls,
        projection.live_calls,
    ) == (0, 0, 0, 0)
    serialized = repr(receipt.unsigned_payload()).lower()
    assert "prompt" not in serialized
    assert "message" not in serialized
    assert "content" not in serialized


def test_receipt_is_hmac_authenticated_and_exactly_attested():
    item = catalog()
    projection, receipt = item.describe(query(item))
    expected = hmac.new(
        KEY,
        external_module._canonical(receipt.unsigned_payload()),
        hashlib.sha256,
    ).hexdigest()
    assert hmac.compare_digest(receipt.authentication_tag, expected)
    item.attest_receipt(projection, receipt)


def test_exact_replay_returns_same_projection_and_receipt_objects():
    item = catalog()
    request = query(item)
    first_projection, first_receipt = item.describe(request)
    next_projection, next_receipt = item.describe(request)
    assert next_projection is first_projection
    assert next_receipt is first_receipt


def test_cancellation_is_final_before_projection_or_replay():
    item = catalog()
    cancelled = query(item, cancelled=True)
    with pytest.raises(
        DisabledExternalAgentDescriptorV1Denied,
        match="cancellation is final",
    ):
        item.describe(cancelled)
    active = query(item)
    item.describe(active)
    with pytest.raises(DisabledExternalAgentDescriptorV1Denied):
        item.describe(replace(active, cancelled=True))


@pytest.mark.parametrize(
    "changes",
    [
        {"workspace_id": "workspace-other"},
        {"account_id": "account-other"},
        {"profile_id": "profile-other"},
        {"principal_id": "principal-other"},
        {"adapter_id": "external-agent-other"},
        {"provider_id": "external-provider-other"},
    ],
)
def test_cross_identity_queries_are_denied(changes: dict[str, str]):
    item = catalog()
    with pytest.raises(DisabledExternalAgentDescriptorV1Denied):
        item.describe(query(item, query_identity=identity(**changes)))


def test_version_and_descriptor_digest_drift_are_denied():
    item = catalog()
    with pytest.raises(DisabledExternalAgentDescriptorV1Denied):
        item.describe(query(item, expected_version="v2"))
    with pytest.raises(DisabledExternalAgentDescriptorV1Denied):
        item.describe(query(item, expected_digest="f" * 64))


def test_forged_receipt_and_projection_substitution_are_denied():
    item = catalog()
    projection, receipt = item.describe(query(item))
    forged = replace(receipt, authentication_tag="0" * 64)
    with pytest.raises(DisabledExternalAgentDescriptorV1Denied):
        item.attest_receipt(projection, forged)
    other = catalog(identity(workspace_id="workspace-other"))
    other_projection, _other_receipt = other.describe(
        query(other, request_id="request-other")
    )
    with pytest.raises(DisabledExternalAgentDescriptorV1Denied):
        item.attest_receipt(other_projection, receipt)


@pytest.mark.parametrize(
    "value",
    [
        "secret-agent",
        "token-agent",
        "credential-agent",
        "private-agent",
        "sk-agent",
        "ghp-agent",
        "owner@example",
        "UPPERCASE",
        " has-space",
    ],
)
def test_privacy_and_secret_looking_identity_metadata_is_denied(value: str):
    with pytest.raises(DisabledExternalAgentDescriptorV1ContractError):
        identity(principal_id=value)


def test_exact_type_subclasses_are_denied():
    class QuerySubclass(ExternalAgentDescriptorQueryV1):
        pass

    item = catalog()
    base = query(item)
    subclass = QuerySubclass(
        base.request_id,
        base.identity,
        base.expected_version,
        base.expected_descriptor_digest,
    )
    with pytest.raises(DisabledExternalAgentDescriptorV1ContractError):
        item.describe(subclass)


def test_component_hash_drift_is_denied(monkeypatch: pytest.MonkeyPatch):
    real = external_module._sha_file
    first_path = (ROOT / COMPONENT_ACCEPTANCE_ROOTS[0][1]).resolve()

    def drift(path: Path) -> str:
        if path == first_path:
            return "0" * 64
        return real(path)

    monkeypatch.setattr(external_module, "_sha_file", drift)
    with pytest.raises(
        DisabledExternalAgentDescriptorV1Denied,
        match="component acceptance drift",
    ):
        catalog()


def test_inherited_type_authority_drift_is_denied(
    monkeypatch: pytest.MonkeyPatch,
):
    item = catalog()
    monkeypatch.setattr(nexus_v32, "CapabilityDescriptorV32", object)
    with pytest.raises(DisabledExternalAgentDescriptorV1Denied):
        item.descriptor.attest()


def test_request_rebinding_is_explicit_permission_denial():
    assert issubclass(
        DisabledExternalAgentDescriptorV1Conflict,
        DisabledExternalAgentDescriptorV1Denied,
    )
    item = catalog()
    first = query(item)
    item.describe(first)
    with pytest.raises(
        DisabledExternalAgentDescriptorV1Conflict,
        match="conflicts with prior input",
    ):
        item.describe(
            query(
                item,
                query_identity=identity(workspace_id="workspace-other"),
            )
        )


def test_candidate_ast_has_no_network_process_provider_or_execution_surface():
    source = (
        ROOT / "core/phase6_disabled_external_agent_descriptor_v1.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    forbidden_imports = {
        "asyncio",
        "aiohttp",
        "http",
        "httpx",
        "openai",
        "requests",
        "socket",
        "subprocess",
        "urllib",
        "webbrowser",
    }
    assert not (imports & forbidden_imports)
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not (
        calls
        & {
            "connect",
            "create_connection",
            "Popen",
            "post",
            "request",
            "run",
            "send",
            "start",
            "urlopen",
        }
    )
    assert "provider_v1.create_provider_registry_v1" not in source
    assert "ModelRouterV1" not in source


def test_focused_structural_scan_proves_absence_from_live_surfaces():
    live_files = [ROOT / "main.py", ROOT / "ui.py"]
    for root_name in ("dashboard", "runtime", "packaging", "qml"):
        candidate = ROOT / root_name
        if candidate.is_dir():
            live_files.extend(path for path in candidate.rglob("*") if path.is_file())
    scripts = ROOT / "scripts"
    live_files.extend(path for path in scripts.glob("launch_*") if path.is_file())
    checked = 0
    for path in sorted(set(live_files)):
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        checked += 1
        assert "phase6_disabled_external_agent_descriptor_v1" not in source
        assert FEATURE_FLAG not in source
    assert checked >= 2


def test_projection_and_receipt_constructor_contracts_deny_drift():
    item = catalog()
    projection, receipt = item.describe(query(item))
    with pytest.raises(DisabledExternalAgentDescriptorV1Denied):
        replace(projection, network_calls=1)
    with pytest.raises(DisabledExternalAgentDescriptorV1Denied):
        replace(receipt, health=CapabilityStatusV32.AVAILABLE_READ_ONLY)
