"""Explicit-gesture, local-only clipboard analysis for Onyx."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Final, Mapping, Protocol


FEATURE_FLAG: Final = "ONYX_CLIPBOARD_INTELLIGENCE_V1"
DEFAULT_MAX_BYTES: Final = 16_384
DEFAULT_RETENTION_SECONDS: Final = 900
DEFAULT_MAX_CACHED_PREVIEWS: Final = 128
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SECRET_PATTERNS: Final = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:sk|ghp|xox[baprs])[-_][A-Za-z0-9_-]{16,}\b"),
    re.compile(
        r"\b(?:password|passwd|secret|access[_ -]?token|api[_ -]?key)\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
)


class ClipboardIntelligenceError(RuntimeError):
    pass


class ClipboardIntelligenceDenied(PermissionError):
    pass


class OwnerScopeAdapterV1(Protocol):
    """Narrow adapter boundary; owner-profile modules remain authoritative."""

    def allows_scope(self, owner_profile_id: str, workspace_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class ClipboardConsentV1:
    owner_profile_id: str
    workspace_id: str
    enabled: bool
    paused: bool
    content_class: str
    retention_seconds: int


@dataclass(frozen=True, slots=True)
class ClipboardPreviewV1:
    snapshot_id: str
    owner_profile_id: str
    workspace_id: str
    content_class: str
    byte_count: int
    text: str
    created_at: float
    expires_at: float
    local_only: bool = True
    memory_authorized: bool = False
    provider_authorized: bool = False


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ClipboardIntelligenceDenied(f"{label} is invalid")
    return value


class ClipboardIntelligenceStoreV1:
    """Stores consent and bounded previews; it never observes the clipboard."""

    def __init__(
        self,
        path: Path | str,
        *,
        owner_scope: OwnerScopeAdapterV1 | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._owner_scope = owner_scope
        self._clock = clock
        self._preview_cache: dict[str, ClipboardPreviewV1] = {}
        self.background_workers = 0
        self.polling_interval = None
        rebuild_previews = False
        with self._connect() as connection:
            preview_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(clipboard_previews)"
                ).fetchall()
            }
            rebuild_previews = bool(preview_columns) and preview_columns != {
                "snapshot_id", "owner_profile_id", "workspace_id", "content_class",
                "byte_count", "content_digest", "created_at", "expires_at",
            }
            if rebuild_previews:
                connection.execute("PRAGMA journal_mode=DELETE")
                connection.execute("DROP TABLE clipboard_previews")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS clipboard_consent(
                    owner_profile_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL, paused INTEGER NOT NULL,
                    content_class TEXT NOT NULL, retention_seconds INTEGER NOT NULL,
                    PRIMARY KEY(owner_profile_id, workspace_id)
                );
                CREATE TABLE IF NOT EXISTS clipboard_previews(
                    snapshot_id TEXT PRIMARY KEY, owner_profile_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL, content_class TEXT NOT NULL,
                    byte_count INTEGER NOT NULL, content_digest TEXT NOT NULL,
                    created_at REAL NOT NULL, expires_at REAL NOT NULL
                );
                """
            )
            # Preview content is process-local. Metadata without its cache entry is
            # unusable after restart and is removed fail-closed.
            connection.execute("DELETE FROM clipboard_previews")
        if rebuild_previews:
            # Reclaim pages so legacy raw text cannot remain in the database bytes.
            with self._connect() as connection:
                connection.execute("VACUUM")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _scope(self, owner_profile_id: str, workspace_id: str) -> tuple[str, str]:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        if self._owner_scope is not None and not self._owner_scope.allows_scope(owner, workspace):
            raise ClipboardIntelligenceDenied("owner profile adapter denied scope")
        return owner, workspace

    def opt_in(
        self,
        owner_profile_id: str,
        workspace_id: str,
        *,
        content_class: str = "text/plain",
        retention_seconds: int = DEFAULT_RETENTION_SECONDS,
    ) -> ClipboardConsentV1:
        owner, workspace = self._scope(owner_profile_id, workspace_id)
        if content_class != "text/plain":
            raise ClipboardIntelligenceDenied("only text/plain is supported")
        if type(retention_seconds) is not int or not 1 <= retention_seconds <= 86_400:
            raise ClipboardIntelligenceDenied("retention_seconds is outside its bound")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO clipboard_consent VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(owner_profile_id,workspace_id) DO UPDATE SET "
                "enabled=1,paused=0,content_class=excluded.content_class,"
                "retention_seconds=excluded.retention_seconds",
                (owner, workspace, 1, 0, content_class, retention_seconds),
            )
        return self.status(owner, workspace)

    def status(self, owner_profile_id: str, workspace_id: str) -> ClipboardConsentV1:
        owner, workspace = self._scope(owner_profile_id, workspace_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM clipboard_consent WHERE owner_profile_id=? AND workspace_id=?",
                (owner, workspace),
            ).fetchone()
        if row is None:
            return ClipboardConsentV1(
                owner, workspace, False, False, "text/plain", DEFAULT_RETENTION_SECONDS
            )
        return ClipboardConsentV1(
            owner,
            workspace,
            bool(row["enabled"]),
            bool(row["paused"]),
            str(row["content_class"]),
            int(row["retention_seconds"]),
        )

    def pause(self, owner_profile_id: str, workspace_id: str) -> ClipboardConsentV1:
        owner, workspace = self._scope(owner_profile_id, workspace_id)
        with self._connect() as connection:
            connection.execute(
                "UPDATE clipboard_consent SET paused=1 WHERE owner_profile_id=? AND workspace_id=?",
                (owner, workspace),
            )
        return self.status(owner, workspace)

    def revoke(self, owner_profile_id: str, workspace_id: str) -> ClipboardConsentV1:
        owner, workspace = self._scope(owner_profile_id, workspace_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM clipboard_previews WHERE owner_profile_id=? AND workspace_id=?",
                (owner, workspace),
            )
            connection.execute(
                "DELETE FROM clipboard_consent WHERE owner_profile_id=? AND workspace_id=?",
                (owner, workspace),
            )
        self._erase_cached_scope(owner, workspace)
        return self.status(owner, workspace)

    def clear(self, owner_profile_id: str, workspace_id: str) -> int:
        owner, workspace = self._scope(owner_profile_id, workspace_id)
        with self._connect() as connection:
            deleted = connection.execute(
                "DELETE FROM clipboard_previews WHERE owner_profile_id=? AND workspace_id=?",
                (owner, workspace),
            ).rowcount
        self._erase_cached_scope(owner, workspace)
        return deleted

    def _erase_cached_scope(self, owner: str, workspace: str) -> None:
        for snapshot_id, preview in tuple(self._preview_cache.items()):
            if (preview.owner_profile_id, preview.workspace_id) == (owner, workspace):
                del self._preview_cache[snapshot_id]

    def analyze_snapshot(
        self,
        owner_profile_id: str,
        workspace_id: str,
        reader: Callable[[], object],
        *,
        content_class: str = "text/plain",
        max_bytes: int = DEFAULT_MAX_BYTES,
        source_is_onyx_write: bool = False,
    ) -> ClipboardPreviewV1:
        """Read exactly once after this explicit call; never poll or subscribe."""
        owner, workspace = self._scope(owner_profile_id, workspace_id)
        consent = self.status(owner, workspace)
        if not consent.enabled or consent.paused:
            raise ClipboardIntelligenceDenied("clipboard analysis is disabled or paused")
        if source_is_onyx_write:
            raise ClipboardIntelligenceDenied("Onyx clipboard writes cannot be re-ingested")
        if content_class != consent.content_class or content_class != "text/plain":
            raise ClipboardIntelligenceDenied("clipboard content class is not consented")
        if type(max_bytes) is not int or not 1 <= max_bytes <= DEFAULT_MAX_BYTES:
            raise ClipboardIntelligenceDenied("max_bytes is outside its bound")
        value = reader()
        if type(value) is not str:
            raise ClipboardIntelligenceDenied("binary or unsupported clipboard content was ignored")
        encoded = value.encode("utf-8")
        if not value.strip() or len(encoded) > max_bytes:
            raise ClipboardIntelligenceDenied("clipboard content is empty or oversized")
        if any(pattern.search(value) for pattern in _SECRET_PATTERNS):
            raise ClipboardIntelligenceDenied("secret-like clipboard content was ignored")
        now = self._clock()
        self.expire(now=now)
        digest = hashlib.sha256(
            f"{owner}\0{workspace}\0{now}\0".encode() + encoded
        ).hexdigest()
        preview = ClipboardPreviewV1(
            "clip_" + digest[:24], owner, workspace, content_class,
            len(encoded), value, now, now + consent.retention_seconds,
        )
        if len(self._preview_cache) >= DEFAULT_MAX_CACHED_PREVIEWS:
            oldest = min(
                self._preview_cache.values(),
                key=lambda item: (item.created_at, item.snapshot_id),
            )
            del self._preview_cache[oldest.snapshot_id]
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM clipboard_previews WHERE snapshot_id=?",
                    (oldest.snapshot_id,),
                )
        self._preview_cache[preview.snapshot_id] = preview
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO clipboard_previews VALUES(?,?,?,?,?,?,?,?)",
                (preview.snapshot_id, owner, workspace, content_class,
                 preview.byte_count, digest, now, preview.expires_at),
            )
        return preview

    def list_previews(
        self, owner_profile_id: str, workspace_id: str
    ) -> tuple[ClipboardPreviewV1, ...]:
        owner, workspace = self._scope(owner_profile_id, workspace_id)
        self.expire()
        return tuple(
            sorted(
                (
                    preview
                    for preview in self._preview_cache.values()
                    if (preview.owner_profile_id, preview.workspace_id)
                    == (owner, workspace)
                ),
                key=lambda item: (item.created_at, item.snapshot_id),
            )
        )

    def expire(self, *, now: float | None = None) -> int:
        cutoff = self._clock() if now is None else now
        expired_ids = tuple(
            snapshot_id
            for snapshot_id, preview in self._preview_cache.items()
            if preview.expires_at <= cutoff
        )
        for snapshot_id in expired_ids:
            del self._preview_cache[snapshot_id]
        with self._connect() as connection:
            return connection.execute(
                "DELETE FROM clipboard_previews WHERE expires_at<=?", (cutoff,)
            ).rowcount


