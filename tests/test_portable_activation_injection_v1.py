from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from core import onyx_live_activation_v15 as v15
from core import onyx_live_activation_v17 as v17
from core import onyx_live_activation_v18 as v18
from core import portable_host_capability_v1 as portable_authority
from core.executable_runtime_endpoint_v1 import executable_runtime_endpoint_v1
from core.posix_artifact_root_authority_v1 import (
    authorize_posix_artifact_root_v1,
)
from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1


def test_v15_portable_endpoint_requires_explicit_typed_injection(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    docker_cli = str((tmp_path / "missing-docker.exe").resolve())
    address = "unix:///onyx-test-runtime/onyx-docker.sock"
    endpoint = executable_runtime_endpoint_v1(
        address,
        platform_name="Linux",
        require_existing=False,
    )
    environment = v15.exact_activation_environment(
        (workspace,),
        executable_docker_cli=docker_cli,
        executable_docker_host=address,
        executable_sandbox=False,
        runtime_endpoint=endpoint,
    )

    with pytest.raises(v15.ActivationV15Error, match="npipe"):
        v15.ActivationFlagsV15.from_canonical_environ(environment)

    flags = v15.ActivationFlagsV15.from_canonical_environ(
        environment,
        runtime_endpoint_factory=lambda raw: endpoint if raw == address else None,
    )
    assert flags.runtime_endpoint is endpoint
    assert flags.executable_docker_host == address


def test_v15_default_windows_endpoint_contract_is_unchanged(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    environment = v15.exact_activation_environment(
        (workspace,),
        executable_docker_cli=str((tmp_path / "missing-docker.exe").resolve()),
        executable_sandbox=False,
    )

    flags = v15.ActivationFlagsV15.from_canonical_environ(environment)

    assert flags.runtime_endpoint is None
    assert flags.executable_docker_host == v15.DEFAULT_WINDOWS_DOCKER_HOST


def test_v17_non_windows_preflight_rejects_arbitrary_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = ModuleType("portable_v17_host")
    module.OnyxLive = type("OnyxLive", (), {})
    base = SimpleNamespace(project=Path.cwd())
    stages: list[str] = []
    monkeypatch.setattr(v17.os, "name", "posix")
    monkeypatch.setattr(
        v17.ActivationFlagsV17,
        "from_canonical_environ",
        classmethod(lambda cls, _source=None: object()),
    )
    monkeypatch.setattr(
        v17.v16,
        "preflight_host",
        lambda _module, _source: base,
    )

    with pytest.raises(v17.ActivationV17PlatformDenied, match="arbitrary"):
        v17.preflight_host(
            module,
            {},
            platform_guard=lambda stage: stages.append(stage) or True,
        )
    assert stages == []


def test_v17_non_windows_guard_denial_is_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(v17.os, "name", "posix")
    monkeypatch.setattr(
        v17.ActivationFlagsV17,
        "from_canonical_environ",
        classmethod(lambda cls, _source=None: object()),
    )

    with pytest.raises(v17.ActivationV17PlatformDenied, match="arbitrary"):
        v17.preflight_host(
            ModuleType("portable_v17_denied"),
            {},
            platform_guard=lambda _stage: False,
        )


def test_v18_non_windows_preflight_rejects_arbitrary_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = ModuleType("portable_v18_host")
    module.OnyxLive = type("OnyxLive", (), {})
    base = SimpleNamespace(project=Path.cwd())
    stages: list[str] = []
    monkeypatch.setattr(v18.os, "name", "posix")
    monkeypatch.setattr(
        v18.ActivationFlagsV18,
        "from_canonical_environ",
        classmethod(lambda cls, _source=None: object()),
    )

    def base_preflight(
        _module: object,
        _source: object,
        *,
        platform_guard: object,
    ) -> object:
        assert callable(platform_guard)
        assert platform_guard("founder_preflight") is True
        return base

    monkeypatch.setattr(v18.v17, "preflight_host", base_preflight)

    def guard(stage: str) -> bool:
        stages.append(stage)
        return True

    with pytest.raises(v18.ActivationV18PlatformDenied, match="arbitrary"):
        v18.preflight_host(
            module,
            {},
            platform_guard=guard,
        )
    assert stages == []


def test_v18_portable_artifact_boundary_factories_are_paired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = ModuleType("portable_v18_controller")
    host = type("OnyxLive", (), {})
    module.OnyxLive = host
    flags = object.__new__(v18.ActivationFlagsV18)
    object.__setattr__(flags, "base", object())
    contract = v18.HostContractV18(module, host, tmp_path, object())  # type: ignore[arg-type]
    monkeypatch.setattr(
        v18.v17.OnyxLiveActivationV17,
        "__init__",
        lambda self, *_args, **_kwargs: setattr(self, "_installed", False),
    )
    monkeypatch.setattr(v18, "os", SimpleNamespace(name="nt"))

    with pytest.raises(v18.ActivationV18Error, match="must be paired"):
        v18.OnyxLiveActivationV18(
            flags,
            contract,
            trusted_directory_factory=lambda **_kwargs: object(),
        )

    def boundary_factory(**_kwargs: object) -> object:
        return object()

    def authorizer(*_args: object, **_kwargs: object) -> object:
        return object()

    controller = v18.OnyxLiveActivationV18(
        flags,
        contract,
        trusted_directory_factory=boundary_factory,
        artifact_root_authorizer=authorizer,
    )
    assert controller._trusted_directory_factory is boundary_factory
    assert controller._artifact_root_authorizer is authorizer


def test_v18_accepts_exact_posix_artifact_successor_as_sealed_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if portable_authority.os.name != "posix":
        pytest.skip("native POSIX authority is required")
    module = ModuleType("portable_v18_posix_authority")
    host = type("OnyxLive", (), {})
    module.OnyxLive = host
    flags = object.__new__(v18.ActivationFlagsV18)
    object.__setattr__(flags, "base", object())
    contract = v18.HostContractV18(module, host, tmp_path, object())  # type: ignore[arg-type]
    monkeypatch.setattr(
        v18.v17.OnyxLiveActivationV17,
        "__init__",
        lambda self, *_args, **_kwargs: setattr(self, "_installed", False),
    )

    bindings = portable_authority._mint_portable_host_bindings_v1(
        f"unix://{tmp_path / 'runtime.sock'}"
    )
    controller = v18.OnyxLiveActivationV18(
        flags,
        contract,
        portable_bindings=bindings,
    )

    assert controller._trusted_directory_factory is PosixTrustedDirectoryV1
    assert controller._artifact_root_authorizer is authorize_posix_artifact_root_v1
