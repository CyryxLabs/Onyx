from pathlib import Path
from types import SimpleNamespace

import pytest

from core import control_plane as control_plane_module
from core import onyx_live_activation_v18 as v18
from core import paths as paths_module


class _ExpectedInstantiationFailure(RuntimeError):
    pass


def test_document_intake_smoke_isolates_and_restores_control_plane_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = tmp_path / "data"
    workspace = data / "workspace"
    corpus = data / "corpus"
    output = data / "document-intake-smoke-v1.json"
    expected_runtime = data / "runtime" / "control-plane-smoke-v1"
    workspace.mkdir(parents=True)
    corpus.mkdir()

    monkeypatch.setenv(v18.DOCUMENT_INTAKE_SMOKE_CORPUS_ENV, str(corpus))
    monkeypatch.setenv(v18.DOCUMENT_INTAKE_SMOKE_OUTPUT_ENV, str(output))
    monkeypatch.setattr(v18, "data_root", lambda: data)

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
        base=SimpleNamespace(
            base=SimpleNamespace(base=SimpleNamespace(workspace_roots=(workspace,)))
        )
    )
    identity = SimpleNamespace(
        principal_id="principal-test",
        workspace_id="workspace-test",
        account_id="account-test",
        profile_id="profile-test",
        workspace_display="Test workspace",
    )
    monkeypatch.setattr(
        v18.ActivationFlagsV18,
        "from_canonical_environ",
        classmethod(lambda _cls, _source: flags),
    )
    monkeypatch.setattr(
        v18.v17.v16,
        "governance_workspace_bindings_v1",
        lambda _roots: (identity, ()),
    )
    monkeypatch.setattr(
        v18.v17.v16,
        "_governance_smoke_native_vaults_v1",
        lambda _data: (object(), object(), object()),
    )

    observed: dict[str, object] = {}

    class FakeIsolation:
        network_calls = 0
        provider_calls = 0
        process_calls = 0

        def __init__(self, _module: object) -> None:
            pass

        def install(self) -> None:
            observed["isolation_installed"] = True

        def close(self) -> None:
            observed["isolation_closed"] = True

    class FakeActivation:
        def instantiate_live(self, _ui: object) -> object:
            observed["paths_runtime"] = paths_module.private_control_plane_runtime_dir()
            observed["control_plane_runtime"] = (
                control_plane_module.private_control_plane_runtime_dir()
            )
            raise _ExpectedInstantiationFailure

        def rollback_to_v17(self) -> None:
            observed["rollback_v17"] = True

    monkeypatch.setattr(v18.v17, "_FounderSmokeIsolationV17", FakeIsolation)
    monkeypatch.setattr(
        v18, "activate_main", lambda *_args, **_kwargs: FakeActivation()
    )

    def original_memory_dir() -> Path:
        return Path("original-memory")

    def original_runtime_dir() -> Path:
        return Path("original-runtime")

    module = SimpleNamespace(
        memory_dir=original_memory_dir,
        runtime_dir=original_runtime_dir,
    )

    with pytest.raises(_ExpectedInstantiationFailure):
        v18.run_document_intake_smoke_v181(
            module,  # type: ignore[arg-type]
            dayops_factory=object(),
        )

    assert observed == {
        "isolation_installed": True,
        "paths_runtime": expected_runtime,
        "control_plane_runtime": expected_runtime,
        "rollback_v17": True,
        "isolation_closed": True,
    }
    assert module.memory_dir is original_memory_dir
    assert module.runtime_dir is original_runtime_dir
    assert paths_module.private_control_plane_runtime_dir is persistent_runtime_refused
    assert (
        control_plane_module.private_control_plane_runtime_dir
        is persistent_runtime_refused
    )
