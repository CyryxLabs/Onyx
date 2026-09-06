"""Strict POSIX successor for the existing Windows artifact-root authority.

The artifact engine already owns descriptor-relative POSIX CAS operations.
This module only converts one exact ``PosixTrustedDirectoryV1`` into the opaque
``ArtifactRootCapability`` consumed by ``ArtifactService``.  It does not alter
or replace the Windows ``authorize_host_root_v1`` contract.
"""

from __future__ import annotations

import os
import stat
import weakref
from pathlib import Path

from core import artifact_service as artifacts
from core.host_security_boundary_v1 import HostSecurityBoundaryError
from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1


def _identity(info: os.stat_result) -> tuple[int, int]:
    return int(info.st_dev), int(info.st_ino)


def _effective_uid() -> int:
    getter = getattr(os, "geteuid", None)
    if not callable(getter):
        raise artifacts.ArtifactIsolationError(
            "POSIX artifact authority cannot determine the effective uid"
        )
    return int(getter())


def _validated_posix_artifact_root_v1(
    boundary: object,
) -> Path:
    """Revalidate type, owner, mode, link state, and both pinned identities."""

    if os.name != "posix" or type(boundary) is not PosixTrustedDirectoryV1:
        raise artifacts.ArtifactIsolationError(
            "artifact host root requires an exact POSIX trusted boundary"
        )
    if (
        boundary.enabled is not True
        or boundary._closed
        or boundary._descriptor < 0
        or boundary._root_identity is None
        or not boundary.path.is_absolute()
    ):
        raise artifacts.ArtifactIsolationError(
            "POSIX artifact trusted boundary is unavailable"
        )
    try:
        boundary._validate()
        descriptor_info = os.fstat(boundary._descriptor)
        named_info = boundary.path.lstat()
    except (HostSecurityBoundaryError, OSError) as exc:
        raise artifacts.ArtifactIntegrityError(
            "POSIX artifact trusted boundary validation failed"
        ) from exc
    owner = _effective_uid()
    if (
        not stat.S_ISDIR(descriptor_info.st_mode)
        or not stat.S_ISDIR(named_info.st_mode)
        or stat.S_ISLNK(named_info.st_mode)
        or boundary.path.is_symlink()
        or int(descriptor_info.st_uid) != owner
        or int(named_info.st_uid) != owner
        or stat.S_IMODE(descriptor_info.st_mode) != 0o700
        or stat.S_IMODE(named_info.st_mode) != 0o700
    ):
        raise artifacts.ArtifactIsolationError(
            "POSIX artifact root must be one owner-private 0700 directory"
        )
    descriptor_identity = _identity(descriptor_info)
    named_identity = _identity(named_info)
    if (
        descriptor_identity != boundary._root_identity
        or named_identity != boundary._root_identity
    ):
        raise artifacts.ArtifactIntegrityError(
            "POSIX artifact trusted boundary identity changed"
        )
    return boundary.path.resolve(strict=True)


def authorize_posix_artifact_root_v1(
    boundary: object,
    *,
    workspace_id: str,
) -> artifacts.ArtifactRootCapability:
    """Consume one exact POSIX boundary as an ArtifactService authority.

    The returned capability owns both the artifact engine's pinned descriptor
    chain and the supplied trusted-directory descriptor.  Closing either the
    service or capability retires them in the same order as the Windows host
    authority.
    """

    path = _validated_posix_artifact_root_v1(boundary)
    assert type(boundary) is PosixTrustedDirectoryV1
    capability: artifacts.ArtifactRootCapability | None = None
    try:
        capability = artifacts._authorize_root_for_testing(
            path,
            allowlisted_roots=(path,),
            workspace_id=workspace_id,
        )
        boundary._validate()
    except BaseException:
        try:
            if capability is not None:
                capability.close()
        finally:
            boundary.close()
        raise
    with artifacts._CAPABILITIES_LOCK:
        state = artifacts._CAPABILITIES.get(capability)
    if state is None:
        capability.close()
        boundary.close()
        raise artifacts.ArtifactIntegrityError(
            "POSIX artifact capability registration was lost"
        )
    prior_finalizer = capability._finalizer
    if prior_finalizer is not None and prior_finalizer.alive:
        prior_finalizer.detach()
    capability._host_boundary = boundary
    try:
        capability._finalizer = weakref.finalize(
            capability,
            artifacts._finalize_host_capability,
            state,
            boundary,
        )
    except BaseException:
        capability.close()
        raise
    return capability


__all__ = ["authorize_posix_artifact_root_v1"]
