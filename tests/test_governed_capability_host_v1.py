from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from unittest.mock import patch

import pytest

from core.governance_nucleus_v1 import (
    GovernanceIdentityV1,
    GovernanceNucleusV1,
    GovernanceV1Denied,
)
from core.governed_capability_host_v1 import (
    GovernedCapabilityHostV1,
    HostBoundCapabilityPortV1,
)


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
        self.revocations: list[str] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.kill_result: object = None

    def _dispatch_authorized(self, operation: str, arguments: dict[str, object]) -> object:
        self.calls += 1
        self.entered.set()
        if self.block:
            self.release.wait(5)
        return {"operation": operation, "value": arguments.get("value")}

    def revoke(self, binding_id: str) -> None:
        self.revocations.append(binding_id)

    def kill(self) -> object:
        self.kills += 1
        self.release.set()
        return self.kill_result


def _nucleus(path: Path, vaults: tuple[_Vault, _Vault, _Vault] | None = None):
    stores = vaults or (_Vault(), _Vault(), _Vault())
    nucleus = GovernanceNucleusV1(
        path=path,
        identity=GovernanceIdentityV1(
            "onyx-owner", "onyx-local-workspace", "cyryx-local-account",
            "onyx-owner-profile",
        ),
        key_vault=stores[0], head_vault=stores[1], pending_vault=stores[2],
    )
    return nucleus, stores


def _host(tmp_path: Path):
    nucleus, vaults = _nucleus(tmp_path / "governance.sqlite3")
    session = nucleus.begin_session()
    port = _Port()
    host = GovernedCapabilityHostV1(
        nucleus=nucleus, registry={"documents": (port, frozenset({"read"}))},
    )
    return nucleus, session, port, host, vaults


def test_unknown_capability_and_operation_default_deny(tmp_path: Path) -> None:
    _, session, port, host, _ = _host(tmp_path)
    with pytest.raises(GovernanceV1Denied, match="unknown"):
        host.bind(session, "network", "read", {})
    with pytest.raises(GovernanceV1Denied, match="unknown"):
        host.bind(session, "documents", "delete", {})
    assert port.calls == 0


@pytest.mark.parametrize("field,value", [
    ("session_generation", 999),
    ("workspace_id", "foreign-workspace"),
    ("principal_id", "foreign-principal"),
])
def test_stale_or_cross_scope_binding_is_denied(
    tmp_path: Path, field: str, value: object,
) -> None:
    _, session, port, host, _ = _host(tmp_path)
    binding = replace(host.bind(session, "documents", "read", {}), **{field: value})
    with pytest.raises(GovernanceV1Denied):
        host.dispatch(binding, {})
    assert port.calls == 0


def test_argument_and_policy_binding_are_exact(tmp_path: Path) -> None:
    _, session, port, host, _ = _host(tmp_path)
    binding = host.bind(session, "documents", "read", {"value": 1})
    with pytest.raises(GovernanceV1Denied, match="digest mismatch"):
        host.dispatch(binding, {"value": 2})
    binding = host.bind(session, "documents", "read", {"value": 1})
    with pytest.raises(GovernanceV1Denied, match="host-issued one-use"):
        host.dispatch(replace(binding, policy_binding_digest="0" * 64), {"value": 1})
    assert port.calls == 0


def test_audit_failure_prevents_dispatch(tmp_path: Path) -> None:
    _, session, port, host, _ = _host(tmp_path)
    binding = host.bind(session, "documents", "read", {})
    with patch("core.permission_broker.audit_healthy", return_value=False):
        with pytest.raises(GovernanceV1Denied, match="audit"):
            host.dispatch(binding, {})
    assert port.calls == 0


def test_kill_before_dispatch_is_monotonic_and_idempotent(tmp_path: Path) -> None:
    _, session, port, host, _ = _host(tmp_path)
    binding = host.bind(session, "documents", "read", {})
    first = host.kill()
    second = host.kill()
    assert first is second
    assert port.kills == 1
    with pytest.raises(GovernanceV1Denied, match="kill"):
        host.dispatch(binding, {})


