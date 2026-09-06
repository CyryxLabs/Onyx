from pathlib import Path
from types import SimpleNamespace

import pytest

from core import control_plane as control_plane_module
from core import onyx_live_activation_v17 as v17
from core import paths as paths_module


class _ExpectedInstantiationFailure(RuntimeError):
    pass


class _FakeVault:
    def delete(self) -> None:
        pass


def test_founder_smoke_isolates_and_restores_both_control_plane_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = tmp_path / "data"
    workspace = data / "workspace"
    corpus = data / "corpus"
    output = data / "founder-smoke-v1.json"
    expected_runtime = data / "runtime" / "control-plane-smoke-v1"
    workspace.mkdir(parents=True)
    corpus.mkdir()

    def persistent_runtime_refused() -> Path:
        raise AssertionError("persistent Control Plane binding was invoked")

    monkeypatch.setattr(
        paths_module,
        "private_control_plane_runtime_dir",
        persistent_runtime_refused,
    )
    monkeypatch.setattr(
        control_plane_module,
        "private_control_plane_runtime_dir",
        persistent_runtime_refused,
    )

    flags = SimpleNamespace(
        base=SimpleNamespace(base=SimpleNamespace(workspace_roots=(workspace,)))
    )
    identity = SimpleNamespace(
        principal_id="principal-test",
        workspace_id="workspace-0123456789abcdef01234567",
        account_id="account-test",
        profile_id="profile-test",
        workspace_display="Test workspace",
    )
    monkeypatch.setattr(
        v17.ActivationFlagsV17,
        "from_canonical_environ",
        classmethod(lambda _cls, _source: flags),
    )
    monkeypatch.setattr(
        v17.v16,
        "governance_workspace_bindings_v1",
        lambda _roots: (identity, ()),
    )
    monkeypatch.setattr(
        v17.v16,
        "_governance_smoke_native_vaults_v1",
        lambda _data: (_FakeVault(), _FakeVault(), _FakeVault()),
    )
    monkeypatch.setattr(v17, "NativeSecretVault", lambda _reference: _FakeVault())
    monkeypatch.setattr(v17, "preflight_host", lambda _module, _source: object())

    observed: dict[str, object] = {}

    class FakeController:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self._base = SimpleNamespace(
                _base=SimpleNamespace(external_agent_capability=None),
                rollback_all=lambda: observed.__setitem__("rollback_all", True),
            )

        def install(self) -> None:
            observed["installed"] = True

        def instantiate_live(self, _ui: object) -> object:
            observed["paths_runtime"] = paths_module.private_control_plane_runtime_dir()
            observed["control_plane_runtime"] = (
                control_plane_module.private_control_plane_runtime_dir()
            )
            raise _ExpectedInstantiationFailure

        def rollback_to_v16(self) -> None:
            observed["rollback_v16"] = True

    monkeypatch.setattr(v17, "OnyxLiveActivationV17", FakeController)
    module = SimpleNamespace(
        memory_dir=lambda: Path("original-memory"),
        runtime_dir=lambda: Path("original-runtime"),
    )
    isolation = object.__new__(v17._FounderSmokeIsolationV17)

    with pytest.raises(_ExpectedInstantiationFailure):
        v17._run_founder_smoke_windows_v17(
            module,  # type: ignore[arg-type]
            data=data,
            workspace=workspace,
            corpus=corpus,
            output=output,
            isolation=isolation,
        )

    assert observed == {
        "installed": True,
        "paths_runtime": expected_runtime,
        "control_plane_runtime": expected_runtime,
        "rollback_v16": True,
        "rollback_all": True,
    }
    assert paths_module.private_control_plane_runtime_dir is persistent_runtime_refused
    assert (
        control_plane_module.private_control_plane_runtime_dir
        is persistent_runtime_refused
    )
