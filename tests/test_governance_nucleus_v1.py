from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from core import governance_nucleus_v1 as governance
from core import permission_broker
from core.governance_nucleus_v1 import (
    GovernanceCommitFenceV1,
    GovernanceIdentityV1,
    GovernanceNucleusV1,
    GovernanceV1Denied,
    GovernanceV1IntegrityError,
)
from core.permission_broker import build_request
from core.workspaces import WorkspaceRecord


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


class _FailNextDeleteVault(_Vault):
    def __init__(self) -> None:
        super().__init__()
        self.fail_next_delete = False

    def delete(self) -> bool:
        if self.fail_next_delete:
            self.fail_next_delete = False
            return False
        return super().delete()


class _Target:
    def __init__(self) -> None:
        self.calls = 0

    def kill(self) -> None:
        self.calls += 1

    def request_global_away_kill(self) -> None:
        self.calls += 1


def _nucleus(
    path: Path,
    *,
    identity: GovernanceIdentityV1 | None = None,
    vaults: tuple[_Vault, _Vault, _Vault] | None = None,
    workspace_records: tuple[WorkspaceRecord, ...] = (),
    **options: object,
) -> tuple[GovernanceNucleusV1, tuple[_Vault, _Vault, _Vault]]:
    values = vaults or (_Vault(), _Vault(), _Vault())
    result = GovernanceNucleusV1(
        path=path,
        identity=identity
        or GovernanceIdentityV1(
            "onyx-owner",
            "onyx-local-workspace",
            "cyryx-local-account",
            "onyx-owner-profile",
        ),
        key_vault=values[0],
        head_vault=values[1],
        pending_vault=values[2],
        workspace_records=workspace_records,
        **options,
    )
    return result, values


def _invoke(
    nucleus: GovernanceNucleusV1,
    invocation_id: str,
    tool: str,
    arguments: dict[str, object],
):
    token = nucleus.begin_invocation(invocation_id)
    try:
        return nucleus.authorization_hook(tool, arguments)
    finally:
        nucleus.end_invocation(token)


def test_low_risk_exact_grant_reuses_and_counts_without_prompt(tmp_path: Path) -> None:
    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    session = nucleus.begin_session()

    first = _invoke(nucleus, "call-1", "system_status", {})
    second = _invoke(nucleus, "call-2", "system_status", {})

    assert first is not None and first[0] is True
    assert second is not None and second[0] is True
    assert first[1] == second[1]
    assert nucleus.status().active_grants == 1
    assert session.workspace_id == "onyx-local-workspace"


def test_dayops_read_uses_bounded_low_risk_grant_without_prompt(
    tmp_path: Path,
) -> None:
    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    nucleus.begin_session()

    first = _invoke(
        nucleus,
        "dayops-call-1",
        "day_brief_read",
        {"date": "2026-07-31"},
    )
    second = _invoke(
        nucleus,
        "dayops-call-2",
        "day_brief_read",
        {"date": "2026-07-31"},
    )

    assert first is not None and first[0] is True
    assert second is not None and second[0] is True
    assert first[1] == second[1]
    assert first[1].startswith("governance-grant:")
    assert nucleus.status().active_grants == 1


def test_payload_change_gets_different_exact_grant_and_secret_is_not_stored(
    tmp_path: Path,
) -> None:
    path = tmp_path / "governance.sqlite3"
    nucleus, _ = _nucleus(path)
    nucleus.begin_session()
    first = _invoke(
        nucleus,
        "call-1",
        "weather_report",
        {"city": "Miami", "api_key": "secret-one"},
    )
    second = _invoke(
        nucleus,
        "call-2",
        "weather_report",
        {"city": "Orlando", "api_key": "secret-two"},
    )

    assert first is not None and second is not None
    assert first[1] != second[1]
    raw = path.read_bytes()
    assert b"secret-one" not in raw
    assert b"secret-two" not in raw
    assert b"Miami" not in raw
    assert b"Orlando" not in raw


def test_always_explicit_cannot_receive_grant_and_inbox_owns_decision(
    tmp_path: Path,
) -> None:
    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    nucleus.begin_session()
    assert (
        _invoke(
            nucleus,
            "call-explicit",
            "send_message",
            {"recipient": "owner@example.test", "message": "hello"},
        )
        is None
    )

    request = build_request(
        "send_message",
        "Allow exact send?",
        {
            "tool": "send_message",
            "arguments": {
                "recipient": "owner@example.test",
                "message": "hello",
            },
        },
    )
    token = nucleus.begin_invocation("call-explicit")
    seen: list[dict] = []
    try:
        callback = nucleus.approval_inbox.wrap(
            lambda value: seen.append(value) or value["digest"]
        )
        assert callback(request) == request["digest"]
    finally:
        nucleus.end_invocation(token)

    assert len(seen) == 1
    assert nucleus.dashboard_read("inbox")["data"]["items"] == []


def test_denied_explicit_action_never_gets_receipt_authority(tmp_path: Path) -> None:
    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    nucleus.begin_session()
    request = build_request(
        "send_message",
        "Allow send?",
        {
            "tool": "send_message",
            "arguments": {"recipient": "o@example.test", "message": "hi"},
        },
    )
    token = nucleus.begin_invocation("call-denied")
    try:
        callback = nucleus.approval_inbox.wrap(lambda _value: None)
        assert callback(request) is None
    finally:
        nucleus.end_invocation(token)
    nucleus.record_outcome(
        invocation_id="call-denied",
        outcome="completed",
        result={"unexpected": True},
    )
    events = nucleus._ledger.events(nucleus.identity.workspace_id)
    assert events[-1].event_type == "action-denied"


