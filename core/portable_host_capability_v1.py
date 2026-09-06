"""Opaque native-POSIX authority for the default-off portable candidate.

The public activation stack may validate this authority, but it cannot mint
one.  A capability and its immutable binding set are registered by identity
only after a real macOS/Linux host check in this module.  This prevents a
caller supplied lambda or look-alike factory from widening the host boundary.

Threat boundary: this is an injection-integrity boundary between the official
activation modules; it is not a sandbox against arbitrary Python already
executing inside this process.  The private issuer intentionally accepts only
the runtime address and always binds the fixed implementations imported here.
It has no caller-controlled factory or feature-escalation parameter.
"""

from __future__ import annotations

import os
import platform
import weakref
from dataclasses import dataclass
from typing import Callable, Final

from core.executable_runtime_endpoint_v1 import (
    ExecutableRuntimeEndpointV1,
    executable_runtime_endpoint_v1,
)
from core.posix_artifact_root_authority_v1 import authorize_posix_artifact_root_v1
from core.posix_kill_signal_v1 import PosixKillSignalV1
from core.posix_trusted_directory_v1 import (
    PosixTrustedDirectoryV1,
    require_posix_descriptor_sqlite_v1,
)


SUPPORTED_SYSTEMS: Final = frozenset({"Darwin", "Linux"})
ALLOWED_STAGES: Final = frozenset(
    {
        "governance_v16",
        "founder_preflight",
        "founder_controller",
        "document_intake_preflight",
        "dayops_preflight",
    }
)


class PortableHostCapabilityV1Error(RuntimeError):
    """The native portable authority is absent, forged, or has drifted."""


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False)
class PortableHostCapabilityV1:
    """Opaque process-bound proof of a real supported POSIX host."""

    _seal: object
    system: str
    euid: int
    process_id: int


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False)
class PortableHostBindingsV1:
    """One sealed, all-or-nothing set of portable host implementations."""

    _seal: object
    capability: PortableHostCapabilityV1
    runtime_address: str
    runtime_endpoint_factory: Callable[[str], ExecutableRuntimeEndpointV1]
    trusted_directory_factory: type[PosixTrustedDirectoryV1]
    kill_signal_factory: type[PosixKillSignalV1]
    artifact_root_authorizer: Callable[..., object]
    governance_descriptor_io: bool


_CAPABILITY_SEAL = object()
_BINDINGS_SEAL = object()
_CAPABILITIES: dict[int, weakref.ReferenceType[PortableHostCapabilityV1]] = {}
_BINDINGS: dict[
    int,
    tuple[
        weakref.ReferenceType[PortableHostBindingsV1],
        Callable[[str], ExecutableRuntimeEndpointV1],
    ],
] = {}


def _register_capability(value: PortableHostCapabilityV1) -> None:
    identity = id(value)

    def retire(reference: weakref.ReferenceType[PortableHostCapabilityV1]) -> None:
        if _CAPABILITIES.get(identity) is reference:
            _CAPABILITIES.pop(identity, None)

    reference = weakref.ref(value, retire)
    _CAPABILITIES[identity] = reference


def _register_bindings(
    value: PortableHostBindingsV1,
    endpoint_factory: Callable[[str], ExecutableRuntimeEndpointV1],
) -> None:
    identity = id(value)

    def retire(reference: weakref.ReferenceType[PortableHostBindingsV1]) -> None:
        registered = _BINDINGS.get(identity)
        if registered is not None and registered[0] is reference:
            _BINDINGS.pop(identity, None)

    reference = weakref.ref(value, retire)
    _BINDINGS[identity] = (reference, endpoint_factory)


def _registered_capability(value: object) -> bool:
    if type(value) is not PortableHostCapabilityV1:
        return False
    reference = _CAPABILITIES.get(id(value))
    return reference is not None and reference() is value


