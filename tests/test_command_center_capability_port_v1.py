"""Adversarial tests for the provider-free A14 Command Center projection."""

from __future__ import annotations

import json

import pytest

from core.capability_ports.command_center_v1 import CommandCenterCapabilityPortV1
from core.governance_nucleus_v1 import GovernanceV1ContractError, GovernanceV1Denied


def _receipt(correlation_id: str = "receipt-a", **changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "correlation_id": correlation_id,
        "principal_id": "owner",
        "workspace_id": "workspace-a",
    }
    value.update(changes)
    return value


def _row(kind: str, **changes: object) -> dict[str, object]:
    identifiers = {
        "capability": {"capability_id": "cap-a", "status": "verified"},
        "mission": {"mission_id": "mission-a", "state": "succeeded"},
        "evidence": {"evidence_id": "evidence-a", "status": "verified"},
        "budget": {"budget_id": "budget-a", "status": "verified", "remaining_micro": 10},
    }
    value: dict[str, object] = {
        "principal_id": "owner",
        "workspace_id": "workspace-a",
        "captured_at": 990,
        "receipt_correlation_id": "receipt-a",
        **identifiers[kind],
    }
    value.update(changes)
    return value


def _port(**changes: object) -> CommandCenterCapabilityPortV1:
    values: dict[str, object] = {
        "principal_id": "owner",
        "workspace_id": "workspace-a",
        "capability_snapshot": (_row("capability"),),
        "mission_snapshot": (_row("mission"),),
        "evidence_snapshot": (_row("evidence"),),
        "budget_snapshot": (_row("budget"),),
        "composition_receipts": (_receipt(),),
        "observed_at": 1_000,
        "freshness_seconds": 100,
        "max_rows": 10,
    }
    values.update(changes)
    return CommandCenterCapabilityPortV1(**values)


def test_projection_marks_stale_rows_and_preserves_deterministic_cli_parity() -> None:
    port = _port(mission_snapshot=(_row("mission", captured_at=899),))
    first = port.project(principal_id="owner", workspace_id="workspace-a")
    second = port.project(principal_id="owner", workspace_id="workspace-a")
    assert first == second
    assert first["stale"] is True
    assert first["stale_sections"] == ("missions",)
    assert first["sections"]["missions"][0]["stale"] is True
    assert first["cli_status"] == second["cli_status"]


def test_overbroad_configuration_and_snapshots_fail_closed() -> None:
    with pytest.raises(GovernanceV1ContractError, match="overbroad"):
        _port(max_rows=101)
    with pytest.raises(GovernanceV1ContractError, match="overbroad"):
        _port(mission_snapshot=tuple(_row("mission", mission_id=f"m-{i}") for i in range(1_001)))


def test_principal_and_workspace_are_enforced_on_sources_receipts_and_queries() -> None:
    with pytest.raises(GovernanceV1Denied, match="cross-workspace"):
        _port(mission_snapshot=(_row("mission", workspace_id="workspace-b"),))
    with pytest.raises(GovernanceV1Denied, match="cross-workspace"):
        _port(composition_receipts=(_receipt(principal_id="intruder"),))
    with pytest.raises(GovernanceV1Denied, match="cross-workspace"):
        _port().project(principal_id="intruder", workspace_id="workspace-a")


def test_projection_filters_secrets_payloads_and_raw_paths() -> None:
    mission = _row(
        "mission",
        title=r"C:\private\mission.txt",
        api_key="super-secret",
        token="bearer-value",
        payload={"secret": "nested"},
        safe_extra="must-not-pass-allowlist",
    )
    rendered = json.dumps(_port(mission_snapshot=(mission,)).project(
        principal_id="owner", workspace_id="workspace-a"
    ))
    for forbidden in ("private", "super-secret", "bearer-value", "nested", "safe_extra"):
        assert forbidden not in rendered


def test_mismatched_or_missing_composition_receipt_is_denied() -> None:
    with pytest.raises(GovernanceV1Denied, match="correlation mismatch"):
        _port(mission_snapshot=(_row("mission", receipt_correlation_id="receipt-b"),))
    with pytest.raises(GovernanceV1Denied, match="correlation mismatch"):
        _port(composition_receipts=())


def test_empty_state_is_deterministic_bounded_and_truthful() -> None:
    port = _port(
        capability_snapshot=(), mission_snapshot=(), evidence_snapshot=(),
        budget_snapshot=(), composition_receipts=(),
    )
    result = port.project(principal_id="owner", workspace_id="workspace-a")
    assert result == port.project(principal_id="owner", workspace_id="workspace-a")
    assert result["row_count"] == 0
    assert result["sections"] == {name: () for name in ("capabilities", "missions", "evidence", "budgets")}
    assert result["redacted"] is result["read_only"] is True
    assert result["control_authorized"] is result["dispatch_authorized"] is False


def test_attempted_control_is_rejected_and_callbacks_cannot_be_injected() -> None:
    port = _port()
    with pytest.raises(GovernanceV1Denied, match="control"):
        port._dispatch_authorized("mission.cancel", {"principal_id": "owner", "workspace_id": "workspace-a"})
    with pytest.raises(GovernanceV1ContractError, match="fields mismatch"):
        port._dispatch_authorized("status.query", {
            "principal_id": "owner", "workspace_id": "workspace-a", "dispatch": lambda: None,
        })
    with pytest.raises(TypeError):
        _port(control_callback=lambda: None)
    assert not any(hasattr(port, name) for name in ("dispatch_control", "cancel", "run", "start"))


def test_projection_has_no_side_effects_and_copies_injected_snapshots() -> None:
    mission = _row("mission")
    receipts = [_receipt()]
    port = _port(mission_snapshot=[mission], composition_receipts=receipts)
    before = port.project(principal_id="owner", workspace_id="workspace-a")
    mission["state"] = "failed"
    receipts.clear()
    after = port.project(principal_id="owner", workspace_id="workspace-a")
    assert before == after