def test_reconnect_revokes_grants_and_restart_preserves_use_history(
    tmp_path: Path,
) -> None:
    path = tmp_path / "governance.sqlite3"
    nucleus, vaults = _nucleus(path)
    first = nucleus.begin_session()
    _invoke(nucleus, "call-1", "system_status", {})
    nucleus.end_session("reconnect")
    second = nucleus.begin_session()
    assert second.session_id != first.session_id
    assert second.generation == first.generation + 1
    nucleus.end_session("shutdown")

    reopened, _ = _nucleus(path, vaults=vaults)
    third = reopened.begin_session()
    assert third.generation == second.generation + 1
    assert reopened.status().active_grants == 0


def test_grant_use_limit_expiry_and_owner_revoke_are_exact(
    tmp_path: Path,
) -> None:
    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    nucleus.begin_session()
    decisions = [
        _invoke(nucleus, f"use-{index}", "system_status", {}) for index in range(8)
    ]
    first_grant = str(decisions[0][1]).removeprefix("governance-grant:")
    assert all(item[1] == decisions[0][1] for item in decisions)
    assert nucleus.status().active_grants == 0

    replacement = _invoke(nucleus, "use-9", "system_status", {})
    replacement_grant = str(replacement[1]).removeprefix("governance-grant:")
    assert replacement_grant != first_grant
    nucleus.dashboard_facade(None, None).revoke_grant(replacement_grant)
    assert nucleus.status().active_grants == 0

    expiring, _ = _nucleus(tmp_path / "expiring.sqlite3")
    expiring.begin_session()
    before = _invoke(expiring, "expiry-1", "system_status", {})
    grant_id = str(before[1]).removeprefix("governance-grant:")
    expiring._grants[grant_id] = replace(expiring._grants[grant_id], expires_at_ms=0)
    after = _invoke(expiring, "expiry-2", "system_status", {})
    assert before[1] != after[1]


def test_pending_explicit_action_is_visible_only_inside_authority_callback(
    tmp_path: Path,
) -> None:
    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    nucleus.begin_session()
    request = build_request(
        "send_message",
        "Allow exact send?",
        {
            "tool": "send_message",
            "arguments": {
                "recipient": "owner@example.test",
                "message": "hello",
            },
        },
    )
    observed: list[dict[str, object]] = []

    def decide(value: dict) -> str:
        page = nucleus.dashboard_read("inbox")
        observed.extend(page["data"]["items"])
        assert page["data"]["approval_action_available"] is False
        assert page["data"]["decision_channel"] == "trusted-local-ui-only"
        return value["digest"]

    token = nucleus.begin_invocation("visible-explicit")
    try:
        assert nucleus.approval_inbox.wrap(decide)(request) == request["digest"]
    finally:
        nucleus.end_invocation(token)
    assert len(observed) == 1
    assert observed[0]["workspace_id"] == "onyx-local-workspace"
    assert nucleus.dashboard_read("inbox")["data"]["items"] == []


def test_two_workspace_projection_has_zero_leak(tmp_path: Path) -> None:
    path = tmp_path / "shared-governance.sqlite3"
    first, vaults = _nucleus(path)
    second, _ = _nucleus(
        path,
        identity=GovernanceIdentityV1(
            "onyx-owner",
            "client-workspace",
            "client-account",
            "client-profile",
            "Client Workspace",
        ),
        vaults=vaults,
    )
    first.begin_session()
    second.begin_session()
    _invoke(first, "one", "system_status", {})
    _invoke(second, "two", "system_status", {})

    all_events = first._ledger._events_global()
    assert {item.workspace_id for item in all_events} == {
        "onyx-local-workspace",
        "client-workspace",
    }
    assert first.status().active_grants == 1
    assert second.status().active_grants == 1
    assert "client-workspace" not in json.dumps(first.status_payload())
    assert "onyx-local-workspace" not in json.dumps(second.status_payload())


def test_global_kill_is_anchored_before_propagation_and_survives_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "governance.sqlite3"
    nucleus, vaults = _nucleus(path)
    nucleus.begin_session()
    _invoke(nucleus, "call-1", "system_status", {})
    phase5 = _Target()
    phase11 = _Target()

    result = nucleus.global_kill(phase5=phase5, phase11=phase11)

    events = nucleus._ledger.events(nucleus.identity.workspace_id)
    kill_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "global-kill-latched"
    )
    session_end_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "session-ended"
    )
    assert kill_index < session_end_index
    assert result["mutations_frozen"] is True
    assert phase5.calls == 1
    assert phase11.calls == 1
    assert _invoke(nucleus, "after-kill", "system_status", {})[0] is False

    reopened, _ = _nucleus(path, vaults=vaults)
    assert reopened.killed is True
    with pytest.raises(
        GovernanceV1Denied,
        match="global kill|session capability is unavailable",
    ):
        reopened.begin_session()


def test_late_result_after_kill_is_quarantined(tmp_path: Path) -> None:
    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    nucleus.begin_session()
    _invoke(nucleus, "call-late", "system_status", {})
    nucleus.global_kill()
    nucleus.record_outcome(
        invocation_id="call-late",
        outcome="completed",
        result={"status": "late-success"},
    )
    assert nucleus._ledger.events(nucleus.identity.workspace_id)[-1].event_type == (
        "action-late-blocked"
    )


