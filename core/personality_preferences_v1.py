"""Owner-controlled, provenance-scored personality preference suggestions.

The model may submit evidence references and a bounded suggestion.  Suggestions
never become active by themselves: promotion and rollback require a host-owned
owner-authority callback.  Identity, safety, permissions, tools, providers and
voice configuration are intentionally outside the representable schema.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import stat
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Sequence

from core.phase6_agentic_core_v6 import normalized_sql_v6


SCHEMA_VERSION = 1
FEATURE_FLAG = "ONYX_PERSONALITY_PREFERENCES_V1"
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,191}")
_DIGEST = re.compile(r"[0-9a-f]{64}")


class PersonalityPreferenceError(RuntimeError):
    pass


class PersonalityPreferenceContractError(ValueError):
    pass


class PersonalityPreferenceDenied(PermissionError):
    pass


class PreferenceKeyV1(str, Enum):
    RESPONSE_DETAIL = "response_detail"
    CONVERSATION_TONE = "conversation_tone"
    INITIATIVE = "initiative"
    BRIEF_FORMAT = "brief_format"
    INTERRUPTION_STYLE = "interruption_style"


_ALLOWED_VALUES: dict[PreferenceKeyV1, frozenset[str]] = {
    PreferenceKeyV1.RESPONSE_DETAIL: frozenset({"concise", "balanced", "detailed"}),
    PreferenceKeyV1.CONVERSATION_TONE: frozenset({"direct", "warm", "formal"}),
    PreferenceKeyV1.INITIATIVE: frozenset({"reactive", "balanced", "proactive"}),
    PreferenceKeyV1.BRIEF_FORMAT: frozenset({"priorities_first", "timeline", "compact"}),
    PreferenceKeyV1.INTERRUPTION_STYLE: frozenset({"critical_only", "batched", "timely"}),
}


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise PersonalityPreferenceContractError(f"{label} is invalid")
    return value


def _canonical_json(value: object) -> str:
    try:
        result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise PersonalityPreferenceContractError("value is not canonical JSON") from exc
    if len(result.encode()) > 32_768:
        raise PersonalityPreferenceContractError("value exceeds its byte budget")
    return result


def _private_path(path: Path) -> None:
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise PersonalityPreferenceContractError("an explicit absolute database path is required")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise PersonalityPreferenceDenied("linked preference directory is forbidden")
    attributes = getattr(path.parent.stat(), "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if attributes & reparse:
        raise PersonalityPreferenceDenied("reparse-point preference directory is forbidden")
    if path.exists() and path.is_symlink():
        raise PersonalityPreferenceDenied("linked preference database is forbidden")


def _key(value: PreferenceKeyV1) -> PreferenceKeyV1:
    if type(value) is not PreferenceKeyV1:
        raise PersonalityPreferenceContractError("exact PreferenceKeyV1 is required")
    return value


def _preference_value(key: PreferenceKeyV1, value: object) -> str:
    selected = _key(key)
    if type(value) is not str or value not in _ALLOWED_VALUES[selected]:
        raise PersonalityPreferenceContractError("preference value is not allowlisted")
    return value


@dataclass(frozen=True)
class PersonalityPreferenceFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise PersonalityPreferenceContractError("enabled must be an exact boolean")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "PersonalityPreferenceFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True)
class PreferenceEvidenceV1:
    evidence_id: str
    source_type: str
    source_reference: str
    observation_digest: str
    occurred_at: float

    def __post_init__(self) -> None:
        _identifier(self.evidence_id, "evidence_id")
        _identifier(self.source_type, "source_type")
        _identifier(self.source_reference, "source_reference")
        if _DIGEST.fullmatch(self.observation_digest) is None:
            raise PersonalityPreferenceContractError("observation_digest is invalid")
        if (
            isinstance(self.occurred_at, bool)
            or not isinstance(self.occurred_at, (int, float))
            or not math.isfinite(self.occurred_at)
            or self.occurred_at <= 0
        ):
            raise PersonalityPreferenceContractError("occurred_at is invalid")


@dataclass(frozen=True)
class PreferenceSuggestionV1:
    suggestion_id: str
    owner_profile_id: str
    workspace_id: str
    key: PreferenceKeyV1
    suggested_value: str
    confidence: float
    evidence_count: int
    status: str
    revision: int


@dataclass(frozen=True)
class ActivePreferenceV1:
    owner_profile_id: str
    workspace_id: str
    key: PreferenceKeyV1
    value: str
    source_suggestion_id: str
    revision: int


class PersonalityPreferenceStoreV1:
    _DDL = (
        """CREATE TABLE metadata(schema_version INTEGER NOT NULL CHECK(schema_version=1))""",
        """CREATE TABLE suggestions(
          suggestion_id TEXT PRIMARY KEY,
          owner_profile_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL,
          preference_key TEXT NOT NULL CHECK(preference_key IN
            ('response_detail','conversation_tone','initiative','brief_format','interruption_style')),
          suggested_value TEXT NOT NULL,
          confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
          evidence_json TEXT NOT NULL,
          status TEXT NOT NULL CHECK(status IN ('pending','promoted','rejected','superseded')),
          revision INTEGER NOT NULL CHECK(revision>=1),
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL
        )""",
        """CREATE TABLE active_preferences(
          owner_profile_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL,
          preference_key TEXT NOT NULL,
          value TEXT NOT NULL,
          source_suggestion_id TEXT NOT NULL REFERENCES suggestions(suggestion_id),
          revision INTEGER NOT NULL CHECK(revision>=1),
          updated_at REAL NOT NULL,
          PRIMARY KEY(owner_profile_id,workspace_id,preference_key)
        )""",
        """CREATE TABLE preference_history(
          history_id TEXT PRIMARY KEY,
          owner_profile_id TEXT NOT NULL,
          workspace_id TEXT NOT NULL,
          preference_key TEXT NOT NULL,
          value TEXT,
          source_suggestion_id TEXT,
          revision INTEGER NOT NULL,
          action TEXT NOT NULL CHECK(action IN ('promote','rollback')),
          created_at REAL NOT NULL
        )""",
        """CREATE TABLE preference_events(
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          entity_id TEXT NOT NULL,
          timestamp REAL NOT NULL,
          event TEXT NOT NULL,
          detail_json TEXT NOT NULL,
          prev_hash TEXT NOT NULL,
          event_hash TEXT NOT NULL UNIQUE
        )""",
        """CREATE INDEX idx_suggestions_scope
          ON suggestions(owner_profile_id,workspace_id,status,preference_key)""",
        """CREATE TRIGGER preference_events_no_update BEFORE UPDATE ON preference_events
          BEGIN SELECT RAISE(ABORT,'preference events are immutable'); END""",
        """CREATE TRIGGER preference_events_no_delete BEFORE DELETE ON preference_events
          BEGIN SELECT RAISE(ABORT,'preference events are immutable'); END""",
    )

    def __init__(
        self,
        path: Path | str,
        gate: PersonalityPreferenceFeatureGateV1,
        *,
        owner_authority: Callable[[str, str, str, str], bool],
    ) -> None:
        if type(gate) is not PersonalityPreferenceFeatureGateV1 or not gate.enabled:
            raise PersonalityPreferenceDenied("personality preferences are disabled")
        if not callable(owner_authority):
            raise PersonalityPreferenceContractError("owner_authority must be callable")
        self.path = Path(path)
        _private_path(self.path)
        self._owner_authority = owner_authority
        self._lock = threading.RLock()
        self._expected_signature = self._build_expected_signature()
        self.initialize()

    @staticmethod
    def _signature(connection: sqlite3.Connection) -> str:
        objects = []
        for row in connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ):
            if row[3] is None:
                raise PersonalityPreferenceError("schema object has no stored SQL")
            objects.append((row[0], row[1], row[2], normalized_sql_v6(str(row[3]))))
        details: dict[str, object] = {}
        for table in sorted(row[1] for row in objects if row[0] == "table"):
            details[f"table_xinfo:{table}"] = [
                tuple(item) for item in connection.execute(f"PRAGMA table_xinfo('{table}')")
            ]
            details[f"foreign_key_list:{table}"] = [
                tuple(item)
                for item in connection.execute(f"PRAGMA foreign_key_list('{table}')")
            ]
        return hashlib.sha256(_canonical_json({"objects": objects, "details": details}).encode()).hexdigest()

    @classmethod
    def _build_expected_signature(cls) -> str:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            for statement in cls._DDL:
                connection.execute(statement)
            connection.execute("INSERT INTO metadata(schema_version) VALUES(1)")
            connection.execute("PRAGMA user_version=1")
            return cls._signature(connection)
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        _private_path(self.path)
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def initialize(self) -> None:
        with self._lock:
            connection = self._connect()
            try:
                count = int(connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                ).fetchone()[0])
                version = int(connection.execute("PRAGMA user_version").fetchone()[0])
                if count == 0 and version == 0:
                    connection.execute("BEGIN IMMEDIATE")
                    for statement in self._DDL:
                        connection.execute(statement)
                    connection.execute("INSERT INTO metadata(schema_version) VALUES(1)")
                    connection.execute("PRAGMA user_version=1")
                    connection.execute("COMMIT")
                if (
                    int(connection.execute("PRAGMA user_version").fetchone()[0]) != 1
                    or [tuple(row) for row in connection.execute("SELECT schema_version FROM metadata")] != [(1,)]
                    or self._signature(connection) != self._expected_signature
                    or connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or connection.execute("PRAGMA foreign_key_check").fetchall()
                ):
                    raise PersonalityPreferenceError("preference schema authentication failed")
            except BaseException:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            finally:
                connection.close()

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        entity_id: str,
        event: str,
        detail: Mapping[str, object],
    ) -> None:
        previous = connection.execute(
            "SELECT event_hash FROM preference_events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev_hash = "0" * 64 if previous is None else str(previous[0])
        timestamp = time.time()
        detail_json = _canonical_json(dict(detail))
        event_hash = hashlib.sha256(_canonical_json({
            "entity_id": entity_id,
            "timestamp": timestamp,
            "event": event,
            "detail_json": detail_json,
            "prev_hash": prev_hash,
        }).encode()).hexdigest()
        connection.execute(
            "INSERT INTO preference_events(entity_id,timestamp,event,detail_json,prev_hash,event_hash) "
            "VALUES(?,?,?,?,?,?)",
            (entity_id, timestamp, event, detail_json, prev_hash, event_hash),
        )

    def suggest(
        self,
        *,
        owner_profile_id: str,
        workspace_id: str,
        key: PreferenceKeyV1,
        value: str,
        evidence: Sequence[PreferenceEvidenceV1],
        now: float | None = None,
    ) -> PreferenceSuggestionV1:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        selected_key = _key(key)
        selected_value = _preference_value(selected_key, value)
        if type(evidence) not in {tuple, list} or not 3 <= len(evidence) <= 32:
            raise PersonalityPreferenceContractError("three to 32 evidence references are required")
        if any(type(item) is not PreferenceEvidenceV1 for item in evidence):
            raise PersonalityPreferenceContractError("evidence type is invalid")
        if len({item.evidence_id for item in evidence}) != len(evidence):
            raise PersonalityPreferenceContractError("evidence must be unique")
        if len({item.source_type for item in evidence}) < 2:
            raise PersonalityPreferenceContractError("evidence must have diverse provenance")
        timestamp = time.time() if now is None else float(now)
        if not math.isfinite(timestamp) or timestamp <= 0:
            raise PersonalityPreferenceContractError("now is invalid")
        recent = sum(1 for item in evidence if 0 <= timestamp - item.occurred_at <= 90 * 86400)
        diversity = len({item.source_type for item in evidence})
        confidence = min(0.95, round(0.40 + 0.07 * recent + 0.06 * diversity, 4))
        suggestion_id = "suggestion_" + uuid.uuid4().hex
        evidence_json = _canonical_json([
            {
                "evidence_id": item.evidence_id,
                "source_type": item.source_type,
                "source_reference": item.source_reference,
                "observation_digest": item.observation_digest,
                "occurred_at": item.occurred_at,
            }
            for item in evidence
        ])
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO suggestions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (suggestion_id, owner, workspace, selected_key.value, selected_value,
                 confidence, evidence_json, "pending", 1, timestamp, timestamp),
            )
            self._event(connection, suggestion_id, "preference.suggested", {
                "key": selected_key.value, "value": selected_value,
                "confidence": confidence, "evidence_count": len(evidence),
            })
            connection.execute("COMMIT")
        return PreferenceSuggestionV1(
            suggestion_id, owner, workspace, selected_key, selected_value,
            confidence, len(evidence), "pending", 1,
        )

    def get_suggestion(self, suggestion_id: str) -> PreferenceSuggestionV1:
        key = _identifier(suggestion_id, "suggestion_id")
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM suggestions WHERE suggestion_id=?", (key,)).fetchone()
        if row is None:
            raise PersonalityPreferenceError("suggestion is unknown")
        evidence = json.loads(str(row["evidence_json"]))
        return PreferenceSuggestionV1(
            key, str(row["owner_profile_id"]), str(row["workspace_id"]),
            PreferenceKeyV1(str(row["preference_key"])), str(row["suggested_value"]),
            float(row["confidence"]), len(evidence), str(row["status"]), int(row["revision"]),
        )

    def promote(self, suggestion_id: str) -> ActivePreferenceV1:
        suggestion = self.get_suggestion(suggestion_id)
        if suggestion.status != "pending":
            raise PersonalityPreferenceDenied("suggestion is not pending")
        decision_digest = hashlib.sha256(_canonical_json({
            "suggestion_id": suggestion.suggestion_id,
            "key": suggestion.key.value,
            "value": suggestion.suggested_value,
            "revision": suggestion.revision,
        }).encode()).hexdigest()
        allowed = self._owner_authority(
            suggestion.owner_profile_id, suggestion.workspace_id,
            suggestion.suggestion_id, decision_digest,
        )
        if type(allowed) is not bool or not allowed:
            raise PersonalityPreferenceDenied("owner authority denied promotion")
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM active_preferences WHERE owner_profile_id=? AND workspace_id=? "
                "AND preference_key=?",
                (suggestion.owner_profile_id, suggestion.workspace_id, suggestion.key.value),
            ).fetchone()
            revision = 1 if current is None else int(current["revision"]) + 1
            if current is not None:
                connection.execute(
                    "UPDATE suggestions SET status='superseded',revision=revision+1,updated_at=? "
                    "WHERE suggestion_id=?",
                    (now, str(current["source_suggestion_id"])),
                )
            connection.execute(
                "INSERT INTO active_preferences VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(owner_profile_id,workspace_id,preference_key) DO UPDATE SET "
                "value=excluded.value,source_suggestion_id=excluded.source_suggestion_id,"
                "revision=excluded.revision,updated_at=excluded.updated_at",
                (suggestion.owner_profile_id, suggestion.workspace_id, suggestion.key.value,
                 suggestion.suggested_value, suggestion.suggestion_id, revision, now),
            )
            promoted = connection.execute(
                "UPDATE suggestions SET status='promoted',revision=revision+1,updated_at=? "
                "WHERE suggestion_id=? AND status='pending'",
                (now, suggestion.suggestion_id),
            ).rowcount
            if promoted != 1:
                raise PersonalityPreferenceDenied("suggestion changed during promotion")
            connection.execute(
                "INSERT INTO preference_history VALUES(?,?,?,?,?,?,?,?,?)",
                ("history_" + uuid.uuid4().hex, suggestion.owner_profile_id,
                 suggestion.workspace_id, suggestion.key.value, suggestion.suggested_value,
                 suggestion.suggestion_id, revision, "promote", now),
            )
            self._event(connection, suggestion.suggestion_id, "preference.promoted", {
                "key": suggestion.key.value, "revision": revision,
                "decision_digest": decision_digest,
            })
            connection.execute("COMMIT")
        return ActivePreferenceV1(
            suggestion.owner_profile_id, suggestion.workspace_id, suggestion.key,
            suggestion.suggested_value, suggestion.suggestion_id, revision,
        )

    def reject(self, suggestion_id: str) -> PreferenceSuggestionV1:
        suggestion = self.get_suggestion(suggestion_id)
        decision_digest = hashlib.sha256(f"reject:{suggestion.suggestion_id}:{suggestion.revision}".encode()).hexdigest()
        if self._owner_authority(suggestion.owner_profile_id, suggestion.workspace_id,
                                 suggestion.suggestion_id, decision_digest) is not True:
            raise PersonalityPreferenceDenied("owner authority denied rejection")
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                "UPDATE suggestions SET status='rejected',revision=revision+1,updated_at=? "
                "WHERE suggestion_id=? AND status='pending'",
                (time.time(), suggestion.suggestion_id),
            ).rowcount
            if changed != 1:
                raise PersonalityPreferenceDenied("suggestion is not pending")
            self._event(connection, suggestion.suggestion_id, "preference.rejected", {})
            connection.execute("COMMIT")
        return self.get_suggestion(suggestion.suggestion_id)

    def rollback(self, owner_profile_id: str, workspace_id: str, key: PreferenceKeyV1) -> ActivePreferenceV1 | None:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        selected_key = _key(key)
        with self._connect() as connection:
            current = connection.execute(
                "SELECT * FROM active_preferences WHERE owner_profile_id=? AND workspace_id=? "
                "AND preference_key=?",
                (owner, workspace, selected_key.value),
            ).fetchone()
            if current is None:
                return None
            source_history = connection.execute(
                "SELECT revision FROM preference_history WHERE owner_profile_id=? "
                "AND workspace_id=? AND preference_key=? AND action='promote' "
                "AND source_suggestion_id=? ORDER BY revision DESC LIMIT 1",
                (owner, workspace, selected_key.value, str(current["source_suggestion_id"])),
            ).fetchone()
            if source_history is None:
                raise PersonalityPreferenceError("active preference has no promotion history")
            previous = connection.execute(
                "SELECT * FROM preference_history WHERE owner_profile_id=? AND workspace_id=? "
                "AND preference_key=? AND action='promote' AND revision<? "
                "ORDER BY revision DESC LIMIT 1",
                (owner, workspace, selected_key.value, int(source_history["revision"])),
            ).fetchone()
        if current is None:
            return None
        current_revision = int(current["revision"])
        decision_digest = hashlib.sha256(
            f"rollback:{owner}:{workspace}:{selected_key.value}:{current_revision}".encode()
        ).hexdigest()
        if self._owner_authority(owner, workspace, selected_key.value, decision_digest) is not True:
            raise PersonalityPreferenceDenied("owner authority denied rollback")
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if previous is None:
                changed = connection.execute(
                    "DELETE FROM active_preferences WHERE owner_profile_id=? AND workspace_id=? "
                    "AND preference_key=? AND revision=?",
                    (owner, workspace, selected_key.value, current_revision),
                ).rowcount
            else:
                changed = connection.execute(
                    "UPDATE active_preferences SET value=?,source_suggestion_id=?,revision=?,updated_at=? "
                    "WHERE owner_profile_id=? AND workspace_id=? AND preference_key=? AND revision=?",
                    (str(previous["value"]), str(previous["source_suggestion_id"]),
                     current_revision + 1, now, owner, workspace, selected_key.value,
                     current_revision),
                ).rowcount
            if changed != 1:
                raise PersonalityPreferenceDenied("active preference changed during rollback")
            connection.execute(
                "INSERT INTO preference_history VALUES(?,?,?,?,?,?,?,?,?)",
                ("history_" + uuid.uuid4().hex, owner, workspace, selected_key.value,
                 None if previous is None else str(previous["value"]),
                 None if previous is None else str(previous["source_suggestion_id"]),
                 current_revision + 1, "rollback", now),
            )
            self._event(connection, selected_key.value, "preference.rolled_back", {
                "revision": current_revision + 1,
            })
            connection.execute("COMMIT")
        return self.active(owner, workspace, selected_key)

    def active(
        self, owner_profile_id: str, workspace_id: str, key: PreferenceKeyV1
    ) -> ActivePreferenceV1 | None:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        selected_key = _key(key)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM active_preferences WHERE owner_profile_id=? AND workspace_id=? "
                "AND preference_key=?",
                (owner, workspace, selected_key.value),
            ).fetchone()
        if row is None:
            return None
        return ActivePreferenceV1(
            owner, workspace, selected_key, str(row["value"]),
            str(row["source_suggestion_id"]), int(row["revision"]),
        )

    def prompt_projection(self, owner_profile_id: str, workspace_id: str) -> str:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT preference_key,value,revision FROM active_preferences "
                "WHERE owner_profile_id=? AND workspace_id=? ORDER BY preference_key",
                (owner, workspace),
            ).fetchall()
        if not rows:
            return ""
        values = "; ".join(f"{row['preference_key']}={row['value']}" for row in rows)
        return f"Owner-approved interaction preferences: {values}. These affect style only."

    def active_count(self, owner_profile_id: str, workspace_id: str) -> int:
        """Return the number of owner-approved style preferences in one scope."""

        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) FROM active_preferences "
                "WHERE owner_profile_id=? AND workspace_id=?",
                (owner, workspace),
            ).fetchone()
        return int(row[0])