def test_kill_during_dispatch_returns_uncertain_receipt(tmp_path: Path) -> None:
    _, session, port, host, _ = _host(tmp_path)
    port.block = True
    binding = host.bind(session, "documents", "read", {"value": 7})
    receipts = []
    thread = threading.Thread(target=lambda: receipts.append(host.dispatch(binding, {"value": 7})))
    thread.start()
    assert port.entered.wait(2)
    kill_receipt = host.kill()
    thread.join(5)
    assert kill_receipt.status == "kill-latched"
    assert receipts[0].outcome == "uncertain"
    assert receipts[0].uncertainty is True


def test_restart_preserves_killed_state(tmp_path: Path) -> None:
    path = tmp_path / "governance.sqlite3"
    nucleus, session, port, host, vaults = _host(tmp_path)
    host.kill()
    nucleus.close()
    restarted, _ = _nucleus(path, vaults)
    restarted_host = GovernedCapabilityHostV1(
        nucleus=restarted,
        registry={"documents": (_Port(), frozenset({"read"}))},
    )
    assert restarted_host.killed is True
    with pytest.raises(GovernanceV1Denied):
        restarted_host.dispatch(host.bind(session, "documents", "read", {}), {})


def test_local_shutdown_stops_ports_without_poisoning_restart(tmp_path: Path) -> None:
    path = tmp_path / "governance.sqlite3"
    nucleus, session, port, host, vaults = _host(tmp_path)
    binding = host.bind(session, "documents", "read", {})

    first = host.shutdown()
    second = host.shutdown()

    assert first is second
    assert first.status == "shutdown-local"
    assert first.nucleus["durable_global_kill"] is False
    assert nucleus.killed is False
    assert port.kills == 1
    with pytest.raises(GovernanceV1Denied, match="kill"):
        host.dispatch(binding, {})
    nucleus.close()

    restarted, _ = _nucleus(path, vaults)
    assert restarted.killed is False
    assert restarted.begin_session().generation == session.generation + 1


def test_explicit_release_is_audited_and_requires_exact_confirmation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "governance.sqlite3"
    nucleus, _session, _port, host, vaults = _host(tmp_path)
    host.kill()
    nucleus.close()
    killed, _ = _nucleus(path, vaults)

    with pytest.raises(GovernanceV1Denied, match="explicit"):
        killed.release_global_kill(confirmation="yes")
    assert killed.killed is True
    released = killed.release_global_kill(
        confirmation="RELEASE ONYX GLOBAL KILL"
    )
    assert released["status"] == "released"
    assert released["restart_required"] is True
    killed.close()

    restarted, _ = _nucleus(path, vaults)
    assert restarted.killed is False
    restarted.begin_session()


def test_revoke_is_binding_specific(tmp_path: Path) -> None:
    _, session, port, host, _ = _host(tmp_path)
    revoked = host.bind(session, "documents", "read", {"value": 1})
    allowed = host.bind(session, "documents", "read", {"value": 2})
    host.revoke(revoked.binding_id)
    with pytest.raises(GovernanceV1Denied, match="revoked"):
        host.dispatch(revoked, {"value": 1})
    assert host.dispatch(allowed, {"value": 2}).outcome == "completed"
    assert port.revocations == [revoked.binding_id]


def test_incomplete_participant_is_reported_and_unrelated_process_untouched(tmp_path: Path) -> None:
    nucleus, _, _, _, _ = _host(tmp_path)
    port = _Port()
    port.kill_result = False
    unrelated = _Port()
    host = GovernedCapabilityHostV1(
        nucleus=nucleus, registry={"documents": (port, frozenset({"read"}))},
    )
    receipt = host.kill()
    assert receipt.participants == (("documents", "incomplete:returned-false"),)
    assert receipt.uncertainty is True
    assert unrelated.kills == 0