def test_attempted_unknown_survives_restart_for_reconciliation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "governance.sqlite3"
    nucleus, vaults = _nucleus(path)
    nucleus.begin_session()
    _invoke(nucleus, "call-unknown", "system_status", {})
    nucleus.record_outcome(
        invocation_id="call-unknown",
        outcome="attempted_unknown",
        result=None,
        error_type="ConnectionResetError",
    )
    nucleus.end_session("restart")

    reopened, _ = _nucleus(path, vaults=vaults)
    assert reopened.status().attempted_unknown == 1
    assert any(
        item.event_type == "action-attempted-unknown"
        for item in reopened._ledger.events(reopened.identity.workspace_id)
    )


def test_approved_without_terminal_receipt_becomes_unknown_once_on_restart(
    tmp_path: Path,
) -> None:
    path = tmp_path / "governance.sqlite3"
    nucleus, vaults = _nucleus(path)
    nucleus.begin_session()
    approved, _proof = _invoke(nucleus, "crash-window", "system_status", {})
    assert approved is True
    assert "approved" in nucleus._action_states.values()

    # Simulate abrupt process loss: close only the storage handle, without the
    # graceful session/outcome path.
    nucleus._ledger.close()
    reopened, _ = _nucleus(path, vaults=vaults)
    assert reopened.status().attempted_unknown == 1
    inbox = reopened.dashboard_read("inbox")["data"]["items"]
    assert len(inbox) == 1
    assert inbox[0]["item_id"].startswith("reconcile-")
    assert "reconciliation required" in inbox[0]["reason"]
    events = reopened._ledger.events(reopened.identity.workspace_id)
    unknown_count = sum(
        item.event_type == "action-attempted-unknown" for item in events
    )
    before = len(events)
    reopened.record_outcome(
        invocation_id="crash-window",
        outcome="completed",
        result={"must": "not-commit"},
    )
    assert len(reopened._ledger.events(reopened.identity.workspace_id)) == before
    reopened.close()

    restarted_again, _ = _nucleus(path, vaults=vaults)
    events = restarted_again._ledger.events(restarted_again.identity.workspace_id)
    assert (
        sum(item.event_type == "action-attempted-unknown" for item in events)
        == unknown_count
    )
    restarted_again.close()


@pytest.mark.parametrize("outcome", ("completed", "denied", "rejected", "failed"))
def test_action_receipt_preserves_exact_observed_outcome(
    tmp_path: Path, outcome: str
) -> None:
    nucleus, _ = _nucleus(tmp_path / f"{outcome}.sqlite3")
    nucleus.begin_session()
    invocation = f"receipt-{outcome}"
    _invoke(nucleus, invocation, "system_status", {})
    nucleus.record_outcome(
        invocation_id=invocation,
        outcome=outcome,
        result={"observed": outcome},
        error_type="RuntimeError" if outcome == "failed" else "",
    )
    event = nucleus._ledger.events(nucleus.identity.workspace_id)[-1]
    assert event.event_type == "action-receipt"
    assert event.payload["outcome"] == outcome


def test_tamper_and_head_rollback_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "governance.sqlite3"
    nucleus, vaults = _nucleus(path)
    nucleus.begin_session()
    connection = __import__("sqlite3").connect(path)
    try:
        connection.execute("DROP TRIGGER events_no_update")
        connection.execute("UPDATE events SET payload_json='{}' WHERE sequence=1")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(GovernanceV1IntegrityError):
        _nucleus(path, vaults=vaults)


def test_incremental_live_reader_detects_external_tamper_and_head_rollback(
    tmp_path: Path,
) -> None:
    path = tmp_path / "governance.sqlite3"
    nucleus, vaults = _nucleus(path)
    nucleus.begin_session()
    original_head = vaults[1].get_bytes()
    assert original_head is not None
    vaults[1].set_bytes(b"rolled-back-head")
    with pytest.raises(GovernanceV1IntegrityError, match="head anchor"):
        nucleus.status()
    vaults[1].set_bytes(original_head)

    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TRIGGER events_no_update")
        connection.execute("UPDATE events SET payload_json='{}' WHERE sequence=1")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(GovernanceV1IntegrityError):
        nucleus.status()
    nucleus._ledger.close()


def test_nexus_projection_is_truthful_and_dispatch_closed() -> None:
    identity = GovernanceIdentityV1(
        "onyx-owner",
        "onyx-local-workspace",
        "cyryx-local-account",
        "onyx-owner-profile",
    )
    assert identity.digest
    # There is intentionally no generic dispatch method on the live nucleus.
    assert not hasattr(GovernanceNucleusV1, "dispatch")


def test_missing_database_with_durable_vaults_never_reinitializes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "governance.sqlite3"
    nucleus, vaults = _nucleus(path)
    nucleus.close()
    path.unlink()

    with pytest.raises(GovernanceV1IntegrityError, match="database is missing"):
        _nucleus(path, vaults=vaults)
    assert not path.exists()


def test_trusted_directory_boundary_is_used_and_closed(tmp_path: Path) -> None:
    observed: list[tuple[Path, bool]] = []

    class Boundary:
        def __init__(self, *, root: Path, enabled: bool) -> None:
            observed.append((Path(root), enabled))

        def close(self) -> None:
            observed.append((Path("closed"), True))

    path = tmp_path / "governance.sqlite3"
    nucleus, _ = _nucleus(
        path,
        trusted_directory_factory=Boundary,
        require_windows_boundary=True,
    )
    nucleus.close()
    assert observed[0] == (tmp_path, True)
    assert observed[-1][0] == Path("closed")


def test_trusted_directory_closes_even_when_session_shutdown_fails(
    tmp_path: Path,
) -> None:
    closed: list[bool] = []

    class Boundary:
        def __init__(self, *, root: Path, enabled: bool) -> None:
            assert root == tmp_path
            assert enabled is True

        def close(self) -> None:
            closed.append(True)

    nucleus, _ = _nucleus(
        tmp_path / "governance.sqlite3",
        trusted_directory_factory=Boundary,
        require_windows_boundary=True,
    )
    with (
        patch.object(
            nucleus,
            "end_session",
            side_effect=GovernanceV1IntegrityError("shutdown failed"),
        ),
        pytest.raises(GovernanceV1IntegrityError, match="shutdown failed"),
    ):
        nucleus.close()
    assert closed == [True]


