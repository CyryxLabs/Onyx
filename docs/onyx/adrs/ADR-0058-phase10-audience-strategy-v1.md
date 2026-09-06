# ADR-0058 — Phase 10 audience research and strategy V1

## Status

Proposed (candidate E1–E5 complete, E6 pending).

## Context

Phase 10's strategy layer (PRD: audience/trend research, 30/60/90 strategy,
funnel/KPI, experiment ledger) was the next deterministic slice after the
accepted content-draft contract. Its PRD guards — no fabricated research, no
cross-platform metric equivalence, no winner claims from inadequate
samples — must be structural.

## Decision

Add `core/phase10_audience_strategy_v1.py`, default-off
(`ONYX_PHASE10_AUDIENCE_STRATEGY_V1`), deterministic, hermetic, entry-bound
to the accepted slice-4 four-file acceptance tuple, importing `PLATFORMS`
from slice 1. Structural gates: every research claim cites a `source_ref`
and every audience segment carries ≥1 claim; KPIs always name exactly one
platform with horizon ∈ {30, 60, 90}; strategy plans carry exactly the three
horizons with non-empty goals; funnel stages reference known KPIs with
unique order; experiments declare `min_sample ≥ 100` and
`winner_declared=True` requires `observed_sample ≥ min_sample`. Projections
only; no publish/schedule/action surface. The module calls no model, opens
no network, spawns no process, persists nothing and takes no action.

## Consequences

- Content and publishing decisions gain a strategy substrate that traces to
  cited evidence; later slices (scheduling/publishing, analytics) bind to
  it without inheriting invention risk.
- Any regression in the anti-fabrication, cadence, per-platform or
  sample-floor gates, the entry-bind or the cumulative gate fails the
  slice verifier.

## Alternatives considered

- Free-form horizons: rejected — the PRD names the 30/60/90 cadence; a
  key-set contract is the honest encoding.
- Cross-platform composite KPIs: rejected — the PRD forbids cross-platform
  metric equivalence; a KPI names one platform, always.
- Winner flags with warnings: rejected — an unsupported winner claim must
  be unrepresentable, not discouraged.
