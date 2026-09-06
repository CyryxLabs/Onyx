"""Private, user-entered calorie and exercise tracking for Onyx."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Final, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


FEATURE_FLAG: Final = "ONYX_WELLNESS_TRACKER_V1"
MAX_CALORIES: Final = 20_000
MAX_EXERCISE_VALUE: Final = 86_400
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_UNITS = frozenset({"minutes", "seconds", "repetitions", "steps", "kilometers", "miles"})


class WellnessTrackerError(RuntimeError):
    pass


class WellnessTrackerDenied(PermissionError):
    pass


class OwnerScopeAdapterV1(Protocol):
    def allows_scope(self, owner_profile_id: str, workspace_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class WellnessEntryV1:
    entry_id: str
    kind: str
    owner_profile_id: str
    workspace_id: str
    occurred_at: str
    timezone: str
    value: float
    unit: str
    activity: str | None
    status: str
    source: str
    idempotency_key: str
    revision: int


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise WellnessTrackerDenied(f"{label} is invalid")
    return value


def _zone(value: object) -> ZoneInfo:
    if type(value) is not str:
        raise WellnessTrackerDenied("timezone must be a canonical IANA timezone")
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise WellnessTrackerDenied("timezone must be a canonical IANA timezone") from exc


def _timestamp(value: object) -> datetime:
    if type(value) is not str:
        raise WellnessTrackerDenied("occurred_at must be ISO 8601 text")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WellnessTrackerDenied("occurred_at must be valid ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WellnessTrackerDenied("occurred_at must include an offset")
    return parsed.astimezone(timezone.utc)


class WellnessTrackerStoreV1:
    LIMITATION = "User-entered tracking only; not medical advice or a verified health outcome."

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
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS wellness_entries(
                    entry_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    owner_profile_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL, timezone TEXT NOT NULL,
                    value REAL NOT NULL, unit TEXT NOT NULL, activity TEXT,
                    status TEXT NOT NULL, source TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL, revision INTEGER NOT NULL,
                    removed INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL,
                    UNIQUE(owner_profile_id,workspace_id,idempotency_key)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _scope(self, owner_profile_id: str, workspace_id: str) -> tuple[str, str]:
        owner = _identifier(owner_profile_id, "owner_profile_id")
        workspace = _identifier(workspace_id, "workspace_id")
        if self._owner_scope is not None and not self._owner_scope.allows_scope(owner, workspace):
            raise WellnessTrackerDenied("owner profile adapter denied scope")
        return owner, workspace

    def create_calorie(
        self, owner_profile_id: str, workspace_id: str, *, calories: float,
        occurred_at: str, timezone_name: str, idempotency_key: str,
        source: str = "user", confirmed: bool = True,
    ) -> WellnessEntryV1:
        return self._create(
            owner_profile_id, workspace_id, kind="calorie", value=calories,
            unit="kcal", activity=None, occurred_at=occurred_at,
            timezone_name=timezone_name, idempotency_key=idempotency_key,
            source=source, confirmed=confirmed,
        )

    def create_exercise(
        self, owner_profile_id: str, workspace_id: str, *, activity: str,
        value: float, unit: str, occurred_at: str, timezone_name: str,
        idempotency_key: str, source: str = "user", confirmed: bool = True,
    ) -> WellnessEntryV1:
        if type(activity) is not str or not (1 <= len(activity.strip()) <= 120):
            raise WellnessTrackerDenied("activity is empty or exceeds its bound")
        if unit not in _UNITS:
            raise WellnessTrackerDenied("exercise unit is unsupported")
        return self._create(
            owner_profile_id, workspace_id, kind="exercise", value=value,
            unit=unit, activity=activity.strip(), occurred_at=occurred_at,
            timezone_name=timezone_name, idempotency_key=idempotency_key,
            source=source, confirmed=confirmed,
        )

    def create_vision_estimate(
        self, owner_profile_id: str, workspace_id: str, *, kind: str,
        value: float, occurred_at: str, timezone_name: str, idempotency_key: str,
        activity: str | None = None, unit: str = "kcal",
    ) -> WellnessEntryV1:
        """Persist an uncertain model estimate as a non-counting draft."""
        if kind == "calorie":
            return self.create_calorie(
                owner_profile_id, workspace_id, calories=value, occurred_at=occurred_at,
                timezone_name=timezone_name, idempotency_key=idempotency_key,
                source="vision_estimate", confirmed=False,
            )
        if kind == "exercise" and activity is not None:
            return self.create_exercise(
                owner_profile_id, workspace_id, activity=activity, value=value, unit=unit,
                occurred_at=occurred_at, timezone_name=timezone_name,
                idempotency_key=idempotency_key, source="vision_estimate", confirmed=False,
            )
        raise WellnessTrackerDenied("vision estimate kind is unsupported")

    def _create(
        self, owner_profile_id: str, workspace_id: str, *, kind: str, value: float,
        unit: str, activity: str | None, occurred_at: str, timezone_name: str,
        idempotency_key: str, source: str, confirmed: bool,
    ) -> WellnessEntryV1:
        owner, workspace = self._scope(owner_profile_id, workspace_id)
        zone = _zone(timezone_name)
        moment = _timestamp(occurred_at)
        key = _identifier(idempotency_key, "idempotency_key")
        if type(value) not in {int, float} or isinstance(value, bool) or value <= 0:
            raise WellnessTrackerDenied("wellness value must be positive")
        maximum = MAX_CALORIES if kind == "calorie" else MAX_EXERCISE_VALUE
        if value > maximum:
            raise WellnessTrackerDenied("wellness value exceeds its bound")
        if source not in {"user", "vision_estimate", "sensor_estimate"}:
            raise WellnessTrackerDenied("wellness source is unsupported")
        if source != "user" and confirmed:
            raise WellnessTrackerDenied("derived values must remain drafts until confirmed")
        canonical = {
            "activity": activity, "kind": kind, "occurred_at": moment.isoformat(),
            "source": source, "timezone": zone.key, "unit": unit, "value": float(value),
        }
        digest = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
        entry_id = "well_" + digest[:24]
        status = "confirmed" if confirmed else "draft"
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO wellness_entries VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (entry_id, kind, owner, workspace, moment.isoformat(), zone.key,
                     float(value), unit, activity, status, source, key, 1, 0, self._clock()),
                )
        except sqlite3.IntegrityError:
            existing = self._by_key(owner, workspace, key)
            if existing is None or existing.entry_id != entry_id:
                raise WellnessTrackerDenied("idempotency key conflicts with another payload") from None
            return existing
        return self.get(entry_id, owner, workspace)

    def _by_key(self, owner: str, workspace: str, key: str) -> WellnessEntryV1 | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM wellness_entries WHERE owner_profile_id=? AND workspace_id=? "
                "AND idempotency_key=?", (owner, workspace, key),
            ).fetchone()
        return None if row is None else self._entry(row)

    def get(self, entry_id: str, owner_profile_id: str, workspace_id: str) -> WellnessEntryV1:
        owner, workspace = self._scope(owner_profile_id, workspace_id)
        _identifier(entry_id, "entry_id")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM wellness_entries WHERE entry_id=? AND owner_profile_id=? "
                "AND workspace_id=?", (entry_id, owner, workspace),
            ).fetchone()
        if row is None:
            raise WellnessTrackerDenied("wellness entry is unavailable in this scope")
        return self._entry(row)

    def list_entries(
        self, owner_profile_id: str, workspace_id: str, *, kind: str | None = None,
        include_drafts: bool = True,
    ) -> tuple[WellnessEntryV1, ...]:
        owner, workspace = self._scope(owner_profile_id, workspace_id)
        if kind not in {None, "calorie", "exercise"}:
            raise WellnessTrackerDenied("wellness kind is unsupported")
        query = "SELECT * FROM wellness_entries WHERE owner_profile_id=? AND workspace_id=? AND removed=0"
        values: list[object] = [owner, workspace]
        if kind is not None:
            query += " AND kind=?"
            values.append(kind)
        if not include_drafts:
            query += " AND status='confirmed'"
        query += " ORDER BY occurred_at,entry_id"
        with self._connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return tuple(self._entry(row) for row in rows)

    def confirm(self, entry_id: str, owner_profile_id: str, workspace_id: str) -> WellnessEntryV1:
        return self._update(entry_id, owner_profile_id, workspace_id, status="confirmed")

    def correct(
        self, entry_id: str, owner_profile_id: str, workspace_id: str, *,
        value: float, occurred_at: str | None = None, timezone_name: str | None = None,
        activity: str | None = None, unit: str | None = None,
    ) -> WellnessEntryV1:
        current = self.get(entry_id, owner_profile_id, workspace_id)
        maximum = MAX_CALORIES if current.kind == "calorie" else MAX_EXERCISE_VALUE
        if type(value) not in {int, float} or isinstance(value, bool) or not 0 < value <= maximum:
            raise WellnessTrackerDenied("corrected value is outside its bound")
        changes: dict[str, object] = {"value": float(value)}
        if occurred_at is not None:
            changes["occurred_at"] = _timestamp(occurred_at).isoformat()
        if timezone_name is not None:
            changes["timezone"] = _zone(timezone_name).key
        if current.kind == "exercise":
            if activity is not None:
                if not activity.strip() or len(activity.strip()) > 120:
                    raise WellnessTrackerDenied("activity is empty or exceeds its bound")
                changes["activity"] = activity.strip()
            if unit is not None:
                if unit not in _UNITS:
                    raise WellnessTrackerDenied("exercise unit is unsupported")
                changes["unit"] = unit
        return self._update(entry_id, owner_profile_id, workspace_id, **changes)

    def remove(self, entry_id: str, owner_profile_id: str, workspace_id: str) -> WellnessEntryV1:
        return self._update(entry_id, owner_profile_id, workspace_id, removed=1)

    def _update(
        self, entry_id: str, owner_profile_id: str, workspace_id: str, **changes: object
    ) -> WellnessEntryV1:
        current = self.get(entry_id, owner_profile_id, workspace_id)
        allowed = {"value", "occurred_at", "timezone", "activity", "unit", "status", "removed"}
        if not changes or not set(changes) <= allowed:
            raise WellnessTrackerDenied("wellness correction is invalid")
        assignments = ",".join(f"{name}=?" for name in changes)
        values = [*changes.values(), current.revision + 1, entry_id,
                  current.owner_profile_id, current.workspace_id, current.revision]
        with self._connect() as connection:
            changed = connection.execute(
                f"UPDATE wellness_entries SET {assignments},revision=? WHERE entry_id=? "
                "AND owner_profile_id=? AND workspace_id=? AND revision=?", values,
            ).rowcount
        if changed != 1:
            raise WellnessTrackerDenied("wellness entry changed concurrently")
        return self.get(entry_id, owner_profile_id, workspace_id)

    def totals(
        self, owner_profile_id: str, workspace_id: str, *, day: str,
        timezone_name: str,
    ) -> dict[str, object]:
        owner, workspace = self._scope(owner_profile_id, workspace_id)
        zone = _zone(timezone_name)
        try:
            local_day = datetime.strptime(day, "%Y-%m-%d").date()
        except (TypeError, ValueError) as exc:
            raise WellnessTrackerDenied("day must use YYYY-MM-DD") from exc
        start = datetime.combine(local_day, datetime.min.time(), zone).astimezone(timezone.utc)
        end = (datetime.combine(local_day, datetime.min.time(), zone) + timedelta(days=1)).astimezone(timezone.utc)
        entries = self.list_entries(owner, workspace, include_drafts=False)
        selected = [entry for entry in entries if start <= datetime.fromisoformat(entry.occurred_at) < end]
        exercise: dict[str, float] = {}
        calories = 0.0
        for entry in selected:
            if entry.kind == "calorie":
                calories += entry.value
            else:
                exercise[entry.unit] = exercise.get(entry.unit, 0.0) + entry.value
        return {
            "contract": "OnyxWellnessTotals.v1", "owner_profile_id": owner,
            "workspace_id": workspace, "day": day, "timezone": zone.key,
            "calories_kcal": calories, "exercise": exercise,
            "limitation": self.LIMITATION,
        }

    @staticmethod
    def _entry(row: sqlite3.Row) -> WellnessEntryV1:
        return WellnessEntryV1(
            str(row["entry_id"]), str(row["kind"]), str(row["owner_profile_id"]),
            str(row["workspace_id"]), str(row["occurred_at"]), str(row["timezone"]),
            float(row["value"]), str(row["unit"]), row["activity"],
            str(row["status"]), str(row["source"]), str(row["idempotency_key"]),
            int(row["revision"]),
        )


__all__ = [
    "WellnessEntryV1", "WellnessTrackerDenied", "WellnessTrackerError",
    "WellnessTrackerStoreV1",
]
