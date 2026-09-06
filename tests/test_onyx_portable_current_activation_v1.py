from __future__ import annotations

import os
import runpy
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from core import onyx_live_activation_v15 as v15
from core import onyx_live_activation_v18 as v18
from core import onyx_live_activation_v19 as v19
from core import onyx_portable_current_activation_v1 as portable
from core.native_activation_contract_v1 import (
    NativeActivationContractError,
    activation_contract_for_system_v1,
)
from core.posix_artifact_root_authority_v1 import (
    authorize_posix_artifact_root_v1,
)
from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1


ROOT = Path(__file__).resolve().parents[1]


def test_native_contract_keeps_portable_candidate_truthfully_limited() -> None:
    legacy = activation_contract_for_system_v1("Linux")
    candidate = activation_contract_for_system_v1(
        "Linux",
        portable_current=True,
    )

    assert legacy["normal_activation"] == "v8"
    assert candidate == {
        "contract": "OnyxHostActivation.v1",
        "normal_activation": "unavailable",
        "declared_activation": "v19",
        "smoke_activation": "none",
        "highest_proven_activation": "v16_descriptor_ledger",
        "boundary_reached": "pre_v10",
        "next_unimplemented_activation": "v4_portable_owner_authority",
        "activation_profile": "portable-current-negative-boundary-default-off",
        "capability_limited": True,
        "v15_v19_parity": False,
        "native_evidence_required": True,
        "limitation_reason": "portable_current_v4_owner_authority_unavailable",
    }
    assert (
        activation_contract_for_system_v1(
            "Windows",
            portable_current=True,
        )["activation_profile"]
        == "current-windows"
    )
    with pytest.raises(NativeActivationContractError, match="boolean"):
        activation_contract_for_system_v1("Linux", portable_current=1)  # type: ignore[arg-type]


def test_exact_candidate_environment_threads_typed_unix_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(portable, "_native_system", lambda: "Linux")

    boundary = None
    if os.name == "posix":
        workspace.chmod(0o700)
        boundary = PosixTrustedDirectoryV1(root=workspace, enabled=True)

    try:
        environment = portable.exact_activation_environment_v1(
            workspace,
            environ={"UNCHANGED": "yes"},
            workspace_boundary=boundary,
        )
    finally:
        if boundary is not None:
            boundary.close()
    address = portable.default_runtime_address_v1("Linux")
    endpoint = portable.runtime_endpoint_v1(address, system="Linux")
    flags = v19.ActivationFlagsV19.from_canonical_environ(
        environment,
        runtime_endpoint_factory=lambda raw: endpoint if raw == address else None,
    )

    assert environment[portable.FEATURE_FLAG] == "1"
    assert environment["UNCHANGED"] == "yes"
    assert flags.base.base.base.base.runtime_endpoint == endpoint
    assert flags.base.base.base.base.executable_sandbox is False


def test_candidate_activation_requires_flag_and_refuses_unbound_owner_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(portable, "_native_system", lambda: "Linux")
    calls = 0

    def fake_activate(
        module: ModuleType,
        source: object,
        **options: object,
    ) -> object:
        nonlocal calls
        calls += 1
        return object()

    monkeypatch.setattr(portable.v19, "activate_main", fake_activate)
    host = ModuleType("portable_current_host")
    environment = {
        portable.FEATURE_FLAG: "1",
        v15.EXECUTABLE_DOCKER_HOST_FLAG: "unix:///run/onyx-docker.sock",
    }

    bindings = SimpleNamespace(governance_descriptor_io=True)
    monkeypatch.setattr(
        portable, "_mint_portable_host_bindings_v1", lambda _a: bindings
    )
    monkeypatch.setattr(
        portable,
        "require_portable_host_bindings_v1",
        lambda value, *, stage: value,
    )

    def owner_backend_unavailable():
        raise portable.PosixOwnerAuthorityUnavailableV1(
            "posix_owner_secure_backend_unavailable"
        )

    monkeypatch.setattr(
        portable,
        "PosixOwnerAuthorityFactoryV1",
        owner_backend_unavailable,
    )
    with pytest.raises(
        portable.PortableCurrentActivationV1Error,
        match="v4_owner_authority_unavailable",
    ):
        portable.activate_main(host, environment)
    assert calls == 0

    with pytest.raises(
        portable.PortableCurrentActivationV1Error, match="not_requested"
    ):
        portable.activate_main(host, {})


