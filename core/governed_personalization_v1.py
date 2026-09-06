"""Workspace-bound, owner-governed personalization records.

Personalization is descriptive only.  It cannot represent or alter authority,
risk, account, credential, permission, or safety state.  Inferences remain
inactive until explicitly confirmed by the owner.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Final, Mapping


FEATURE_FLAG: Final = "ONYX_GOVERNED_PERSONALIZATION_V1"
SENSITIVE_FLAG: Final = "ONYX_GOVERNED_PERSONALIZATION_SENSITIVE_V1"
DEFAULT_FRESHNESS_SECONDS: Final = 90 * 86_400
MAX_VALUE_BYTES: Final = 32_768
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_KEY = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_SENSITIVITIES = frozenset({"public", "internal", "sensitive"})
_FORBIDDEN_KEY_PARTS = frozenset(
    {
        "account",
        "approval",
        "authority",
        "credential",
        "identity",
        "permission",
        "policy",
        "risk",
        "safety",
        "scope",
        "secret",
        "token",
    }
)


def _absolute_without_link_resolution(path: Path | str) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _reject_linked_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            if current.is_symlink():
                raise GovernedPersonalizationDenied(
                    "linked personalization storage is forbidden"
                )
        except OSError as exc:
            raise GovernedPersonalizationDenied(
                "personalization storage ancestry is unverifiable"
            ) from exc


class GovernedPersonalizationError(RuntimeError):
    """Base error for personalization storage and integrity failures."""


class GovernedPersonalizationContractError(ValueError):
    """Raised when an input violates the versioned record contract."""


class GovernedPersonalizationDenied(PermissionError):
    """Raised when a disabled feature or scope policy denies an operation."""


@dataclass(frozen=True, slots=True)
class PersonalizationFeatureGateV1:
    enabled: bool
    sensitive_enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool or type(self.sensitive_enabled) is not bool:
            raise GovernedPersonalizationContractError(
                "feature gates require exact booleans"
            )

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "PersonalizationFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(
            enabled=source.get(FEATURE_FLAG, "") == "true",
            sensitive_enabled=source.get(SENSITIVE_FLAG, "") == "true",
        )


@dataclass(frozen=True, slots=True)
class PersonalizationRecordV1:
    record_id: str
    owner_profile_id: str
    workspace_id: str
    preference_key: str
    value: object
    provenance: tuple[str, ...]
    sensitivity: str
    source: str
    status: str
    freshness: str
    created_at: float
    updated_at: float
    fresh_until: float
    revision: int

    def payload(self) -> dict[str, object]:
        return asdict(self)


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise GovernedPersonalizationContractError(f"{label} is invalid")
    return value


def _preference_key(value: object) -> str:
    if type(value) is not str or _KEY.fullmatch(value) is None:
        raise GovernedPersonalizationContractError("preference_key is invalid")
    parts = set(re.split(r"[._-]", value))
    if parts & _FORBIDDEN_KEY_PARTS:
        raise GovernedPersonalizationDenied(
            "personalization cannot affect authority, risk, account, or safety state"
        )
    return value


def _canonical_value(value: object) -> str:
    if value is None or isinstance(value, (bool, int, float, str, list, dict)) is False:
        raise GovernedPersonalizationContractError("value must be JSON compatible")
    if isinstance(value, float) and not math.isfinite(value):
        raise GovernedPersonalizationContractError("value contains a non-finite number")
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise GovernedPersonalizationContractError(
            "value must be canonical JSON"
        ) from exc
    if len(encoded.encode("utf-8")) > MAX_VALUE_BYTES:
        raise GovernedPersonalizationContractError("value exceeds its byte budget")
    if decoded != value:
        raise GovernedPersonalizationContractError("value is not stable canonical JSON")
    return encoded


def _provenance(value: object) -> tuple[str, ...]:
    if type(value) not in {tuple, list} or not value:
        raise GovernedPersonalizationContractError("provenance is required")
    if len(value) > 32 or any(
        type(item) is not str or not item.strip() for item in value
    ):
        raise GovernedPersonalizationContractError("provenance is invalid")
    normalized = tuple(item.strip() for item in value)
    if len(set(normalized)) != len(normalized):
        raise GovernedPersonalizationContractError("provenance must be unique")
    return normalized


class GovernedPersonalizationStoreV1:
    """SQLite record store bound to exactly one owner/workspace scope."""

    def __init__(
        self,
        path: Path | str,
        *,
        owner_profile_id: str,
        workspace_id: str,
        gate: PersonalizationFeatureGateV1 | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.gate = (
            PersonalizationFeatureGateV1.from_environ() if gate is None else gate
        )
        if type(self.gate) is not PersonalizationFeatureGateV1 or not self.gate.enabled:
            raise GovernedPersonalizationDenied("governed personalization is disabled")
        self.owner_profile_id = _identifier(owner_profile_id, "owner_profile_id")
        self.workspace_id = _identifier(workspace_id, "workspace_id")
        if not callable(clock):
            raise GovernedPersonalizationContractError("clock must be callable")
        self._clock = clock
        self.path = _absolute_without_link_resolution(path)
        _reject_linked_components(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _reject_linked_components(self.path)
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS personalization_records(
                    record_id TEXT PRIMARY KEY,
                    owner_profile_id TEXT NOT NULL,
                    workspace_id TEXT NOT NULL,
                    preference_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    provenance_json TEXT NOT NULL,
                    sensitivity TEXT NOT NULL CHECK(sensitivity IN ('public','internal','sensitive')),
                    source TEXT NOT NULL CHECK(source IN ('inferred','owner_confirmed')),
                    status TEXT NOT NULL CHECK(status IN ('inferred','confirmed','revoked')),
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    fresh_until REAL NOT NULL,
                    revision INTEGER NOT NULL CHECK(revision >= 1)
                );
                CREATE INDEX IF NOT EXISTS idx_personalization_scope
                    ON personalization_records(owner_profile_id,workspace_id,status,preference_key);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _scope(self, owner_profile_id: str | None, workspace_id: str | None) -> None:
        owner = (
            self.owner_profile_id
            if owner_profile_id is None
            else _identifier(owner_profile_id, "owner_profile_id")
        )
        workspace = (
            self.workspace_id
            if workspace_id is None
            else _identifier(workspace_id, "workspace_id")
        )
        if (owner, workspace) != (self.owner_profile_id, self.workspace_id):
            raise GovernedPersonalizationDenied(
                "cross-workspace personalization is denied"
            )

    def _now(self) -> float:
        value = self._clock()
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise GovernedPersonalizationError("clock returned an invalid timestamp")
        return float(value)

    def _record(self, row: sqlite3.Row) -> PersonalizationRecordV1:
        now = self._now()
        status = str(row["status"])
        freshness = (
            "revoked"
            if status == "revoked"
            else "fresh"
            if now <= float(row["fresh_until"])
            else "stale"
        )
        return PersonalizationRecordV1(
            record_id=str(row["record_id"]),
            owner_profile_id=str(row["owner_profile_id"]),
            workspace_id=str(row["workspace_id"]),
            preference_key=str(row["preference_key"]),
            value=json.loads(str(row["value_json"])),
            provenance=tuple(json.loads(str(row["provenance_json"]))),
            sensitivity=str(row["sensitivity"]),
            source=str(row["source"]),
            status=status,
            freshness=freshness,
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            fresh_until=float(row["fresh_until"]),
            revision=int(row["revision"]),
        )

    def _read(self, record_id: str) -> sqlite3.Row:
        key = _identifier(record_id, "record_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM personalization_records WHERE record_id=? AND owner_profile_id=? AND workspace_id=?",
                (key, self.owner_profile_id, self.workspace_id),
            ).fetchone()
        if row is None:
            raise GovernedPersonalizationDenied(
                "record is unavailable or cross-workspace"
            )
        if str(row["sensitivity"]) == "sensitive" and not self.gate.sensitive_enabled:
            raise GovernedPersonalizationDenied("sensitive personalization is disabled")
        return row

    def create(
        self,
        *,
        preference_key: str,
        value: object,
        provenance: tuple[str, ...] | list[str],
        sensitivity: str = "internal",
        inferred: bool = True,
        freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS,
        owner_profile_id: str | None = None,
        workspace_id: str | None = None,
    ) -> PersonalizationRecordV1:
        self._scope(owner_profile_id, workspace_id)
        key = _preference_key(preference_key)
        value_json = _canonical_value(value)
        sources = _provenance(provenance)
        if sensitivity not in _SENSITIVITIES:
            raise GovernedPersonalizationContractError("sensitivity is invalid")
        if sensitivity == "sensitive" and not self.gate.sensitive_enabled:
            raise GovernedPersonalizationDenied("sensitive personalization is disabled")
        if type(inferred) is not bool:
            raise GovernedPersonalizationContractError(
                "inferred must be an exact boolean"
            )
        if (
            type(freshness_seconds) is not int
            or not 1 <= freshness_seconds <= 365 * 86_400
        ):
            raise GovernedPersonalizationContractError(
                "freshness_seconds is outside its bound"
            )
        now = self._now()
        record_id = "pref_" + uuid.uuid4().hex
        source = "inferred" if inferred else "owner_confirmed"
        status = "inferred" if inferred else "confirmed"
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO personalization_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record_id,
                    self.owner_profile_id,
                    self.workspace_id,
                    key,
                    value_json,
                    json.dumps(sources),
                    sensitivity,
                    source,
                    status,
                    now,
                    now,
                    now + freshness_seconds,
                    1,
                ),
            )
        return self.inspect(record_id)

    def inspect(
        self,
        record_id: str | None = None,
        *,
        include_revoked: bool = False,
        owner_profile_id: str | None = None,
        workspace_id: str | None = None,
    ) -> PersonalizationRecordV1 | tuple[PersonalizationRecordV1, ...]:
        self._scope(owner_profile_id, workspace_id)
        if record_id is not None:
            return self._record(self._read(record_id))
        query = "SELECT * FROM personalization_records WHERE owner_profile_id=? AND workspace_id=?"
        parameters: list[object] = [self.owner_profile_id, self.workspace_id]
        if not include_revoked:
            query += " AND status!='revoked'"
        if not self.gate.sensitive_enabled:
            query += " AND sensitivity!='sensitive'"
        query += " ORDER BY created_at,record_id"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return tuple(self._record(row) for row in rows)

    def confirm(self, record_id: str) -> PersonalizationRecordV1:
        row = self._read(record_id)
        if str(row["status"]) != "inferred":
            raise GovernedPersonalizationDenied(
                "only an inferred record can be confirmed"
            )
        now = self._now()
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE personalization_records SET source='owner_confirmed',status='confirmed',updated_at=?,revision=revision+1 "
                "WHERE record_id=? AND status='inferred'",
                (now, record_id),
            ).rowcount
        if changed != 1:
            raise GovernedPersonalizationDenied("record changed during confirmation")
        return self.inspect(record_id)  # type: ignore[return-value]

    def edit(
        self,
        record_id: str,
        *,
        value: object,
        provenance: tuple[str, ...] | list[str],
        freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS,
    ) -> PersonalizationRecordV1:
        row = self._read(record_id)
        if str(row["status"]) == "revoked":
            raise GovernedPersonalizationDenied("revoked records cannot be edited")
        value_json = _canonical_value(value)
        sources = _provenance(provenance)
        if (
            type(freshness_seconds) is not int
            or not 1 <= freshness_seconds <= 365 * 86_400
        ):
            raise GovernedPersonalizationContractError(
                "freshness_seconds is outside its bound"
            )
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE personalization_records SET value_json=?,provenance_json=?,source='owner_confirmed',"
                "status='confirmed',updated_at=?,fresh_until=?,revision=revision+1 WHERE record_id=?",
                (
                    value_json,
                    json.dumps(sources),
                    now,
                    now + freshness_seconds,
                    record_id,
                ),
            )
        return self.inspect(record_id)  # type: ignore[return-value]

    def revoke(self, record_id: str) -> PersonalizationRecordV1:
        self._read(record_id)
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE personalization_records SET status='revoked',updated_at=?,revision=revision+1 WHERE record_id=?",
                (now, record_id),
            )
        return self.inspect(record_id)  # type: ignore[return-value]

    def export(self) -> dict[str, object]:
        records = self.inspect(include_revoked=True)
        assert isinstance(records, tuple)
        return {
            "contract": "OnyxGovernedPersonalization.v1",
            "owner_profile_id": self.owner_profile_id,
            "workspace_id": self.workspace_id,
            "records": [record.payload() for record in records],
        }

    def delete(self, record_id: str | None = None) -> int:
        with self._connect() as connection:
            if record_id is None:
                return connection.execute(
                    "DELETE FROM personalization_records WHERE owner_profile_id=? AND workspace_id=?",
                    (self.owner_profile_id, self.workspace_id),
                ).rowcount
            self._read(record_id)
            return connection.execute(
                "DELETE FROM personalization_records WHERE record_id=? AND owner_profile_id=? AND workspace_id=?",
                (record_id, self.owner_profile_id, self.workspace_id),
            ).rowcount


__all__ = [
    "DEFAULT_FRESHNESS_SECONDS",
    "FEATURE_FLAG",
    "GovernedPersonalizationContractError",
    "GovernedPersonalizationDenied",
    "GovernedPersonalizationError",
    "GovernedPersonalizationStoreV1",
    "PersonalizationFeatureGateV1",
    "PersonalizationRecordV1",
    "SENSITIVE_FLAG",
]
