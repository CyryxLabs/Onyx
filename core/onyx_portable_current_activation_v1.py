"""Default-off macOS/Linux binding for the current V15-V19 host stack.

This module owns no assistant engine.  It supplies the exact host-specific
boundaries required by the existing activation chain and leaves every Windows
default untouched.  The candidate remains capability-limited until native
macOS and Linux evidence promotes its activation contract.
"""

from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Final

from core import onyx_live_activation_v15 as v15
from core import onyx_live_activation_v19 as v19
from core.executable_runtime_endpoint_v1 import (
    ExecutableRuntimeEndpointV1,
    executable_runtime_endpoint_v1,
)
from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1
from core.posix_owner_authority_v1 import (
    PosixOwnerAuthorityFactoryV1,
    PosixOwnerAuthorityUnavailableV1,
)
from core.portable_host_capability_v1 import (
    PortableHostBindingsV1,
    PortableHostCapabilityV1Error,
    _mint_portable_host_bindings_v1,
    require_portable_host_bindings_v1,
)


FEATURE_FLAG: Final = "ONYX_PORTABLE_CURRENT_ACTIVATION_V1"
SUPPORTED_SYSTEMS: Final = frozenset({"Darwin", "Linux"})


class PortableCurrentActivationV1Error(RuntimeError):
    """The explicit portable-current candidate could not be established."""


def _native_system() -> str:
    system = platform.system()
    if os.name != "posix" or system not in SUPPORTED_SYSTEMS:
        raise PortableCurrentActivationV1Error("portable_current_posix_host_required")
    if not callable(getattr(os, "geteuid", None)):
        raise PortableCurrentActivationV1Error(
            "portable_current_owner_identity_unavailable"
        )
    return system


def default_runtime_address_v1(system: str | None = None) -> str:
    """Return a short, canonical local endpoint identity for a disabled sandbox."""

    selected = _native_system() if system is None else system
    if selected == "Darwin":
        return "unix:///private/tmp/onyx-docker.sock"
    if selected == "Linux":
        return "unix:///run/onyx-docker.sock"
    raise PortableCurrentActivationV1Error("portable_current_runtime_host_unsupported")


def runtime_endpoint_v1(
    address: str,
    *,
    system: str | None = None,
) -> ExecutableRuntimeEndpointV1:
    selected = _native_system() if system is None else system
    if selected not in SUPPORTED_SYSTEMS:
        raise PortableCurrentActivationV1Error(
            "portable_current_runtime_host_unsupported"
        )
    return executable_runtime_endpoint_v1(
        address,
        platform_name=selected,
        require_existing=False,
    )


def exact_activation_environment_v1(
    workspace_root: str | os.PathLike[str],
    *,
    environ: Mapping[str, str] | None = None,
    runtime_address: str | None = None,
    workspace_boundary: PosixTrustedDirectoryV1 | None = None,
) -> dict[str, str]:
    """Return a canonical explicit candidate environment without selecting it."""

    system = _native_system()
    workspace = Path(workspace_root)
    if not workspace.is_absolute():
        raise PortableCurrentActivationV1Error("portable_current_workspace_unavailable")
    if os.name == "posix":
        if (
            type(workspace_boundary) is not PosixTrustedDirectoryV1
            or workspace_boundary.path != workspace
        ):
            raise PortableCurrentActivationV1Error(
                "portable_current_workspace_boundary_required"
            )
        workspace_boundary._validate()
    elif not workspace.is_dir():
        # Platform-independent contract tests may exercise environment
        # assembly on Windows; native portable launch never uses this branch.
        raise PortableCurrentActivationV1Error("portable_current_workspace_unavailable")
    address = runtime_address or default_runtime_address_v1(system)
    endpoint = runtime_endpoint_v1(address, system=system)
    result = dict(os.environ if environ is None else environ)
    for name in v19.CONTROL_FLAGS:
        result.pop(name, None)
    result.update(
        v19.exact_activation_environment(
            (workspace,),
            executable_docker_cli=str(
                (workspace / ".onyx" / "disabled-docker-cli").absolute()
            ),
            executable_docker_host=address,
            executable_sandbox=False,
            runtime_endpoint=endpoint,
        )
    )
    result[FEATURE_FLAG] = "1"
    return result


