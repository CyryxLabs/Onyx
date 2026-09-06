"""Default-off Argos world-intelligence registry (Argos V1).

First slice of Argos, the 100% proprietary Cyryx Labs world-intelligence
(successor to the dropped third-party World Monitor, from which nothing is
copied). It holds registered, rights-noted sources and categorized, scored
world signals as a pure deterministic, hermetic contract with a
deterministic brief projection. It calls no model, opens no network,
persists nothing and takes no action.

Governance is structural, not advisory:

* **Registered, rights-noted sources only.** Every signal references a
  registered `ArgosSourceV1`, and every source carries a `rights_note` —
  the license-honesty discipline applied at the data layer.
* **Closed taxonomies.** Signal categories and source kinds are closed
  vocabularies; unknown values are rejected, never coerced.
* **Injected time, bounded scores.** `observed_at` is an injected integer
  (no clock read); severity and confidence are each 1–5.
* **Argos informs, never acts.** `is_actionable()` is structurally False —
  a signal or score can never trigger an action (the accepted Phase 9
  rule, inherited verbatim).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

FEATURE_FLAG: Final = "ONYX_ARGOS_V1"
ENABLED_VALUE: Final = "true"
MAX_ITEMS: Final = 5_000
MAX_ID_BYTES: Final = 256
MAX_TEXT_BYTES: Final = 4_000
MAX_OBSERVED_AT: Final = 4_102_444_800  # 2100-01-01T00:00:00Z
MIN_SCORE: Final = 1
MAX_SCORE: Final = 5
MAX_BRIEF_LIMIT: Final = 100
ARGOS_CATEGORIES: Final = (
    "climate",
    "culture",
    "geopolitics",
    "health",
    "markets",
    "regulation",
    "security",
    "technology",
)
SOURCE_KINDS: Final = ("market_data", "official", "press", "social")
_CONSTRUCTION_KEY = object()

# The accepted Phase 9 exit four-file acceptance tuple.
ACCEPTED_PHASE9_EXIT_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase9-exit-candidate-v1/manifest.json",
        "c0e8105eceb011b5a0629df8d9ea5beb2588787833d6053cebee6f66bf66ee2d",
    ),
    (
        "docs/onyx/acceptance/VE-P9-EXIT-CANDIDATE-V1-E6-001.md",
        "d579582818877d2ba85824ae1b19b06b302ada9032e147e7de8f0efb5d304c31",
    ),
    (
        "docs/onyx/acceptance/VE-P9-EXIT-CANDIDATE-V1-E6-001.manifest.json",
        "7fe79fac2eec5f438e0d90d88e2a8a026aa715086e2fdbc75efda772d3bd174a",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P9-EXIT-CANDIDATE-V1-E6-001.sha256",
        "2024fc3768fa0e7b22e5ab78bdd05cf43822393513bde7d0998b164204fa88e2",
    ),
)


class ArgosV1Error(RuntimeError):
    pass


class ArgosV1ContractError(ValueError):
    pass


class ArgosV1Denied(PermissionError):
    pass


def _text(value: object, maximum: int, *, field_name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise ArgosV1ContractError(f"{field_name} contract violation")
    if len(value.encode("utf-8")) > maximum:
        raise ArgosV1ContractError(f"{field_name} contract violation")
    return value


def _integer(value: object, *, field_name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise ArgosV1ContractError(f"{field_name} contract violation")
    return value


def _sequence(value: object, *, field_name: str) -> tuple[object, ...]:
    if type(value) not in (list, tuple):
        raise ArgosV1ContractError(f"{field_name} must be a sequence")
    if len(value) > MAX_ITEMS:
        raise ArgosV1ContractError(f"{field_name} exceeds item cap")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class ArgosFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ArgosV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ArgosFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class ArgosSourceV1:
    source_id: str
    kind: str
    origin: str
    rights_note: str


@dataclass(frozen=True, slots=True)
class WorldSignalV1:
    signal_id: str
    category: str
    region: str
    headline: str
    source_id: str
    observed_at: int
    severity: int
    confidence: int

    @property
    def weight(self) -> int:
        return self.severity * self.confidence


@dataclass(frozen=True, slots=True)
class ArgosSnapshotV1:
    sources: tuple[ArgosSourceV1, ...]
    signals: tuple[WorldSignalV1, ...]


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_PHASE9_EXIT_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise ArgosV1Denied("accepted Phase 9 exit evidence unavailable") from exc
        if not hmac.compare_digest(actual, expected):
            raise ArgosV1Denied("accepted Phase 9 exit evidence drift")


class ArgosRegistryV1:
    """Deterministic, hermetic world-signal registry; informs, never acts."""

    __slots__ = ("_sources", "_signals")

    def __init__(self, *, construction_key: object) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise ArgosV1ContractError("use create_argos_registry_v1")
        self._sources: dict[str, ArgosSourceV1] = {}
        self._signals: dict[str, WorldSignalV1] = {}

    def _load_source(self, raw: object) -> ArgosSourceV1:
        if type(raw) is not dict or set(raw) != {
            "source_id",
            "kind",
            "origin",
            "rights_note",
        }:
            raise ArgosV1ContractError("source keys contract violation")
        kind = _text(raw["kind"], MAX_ID_BYTES, field_name="kind")
        if kind not in SOURCE_KINDS:
            raise ArgosV1ContractError("source kind is unknown")
        return ArgosSourceV1(
            source_id=_text(raw["source_id"], MAX_ID_BYTES, field_name="source_id"),
            kind=kind,
            origin=_text(raw["origin"], MAX_ID_BYTES, field_name="origin"),
            rights_note=_text(
                raw["rights_note"], MAX_TEXT_BYTES, field_name="rights_note"
            ),
        )

    def _load_signal(self, raw: object) -> WorldSignalV1:
        if type(raw) is not dict or set(raw) != {
            "signal_id",
            "category",
            "region",
            "headline",
            "source_id",
            "observed_at",
            "severity",
            "confidence",
        }:
            raise ArgosV1ContractError("signal keys contract violation")
        category = _text(raw["category"], MAX_ID_BYTES, field_name="category")
        if category not in ARGOS_CATEGORIES:
            raise ArgosV1ContractError("signal category is unknown")
        source_id = _text(raw["source_id"], MAX_ID_BYTES, field_name="source_id")
        if source_id not in self._sources:
            raise ArgosV1ContractError("signal references unregistered source")
        return WorldSignalV1(
            signal_id=_text(raw["signal_id"], MAX_ID_BYTES, field_name="signal_id"),
            category=category,
            region=_text(raw["region"], MAX_ID_BYTES, field_name="region"),
            headline=_text(raw["headline"], MAX_TEXT_BYTES, field_name="headline"),
            source_id=source_id,
            observed_at=_integer(
                raw["observed_at"], field_name="observed_at",
                minimum=0, maximum=MAX_OBSERVED_AT,
            ),
            severity=_integer(
                raw["severity"], field_name="severity",
                minimum=MIN_SCORE, maximum=MAX_SCORE,
            ),
            confidence=_integer(
                raw["confidence"], field_name="confidence",
                minimum=MIN_SCORE, maximum=MAX_SCORE,
            ),
        )

    def build(self, plan: object) -> ArgosSnapshotV1:
        if type(plan) is not dict or set(plan) != {"sources", "signals"}:
            raise ArgosV1ContractError("plan keys contract violation")
        for raw in _sequence(plan["sources"], field_name="sources"):
            source = self._load_source(raw)
            if source.source_id in self._sources:
                raise ArgosV1ContractError("duplicate source_id")
            self._sources[source.source_id] = source
        for raw in _sequence(plan["signals"], field_name="signals"):
            signal = self._load_signal(raw)
            if signal.signal_id in self._signals:
                raise ArgosV1ContractError("duplicate signal_id")
            self._signals[signal.signal_id] = signal
        return ArgosSnapshotV1(
            sources=tuple(self._sources[key] for key in sorted(self._sources)),
            signals=tuple(self._signals[key] for key in sorted(self._signals)),
        )

    @staticmethod
    def _ranked(signals: list[WorldSignalV1]) -> tuple[WorldSignalV1, ...]:
        return tuple(
            sorted(signals, key=lambda signal: (-signal.weight, signal.signal_id))
        )

    def signals_for(self, category: str) -> tuple[WorldSignalV1, ...]:
        return self._ranked(
            [s for s in self._signals.values() if s.category == category]
        )

    def brief(self, limit: int) -> tuple[WorldSignalV1, ...]:
        bounded = _integer(
            limit, field_name="limit", minimum=1, maximum=MAX_BRIEF_LIMIT
        )
        return self._ranked(list(self._signals.values()))[:bounded]

    def is_actionable(self, signal_id: str) -> bool:
        # Structurally False: Argos informs, it never acts. A signal or a
        # score can never trigger an action (the accepted Phase 9 rule).
        _ = signal_id
        return False


def create_argos_registry_v1(project_root: Path | str) -> ArgosRegistryV1:
    _verify_entry(project_root)
    return ArgosRegistryV1(construction_key=_CONSTRUCTION_KEY)


__all__ = [
    "FEATURE_FLAG",
    "ENABLED_VALUE",
    "ARGOS_CATEGORIES",
    "SOURCE_KINDS",
    "ArgosFeatureGateV1",
    "ArgosSourceV1",
    "WorldSignalV1",
    "ArgosSnapshotV1",
    "ArgosRegistryV1",
    "ArgosV1Error",
    "ArgosV1ContractError",
    "ArgosV1Denied",
    "create_argos_registry_v1",
]
