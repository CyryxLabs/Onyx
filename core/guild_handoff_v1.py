"""Default-off guild handoff and story contracts (Guild A9.2).

Second Onyx Engineering Guild slice. It encodes the AEXOS story-driven
development discipline as data: typed story contracts with the fixed
lifecycle, QA verdicts bound to the constitutional `quality_verdicts`
authority, the bounded QA loop, and compact bounded handoff artifacts —
validated against an A9.1 guild registry snapshot. It calls no model, opens
no network, spawns no process, persists nothing and takes no action.

Governance is structural, not advisory:

* **Fixed lifecycle.** `draft -> approved -> in_progress -> in_review ->
  done`, with the single loop edge `in_review -> in_progress`. Skipped
  stages and regressions are rejected; every story carries its full
  transition history and the history must land on its recorded status.
* **QA gate.** `done` requires at least one `approve` verdict and no
  `blocked` verdict; a verdict's reviewer must hold the constitutional
  `quality_verdicts` authority in the supplied registry snapshot; loop
  edges are covered by `reject` verdicts and rejects are capped (the AEXOS
  QA-loop maximum).
* **Bounded handoffs.** A handoff names two distinct existing roles and a
  known story, with at most five decisions, ten files and three blockers,
  a non-empty next action and a hard total byte budget — the AEXOS
  agent-handoff compaction rule as an invariant.
* **No execution.** Stories and handoffs describe; nothing here runs,
  schedules or dispatches. The workflow engine (A9.3) and every executable
  surface remain later, separately gated slices.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

from core.guild_profiles_v1 import GuildRegistrySnapshotV1

FEATURE_FLAG: Final = "ONYX_GUILD_HANDOFF_V1"
ENABLED_VALUE: Final = "true"
MAX_ITEMS: Final = 2_000
MAX_ID_BYTES: Final = 256
MAX_TEXT_BYTES: Final = 20_000
MAX_HANDOFF_BYTES: Final = 4_000
MAX_HANDOFF_DECISIONS: Final = 5
MAX_HANDOFF_FILES: Final = 10
MAX_HANDOFF_BLOCKERS: Final = 3
MAX_QA_REJECTS: Final = 5
STORY_STATUSES: Final = ("draft", "approved", "in_progress", "in_review", "done")
ALLOWED_TRANSITIONS: Final = frozenset(
    {
        ("draft", "approved"),
        ("approved", "in_progress"),
        ("in_progress", "in_review"),
        ("in_review", "done"),
        ("in_review", "in_progress"),
    }
)
QA_VERDICTS: Final = ("approve", "reject", "blocked")
QUALITY_VERDICT_OPERATION: Final = "quality_verdicts"
_CONSTRUCTION_KEY = object()

# The accepted Guild Profiles (A9.1) four-file acceptance tuple. Building a
# story ledger is denied unless this frozen predecessor evidence is byte-exact.
ACCEPTED_GUILD_PROFILES_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/guild-profiles-v1/manifest.json",
        "59987cbf6ce2c3ed27ffac0e40288b8df9f3c29a66f64e9ecccd39aff3bb132a",
    ),
    (
        "docs/onyx/acceptance/VE-GUILD-PROFILES-V1-E6-001.md",
        "f2eab1e05b0350c61f4327ab4d069b114f9b9644a3be0bfac81606ab6987855e",
    ),
    (
        "docs/onyx/acceptance/VE-GUILD-PROFILES-V1-E6-001.manifest.json",
        "d4a27650157d8ad95a37701db2ac08a37a2750c79312181f6f444efe9f7c5fdd",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-GUILD-PROFILES-V1-E6-001.sha256",
        "9e9c50c2b20c2b0634f8892298019c411656583ec81b5d158fb7dd9e24aae926",
    ),
)


class GuildHandoffV1Error(RuntimeError):
    pass


class GuildHandoffV1ContractError(ValueError):
    pass


class GuildHandoffV1Denied(PermissionError):
    pass


def _text(value: object, maximum: int, *, field_name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise GuildHandoffV1ContractError(f"{field_name} contract violation")
    if len(value.encode("utf-8")) > maximum:
        raise GuildHandoffV1ContractError(f"{field_name} contract violation")
    return value


def _sequence(value: object, *, field_name: str, maximum: int = MAX_ITEMS) -> tuple[object, ...]:
    if type(value) not in (list, tuple):
        raise GuildHandoffV1ContractError(f"{field_name} must be a sequence")
    if len(value) > maximum:
        raise GuildHandoffV1ContractError(f"{field_name} exceeds item cap")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class GuildHandoffFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise GuildHandoffV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "GuildHandoffFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class StoryContractV1:
    story_id: str
    epic_id: str
    title: str
    acceptance_criteria: tuple[str, ...]
    assigned_role_id: str
    status: str
    transition_history: tuple[str, ...]
    file_list: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class QaVerdictV1:
    story_id: str
    verdict: str
    reviewer_role_id: str


@dataclass(frozen=True, slots=True)
class HandoffArtifactV1:
    handoff_id: str
    story_id: str
    from_role_id: str
    to_role_id: str
    decisions: tuple[str, ...]
    files_modified: tuple[str, ...]
    blockers: tuple[str, ...]
    next_action: str


@dataclass(frozen=True, slots=True)
class GuildStoryLedgerSnapshotV1:
    stories: tuple[StoryContractV1, ...]
    verdicts: tuple[QaVerdictV1, ...]
    handoffs: tuple[HandoffArtifactV1, ...]


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_GUILD_PROFILES_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise GuildHandoffV1Denied(
                "accepted guild-profiles evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise GuildHandoffV1Denied("accepted guild-profiles evidence drift")


class GuildStoryLedgerV1:
    """Deterministic, hermetic story/verdict/handoff ledger with QA gates."""

    __slots__ = ("_stories", "_verdicts", "_handoffs")

    def __init__(self, *, construction_key: object) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise GuildHandoffV1ContractError("use create_guild_story_ledger_v1")
        self._stories: dict[str, StoryContractV1] = {}
        self._verdicts: dict[str, list[QaVerdictV1]] = {}
        self._handoffs: dict[str, HandoffArtifactV1] = {}

    def _load_story(self, raw: object, roles: frozenset[str]) -> StoryContractV1:
        if type(raw) is not dict or set(raw) != {
            "story_id",
            "epic_id",
            "title",
            "acceptance_criteria",
            "assigned_role_id",
            "status",
            "transition_history",
            "file_list",
        }:
            raise GuildHandoffV1ContractError("story keys contract violation")
        criteria: list[str] = []
        for item in _sequence(raw["acceptance_criteria"], field_name="acceptance_criteria"):
            criteria.append(_text(item, MAX_TEXT_BYTES, field_name="acceptance_criteria"))
        if not criteria:
            raise GuildHandoffV1ContractError("story has no acceptance criteria")
        assigned = _text(raw["assigned_role_id"], MAX_ID_BYTES, field_name="assigned_role_id")
        if assigned not in roles:
            raise GuildHandoffV1ContractError("story assigned to unknown role")
        status = _text(raw["status"], MAX_ID_BYTES, field_name="status")
        if status not in STORY_STATUSES:
            raise GuildHandoffV1ContractError("story status is unknown")
        history: list[str] = []
        for item in _sequence(raw["transition_history"], field_name="transition_history"):
            step = _text(item, MAX_ID_BYTES, field_name="transition_history")
            if step not in STORY_STATUSES:
                raise GuildHandoffV1ContractError("history status is unknown")
            history.append(step)
        if not history or history[0] != "draft":
            raise GuildHandoffV1ContractError("history must begin at draft")
        for earlier, later in zip(history, history[1:]):
            if (earlier, later) not in ALLOWED_TRANSITIONS:
                raise GuildHandoffV1ContractError("history transition is not allowed")
        if history[-1] != status:
            raise GuildHandoffV1ContractError("history does not land on status")
        files: list[str] = []
        for item in _sequence(raw["file_list"], field_name="file_list"):
            entry = _text(item, MAX_ID_BYTES, field_name="file_list")
            if entry in files:
                raise GuildHandoffV1ContractError("duplicate file_list entry")
            files.append(entry)
        return StoryContractV1(
            story_id=_text(raw["story_id"], MAX_ID_BYTES, field_name="story_id"),
            epic_id=_text(raw["epic_id"], MAX_ID_BYTES, field_name="epic_id"),
            title=_text(raw["title"], MAX_ID_BYTES, field_name="title"),
            acceptance_criteria=tuple(criteria),
            assigned_role_id=assigned,
            status=status,
            transition_history=tuple(history),
            file_list=tuple(files),
        )

    def _load_verdict(self, raw: object, qa_owners: tuple[str, ...]) -> QaVerdictV1:
        if type(raw) is not dict or set(raw) != {
            "story_id",
            "verdict",
            "reviewer_role_id",
        }:
            raise GuildHandoffV1ContractError("verdict keys contract violation")
        verdict = _text(raw["verdict"], MAX_ID_BYTES, field_name="verdict")
        if verdict not in QA_VERDICTS:
            raise GuildHandoffV1ContractError("verdict is unknown")
        reviewer = _text(
            raw["reviewer_role_id"], MAX_ID_BYTES, field_name="reviewer_role_id"
        )
        if reviewer not in qa_owners:
            raise GuildHandoffV1ContractError(
                "reviewer does not hold quality_verdicts authority"
            )
        story_id = _text(raw["story_id"], MAX_ID_BYTES, field_name="story_id")
        if story_id not in self._stories:
            raise GuildHandoffV1ContractError("verdict references unknown story")
        return QaVerdictV1(
            story_id=story_id, verdict=verdict, reviewer_role_id=reviewer
        )

    def _load_handoff(self, raw: object, roles: frozenset[str]) -> HandoffArtifactV1:
        if type(raw) is not dict or set(raw) != {
            "handoff_id",
            "story_id",
            "from_role_id",
            "to_role_id",
            "decisions",
            "files_modified",
            "blockers",
            "next_action",
        }:
            raise GuildHandoffV1ContractError("handoff keys contract violation")
        from_role = _text(raw["from_role_id"], MAX_ID_BYTES, field_name="from_role_id")
        to_role = _text(raw["to_role_id"], MAX_ID_BYTES, field_name="to_role_id")
        if from_role not in roles or to_role not in roles:
            raise GuildHandoffV1ContractError("handoff references unknown role")
        if from_role == to_role:
            raise GuildHandoffV1ContractError("self-handoff is rejected")
        story_id = _text(raw["story_id"], MAX_ID_BYTES, field_name="story_id")
        if story_id not in self._stories:
            raise GuildHandoffV1ContractError("handoff references unknown story")
        sections: dict[str, tuple[str, ...]] = {}
        for field_name, maximum in (
            ("decisions", MAX_HANDOFF_DECISIONS),
            ("files_modified", MAX_HANDOFF_FILES),
            ("blockers", MAX_HANDOFF_BLOCKERS),
        ):
            items: list[str] = []
            for item in _sequence(raw[field_name], field_name=field_name, maximum=maximum):
                items.append(_text(item, MAX_TEXT_BYTES, field_name=field_name))
            sections[field_name] = tuple(items)
        next_action = _text(raw["next_action"], MAX_TEXT_BYTES, field_name="next_action")
        total_bytes = len(next_action.encode("utf-8")) + sum(
            len(item.encode("utf-8"))
            for section in sections.values()
            for item in section
        )
        if total_bytes > MAX_HANDOFF_BYTES:
            raise GuildHandoffV1ContractError("handoff exceeds byte budget")
        return HandoffArtifactV1(
            handoff_id=_text(raw["handoff_id"], MAX_ID_BYTES, field_name="handoff_id"),
            story_id=story_id,
            from_role_id=from_role,
            to_role_id=to_role,
            decisions=sections["decisions"],
            files_modified=sections["files_modified"],
            blockers=sections["blockers"],
            next_action=next_action,
        )

    def build(
        self, registry: GuildRegistrySnapshotV1, plan: object
    ) -> GuildStoryLedgerSnapshotV1:
        if type(registry) is not GuildRegistrySnapshotV1:
            raise GuildHandoffV1ContractError(
                "registry must be an exact GuildRegistrySnapshotV1"
            )
        roles = frozenset(profile.role_id for profile in registry.profiles)
        qa_owners: tuple[str, ...] = ()
        for operation, owners in registry.matrix.exclusive_owners:
            if operation == QUALITY_VERDICT_OPERATION:
                qa_owners = owners
        if not qa_owners:
            raise GuildHandoffV1ContractError(
                "registry lacks quality_verdicts owners"
            )
        if type(plan) is not dict or set(plan) != {"stories", "verdicts", "handoffs"}:
            raise GuildHandoffV1ContractError("plan keys contract violation")

        for raw in _sequence(plan["stories"], field_name="stories"):
            story = self._load_story(raw, roles)
            if story.story_id in self._stories:
                raise GuildHandoffV1ContractError("duplicate story_id")
            self._stories[story.story_id] = story

        for raw in _sequence(plan["verdicts"], field_name="verdicts"):
            verdict = self._load_verdict(raw, qa_owners)
            self._verdicts.setdefault(verdict.story_id, []).append(verdict)

        for raw in _sequence(plan["handoffs"], field_name="handoffs"):
            handoff = self._load_handoff(raw, roles)
            if handoff.handoff_id in self._handoffs:
                raise GuildHandoffV1ContractError("duplicate handoff_id")
            self._handoffs[handoff.handoff_id] = handoff

        # QA gates per story: reject-covered loop edges, capped rejects,
        # approve-gated done, blocked stories stuck in review.
        for story in self._stories.values():
            verdicts = self._verdicts.get(story.story_id, [])
            rejects = sum(1 for v in verdicts if v.verdict == "reject")
            approves = sum(1 for v in verdicts if v.verdict == "approve")
            blocked = sum(1 for v in verdicts if v.verdict == "blocked")
            loop_edges = sum(
                1
                for earlier, later in zip(
                    story.transition_history, story.transition_history[1:]
                )
                if (earlier, later) == ("in_review", "in_progress")
            )
            if rejects > MAX_QA_REJECTS:
                raise GuildHandoffV1ContractError("QA reject cap exceeded")
            if loop_edges > rejects:
                raise GuildHandoffV1ContractError(
                    "review loop edge without a covering reject verdict"
                )
            if story.status == "done":
                if approves < 1:
                    raise GuildHandoffV1ContractError(
                        "done story without an approve verdict"
                    )
                if blocked:
                    raise GuildHandoffV1ContractError(
                        "done story carries a blocked verdict"
                    )
            if blocked and story.status != "in_review":
                raise GuildHandoffV1ContractError(
                    "blocked story must remain in review"
                )

        return GuildStoryLedgerSnapshotV1(
            stories=tuple(self._stories[key] for key in sorted(self._stories)),
            verdicts=tuple(
                verdict
                for key in sorted(self._verdicts)
                for verdict in self._verdicts[key]
            ),
            handoffs=tuple(self._handoffs[key] for key in sorted(self._handoffs)),
        )

    def story_status(self, story_id: str) -> str | None:
        story = self._stories.get(story_id)
        return None if story is None else story.status

    def qa_reject_count(self, story_id: str) -> int:
        return sum(
            1
            for verdict in self._verdicts.get(story_id, [])
            if verdict.verdict == "reject"
        )

    def is_done(self, story_id: str) -> bool:
        story = self._stories.get(story_id)
        return story is not None and story.status == "done"


def create_guild_story_ledger_v1(project_root: Path | str) -> GuildStoryLedgerV1:
    _verify_entry(project_root)
    return GuildStoryLedgerV1(construction_key=_CONSTRUCTION_KEY)


__all__ = [
    "FEATURE_FLAG",
    "ENABLED_VALUE",
    "STORY_STATUSES",
    "ALLOWED_TRANSITIONS",
    "QA_VERDICTS",
    "MAX_QA_REJECTS",
    "MAX_HANDOFF_BYTES",
    "GuildHandoffFeatureGateV1",
    "StoryContractV1",
    "QaVerdictV1",
    "HandoffArtifactV1",
    "GuildStoryLedgerSnapshotV1",
    "GuildStoryLedgerV1",
    "GuildHandoffV1Error",
    "GuildHandoffV1ContractError",
    "GuildHandoffV1Denied",
    "create_guild_story_ledger_v1",
]
