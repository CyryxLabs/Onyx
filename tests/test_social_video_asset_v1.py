from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.social_video_asset_v1 import (
    SocialVideoAssetBrokerV1,
    SocialVideoAssetDenied,
)
from scripts import onyx_social_cli


def _video(root: Path, name: str = "clip.mp4", content: bytes = b"video-data") -> Path:
    path = root / name
    if path.suffix.lower() == ".webm":
        payload = b"\x1a\x45\xdf\xa3" + content
    else:
        payload = b"\x00\x00\x00\x18ftypmp42" + content
    path.write_bytes(payload)
    return path


def test_descriptor_binds_exact_video_without_serializing_local_path(tmp_path: Path) -> None:
    path = _video(tmp_path)
    broker = SocialVideoAssetBrokerV1((tmp_path.resolve(),), max_bytes=1024)
    descriptor = broker.inspect(
        path.resolve(), workspace_id="workspace-a", principal_id="owner-a"
    )
    encoded = json.dumps(descriptor.to_dict(), sort_keys=True)
    assert descriptor.mime_type == "video/mp4"
    assert descriptor.size_bytes == len(b"\x00\x00\x00\x18ftypmp42video-data")
    assert str(path) not in encoded
    resolved = broker.resolve(
        descriptor.binding, workspace_id="workspace-a", principal_id="owner-a"
    )
    with resolved.open_binary() as stream:
        assert stream.read() == b"\x00\x00\x00\x18ftypmp42video-data"


def test_video_mutation_after_preview_invalidates_dispatch(tmp_path: Path) -> None:
    path = _video(tmp_path)
    broker = SocialVideoAssetBrokerV1((tmp_path.resolve(),), max_bytes=1024)
    descriptor = broker.inspect(
        path.resolve(), workspace_id="workspace-a", principal_id="owner-a"
    )
    path.write_bytes(b"changed-video")
    with pytest.raises(SocialVideoAssetDenied, match="changed after preview"):
        broker.resolve(
            descriptor.binding, workspace_id="workspace-a", principal_id="owner-a"
        )


def test_deleted_video_after_preview_invalidates_dispatch(tmp_path: Path) -> None:
    path = _video(tmp_path)
    broker = SocialVideoAssetBrokerV1((tmp_path.resolve(),), max_bytes=1024)
    descriptor = broker.inspect(
        path.resolve(), workspace_id="workspace-a", principal_id="owner-a"
    )
    path.unlink()
    with pytest.raises(SocialVideoAssetDenied, match="changed after preview"):
        broker.resolve(
            descriptor.binding, workspace_id="workspace-a", principal_id="owner-a"
        )


def test_expired_or_cross_scope_lease_is_denied(tmp_path: Path) -> None:
    now = [100.0]
    broker = SocialVideoAssetBrokerV1(
        (tmp_path.resolve(),), max_bytes=1024, clock=lambda: now[0]
    )
    descriptor = broker.inspect(
        _video(tmp_path).resolve(),
        workspace_id="workspace-a",
        principal_id="owner-a",
        lease_seconds=1.0,
    )
    with pytest.raises(SocialVideoAssetDenied, match="scope"):
        broker.resolve(
            descriptor.binding, workspace_id="workspace-b", principal_id="owner-a"
        )
    now[0] = 101.0
    with pytest.raises(SocialVideoAssetDenied, match="expired"):
        broker.resolve(
            descriptor.binding, workspace_id="workspace-a", principal_id="owner-a"
        )


def test_restart_does_not_restore_raw_path_or_allow_blind_dispatch(tmp_path: Path) -> None:
    first = SocialVideoAssetBrokerV1((tmp_path.resolve(),), max_bytes=1024)
    descriptor = first.inspect(
        _video(tmp_path).resolve(),
        workspace_id="workspace-a",
        principal_id="owner-a",
    )
    restarted = SocialVideoAssetBrokerV1((tmp_path.resolve(),), max_bytes=1024)
    with pytest.raises(SocialVideoAssetDenied, match="not restored"):
        restarted.resolve(
            descriptor.binding, workspace_id="workspace-a", principal_id="owner-a"
        )


@pytest.mark.parametrize("name", ["clip.txt", "clip.exe", "clip.mkv"])
def test_unsupported_video_types_are_denied(tmp_path: Path, name: str) -> None:
    broker = SocialVideoAssetBrokerV1((tmp_path.resolve(),), max_bytes=1024)
    with pytest.raises(SocialVideoAssetDenied, match="type"):
        broker.inspect(
            _video(tmp_path, name).resolve(),
            workspace_id="workspace-a",
            principal_id="owner-a",
        )


def test_oversized_video_is_denied_before_hashing(tmp_path: Path) -> None:
    broker = SocialVideoAssetBrokerV1((tmp_path.resolve(),), max_bytes=4)
    with pytest.raises(SocialVideoAssetDenied, match="size"):
        broker.inspect(
            _video(tmp_path).resolve(),
            workspace_id="workspace-a",
            principal_id="owner-a",
        )


def test_renamed_non_video_content_is_denied(tmp_path: Path) -> None:
    path = tmp_path / "renamed.mp4"
    path.write_bytes(b"not-a-video")
    broker = SocialVideoAssetBrokerV1((tmp_path.resolve(),), max_bytes=1024)
    with pytest.raises(SocialVideoAssetDenied, match="signature"):
        broker.inspect(
            path.resolve(), workspace_id="workspace-a", principal_id="owner-a"
        )


def test_symlinked_video_is_denied_when_host_supports_symlinks(tmp_path: Path) -> None:
    target = _video(tmp_path)
    link = tmp_path / "linked.mp4"
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("host does not permit test symlinks")
    broker = SocialVideoAssetBrokerV1((tmp_path.resolve(),), max_bytes=1024)
    with pytest.raises(SocialVideoAssetDenied, match="symlink"):
        broker.inspect(
            link.absolute(), workspace_id="workspace-a", principal_id="owner-a"
        )


def test_cli_video_preview_is_local_machine_readable_and_path_free(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    media = _video(tmp_path).resolve()
    result = onyx_social_cli.main(
        [
            "video-preview",
            "--workspace-id", "workspace-a",
            "--principal-id", "owner-a",
            "--account-id", "account-a",
            "--target", "instagram-reels",
            "--caption", "Evidence-bound preview.",
            "--controlled-root", str(tmp_path.resolve()),
            "--media-file", str(media),
        ]
    )
    assert result == 0
    raw = capsys.readouterr().out
    output = json.loads(raw)
    assert output["video_asset"]["contract"] == "OnyxSocialVideoAsset.v1"
    assert output["preview"]["consent_text"].startswith("PUBLISH EXACT PREVIEW ")
    assert str(media) not in raw