def test_negative_boundary_proof_closes_readiness_without_factory_call_or_v19(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(portable, "_native_system", lambda: "Linux")
    bindings = SimpleNamespace(governance_descriptor_io=True)
    stages: list[str] = []
    monkeypatch.setattr(
        portable,
        "_mint_portable_host_bindings_v1",
        lambda _address: bindings,
    )
    monkeypatch.setattr(
        portable,
        "require_portable_host_bindings_v1",
        lambda value, *, stage: stages.append(stage) or value,
    )
    authority_calls = 0
    close_calls = 0
    v19_calls = 0

    class ReadinessFactory:
        def __call__(self):
            nonlocal authority_calls
            authority_calls += 1
            return object()

        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1

    monkeypatch.setattr(
        portable,
        "PosixOwnerAuthorityFactoryV1",
        lambda: ReadinessFactory(),
    )

    def activate_v19(*_args, **_kwargs):
        nonlocal v19_calls
        v19_calls += 1
        return object()

    monkeypatch.setattr(portable.v19, "activate_main", activate_v19)
    environment = {
        portable.FEATURE_FLAG: "1",
        v15.EXECUTABLE_DOCKER_HOST_FLAG: "unix:///run/onyx-docker.sock",
    }

    with pytest.raises(
        portable.PortableCurrentActivationV1Error,
        match="^portable_current_v4_owner_authority_unavailable$",
    ):
        portable.prove_negative_boundary_v1(environment)

    assert stages == ["governance_v16"]
    assert authority_calls == 0
    assert close_calls == 1
    assert v19_calls == 0


def test_negative_boundary_proof_maps_unavailable_readiness_canonically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(portable, "_native_system", lambda: "Linux")
    bindings = SimpleNamespace(governance_descriptor_io=True)
    monkeypatch.setattr(
        portable,
        "_mint_portable_host_bindings_v1",
        lambda _address: bindings,
    )
    monkeypatch.setattr(
        portable,
        "require_portable_host_bindings_v1",
        lambda value, *, stage: value,
    )
    v19_calls = 0

    def unavailable_factory():
        raise portable.PosixOwnerAuthorityUnavailableV1(
            "posix_owner_secure_backend_unavailable"
        )

    def activate_v19(*_args, **_kwargs):
        nonlocal v19_calls
        v19_calls += 1
        return object()

    monkeypatch.setattr(
        portable,
        "PosixOwnerAuthorityFactoryV1",
        unavailable_factory,
    )
    monkeypatch.setattr(portable.v19, "activate_main", activate_v19)

    with pytest.raises(
        portable.PortableCurrentActivationV1Error,
        match="^portable_current_v4_owner_authority_unavailable$",
    ):
        portable.prove_negative_boundary_v1(
            {
                portable.FEATURE_FLAG: "1",
                v15.EXECUTABLE_DOCKER_HOST_FLAG: "unix:///run/onyx-docker.sock",
            }
        )
    assert v19_calls == 0


def test_negative_boundary_proof_propagates_close_failure_without_v19(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(portable, "_native_system", lambda: "Linux")
    bindings = SimpleNamespace(governance_descriptor_io=True)
    monkeypatch.setattr(
        portable,
        "_mint_portable_host_bindings_v1",
        lambda _address: bindings,
    )
    monkeypatch.setattr(
        portable,
        "require_portable_host_bindings_v1",
        lambda value, *, stage: value,
    )
    authority_calls = 0
    close_calls = 0

    class CloseFailure(RuntimeError):
        pass

    class ReadinessFactory:
        def __call__(self):
            nonlocal authority_calls
            authority_calls += 1
            return object()

        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1
            raise CloseFailure("close-failure")

    monkeypatch.setattr(
        portable,
        "PosixOwnerAuthorityFactoryV1",
        lambda: ReadinessFactory(),
    )
    monkeypatch.setattr(
        portable.v19,
        "activate_main",
        lambda *_args, **_kwargs: pytest.fail("V19 must remain behind the proof"),
    )

    with pytest.raises(CloseFailure, match="close-failure"):
        portable.prove_negative_boundary_v1(
            {
                portable.FEATURE_FLAG: "1",
                v15.EXECUTABLE_DOCKER_HOST_FLAG: "unix:///run/onyx-docker.sock",
            }
        )
    assert authority_calls == 0
    assert close_calls == 1


def test_negative_boundary_proof_preserves_flag_and_binding_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(portable, "_native_system", lambda: "Linux")
    mint_calls = 0

    def mint(_address: str):
        nonlocal mint_calls
        mint_calls += 1
        return SimpleNamespace(governance_descriptor_io=True)

    monkeypatch.setattr(portable, "_mint_portable_host_bindings_v1", mint)
    monkeypatch.setattr(
        portable,
        "PosixOwnerAuthorityFactoryV1",
        lambda: pytest.fail("owner readiness must remain behind guards"),
    )
    with pytest.raises(
        portable.PortableCurrentActivationV1Error,
        match="activation_not_requested",
    ):
        portable.prove_negative_boundary_v1({})
    assert mint_calls == 0

    def deny_binding(_value, *, stage: str):
        assert stage == "governance_v16"
        raise portable.PortableHostCapabilityV1Error("binding unavailable")

    monkeypatch.setattr(portable, "require_portable_host_bindings_v1", deny_binding)
    with pytest.raises(
        portable.PortableCurrentActivationV1Error,
        match="host_authority_unavailable",
    ):
        portable.prove_negative_boundary_v1(
            {
                portable.FEATURE_FLAG: "1",
                v15.EXECUTABLE_DOCKER_HOST_FLAG: "unix:///run/onyx-docker.sock",
            }
        )
    assert mint_calls == 1

    monkeypatch.setattr(
        portable,
        "require_portable_host_bindings_v1",
        lambda value, *, stage: value,
    )
    monkeypatch.setattr(
        portable,
        "_mint_portable_host_bindings_v1",
        lambda _address: SimpleNamespace(governance_descriptor_io=False),
    )
    with pytest.raises(
        portable.PortableCurrentActivationV1Error,
        match="v16_descriptor_governance_unavailable",
    ):
        portable.prove_negative_boundary_v1(
            {
                portable.FEATURE_FLAG: "1",
                v15.EXECUTABLE_DOCKER_HOST_FLAG: "unix:///run/onyx-docker.sock",
            }
        )


def test_candidate_threads_official_owner_factory_through_v19_and_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(portable, "_native_system", lambda: "Linux")
    bindings = SimpleNamespace(governance_descriptor_io=True)
    monkeypatch.setattr(
        portable,
        "_mint_portable_host_bindings_v1",
        lambda _address: bindings,
    )
    monkeypatch.setattr(
        portable,
        "require_portable_host_bindings_v1",
        lambda value, *, stage: value,
    )
    events: list[str] = []

    class OwnerFactory:
        def __call__(self):
            return object()

        def close(self):
            events.append("owner-close")

    factory = OwnerFactory()
    monkeypatch.setattr(portable, "PosixOwnerAuthorityFactoryV1", lambda: factory)
    captured: dict[str, object] = {}

    class Controller:
        def rollback_all(self):
            events.append("v19-rollback")

    def activate(_module, source, **options):
        captured["source"] = source
        captured.update(options)
        return Controller()

    monkeypatch.setattr(portable.v19, "activate_main", activate)
    environment = {
        portable.FEATURE_FLAG: "1",
        v15.EXECUTABLE_DOCKER_HOST_FLAG: "unix:///run/onyx-docker.sock",
    }
    controller = portable.activate_main(ModuleType("portable-host"), environment)
    assert captured["portable_bindings"] is bindings
    assert captured["authority_factory"] is factory
    controller.rollback_all()
    controller.rollback_all()
    assert events == ["v19-rollback", "owner-close", "v19-rollback"]


def test_v19_rejects_explicit_posix_guard_before_v18(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = ModuleType("portable_v19_host")
    host = type("OnyxLive", (), {})
    module.OnyxLive = host
    base = SimpleNamespace(project=ROOT)
    stages: list[str] = []
    monkeypatch.setattr(v19.os, "name", "posix")
    monkeypatch.setattr(
        v19.ActivationFlagsV19,
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
        assert platform_guard("document_intake_preflight") is True
        return base

    monkeypatch.setattr(v19.v18, "preflight_host", base_preflight)
    monkeypatch.setattr(v19, "verify_current_hud_acceptance", lambda _root: None)

    def guard(stage: str) -> bool:
        stages.append(stage)
        return True

    with pytest.raises(v19.ActivationV19PlatformDenied, match="arbitrary"):
        v19.preflight_host(module, {}, platform_guard=guard)
    assert stages == []


def test_v18_threads_portable_directory_factory_into_v17_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = ModuleType("portable_v18_factory_thread")
    host = type("OnyxLive", (), {})
    module.OnyxLive = host
    flags = object.__new__(v18.ActivationFlagsV18)
    object.__setattr__(flags, "base", object())
    contract = v18.HostContractV18(module, host, tmp_path, object())  # type: ignore[arg-type]
    captured: dict[str, object] = {}

    def base_init(self: object, *_args: object, **kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(v18.v17.OnyxLiveActivationV17, "__init__", base_init)
    if os.name == "posix":
        from core import portable_host_capability_v1 as authority

        bindings = authority._mint_portable_host_bindings_v1(
            "unix:///run/onyx-docker.sock"
        )
        controller = v18.OnyxLiveActivationV18(
            flags,
            contract,
            portable_bindings=bindings,
        )
        assert controller._trusted_directory_factory is PosixTrustedDirectoryV1
        assert captured["portable_bindings"] is bindings
    else:
        controller = v18.OnyxLiveActivationV18(
            flags,
            contract,
            trusted_directory_factory=PosixTrustedDirectoryV1,
            artifact_root_authorizer=authorize_posix_artifact_root_v1,
        )

        assert controller._trusted_directory_factory is PosixTrustedDirectoryV1
        assert captured["trusted_directory_factory"] is PosixTrustedDirectoryV1


def test_stable_bootstrap_selects_candidate_only_for_explicit_posix_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = runpy.run_path(
        str(ROOT / "scripts" / "bootstrap_onyx.pyw"),
        run_name="portable_current_bootstrap_contract",
    )
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Linux")
    monkeypatch.delenv(portable.FEATURE_FLAG, raising=False)
    assert namespace["_selected_bootstrap"]() == namespace["CURRENT_BOOTSTRAP"]
    monkeypatch.setenv(portable.FEATURE_FLAG, "1")
    assert namespace["_selected_bootstrap"]() == namespace["PORTABLE_CURRENT_BOOTSTRAP"]
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Windows")
    assert namespace["_selected_bootstrap"]() == namespace["CURRENT_BOOTSTRAP"]
