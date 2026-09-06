from __future__ import annotations

import inspect
import os
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from core import onyx_live_activation_v17 as v17
from core import onyx_live_activation_v18 as v18
from core import onyx_live_activation_v19 as v19
from core import portable_host_capability_v1 as authority
from core.governance_nucleus_v1 import _GovernanceLedgerV1
from core.host_security_boundary_v1 import HostSecurityBoundaryError
from core.portable_host_capability_v1 import (
    PortableHostBindingsV1,
    PortableHostCapabilityV1,
    PortableHostCapabilityV1Error,
    require_portable_host_bindings_v1,
)
from core.posix_single_instance_v1 import PosixSingleInstanceV1
from core.posix_trusted_directory_v1 import (
    PosixFileLockLeaseV1,
    PosixTrustedDirectoryV1,
)


def _fake_bindings() -> PortableHostBindingsV1:
    capability = PortableHostCapabilityV1(object(), "Linux", 1000, 1)
    return PortableHostBindingsV1(
        object(),
        capability,
        "unix:///run/onyx-docker.sock",
        lambda _raw: object(),  # type: ignore[arg-type]
        PosixTrustedDirectoryV1,
        object,  # type: ignore[arg-type]
        lambda *_args, **_kwargs: object(),
        True,
    )


def test_official_issuer_accepts_no_factory_or_feature_escalation() -> None:
    signature = inspect.signature(authority._mint_portable_host_bindings_v1)

    assert tuple(signature.parameters) == ("runtime_address",)
    assert all(
        name not in signature.parameters
        for name in (
            "factory",
            "runtime_endpoint_factory",
            "trusted_directory_factory",
            "governance_descriptor_io",
            "enable_governance",
        )
    )


def test_lookalike_capability_and_bindings_are_rejected() -> None:
    with pytest.raises(PortableHostCapabilityV1Error, match="bindings_invalid"):
        require_portable_host_bindings_v1(_fake_bindings())


def test_real_seal_clone_and_hostile_callable_equality_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EvilCallable:
        executed = False

        def __call__(self, _raw: str) -> object:
            self.executed = True
            return object()

        def __hash__(self) -> int:
            return 0

        def __eq__(self, _other: object) -> bool:
            return True

    monkeypatch.setattr(
        authority,
        "_native_posix_identity",
        lambda: ("Linux", 1000, 4321),
    )
    monkeypatch.setattr(
        authority,
        "require_posix_descriptor_sqlite_v1",
        lambda: None,
    )
    issued = authority._mint_portable_host_bindings_v1(
        "unix:///run/onyx-docker.sock"
    )
    capability_clone = PortableHostCapabilityV1(
        authority._CAPABILITY_SEAL,
        issued.capability.system,
        issued.capability.euid,
        issued.capability.process_id,
    )
    evil = EvilCallable()
    bindings_clone = PortableHostBindingsV1(
        authority._BINDINGS_SEAL,
        capability_clone,
        issued.runtime_address,
        evil,  # type: ignore[arg-type]
        issued.trusted_directory_factory,
        issued.kill_signal_factory,
        issued.artifact_root_authorizer,
        issued.governance_descriptor_io,
    )

    assert issued != bindings_clone
    with pytest.raises(PortableHostCapabilityV1Error, match="bindings_invalid"):
        require_portable_host_bindings_v1(bindings_clone)
    assert evil.executed is False


@pytest.mark.parametrize("activation", [v17, v18, v19])
def test_v17_v19_reject_fake_guard_and_factory_on_posix(
    activation: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(activation.os, "name", "posix")
    with pytest.raises(Exception, match="arbitrary portable"):
        activation.preflight_host(
            ModuleType("forged_portable_host"),
            {},
            platform_guard=lambda _stage: True,
            runtime_endpoint_factory=lambda _raw: object(),
        )


def test_registered_binding_is_process_bound_and_governance_is_descriptor_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        authority,
        "_native_posix_identity",
        lambda: ("Linux", 1000, 4321),
    )
    monkeypatch.setattr(
        authority,
        "require_posix_descriptor_sqlite_v1",
        lambda: None,
    )
    bindings = authority._mint_portable_host_bindings_v1(
        "unix:///run/onyx-docker.sock"
    )
    assert require_portable_host_bindings_v1(bindings) is bindings
    assert bindings.governance_descriptor_io is True
    monkeypatch.setattr(
        authority,
        "_native_posix_identity",
        lambda: ("Linux", 1000, 4322),
    )
    with pytest.raises(PortableHostCapabilityV1Error, match="capability_drift"):
        require_portable_host_bindings_v1(bindings)


