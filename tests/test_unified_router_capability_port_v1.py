from pathlib import Path

from core.capability_ports.unified_router_v1 import UnifiedRouterV1
from core.governance_nucleus_v1 import GovernanceIdentityV1, GovernanceNucleusV1
from core.governed_capability_host_v1 import (
    GovernedCapabilityHostV1,
    HostBoundCapabilityPortV1,
)


class _Vault:
    value: bytes | None = None

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, value: bytes | bytearray) -> None:
        self.value = bytes(value)

    def delete(self) -> bool:
        self.value = None
        return True


class _Port(HostBoundCapabilityPortV1):
    calls = 0

    def __init__(self) -> None:
        super().__init__()

    def _dispatch_authorized(self, operation: str, arguments: dict[str, object]) -> object:
        self.calls += 1
        return arguments

    def revoke(self, binding_id: str) -> None:
        return None

    def kill(self) -> bool:
        return True


def test_router_only_plans_and_attests_never_dispatches(tmp_path: Path) -> None:
    nucleus = GovernanceNucleusV1(
        path=tmp_path / "governance.sqlite3",
        identity=GovernanceIdentityV1("onyx-owner", "onyx-local-workspace", "cyryx-local-account", "onyx-owner-profile"),
        key_vault=_Vault(), head_vault=_Vault(), pending_vault=_Vault(),
    )
    port = _Port()
    host = GovernedCapabilityHostV1(nucleus=nucleus, registry={"argos": (port, frozenset({"read.status"}))})
    router = UnifiedRouterV1(host)
    plan = router.plan(nucleus.begin_session(), "argos", "read.status", {})
    assert router.attest(plan) is True
    assert not hasattr(router, "dispatch")
    assert port.calls == 0