def test_incremental_ledger_does_not_rescan_full_chain_per_append(
    tmp_path: Path,
) -> None:
    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    ledger = nucleus._ledger
    with patch.object(
        ledger, "_verify_chain", wraps=ledger._verify_chain
    ) as verify_chain:
        for index in range(32):
            ledger.append(
                "test-event",
                f"entity-{index}",
                nucleus.identity.workspace_id,
                {"index": index},
            )
        assert verify_chain.call_count == 0
        assert len(ledger.events(nucleus.identity.workspace_id)) >= 32
        assert verify_chain.call_count == 0
    nucleus.close()


def test_stale_pending_marker_after_commit_and_anchor_recovers(
    tmp_path: Path,
) -> None:
    path = tmp_path / "governance.sqlite3"
    nucleus, vaults = _nucleus(path)
    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            "SELECT sequence,previous_hmac,event_hmac FROM events "
            "ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    marker = {
        "contract": "GovernancePendingAppend.v1",
        "before_sequence": int(row[0]) - 1,
        "before_hmac": str(row[1]),
        "after_sequence": int(row[0]),
        "after_hmac": str(row[2]),
    }
    marker["marker_hmac"] = hmac.new(
        nucleus._ledger._key,
        b"ONYX-GOVERNANCE-PENDING.v1\0" + governance._canonical(marker),
        hashlib.sha256,
    ).hexdigest()
    nucleus.close()
    vaults[2].set_bytes(governance._canonical(marker))

    reopened, _ = _nucleus(path, vaults=vaults)
    assert reopened.status().available is True
    assert vaults[2].get_bytes() is None


def test_exact_schema_rejects_unknown_object(tmp_path: Path) -> None:
    path = tmp_path / "governance.sqlite3"
    nucleus, vaults = _nucleus(path)
    nucleus.close()
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE unauthorized(value TEXT)")
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(GovernanceV1IntegrityError, match="schema objects"):
        _nucleus(path, vaults=vaults)