def test_v17_retains_exact_binding_identity_for_future_founder_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding = SimpleNamespace(
        governance_descriptor_io=True,
        trusted_directory_factory=PosixTrustedDirectoryV1,
    )
    flags = object.__new__(v17.ActivationFlagsV17)
    contract = object.__new__(v17.HostContractV17)
    object.__setattr__(flags, "base", object())
    object.__setattr__(contract, "base", object())
    monkeypatch.setattr(v17.os, "name", "posix")
    monkeypatch.setattr(
        v17,
        "require_portable_host_bindings_v1",
        lambda value, *, stage: value if value is binding else None,
    )
    monkeypatch.setattr(
        v17.v16.OnyxLiveActivationV16,
        "__init__",
        lambda self, *_args, **_kwargs: None,
    )

    controller = v17.OnyxLiveActivationV17(
        flags,
        contract,
        portable_bindings=binding,  # type: ignore[arg-type]
    )

    assert controller._portable_bindings is binding
    assert controller._trusted_directory_factory is PosixTrustedDirectoryV1


def test_lock_lease_relinquishes_fd_before_unlock_or_close_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lease = PosixFileLockLeaseV1(
        41,
        parent_descriptor=42,
        leaf="onyx.lock",
        parent_identity=(1, 1),
        file_identity=(1, 2),
    )
    closes: list[int] = []

    def fail_unlock(_fd: int, _operation: int) -> None:
        raise OSError("unlock failed")

    def close_after_release(fd: int) -> None:
        closes.append(fd)
        raise OSError("close reported after release")

    monkeypatch.setattr(lease, "_validate", lambda: None)
    monkeypatch.setattr(
        "core.posix_trusted_directory_v1.fcntl",
        type("F", (), {"LOCK_UN": 8, "flock": fail_unlock}),
    )
    monkeypatch.setattr("core.posix_trusted_directory_v1.os.close", close_after_release)
    with pytest.raises(HostSecurityBoundaryError, match="release_failed"):
        lease.close()
    assert lease._descriptor == -1
    assert lease._parent_descriptor == -1
    assert lease._closed is True
    lease.close()
    assert closes == [41, 42]


def test_single_instance_relinquishes_lease_before_close_error() -> None:
    class Lease:
        calls = 0

        def close(self) -> None:
            self.calls += 1
            raise OSError("released")

    class Directory:
        lease = Lease()

        def acquire_lock(self, _relative: str) -> Lease:
            return self.lease

    instance = PosixSingleInstanceV1(directory=Directory())
    assert instance.acquire() is True
    with pytest.raises(OSError, match="released"):
        instance.close()
    assert instance.acquired is False
    instance.close()
    assert Directory.lease.calls == 1


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX dirfd")
def test_posix_boundary_rejects_mode_uid_and_inode_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "trusted"
    boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
    try:
        root.chmod(0o755)
        with pytest.raises(HostSecurityBoundaryError, match="permissions_invalid"):
            with boundary.session():
                pass
        root.chmod(0o700)
        real_uid = os.geteuid()
        monkeypatch.setattr(os, "geteuid", lambda: real_uid + 1)
        with pytest.raises(HostSecurityBoundaryError, match="permissions_invalid"):
            with boundary.session():
                pass
    finally:
        monkeypatch.undo()
        root.chmod(0o700)
        boundary.close()


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX dirfd")
def test_governance_posix_boundary_prepares_descriptor_bound_sqlite(
    tmp_path: Path,
) -> None:
    ledger = object.__new__(_GovernanceLedgerV1)
    ledger.path = tmp_path / "governance" / "governance.sqlite3"
    ledger._trusted_directory_factory = PosixTrustedDirectoryV1
    ledger._require_host_boundary = True
    ledger._trusted_directory = None
    ledger._descriptor_path = None
    ledger._prepare_root()
    assert type(ledger._trusted_directory) is PosixTrustedDirectoryV1
    assert ledger._descriptor_path is not None
    ledger._descriptor_path.close()
    ledger._trusted_directory.close()


def test_windows_default_path_rejects_portable_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(v19.os, "name", "nt")
    with pytest.raises(v19.ActivationV19PlatformDenied, match="invalid on Windows"):
        v19._require_current_host_boundary_v19(
            _fake_bindings(),
            stage="dayops_preflight",
        )
