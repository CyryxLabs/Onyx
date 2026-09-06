"""Ephemeral, digest-bound local video leases for governed social dispatch."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import mimetypes
from pathlib import Path
import secrets
import stat
import time
from typing import BinaryIO, Callable, Final


FEATURE_FLAG: Final = "ONYX_SOCIAL_VIDEO_ASSET_V1"
DEFAULT_MAX_BYTES: Final = 4 * 1024 * 1024 * 1024
DEFAULT_LEASE_SECONDS: Final = 300.0
_VIDEO_TYPES: Final = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".m4v": "video/x-m4v",
}


class SocialVideoAssetContractError(ValueError):
    """An asset or lease failed its closed input contract."""


class SocialVideoAssetDenied(PermissionError):
    """The host denied access, scope, drift, or lease use."""


@dataclass(frozen=True, slots=True)
class VideoAssetDescriptorV1:
    contract: str
    lease_id: str
    workspace_id: str
    principal_id: str
    sha256: str
    size_bytes: int
    mime_type: str
    expires_at: float
    status: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @property
    def binding(self) -> str:
        return (
            f"onyx-video-v1:{self.sha256}:{self.size_bytes}:"
            f"{self.mime_type}:{self.lease_id}"
        )


@dataclass(frozen=True, slots=True)
class VideoAssetDispatchV1:
    """Process-local adapter input; never serialize this object into the ledger."""

    descriptor: VideoAssetDescriptorV1
    local_path: Path

    def open_binary(self) -> BinaryIO:
        return self.local_path.open("rb")


@dataclass(slots=True)
class _Lease:
    descriptor: VideoAssetDescriptorV1
    path: Path
    device: int
    inode: int
    modified_ns: int


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or not (1 <= len(value) <= 128):
        raise SocialVideoAssetContractError(f"{label} is invalid")
    if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-" for character in value):
        raise SocialVideoAssetContractError(f"{label} is invalid")
    return value


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def _has_symlink(path: Path, roots: tuple[Path, ...]) -> bool:
    current = path
    while True:
        if current.is_symlink():
            return True
        if current in roots or current.parent == current:
            return False
        current = current.parent


def _sha256(path: Path, maximum: int) -> str:
    digest = hashlib.sha256()
    read = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            read += len(chunk)
            if read > maximum:
                raise SocialVideoAssetDenied("video exceeds the configured size bound")
            digest.update(chunk)
    return digest.hexdigest()


def _validate_signature(path: Path, mime_type: str) -> None:
    with path.open("rb") as stream:
        header = stream.read(16)
    if mime_type == "video/webm":
        valid = header.startswith(b"\x1a\x45\xdf\xa3")
    else:
        valid = len(header) >= 12 and header[4:8] == b"ftyp"
    if not valid:
        raise SocialVideoAssetDenied("video content signature is unsupported")


class SocialVideoAssetBrokerV1:
    """Hold short-lived local paths outside the durable publication ledger."""

    def __init__(
        self,
        controlled_roots: tuple[Path, ...],
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not controlled_roots:
            raise SocialVideoAssetContractError("at least one controlled root is required")
        roots: list[Path] = []
        for root in controlled_roots:
            if not isinstance(root, Path) or not root.is_absolute():
                raise SocialVideoAssetContractError("controlled roots must be absolute Paths")
            resolved = root.resolve()
            if not resolved.is_dir():
                raise SocialVideoAssetContractError("controlled root is unavailable")
            roots.append(resolved)
        if type(max_bytes) is not int or not 1 <= max_bytes <= DEFAULT_MAX_BYTES:
            raise SocialVideoAssetContractError("max_bytes is outside its bound")
        self.controlled_roots = tuple(roots)
        self.max_bytes = max_bytes
        self._clock = clock
        self._leases: dict[str, _Lease] = {}

    def inspect(
        self,
        path: Path,
        *,
        workspace_id: str,
        principal_id: str,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
    ) -> VideoAssetDescriptorV1:
        workspace = _identifier(workspace_id, "workspace_id")
        principal = _identifier(principal_id, "principal_id")
        if not isinstance(path, Path) or not path.is_absolute():
            raise SocialVideoAssetContractError("video path must be an absolute Path")
        if not isinstance(lease_seconds, (int, float)) or isinstance(lease_seconds, bool):
            raise SocialVideoAssetContractError("lease_seconds must be numeric")
        if not 1.0 <= float(lease_seconds) <= 900.0:
            raise SocialVideoAssetContractError("lease_seconds is outside its bound")
        if _has_symlink(path, self.controlled_roots):
            raise SocialVideoAssetDenied("symlinked video paths are denied")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise SocialVideoAssetDenied("video path is unavailable") from exc
        if not _inside(resolved, self.controlled_roots):
            raise SocialVideoAssetDenied("video is outside the controlled roots")
        before = resolved.stat()
        if not stat.S_ISREG(before.st_mode):
            raise SocialVideoAssetDenied("video asset must be a regular file")
        if before.st_size <= 0 or before.st_size > self.max_bytes:
            raise SocialVideoAssetDenied("video size is outside the configured bound")
        expected_mime = _VIDEO_TYPES.get(resolved.suffix.lower())
        guessed_mime = mimetypes.guess_type(resolved.name)[0]
        if expected_mime is None or guessed_mime != expected_mime:
            raise SocialVideoAssetDenied("video type is unsupported or ambiguous")
        _validate_signature(resolved, expected_mime)
        digest = _sha256(resolved, self.max_bytes)
        after = resolved.stat()
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if identity_before != identity_after:
            raise SocialVideoAssetDenied("video changed while it was inspected")
        lease_id = "video_" + secrets.token_hex(16)
        descriptor = VideoAssetDescriptorV1(
            contract="OnyxSocialVideoAsset.v1",
            lease_id=lease_id,
            workspace_id=workspace,
            principal_id=principal,
            sha256=digest,
            size_bytes=after.st_size,
            mime_type=expected_mime,
            expires_at=self._clock() + float(lease_seconds),
            status="ready",
        )
        self._leases[lease_id] = _Lease(
            descriptor=descriptor,
            path=resolved,
            device=after.st_dev,
            inode=after.st_ino,
            modified_ns=after.st_mtime_ns,
        )
        return descriptor

    def resolve(
        self,
        binding: str,
        *,
        workspace_id: str,
        principal_id: str,
    ) -> VideoAssetDispatchV1:
        workspace = _identifier(workspace_id, "workspace_id")
        principal = _identifier(principal_id, "principal_id")
        if type(binding) is not str:
            raise SocialVideoAssetContractError("video binding must be text")
        parts = binding.split(":")
        if len(parts) != 5 or parts[0] != "onyx-video-v1":
            raise SocialVideoAssetContractError("video binding is invalid")
        _, expected_digest, size_text, expected_mime, lease_id = parts
        lease = self._leases.get(lease_id)
        if lease is None:
            raise SocialVideoAssetDenied("video lease is unavailable or was not restored")
        descriptor = lease.descriptor
        if descriptor.workspace_id != workspace or descriptor.principal_id != principal:
            raise SocialVideoAssetDenied("video lease scope does not match")
        if self._clock() >= descriptor.expires_at:
            self._leases.pop(lease_id, None)
            raise SocialVideoAssetDenied("video lease expired")
        if expected_digest != descriptor.sha256 or expected_mime != descriptor.mime_type:
            raise SocialVideoAssetDenied("video binding drifted")
        try:
            expected_size = int(size_text)
        except ValueError as exc:
            raise SocialVideoAssetContractError("video binding size is invalid") from exc
        if expected_size != descriptor.size_bytes:
            raise SocialVideoAssetDenied("video binding drifted")
        if _has_symlink(lease.path, self.controlled_roots):
            raise SocialVideoAssetDenied("video path became symlinked")
        try:
            current = lease.path.stat()
        except OSError as exc:
            raise SocialVideoAssetDenied(
                "video changed after preview; consent is invalid"
            ) from exc
        identity = (current.st_dev, current.st_ino, current.st_mtime_ns)
        if identity != (lease.device, lease.inode, lease.modified_ns):
            raise SocialVideoAssetDenied("video changed after preview; consent is invalid")
        try:
            current_digest = _sha256(lease.path, self.max_bytes)
        except OSError as exc:
            raise SocialVideoAssetDenied(
                "video changed after preview; consent is invalid"
            ) from exc
        if current.st_size != descriptor.size_bytes or not hmac.compare_digest(
            current_digest, descriptor.sha256
        ):
            raise SocialVideoAssetDenied("video changed after preview; consent is invalid")
        return VideoAssetDispatchV1(descriptor=descriptor, local_path=lease.path)

    def revoke(self, lease_id: str) -> VideoAssetDescriptorV1:
        lease = self._leases.pop(_identifier(lease_id, "lease_id"), None)
        if lease is None:
            raise SocialVideoAssetDenied("video lease is unavailable")
        return VideoAssetDescriptorV1(
            **{
                **lease.descriptor.to_dict(),
                "status": "revoked",
            }
        )


__all__ = [
    "SocialVideoAssetBrokerV1",
    "SocialVideoAssetContractError",
    "SocialVideoAssetDenied",
    "VideoAssetDescriptorV1",
    "VideoAssetDispatchV1",
]