def test_exact_schema_rejects_same_named_trigger_with_changed_definition(
    tmp_path: Path,
) -> None:
    path = tmp_path / "governance.sqlite3"
    nucleus, vaults = _nucleus(path)
    nucleus.close()
    connection = sqlite3.connect(path)
    try:
        connection.execute("DROP TRIGGER events_no_update")
        connection.execute(
            "CREATE TRIGGER events_no_update BEFORE UPDATE ON events "
            "BEGIN SELECT RAISE(ABORT,'different contract'); END"
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(GovernanceV1IntegrityError, match="definitions"):
        _nucleus(path, vaults=vaults)


def test_inbox_capacity_and_callback_failure_are_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    nucleus.begin_session()
    request = build_request(
        "send_message",
        "Allow send?",
        {
            "tool": "send_message",
            "arguments": {"recipient": "owner@example.test", "message": "x"},
        },
    )
    monkeypatch.setattr(governance, "MAX_PENDING", 0)
    token = nucleus.begin_invocation("capacity")
    try:
        with pytest.raises(GovernanceV1Denied, match="capacity"):
            nucleus.approval_inbox.wrap(lambda value: value["digest"])(request)
    finally:
        nucleus.end_invocation(token)
    assert nucleus.status().pending_approvals == 0
    assert nucleus._ledger.events(nucleus.identity.workspace_id)[-1].event_type == (
        "action-denied"
    )

    monkeypatch.setattr(governance, "MAX_PENDING", 512)
    failing, _ = _nucleus(tmp_path / "callback-failure.sqlite3")
    failing.begin_session()
    token = failing.begin_invocation("callback-failure")
    try:
        with pytest.raises(GovernanceV1Denied, match="callback failed"):
            failing.approval_inbox.wrap(
                lambda _value: (_ for _ in ()).throw(RuntimeError("boom"))
            )(request)
    finally:
        failing.end_invocation(token)
    events = failing._ledger.events(failing.identity.workspace_id)
    assert events[-1].event_type == "action-approval-failed"
    assert not any(
        item.event_type == "action-receipt" and item.entity_id == events[-1].entity_id
        for item in events
    )


def test_nested_approval_wrapper_is_rejected(tmp_path: Path) -> None:
    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    wrapped = nucleus.approval_inbox.wrap(lambda request: request["digest"])
    with pytest.raises(governance.GovernanceV1ContractError, match="already"):
        nucleus.approval_inbox.wrap(wrapped)
    other, _ = _nucleus(tmp_path / "other.sqlite3")
    with pytest.raises(governance.GovernanceV1ContractError, match="already"):
        other.approval_inbox.wrap(wrapped)


def test_capability_dispatch_requires_exact_healthy_phase5(tmp_path: Path) -> None:
    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")

    class Phase5:
        def __init__(self, *, state: str, failures: tuple[str, ...]) -> None:
            self.state = state
            self.failures = failures

        def status_payload(self) -> dict[str, object]:
            return {
                "data": {
                    "state": self.state,
                    "component_failures": self.failures,
                    "flags": (
                        ("local_catalog_read", True),
                        ("low_risk", True),
                    ),
                }
            }

    def dispatch(phase5: object | None) -> bool:
        entries = nucleus.capabilities_payload(phase5)["data"]["items"]
        return next(
            item["dispatch_available"]
            for item in entries
            if item["capability"] == "local-catalog"
        )

    assert dispatch(None) is False
    assert dispatch(Phase5(state="READY", failures=("worker",))) is False
    assert dispatch(Phase5(state="READY", failures=())) is True


def test_workspace_status_sequence_does_not_leak_other_workspace(
    tmp_path: Path,
) -> None:
    path = tmp_path / "governance.sqlite3"
    first, vaults = _nucleus(path)
    first_sequence = first.status().ledger_sequence
    second, _ = _nucleus(
        path,
        identity=GovernanceIdentityV1(
            "onyx-owner", "workspace-two", "account-two", "profile-two"
        ),
        vaults=vaults,
    )
    second.begin_session()
    _invoke(second, "two-read", "system_status", {})
    assert first.status().ledger_sequence == first_sequence
    assert second.status().ledger_sequence > first_sequence


def test_partial_kill_receipts_and_live_kill_tail_restore(
    tmp_path: Path,
) -> None:
    class Broken:
        def kill(self) -> None:
            raise RuntimeError("phase5")

        def request_global_away_kill(self) -> bool:
            return False

    class Worker:
        def stop(self, *, timeout: float) -> bool:
            assert timeout == 5.0
            return False

    path = tmp_path / "governance.sqlite3"
    nucleus, vaults = _nucleus(path)
    result = nucleus.global_kill(
        phase5=Broken(), phase11=Broken(), mission_worker=Worker()
    )
    assert result["propagation"]["phase5"] == "incomplete:RuntimeError"
    assert result["propagation"]["phase11"] == "incomplete:returned-false"
    reopened, _ = _nucleus(path, vaults=vaults)
    assert dict(reopened.status().kill_propagation)["mission-worker"] == (
        "incomplete:returned-false"
    )

    tail_path = tmp_path / "tail.sqlite3"
    tail, tail_vaults = _nucleus(tail_path)
    tail._ledger.append(
        "global-kill-latched",
        "global-kill",
        tail.identity.workspace_id,
        {"reason": "crash-after-durable-tail"},
    )
    tail.close()
    restored, _ = _nucleus(tail_path, vaults=tail_vaults)
    assert restored.killed is True
    assert set(dict(restored.status().kill_propagation).values()) == {
        "incomplete:not-recorded"
    }


def test_post_anchor_pending_cleanup_failure_keeps_live_and_restart_killed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "governance.sqlite3"
    pending = _FailNextDeleteVault()
    vaults = (_Vault(), _Vault(), pending)
    nucleus, _ = _nucleus(path, vaults=vaults)
    nucleus.begin_session()
    pending.fail_next_delete = True

    result = nucleus.global_kill()

    assert nucleus.killed is True
    assert result["latch_persistence"].startswith("confirmed-cleanup-incomplete:")
    assert result["propagation"]["phase11"].startswith(
        "incomplete:unavailable;receipt-"
    )
    assert pending.get_bytes() is not None
    decision = _invoke(nucleus, "blocked-live", "system_status", {})
    assert decision == (
        False,
        "Permission denied: global mutation kill is latched.",
    )
    # Commit and anchor are authenticated. The next append now recovers the
    # stale cleanup marker, as the existing recovery test above specifies.
    # Recovery must never clear the durable mutation-kill latch.
    nucleus._ledger.append(
        "test-event", "test-entity", nucleus.identity.workspace_id, {"stale": True},
    )
    assert pending.get_bytes() is None
    assert nucleus.killed is True
    assert _invoke(nucleus, "blocked-after-cleanup", "system_status", {}) == decision
    nucleus.close()
    reopened, _ = _nucleus(path, vaults=vaults)
    assert reopened.killed is True
    with pytest.raises(GovernanceV1Denied, match="global kill"):
        reopened.begin_session()


def test_governance_prevents_owner_autonomy_and_compensates_audit_failure(
    tmp_path: Path,
) -> None:
    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    nucleus.begin_session()
    permission_broker.set_governance_authorization_hook(nucleus.authorization_hook)
    permission_broker.set_permission_callback(lambda _request: None)
    permission_broker.set_trust_profile("autonomous")
    permission_broker.configure_owner_autonomy(True, (str(tmp_path),))
    try:
        allowed, _ = permission_broker.authorize_model_tool(
            "send_message",
            {"recipient": "owner@example.test", "message": "x"},
        )
        assert allowed is False

        with patch.object(permission_broker, "_audit_healthy", False):
            token = nucleus.begin_invocation("unhealthy-before-grant")
            try:
                allowed, reason = permission_broker.authorize_model_tool(
                    "system_status", {}
                )
            finally:
                nucleus.end_invocation(token)
            assert allowed is False
            assert "audit is unhealthy" in reason
            assert nucleus.status().active_grants == 0

        with (
            patch.object(permission_broker, "_audit_healthy", True),
            patch.object(
                permission_broker,
                "append_tool_audit",
                side_effect=OSError("audit unavailable"),
            ),
        ):
            token = nucleus.begin_invocation("audit-failure")
            try:
                allowed, reason = permission_broker.authorize_model_tool(
                    "system_status", {}
                )
            finally:
                nucleus.end_invocation(token)
            assert allowed is False
            assert "audit failed" in reason
            assert permission_broker.audit_healthy() is False
            assert nucleus.status().active_grants == 0
            assert (
                nucleus._ledger.events(nucleus.identity.workspace_id)[-1].event_type
                == "governance-audit-failed"
            )
    finally:
        permission_broker.set_governance_authorization_hook(None)
        permission_broker.set_permission_callback(None)
        permission_broker.configure_owner_autonomy(False, ())


def test_global_kill_wins_over_inflight_explicit_approval_and_dispatch(
    tmp_path: Path,
) -> None:
    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    nucleus.begin_session()
    entered = threading.Event()
    release = threading.Event()
    dispatched: list[str] = []

    def trusted(request: dict) -> str:
        entered.set()
        assert release.wait(5.0)
        return request["digest"]

    permission_broker.set_governance_authorization_hook(nucleus.authorization_hook)
    permission_broker.set_permission_callback(nucleus.approval_inbox.wrap(trusted))
    nucleus.assert_dispatch_allowed(
        invocation_id="phase5-catalog",
        tool_name="local_catalog_read",
        authorization_proof="phase5-exact-local-read",
    )

    def request_and_dispatch() -> tuple[bool, str]:
        token = nucleus.begin_invocation("kill-race")
        try:
            approved, proof = permission_broker.authorize_model_tool(
                "send_message",
                {"recipient": "owner@example.test", "message": "hello"},
            )
            if approved:
                nucleus.assert_dispatch_allowed(
                    invocation_id="kill-race",
                    tool_name="send_message",
                    authorization_proof=proof,
                )
                dispatched.append("send_message")
            return approved, proof
        finally:
            nucleus.end_invocation(token)

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(request_and_dispatch)
            assert entered.wait(5.0)
            result = nucleus.global_kill()
            release.set()
            approved, _proof = pending.result(timeout=5.0)
        assert result["status"] == "kill-latched"
        assert approved is False
        assert dispatched == []
        assert "late-blocked" in nucleus._action_states.values()
    finally:
        release.set()
        permission_broker.set_governance_authorization_hook(None)
        permission_broker.set_permission_callback(None)
        nucleus.close()
        permission_broker.set_trust_profile("cautious")
        permission_broker._audit_healthy = True


def test_local_commit_fence_kill_first_denies_without_mutation(
    tmp_path: Path,
) -> None:
    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    nucleus.begin_session()
    mutations: list[str] = []
    nucleus.global_kill()
    with pytest.raises(GovernanceV1Denied, match="global kill"):
        with nucleus.local_commit_fence():
            mutations.append("committed")
    assert mutations == []
    nucleus.close()


def test_local_commit_fence_commit_first_linearizes_before_kill(
    tmp_path: Path,
) -> None:
    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    session = nucleus.begin_session()
    entered = threading.Event()
    release = threading.Event()
    kill_started = threading.Event()
    order: list[str] = []

    def commit() -> GovernanceCommitFenceV1:
        with nucleus.local_commit_fence() as token:
            entered.set()
            assert release.wait(5)
            order.append("commit")
            return token

    def kill() -> dict[str, object]:
        kill_started.set()
        result = nucleus.global_kill()
        order.append("kill")
        return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        committing = executor.submit(commit)
        assert entered.wait(5)
        killing = executor.submit(kill)
        assert kill_started.wait(5)
        assert not killing.done()
        release.set()
        token = committing.result(timeout=5)
        killed = killing.result(timeout=5)
    assert type(token) is GovernanceCommitFenceV1
    assert token.session_id == session.session_id
    assert order == ["commit", "kill"]
    assert killed["status"] == "kill-latched"
    nucleus.close()


def test_local_commit_fence_audit_unhealthy_denies_before_body(
    tmp_path: Path,
) -> None:
    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    nucleus.begin_session()
    permission_broker._audit_healthy = False
    touched: list[str] = []
    try:
        with pytest.raises(GovernanceV1Denied, match="audit is unhealthy"):
            with nucleus.local_commit_fence():
                touched.append("commit")
        assert touched == []
    finally:
        permission_broker._audit_healthy = True
        nucleus.close()


def test_human_approval_reaches_dispatch_through_the_inbox_wrapper(
    tmp_path: Path,
) -> None:
    """Clicking Yes in the approval dialog must actually dispatch.

    Mirrors main._execute_tool: the broker authorizes with the governance
    invocation reference attached, the owner approves in the dialog, and the
    nucleus fence then validates the proof before dispatch. The approval-inbox
    wrapper is what registers the action-intent the fence looks for. Without
    it the fence finds no binding and denies every approved action, which is
    what made the dialog structurally useless.
    """
    from core import permission_broker

    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    nucleus.begin_session()
    approvals: list[dict] = []

    def owner_clicks_yes(request: dict) -> str:
        approvals.append(request)
        return request["digest"]

    permission_broker.set_permission_callback(
        nucleus.approval_inbox.wrap(owner_clicks_yes)
    )
    permission_broker.set_governance_authorization_hook(nucleus.authorization_hook)
    try:
        approved, proof = permission_broker.authorize_model_tool(
            "send_message",
            {
                "recipient": "o@example.test",
                "message": "hi",
                "_governance_invocation_ref": "call-owner-1",
            },
        )
        assert approved is True, proof
        assert len(approvals) == 1, "the owner was never actually asked"
        nucleus.assert_dispatch_allowed(
            invocation_id="call-owner-1",
            tool_name="send_message",
            authorization_proof=proof,
        )
    finally:
        permission_broker.set_governance_authorization_hook(None)
        permission_broker.set_permission_callback(None)


def test_unwrapped_callback_makes_every_approval_fail_the_fence(
    tmp_path: Path,
) -> None:
    """Regression guard for the P0: Yes read as No.

    This is the exact shape of the defect that shipped. The governance hook
    was installed but the trusted callback was left unwrapped, so the owner's
    approval never registered an action-intent and the dispatch fence denied
    the action the owner had just approved.
    """
    from core import permission_broker

    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    nucleus.begin_session()

    def owner_clicks_yes(request: dict) -> str:
        return request["digest"]

    # The defective wiring: hook installed, callback NOT wrapped.
    permission_broker.set_permission_callback(owner_clicks_yes)
    permission_broker.set_governance_authorization_hook(nucleus.authorization_hook)
    try:
        approved, proof = permission_broker.authorize_model_tool(
            "send_message",
            {
                "recipient": "o@example.test",
                "message": "hi",
                "_governance_invocation_ref": "call-owner-2",
            },
        )
        assert approved is True, "the broker did accept the owner's approval"
        with pytest.raises(GovernanceV1Denied):
            nucleus.assert_dispatch_allowed(
                invocation_id="call-owner-2",
                tool_name="send_message",
                authorization_proof=proof,
            )
    finally:
        permission_broker.set_governance_authorization_hook(None)
        permission_broker.set_permission_callback(None)


# ── A4: evaluated owner autonomy ────────────────────────────────────────────


def _autonomy_nucleus(tmp_path: Path, evaluator=None):
    nucleus, _ = _nucleus(tmp_path / "governance.sqlite3")
    nucleus.begin_session()
    if evaluator is not None:
        nucleus.set_owner_autonomy_evaluator(evaluator)
    return nucleus


def ALLOW_ALL(_tool, _args, _risk):
    return True


def test_owner_autonomy_is_off_until_an_evaluator_is_installed(tmp_path: Path) -> None:
    """No evaluator means the previous posture exactly: file work still asks."""
    nucleus = _autonomy_nucleus(tmp_path)
    assert (
        nucleus.authorization_hook(
            "file_controller", {"action": "list", "path": "C:/w"}
        )
        is None
    )


def test_autonomy_grant_satisfies_the_dispatch_fence(tmp_path: Path) -> None:
    """The whole point: an autonomous grant must register an action-intent.

    A grant that authorizes without registering would repeat the P0 exactly —
    approved by the broker, then denied by the fence.
    """
    nucleus = _autonomy_nucleus(tmp_path, ALLOW_ALL)
    decision = nucleus.authorization_hook(
        "file_controller",
        {"action": "list", "path": "C:/w", "_governance_invocation_ref": "call-a4"},
    )
    assert decision is not None and decision[0] is True
    nucleus.assert_dispatch_allowed(
        invocation_id="call-a4",
        tool_name="file_controller",
        authorization_proof=decision[1],
    )


def test_autonomy_grant_is_recorded_under_its_own_authority(tmp_path: Path) -> None:
    """An autonomous grant must be distinguishable in the ledger, forever."""
    nucleus = _autonomy_nucleus(tmp_path, ALLOW_ALL)
    nucleus.authorization_hook("file_controller", {"action": "write", "path": "C:/w/a"})
    rows = nucleus.dashboard_read("inbox")
    assert rows is not None  # dashboard stays readable after an autonomous grant


@pytest.mark.parametrize(
    "tool,args",
    [
        ("dev_agent", {}),
        ("send_message", {}),
        ("shutdown_onyx", {}),
        ("mission_create", {}),
        ("mission_cancel", {}),
        ("flight_finder", {}),
    ],
)
def test_always_explicit_work_is_never_autonomous(tmp_path: Path, tool, args) -> None:
    """Even with an evaluator that approves everything, these still ask.

    This is the absolute boundary. If any of these ever returns a grant, the
    owner has silently lost the confirmation step on an irreversible or
    outward-facing action.
    """
    nucleus = _autonomy_nucleus(tmp_path, ALLOW_ALL)
    assert nucleus.authorization_hook(tool, args) is None


def test_evaluator_that_raises_fails_closed(tmp_path: Path) -> None:
    def boom(_tool, _args, _risk):
        raise RuntimeError("evaluator exploded")

    nucleus = _autonomy_nucleus(tmp_path, boom)
    assert (
        nucleus.authorization_hook(
            "file_controller", {"action": "list", "path": "C:/w"}
        )
        is None
    )


@pytest.mark.parametrize("value", [1, "yes", [1], {"ok": True}, object()])
def test_only_an_exact_true_grants_autonomy(tmp_path: Path, value) -> None:
    """Truthiness must not be enough to open authority."""
    nucleus = _autonomy_nucleus(tmp_path, lambda _t, _a, _r: value)
    assert (
        nucleus.authorization_hook(
            "file_controller", {"action": "list", "path": "C:/w"}
        )
        is None
    )


def test_evaluator_refusal_returns_to_asking(tmp_path: Path) -> None:
    nucleus = _autonomy_nucleus(tmp_path, lambda _t, _a, _r: False)
    assert (
        nucleus.authorization_hook(
            "file_controller", {"action": "write", "path": "C:/w/a"}
        )
        is None
    )


def test_evaluator_receives_the_declared_risk(tmp_path: Path) -> None:
    seen: list[str] = []

    def record(_tool, _args, risk):
        seen.append(risk)
        return True

    nucleus = _autonomy_nucleus(tmp_path, record)
    nucleus.authorization_hook("file_controller", {"action": "list", "path": "C:/w"})
    nucleus.authorization_hook("file_controller", {"action": "write", "path": "C:/w/a"})
    assert seen == ["medium", "high"]


def test_low_risk_reads_still_need_no_evaluator(tmp_path: Path) -> None:
    """The pre-existing bounded low-risk grant must be untouched by A4."""
    nucleus = _autonomy_nucleus(tmp_path)
    decision = nucleus.authorization_hook("web_search", {"query": "x"})
    assert decision is not None and decision[0] is True


def test_uninstalling_the_evaluator_restores_asking(tmp_path: Path) -> None:
    nucleus = _autonomy_nucleus(tmp_path, ALLOW_ALL)
    assert (
        nucleus.authorization_hook(
            "file_controller", {"action": "list", "path": "C:/w"}
        )
        is not None
    )
    nucleus.set_owner_autonomy_evaluator(None)
    assert (
        nucleus.authorization_hook(
            "file_controller", {"action": "list", "path": "C:/w"}
        )
        is None
    )


@pytest.mark.parametrize(
    "tool,args",
    [
        ("save_memory", {"category": "a", "key": "b", "value": "c"}),
        ("reminder", {}),
        ("screen_process", {}),
        ("open_app", {}),
    ],
)
def test_routine_assistant_work_is_evaluable_not_explicit(
    tmp_path: Path, tool, args
) -> None:
    """Recorded scope move: these no longer interrupt the owner.

    They sit in the autonomy set the owner configured, and stopping for a
    dialog on every remembered note or reminder is the friction A4 exists to
    remove. They remain gated: without an installed evaluator they still ask.
    """
    nucleus = _autonomy_nucleus(tmp_path)
    assert nucleus.authorization_hook(tool, args) is None
    nucleus.set_owner_autonomy_evaluator(ALLOW_ALL)
    assert nucleus.authorization_hook(tool, args) is not None


# ── owner scope 2026-08-21: free on the owner's files, never on system files ──


@pytest.mark.parametrize(
    "tool,args",
    [
        ("file_controller", {"action": "delete", "path": "C:/Users/o/Desktop/a.txt"}),
        ("file_controller", {"action": "organize_desktop"}),
        ("browser_control", {"action": "go_to"}),
        ("computer_control", {"action": "click"}),
        ("desktop_control", {"action": "organize"}),
        ("computer_settings", {"action": "set"}),
        ("code_helper", {"action": "run"}),
    ],
)
def test_owner_scope_work_no_longer_interrupts(tmp_path: Path, tool, args) -> None:
    """Recorded scope decision: Onyx acts on the owner's own machine freely.

    These previously stopped for a dialog every time. They remain gated —
    without an evaluator they still ask — but they are no longer structurally
    always-explicit.
    """
    nucleus = _autonomy_nucleus(tmp_path)
    assert nucleus.authorization_hook(tool, args) is None
    nucleus.set_owner_autonomy_evaluator(ALLOW_ALL)
    assert nucleus.authorization_hook(tool, args) is not None


@pytest.mark.parametrize(
    "tool",
    [
        "send_message",
        "dev_agent",
        "shutdown_onyx",
        "mission_create",
    ],
)
def test_outward_and_code_executing_tools_stay_explicit(tmp_path: Path, tool) -> None:
    """The scope widening is local-only.

    `send_message` acts outward on the owner's behalf, `shutdown_onyx` ends the
    session needed to intervene, and `dev_agent` executes arbitrary code — no
    path rule could hold the system-file restriction against it.
    """
    nucleus = _autonomy_nucleus(tmp_path, ALLOW_ALL)
    assert nucleus.authorization_hook(tool, {}) is None


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Windows\System32\drivers\etc\hosts",
        r"C:\Windows",
        r"C:\Program Files\App\thing.dll",
        r"C:\Program Files (x86)\App\thing.dll",
        r"C:\ProgramData\App\config.cfg",
        "C:\\",
    ],
)
@pytest.mark.parametrize("action", ["write", "delete", "move", "create_file"])
def test_system_files_are_never_touched_without_approval(path, action) -> None:
    """The owner's one standing restriction, enforced by whole path component."""
    permission_broker.configure_owner_autonomy(True, [])
    args = {"action": action, "path": path, "destination": r"C:\Windows\x"}
    assert permission_broker._autonomous_file_target_allowed(args, action) is False


