"""Workspace-bound, non-actionable opportunity candidate queue for Onyx."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Final, Sequence
from urllib.parse import urlparse

from core.opportunity_economics_v1 import OpportunityEconomicDecisionV1
from core.web_opportunity_research_v1 import ResearchEvidenceV1


SCHEMA: Final = "OnyxOpportunityQueue.v1"
MAX_EVIDENCE: Final = 32
_STATES: Final = frozenset({"candidate", "approved_review", "rejected", "revoked"})


class OpportunityQueueV1Error(RuntimeError):
    pass


class OpportunityQueueV1ContractError(ValueError):
    pass


class OpportunityQueueV1Denied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class OpportunityRecordV1:
    opportunity_id: str
    owner_profile_id: str
    workspace_id: str
    title: str
    score: int
    state: str
    evidence: tuple[ResearchEvidenceV1, ...]
    economics: OpportunityEconomicDecisionV1
    created_at: int
    expires_at: int
    independent_publishers: int
    promotion_eligible: bool
    actionable: bool = False


class OpportunityQueueV1:
    """Persist candidates; approval means review-ready, never action authority."""

    def __init__(
        self,
        path: Path | str,
        *,
        owner_profile_id: str,
        workspace_id: str,
        owner_approval_token: str,
        clock: Callable[[], int] = lambda: int(time.time()),
    ) -> None:
        for label, value in (
            ("owner_profile_id", owner_profile_id),
            ("workspace_id", workspace_id),
        ):
            if type(value) is not str or not value or len(value) > 128:
                raise OpportunityQueueV1ContractError(f"{label} is invalid")
        if type(owner_approval_token) is not str or len(owner_approval_token) < 16:
            raise OpportunityQueueV1ContractError("owner approval token is invalid")
        if not callable(clock):
            raise OpportunityQueueV1ContractError("clock is invalid")
        self.path = Path(os.path.abspath(os.fspath(Path(path).expanduser())))
        current = Path(self.path.anchor)
        for component in self.path.parts[1:]:
            current /= component
            if current.exists() and current.is_symlink():
                raise OpportunityQueueV1Denied("linked queue storage is denied")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        current = Path(self.path.anchor)
        for component in self.path.parts[1:]:
            current /= component
            if current.is_symlink():
                raise OpportunityQueueV1Denied("linked queue storage is denied")
        self.owner_profile_id = owner_profile_id
        self.workspace_id = workspace_id
        self._approval_digest = hashlib.sha256(owner_approval_token.encode()).digest()
        self._clock = clock
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS opportunities(
                opportunity_id TEXT PRIMARY KEY, owner_profile_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL, title TEXT NOT NULL, score INTEGER NOT NULL,
                state TEXT NOT NULL, evidence_json TEXT NOT NULL, economics_json TEXT NOT NULL,
                created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)"""
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _now(self) -> int:
        value = self._clock()
        if type(value) is not int or value < 0:
            raise OpportunityQueueV1Error("clock returned an invalid timestamp")
        return value

    @staticmethod
    def _publishers(evidence: Sequence[ResearchEvidenceV1]) -> int:
        return len({urlparse(item.url).hostname for item in evidence})

    @classmethod
    def _eligible(
        cls,
        evidence: Sequence[ResearchEvidenceV1],
        economics: OpportunityEconomicDecisionV1,
        score: int,
    ) -> bool:
        return (
            cls._publishers(evidence) >= 2
            and all(not item.instruction_signals for item in evidence)
            and economics.status == "verified"
            and economics.recommendation_eligible is True
            and score >= 60
        )

    def enqueue(
        self,
        *,
        title: str,
        score: int,
        evidence: Sequence[ResearchEvidenceV1],
        economics: OpportunityEconomicDecisionV1,
        ttl_seconds: int = 7 * 86_400,
    ) -> OpportunityRecordV1:
        if type(title) is not str or not title.strip() or len(title) > 512:
            raise OpportunityQueueV1ContractError("title is invalid")
        if type(score) is not int or not 0 <= score <= 100:
            raise OpportunityQueueV1ContractError("score is invalid")
        if (
            isinstance(evidence, (str, bytes))
            or not isinstance(evidence, Sequence)
            or not 1 <= len(evidence) <= MAX_EVIDENCE
            or any(type(item) is not ResearchEvidenceV1 for item in evidence)
        ):
            raise OpportunityQueueV1ContractError("evidence is invalid")
        if type(economics) is not OpportunityEconomicDecisionV1:
            raise OpportunityQueueV1ContractError("exact economics decision required")
        if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 90 * 86_400:
            raise OpportunityQueueV1ContractError("ttl is outside its bound")
        now = self._now()
        opportunity_id = "opp_" + uuid.uuid4().hex
        evidence_json = json.dumps(
            [asdict(item) for item in evidence],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        economics_json = json.dumps(
            asdict(economics), sort_keys=True, separators=(",", ":")
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO opportunities VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    opportunity_id,
                    self.owner_profile_id,
                    self.workspace_id,
                    title.strip(),
                    score,
                    "candidate",
                    evidence_json,
                    economics_json,
                    now,
                    now + ttl_seconds,
                ),
            )
        return self.inspect(opportunity_id)

    def _record(self, row: sqlite3.Row) -> OpportunityRecordV1:
        evidence = tuple(
            ResearchEvidenceV1(**item) for item in json.loads(row["evidence_json"])
        )
        economics = OpportunityEconomicDecisionV1(
            **json.loads(row["economics_json"])
        )
        state = str(row["state"])
        if state not in _STATES:
            raise OpportunityQueueV1Denied("queue state drift")
        return OpportunityRecordV1(
            str(row["opportunity_id"]),
            str(row["owner_profile_id"]),
            str(row["workspace_id"]),
            str(row["title"]),
            int(row["score"]),
            state,
            evidence,
            economics,
            int(row["created_at"]),
            int(row["expires_at"]),
            self._publishers(evidence),
            self._eligible(evidence, economics, int(row["score"])),
        )

    def inspect(self, opportunity_id: str | None = None) -> OpportunityRecordV1 | tuple[OpportunityRecordV1, ...]:
        with self._connect() as connection:
            if opportunity_id is None:
                rows = connection.execute(
                    "SELECT * FROM opportunities WHERE owner_profile_id=? AND workspace_id=? ORDER BY created_at,opportunity_id",
                    (self.owner_profile_id, self.workspace_id),
                ).fetchall()
                return tuple(self._record(row) for row in rows)
            row = connection.execute(
                "SELECT * FROM opportunities WHERE opportunity_id=? AND owner_profile_id=? AND workspace_id=?",
                (opportunity_id, self.owner_profile_id, self.workspace_id),
            ).fetchone()
        if row is None:
            raise OpportunityQueueV1Denied("opportunity is unavailable")
        return self._record(row)

    def approve_for_review(
        self, opportunity_id: str, *, owner_approval_token: str
    ) -> OpportunityRecordV1:
        record = self.inspect(opportunity_id)
        assert isinstance(record, OpportunityRecordV1)
        if record.state != "candidate" or self._now() >= record.expires_at:
            raise OpportunityQueueV1Denied("candidate is not active")
        if type(owner_approval_token) is not str:
            raise OpportunityQueueV1Denied("owner approval is invalid")
        supplied = hashlib.sha256(owner_approval_token.encode()).digest()
        if not hmac.compare_digest(supplied, self._approval_digest):
            raise OpportunityQueueV1Denied("owner approval is invalid")
        if not record.promotion_eligible:
            raise OpportunityQueueV1Denied("candidate failed promotion gates")
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE opportunities SET state='approved_review' WHERE opportunity_id=? AND state='candidate'",
                (opportunity_id,),
            ).rowcount
        if changed != 1:
            raise OpportunityQueueV1Denied("candidate changed during approval")
        return self.inspect(opportunity_id)  # type: ignore[return-value]

    def revoke(self, opportunity_id: str) -> OpportunityRecordV1:
        self.inspect(opportunity_id)
        with self._connect() as connection:
            connection.execute(
                "UPDATE opportunities SET state='revoked' WHERE opportunity_id=?",
                (opportunity_id,),
            )
        return self.inspect(opportunity_id)  # type: ignore[return-value]


__all__ = [
    "OpportunityQueueV1",
    "OpportunityQueueV1ContractError",
    "OpportunityQueueV1Denied",
    "OpportunityQueueV1Error",
    "OpportunityRecordV1",
    "SCHEMA",
]
