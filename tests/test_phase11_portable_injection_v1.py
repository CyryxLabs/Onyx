from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import pytest

from core.missions import MissionStore
from core.phase11_live_mission_v1 import (
    Phase11LiveMissionError,
    Phase11LiveMissionV1,
    _KillState,
)


class _MemoryVault:
    def __init__(self) -> None:
        self.value: bytes | None = None

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, secret: bytes | bytearray) -> None:
        self.value = bytes(secret)


class _VaultFactory:
    def __init__(self) -> None:
        self.vaults: dict[str, _MemoryVault] = {}

    def __call__(self, reference: object) -> _MemoryVault:
        account = str(getattr(reference, "account"))
        return self.vaults.setdefault(account, _MemoryVault())


class _Boundary:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _KillSignal:
    def __init__(self) -> None:
        self._closed = False
        self.signaled = False

    def is_set(self) -> bool:
        return self.signaled

    def set(self) -> None:
        self.signaled = True

    def close(self) -> None:
        self._closed = True


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


def test_default_off_does_not_touch_injected_host_factories(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    def forbidden(**_kwargs: object) -> object:
        raise AssertionError("factory touched while Phase 11 is disabled")

    bridge = Phase11LiveMissionV1(
        MissionStore(tmp_path / "missions.sqlite3"),
        binding_dir=tmp_path / "must-not-exist" / "bindings",
        allowed_roots=(root,),
        enabled=False,
        trusted_directory_factory=forbidden,
        kill_signal_factory=forbidden,
    )

    assert bridge.enabled is False
    assert (tmp_path / "must-not-exist").exists() is False


def test_explicit_host_boundary_factory_is_owned_and_closed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    binding_dir = tmp_path / "bindings"
    calls: list[tuple[Path, bool]] = []
    boundary: _Boundary | None = None

    def boundary_factory(*, root: Path, enabled: bool) -> _Boundary:
        nonlocal boundary
        root.mkdir(parents=True, mode=0o700)
        calls.append((root, enabled))
        boundary = _Boundary(root)
        return boundary

    bridge = Phase11LiveMissionV1(
        MissionStore(tmp_path / "missions.sqlite3"),
        binding_dir=binding_dir,
        allowed_roots=(root,),
        enabled=True,
        key=b"p" * 32,
        anchor_vault_factory=_VaultFactory(),
        trusted_directory_factory=boundary_factory,
    )

    assert calls == [(binding_dir, True)]
    assert bridge._host_binding_boundary is boundary
    bridge.close()
    assert boundary is not None and boundary.closed is True
    assert bridge._host_binding_boundary is None


def test_kill_signal_factory_receives_bound_opaque_identity() -> None:
    candidate = object.__new__(Phase11LiveMissionV1)
    candidate._lock = threading.RLock()
    candidate._kill_states = {}
    candidate._closed = False
    candidate._key = b"p" * 32
    candidate._kill_event_namespace = hashlib.sha256(b"test-boundary").digest()
    candidate._host_binding_boundary = object()
    observed: dict[str, object] = {}
    signal = _KillSignal()

    def factory(**kwargs: object) -> _KillSignal:
        observed.update(kwargs)
        return signal

    candidate._kill_signal_factory = factory
    mission_id = "mis_" + "1" * 32
    binding_digest = "a" * 64
    state = candidate._kill_state(mission_id, binding_digest)

    assert state.kernel is signal
    assert observed["directory"] is candidate._host_binding_boundary
    assert observed["binding_digest"] == binding_digest
    assert observed["name"] == candidate._portable_kill_signal_name(
        mission_id, binding_digest
    )
    assert str(observed["name"]).startswith("phase11-")
    assert "\\" not in str(observed["name"])


def test_kill_signal_factory_failure_is_fail_closed() -> None:
    candidate = object.__new__(Phase11LiveMissionV1)
    candidate._lock = threading.RLock()
    candidate._kill_states = {}
    candidate._closed = False
    candidate._key = b"p" * 32
    candidate._kill_event_namespace = hashlib.sha256(b"test-boundary").digest()
    candidate._host_binding_boundary = object()

    def factory(**_kwargs: object) -> object:
        raise RuntimeError("injected failure")

    candidate._kill_signal_factory = factory
    with pytest.raises(Phase11LiveMissionError, match="factory failed"):
        candidate._kill_state("mis_" + "1" * 32, "a" * 64)


def test_kill_signal_factory_rejects_incomplete_boundary() -> None:
    candidate = object.__new__(Phase11LiveMissionV1)
    candidate._lock = threading.RLock()
    candidate._kill_states = {}
    candidate._closed = False
    candidate._key = b"p" * 32
    candidate._kill_event_namespace = hashlib.sha256(b"test-boundary").digest()
    candidate._host_binding_boundary = object()
    candidate._kill_signal_factory = lambda **_kwargs: object()

    with pytest.raises(Phase11LiveMissionError, match="boundary is invalid"):
        candidate._kill_state("mis_" + "1" * 32, "a" * 64)


def test_protocol_only_kill_signal_releases_host_boundary_on_close() -> None:
    events: list[str] = []

    class ProtocolOnlySignal:
        def is_set(self) -> bool:
            return False

        def set(self) -> None:
            return None

        def close(self) -> None:
            events.append("signal.close")

    class Boundary:
        def close(self) -> None:
            events.append("boundary.close")

    candidate = object.__new__(Phase11LiveMissionV1)
    candidate._lock = threading.RLock()
    candidate._closed = False
    candidate._closing = False
    state = _KillState(kernel=ProtocolOnlySignal())
    candidate._kill_states = {"mis_test": state}
    candidate.away_mode = None
    candidate.external_agent = None
    candidate.autopilot = None
    candidate._host_binding_boundary = Boundary()
    candidate._windows_binding_boundary = None

    candidate.close(0.1)

    assert events == ["signal.close", "boundary.close"]
    assert state.kernel_closed is True
    assert candidate._host_binding_boundary is None
