from __future__ import annotations

import os
import platform
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from core import onyx_live_activation_v16 as v16
from core import onyx_live_activation_v19 as v19
from core import portable_host_capability_v1 as portable_authority
from core import posix_trusted_directory_v1 as posix_directory
from core.governance_nucleus_v1 import (
    GovernanceV1IntegrityError,
    _GovernanceLedgerV1,
)
from core.host_security_boundary_v1 import HostSecurityBoundaryError
from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1


pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="requires native POSIX descriptor operations"
)


class _MemoryVault:
    def __init__(self) -> None:
        self.value: bytes | None = None

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, value: bytes) -> None:
        self.value = bytes(value)

    def delete(self) -> bool:
        self.value = None
        return True


def _ledger(root: Path, vaults: tuple[_MemoryVault, ...]) -> _GovernanceLedgerV1:
    return _GovernanceLedgerV1(
        root / "governance.sqlite3",
        key_vault=vaults[0],
        head_vault=vaults[1],
        pending_vault=vaults[2],
        trusted_directory_factory=PosixTrustedDirectoryV1,
        require_host_boundary=True,
    )


def test_linux_native_descriptor_ledger_roundtrip_reopen_and_cleanup(
    tmp_path: Path,
) -> None:
    if platform.system() != "Linux":
        pytest.skip("Linux-native positive proof")
    root = tmp_path / "governance"
    root.mkdir(mode=0o700)
    vaults = (_MemoryVault(), _MemoryVault(), _MemoryVault())

    ledger = _ledger(root, vaults).initialize()
    lease = ledger._descriptor_path
    event = ledger.append("probe", "entity", "workspace", {"ok": True})
    assert event.sequence == 1
    assert (root / "governance.sqlite3").stat().st_mode & 0o777 == 0o600
    ledger.close()
    assert lease._closed is True

    reopened = _ledger(root, vaults).initialize()
    assert reopened.has_durable_event("probe", "entity") is True
    reopened.close()


def test_descriptor_ledger_rejects_symlink_leaf_before_sqlite(
    tmp_path: Path,
) -> None:
    root = tmp_path / "governance"
    root.mkdir(mode=0o700)
    target = tmp_path / "outside.sqlite3"
    target.write_bytes(b"")
    target.chmod(0o600)
    (root / "governance.sqlite3").symlink_to(target)
    vaults = (_MemoryVault(), _MemoryVault(), _MemoryVault())

    with pytest.raises(
        GovernanceV1IntegrityError,
        match="descriptor-bound|not a regular trusted file",
    ):
        _ledger(root, vaults).initialize()


def test_descriptor_ledger_detects_named_root_replacement(
    tmp_path: Path,
) -> None:
    root = tmp_path / "governance"
    root.mkdir(mode=0o700)
    vaults = (_MemoryVault(), _MemoryVault(), _MemoryVault())
    ledger = _ledger(root, vaults).initialize()
    displaced = tmp_path / "governance-displaced"
    root.rename(displaced)
    root.mkdir(mode=0o700)
    try:
        with pytest.raises(
            GovernanceV1IntegrityError,
            match="identity|storage signature",
        ):
            ledger.has_durable_event("probe", "entity")
    finally:
        ledger.close()


def test_darwin_emulation_has_typed_fd_vfs_validation_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if platform.system() == "Darwin":
        pytest.skip("emulation test runs on a non-Darwin POSIX host")
    root = tmp_path / "darwin-gate"
    root.mkdir(mode=0o700)
    boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
    real_stat = posix_directory.os.stat

    def deny_dev_fd(path: object, *args: object, **kwargs: object):
        if isinstance(path, str) and path.startswith("/dev/fd/"):
            raise FileNotFoundError(path)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(posix_directory.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(posix_directory.os, "stat", deny_dev_fd)
    try:
        with boundary.session() as session:
            with pytest.raises(
                HostSecurityBoundaryError,
                match="descriptor_path_unavailable",
            ):
                session.descriptor_path("governance.sqlite3")
    finally:
        boundary.close()


def test_v16_threads_one_sealed_binding_into_governance_and_phase11(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if platform.system() != "Linux":
        pytest.skip("Linux-native positive proof")
    bindings = portable_authority._mint_portable_host_bindings_v1(
        "unix:///run/onyx-docker.sock"
    )
    flags = object.__new__(v16.ActivationFlagsV16)
    contract = object.__new__(v16.HostContractV16)
    object.__setattr__(flags, "base", object())
    object.__setattr__(contract, "base", object())
    captured: dict[str, object] = {}

    def capture_base(_self: object, *_args: object, **kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(v16.v15.OnyxLiveActivationV15, "__init__", capture_base)
    controller = v16.OnyxLiveActivationV16(
        flags,
        contract,
        portable_bindings=bindings,
    )

    assert controller._portable_bindings is bindings
    assert captured["phase11_trusted_directory_factory"] is PosixTrustedDirectoryV1
    assert captured["phase11_kill_signal_factory"] is bindings.kill_signal_factory


def test_v19_preflight_preserves_binding_identity_to_v18(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if platform.system() != "Linux":
        pytest.skip("Linux-native positive proof")
    bindings = portable_authority._mint_portable_host_bindings_v1(
        "unix:///run/onyx-docker.sock"
    )
    module = ModuleType("portable_v19_native_host")
    module.OnyxLive = type("OnyxLive", (), {})
    base = SimpleNamespace(project=tmp_path)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        v19.ActivationFlagsV19,
        "from_canonical_environ",
        classmethod(lambda cls, *_args, **_kwargs: object()),
    )

    def base_preflight(*_args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return base

    monkeypatch.setattr(v19.v18, "preflight_host", base_preflight)
    monkeypatch.setattr(v19, "verify_current_hud_acceptance", lambda _root: None)

    contract = v19.preflight_host(module, {}, portable_bindings=bindings)
    assert contract.base is base
    assert captured["portable_bindings"] is bindings
    assert captured["runtime_endpoint_factory"] is bindings.runtime_endpoint_factory