class StaticOwnerScopeAdapterV1:
    """CLI/test adapter that binds operations to one already-resolved owner scope."""

    def __init__(self, owner_profile_id: str, workspace_id: str) -> None:
        self.owner_profile_id = _identifier(owner_profile_id, "owner_profile_id")
        self.workspace_id = _identifier(workspace_id, "workspace_id")

    def allows_scope(self, owner_profile_id: str, workspace_id: str) -> bool:
        return (owner_profile_id, workspace_id) == (
            self.owner_profile_id,
            self.workspace_id,
        )


def status_payload(consent: ClipboardConsentV1) -> Mapping[str, object]:
    return {
        "contract": "OnyxClipboardIntelligence.v1",
        "status": "disabled" if not consent.enabled else "paused" if consent.paused else "enabled",
        "owner_profile_id": consent.owner_profile_id,
        "workspace_id": consent.workspace_id,
        "content_class": consent.content_class,
        "retention_seconds": consent.retention_seconds,
        "polling": False,
        "local_only": True,
    }


__all__ = [
    "ClipboardConsentV1", "ClipboardIntelligenceDenied", "ClipboardIntelligenceError",
    "ClipboardIntelligenceStoreV1", "ClipboardPreviewV1", "StaticOwnerScopeAdapterV1",
    "status_payload",
]
