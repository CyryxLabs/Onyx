# Story ONYX-P10-AUDIENCE-STRATEGY-V1 — Audience Research & 30/60/90 Strategy V1

**Status:** Done (accepted 2026-08-19, `VE-P10-AUDIENCE-STRATEGY-V1-E6-001`,
root `81199863…`; acceptance verifier reproduced the full 32-file gate
833/0/0/17/96; autonomous-session honesty boundary recorded; matrix/ledger
updates batched into the V54 pass)
**Epic:** Phase 10 — Social organic OS (slice 5, plan item A20)
**Predecessor:** `VE-P10-CONTENT-DRAFT-V1-E6-001` (slice 4, root `59308ada…`,
reproduced through the current-successor chain)

## Story

As the Cyryx Labs owner, I want Onyx to hold **cited audience research,
30/60/90 strategy plans, per-platform funnels/KPIs and a sample-floored
experiment ledger** — the strategy layer of the social organic OS — with the
PRD's anti-fabrication guards enforced structurally, so content and
publishing decisions later trace to evidence, never invention.

## Design

Module `core/phase10_audience_strategy_v1.py`, flag
`ONYX_PHASE10_AUDIENCE_STRATEGY_V1`, default-off, deterministic, hermetic;
entry-bound to the slice-4 four-file acceptance tuple; imports `PLATFORMS`
from slice 1.

- `ResearchClaimV1`: every claim cites a `source_ref` (no uncited research);
  platform-scoped.
- `AudienceSegmentV1`: brand-scoped, platform ∈ PLATFORMS, must carry ≥1
  research claim — audiences cannot be invented.
- `KpiV1`: per-platform metric with integer target ≥ 0 and horizon ∈
  {30, 60, 90} days — **no cross-platform metric equivalence is
  representable** (a KPI always names one platform).
- `FunnelStageV1`: ordered stages referencing known KPIs; duplicate order
  rejected.
- `StrategyPlanV1`: exactly the three horizons 30/60/90, each with
  non-empty goals — the PRD cadence as a key-set contract.
- `ExperimentV1`: hypothesis + platform + `min_sample` (≥ the 100 floor) +
  `observed_sample`; `winner_declared=True` requires
  `observed_sample ≥ min_sample` — **no winner claims from inadequate
  samples**, structurally.
- Sealed `AudienceStrategySetV1` (`create_audience_strategy_set_v1`):
  unique ids, closed cross-references, projections only; no
  publish/schedule/dispatch surface (machine-asserted).

## Acceptance criteria

1. [ ] Contracts as designed; default-off; hermetic.
2. [ ] Anti-fabrication: uncited claims, claimless segments → rejected.
3. [ ] 30/60/90 key-set enforced; missing/extra horizons rejected.
4. [ ] Per-platform KPIs only; funnel references closed; dup order rejected.
5. [ ] Experiment sample floor + winner gate enforced.
6. [ ] Entry-bind to slice-4 tuple; ≥34 adversarial tests; 32-file gate
       (A9.4's selection + this file) after the A9.4 seal; standard chain +
       E6 with the autonomous-session honesty boundary.
7. [ ] Matrix/ledger updates in the following documentation-authority pass.

## Out of scope

Publishing/scheduling (later gated slices), live provider reads
(BLOCKED_BY_ACCESS), paid media, analytics ingestion, runtime wiring.

## File List

- `docs/stories/ONYX-P10-AUDIENCE-STRATEGY-V1.story.md` (this story)

## Change Log

- 2026-08-18: Opened while the R15B soak (attempt 2) runs; gates queued
  behind the A9.4 seal.