def _requested(source: Mapping[str, str]) -> None:
    if source.get(FEATURE_FLAG) != "1":
        raise PortableCurrentActivationV1Error(
            "portable_current_activation_not_requested"
        )


def prove_negative_boundary_v1(
    environ: Mapping[str, str] | None = None,
) -> None:
    """Prove portable readiness without creating owner state or starting V19.

    This additive entrypoint exists only for the packaged negative-boundary
    smoke.  It intentionally repeats the production guards so the proof cannot
    weaken or parameterize :func:`activate_main`.  A ready factory is closed
    without ever being called; no owner key, journal, chain head, authority, or
    V19/V10 runtime can be created by this path.
    """

    _native_system()
    source = os.environ if environ is None else environ
    _requested(source)
    address = source.get(v15.EXECUTABLE_DOCKER_HOST_FLAG, "")
    try:
        bindings = _mint_portable_host_bindings_v1(address)
        require_portable_host_bindings_v1(bindings, stage="governance_v16")
    except PortableHostCapabilityV1Error as exc:
        raise PortableCurrentActivationV1Error(
            "portable_current_host_authority_unavailable"
        ) from exc
    if bindings.governance_descriptor_io is not True:
        raise PortableCurrentActivationV1Error(
            "portable_current_v16_descriptor_governance_unavailable"
        )
    try:
        owner_factory = PosixOwnerAuthorityFactoryV1()
    except PosixOwnerAuthorityUnavailableV1 as exc:
        raise PortableCurrentActivationV1Error(
            "portable_current_v4_owner_authority_unavailable"
        ) from exc
    owner_factory.close()
    raise PortableCurrentActivationV1Error(
        "portable_current_v4_owner_authority_unavailable"
    )


def activate_main(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
) -> v19.OnyxLiveActivationV19:
    """Install V19 with exact POSIX successors behind the explicit flag."""

    _native_system()
    source = os.environ if environ is None else environ
    _requested(source)
    address = source.get(v15.EXECUTABLE_DOCKER_HOST_FLAG, "")
    try:
        bindings = _mint_portable_host_bindings_v1(address)
        require_portable_host_bindings_v1(bindings, stage="governance_v16")
    except PortableHostCapabilityV1Error as exc:
        raise PortableCurrentActivationV1Error(
            "portable_current_host_authority_unavailable"
        ) from exc
    if bindings.governance_descriptor_io is not True:
        raise PortableCurrentActivationV1Error(
            "portable_current_v16_descriptor_governance_unavailable"
        )
    try:
        owner_factory = PosixOwnerAuthorityFactoryV1()
    except PosixOwnerAuthorityUnavailableV1 as exc:
        # Backend readiness is proven before the factory creates its trusted
        # directory, lease, journal, key, or chain head.
        raise PortableCurrentActivationV1Error(
            "portable_current_v4_owner_authority_unavailable"
        ) from exc
    try:
        controller = v19.activate_main(
            module,
            source,
            portable_bindings=bindings,
            authority_factory=owner_factory,
        )
    except BaseException:
        owner_factory.close()
        raise

    original_rollback = controller.rollback_all
    closed = False

    def rollback_all() -> None:
        nonlocal closed
        active_error: BaseException | None = None
        try:
            original_rollback()
        except BaseException as exc:
            active_error = exc
        try:
            if not closed:
                owner_factory.close()
                closed = True
        except BaseException:
            if active_error is None:
                raise
        if active_error is not None:
            raise active_error

    controller.rollback_all = rollback_all  # type: ignore[method-assign]
    controller._portable_owner_authority_factory_v1 = owner_factory
    return controller


__all__ = [
    "FEATURE_FLAG",
    "PortableCurrentActivationV1Error",
    "PortableHostBindingsV1",
    "SUPPORTED_SYSTEMS",
    "activate_main",
    "default_runtime_address_v1",
    "exact_activation_environment_v1",
    "prove_negative_boundary_v1",
    "runtime_endpoint_v1",
]
