# ADR-0046 — Phase 9 opportunity scoring V1

## Status

Proposed (candidate E1–E5 complete, E6 pending).

## Context

Phase 9 item 3 of the Onyx PRD requires transparent opportunity scoring across
pain/economic cost, urgency, buyer/payability, timing, competition, Cyryx
advantage, time to MVP/revenue, complexity, distribution, moat, legal/platform
risk and evidence confidence. The scoring must be transparent (auditable, not a
black box) and must never itself take an action — in particular the PRD forbids
turning geopolitical or financial signals into autonomous trades.

This is the second Phase 9 slice, following the accepted intelligence ingestion
contract. It must be additive, exactly default-off, and side-effect-free.

## Decision

Add a pure deterministic, default-off `phase9-opportunity-scoring-v1` contract
behind the exact flag `ONYX_PHASE9_OPPORTUNITY_SCORING_V1`. It scores an
opportunity from twelve integer dimension scores (each `0..5`) using a fixed,
documented weight per dimension and an explicit benefit/cost direction. Benefit
dimensions reward a high raw score; cost/risk dimensions (competition, time to
MVP/revenue, complexity, legal/platform risk) reward a low raw score by scoring
their inverted value `SCORE_MAX - raw`. The weighted points are summed and
normalised with deterministic integer half-up rounding to a `0..100` total,
mapped to a fixed band ladder (`watch < 40 ≤ consider < 60 ≤ pursue < 80 ≤
priority`). The result exposes the complete per-dimension breakdown (raw,
direction, effective value, weight, earned points and maximum points), a
`low_confidence` flag when evidence confidence is at or below its floor, and a
batch rank (total descending, `opportunity_id` ascending tie-break). Sessions
are built through a sealed factory that returns `None` when the flag is unset
and otherwise entry-binds to the accepted intelligence ingestion evidence by
SHA-256.

## Consequences

- Scoring is fully transparent: the total is reproducible from the returned
  breakdown, and the weights/directions are fixed constants, not model output.
- It calls no model, opens no network, persists nothing and takes no action; a
  score is advisory data only and can never trigger a trade or other side
  effect.
- The rounding is written in half-up form for correctness under future weight
  changes; at the fixed V1 weight scale (maximum 140 points) an exact half-value
  cannot occur, so in practice it reduces to nearest-integer rounding.
- Live source ingestion, model-assisted or learned weighting, opportunity
  clustering and any autonomous acting on a score are out of scope for later
  gated successors.
- The result is default-off and unwired: no startup, voice, UI or dashboard path
  constructs it.

## Alternatives considered

- Learned or model-assigned weights: rejected — fixed transparent weights are
  auditable and testable and keep the slice model-free; a learned successor
  would need its own evaluation and governance.
- Floating-point normalisation: rejected in favour of integer half-up rounding
  so the total is byte-identical across platforms and fully deterministic.
- Treating evidence confidence as a hard cap on the total: rejected for V1 in
  favour of a transparent weighted contribution plus an explicit
  `low_confidence` flag, leaving cap policy to a later successor.
