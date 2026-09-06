from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from core.capability_composition_v1 import create_capability_composition_v1
from core.capability_ports.budget_v1 import BudgetCapabilityPortV1
from core.governance_nucleus_v1 import GovernanceIdentityV1, GovernanceNucleusV1, GovernanceV1Denied


class _Vault:
    value: bytes | None = None

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, value: bytes | bytearray) -> None:
        self.value = bytes(value)

    def delete(self) -> bool:
        self.value = None
        return True


class _Store:
    def __init__(self) -> None:
        self.value: bytes | None = None
        self.saves = 0
        self.fail = False

    def load_bytes(self) -> bytes | None:
        return self.value

    def save_bytes(self, value: bytes) -> None:
        if self.fail:
            raise OSError("injected atomic-store failure")
        self.value = bytes(value)
        self.saves += 1


def _nucleus(path: Path) -> GovernanceNucleusV1:
    return GovernanceNucleusV1(path=path, identity=GovernanceIdentityV1("owner", "workspace", "account", "profile"),
                               key_vault=_Vault(), head_vault=_Vault(), pending_vault=_Vault(), require_windows_boundary=False)


def _composition(tmp_path: Path, quota: int = 100, store: _Store | None = None):
    nucleus = _nucleus(tmp_path / f"governance-{id(store)}.sqlite3")
    composition = create_capability_composition_v1(nucleus=nucleus, port_factories={"budget": lambda: BudgetCapabilityPortV1(
        principal_id="owner", workspace_id="workspace", quota_micro=quota, store=store)})
    return nucleus, composition


def _args(key: str, **extra: object) -> dict[str, object]:
    return {"principal_id": "owner", "workspace_id": "workspace", "idempotency_key": key, **extra}


def test_startup_does_not_mutate_injected_store_and_retry_is_idempotent(tmp_path: Path) -> None:
    store = _Store()
    nucleus, composition = _composition(tmp_path, store=store)
    assert store.saves == 0 and store.value is None
    args = _args("reserve-1", amount_micro=40)
    first = composition.dispatch(nucleus.begin_session(), "budget", "reserve", args)
    second = composition.dispatch(nucleus.begin_session(), "budget", "reserve", args)
    assert first.outcome == second.outcome == "completed"
    status = composition.dispatch(nucleus.begin_session(), "budget", "status", _args("status-1"))
    assert status.outcome == "completed"


def test_hard_quota_is_atomic_under_concurrency(tmp_path: Path) -> None:
    nucleus, composition = _composition(tmp_path)
    session = nucleus.begin_session()
    def reserve(index: int):
        return composition.dispatch(session, "budget", "reserve", _args(f"r-{index}", amount_micro=70))
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(reserve, range(2)))
    assert sorted(receipt.outcome for receipt in receipts) == ["completed", "failed"]


def test_store_failure_rolls_back_reservation_atomically(tmp_path: Path) -> None:
    store = _Store()
    store.fail = True
    nucleus, composition = _composition(tmp_path, store=store)
    failed = composition.dispatch(
        nucleus.begin_session(), "budget", "reserve", _args("failed", amount_micro=90)
    )
    assert failed.outcome == "failed"
    store.fail = False
    retry = composition.dispatch(
        nucleus.begin_session(), "budget", "reserve", _args("retry", amount_micro=90)
    )
    assert retry.outcome == "completed"


def test_uncertain_result_remains_spent_across_restart_and_cannot_release(tmp_path: Path) -> None:
    store = _Store()
    nucleus, composition = _composition(tmp_path, store=store)
    session = nucleus.begin_session()
    reserved = composition.dispatch(session, "budget", "reserve", _args("reserve", amount_micro=80))
    assert reserved.outcome == "completed"
    port_result = reserved.result
    assert port_result is not None  # Host redacts content, reservation id is intentionally not exposed.
    reservation_id = next(iter(composition.host._registry["budget"].port._port._reservations))
    committed = composition.dispatch(session, "budget", "commit", _args("commit", reservation_id=reservation_id, uncertain=True))
    assert committed.outcome == "completed"
    released = composition.dispatch(session, "budget", "release", _args("release", reservation_id=reservation_id))
    assert released.outcome == "failed"
    _, restarted = _composition(tmp_path / "restart", store=store)
    exhausted = restarted.dispatch(restarted.host._nucleus.begin_session(), "budget", "reserve", _args("new", amount_micro=30))
    assert exhausted.outcome == "failed"


def test_budget_is_policy_not_permission_and_kill_revokes_future_work(tmp_path: Path) -> None:
    nucleus, composition = _composition(tmp_path)
    session = nucleus.begin_session()
    receipt = composition.dispatch(session, "budget", "reserve", _args("r", amount_micro=10))
    assert receipt.outcome == "completed"
    assert "permission_granted" not in str(receipt.result)
    assert not hasattr(composition, "spend")
    composition.kill()
    with pytest.raises(GovernanceV1Denied):
        composition.plan(session, "budget", "status", _args("after-kill"))
