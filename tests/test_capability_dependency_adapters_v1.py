from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from core.capability_composition_v1 import create_capability_composition_v1
from core.capability_ports.evidence_v1 import EvidenceValidationPortV1
from core.capability_ports.mission_context_v1 import MissionContextReadPortV1
from core.capability_ports.nexus_v1 import NexusProjectionPortV1
from core.capability_ports.workspace_v1 import WorkspaceShadowPortV1
from core.governance_nucleus_v1 import GovernanceIdentityV1, GovernanceNucleusV1, GovernanceV1ContractError, GovernanceV1Denied


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


def _nucleus(path: Path) -> GovernanceNucleusV1:
    return GovernanceNucleusV1(
        path=path,
        identity=GovernanceIdentityV1("owner", "workspace", "account", "profile"),
        key_vault=_Vault(), head_vault=_Vault(), pending_vault=_Vault(),
        require_windows_boundary=False,
    )


class _ContextStore:
    def __init__(self) -> None:
        self.calls = 0

    def get_context(self, workspace_id: str, mission_id: str) -> object:
        self.calls += 1
        return type("Record", (), {"revision": 1})()

    def list_events(self, workspace_id: str, mission_id: str) -> tuple[object, ...]:
        self.calls += 1
        return ()


def test_construction_has_no_owner_store_or_reader_side_effects(tmp_path: Path) -> None:
    calls: list[str] = []
    store = _ContextStore()
    workspace = WorkspaceShadowPortV1(
        workspace_id="workspace",
        primary_reader=lambda: calls.append("primary") or (),
        shadow_reader=lambda: calls.append("shadow") or (),
    )
    context = MissionContextReadPortV1(workspace_id="workspace", store=store)
    composition = create_capability_composition_v1(
        nucleus=_nucleus(tmp_path / "governance.sqlite3"),
        port_factories={"workspace": lambda: workspace, "mission_context": lambda: context},
    )
    assert calls == []
    assert store.calls == 0
    assert not hasattr(context, "initialize_context")
    composition.kill()


@pytest.mark.parametrize(
    "row",
    (
        {"workspace_id": "other"},
        {"workspace_id": "workspace", "is_link": True},
        {"workspace_id": "workspace", "linked_workspace_id": "other"},
    ),
)
def test_forged_linked_and_cross_workspace_shadow_rows_fail(row: dict[str, object], tmp_path: Path) -> None:
    port = WorkspaceShadowPortV1(workspace_id="workspace", primary_reader=lambda: (row,), shadow_reader=lambda: (row,))
    composition = create_capability_composition_v1(nucleus=_nucleus(tmp_path / "g.sqlite3"), port_factories={"workspace": lambda: port})
    receipt = composition.dispatch(_nucleus_session(composition), "workspace", "read.list", {})
    assert receipt.outcome == "failed"
    assert receipt.reason == "GovernanceV1Denied"


def _nucleus_session(composition: object):
    return composition.host._nucleus.begin_session()


def test_wrong_principal_workspace_and_stale_grant_never_reach_adapter(tmp_path: Path) -> None:
    calls: list[str] = []
    port = WorkspaceShadowPortV1(workspace_id="workspace", primary_reader=lambda: calls.append("read") or (), shadow_reader=lambda: ())
    nucleus = _nucleus(tmp_path / "g.sqlite3")
    composition = create_capability_composition_v1(nucleus=nucleus, port_factories={"workspace": lambda: port})
    plan = composition.plan(nucleus.begin_session(), "workspace", "read.list", {})
    for field, value in (("principal_id", "forged"), ("workspace_id", "other"), ("session_generation", 99)):
        with pytest.raises(GovernanceV1Denied):
            composition.host.dispatch(replace(plan.binding, **{field: value}), {})
    assert calls == []


def test_evidence_receipt_mismatch_replay_and_default_write_deny(tmp_path: Path) -> None:
    port = EvidenceValidationPortV1()
    nucleus = _nucleus(tmp_path / "g.sqlite3")
    composition = create_capability_composition_v1(nucleus=nucleus, port_factories={"evidence": lambda: port})
    session = nucleus.begin_session()
    mismatch = {"correlation_id": "a", "receipt_correlation_id": "b", "redacted": True}
    assert composition.dispatch(session, "evidence", "validate.receipt", mismatch).outcome == "failed"
    valid = {"correlation_id": "a", "receipt_correlation_id": "a", "redacted": True}
    assert composition.dispatch(session, "evidence", "validate.receipt", valid).outcome == "completed"
    assert composition.dispatch(session, "evidence", "validate.receipt", valid).outcome == "failed"
    denied = {"correlation_id": "write", "receipt_correlation_id": "write", "redacted": True}
    assert composition.dispatch(session, "evidence", "append.test", denied).outcome == "failed"


def test_provider_free_test_writer_is_host_authorized_and_kill_applies(tmp_path: Path) -> None:
    written: list[object] = []
    port = EvidenceValidationPortV1.provider_free_test_double(written.append)
    nucleus = _nucleus(tmp_path / "g.sqlite3")
    composition = create_capability_composition_v1(nucleus=nucleus, port_factories={"evidence": lambda: port})
    arguments = {"correlation_id": "test", "receipt_correlation_id": "test", "redacted": True}
    assert composition.dispatch(nucleus.begin_session(), "evidence", "append.test", arguments).outcome == "completed"
    assert len(written) == 1
    composition.kill()
    with pytest.raises(GovernanceV1Denied):
        composition.plan(nucleus.begin_session(), "evidence", "validate.receipt", arguments)


def test_nexus_projects_only_and_rejects_duplicate_unknown_and_direct_dispatch(tmp_path: Path) -> None:
    descriptor = {"capability_id": "alpha", "workspace_id": "workspace"}
    with pytest.raises(GovernanceV1ContractError, match="duplicate"):
        NexusProjectionPortV1(workspace_id="workspace", descriptors=(descriptor, descriptor))
    port = NexusProjectionPortV1(workspace_id="workspace", descriptors=(descriptor,))
    assert not hasattr(port, "register")
    with pytest.raises(GovernanceV1Denied, match="host-bound"):
        port.dispatch("read.list", {})
    nucleus = _nucleus(tmp_path / "g.sqlite3")
    composition = create_capability_composition_v1(nucleus=nucleus, port_factories={"nexus": lambda: port})
    receipt = composition.dispatch(nucleus.begin_session(), "nexus", "read.descriptor", {"capability_id": "unknown"})
    assert receipt.outcome == "failed"
    assert not hasattr(composition.router, "dispatch")

