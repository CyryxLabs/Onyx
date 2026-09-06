"""Governed scheduled opportunity monitoring and evidence digests for Onyx.

The monitor owns cadence, leases, source allowlists, freshness assessment and
contradiction flags. It never scores commercial viability, invents economics,
contacts anyone, publishes content, spends money or authorizes another tool.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Final, Sequence
from urllib.parse import urlparse

from core.web_opportunity_research_v1 import (
    ResearchEvidenceV1,
    WebOpportunityResearchV1,
)


SCHEMA: Final = "OnyxOpportunityMonitor.v1"
MIN_INTERVAL_SECONDS: Final = 15 * 60
MAX_INTERVAL_SECONDS: Final = 7 * 86_400
MAX_POLICIES: Final = 20
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_POSITIVE = frozenset(
    {"demand", "expand", "growth", "increase", "launch", "opportunity", "rising"}
)
_NEGATIVE = frozenset(
    {"ban", "contraction", "cut", "decline", "falling", "loss", "shutdown"}
)


class OpportunityMonitorV1Error(RuntimeError):
    pass


class OpportunityMonitorV1ContractError(ValueError):
    pass


class OpportunityMonitorV1Denied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class OpportunityMonitorPolicyV1:
    schedule_id: str
    query: str
    mode: str
    allowed_domains: tuple[str, ...]
    interval_seconds: int
    max_results: int
    max_runs_per_day: int
    max_age_hours: int
    enabled: bool
    next_due_at: int


@dataclass(frozen=True, slots=True)
class OpportunityEvidenceAssessmentV1:
    evidence: ResearchEvidenceV1
    freshness: str
    age_hours: int | None
    contradiction: bool


@dataclass(frozen=True, slots=True)
class OpportunityDigestV1:
    schema: str
    run_id: str
    schedule_id: str
    status: str
    query_sha256: str
    retrieved_at: int
    next_due_at: int
    assessments: tuple[OpportunityEvidenceAssessmentV1, ...]
    fresh_count: int
    stale_count: int
    contradiction_count: int
    promotion_authorized: bool = False
    external_action_authorized: bool = False


def _clean_text(value: object, label: str, maximum: int) -> str:
    if type(value) is not str:
        raise OpportunityMonitorV1ContractError(f"{label} must be text")
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > maximum or "\x00" in cleaned:
        raise OpportunityMonitorV1ContractError(f"{label} is invalid")
    return cleaned


def _domain(value: object) -> str:
    domain = _clean_text(value, "allowed domain", 253).rstrip(".").casefold()
    if (
        re.fullmatch(
            r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
            r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
            domain,
        )
        is None
    ):
        raise OpportunityMonitorV1ContractError("allowed domain is invalid")
    return domain


def _published_epoch(value: str | None) -> int | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.astimezone(timezone.utc).timestamp())


def _words(value: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]{3,}", value.casefold()))


def _contradictory_ids(evidence: Sequence[ResearchEvidenceV1]) -> frozenset[str]:
    marked: set[str] = set()
    for index, left in enumerate(evidence):
        left_words = _words(f"{left.title} {left.snippet}")
        left_positive = bool(left_words & _POSITIVE)
        left_negative = bool(left_words & _NEGATIVE)
        for right in evidence[index + 1 :]:
            right_words = _words(f"{right.title} {right.snippet}")
            opposite = (left_positive and bool(right_words & _NEGATIVE)) or (
                left_negative and bool(right_words & _POSITIVE)
            )
            shared_subject = len(
                (left_words - _POSITIVE - _NEGATIVE)
                & (right_words - _POSITIVE - _NEGATIVE)
            ) >= 2
            if opposite and shared_subject:
                marked.update((left.evidence_id, right.evidence_id))
    return frozenset(marked)


class OpportunityMonitorV1:
    """Persist bounded schedules and run only due, leased read-only research."""

    def __init__(
        self,
        path: Path | str,
        *,
        owner_profile_id: str,
        workspace_id: str,
        clock: Callable[[], int] = lambda: int(time.time()),
    ) -> None:
        self.owner_profile_id = _clean_text(owner_profile_id, "owner_profile_id", 128)
        self.workspace_id = _clean_text(workspace_id, "workspace_id", 128)
        if not callable(clock):
            raise OpportunityMonitorV1ContractError("clock is invalid")
        self._clock = clock
        self.path = Path(os.path.abspath(os.fspath(Path(path).expanduser())))
        cursor = Path(self.path.anchor)
        for part in self.path.parts[1:]:
            cursor /= part
            if cursor.exists() and cursor.is_symlink():
                raise OpportunityMonitorV1Denied("linked monitor storage is denied")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS monitor_policy(
                  schedule_id TEXT NOT NULL, owner_profile_id TEXT NOT NULL,
                  workspace_id TEXT NOT NULL, policy_json TEXT NOT NULL,
                  claim_until INTEGER NOT NULL DEFAULT 0,
                  PRIMARY KEY(schedule_id,owner_profile_id,workspace_id));
                CREATE TABLE IF NOT EXISTS monitor_run(
                  run_id TEXT PRIMARY KEY, schedule_id TEXT NOT NULL,
                  owner_profile_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
                  completed_at INTEGER NOT NULL, digest_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS monitor_control(
                  owner_profile_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
                  killed INTEGER NOT NULL, PRIMARY KEY(owner_profile_id,workspace_id));
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO monitor_control VALUES(?,?,0)",
                (self.owner_profile_id, self.workspace_id),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _now(self) -> int:
        value = self._clock()
        if type(value) is not int or value < 0:
            raise OpportunityMonitorV1Error("clock returned an invalid timestamp")
        return value

    def configure(
        self,
        *,
        schedule_id: object,
        query: object,
        allowed_domains: Sequence[str],
        interval_seconds: int = 21_600,
        mode: str = "news",
        max_results: int = 8,
        max_runs_per_day: int = 4,
        max_age_hours: int = 168,
        enabled: bool = True,
    ) -> OpportunityMonitorPolicyV1:
        identifier = _clean_text(schedule_id, "schedule_id", 80).casefold()
        if _ID.fullmatch(identifier) is None:
            raise OpportunityMonitorV1ContractError("schedule_id is invalid")
        clean_query = _clean_text(query, "query", 500)
        domains = tuple(sorted({_domain(item) for item in allowed_domains}))
        if not 1 <= len(domains) <= 16:
            raise OpportunityMonitorV1ContractError("allowed domains are outside their bound")
        if type(interval_seconds) is not int or not MIN_INTERVAL_SECONDS <= interval_seconds <= MAX_INTERVAL_SECONDS:
            raise OpportunityMonitorV1ContractError("interval is outside its bound")
        if mode not in {"search", "news"}:
            raise OpportunityMonitorV1ContractError("mode is invalid")
        if type(max_results) is not int or not 1 <= max_results <= 20:
            raise OpportunityMonitorV1ContractError("max_results is outside its bound")
        if type(max_runs_per_day) is not int or not 1 <= max_runs_per_day <= 24:
            raise OpportunityMonitorV1ContractError("daily run cap is invalid")
        if type(max_age_hours) is not int or not 1 <= max_age_hours <= 720:
            raise OpportunityMonitorV1ContractError("freshness window is invalid")
        if type(enabled) is not bool:
            raise OpportunityMonitorV1ContractError("enabled must be exact bool")
        now = self._now()
        policy = OpportunityMonitorPolicyV1(
            identifier, clean_query, mode, domains, interval_seconds, max_results,
            max_runs_per_day, max_age_hours, enabled, now,
        )
        payload = json.dumps(asdict(policy), sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM monitor_policy WHERE owner_profile_id=? AND workspace_id=?",
                (self.owner_profile_id, self.workspace_id),
            ).fetchone()[0]
            exists = connection.execute(
                "SELECT 1 FROM monitor_policy WHERE schedule_id=? AND owner_profile_id=? AND workspace_id=?",
                (identifier, self.owner_profile_id, self.workspace_id),
            ).fetchone()
            if not exists and count >= MAX_POLICIES:
                raise OpportunityMonitorV1Denied("monitor policy capacity is full")
            connection.execute(
                "INSERT INTO monitor_policy VALUES(?,?,?,?,0) ON CONFLICT(schedule_id,owner_profile_id,workspace_id) DO UPDATE SET policy_json=excluded.policy_json,claim_until=0",
                (identifier, self.owner_profile_id, self.workspace_id, payload),
            )
        return policy

    @staticmethod
    def _policy(row: sqlite3.Row) -> OpportunityMonitorPolicyV1:
        raw = json.loads(str(row["policy_json"]))
        raw["allowed_domains"] = tuple(raw["allowed_domains"])
        return OpportunityMonitorPolicyV1(**raw)

    def policies(self) -> tuple[OpportunityMonitorPolicyV1, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM monitor_policy WHERE owner_profile_id=? AND workspace_id=? ORDER BY schedule_id",
                (self.owner_profile_id, self.workspace_id),
            ).fetchall()
        return tuple(self._policy(row) for row in rows)

    def kill(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE monitor_control SET killed=1 WHERE owner_profile_id=? AND workspace_id=?",
                (self.owner_profile_id, self.workspace_id),
            )

    def resume(self) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE monitor_control SET killed=0 WHERE owner_profile_id=? AND workspace_id=?",
                (self.owner_profile_id, self.workspace_id),
            )

    def killed(self) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT killed FROM monitor_control WHERE owner_profile_id=? AND workspace_id=?",
                (self.owner_profile_id, self.workspace_id),
            ).fetchone()
        return row is None or int(row[0]) != 0

    def _claim_due(self, now: int) -> OpportunityMonitorPolicyV1 | None:
        if self.killed():
            return None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT * FROM monitor_policy WHERE owner_profile_id=? AND workspace_id=? AND claim_until<? ORDER BY schedule_id",
                (self.owner_profile_id, self.workspace_id, now),
            ).fetchall()
            for row in rows:
                policy = self._policy(row)
                if not policy.enabled or policy.next_due_at > now:
                    continue
                day_start = now - (now % 86_400)
                runs = connection.execute(
                    "SELECT COUNT(*) FROM monitor_run WHERE schedule_id=? AND owner_profile_id=? AND workspace_id=? AND completed_at>=?",
                    (policy.schedule_id, self.owner_profile_id, self.workspace_id, day_start),
                ).fetchone()[0]
                if runs >= policy.max_runs_per_day:
                    continue
                changed = connection.execute(
                    "UPDATE monitor_policy SET claim_until=? WHERE schedule_id=? AND owner_profile_id=? AND workspace_id=? AND claim_until<?",
                    (now + 300, policy.schedule_id, self.owner_profile_id, self.workspace_id, now),
                ).rowcount
                if changed == 1:
                    return policy
        return None

    def run_due(
        self, researcher: WebOpportunityResearchV1
    ) -> tuple[OpportunityDigestV1, ...]:
        if type(researcher) is not WebOpportunityResearchV1:
            raise OpportunityMonitorV1ContractError("exact researcher required")
        output: list[OpportunityDigestV1] = []
        while True:
            now = self._now()
            policy = self._claim_due(now)
            if policy is None:
                break
            try:
                receipt = researcher.research(
                    policy.query, mode=policy.mode, max_results=policy.max_results
                )
                evidence = tuple(
                    item
                    for item in receipt.evidence
                    if (urlparse(item.url).hostname or "").casefold()
                    in policy.allowed_domains
                )
                contradictions = _contradictory_ids(evidence)
                assessed: list[OpportunityEvidenceAssessmentV1] = []
                for item in evidence:
                    published = _published_epoch(item.published_at)
                    age = None if published is None else max(0, (now - published) // 3_600)
                    freshness = (
                        "unknown"
                        if age is None
                        else "fresh"
                        if age <= policy.max_age_hours
                        else "stale"
                    )
                    assessed.append(
                        OpportunityEvidenceAssessmentV1(
                            item, freshness, age, item.evidence_id in contradictions
                        )
                    )
                next_due = now + policy.interval_seconds
                digest = OpportunityDigestV1(
                    SCHEMA,
                    "run_" + uuid.uuid4().hex,
                    policy.schedule_id,
                    receipt.status,
                    receipt.query_sha256,
                    now,
                    next_due,
                    tuple(assessed),
                    sum(item.freshness == "fresh" for item in assessed),
                    sum(item.freshness == "stale" for item in assessed),
                    sum(item.contradiction for item in assessed),
                )
                serialized = json.dumps(
                    asdict(digest), ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                updated = OpportunityMonitorPolicyV1(
                    policy.schedule_id, policy.query, policy.mode,
                    policy.allowed_domains, policy.interval_seconds,
                    policy.max_results, policy.max_runs_per_day,
                    policy.max_age_hours, policy.enabled, next_due,
                )
                with self._connect() as connection:
                    connection.execute(
                        "INSERT INTO monitor_run VALUES(?,?,?,?,?,?)",
                        (digest.run_id, policy.schedule_id, self.owner_profile_id, self.workspace_id, now, serialized),
                    )
                    connection.execute(
                        "UPDATE monitor_policy SET policy_json=?,claim_until=0 WHERE schedule_id=? AND owner_profile_id=? AND workspace_id=?",
                        (json.dumps(asdict(updated), sort_keys=True, separators=(",", ":")), policy.schedule_id, self.owner_profile_id, self.workspace_id),
                    )
                output.append(digest)
            except BaseException:
                with self._connect() as connection:
                    connection.execute(
                        "UPDATE monitor_policy SET claim_until=0 WHERE schedule_id=? AND owner_profile_id=? AND workspace_id=?",
                        (policy.schedule_id, self.owner_profile_id, self.workspace_id),
                    )
                raise
        return tuple(output)

    def digests(self, *, limit: int = 20) -> tuple[dict[str, object], ...]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise OpportunityMonitorV1ContractError("digest limit is invalid")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT digest_json FROM monitor_run WHERE owner_profile_id=? AND workspace_id=? ORDER BY completed_at DESC,run_id DESC LIMIT ?",
                (self.owner_profile_id, self.workspace_id, limit),
            ).fetchall()
        return tuple(json.loads(str(row[0])) for row in rows)


__all__ = [
    "OpportunityDigestV1",
    "OpportunityEvidenceAssessmentV1",
    "OpportunityMonitorPolicyV1",
    "OpportunityMonitorV1",
    "OpportunityMonitorV1ContractError",
    "OpportunityMonitorV1Denied",
    "OpportunityMonitorV1Error",
    "SCHEMA",
]
