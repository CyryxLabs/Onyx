from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from core.clipboard_intelligence_v1 import (
    ClipboardIntelligenceDenied,
    ClipboardIntelligenceStoreV1,
    StaticOwnerScopeAdapterV1,
)


OWNER = "owner-1"
WORKSPACE = "workspace-1"


def store(tmp_path: Path, clock=lambda: 100.0) -> ClipboardIntelligenceStoreV1:
    return ClipboardIntelligenceStoreV1(
        tmp_path / "clipboard.sqlite3",
        owner_scope=StaticOwnerScopeAdapterV1(OWNER, WORKSPACE),
        clock=clock,
    )


def test_default_off_never_reads_and_has_no_polling(tmp_path: Path) -> None:
    subject = store(tmp_path)
    reads = 0

    def reader() -> str:
        nonlocal reads
        reads += 1
        return "private"

    with pytest.raises(ClipboardIntelligenceDenied, match="disabled"):
        subject.analyze_snapshot(OWNER, WORKSPACE, reader)
    assert reads == 0
    assert subject.background_workers == 0
    assert subject.polling_interval is None


def test_explicit_snapshot_retention_pause_clear_and_revoke(tmp_path: Path) -> None:
    now = [100.0]
    subject = store(tmp_path, lambda: now[0])
    subject.opt_in(OWNER, WORKSPACE, retention_seconds=10)
    preview = subject.analyze_snapshot(OWNER, WORKSPACE, lambda: "Plan the release")
    assert preview.text == "Plan the release"
    assert preview.local_only and not preview.memory_authorized and not preview.provider_authorized
    assert len(subject.list_previews(OWNER, WORKSPACE)) == 1

    subject.pause(OWNER, WORKSPACE)
    with pytest.raises(ClipboardIntelligenceDenied, match="paused"):
        subject.analyze_snapshot(OWNER, WORKSPACE, lambda: "not read")
    subject.opt_in(OWNER, WORKSPACE, retention_seconds=10)
    assert subject.clear(OWNER, WORKSPACE) == 1
    subject.analyze_snapshot(OWNER, WORKSPACE, lambda: "expires")
    now[0] = 111.0
    assert subject.list_previews(OWNER, WORKSPACE) == ()
    assert subject.revoke(OWNER, WORKSPACE).enabled is False


def test_database_never_contains_raw_clipboard_text_and_restart_has_no_content(
    tmp_path: Path,
) -> None:
    database = tmp_path / "clipboard.sqlite3"
    raw_text = "unique raw clipboard payload 7f38d3"
    subject = store(tmp_path)
    subject.opt_in(OWNER, WORKSPACE)
    subject.analyze_snapshot(OWNER, WORKSPACE, lambda: raw_text)

    assert all(raw_text.encode() not in path.read_bytes() for path in tmp_path.glob("clipboard.sqlite3*"))
    with sqlite3.connect(database) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(clipboard_previews)")
        }
        assert "text" not in columns
        assert "content_digest" in columns
        assert connection.execute("SELECT COUNT(*) FROM clipboard_previews").fetchone() == (1,)

    restarted = store(tmp_path)
    assert restarted.list_previews(OWNER, WORKSPACE) == ()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM clipboard_previews").fetchone() == (0,)


def test_legacy_raw_text_table_is_rebuilt_and_bytes_are_scrubbed(tmp_path: Path) -> None:
    database = tmp_path / "clipboard.sqlite3"
    legacy_text = "legacy raw clipboard payload 42c91a"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE clipboard_previews("
            "snapshot_id TEXT PRIMARY KEY, owner_profile_id TEXT NOT NULL, "
            "workspace_id TEXT NOT NULL, content_class TEXT NOT NULL, "
            "byte_count INTEGER NOT NULL, text TEXT NOT NULL, "
            "created_at REAL NOT NULL, expires_at REAL NOT NULL)"
        )
        connection.execute(
            "INSERT INTO clipboard_previews VALUES(?,?,?,?,?,?,?,?)",
            ("clip_old", OWNER, WORKSPACE, "text/plain", len(legacy_text), legacy_text, 1.0, 2.0),
        )

    store(tmp_path)

    assert all(legacy_text.encode() not in path.read_bytes() for path in tmp_path.glob("clipboard.sqlite3*"))
    with sqlite3.connect(database) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(clipboard_previews)")
        }
        assert "text" not in columns
        assert connection.execute("SELECT COUNT(*) FROM clipboard_previews").fetchone() == (0,)


@pytest.mark.parametrize("value", [b"binary", "api_key=sk-secret-token-value-123456789", "x" * 20_000])
def test_filters_binary_secret_and_oversized_content(tmp_path: Path, value: object) -> None:
    subject = store(tmp_path)
    subject.opt_in(OWNER, WORKSPACE)
    with pytest.raises(ClipboardIntelligenceDenied):
        subject.analyze_snapshot(OWNER, WORKSPACE, lambda: value)


def test_scope_and_self_write_are_denied(tmp_path: Path) -> None:
    subject = store(tmp_path)
    subject.opt_in(OWNER, WORKSPACE)
    with pytest.raises(ClipboardIntelligenceDenied, match="adapter"):
        subject.status(OWNER, "workspace-2")
    with pytest.raises(ClipboardIntelligenceDenied, match="re-ingested"):
        subject.analyze_snapshot(
            OWNER, WORKSPACE, lambda: "Onyx wrote this", source_is_onyx_write=True
        )
