from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from core.capability_composition_v1 import (
    CAPABILITY_OPERATIONS,
    SCHEMA_VERSION,
    create_capability_composition_v1,
)
from core.governance_nucleus_v1 import (
    GovernanceIdentityV1,
    GovernanceNucleusV1,
    GovernanceV1Denied,
)
from core.governed_capability_host_v1 import HostBoundCapabilityPortV1


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


class _Port(HostBoundCapabilityPortV1):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0
        self.kills = 0
        self.timeout = False

    def _dispatch_authorized(self, operation: str, arguments: dict[str, object]) -> object:
        self.calls += 1
        if self.timeout:
            raise TimeoutError("provider-free deterministic timeout")
        return {"operation": operation, "count": len(arguments)}

    def revoke(self, binding_id: str) -> None:
        del binding_id

    def kill(self) -> bool:
        self.kills += 1
        return True


def _nucleus(path: Path) -> GovernanceNucleusV1:
    return GovernanceNucleusV1(
        path=path,
        identity=GovernanceIdentityV1("owner", "workspace", "account", "profile"),
        key_vault=_Vault(),
        head_vault=_Vault(),
        pending_vault=_Vault(),
        require_windows_boundary=False,
    )


def test_default_composition_is_closed_provider_free_and_redacted(tmp_path: Path) -> None:
    composition = create_capability_composition_v1(
        nucleus=_nucleus(tmp_path / "governance.sqlite3")
    )
    status = composition.status()
    assert status.schema == SCHEMA_VERSION
    assert status.provider_dispatch is False
    assert status.redacted is True
    assert tuple(row["capability"] for row in status.capabilities) == tuple(
        sorted(CAPABILITY_OPERATIONS)
    )
    assert {row["readiness"] for row in status.capabilities} == {"default-off"}
    assert not hasattr(composition.router, "dispatch")
    assert "project_execution" in CAPABILITY_OPERATIONS


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("principal_id", "wrong-principal"),
        ("workspace_id", "wrong-workspace"),
        ("session_generation", 99),
    ),
)
def test_dispatch_denies_wrong_scope_before_injected_port(
    tmp_path: Path, field: str, value: object
) -> None:
    nucleus = _nucleus(tmp_path / "governance.sqlite3")
    port = _Port()
    composition = create_capability_composition_v1(
        nucleus=nucleus, port_factories={"argos": lambda: port}
    )
    session = nucleus.begin_session()
    plan = composition.plan(session, "argos", "read.status", {})
    binding = replace(plan.binding, **{field: value})
    with pytest.raises(GovernanceV1Denied):
        composition.host.dispatch(binding, {})
    assert port.calls == 0


def test_source_e2e_routes_only_host_dispatch_and_single_kill(tmp_path: Path) -> None:
    nucleus = _nucleus(tmp_path / "governance.sqlite3")
    port = _Port()
    composition = create_capability_composition_v1(
        nucleus=nucleus, port_factories={"argos": lambda: port}
    )
    receipt = composition.dispatch(
        nucleus.begin_session(), "argos", "read.status", {}
    )
    assert receipt.outcome == "completed"
    assert port.calls == 1
    assert composition.kill() is composition.kill()
    assert port.kills == 1


def test_composition_shutdown_is_process_local(tmp_path: Path) -> None:
    nucleus = _nucleus(tmp_path / "governance.sqlite3")
    port = _Port()
    composition = create_capability_composition_v1(
        nucleus=nucleus, port_factories={"argos": lambda: port}
    )
    session = nucleus.begin_session()

    assert composition.shutdown() is composition.shutdown()
    assert composition.status().killed is True
    assert nucleus.killed is False
    assert port.kills == 1
    with pytest.raises(GovernanceV1Denied):
        composition.plan(session, "argos", "read.status", {})


@pytest.mark.parametrize("capability", tuple(sorted(CAPABILITY_OPERATIONS)))
def test_provider_free_allow_revoke_timeout_matrix(
    tmp_path: Path, capability: str
) -> None:
    nucleus = _nucleus(tmp_path / f"{capability}.sqlite3")
    port = _Port()
    composition = create_capability_composition_v1(
        nucleus=nucleus, port_factories={capability: lambda: port}
    )
    session = nucleus.begin_session()
    operation = sorted(CAPABILITY_OPERATIONS[capability])[0]

    allowed = composition.dispatch(session, capability, operation, {})
    assert allowed.outcome == "completed"

    revoked = composition.plan(session, capability, operation, {})
    composition.terminate("revoke", binding_id=revoked.binding.binding_id)
    with pytest.raises(GovernanceV1Denied, match="revoked"):
        composition.host.dispatch(revoked.binding, {})

    port.timeout = True
    timed_out = composition.dispatch(session, capability, operation, {})
    assert timed_out.outcome == "failed"
    assert timed_out.reason == "TimeoutError"


def test_main_composes_after_governance_and_cleans_partial_and_shutdown() -> None:
    source = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
    governance = source.index("governance_activation.initialize_host(self)")
    composition = source.index("create_capability_composition_v1(", governance)
    provider = source.index("founder_activation.initialize_host(self)", composition)
    assert governance < composition < provider
    assert source.count('"Capability composition V1"') == 2
    assert source.count("capability_composition.shutdown") == 2
    assert "capability_composition.kill" not in source
    assert "capability_composition.host.dispatch" not in source