def _registered_bindings(
    value: object,
) -> tuple[
    weakref.ReferenceType[PortableHostBindingsV1],
    Callable[[str], ExecutableRuntimeEndpointV1],
] | None:
    if type(value) is not PortableHostBindingsV1:
        return None
    registered = _BINDINGS.get(id(value))
    if registered is None or registered[0]() is not value:
        return None
    return registered


def _native_posix_identity() -> tuple[str, int, int]:
    system = platform.system()
    geteuid = getattr(os, "geteuid", None)
    if os.name != "posix" or system not in SUPPORTED_SYSTEMS or not callable(geteuid):
        raise PortableHostCapabilityV1Error("portable_native_posix_host_required")
    return system, int(geteuid()), os.getpid()


def _mint_portable_host_bindings_v1(runtime_address: str) -> PortableHostBindingsV1:
    """Issue only the constrained official binding set for the native host.

    Python privacy cannot protect against hostile code with arbitrary
    same-process introspection.  This function instead prevents accidental or
    API-level widening: no external factory, governance toggle, or alternate
    implementation can be supplied by its caller.
    """

    system, euid, process_id = _native_posix_identity()
    if not isinstance(runtime_address, str) or not runtime_address:
        raise PortableHostCapabilityV1Error("portable_runtime_address_invalid")
    endpoint = executable_runtime_endpoint_v1(
        runtime_address,
        platform_name=system,
        require_existing=False,
    )
    try:
        require_posix_descriptor_sqlite_v1()
    except Exception as exc:
        raise PortableHostCapabilityV1Error(
            "portable_governance_descriptor_io_unavailable"
        ) from exc
    capability = PortableHostCapabilityV1(
        _CAPABILITY_SEAL,
        system,
        euid,
        process_id,
    )
    _register_capability(capability)

    def endpoint_factory(raw: str) -> ExecutableRuntimeEndpointV1:
        require_portable_host_capability_v1(capability)
        if raw != runtime_address:
            raise PortableHostCapabilityV1Error("portable_runtime_endpoint_drift")
        return endpoint

    bindings = PortableHostBindingsV1(
        _BINDINGS_SEAL,
        capability,
        runtime_address,
        endpoint_factory,
        PosixTrustedDirectoryV1,
        PosixKillSignalV1,
        authorize_posix_artifact_root_v1,
        True,
    )
    _register_bindings(bindings, endpoint_factory)
    return bindings


def require_portable_host_capability_v1(
    value: object,
    *,
    stage: str | None = None,
) -> PortableHostCapabilityV1:
    if (
        not _registered_capability(value)
        or value._seal is not _CAPABILITY_SEAL
    ):
        raise PortableHostCapabilityV1Error("portable_host_capability_invalid")
    system, euid, process_id = _native_posix_identity()
    if (value.system, value.euid, value.process_id) != (system, euid, process_id):
        raise PortableHostCapabilityV1Error("portable_host_capability_drift")
    if stage is not None and stage not in ALLOWED_STAGES:
        raise PortableHostCapabilityV1Error("portable_host_stage_invalid")
    return value


def require_portable_host_bindings_v1(
    value: object,
    *,
    stage: str | None = None,
) -> PortableHostBindingsV1:
    registered = _registered_bindings(value)
    if registered is None or value._seal is not _BINDINGS_SEAL:
        raise PortableHostCapabilityV1Error("portable_host_bindings_invalid")
    require_portable_host_capability_v1(value.capability, stage=stage)
    if (
        value.trusted_directory_factory is not PosixTrustedDirectoryV1
        or value.kill_signal_factory is not PosixKillSignalV1
        or value.artifact_root_authorizer is not authorize_posix_artifact_root_v1
        or value.runtime_endpoint_factory is not registered[1]
        or value.governance_descriptor_io is not True
    ):
        raise PortableHostCapabilityV1Error("portable_host_bindings_drift")
    return value


__all__ = [
    "PortableHostBindingsV1",
    "PortableHostCapabilityV1",
    "PortableHostCapabilityV1Error",
    "require_portable_host_bindings_v1",
    "require_portable_host_capability_v1",
]
