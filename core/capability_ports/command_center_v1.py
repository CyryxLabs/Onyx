"""Provider-free, read-only A14 Command Center status projection."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from core.governance_nucleus_v1 import GovernanceV1ContractError, GovernanceV1Denied
from core.governed_capability_host_v1 import HostBoundCapabilityPortV1

OPERATIONS = frozenset({"status.query"})
SCHEMA = "OnyxCommandCenterProjection.v1"
MAX_ROWS = 100
MAX_INPUT_ROWS = 1_000
MAX_TEXT_BYTES = 512
DEFAULT_FRESHNESS_SECONDS = 300
_SECTIONS = ("capabilities", "missions", "evidence", "budgets")
_STATUS_ORDER = {
    "blocked": 0,
    "failed": 1,
    "uncertain": 2,
    "stale": 3,
    "running": 4,
    "queued": 5,
    "partial": 6,
    "verified": 7,
    "succeeded": 8,
    "default-off": 9,
    "unverified": 10,
    "unknown": 11,
}
_ALLOWED = {
    "capabilities": frozenset({"capability_id", "capability", "readiness", "status", "label"}),
    "missions": frozenset({"mission_id", "state", "status", "title", "step_count"}),
    "evidence": frozenset({"evidence_id", "status", "kind", "verified", "redacted"}),
    "budgets": frozenset({"budget_id", "status", "quota_micro", "used_micro", "remaining_micro"}),
}
_IDENTIFIERS = {
    "capabilities": ("capability_id", "capability"),
    "missions": ("mission_id",),
    "evidence": ("evidence_id",),
    "budgets": ("budget_id",),
}
_FORBIDDEN_KEY = re.compile(
    r"(?:secret|token|password|credential|api[_-]?key|content|payload|body|path|file|directory|root|callback|dispatch|control)",
    re.IGNORECASE,
)
_RAW_PATH = re.compile(r"(?:^[A-Za-z]:[\\/]|^\\\\|^/|(?:^|[\\/])\.\.(?:[\\/]|$))")


@dataclass(frozen=True, slots=True)
class _Source:
    section: str
    rows: tuple[Mapping[str, object], ...]


def _exact_text(value: object, field: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise GovernanceV1ContractError(f"command center {field} is invalid")
    if len(value.encode("utf-8")) > MAX_TEXT_BYTES:
        raise GovernanceV1ContractError(f"command center {field} exceeds its bound")
    return value


def _exact_integer(value: object, field: str) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 0:
        raise GovernanceV1ContractError(f"command center {field} is invalid")
    return value


class CommandCenterCapabilityPortV1(HostBoundCapabilityPortV1):
    """Deterministic projection over owner-injected immutable snapshot values.

    The adapter contains no loaders, callbacks, providers, or control surface.  It
    copies and validates every input during construction so later caller mutation
    cannot change the projected CLI-equivalent status.
    """

    def __init__(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        capability_snapshot: Sequence[Mapping[str, object]] = (),
        mission_snapshot: Sequence[Mapping[str, object]] = (),
        evidence_snapshot: Sequence[Mapping[str, object]] = (),
        budget_snapshot: Sequence[Mapping[str, object]] = (),
        composition_receipts: Sequence[Mapping[str, object]] = (),
        observed_at: int,
        freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS,
        max_rows: int = 50,
    ) -> None:
        super().__init__()
        self._principal_id = _exact_text(principal_id, "principal_id")
        self._workspace_id = _exact_text(workspace_id, "workspace_id")
        self._observed_at = _exact_integer(observed_at, "observed_at")
        self._freshness_seconds = _exact_integer(freshness_seconds, "freshness_seconds")
        if not 1 <= freshness_seconds <= 86_400:
            raise GovernanceV1ContractError("command center freshness is out of bounds")
        if type(max_rows) is not int or isinstance(max_rows, bool) or not 1 <= max_rows <= MAX_ROWS:
            raise GovernanceV1ContractError("command center row bound is overbroad")
        self._max_rows = max_rows
        self._receipts = self._copy_receipts(composition_receipts)
        raw_sources = (
            ("capabilities", capability_snapshot),
            ("missions", mission_snapshot),
            ("evidence", evidence_snapshot),
            ("budgets", budget_snapshot),
        )
        self._sources = tuple(
            _Source(section, self._copy_rows(section, rows)) for section, rows in raw_sources
        )
        self._killed = False

    def _copy_receipts(
        self, receipts: Sequence[Mapping[str, object]]
    ) -> dict[str, tuple[str, str]]:
        if type(receipts) not in (tuple, list) or len(receipts) > MAX_INPUT_ROWS:
            raise GovernanceV1ContractError("command center receipts are overbroad")
        copied: dict[str, tuple[str, str]] = {}
        for raw in receipts:
            if not isinstance(raw, Mapping):
                raise GovernanceV1ContractError("command center receipt is invalid")
            receipt_id = _exact_text(raw.get("correlation_id"), "receipt correlation")
            principal = _exact_text(raw.get("principal_id"), "receipt principal")
            workspace = _exact_text(raw.get("workspace_id"), "receipt workspace")
            if principal != self._principal_id or workspace != self._workspace_id:
                raise GovernanceV1Denied("cross-workspace command center receipt denied")
            if receipt_id in copied:
                raise GovernanceV1ContractError("duplicate command center receipt")
            copied[receipt_id] = (principal, workspace)
        return copied

    def _copy_rows(
        self, section: str, rows: Sequence[Mapping[str, object]]
    ) -> tuple[Mapping[str, object], ...]:
        if type(rows) not in (tuple, list) or len(rows) > MAX_INPUT_ROWS:
            raise GovernanceV1ContractError("command center snapshot is overbroad")
        copied: list[Mapping[str, object]] = []
        for raw in rows:
            if not isinstance(raw, Mapping):
                raise GovernanceV1ContractError("command center snapshot row is invalid")
            row = dict(raw)
            if row.get("principal_id") != self._principal_id or row.get("workspace_id") != self._workspace_id:
                raise GovernanceV1Denied("cross-workspace command center snapshot denied")
            captured_at = _exact_integer(row.get("captured_at"), "captured_at")
            if captured_at > self._observed_at:
                raise GovernanceV1ContractError("command center snapshot is future-dated")
            correlation = _exact_text(row.get("receipt_correlation_id"), "receipt correlation")
            if correlation not in self._receipts:
                raise GovernanceV1Denied("command center receipt correlation mismatch")
            identifier = next((row.get(key) for key in _IDENTIFIERS[section] if row.get(key)), None)
            _exact_text(identifier, f"{section} identifier")
            copied.append(row)
        return tuple(copied)

    @staticmethod
    def _safe_scalar(value: object) -> object | None:
        if type(value) is str:
            if not value or "\x00" in value or len(value.encode("utf-8")) > MAX_TEXT_BYTES:
                return None
            if _RAW_PATH.search(value):
                return None
            return value
        if type(value) in (int, bool) or value is None:
            return value
        return None

    def _project_row(self, source: _Source, row: Mapping[str, object]) -> dict[str, object]:
        projected = {
            key: safe
            for key, value in row.items()
            if key in _ALLOWED[source.section]
            and not _FORBIDDEN_KEY.search(key)
            and (safe := self._safe_scalar(value)) is not None
        }
        age = self._observed_at - int(row["captured_at"])
        projected.update(
            receipt_correlation_id=str(row["receipt_correlation_id"]),
            captured_at=int(row["captured_at"]),
            age_seconds=age,
            stale=age > self._freshness_seconds,
            redacted=True,
        )
        return projected

    @staticmethod
    def _sort_key(row: Mapping[str, object]) -> tuple[object, ...]:
        status = str(row.get("state", row.get("status", row.get("readiness", "unknown")))).lower()
        identifier = next(
            (str(row[key]) for key in ("mission_id", "capability_id", "capability", "evidence_id", "budget_id") if key in row),
            "",
        )
        return (_STATUS_ORDER.get(status, len(_STATUS_ORDER)), identifier, str(row["receipt_correlation_id"]))

    def project(self, *, principal_id: str, workspace_id: str) -> dict[str, object]:
        """Return the same canonical state ordering intended for CLI status consumers."""
        if principal_id != self._principal_id or workspace_id != self._workspace_id:
            raise GovernanceV1Denied("cross-workspace command center query denied")
        if self._killed:
            raise GovernanceV1Denied("command center projection kill is latched")
        sections: dict[str, tuple[dict[str, object], ...]] = {}
        stale_sections: list[str] = []
        truncated = False
        remaining = self._max_rows
        for source in self._sources:
            ordered = sorted((self._project_row(source, row) for row in source.rows), key=self._sort_key)
            selected = tuple(ordered[:remaining])
            remaining -= len(selected)
            truncated = truncated or len(selected) != len(ordered)
            sections[source.section] = selected
            if any(row["stale"] for row in selected):
                stale_sections.append(source.section)
        cli_status = tuple(
            (
                section,
                tuple(
                    (
                        self._sort_key(row)[1],
                        str(
                            row.get(
                                "state",
                                row.get("status", row.get("readiness", "unknown")),
                            )
                        ),
                    )
                    for row in sections[section]
                ),
            )
            for section in _SECTIONS
        )
        return {
            "schema": SCHEMA,
            "principal_id": self._principal_id,
            "workspace_id": self._workspace_id,
            "observed_at": self._observed_at,
            "sections": sections,
            "cli_status": cli_status,
            "row_count": self._max_rows - remaining,
            "truncated": truncated,
            "stale": bool(stale_sections),
            "stale_sections": tuple(stale_sections),
            "provenance_correlations": tuple(sorted(self._receipts)),
            "redacted": True,
            "read_only": True,
            "control_authorized": False,
            "dispatch_authorized": False,
        }

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object]) -> object:
        if operation != "status.query":
            raise GovernanceV1Denied("command center control operation denied")
        if type(arguments) is not dict or set(arguments) != {"principal_id", "workspace_id"}:
            raise GovernanceV1ContractError("command center query fields mismatch")
        return self.project(
            principal_id=arguments["principal_id"], workspace_id=arguments["workspace_id"]
        )

    def revoke(self, binding_id: str) -> None:
        _exact_text(binding_id, "binding_id")

    def kill(self) -> bool:
        self._killed = True
        return True


__all__ = [
    "DEFAULT_FRESHNESS_SECONDS",
    "MAX_INPUT_ROWS",
    "MAX_ROWS",
    "OPERATIONS",
    "SCHEMA",
    "CommandCenterCapabilityPortV1",
]
