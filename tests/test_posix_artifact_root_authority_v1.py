from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import artifact_service as artifacts
from core import posix_artifact_root_authority_v1 as authority
from core.posix_artifact_root_authority_v1 import (
    authorize_posix_artifact_root_v1,
)
from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1


def _synthetic_boundary(tmp_path: Path) -> PosixTrustedDirectoryV1:
    boundary = object.__new__(PosixTrustedDirectoryV1)
    boundary.enabled = True
    boundary.path = tmp_path
    boundary._descriptor = 41
    boundary._root_identity = (7, 11)
    boundary._closed = False
    return boundary


def _directory_info(
    *,
    uid: int = 1000,
    mode: int = 0o700,
    identity: tuple[int, int] = (7, 11),
) -> SimpleNamespace:
    return SimpleNamespace(
        st_mode=stat.S_IFDIR | mode,
        st_uid=uid,
        st_dev=identity[0],
        st_ino=identity[1],
    )


def _install_synthetic_posix(
    monkeypatch: pytest.MonkeyPatch,
    *,
    descriptor_info: SimpleNamespace,
    named_info: SimpleNamespace,
) -> None:
    path_type = type(Path.cwd())
    monkeypatch.setattr(authority.os, "name", "posix")
    monkeypatch.setattr(authority, "_effective_uid", lambda: 1000)
    monkeypatch.setattr(authority.os, "fstat", lambda _descriptor: descriptor_info)
    monkeypatch.setattr(path_type, "lstat", lambda _path: named_info)
    monkeypatch.setattr(
        PosixTrustedDirectoryV1,
        "_validate",
        lambda _boundary: None,
    )


def test_posix_authority_refuses_non_posix_host(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _synthetic_boundary(tmp_path)
    monkeypatch.setattr(authority.os, "name", "nt")

    with pytest.raises(artifacts.ArtifactIsolationError, match="exact POSIX"):
        authorize_posix_artifact_root_v1(
            boundary,
            workspace_id="workspace-owner",
        )


@pytest.mark.parametrize(
    ("descriptor_info", "named_info", "error"),
    [
        (_directory_info(uid=2000), _directory_info(), "owner-private"),
        (_directory_info(), _directory_info(mode=0o750), "owner-private"),
        (
            SimpleNamespace(
                st_mode=stat.S_IFREG | 0o700,
                st_uid=1000,
                st_dev=7,
                st_ino=11,
            ),
            _directory_info(),
            "owner-private",
        ),
        (_directory_info(), _directory_info(identity=(7, 12)), "identity changed"),
    ],
)
def test_posix_boundary_validates_uid_mode_descriptor_and_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    descriptor_info: SimpleNamespace,
    named_info: SimpleNamespace,
    error: str,
) -> None:
    boundary = _synthetic_boundary(tmp_path)
    _install_synthetic_posix(
        monkeypatch,
        descriptor_info=descriptor_info,
        named_info=named_info,
    )

    with pytest.raises(
        (artifacts.ArtifactIsolationError, artifacts.ArtifactIntegrityError),
        match=error,
    ):
        authority._validated_posix_artifact_root_v1(boundary)


def test_posix_boundary_rejects_link_leaf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _synthetic_boundary(tmp_path)
    linked = SimpleNamespace(
        st_mode=stat.S_IFLNK | 0o700,
        st_uid=1000,
        st_dev=7,
        st_ino=11,
    )
    _install_synthetic_posix(
        monkeypatch,
        descriptor_info=_directory_info(),
        named_info=linked,
    )

    with pytest.raises(artifacts.ArtifactIsolationError, match="owner-private"):
        authority._validated_posix_artifact_root_v1(boundary)


def test_posix_boundary_accepts_matching_private_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundary = _synthetic_boundary(tmp_path)
    info = _directory_info()
    _install_synthetic_posix(
        monkeypatch,
        descriptor_info=info,
        named_info=info,
    )

    assert authority._validated_posix_artifact_root_v1(boundary) == tmp_path


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX descriptors")
def test_native_posix_capability_owns_boundary_and_serves_artifacts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "artifacts"
    boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
    capability = authorize_posix_artifact_root_v1(
        boundary,
        workspace_id="workspace-owner",
    )
    service = artifacts.ArtifactService(
        capability,
        workspace_id="workspace-owner",
        enabled=True,
    )
    try:
        record = service.publish_bytes(
            b"portable artifact",
            media_type="text/plain",
            data_class="internal",
            source_provenance={"kind": "portable_authority_test"},
        )
        assert service.read(record) == b"portable artifact"
        assert capability._host_boundary is boundary
    finally:
        service.close()
    assert boundary._closed is True