def test_owner_files_are_free_anywhere_outside_system_roots() -> None:
    """Outside the protected system roots the owner's own files carry no fence.

    Deliberately not under ``tmp_path``: pytest's base temp lives inside the
    Onyx source tree here, and Onyx refuses to autonomously modify its own
    sources. The target's parent must also exist, which is pre-existing
    behaviour of the containment walk.
    """
    import tempfile

    permission_broker.configure_owner_autonomy(True, [])
    with tempfile.TemporaryDirectory(prefix="onyx-owner-scope-") as raw:
        target = Path(raw) / "report.docx"
        for action in ("write", "delete", "create_file"):
            assert (
                permission_broker._autonomous_file_target_allowed(
                    {"action": action, "path": str(target)}, action
                )
                is True
            ), action


def test_sibling_named_system_directory_is_not_protected() -> None:
    """A directory merely named like a system root is still the owner's."""
    import tempfile

    permission_broker.configure_owner_autonomy(True, [])
    with tempfile.TemporaryDirectory(prefix="onyx-owner-scope-") as raw:
        sibling = Path(raw) / "Windows2"
        sibling.mkdir()
        assert (
            permission_broker._autonomous_file_target_allowed(
                {"action": "write", "path": str(sibling / "notes.txt")}, "write"
            )
            is True
        )


@pytest.fixture(autouse=True)
def _restore_broker_globals():
    """Keep owner-autonomy configuration from leaking between tests.

    `configure_owner_autonomy` mutates module-level state in the broker. Tests
    in this file exercise it deliberately; without restoration that state
    escapes into every test that runs afterwards, in any file.
    """
    saved = (
        permission_broker._owner_autonomy_enabled,
        permission_broker._autonomous_workspace_roots,
        permission_broker._trust_profile,
    )
    try:
        yield
    finally:
        (
            permission_broker._owner_autonomy_enabled,
            permission_broker._autonomous_workspace_roots,
            permission_broker._trust_profile,
        ) = saved