def test_direct_concrete_port_call_denies_before_adapter() -> None:
    port = _Port()
    with pytest.raises(GovernanceV1Denied, match="not host-bound"):
        port.dispatch("read", {"value": "raw-secret"})
    assert port.calls == 0


def test_fabricated_and_replayed_binding_deny_before_adapter(tmp_path: Path) -> None:
    nucleus, session, port, host, _ = _host(tmp_path)
    binding = host.bind(session, "documents", "read", {"value": 1})
    forged = replace(binding, binding_id="binding-forged")
    with pytest.raises(GovernanceV1Denied, match="host-issued one-use"):
        host.dispatch(forged, {"value": 1})
    assert port.calls == 0
    receipt = host.dispatch(binding, {"value": 1})
    assert receipt.outcome == "completed"
    with pytest.raises(GovernanceV1Denied, match="host-issued one-use"):
        host.dispatch(binding, {"value": 1})
    assert port.calls == 1


def test_result_receipt_is_closed_content_free_envelope(tmp_path: Path) -> None:
    _, session, _, host, _ = _host(tmp_path)
    raw = "caption@example.test account-secret plugin-manifest payload"
    receipt = host.dispatch(
        host.bind(session, "documents", "read", {"value": raw}),
        {"value": raw},
    )
    rendered = repr(receipt)
    assert raw not in rendered
    assert receipt.result is not None
    assert set(receipt.result) == {
        "schema", "status", "result_digest", "result_type", "item_count", "redacted"
    }


def test_social_dataclass_result_digest_uses_only_bounded_shape_metadata(
    tmp_path: Path,
) -> None:
    class State(Enum):
        READY = "enum-raw-secret"

    @dataclass
    class NestedResult:
        caption: str
        token: bytes

    @dataclass
    class SocialResult:
        state: State
        nested: NestedResult
        records: list[object]

    class SocialPort(_Port):
        suffix = "raw-secret"

        def _dispatch_authorized(
            self, operation: str, arguments: dict[str, object]
        ) -> object:
            return SocialResult(
                State.READY,
                NestedResult(f"caption-{self.suffix}", f"bytes-{self.suffix}".encode()),
                [{"access_token": f"nested-{self.suffix}"}],
            )

    nucleus, _ = _nucleus(tmp_path / "social.sqlite3")
    session = nucleus.begin_session()
    port = SocialPort()
    host = GovernedCapabilityHostV1(
        nucleus=nucleus, registry={"social": (port, frozenset({"preview"}))},
    )
    receipt = host.dispatch(host.bind(session, "social", "preview", {}), {})
    port.suffix = "new-secret"
    second = host.dispatch(host.bind(session, "social", "preview", {}), {})
    rendered = repr(receipt)
    for secret in (
        "enum-raw-secret", "caption-raw-secret", "bytes-raw-secret",
        "nested-raw-secret", "access_token",
    ):
        assert secret not in rendered
    assert receipt.result is not None
    assert receipt.result["result_type"] == "SocialResult"
    assert receipt.result["item_count"] == 3
    assert len(str(receipt.result["result_digest"])) == 64
    assert second.result is not None
    assert second.result["result_digest"] == receipt.result["result_digest"]


def test_kill_anchors_nucleus_before_bounded_participant_propagation(tmp_path: Path) -> None:
    nucleus, _, _, _, _ = _host(tmp_path)

    class ObservingPort(_Port):
        def kill(self) -> object:
            assert nucleus.killed is True
            return super().kill()

    host = GovernedCapabilityHostV1(
        nucleus=nucleus,
        registry={"documents": (ObservingPort(), frozenset({"read"}))},
    )
    assert host.kill().uncertainty is False


def test_participant_registry_is_bounded(tmp_path: Path) -> None:
    nucleus = _nucleus(tmp_path / "bounded.sqlite3")[0]
    registry = {
        f"capability-{index}": (_Port(), frozenset({"read"}))
        for index in range(33)
    }
    with pytest.raises(Exception, match="closed capability registry"):
        GovernedCapabilityHostV1(nucleus=nucleus, registry=registry)
